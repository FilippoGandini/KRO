"""Construction of the first-stage MILP formulation."""

from dataclasses import dataclass

import pulp

from kubernetes_resource_optimizer.data.models import InputData
from kubernetes_resource_optimizer.optimization.bounds import (
    DerivedBounds,
    derive_bounds,
)
from kubernetes_resource_optimizer.optimization.constraints import (
    add_assignment_constraints,
    add_node_activation_constraints,
    add_request_limit_ordering_constraints,
)
from kubernetes_resource_optimizer.optimization.objective import (
    set_minimum_active_nodes_objective,
)
from kubernetes_resource_optimizer.optimization.variables import (
    ModelVariables,
    create_variables,
)


@dataclass(frozen=True, slots=True)
class OptimizationModel:
    """A PuLP problem together with its named decision-variable collections."""

    problem: pulp.LpProblem
    variables: ModelVariables


def build_model(
    data: InputData, bounds: DerivedBounds | None = None
) -> OptimizationModel:
    """Build the requested x/y/r/l-only MILP stage.

    Variable bounds implement 0 <= r <= R_max and 0 <= l <= L_max.
    Later chance, effective-demand, capacity, and overcommit stages are
    intentionally absent.
    """

    resolved_bounds = bounds if bounds is not None else derive_bounds(data)
    problem = pulp.LpProblem("kubernetes_resource_optimizer", pulp.LpMinimize)
    variables = create_variables(problem, data, resolved_bounds)

    add_assignment_constraints(problem, data, variables)
    add_node_activation_constraints(problem, data, variables)
    add_request_limit_ordering_constraints(problem, data, variables)
    set_minimum_active_nodes_objective(problem, variables)

    return OptimizationModel(problem=problem, variables=variables)
