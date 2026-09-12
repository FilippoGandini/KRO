"""Separate linear objectives, solved in strict priority order."""

from dataclasses import dataclass

import pulp

from kubernetes_resource_optimizer.data.models import InputData, Resource
from kubernetes_resource_optimizer.optimization.bounds import BoundKey, DerivedBounds
from kubernetes_resource_optimizer.optimization.config import OptimizationConfig
from kubernetes_resource_optimizer.optimization.groups import replica_groups
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
                max(priorities[p.pod_id, resource].spike_score for p in members)
                * variables.limit[members[0].pod_id, resource]
                / bounds.limit_upper[members[0].pod_id, resource]
                for members in replica_groups(data)
                for resource in Resource
                if bounds.limit_upper[members[0].pod_id, resource] > 0
            ),
            pulp.LpMaximize,
        )
    )
    return tuple(stages)
