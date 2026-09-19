"""Read current per-container allocations from a local monitoring snapshot."""

import math
from pathlib import Path

from kubernetes_resource_optimizer.utils.ocp_usage_to_csv import (
    ConversionError,
    _load_json,
)

_PREFIX = "kube_pod_container_"


def load_current_resources(path: Path) -> dict[str, dict[str, float]]:
    """Sum only complete pod allocations; missing limits are not zero limits."""
    document = _load_json(path)
    if (
        not isinstance(document, dict)
        or document.get("status") != "success"
        or not isinstance(document.get("data"), dict)
        or document["data"].get("resultType") != "vector"
        or not isinstance(document["data"].get("result"), list)
    ):
        raise ConversionError(f"{path}: expected a successful current-resource vector")
    containers: dict[str, set[str]] = {}
    allocations: dict[tuple[str, str, str], float] = {}
    namespaces: set[str] = set()
    for series in document["data"]["result"]:
        if not isinstance(series, dict) or not isinstance(series.get("metric"), dict):
            raise ConversionError(f"{path}: invalid resource series")
        metric = series["metric"]
        for label in ("__name__", "namespace", "pod", "container"):
            if not isinstance(metric.get(label), str) or not metric[label].strip():
                raise ConversionError(f"{path}: missing {label} label")
        namespaces.add(metric["namespace"])
        if len(namespaces) > 1:
            raise ConversionError(f"{path}: current resources span multiple namespaces")
        sample = series.get("value")
        if not isinstance(sample, list) or len(sample) != 2:
            raise ConversionError(f"{path}: expected [timestamp, value]")
        try:
            timestamp, value = map(float, sample)
        except (TypeError, ValueError) as error:
            raise ConversionError(f"{path}: invalid resource value") from error
        if not math.isfinite(timestamp) or not math.isfinite(value) or value < 0:
            raise ConversionError(f"{path}: resource values must be finite and nonnegative")
        pod, container = metric["pod"], metric["container"]
        name = metric["__name__"]
        if name == _PREFIX + "info":
            if value > 0:
                containers.setdefault(pod, set()).add(container)
            continue
        if name not in (_PREFIX + "resource_requests", _PREFIX + "resource_limits"):
            raise ConversionError(f"{path}: unexpected resource metric {name!r}")
        resource = metric.get("resource")
        if resource not in ("cpu", "memory"):
            continue
        expected_unit = "core" if resource == "cpu" else "byte"
        if metric.get("unit") != expected_unit:
            raise ConversionError(f"{path}: expected unit={expected_unit!r} for {resource}")
        kind = "request" if name.endswith("requests") else "limit"
        key = (pod, container, f"current_{resource}_{kind}")
        value = value if resource == "cpu" else value / (1024 * 1024)
        if key in allocations and allocations[key] != value:
            raise ConversionError(f"{path}: conflicting current allocations for {key}")
        allocations[key] = value

    result: dict[str, dict[str, float]] = {}
    for pod, members in containers.items():
        fields: dict[str, float] = {}
        for resource in ("cpu", "memory"):
            for kind in ("request", "limit"):
                field = f"current_{resource}_{kind}"
                keys = [(pod, member, field) for member in members]
                if all(key in allocations for key in keys):
                    try:
                        total = math.fsum(allocations[key] for key in keys)
                    except OverflowError as error:
                        raise ConversionError(
                            f"{path}: allocation total overflow for {pod}"
                        ) from error
                    if not math.isfinite(total):
                        raise ConversionError(f"{path}: non-finite allocation total for {pod}")
                    fields[field] = total
        result[pod] = fields
    return result
