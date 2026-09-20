"""Solver-independent time series used by reports and charts."""

from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime

from kubernetes_resource_optimizer.data.models import InputData, Resource, UsageSample
from kubernetes_resource_optimizer.solution.models import (
    OptimizationResult,
    PodResult,
)


@dataclass(frozen=True, slots=True)
class PodSeries:
    """Historical usage and recommendation boundaries for one pod."""

    pod_id: str
    assigned_node: str
    resource: Resource
    timestamps: tuple[datetime, ...]
    usage: tuple[float, ...]
    request: float
    limit: float
    current_request: float | None = None
    current_limit: float | None = None

    def coverage(self, boundary: float) -> float:
        """Empirical coverage with the same tolerance as solution diagnostics."""
        return sum(value <= boundary + 1e-7 for value in self.usage) / len(self.usage)


@dataclass(frozen=True, slots=True)
class NodeSeries:
    """Effective demand components and boundaries for one active node."""

    node_id: str
    resource: Resource
    timestamps: tuple[datetime, ...]
    pod_ids: tuple[str, ...]
    effective_demand: tuple[tuple[float, ...], ...]
    capacity: float
    aggregate_request: float
    aggregate_limit: float
    limit_boundary: float

    @property
    def total_effective_demand(self) -> tuple[float, ...]:
        """Return scenario totals across pods."""

        return tuple(map(sum, zip(*self.effective_demand, strict=True)))


def _usage(sample: UsageSample, resource: Resource) -> float:
    return sample.cpu_usage if resource is Resource.CPU else sample.memory_usage


def _request(result: PodResult, resource: Resource) -> float:
    if resource is Resource.CPU:
        return result.recommended_cpu_request
    return result.recommended_memory_request


def _limit(result: PodResult, resource: Resource) -> float:
    if resource is Resource.CPU:
        return result.recommended_cpu_limit
    return result.recommended_memory_limit


def build_pod_series(
    data: InputData, result: OptimizationResult, resource: Resource
) -> tuple[PodSeries, ...]:
    """Build chronologically ordered pod series from inputs and solution."""

    samples_by_pod: dict[str, list[UsageSample]] = defaultdict(list)
    for sample in data.usage_samples:
        samples_by_pod[sample.pod_id].append(sample)

    pods = {pod.pod_id: pod for pod in data.pods}
    series: list[PodSeries] = []
    for pod in result.pods:
        samples = sorted(
            samples_by_pod[pod.pod_id], key=lambda item: item.timestamp
        )
        series.append(
            PodSeries(
                pod_id=pod.pod_id,
                assigned_node=pod.assigned_node,
                resource=resource,
                timestamps=tuple(sample.timestamp for sample in samples),
                usage=tuple(_usage(sample, resource) for sample in samples),
                request=_request(pod, resource),
                limit=_limit(pod, resource),
                current_request=getattr(pods[pod.pod_id], f"current_{resource.value}_request"),
                current_limit=getattr(pods[pod.pod_id], f"current_{resource.value}_limit"),
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

    pod_series = {
        item.pod_id: item for item in build_pod_series(data, result, resource)
    }
    node_inputs = {node.node_id: node for node in data.nodes}
    node_series: list[NodeSeries] = []
    for node_result in result.nodes:
        if not node_result.active:
            continue
        components = tuple(
            tuple(max(value, series.request) for value in series.usage)
            for pod_id in node_result.assigned_pods
            for series in (pod_series[pod_id],)
        )
        timestamps = (
            pod_series[node_result.assigned_pods[0]].timestamps
            if node_result.assigned_pods
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
                pod_ids=node_result.assigned_pods,
                effective_demand=components,
                capacity=capacity,
                aggregate_request=sum(
                    pod_series[item].request
                    for item in node_result.assigned_pods
                ),
                aggregate_limit=sum(
                    pod_series[item].limit
                    for item in node_result.assigned_pods
                ),
                limit_boundary=limit_overcommit * capacity,
            )
        )
    return tuple(node_series)
