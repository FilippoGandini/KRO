"""Separate linear objectives, solved in strict priority order."""

from dataclasses import dataclass

import pulp

from kubernetes_resource_optimizer.data.models import InputData
from kubernetes_resource_optimizer.optimization.bounds import BoundKey, DerivedBounds
from kubernetes_resource_optimizer.optimization.config import OptimizationConfig
from kubernetes_resource_optimizer.optimization.objectives.priority import LimitPriority
from kubernetes_resource_optimizer.optimization.variables import ModelVariables


@dataclass(frozen=True, slots=True)
class ObjectiveStage:
    """One objective in natural units; sense is PuLP minimize or maximize."""

    name: str
    expression: pulp.LpAffineExpression
    sense: int


def build_objective_stages(
    data: InputData,
    variables: ModelVariables,
    bounds: DerivedBounds,
    config: OptimizationConfig,
    priorities: dict[BoundKey, LimitPriority],
) -> tuple[ObjectiveStage, ...]:
    """No giant coefficients or products of decision variables are required."""

    stages = [
        ObjectiveStage(
            "node_cost",
            pulp.lpSum(
                node.cost * variables.node_active[node.node_id] for node in data.nodes
            ),
            pulp.LpMinimize,
        ),
    ]
    if config.fairness:
        stages.append(
            ObjectiveStage(
                "fairness",
                pulp.lpSum(variables.minimum_limit_headroom.values()),
                pulp.LpMaximize,
            )
        )
    stages.append(
        ObjectiveStage(
            "weighted_limits",
            pulp.lpSum(
                priorities[key].spike_score * variables.limit[key] / bound
                for key, bound in bounds.limit_upper.items()
                if bound > 0
            ),
            pulp.LpMaximize,
        )
    )
    return tuple(stages)
