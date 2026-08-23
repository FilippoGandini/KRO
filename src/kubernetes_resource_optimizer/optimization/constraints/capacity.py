"""Effective-demand linearization and runtime node-capacity constraints."""

from datetime import datetime

import pulp

from kubernetes_resource_optimizer.data.models import (
    InputData,
    Node,
    Resource,
    UsageSample,
)
from kubernetes_resource_optimizer.optimization.bounds import DerivedBounds
from kubernetes_resource_optimizer.optimization.variables import ModelVariables


def _usage(sample: UsageSample, resource: Resource) -> float:
    return sample.cpu_usage if resource is Resource.CPU else sample.memory_usage


def _capacity(node: Node, resource: Resource) -> float:
    return node.cpu_capacity if resource is Resource.CPU else node.memory_capacity


def _samples_by_pod_and_timestamp(
    data: InputData,
) -> dict[tuple[str, datetime], UsageSample]:
    return {(sample.pod_id, sample.timestamp): sample for sample in data.usage_samples}


def add_effective_demand_constraints(
    model: pulp.LpProblem,
    data: InputData,
    bounds: DerivedBounds,
    variables: ModelVariables,
) -> None:
    """Linearize q[i,j,t,h] >= max(u[i,t,h], r[i,h]) * x[i,j].

    Non-negativity is imposed by each effective-demand variable's lower bound.
    The two inequalities below impose the utilization and request lower bounds
    without a nonlinear max expression or a product of decision variables.
    """

    samples = _samples_by_pod_and_timestamp(data)
    timestamps = sorted({sample.timestamp for sample in data.usage_samples})
    for pod in data.pods:
        for node in data.nodes:
            placement = variables.placement[pod.pod_id, node.node_id]
            for timestamp in timestamps:
                sample = samples[pod.pod_id, timestamp]
                for resource in Resource:
                    key = (pod.pod_id, node.node_id, timestamp, resource)
                    demand = variables.effective_demand[key]
                    model += (
                        demand >= _usage(sample, resource) * placement,
                        f"effective_demand_from_usage[{pod.pod_id},{node.node_id},{timestamp.isoformat()},{resource.value}]",
                    )
                    # Enforce q >= request when the workload is placed here.
                    model += (
                        demand
                        >= variables.request[pod.pod_id, resource]
                        - bounds.request_upper[pod.pod_id, resource]
                        * (1 - placement),
                        f"effective_demand_from_request[{pod.pod_id},{node.node_id},{timestamp.isoformat()},{resource.value}]",
                    )


def add_runtime_capacity_constraints(
    model: pulp.LpProblem, data: InputData, variables: ModelVariables
) -> None:
    """Enforce sum_i q[i,j,t,h] <= C[j,h] * y[j] in every scenario."""

    timestamps = sorted({sample.timestamp for sample in data.usage_samples})
    for node in data.nodes:
        for timestamp in timestamps:
            for resource in Resource:
                model += (
                    pulp.lpSum(
                        variables.effective_demand[
                            pod.pod_id, node.node_id, timestamp, resource
                        ]
                        for pod in data.pods
                    )
                    <= _capacity(node, resource)
                    * variables.node_active[node.node_id],
                    f"runtime_capacity[{node.node_id},{timestamp.isoformat()},{resource.value}]",
                )
