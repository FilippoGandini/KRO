"""Shared resource-configuration constraints for service replicas."""

from collections import defaultdict

import pulp

from kubernetes_resource_optimizer.data.models import InputData, Pod, Resource
from kubernetes_resource_optimizer.optimization.variables import ModelVariables


def add_replica_resource_equality_constraints(
    model: pulp.LpProblem, data: InputData, variables: ModelVariables
) -> None:
    """Give replicas of one service identical requests and limits.

    Each replica is equated to one deterministic representative. This is
    equivalent to pairwise equality, while requiring only two constraints per
    additional replica and resource instead of a quadratic number.
    """

    groups: defaultdict[str, list[Pod]] = defaultdict(list)
    for pod in data.pods:
        # Missing service membership means a true singleton. Keeping it out of
        # the mapping also prevents an unrelated pod ID from colliding with an
        # explicitly supplied service ID of the same spelling.
        if pod.service_id is not None:
            groups[pod.service_id].append(pod)

    for service_id, replicas in sorted(groups.items()):
        representative, *others = sorted(replicas, key=lambda pod: pod.pod_id)
        for replica in others:
            for resource in Resource:
                model += (
                    variables.request[replica.pod_id, resource]
                    == variables.request[representative.pod_id, resource],
                    f"replica_request_equal[{service_id},{replica.pod_id},{resource.value}]",
                )
                model += (
                    variables.limit[replica.pod_id, resource]
                    == variables.limit[representative.pod_id, resource],
                    f"replica_limit_equal[{service_id},{replica.pod_id},{resource.value}]",
                )
