"""Scenario capacity using precomputed max(usage, deterministic request)."""

import pulp

from kubernetes_resource_optimizer.data.models import InputData, Resource
from kubernetes_resource_optimizer.optimization.bounds import BoundKey
from kubernetes_resource_optimizer.optimization.variables import ModelVariables


def add_runtime_capacity_constraints(
    model: pulp.LpProblem,
    data: InputData,
    variables: ModelVariables,
    requests: dict[BoundKey, float],
) -> None:
    """Enforce physical capacity in every aligned historical scenario."""
    samples = {(s.pod_id, s.timestamp): s for s in data.usage_samples}
    for node in data.nodes:
        for timestamp in sorted({s.timestamp for s in data.usage_samples}):
            for resource in Resource:
                demand = {}
                for pod in data.pods:
                    sample = samples[pod.pod_id, timestamp]
                    usage = (
                        sample.cpu_usage
                        if resource is Resource.CPU
                        else sample.memory_usage
                    )
                    demand[pod.pod_id] = max(usage, requests[pod.pod_id, resource])
                capacity = (
                    node.cpu_capacity
                    if resource is Resource.CPU
                    else node.memory_capacity
                )
                model += (
                    pulp.lpSum(
                        demand[p.pod_id] * variables.placement[p.pod_id, node.node_id]
                        for p in data.pods
                    )
                    <= capacity * variables.node_active[node.node_id],
                    f"runtime_capacity[{node.node_id},{timestamp.isoformat()},{resource.value}]",
                )
