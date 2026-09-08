"""Construction of the scenario-based placement and limit MILP."""

from dataclasses import dataclass

import pulp

from kubernetes_resource_optimizer.data.models import InputData
from kubernetes_resource_optimizer.optimization.bounds import (
    BoundKey,
    DerivedBounds,
    apply_historical_limit_caps,
    derive_bounds,
)
from kubernetes_resource_optimizer.optimization.config import OptimizationConfig
from kubernetes_resource_optimizer.optimization.constraints import (
    add_assignment_constraints,
    add_equivalent_node_activation_order_constraints,
    add_limit_chance_constraints,
    add_limit_headroom_fairness_constraints,
    add_limit_linearization_constraints,
    add_limit_overcommit_constraints,
    add_node_activation_constraints,
    add_replica_resource_equality_constraints,
    add_request_limit_ordering_constraints,
    add_runtime_capacity_constraints,
)
from kubernetes_resource_optimizer.optimization.history import derive_history_parameters
from kubernetes_resource_optimizer.optimization.objectives.priority import (
    LimitPriority,
    derive_limit_priorities,
)
from kubernetes_resource_optimizer.optimization.objectives.stages import (
    ObjectiveStage,
    build_objective_stages,
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
    stages: tuple[ObjectiveStage, ...]
    priorities: dict[BoundKey, LimitPriority]
    config: OptimizationConfig
    requests: dict[BoundKey, float]


def build_model(
    data: InputData,
    config: OptimizationConfig,
    bounds: DerivedBounds | None = None,
) -> OptimizationModel:
    """Build the complete first-version MILP formulation.

    Requests are coverage order statistics; limits have a hard historical cap.
    """

    history = derive_history_parameters(data, config)
    requests = history.requests
    resolved_bounds = (
        bounds if bounds is not None else derive_bounds(data, history.peaks)
    )
    priorities = derive_limit_priorities(history)
    resolved_bounds = apply_historical_limit_caps(
        resolved_bounds, history.peaks, config.limit_peak_multiplier
    )
    problem = pulp.LpProblem("kubernetes_resource_optimizer", pulp.LpMinimize)
    variables = create_variables(
        problem, data, resolved_bounds, fairness=config.fairness
    )

    add_assignment_constraints(problem, data, variables)
    add_node_activation_constraints(problem, data, variables)
    add_equivalent_node_activation_order_constraints(problem, data, variables)
    add_limit_chance_constraints(problem, data, config, resolved_bounds, variables)
    add_request_limit_ordering_constraints(problem, data, variables, requests)
    add_replica_resource_equality_constraints(problem, data, variables)
    add_runtime_capacity_constraints(problem, data, variables, requests)
    add_limit_linearization_constraints(problem, data, resolved_bounds, variables)
    add_limit_overcommit_constraints(problem, data, config, variables)
    if config.fairness:
        add_limit_headroom_fairness_constraints(
            problem, data, resolved_bounds, variables, requests
        )
    for key, request in requests.items():
        # Keep incompatible deterministic requests as explicit infeasible constraints.
        problem += (
            pulp.LpAffineExpression() <= resolved_bounds.request_upper[key] - request,
            f"request_upper[{key[0]},{key[1].value}]",
        )
    stages = build_objective_stages(
        data, variables, resolved_bounds, config, priorities
    )
    problem.setObjective(stages[0].expression)

    return OptimizationModel(problem, variables, stages, priorities, config, requests)
