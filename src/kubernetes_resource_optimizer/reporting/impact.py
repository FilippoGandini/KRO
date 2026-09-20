"""Matched-cohort allocation totals and compact report impact summaries."""

import math
from dataclasses import dataclass

from kubernetes_resource_optimizer.data.models import InputData, Resource
from kubernetes_resource_optimizer.optimization.config import OptimizationConfig
from kubernetes_resource_optimizer.reporting.formatting import (
    format_number,
    format_percent,
)
from kubernetes_resource_optimizer.reporting.series import WorkloadSeries
from kubernetes_resource_optimizer.solution.models import OptimizationResult


@dataclass(frozen=True, slots=True)
class AllocationImpact:
    """Compare only workloads that supply the relevant current boundary."""

    pods: int
    total_pods: int
    current: float
    recommended: float
    current_coverage: float
    recommended_coverage: float
    current_at_risk: int
    recommended_at_risk: int


def aggregate_impact(
    series: tuple[WorkloadSeries, ...], kind: str, epsilon: float,
) -> AllocationImpact | None:
    pairs = [
        (item, current, item.request if kind == "request" else item.limit)
        for item in series
        if (current := (item.current_request if kind == "request" else item.current_limit))
        is not None
    ]
    if not pairs:
        return None
    observations = sum(len(item.usage) for item, _, _ in pairs)
    current_exceed = [sum(value > current + 1e-7 for value in item.usage)
                      for item, current, _ in pairs]
    recommended_exceed = [sum(value > recommended + 1e-7 for value in item.usage)
                          for item, _, recommended in pairs]
    return AllocationImpact(
        pods=len(pairs), total_pods=len(series),
        current=math.fsum(current for _, current, _ in pairs),
        recommended=math.fsum(recommended for _, _, recommended in pairs),
        current_coverage=1 - sum(current_exceed) / observations,
        recommended_coverage=1 - sum(recommended_exceed) / observations,
        current_at_risk=sum(count / len(item.usage) > epsilon + 1e-7
                            for count, (item, _, _) in zip(current_exceed, pairs, strict=True)),
        recommended_at_risk=sum(count / len(item.usage) > epsilon + 1e-7
                                for count, (item, _, _) in zip(recommended_exceed, pairs, strict=True)),
    )


def _quantity(value: float, resource: Resource) -> str:
    if resource is Resource.CPU:
        number = format_number(value)
        return f"{number} cores"
    if abs(value) >= 1024:
        return f"{format_number(value / 1024)} GiB"
    return f"{format_number(value)} MiB"


def _card(impact: AllocationImpact | None, resource: Resource, kind: str) -> str:
    label = f"{resource.value.upper()} {kind}"
    if impact is None:
        return f'<div class="impact-card {kind}"><b>{label}</b><small>No current data</small></div>'
    difference = impact.recommended - impact.current
    change = "Reduction" if difference < 0 else "Increase" if difference > 0 else "Unchanged"
    percent = f"{format_percent(difference / impact.current, 1, signed=True)}" if impact.current else "base is zero"
    return (
        f'<div class="impact-card {kind}"><b>{label}</b>'
        f'<strong>{_quantity(impact.current, resource)} → {_quantity(impact.recommended, resource)}</strong>'
        f'<span>{change}: {_quantity(abs(difference), resource)} ({percent})</span>'
        f'<small>{impact.pods}/{impact.total_pods} comparable pods · Coverage '
        f'{format_percent(impact.current_coverage, 1)} → {format_percent(impact.recommended_coverage, 1)}</small>'
        f'<small>Pods above risk tolerance: {impact.current_at_risk} → {impact.recommended_at_risk}</small></div>'
    )


def _bars(
    resource: Resource, capacity: float, overcommit: float,
    impacts: tuple[AllocationImpact | None, AllocationImpact | None],
) -> str:
    if all(item is None for item in impacts):
        return ""
    limit_boundary = capacity * overcommit
    maximum = max(capacity, limit_boundary,
                  *(max(item.current, item.recommended) for item in impacts if item)) * 1.05
    lines = []
    for kind, impact in zip(("request", "limit"), impacts, strict=True):
        if impact is None:
            continue
        for label, value in (("Current", impact.current), ("Recommended", impact.recommended)):
            ratio = value / capacity
            lines.append(
                f'<div class="impact-bar-row"><span>{kind.title()} · {label}</span>'
                f'<div class="impact-track"><i class="{kind} {label.lower()}" '
                f'style="width:{value / maximum * 100:.4f}%"></i>'
                f'<i class="capacity-mark" style="left:{capacity / maximum * 100:.4f}%" title="Selected node capacity"></i>'
                + (f'<i class="overcommit-mark" style="left:{limit_boundary / maximum * 100:.4f}%" title="Limit overcommit boundary"></i>'
                   if kind == "limit" else "")
                + f'</div><span>{format_percent(ratio, 1)}</span></div>'
            )
    return (
        f'<div class="impact-chart"><b>{resource.value.upper()} / selected capacity: '
        f'{_quantity(capacity, resource)}</b>{"".join(lines)}'
        f'<small>│ Capacity · ┆ Limit boundary: {_quantity(limit_boundary, resource)} ({overcommit:g}×)</small></div>'
    )


def impact_section(
    data: InputData, result: OptimizationResult, config: OptimizationConfig,
    cpu: tuple[WorkloadSeries, ...], memory: tuple[WorkloadSeries, ...],
) -> str:
    """Render a fixed-size summary; no additional per-workload report rows."""
    cpu_impacts = (aggregate_impact(cpu, "request", config.epsilon_cpu_request),
                   aggregate_impact(cpu, "limit", config.epsilon_cpu_limit))
    memory_impacts = (aggregate_impact(memory, "request", config.epsilon_memory_request),
                      aggregate_impact(memory, "limit", config.epsilon_memory_limit))
    if not any(item for item in (*cpu_impacts, *memory_impacts)):
        return ""
    active = {node.node_id for node in result.nodes if node.active}
    selected = [node for node in data.nodes if node.node_id in active]
    cards = "".join(_card(item, resource, kind)
                    for resource, impacts in ((Resource.CPU, cpu_impacts),
                                              (Resource.MEMORY, memory_impacts))
                    for kind, item in zip(("request", "limit"), impacts, strict=True))
    charts = (
        _bars(Resource.CPU, sum(node.cpu_capacity for node in selected),
              config.cpu_limit_overcommit, cpu_impacts)
        + _bars(Resource.MEMORY, sum(node.memory_capacity for node in selected),
                config.memory_limit_overcommit, memory_impacts)
    )
    return (
        '<section id="allocation-impact"><h3>Overall allocation impact</h3>'
        f'<div class="impact-cards">{cards}</div><div class="impact-charts">{charts}</div>'
        '</section>'
    )


STYLES = """
#allocation-impact{padding:1rem;font-variant-numeric:tabular-nums}
#allocation-impact h3{margin:0 0 .6rem}#allocation-impact p{font-size:.75rem;color:#52616b;margin:.6rem 0 0}
.impact-cards{display:grid;grid-template-columns:repeat(4,minmax(0,1fr));gap:.6rem}
.impact-card{border:1px solid #dfe3e6;border-top:3px solid #1565C0;border-radius:5px;padding:.6rem;display:grid;gap:.25rem;font-size:.8rem}
.impact-card.limit{border-top-color:#6A1B9A}.impact-card strong{font-size:.9rem}.impact-card small{color:#52616b}
.impact-charts{display:grid;grid-template-columns:1fr 1fr;gap:1.5rem;margin-top:.75rem}
.impact-chart{font-size:.75rem;min-width:0}.impact-chart>b{display:block;margin-bottom:.3rem}
.impact-bar-row{display:grid;grid-template-columns:145px minmax(0,1fr) 55px;gap:.5rem;align-items:center;margin:.2rem 0}
.impact-bar-row>span:last-child{text-align:right}.impact-track{height:9px;background:#eef3f7;position:relative}
.impact-track>i{display:block;height:100%;position:absolute;left:0;top:0}.impact-track .request{background:#1565C0}.impact-track .request.current{background:#64A5E8}
.impact-track .limit{background:#6A1B9A}.impact-track .limit.current{background:#B47ACF}
.impact-track .capacity-mark{border-left:2px solid #37474F;height:15px;top:-3px}.impact-track .overcommit-mark{border-left:2px dotted #37474F;height:15px;top:-3px}
@media(max-width:1000px){.impact-cards{grid-template-columns:1fr 1fr}}
@media(max-width:700px){.impact-charts{grid-template-columns:1fr;gap:.6rem}}
@media(max-width:450px){.impact-cards{grid-template-columns:1fr}.impact-bar-row{grid-template-columns:130px minmax(0,1fr) 48px}}
"""
