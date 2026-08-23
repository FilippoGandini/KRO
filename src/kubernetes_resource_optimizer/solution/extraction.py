"""Extract recommendations and diagnostics from a solved MILP model."""

from collections import defaultdict
from datetime import datetime

import pulp

from kubernetes_resource_optimizer.data.models import (
    InputData,
    Node,
    Resource,
    UsageSample,
)
from kubernetes_resource_optimizer.optimization.model import OptimizationModel
from kubernetes_resource_optimizer.optimization.solver import SolverResult, SolverStatus
from kubernetes_resource_optimizer.solution.models import (
    NodeDiagnostics,
    NodeResult,
    OptimizationResult,
    ViolationDiagnostics,
    WorkloadResult,
)

_BINARY_THRESHOLD = 0.5
_COMPARISON_TOLERANCE = 1e-7


def _value(variable: pulp.LpVariable) -> float:
    value = variable.varValue
    if value is None:
        raise ValueError(f"solution has no value for variable {variable.name}")
    return float(value)


def _usage(sample: UsageSample, resource: Resource) -> float:
    if resource is Resource.CPU:
        return sample.cpu_usage
    return sample.memory_usage


def _capacity(node: Node, resource: Resource) -> float:
    if resource is Resource.CPU:
        return node.cpu_capacity
    return node.memory_capacity


def extract_solution(
    data: InputData,
    model: OptimizationModel,
    solver_result: SolverResult,
) -> OptimizationResult:
    """Return recommendations and diagnostics for a feasible solved model.

    Diagnostics are derived from recommendation values and placements rather
    than potentially non-minimal auxiliary variables. This reports actual
    historical exceedances and the intended ``max(usage, request)`` demand.
    """

    if solver_result.status not in {SolverStatus.OPTIMAL, SolverStatus.FEASIBLE}:
        raise ValueError(
            f"cannot extract a solution with solver status {solver_result.status.value}"
        )
    if solver_result.objective_value is None:
        raise ValueError("a feasible solution must have an objective value")

    variables = model.variables
    assigned_by_node: dict[str, list[str]] = {
        node.node_id: [] for node in data.nodes
    }
    assigned_node_by_pod: dict[str, str] = {}
    for pod in data.pods:
        assigned_nodes = [
            node.node_id
            for node in data.nodes
            if _value(variables.placement[pod.pod_id, node.node_id])
            > _BINARY_THRESHOLD
        ]
        if len(assigned_nodes) != 1:
            raise ValueError(
                f"workload {pod.pod_id!r} has {len(assigned_nodes)} assigned nodes"
            )
        assigned_node = assigned_nodes[0]
        assigned_node_by_pod[pod.pod_id] = assigned_node
        assigned_by_node[assigned_node].append(pod.pod_id)

    workloads = tuple(
        WorkloadResult(
            workload_id=pod.pod_id,
            recommended_cpu_request=_value(
                variables.request[pod.pod_id, Resource.CPU]
            ),
            recommended_memory_request=_value(
                variables.request[pod.pod_id, Resource.MEMORY]
            ),
            recommended_cpu_limit=_value(variables.limit[pod.pod_id, Resource.CPU]),
            recommended_memory_limit=_value(
                variables.limit[pod.pod_id, Resource.MEMORY]
            ),
            assigned_node=assigned_node_by_pod[pod.pod_id],
        )
        for pod in data.pods
    )
    nodes = tuple(
        NodeResult(
            node_id=node.node_id,
            active=_value(variables.node_active[node.node_id]) > _BINARY_THRESHOLD,
            assigned_workloads=tuple(sorted(assigned_by_node[node.node_id])),
        )
        for node in data.nodes
    )

    samples_by_pod: dict[str, list[UsageSample]] = defaultdict(list)
    samples_by_timestamp: dict[datetime, list[UsageSample]] = defaultdict(list)
    for sample in data.usage_samples:
        samples_by_pod[sample.pod_id].append(sample)
        samples_by_timestamp[sample.timestamp].append(sample)

    violations: list[ViolationDiagnostics] = []
    for pod in data.pods:
        samples = samples_by_pod[pod.pod_id]
        for resource in Resource:
            request = _value(variables.request[pod.pod_id, resource])
            limit = _value(variables.limit[pod.pod_id, resource])
            request_count = sum(
                _usage(sample, resource) > request + _COMPARISON_TOLERANCE
                for sample in samples
            )
            limit_count = sum(
                _usage(sample, resource) > limit + _COMPARISON_TOLERANCE
                for sample in samples
            )
            scenario_count = len(samples)
            violations.append(
                ViolationDiagnostics(
                    workload_id=pod.pod_id,
                    resource=resource,
                    request_violation_count=request_count,
                    request_violation_rate=request_count / scenario_count,
                    limit_violation_count=limit_count,
                    limit_violation_rate=limit_count / scenario_count,
                )
            )

    node_diagnostics: list[NodeDiagnostics] = []
    for node in data.nodes:
        assigned_pods = set(assigned_by_node[node.node_id])
        peaks: dict[Resource, float] = {}
        for resource in Resource:
            peaks[resource] = max(
                (
                    sum(
                        max(
                            _usage(sample, resource),
                            _value(variables.request[sample.pod_id, resource]),
                        )
                        for sample in timestamp_samples
                        if sample.pod_id in assigned_pods
                    )
                    for timestamp_samples in samples_by_timestamp.values()
                ),
                default=0.0,
            )
        configured_ratios = {
            resource: sum(
                _value(variables.limit[pod_id, resource])
                for pod_id in assigned_pods
            )
            / _capacity(node, resource)
            for resource in Resource
        }
        node_diagnostics.append(
            NodeDiagnostics(
                node_id=node.node_id,
                peak_effective_cpu=peaks[Resource.CPU],
                peak_effective_memory=peaks[Resource.MEMORY],
                configured_cpu_limit_overcommit=configured_ratios[Resource.CPU],
                configured_memory_limit_overcommit=configured_ratios[Resource.MEMORY],
            )
        )

    return OptimizationResult(
        solver_status=solver_result.status,
        objective_value=solver_result.objective_value,
        active_node_count=sum(node.active for node in nodes),
        solve_time_seconds=solver_result.solve_time_seconds,
        workloads=workloads,
        nodes=nodes,
        violations=tuple(violations),
        node_diagnostics=tuple(node_diagnostics),
    )
