"""Objective functions for the MILP."""

import math
from decimal import Decimal
from functools import reduce
from typing import cast

import pulp

from kubernetes_resource_optimizer.data.models import InputData
from kubernetes_resource_optimizer.optimization.bounds import DerivedBounds
from kubernetes_resource_optimizer.optimization.variables import ModelVariables


def set_minimum_nodes_cost_objective(
    model: pulp.LpProblem,
    data: InputData,
    variables: ModelVariables
) -> None:
    """Set the primary objective minimize sum_j y[j] * C[j]."""

    model += pulp.lpSum(node.cost * variables.node_active[node.node_id] for node in data.nodes), "minimum_nodes_cost"


def _cost_quantum(data: InputData) -> float:
    """Return the greatest decimal quantum shared by all configured costs.

    Costs are interpreted as their user-facing decimal representations. In exact
    decimal arithmetic, every sum of node costs is an integer multiple of this 
    quantum. Therefore, two such sums are either equal or differ in absolute value
    by at least one quantum.
    """

    decimals = [Decimal(str(node.cost)) for node in data.nodes]
    exponents = [cast(int, value.as_tuple().exponent) for value in decimals]
    scale = max(max(0, -exponent) for exponent in exponents)
    integers = [int(value * (10**scale)) for value in decimals]
    return reduce(math.gcd, integers) / (10**scale)


def set_minimum_node_cost_and_requests_objective(
    model: pulp.LpProblem,
    data: InputData,
    variables: ModelVariables,
    bounds: DerivedBounds,
) -> None:
    """Minimize total node cost first, then normalized resource requests.

    Each request is divided by its workload/resource-specific ``R_max`` so
    CPU cores and memory MiB contribute on the same dimensionless scale.
    Every normalized term is in [0, 1]. Node costs are uniformly scaled so the
    smallest possible non-zero difference between two node-cost sums outweighs
    the entire secondary objective. This preserves the relative proportions of
    input costs while implementing the lexicographic priority in one MILP.
    """

    normalized_requests = [
        variables.request[key] / upper_bound
        for key, upper_bound in bounds.request_upper.items()
        if upper_bound > 0
    ]
    cost_coefficient = (len(normalized_requests) + 1) / _cost_quantum(data)
    model += (
        cost_coefficient
        * pulp.lpSum(
            node.cost * variables.node_active[node.node_id] for node in data.nodes
        )
        + pulp.lpSum(normalized_requests),
        "minimum_node_cost_and_requests",
    )
