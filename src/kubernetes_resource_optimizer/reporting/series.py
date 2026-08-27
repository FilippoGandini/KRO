"""Solver-independent time series used by reports and charts."""

from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime

from kubernetes_resource_optimizer.data.models import InputData, Resource, UsageSample
from kubernetes_resource_optimizer.solution.models import (
    OptimizationResult,
    WorkloadResult,
)


@dataclass(frozen=True, slots=True)
class WorkloadSeries:
    """Historical usage and recommendation boundaries for one workload."""

    workload_id: str
    assigned_node: str
    resource: Resource
    timestamps: tuple[datetime, ...]
    usage: tuple[float, ...]
    request: float
    limit: float


@dataclass(frozen=True, slots=True)
class NodeSeries:
    """Effective demand components and boundaries for one active node."""

    node_id: str
    resource: Resource
    timestamps: tuple[datetime, ...]
    workload_ids: tuple[str, ...]
    effective_demand: tuple[tuple[float, ...], ...]
    capacity: float
    aggregate_request: float
    aggregate_limit: float
    limit_boundary: float

    @property
    def total_effective_demand(self) -> tuple[float, ...]:
        """Return scenario totals across workloads."""

        return tuple(map(sum, zip(*self.effective_demand, strict=True)))


def _usage(sample: UsageSample, resource: Resource) -> float:
    return sample.cpu_usage if resource is Resource.CPU else sample.memory_usage


def _request(result: WorkloadResult, resource: Resource) -> float:
    if resource is Resource.CPU:
        return result.recommended_cpu_request
    return result.recommended_memory_request


def _limit(result: WorkloadResult, resource: Resource) -> float:
    if resource is Resource.CPU:
        return result.recommended_cpu_limit
    return result.recommended_memory_limit


def build_workload_series(
    data: InputData, result: OptimizationResult, resource: Resource
) -> tuple[WorkloadSeries, ...]:
    """Build chronologically ordered workload series from inputs and solution."""

    samples_by_workload: dict[str, list[UsageSample]] = defaultdict(list)
    for sample in data.usage_samples:
        samples_by_workload[sample.pod_id].append(sample)

    series: list[WorkloadSeries] = []
    for workload in result.workloads:
        samples = sorted(
            samples_by_workload[workload.workload_id], key=lambda item: item.timestamp
        )
        series.append(
            WorkloadSeries(
                workload_id=workload.workload_id,
                assigned_node=workload.assigned_node,
                resource=resource,
                timestamps=tuple(sample.timestamp for sample in samples),
                usage=tuple(_usage(sample, resource) for sample in samples),
                request=_request(workload, resource),
                limit=_limit(workload, resource),
            )
        )
    return tuple(series)


def build_node_series(
    data: InputData,
    result: OptimizationResult,
    resource: Resource,
    limit_overcommit: float,
) -> tuple[NodeSeries, ...]:
    """Build active-node series using the intended max(usage, request) demand."""

    workload_series = {
        item.workload_id: item for item in build_workload_series(data, result, resource)
    }
    node_inputs = {node.node_id: node for node in data.nodes}
    node_series: list[NodeSeries] = []
    for node_result in result.nodes:
        if not node_result.active:
            continue
        components = tuple(
            tuple(max(value, series.request) for value in series.usage)
            for workload_id in node_result.assigned_workloads
            for series in (workload_series[workload_id],)
        )
        timestamps = (
            workload_series[node_result.assigned_workloads[0]].timestamps
            if node_result.assigned_workloads
            else ()
        )
        node = node_inputs[node_result.node_id]
        capacity = (
            node.cpu_capacity if resource is Resource.CPU else node.memory_capacity
        )
        node_series.append(
            NodeSeries(
                node_id=node_result.node_id,
                resource=resource,
                timestamps=timestamps,
                workload_ids=node_result.assigned_workloads,
                effective_demand=components,
                capacity=capacity,
                aggregate_request=sum(
                    workload_series[item].request
                    for item in node_result.assigned_workloads
                ),
                aggregate_limit=sum(
                    workload_series[item].limit
                    for item in node_result.assigned_workloads
                ),
                limit_boundary=limit_overcommit * capacity,
            )
        )
    return tuple(node_series)
