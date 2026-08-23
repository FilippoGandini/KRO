"""Request constraints for the first MILP model-building stage."""

import pulp

from kubernetes_resource_optimizer.data.models import InputData, Resource, UsageSample
from kubernetes_resource_optimizer.optimization.bounds import DerivedBounds
from kubernetes_resource_optimizer.optimization.config import OptimizationConfig
from kubernetes_resource_optimizer.optimization.variables import ModelVariables


def _usage(sample: UsageSample, resource: Resource) -> float:
    """Return one sample's utilization in the resource's canonical unit."""

    if resource is Resource.CPU:
        return sample.cpu_usage
    return sample.memory_usage


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


def add_request_chance_constraints(
    model: pulp.LpProblem,
    data: InputData,
    config: OptimizationConfig,
    bounds: DerivedBounds,
    variables: ModelVariables,
) -> None:
    """Enforce request coverage with at most floor(epsilon_request[h] * |T|) violations."""

    for pod in data.pods:
        samples = tuple(sample for sample in data.usage_samples if sample.pod_id == pod.pod_id)
        for resource in Resource:
            key = (pod.pod_id, resource)
            for sample in samples:
                model += (
                    _usage(sample, resource)
                    <= variables.request[key]
                    + bounds.request_big_m[key]
                    * variables.request_violation[pod.pod_id, sample.timestamp, resource],
                    f"request_coverage[{pod.pod_id},{sample.timestamp.isoformat()},{resource.value}]",
                )
            model += (
                pulp.lpSum(
                    variables.request_violation[pod.pod_id, sample.timestamp, resource]
                    for sample in samples
                )
                <= config.maximum_request_violations(resource, len(samples)),
                f"request_violation_budget[{pod.pod_id},{resource.value}]",
            )


def add_limit_chance_constraints(
    model: pulp.LpProblem,
    data: InputData,
    config: OptimizationConfig,
    bounds: DerivedBounds,
    variables: ModelVariables,
) -> None:
    """Enforce limit coverage with at most floor(epsilon_limit[h] * |T|) violations."""

    for pod in data.pods:
        samples = tuple(sample for sample in data.usage_samples if sample.pod_id == pod.pod_id)
        for resource in Resource:
            key = (pod.pod_id, resource)
            for sample in samples:
                model += (
                    _usage(sample, resource)
                    <= variables.limit[key]
                    + bounds.limit_big_m[key]
                    * variables.limit_violation[pod.pod_id, sample.timestamp, resource],
                    f"limit_coverage[{pod.pod_id},{sample.timestamp.isoformat()},{resource.value}]",
                )
            model += (
                pulp.lpSum(
                    variables.limit_violation[pod.pod_id, sample.timestamp, resource]
                    for sample in samples
                )
                <= config.maximum_limit_violations(resource, len(samples)),
                f"limit_violation_budget[{pod.pod_id},{resource.value}]",
            )
