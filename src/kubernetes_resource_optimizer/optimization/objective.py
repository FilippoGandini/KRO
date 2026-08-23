"""Objective functions for the MILP."""

import pulp

from kubernetes_resource_optimizer.optimization.variables import ModelVariables


def set_minimum_active_nodes_objective(
    model: pulp.LpProblem, variables: ModelVariables
) -> None:
    """Set the primary objective minimize sum_j y[j]."""

    model += pulp.lpSum(variables.node_active.values()), "minimum_active_nodes"
