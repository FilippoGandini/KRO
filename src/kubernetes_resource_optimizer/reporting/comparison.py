"""Compact, optional current/recommended allocation comparison cells."""

import html

from kubernetes_resource_optimizer.data.models import Resource
from kubernetes_resource_optimizer.reporting.formatting import (
    format_number,
    format_percent,
)
from kubernetes_resource_optimizer.reporting.series import PodSeries

STYLES = """
.allocation{display:block;padding:.35rem .5rem;margin:.15rem 0;border-left:3px solid;white-space:nowrap}
.allocation.request{border-color:#1565C0}.allocation.limit{border-color:#6A1B9A}
.allocation.current.request{border-color:#64A5E8;border-left-style:dashed}
.allocation.current.limit{border-color:#B47ACF;border-left-style:dotted}
.allocation small{display:block;color:#455A64;font-size:.78rem}
.allocation.exceeded{background:#fff3cd}.allocation.over-risk{background:#fde2e2}
.comparison-key{font-size:.9rem;line-height:1.6}
"""

NOTE = """<p class="comparison-key">Each cell compares Current and Recommended values
and their historical coverage (usage ≤ boundary)"""


def _cell(series: PodSeries, kind: str, epsilon: float) -> str:
    recommended = series.request if kind == "request" else series.limit
    current = series.current_request if kind == "request" else series.current_limit
    parts = []
    unit = "cores" if series.resource is Resource.CPU else "MiB"
    for label, boundary in (("Current", current), ("Recommended", recommended)):
        css = f"allocation {kind} {label.lower()}"
        if boundary is None:
            parts.append(f'<span class="{css}"><small>{label}</small>—</span>')
            continue
        display = (
            f"{format_number(boundary / 1024)} GiB"
            if series.resource is Resource.MEMORY and boundary >= 1024
            else f"{format_number(boundary)} {unit}"
        )
        coverage = series.coverage(boundary)
        exceeded = sum(value > boundary + 1e-7 for value in series.usage)
        if exceeded:
            css += " over-risk" if 1 - coverage > epsilon + 1e-7 else " exceeded"
        title = (f"{boundary:.15g} {unit}; {exceeded}/{len(series.usage)} observations "
                 f"exceed this {kind}; risk tolerance {format_percent(epsilon, 2)}")
        parts.append(
            f'<span class="{css}" title="{html.escape(title, quote=True)}">'
            f'<small>{label}</small>{display}'
            f'<small>{format_percent(coverage, 2)} coverage · {exceeded}/{len(series.usage)} exceed</small></span>'
        )
    return f'<td data-sort="{recommended:.15g}">{"".join(parts)}</td>'


def comparison_table(
    cpu: tuple[PodSeries, ...], memory: tuple[PodSeries, ...],
    risks: tuple[float, float, float, float],
) -> str:
    headings = ("Pod", "Node", "CPU request (cores)", "CPU limit (cores)",
                "Memory request", "Memory limit")
    header = "".join(f'<th scope="col">{heading}</th>' for heading in headings)
    rows = []
    for cpu_series, memory_series in zip(cpu, memory, strict=True):
        cells = (
            _cell(cpu_series, "request", risks[0]),
            _cell(cpu_series, "limit", risks[1]),
            _cell(memory_series, "request", risks[2]),
            _cell(memory_series, "limit", risks[3]),
        )
        rows.append(
            f'<tr><td>{html.escape(cpu_series.pod_id)}</td>'
            f'<td>{html.escape(cpu_series.assigned_node)}</td>{"".join(cells)}</tr>'
        )
    return f'<table><thead><tr>{header}</tr></thead><tbody>{"".join(rows)}</tbody></table>'
