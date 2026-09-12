"""Exact empirical coverage requests and sorted historical observations."""

from dataclasses import dataclass

from kubernetes_resource_optimizer.data.models import InputData, Resource
from kubernetes_resource_optimizer.optimization.bounds import BoundKey
from kubernetes_resource_optimizer.optimization.config import OptimizationConfig
from kubernetes_resource_optimizer.optimization.groups import replica_groups


@dataclass(frozen=True, slots=True)
class HistoricalParameters:
    """Named input-derived quantities, independent of objective construction."""

    sorted_usage: dict[BoundKey, list[float]]
    coverage_splits: dict[BoundKey, int]
    requests: dict[BoundKey, float]
    peaks: dict[BoundKey, float]


def derive_history_parameters(
    data: InputData, config: OptimizationConfig
) -> HistoricalParameters:
    """Use u_(N-floor(epsilon*N)), or zero if every observation may be exceeded.

    Ties use ranks without interpolation. Service replicas receive the largest
    individual coverage floor; missing service IDs remain independent.
    """
    histories: dict[BoundKey, list[float]] = {
        (pod.pod_id, resource): [] for pod in data.pods for resource in Resource
    }
    for sample in data.usage_samples:
        histories[sample.pod_id, Resource.CPU].append(sample.cpu_usage)
        histories[sample.pod_id, Resource.MEMORY].append(sample.memory_usage)
    references: dict[BoundKey, float] = {}
    splits: dict[BoundKey, int] = {}
    for key, values in histories.items():
        values.sort()
        if not values:
            raise ValueError(f"pod {key[0]!r} has no history")
        split = len(values) - config.maximum_request_violations(key[1], len(values))
        splits[key] = split
        references[key] = values[split - 1] if split else 0.0

    for members in replica_groups(data):
        for resource in Resource:
            shared_request = max(references[pod.pod_id, resource] for pod in members)
            for pod in members:
                references[pod.pod_id, resource] = shared_request

    return HistoricalParameters(
        sorted_usage=histories,
        coverage_splits=splits,
        requests=references,
        peaks={key: values[-1] for key, values in histories.items()},
    )
