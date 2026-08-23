"""Request constraints for the first MILP model-building stage."""

import pulp

from kubernetes_resource_optimizer.data.models import InputData, Resource
from kubernetes_resource_optimizer.optimization.variables import ModelVariables


def add_request_limit_ordering_constraints(
    model: pulp.LpProblem, data: InputData, variables: ModelVariables
) -> None:
    """Enforce r[i,h] <= l[i,h] for every workload and resource."""

    for pod in data.pods:
        for resource in Resource:
            model += (
                variables.request[pod.pod_id, resource]
                <= variables.limit[pod.pod_id, resource],
                f"request_not_above_limit[{pod.pod_id},{resource.value}]",
            )
