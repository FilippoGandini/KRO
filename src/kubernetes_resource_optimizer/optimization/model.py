"""Construction of the first-stage MILP formulation."""

from dataclasses import dataclass

import pulp

from kubernetes_resource_optimizer.data.models import InputData
from kubernetes_resource_optimizer.optimization.bounds import (
    DerivedBounds,
    derive_bounds,
)
from kubernetes_resource_optimizer.optimization.config import OptimizationConfig
from kubernetes_resource_optimizer.optimization.constraints import (
    add_assignment_constraints,
    add_effective_demand_constraints,
    add_limit_chance_constraints,
    add_limit_linearization_constraints,
    add_limit_overcommit_constraints,
    add_node_activation_constraints,
    add_request_chance_constraints,
    add_request_limit_ordering_constraints,
    add_runtime_capacity_constraints,
)
from kubernetes_resource_optimizer.optimization.objective import (
    set_minimum_active_nodes_and_requests_objective,
    set_minimum_active_nodes_objective
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
    data: InputData,
    config: OptimizationConfig,
    bounds: DerivedBounds | None = None,
) -> OptimizationModel:
    """Build the complete first-version MILP formulation.

    Variable bounds implement 0 <= r <= R_max and 0 <= l <= L_max.
    """

    resolved_bounds = bounds if bounds is not None else derive_bounds(data)
    problem = pulp.LpProblem("kubernetes_resource_optimizer", pulp.LpMinimize)
    variables = create_variables(problem, data, resolved_bounds)

    add_assignment_constraints(problem, data, variables)
    add_node_activation_constraints(problem, data, variables)
    add_request_chance_constraints(problem, data, config, resolved_bounds, variables)
    add_limit_chance_constraints(problem, data, config, resolved_bounds, variables)
    add_request_limit_ordering_constraints(problem, data, variables)
    add_effective_demand_constraints(problem, data, resolved_bounds, variables)
    add_runtime_capacity_constraints(problem, data, variables)
    add_limit_linearization_constraints(problem, data, resolved_bounds, variables)
    add_limit_overcommit_constraints(problem, data, config, variables)
    set_minimum_active_nodes_and_requests_objective(
        problem, variables, resolved_bounds
    )

    return OptimizationModel(problem=problem, variables=variables)
