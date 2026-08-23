"""Deterministic derivation of finite MILP bounds and Big-M parameters."""

import math
from dataclasses import dataclass
from decimal import ROUND_FLOOR, Decimal

from kubernetes_resource_optimizer.data.models import (
    InputData,
    Node,
    Pod,
    Resource,
    UsageSample,
)

BoundKey = tuple[str, Resource]


@dataclass(frozen=True, slots=True)
class DerivedBounds:
    """Workload/resource indexed parameters required by the future MILP."""

    request_upper: dict[BoundKey, float]
    limit_upper: dict[BoundKey, float]
    request_big_m: dict[BoundKey, float]
    limit_big_m: dict[BoundKey, float]


def _node_capacity(node: Node, resource: Resource) -> float:
    return node.cpu_capacity if resource is Resource.CPU else node.memory_capacity


def _pod_bound(pod: Pod, resource: Resource, *, request: bool) -> float | None:
    if resource is Resource.CPU:
        return pod.cpu_request_max if request else pod.cpu_limit_max
    return pod.memory_request_max if request else pod.memory_limit_max


def _usage(sample: UsageSample, resource: Resource) -> float:
    return sample.cpu_usage if resource is Resource.CPU else sample.memory_usage


def _validate_bound(value: float, name: str) -> float:
    if not math.isfinite(value) or value < 0:
        raise ValueError(f"{name} must be finite and non-negative")
    return value


def _maximum_node_capacity(nodes: tuple[Node, ...], resource: Resource) -> float:
    if not nodes:
        raise ValueError("at least one candidate node is required to derive bounds")
    capacities = [_validate_bound(_node_capacity(node, resource), "node capacity") for node in nodes]
    return max(capacities)


def derive_request_upper_bound(
    pod: Pod, nodes: tuple[Node, ...], resource: Resource
) -> float:
    """Derive R_max[i,h].

    A supplied workload-specific request maximum is the tight bound. Otherwise,
    the safe fallback is the maximum candidate-node capacity for the resource.
    """

    supplied = _pod_bound(pod, resource, request=True)
    if supplied is not None:
        return _validate_bound(supplied, "request upper bound")
    return _maximum_node_capacity(nodes, resource)


def derive_limit_upper_bound(
    pod: Pod, nodes: tuple[Node, ...], resource: Resource
) -> float:
    """Derive L_max[i,h] using a supplied maximum or maximum node capacity."""

    supplied = _pod_bound(pod, resource, request=False)
    if supplied is not None:
        return _validate_bound(supplied, "limit upper bound")
    return _maximum_node_capacity(nodes, resource)


def _derive_big_m(
    pod_id: str, usage_samples: tuple[UsageSample, ...], resource: Resource
) -> float:
    """Return max_t u[i,t,h], valid and tight given a zero lower bound."""

    values = [
        _validate_bound(_usage(sample, resource), "historical utilization")
        for sample in usage_samples
        if sample.pod_id == pod_id
    ]
    if not values:
        raise ValueError(f"pod {pod_id!r} has no usage samples")
    return max(values)


def derive_request_big_m(
    pod_id: str, usage_samples: tuple[UsageSample, ...], resource: Resource
) -> float:
    """Derive M_request[i,h] as max_t u[i,t,h]."""

    return _derive_big_m(pod_id, usage_samples, resource)


def derive_limit_big_m(
    pod_id: str, usage_samples: tuple[UsageSample, ...], resource: Resource
) -> float:
    """Derive M_limit[i,h] as max_t u[i,t,h]."""

    return _derive_big_m(pod_id, usage_samples, resource)


def maximum_violation_count(epsilon: float, scenario_count: int) -> int:
    """Return floor(epsilon * |T|) without binary floating-point drift."""

    if not math.isfinite(epsilon) or not 0 <= epsilon <= 1:
        raise ValueError("epsilon must be finite and between 0 and 1")
    if isinstance(scenario_count, bool) or not isinstance(scenario_count, int):
        raise TypeError("scenario_count must be an integer")
    if scenario_count < 0:
        raise ValueError("scenario_count must be non-negative")
    product = Decimal(str(epsilon)) * Decimal(scenario_count)
    return int(product.to_integral_value(rounding=ROUND_FLOOR))


def derive_bounds(data: InputData) -> DerivedBounds:
    """Derive every R_max, L_max, M_request, and M_limit parameter."""

    request_upper: dict[BoundKey, float] = {}
    limit_upper: dict[BoundKey, float] = {}
    request_big_m: dict[BoundKey, float] = {}
    limit_big_m: dict[BoundKey, float] = {}
    for pod in data.pods:
        for resource in Resource:
            key = (pod.pod_id, resource)
            request_upper[key] = derive_request_upper_bound(pod, data.nodes, resource)
            limit_upper[key] = derive_limit_upper_bound(pod, data.nodes, resource)
            request_big_m[key] = derive_request_big_m(
                pod.pod_id, data.usage_samples, resource
            )
            limit_big_m[key] = derive_limit_big_m(
                pod.pod_id, data.usage_samples, resource
            )
    return DerivedBounds(
        request_upper=request_upper,
        limit_upper=limit_upper,
        request_big_m=request_big_m,
        limit_big_m=limit_big_m,
    )
