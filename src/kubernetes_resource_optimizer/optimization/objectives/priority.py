"""Data-only limit priorities; these coefficients never depend on MILP variables."""

from dataclasses import dataclass
from math import fsum

from kubernetes_resource_optimizer.data.models import InputData, Resource
from kubernetes_resource_optimizer.optimization.bounds import BoundKey
from kubernetes_resource_optimizer.optimization.config import OptimizationConfig

# Convex mixing of two [0, 1] indicators. Neither preference discards the other.
STEADY_SHARES = {-2: 0.9, -1: 0.75, 0: 0.5, 1: 0.25, 2: 0.1}
PROXIMITY_REGULARIZATION = 0.1


@dataclass(frozen=True, slots=True)
class LimitPriority:
    """Inspectable historical threshold and dimensionless limit reward."""

    request_reference: float
    steady_score: float
    spike_score: float
    weight: float


def derive_limit_priorities(
    data: InputData, config: OptimizationConfig
) -> dict[BoundKey, LimitPriority]:
    """Derive objective weights and the implied request coverage floor.

    The chance constraints remain in the MILP. Service replicas share the
    largest reference in their group, matching their common request floor.
    Rank splitting handles ties deterministically; epsilon=1 has reference zero.
    Empty tails score zero; all-zero histories score zero in both components.
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

    group_reference: dict[tuple[str, Resource], float] = {}
    for pod in data.pods:
        if pod.service_id is not None:
            for resource in Resource:
                key = pod.service_id, resource
                group_reference[key] = max(
                    group_reference.get(key, 0.0), references[pod.pod_id, resource]
                )
    for pod in data.pods:
        if pod.service_id is not None:
            for resource in Resource:
                references[pod.pod_id, resource] = group_reference[
                    pod.service_id, resource
                ]

    priorities: dict[BoundKey, LimitPriority] = {}
    share = STEADY_SHARES[config.limit_priority]
    for key, values in histories.items():
        reference = references[key]
        scale = max(reference, values[-1])
        lower, upper = values[: splits[key]], values[splits[key] :]
        steady = spike = 0.0
        if scale > 0:
            if lower:
                # Divide before averaging to avoid overflow for large finite data.
                gap = max(
                    0.0, reference / scale - fsum(v / scale for v in lower) / len(lower)
                )
                steady = PROXIMITY_REGULARIZATION / (PROXIMITY_REGULARIZATION + gap)
            if upper:
                spike = fsum(max(0.0, v - reference) / scale for v in upper) / len(
                    upper
                )
        priorities[key] = LimitPriority(
            reference, steady, spike, share * steady + (1 - share) * spike
        )
    return priorities
