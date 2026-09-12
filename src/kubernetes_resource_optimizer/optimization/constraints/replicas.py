"""Shared resource-configuration constraints for service replicas."""

import pulp

from kubernetes_resource_optimizer.data.models import InputData, Resource
from kubernetes_resource_optimizer.optimization.groups import replica_groups
from kubernetes_resource_optimizer.optimization.variables import ModelVariables


def add_replica_resource_equality_constraints(
    model: pulp.LpProblem, data: InputData, variables: ModelVariables
) -> None:
    """Give replicas of one service identical requests and limits.

    Each replica is equated to one deterministic representative. This is
    equivalent to pairwise equality, while requiring only one constraint per
    additional replica and resource instead of a quadratic number.
    """

    for members in replica_groups(data):
        representative, *others = members
        service_id = representative.service_id
        for replica in others:
            for resource in Resource:
                model += (
                    variables.limit[replica.pod_id, resource]
                    == variables.limit[representative.pod_id, resource],
                    f"replica_limit_equal[{service_id},{replica.pod_id},{resource.value}]",
                )
