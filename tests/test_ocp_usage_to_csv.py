import csv
import json
from pathlib import Path

import pytest

from kubernetes_resource_optimizer.utils.ocp_usage_to_csv import (
    ConversionError,
    convert_directory,
    convert_exports,
)


def _export(pod: str, values: list[list[object]]) -> dict[str, object]:
    return {
        "status": "success",
        "data": {
            "resultType": "matrix",
            "result": [{"metric": {"pod": pod}, "values": values}],
            "analysis": {},
        },
    }


def _write_json(path: Path, document: dict[str, object]) -> None:
    path.write_text(json.dumps(document), encoding="utf-8")


def test_keeps_cores_and_converts_bytes_to_canonical_units(tmp_path: Path) -> None:
    cpu_path = tmp_path / "cpu.json"
    memory_path = tmp_path / "memory.json"
    output_path = tmp_path / "usage.csv"
    _write_json(cpu_path, _export("pod1", [[1787562000, "0.385790345098765"]]))
    _write_json(memory_path, _export("pod1", [[1787562000, "536870912"]]))

    assert convert_exports(cpu_path, memory_path, output_path) == 1

    with output_path.open(encoding="utf-8", newline="") as stream:
        rows = list(csv.DictReader(stream))
    assert rows == [
        {
            "timestamp": "2026-08-24T09:00:00Z",
            "workload_id": "pod1",
            "cpu_usage": "0.385790345098765",
            "memory_usage": "512",
        }
    ]


def test_can_explicitly_convert_nanocores(tmp_path: Path) -> None:
    cpu_path = tmp_path / "cpu.json"
    memory_path = tmp_path / "memory.json"
    output_path = tmp_path / "usage.csv"
    _write_json(cpu_path, _export("pod1", [[1787562000, "385790345.098765"]]))
    _write_json(memory_path, _export("pod1", [[1787562000, "512"]]))

    convert_exports(
        cpu_path,
        memory_path,
        output_path,
        cpu_unit="nanocores",
        memory_unit="mib",
    )

    with output_path.open(encoding="utf-8", newline="") as stream:
        row = next(csv.DictReader(stream))
    assert row["cpu_usage"] == "0.385790345098765"
    assert row["memory_usage"] == "512"


def test_rejects_unaligned_exports(tmp_path: Path) -> None:
    cpu_path = tmp_path / "cpu.json"
    memory_path = tmp_path / "memory.json"
    _write_json(cpu_path, _export("pod1", [[1787562000, "1"]]))
    _write_json(memory_path, _export("pod1", [[1787565600, "1"]]))

    with pytest.raises(ConversionError, match="not aligned"):
        convert_exports(cpu_path, memory_path, tmp_path / "usage.csv")


def test_rejects_duplicate_pod_timestamp_observations(tmp_path: Path) -> None:
    cpu_path = tmp_path / "cpu.json"
    memory_path = tmp_path / "memory.json"
    duplicate = _export("pod1", [[1787562000, "1"], [1787562000, "2"]])
    _write_json(cpu_path, duplicate)
    _write_json(memory_path, duplicate)

    with pytest.raises(ConversionError, match="duplicate observation"):
        convert_exports(cpu_path, memory_path, tmp_path / "usage.csv")


def test_combines_all_named_pairs_from_directory(tmp_path: Path) -> None:
    input_dir = tmp_path / "json"
    input_dir.mkdir()
    _write_json(input_dir / "pod1-cpu.json", _export("pod1", [[1787562000, "0.5"]]))
    _write_json(
        input_dir / "pod1-mem.json", _export("pod1", [[1787562000, "1048576"]])
    )
    _write_json(input_dir / "pod2-cpu.json", _export("pod2", [[1787562000, "0.7"]]))
    _write_json(
        input_dir / "pod2-mem.json", _export("pod2", [[1787562000, "2097152"]])
    )
    output_path = tmp_path / "usage.csv"

    assert convert_directory(input_dir, output_path) == 2

    with output_path.open(encoding="utf-8", newline="") as stream:
        rows = list(csv.DictReader(stream))
    assert [row["workload_id"] for row in rows] == ["pod1", "pod2"]
    assert [row["cpu_usage"] for row in rows] == ["0.5", "0.7"]
    assert [row["memory_usage"] for row in rows] == ["1", "2"]


def test_directory_rejects_missing_resource_pair(tmp_path: Path) -> None:
    input_dir = tmp_path / "json"
    input_dir.mkdir()
    _write_json(input_dir / "pod1-cpu.json", _export("pod1", [[1787562000, "0.5"]]))

    with pytest.raises(ConversionError, match="missing JSON pairs"):
        convert_directory(input_dir, tmp_path / "usage.csv")


def test_writes_kro_workloads_for_observed_pods(tmp_path: Path) -> None:
    from kubernetes_resource_optimizer.data.csv_loader import load_pods_csv
    from kubernetes_resource_optimizer.utils.ocp_usage_to_csv import main

    for pod in ("pod-b", "pod-a"):
        for resource in ("cpu", "mem"):
            _write_json(
                tmp_path / f"{pod}-{resource}.json",
                _export(pod, [[1787562000, "1"], [1787565600, "2"]]),
            )
    workloads = tmp_path / "workload.csv"
    assert main([
        "--input-dir", str(tmp_path), "--output", str(tmp_path / "usage.csv"),
        "--workloads-output", str(workloads),
    ]) == 0
    pods = load_pods_csv(workloads)
    assert [pod.pod_id for pod in pods] == ["pod-a", "pod-b"]
    assert all(pod.service_id is None for pod in pods)
    assert all(pod.cpu_limit_max is None for pod in pods)
    assert all(pod.current_cpu_request is None for pod in pods)


def test_rejects_different_histories_between_pods(tmp_path: Path) -> None:
    for pod, timestamp in (("pod-a", 1787562000), ("pod-b", 1787565600)):
        for resource in ("cpu", "mem"):
            _write_json(
                tmp_path / f"{pod}-{resource}.json", _export(pod, [[timestamp, "1"]])
            )
    with pytest.raises(ConversionError, match="pod histories are not aligned"):
        convert_directory(
            tmp_path, tmp_path / "usage.csv",
            workloads_output=tmp_path / "workload.csv",
        )
    assert not (tmp_path / "usage.csv").exists()
    assert not (tmp_path / "workload.csv").exists()
