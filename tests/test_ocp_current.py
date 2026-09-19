"""Current allocation snapshots must not invent or double-count pod totals."""

import json
from pathlib import Path

import pytest

from kubernetes_resource_optimizer.utils.ocp_current import load_current_resources
from kubernetes_resource_optimizer.utils.ocp_usage_to_csv import ConversionError


def _sample(
    container: str, kind: str = "info", resource: str = "cpu", value: str = "1",
) -> dict[str, object]:
    return {
        "metric": {"__name__": f"kube_pod_container_{kind}", "pod": "api-a",
                   "container": container, "namespace": "demo", "resource": resource,
                   "unit": "core" if resource == "cpu" else "byte"},
        "value": [1787562000, value],
    }


def _write(tmp_path: Path, rows: list[dict[str, object]]) -> Path:
    path = tmp_path / "current.json"
    path.write_text(json.dumps({
        "status": "success", "data": {"resultType": "vector", "result": rows},
    }))
    return path


def test_sums_all_containers_deduplicates_and_converts_memory(tmp_path: Path) -> None:
    rows = []
    for container in ("app", "sidecar"):
        rows.append(_sample(container))
        for kind in ("resource_requests", "resource_limits"):
            for resource, value in (("cpu", "0.125"), ("memory", "1048576")):
                rows.append(_sample(container, kind, resource, value))
    path = _write(tmp_path, rows + rows)
    assert load_current_resources(path) == {"api-a": {
        "current_cpu_request": 0.25, "current_cpu_limit": 0.25,
        "current_memory_request": 2, "current_memory_limit": 2,
    }}


def test_incomplete_limits_remain_missing_and_explicit_zero_is_preserved(tmp_path: Path) -> None:
    path = _write(tmp_path, [
        _sample("app"), _sample("sidecar"),
        _sample("app", "resource_limits", value="2"),
        _sample("app", "resource_requests", value="0"),
        _sample("sidecar", "resource_requests", value="0"),
    ])
    assert load_current_resources(path) == {"api-a": {"current_cpu_request": 0}}


def test_empty_snapshot_or_missing_inventory_does_not_invent_totals(tmp_path: Path) -> None:
    assert load_current_resources(_write(tmp_path, [])) == {}
    assert load_current_resources(_write(tmp_path, [
        _sample("app", "resource_limits"),
    ])) == {}


@pytest.mark.parametrize("value", ["NaN", "inf", "-1", "oops"])
def test_rejects_invalid_resources(tmp_path: Path, value: str) -> None:
    with pytest.raises(ConversionError):
        load_current_resources(_write(tmp_path, [_sample("app", value=value)]))


def test_conflicting_scrape_values_fail(tmp_path: Path) -> None:
    with pytest.raises(ConversionError, match="conflicting current allocations"):
        load_current_resources(_write(tmp_path, [
            _sample("app", "resource_requests", value="1"),
            _sample("app", "resource_requests", value="2"),
        ]))
