"""Workload assignment and node-activation constraints."""

from collections import defaultdict
from itertools import pairwise

import pulp

from kubernetes_resource_optimizer.data.models import InputData
from kubernetes_resource_optimizer.optimization.variables import ModelVariables


def add_assignment_constraints(
    model: pulp.LpProblem, data: InputData, variables: ModelVariables
) -> None:
    """Enforce sum_j x[i,j] = 1 for every workload i."""

    for pod in data.pods:
        model += (
            pulp.lpSum(
                variables.placement[pod.pod_id, node.node_id]
                for node in data.nodes
            )
            == 1,
            f"assignment_exactly_once[{pod.pod_id}]",
        )


def add_node_activation_constraints(
    model: pulp.LpProblem, data: InputData, variables: ModelVariables
) -> None:
    """Enforce x[i,j] <= y[j] for every workload i and node j."""

    for pod in data.pods:
        for node in data.nodes:
            model += (
                variables.placement[pod.pod_id, node.node_id]
                <= variables.node_active[node.node_id],
                f"placement_requires_active_node[{pod.pod_id},{node.node_id}]",
            )


def add_equivalent_node_activation_order_constraints(
    model: pulp.LpProblem, data: InputData, variables: ModelVariables
) -> None:
    """Activate equivalent nodes in deterministic input order.

    Nodes are equivalent when CPU capacity, memory capacity, and cost are all
    equal. Permuting their activation variables cannot change feasibility or
    objective value, so y[j_k] >= y[j_(k+1)] removes equivalent activation
    patterns without changing the mathematical optimum.
    """

    equivalent_groups: dict[tuple[float, float, float], list[str]] = defaultdict(list)
    for node in data.nodes:
        key = (node.cpu_capacity, node.memory_capacity, node.cost)
        equivalent_groups[key].append(node.node_id)

    for node_ids in equivalent_groups.values():
        for earlier_node_id, later_node_id in pairwise(node_ids):
            model += (
                variables.node_active[earlier_node_id]
                >= variables.node_active[later_node_id],
                f"equivalent_node_activation_order[{earlier_node_id},{later_node_id}]",
            )
