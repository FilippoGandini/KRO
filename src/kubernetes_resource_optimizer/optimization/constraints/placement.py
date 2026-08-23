"""Workload assignment and node-activation constraints."""

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
