from pathlib import Path

import pytest

from kubernetes_resource_optimizer.data.csv_loader import load_input_data
from kubernetes_resource_optimizer.data.validation import InputValidationError


def write_inputs(
    tmp_path: Path,
    *,
    nodes: str = "node_id,cpu_capacity,memory_capacity\nnode-1,8,32768\n",
    pods: str = "pod_id\npod-a\npod-b\n",
    usage: str = (
        "timestamp,pod_id,cpu_usage,memory_usage\n"
        "2026-08-01T10:00:00Z,pod-a,250m,512MiB\n"
        "2026-08-01T11:00:00Z,pod-a,0.31,530\n"
        "2026-08-01T10:00:00Z,pod-b,1.20,2GiB\n"
        "2026-08-01T11:00:00Z,pod-b,0.90,1980\n"
    ),
) -> tuple[Path, Path, Path]:
    paths = (tmp_path / "nodes.csv", tmp_path / "pods.csv", tmp_path / "usage.csv")
    for path, content in zip(paths, (nodes, pods, usage), strict=True):
        path.write_text(content, encoding="utf-8")
    return paths


def load(tmp_path: Path, **overrides: str):
    return load_input_data(*write_inputs(tmp_path, **overrides))


def test_loads_valid_inputs_and_converts_units(tmp_path: Path) -> None:
    pods = (
        "pod_id,service_id,current_cpu_request,current_memory_request,cpu_request_max,memory_limit_max\n"
        "pod-a,api,500m,1GiB,2,4GiB\n"
        "pod-b,api,,,,\n"
    )

    data = load(tmp_path, pods=pods)

    assert data.nodes[0].cpu_capacity == 8.0
    assert data.nodes[0].memory_capacity == 32768.0
    assert data.nodes[0].cost == 1.0
    assert data.pods[0].current_cpu_request == 0.5
    assert data.pods[0].service_id == "api"
    assert data.pods[1].replica_group_id == "api"
    assert data.pods[0].current_memory_request == 1024.0
    assert data.pods[0].memory_limit_max == 4096.0
    assert data.pods[1].current_cpu_request is None
    assert data.usage_samples[0].cpu_usage == 0.25
    assert data.usage_samples[2].memory_usage == 2048.0


def test_loads_node_cost(tmp_path: Path) -> None:
    data = load(
        tmp_path,
        nodes="node_id,cpu_capacity,memory_capacity,cost\nnode-1,8,32768,0.125\n",
    )

    assert data.nodes[0].cost == pytest.approx(0.125)


@pytest.mark.parametrize("input_name", ["pods", "usage"])
def test_requires_pod_id_column(tmp_path: Path, input_name: str) -> None:
    csv = (
        "service_id\napi\n" if input_name == "pods"
        else "timestamp,cpu_usage,memory_usage\n2026-08-01T10:00:00Z,1,128\n"
    )
    with pytest.raises(InputValidationError, match="missing required columns: pod_id"):
        load(tmp_path, **{input_name: csv})


@pytest.mark.parametrize("cost", ["0", "-1", "nan", "inf"])
def test_rejects_non_positive_or_non_finite_node_cost(
    tmp_path: Path, cost: str
) -> None:
    nodes = f"node_id,cpu_capacity,memory_capacity,cost\nnode-1,8,32768,{cost}\n"

    with pytest.raises(InputValidationError, match="cost must be finite and positive"):
        load(tmp_path, nodes=nodes)


def test_missing_or_empty_service_id_creates_singleton_groups(tmp_path: Path) -> None:
    data_without_column = load(tmp_path)
    data_with_empty_values = load(
        tmp_path,
        pods="pod_id,service_id\npod-a,\npod-b,   \n",
    )

    assert [pod.replica_group_id for pod in data_without_column.pods] == [
        "pod-a",
        "pod-b",
    ]
    assert [pod.replica_group_id for pod in data_with_empty_values.pods] == [
        "pod-a",
        "pod-b",
    ]


@pytest.mark.parametrize(
    ("overrides", "message"),
    [
        (
            {
                "nodes": "node_id,cpu_capacity,memory_capacity\nnode-1,8,32768\nnode-1,4,8192\n"
            },
            "duplicate node_id",
        ),
        (
            {"pods": "pod_id\npod-a\npod-a\n"},
            "duplicate pod_id",
        ),
    ],
)
def test_rejects_duplicate_ids(
    tmp_path: Path, overrides: dict[str, str], message: str
) -> None:
    with pytest.raises(InputValidationError, match=message):
        load(tmp_path, **overrides)


def test_rejects_duplicate_usage_samples(tmp_path: Path) -> None:
    usage = (
        "timestamp,pod_id,cpu_usage,memory_usage\n"
        "2026-08-01T10:00:00Z,pod-a,0.25,512\n"
        "2026-08-01T10:00:00Z,pod-a,0.30,520\n"
        "2026-08-01T10:00:00Z,pod-b,0.50,1024\n"
    )
    with pytest.raises(InputValidationError, match="duplicate usage sample"):
        load(tmp_path, usage=usage)


def test_rejects_unknown_pod_id(tmp_path: Path) -> None:
    usage = (
        "timestamp,pod_id,cpu_usage,memory_usage\n"
        "2026-08-01T10:00:00Z,pod-a,0.25,512\n"
        "2026-08-01T10:00:00Z,pod-b,0.50,1024\n"
        "2026-08-01T10:00:00Z,pod-unknown,0.1,128\n"
    )
    with pytest.raises(InputValidationError, match="unknown pod_id 'pod-unknown'"):
        load(tmp_path, usage=usage)


@pytest.mark.parametrize("field,value", [("cpu_usage", "-0.1"), ("memory_usage", "-1")])
def test_rejects_negative_utilization(tmp_path: Path, field: str, value: str) -> None:
    row = {"cpu_usage": "0.1", "memory_usage": "128"}
    row[field] = value
    usage = (
        "timestamp,pod_id,cpu_usage,memory_usage\n"
        f"2026-08-01T10:00:00Z,pod-a,{row['cpu_usage']},{row['memory_usage']}\n"
        "2026-08-01T10:00:00Z,pod-b,0.2,256\n"
    )
    with pytest.raises(InputValidationError, match=f"invalid {field}"):
        load(tmp_path, usage=usage)


@pytest.mark.parametrize(
    ("overrides", "message"),
    [
        (
            {"nodes": "node_id,cpu_capacity,memory_capacity\nnode-1,,32768\n"},
            "missing value for cpu_capacity",
        ),
        (
            {"pods": "pod_id\n\n"},
            "pods.csv must contain at least one pod",
        ),
        (
            {
                "usage": (
                    "timestamp,pod_id,cpu_usage,memory_usage\n"
                    "2026-08-01T10:00:00Z,pod-a,,512\n"
                )
            },
            "missing value for cpu_usage",
        ),
    ],
)
def test_rejects_missing_values(
    tmp_path: Path, overrides: dict[str, str], message: str
) -> None:
    with pytest.raises(InputValidationError, match=message):
        load(tmp_path, **overrides)


@pytest.mark.parametrize("cpu,memory", [("0", "1024"), ("-1", "1024"), ("2", "0")])
def test_rejects_invalid_capacities(tmp_path: Path, cpu: str, memory: str) -> None:
    nodes = f"node_id,cpu_capacity,memory_capacity\nnode-1,{cpu},{memory}\n"
    with pytest.raises(InputValidationError, match="must be finite and positive"):
        load(tmp_path, nodes=nodes)


def test_rejects_inconsistent_scenario_timestamps(tmp_path: Path) -> None:
    usage = (
        "timestamp,pod_id,cpu_usage,memory_usage\n"
        "2026-08-01T10:00:00Z,pod-a,0.25,512\n"
        "2026-08-01T11:00:00Z,pod-a,0.30,520\n"
        "2026-08-01T10:00:00Z,pod-b,0.50,1024\n"
        "2026-08-01T12:00:00Z,pod-b,0.60,1100\n"
    )
    with pytest.raises(InputValidationError, match="inconsistent scenario timestamps"):
        load(tmp_path, usage=usage)


def test_rejects_pod_with_no_scenarios(tmp_path: Path) -> None:
    usage = (
        "timestamp,pod_id,cpu_usage,memory_usage\n2026-08-01T10:00:00Z,pod-a,0.25,512\n"
    )
    with pytest.raises(InputValidationError, match="pod-b.*has no usage samples"):
        load(tmp_path, usage=usage)


def test_rejects_timestamp_without_timezone(tmp_path: Path) -> None:
    usage = (
        "timestamp,pod_id,cpu_usage,memory_usage\n2026-08-01T10:00:00,pod-a,0.25,512\n"
    )
    with pytest.raises(
        InputValidationError, match="timestamp must include a UTC offset"
    ):
        load(tmp_path, usage=usage)
