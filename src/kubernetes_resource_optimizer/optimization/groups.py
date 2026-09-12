"""Deterministic service groups with collision-free independent singletons."""

from collections import defaultdict

from kubernetes_resource_optimizer.data.models import InputData, Pod


def replica_groups(data: InputData) -> tuple[tuple[Pod, ...], ...]:
    groups: defaultdict[tuple[bool, str], list[Pod]] = defaultdict(list)
    for pod in data.pods:
        key = (
            (True, pod.service_id)
            if pod.service_id is not None
            else (False, pod.pod_id)
        )
        groups[key].append(pod)
    return tuple(
        tuple(sorted(members, key=lambda pod: pod.pod_id))
        for members in groups.values()
    )
