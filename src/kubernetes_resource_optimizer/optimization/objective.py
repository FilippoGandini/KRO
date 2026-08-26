"""Objective functions for the MILP."""

import pulp

from kubernetes_resource_optimizer.optimization.bounds import DerivedBounds
from kubernetes_resource_optimizer.optimization.variables import ModelVariables


def set_minimum_active_nodes_objective(
    model: pulp.LpProblem, variables: ModelVariables
) -> None:
    """Set the primary objective minimize sum_j y[j]."""

    model += pulp.lpSum(variables.node_active.values()), "minimum_active_nodes"


def set_minimum_active_nodes_and_requests_objective(
    model: pulp.LpProblem,
    variables: ModelVariables,
    bounds: DerivedBounds,
) -> None:
    """Minimize active nodes first, then normalized resource requests.

    Each request is divided by its workload/resource-specific ``R_max`` so
    CPU cores and memory MiB contribute on the same dimensionless scale.
    Every normalized term is in [0, 1]. Giving each active node a coefficient
    one greater than the number of non-zero request bounds therefore makes
    one fewer active node preferable to any possible request reduction.
    """

    normalized_requests = [
        variables.request[key] / upper_bound
        for key, upper_bound in bounds.request_upper.items()
        if upper_bound > 0
    ]
    active_node_coefficient = len(normalized_requests) + 1
    model += (
        active_node_coefficient * pulp.lpSum(variables.node_active.values())
        + pulp.lpSum(normalized_requests),
        "minimum_active_nodes_and_requests",
    )
