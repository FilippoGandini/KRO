"""Offline tests of controller mapping and generated KRO pod CSVs."""

import csv
import json
from pathlib import Path

import pytest

from kubernetes_resource_optimizer.utils.ocp_owners import resolve_services
from kubernetes_resource_optimizer.utils.ocp_usage_to_csv import ConversionError, main


def _series(child: str, name: str, kind: str, owner: str) -> dict[str, object]:
    return {
        "metric": {
            child: name, "namespace": "example", "owner_kind": kind,
            "owner_name": owner, "owner_is_controller": "true",
        },
        "values": [[1787562000, "1"]],
    }


def _write(path: Path, series: list[dict[str, object]]) -> Path:
    path.write_text(json.dumps({
        "status": "success", "data": {"resultType": "matrix", "result": series},
    }))
    return path


def test_resolves_replicas_across_rollouts_and_direct_controllers(tmp_path: Path) -> None:
    pods = _write(tmp_path / "pod-owners.json", [
        _series("pod", "api-old-a", "ReplicaSet", "api-old"),
        _series("pod", "api-new-b", "ReplicaSet", "api-new"),
        _series("pod", "db-0", "StatefulSet", "db"),
        _series("pod", "standalone-a", "ReplicaSet", "standalone"),
        _series("pod", "legacy-a", "ReplicationController", "legacy"),
    ])
    rs = _series("replicaset", "api-old", "Deployment", "api")
    replicasets = _write(tmp_path / "replicaset-owners.json", [
        rs, rs, _series("replicaset", "api-new", "Deployment", "api"),
    ])
    assert resolve_services(pods, replicasets) == {
        "api-old-a": "Deployment/api", "api-new-b": "Deployment/api",
        "db-0": "StatefulSet/db", "standalone-a": "ReplicaSet/standalone",
        "legacy-a": "ReplicationController/legacy",
    }


@pytest.mark.parametrize("conflicting_rs", [False, True])
def test_rejects_ambiguous_historical_owners(tmp_path: Path, conflicting_rs: bool) -> None:
    pod_series = [_series("pod", "api-a", "ReplicaSet", "api")]
    rs_series = [_series("replicaset", "api", "Deployment", "api")]
    if conflicting_rs:
        rs_series.append(_series("replicaset", "api", "Deployment", "other"))
    else:
        pod_series.append(_series("pod", "api-a", "StatefulSet", "other"))
    with pytest.raises(ConversionError, match="ambiguous historical owners"):
        resolve_services(
            _write(tmp_path / "pods.json", pod_series),
            _write(tmp_path / "rs.json", rs_series),
        )


def test_empty_owner_exports_leave_pods_independent(tmp_path: Path) -> None:
    assert resolve_services(
        _write(tmp_path / "pods.json", []), _write(tmp_path / "rs.json", [])
    ) == {}


def test_ignores_noncontroller_and_inactive_owner_series(tmp_path: Path) -> None:
    noncontroller = _series("pod", "a", "Deployment", "ignored")
    noncontroller["metric"] = {
        "pod": "a", "owner_is_controller": "false",
    }
    inactive = _series("pod", "a", "Deployment", "inactive")
    inactive["values"] = [[1787562000, "0"]]
    assert resolve_services(
        _write(tmp_path / "pods.json", [noncontroller, inactive]),
        _write(tmp_path / "rs.json", []),
    ) == {}


def test_cli_populates_only_observed_pods(tmp_path: Path) -> None:
    for resource in ("cpu", "mem"):
        _write(tmp_path / f"a-{resource}.json", [{
            "metric": {"pod": "a"}, "values": [[1787562000, "1"]],
        }])
    pods = _write(tmp_path / "pod-owners.json", [
        _series("pod", "a", "ReplicaSet", "api-rs"),
        _series("pod", "unobserved", "StatefulSet", "db"),
    ])
    replicasets = _write(tmp_path / "replicaset-owners.json", [
        _series("replicaset", "api-rs", "Deployment", "api"),
    ])
    output = tmp_path / "pods.csv"
    assert main([
        "--input-dir", str(tmp_path), "--output", str(tmp_path / "usage.csv"),
        "--pods-output", str(output), "--pod-owners", str(pods),
        "--replicaset-owners", str(replicasets),
    ]) == 0
    with output.open() as stream:
        rows = list(csv.DictReader(stream))
    assert len(rows) == 1
    assert rows[0]["pod_id"] == "a"
    assert rows[0]["service_id"] == "Deployment/api"


@pytest.mark.parametrize("value", ["NaN", "-1", "inf"])
def test_rejects_invalid_owner_values(tmp_path: Path, value: str) -> None:
    series = _series("pod", "a", "Deployment", "api")
    series["values"] = [[1787562000, value]]
    with pytest.raises(ConversionError):
        resolve_services(
            _write(tmp_path / "pods.json", [series]),
            _write(tmp_path / "rs.json", []),
        )
