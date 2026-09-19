"""Resolve controller identities from local kube-state-metrics matrix exports."""

from pathlib import Path

from kubernetes_resource_optimizer.utils.ocp_usage_to_csv import (
    ConversionError,
    _load_json,
    parse_matrix_export,
)


def _owners(path: Path, child_label: str) -> dict[str, tuple[str, str]]:
    document = _load_json(path)
    if (
        not isinstance(document, dict)
        or document.get("status") != "success"
        or not isinstance(document.get("data"), dict)
        or document["data"].get("resultType") != "matrix"
        or not isinstance(document["data"].get("result"), list)
    ):
        raise ConversionError(f"{path}: expected a successful owner matrix")
    owners: dict[str, tuple[str, str]] = {}
    namespaces: set[str] = set()
    for series in document["data"]["result"]:
        observations = parse_matrix_export(
            {"status": "success", "data": {"resultType": "matrix", "result": [series]}},
            source=str(path), metric_label=child_label,
        )
        metric = series["metric"]
        if metric.get("owner_is_controller") != "true":
            continue
        if not any(value > 0 for value in observations.values()):
            continue
        labels = ("namespace", "owner_kind", "owner_name")
        if any(not isinstance(metric.get(label), str) or not metric[label].strip()
               for label in labels):
            raise ConversionError(f"{path}: owner series has missing identity labels")
        namespaces.add(metric["namespace"])
        if len(namespaces) > 1:
            raise ConversionError(f"{path}: owner export contains multiple namespaces")
        child = next(iter(observations)).workload_id
        owner = (metric["owner_kind"], metric["owner_name"])
        if child in owners and owners[child] != owner:
            raise ConversionError(f"{path}: ambiguous historical owners for {child!r}")
        owners[child] = owner
    return owners


def resolve_services(pod_owners: Path, replicaset_owners: Path) -> dict[str, str]:
    """Use controller ownership, never pod-name suffix guesses or Service selectors."""
    pods = _owners(pod_owners, "pod")
    replicasets = _owners(replicaset_owners, "replicaset")
    services: dict[str, str] = {}
    for pod, owner in pods.items():
        if owner[0] == "ReplicaSet":
            owner = replicasets.get(owner[1], owner)
        services[pod] = f"{owner[0]}/{owner[1]}"
    return services
