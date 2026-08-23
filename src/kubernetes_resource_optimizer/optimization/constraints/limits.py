"""Limit-placement linearization and configured limit-overcommit constraints."""

import pulp

from kubernetes_resource_optimizer.data.models import InputData, Node, Resource
from kubernetes_resource_optimizer.optimization.bounds import DerivedBounds
from kubernetes_resource_optimizer.optimization.config import OptimizationConfig
from kubernetes_resource_optimizer.optimization.variables import ModelVariables


def _capacity(node: Node, resource: Resource) -> float:
    return node.cpu_capacity if resource is Resource.CPU else node.memory_capacity


def add_limit_linearization_constraints(
    model: pulp.LpProblem,
    data: InputData,
    bounds: DerivedBounds,
    variables: ModelVariables,
) -> None:
    """Enforce s[i,j,h] = l[i,h] * x[i,j] without a bilinear product.

    Non-negativity is imposed by each placed-limit variable's lower bound.
    The remaining three inequalities are exact because each limit is bounded
    above by its finite L_max[i,h].
    """

    for pod in data.pods:
        for node in data.nodes:
            placement = variables.placement[pod.pod_id, node.node_id]
            for resource in Resource:
                key = (pod.pod_id, node.node_id, resource)
                placed_limit = variables.placed_limit[key]
                limit = variables.limit[pod.pod_id, resource]
                limit_upper = bounds.limit_upper[pod.pod_id, resource]
                model += (
                    placed_limit <= limit,
                    f"placed_limit_at_most_limit[{pod.pod_id},{node.node_id},{resource.value}]",
                )
                model += (
                    placed_limit <= limit_upper * placement,
                    f"placed_limit_at_most_placement[{pod.pod_id},{node.node_id},{resource.value}]",
                )
                model += (
                    placed_limit >= limit - limit_upper * (1 - placement),
                    f"placed_limit_at_least_limit_when_placed[{pod.pod_id},{node.node_id},{resource.value}]",
                )


def add_limit_overcommit_constraints(
    model: pulp.LpProblem,
    data: InputData,
    config: OptimizationConfig,
    variables: ModelVariables,
) -> None:
    """Enforce sum_i s[i,j,h] <= K_limit[h] C[j,h] y[j]."""

    for node in data.nodes:
        for resource in Resource:
            model += (
                pulp.lpSum(
                    variables.placed_limit[pod.pod_id, node.node_id, resource]
                    for pod in data.pods
                )
                <= config.limit_overcommit(resource)
                * _capacity(node, resource)
                * variables.node_active[node.node_id],
                f"limit_overcommit[{node.node_id},{resource.value}]",
            )
