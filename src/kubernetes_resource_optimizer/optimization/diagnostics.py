"""Read-only necessary feasibility checks on validated inputs, without incumbents."""

from collections import defaultdict
from collections.abc import Iterator
from datetime import datetime

from kubernetes_resource_optimizer.data.models import InputData, Resource
from kubernetes_resource_optimizer.optimization.bounds import (
    BoundKey,
    DerivedBounds,
    apply_historical_limit_caps,
    derive_bounds,
)
from kubernetes_resource_optimizer.optimization.config import OptimizationConfig
from kubernetes_resource_optimizer.optimization.history import derive_history_parameters


def feasibility_diagnostics(
    data: InputData,
    config: OptimizationConfig,
    bounds: DerivedBounds | None = None,
) -> Iterator[str]:
    """Describe bounds and capacity; passing these checks is not a feasibility proof.

    Supply the same optional bounds as build_model when overriding derived bounds.
    Comparisons use input values, without applying solver feasibility tolerances.
    """
    yield "Feasibility diagnostics (CPU cores; memory MiB; input-only checks):"
    history = derive_history_parameters(data, config)
    base = bounds if bounds is not None else derive_bounds(data, history.peaks)
    capped = apply_historical_limit_caps(
        base, history.peaks, config.limit_peak_multiplier
    )
    groups: defaultdict[tuple[bool, str], list[str]] = defaultdict(list)
    for pod in data.pods:
        groups[pod.service_id is not None, pod.service_id or pod.pod_id].append(
            pod.pod_id
        )
    lower: dict[BoundKey, float] = {}
    upper: dict[BoundKey, float] = {}
    for members in groups.values():
        for resource in Resource:
            floors = []
            for pod_id in members:
                key = pod_id, resource
                values = history.sorted_usage[key]
                rank = len(values) - config.maximum_limit_violations(
                    resource, len(values)
                )
                floors.append(
                    max(history.requests[key], values[rank - 1] if rank else 0)
                )
            for pod_id in members:
                lower[pod_id, resource] = max(floors)
                upper[pod_id, resource] = min(
                    capped.limit_upper[p, resource] for p in members
                )

    for pod in data.pods:
        for resource in Resource:
            key = pod.pod_id, resource
            values = history.sorted_usage[key]
            rank = history.coverage_splits[key]
            required = len(values) - config.maximum_limit_violations(
                resource, len(values)
            )
            covered = sum(value <= upper[key] for value in values)
            flags = []
            if history.requests[key] > base.request_upper[key]:
                flags.append("request > request_upper")
            if lower[key] > upper[key]:
                flags.append("shared minimum limit > shared cap")
            if covered < required:
                flags.append("limit coverage unreachable")
            yield (
                f"  pod={pod.pod_id!r} service={pod.service_id!r} resource={resource.value}: "
                f"request_rank={rank}/{len(values)} individual_floor={values[rank - 1] if rank else 0:g} "
                f"request={history.requests[key]:g} request_upper={base.request_upper[key]:g} "
                f"peak={history.peaks[key]:g} limit_bound={base.limit_upper[key]:g} "
                f"peak_multiplier={config.limit_peak_multiplier:g} cap={capped.limit_upper[key]:g} "
                f"shared_cap={upper[key]:g} minimum_limit={lower[key]:g} "
                f"limit_coverage_at_shared_cap={covered}/{len(values)} required={required}; "
                + ("CONFLICT: " + "; ".join(flags) if flags else "OK")
            )

    capacities = {
        (node.node_id, resource): node.cpu_capacity
        if resource is Resource.CPU
        else node.memory_capacity
        for node in data.nodes
        for resource in Resource
    }
    for pod in data.pods:
        candidates = []
        for node in data.nodes:
            if all(
                max(history.peaks[pod.pod_id, r], history.requests[pod.pod_id, r])
                <= capacities[node.node_id, r]
                and lower[pod.pod_id, r]
                <= config.limit_overcommit(r) * capacities[node.node_id, r]
                for r in Resource
            ):
                candidates.append(node.node_id)
        yield (
            f"  pod={pod.pod_id!r} capacity-compatible nodes={candidates!r} "
            "(both resources, all scenarios, minimum-limit overcommit)"
            + ("; CONFLICT: zero candidate nodes" if not candidates else "")
        )

    totals: defaultdict[tuple[datetime, Resource], float] = defaultdict(float)
    for sample in data.usage_samples:
        for resource, usage in (
            (Resource.CPU, sample.cpu_usage),
            (Resource.MEMORY, sample.memory_usage),
        ):
            totals[sample.timestamp, resource] += max(
                usage, history.requests[sample.pod_id, resource]
            )
    for resource in Resource:
        timestamp, demand = max(
            ((t, value) for (t, r), value in totals.items() if r is resource),
            key=lambda item: (item[1], item[0]),
        )
        capacity = sum(capacities[n.node_id, resource] for n in data.nodes)
        minimum = sum(lower[p.pod_id, resource] for p in data.pods)
        budget = capacity * config.limit_overcommit(resource)
        requests = sum(history.requests[p.pod_id, resource] for p in data.pods)
        yield (
            f"  resource={resource.value}: total_requests={requests:g} "
            f"maximum_scenario_demand={demand:g} timestamp={timestamp.isoformat()} "
            f"physical_capacity={capacity:g} minimum_total_limits={minimum:g} "
            f"overcommit_capacity={budget:g}; "
            + (
                "CONFLICT: aggregate capacity exceeded"
                if demand > capacity or minimum > budget
                else "OK"
            )
        )
    yield (
        "These are necessary checks, not an IIS or a proof of feasible placement. "
        "Joint placement and objective locks may still conflict. "
        "Comparisons use input precision; solver numerical tolerances apply."
    )
