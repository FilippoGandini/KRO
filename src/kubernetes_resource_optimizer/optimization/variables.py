"""Decision variables for the MILP model."""

from dataclasses import dataclass
from datetime import datetime

import pulp

from kubernetes_resource_optimizer.data.models import InputData, Resource
from kubernetes_resource_optimizer.optimization.bounds import BoundKey, DerivedBounds

PlacementKey = tuple[str, str]
ViolationKey = tuple[str, datetime, Resource]


@dataclass(frozen=True, slots=True)
class ModelVariables:
    """Decision-variable collections from the implemented formulation."""

    placement: dict[PlacementKey, pulp.LpVariable]
    node_active: dict[str, pulp.LpVariable]
    request: dict[BoundKey, pulp.LpVariable]
    limit: dict[BoundKey, pulp.LpVariable]
    request_violation: dict[ViolationKey, pulp.LpVariable]
    limit_violation: dict[ViolationKey, pulp.LpVariable]


def create_variables(
    model: pulp.LpProblem, data: InputData, bounds: DerivedBounds
) -> ModelVariables:
    """Create placement, resource, and chance-constraint variables."""

    placement = {
        (pod.pod_id, node.node_id): model.add_variable(
            f"placement[{pod.pod_id},{node.node_id}]", cat=pulp.LpBinary
        )
        for pod in data.pods
        for node in data.nodes
    }
    node_active = {
        node.node_id: model.add_variable(
            f"node_active[{node.node_id}]", cat=pulp.LpBinary
        )
        for node in data.nodes
    }
    request = {
        (pod.pod_id, resource): model.add_variable(
            f"request[{pod.pod_id},{resource.value}]",
            lowBound=0,
            upBound=bounds.request_upper[pod.pod_id, resource],
        )
        for pod in data.pods
        for resource in Resource
    }
    limit = {
        (pod.pod_id, resource): model.add_variable(
            f"limit[{pod.pod_id},{resource.value}]",
            lowBound=0,
            upBound=bounds.limit_upper[pod.pod_id, resource],
        )
        for pod in data.pods
        for resource in Resource
    }
    request_violation = {
        (sample.pod_id, sample.timestamp, resource): model.add_variable(
            f"request_violation[{sample.pod_id},{sample.timestamp.isoformat()},{resource.value}]",
            cat=pulp.LpBinary,
        )
        for sample in data.usage_samples
        for resource in Resource
    }
    limit_violation = {
        (sample.pod_id, sample.timestamp, resource): model.add_variable(
            f"limit_violation[{sample.pod_id},{sample.timestamp.isoformat()},{resource.value}]",
            cat=pulp.LpBinary,
        )
        for sample in data.usage_samples
        for resource in Resource
    }
    return ModelVariables(
        placement,
        node_active,
        request,
        limit,
        request_violation,
        limit_violation,
    )
