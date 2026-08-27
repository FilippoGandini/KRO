"""Generation of a self-contained static HTML index and SVG charts."""

from __future__ import annotations

import hashlib
import html
import re
from collections.abc import Sequence
from datetime import timedelta
from itertools import pairwise
from pathlib import Path

from kubernetes_resource_optimizer.data.models import InputData, Resource
from kubernetes_resource_optimizer.optimization.config import OptimizationConfig
from kubernetes_resource_optimizer.reporting.charts import (
    save_node_chart,
    save_workload_chart,
)
from kubernetes_resource_optimizer.reporting.series import (
    build_node_series,
    build_workload_series,
)
from kubernetes_resource_optimizer.solution.models import OptimizationResult


def _filename(identifier: str) -> str:
    slug = re.sub(r"[^A-Za-z0-9._-]+", "-", identifier).strip("-.") or "item"
    digest = hashlib.sha256(identifier.encode()).hexdigest()[:8]
    return f"{slug}-{digest}.svg"


def _table(rows: Sequence[tuple[str, ...]], headings: tuple[str, ...]) -> str:
    header = "".join(f"<th>{html.escape(value)}</th>" for value in headings)
    body = "".join(
        "<tr>" + "".join(f"<td>{html.escape(value)}</td>" for value in row) + "</tr>"
        for row in rows
    )
    return f"<table><thead><tr>{header}</tr></thead><tbody>{body}</tbody></table>"


def _format_duration(duration: timedelta) -> str:
    """Format a positive scenario interval without platform-specific APIs."""

    seconds = int(duration.total_seconds())
    if seconds % 3600 == 0:
        hours = seconds // 3600
        return f"{hours}h"
    if seconds % 60 == 0:
        minutes = seconds // 60
        return f"{minutes}m"
    return f"{seconds}s"


def _scenario_interval(data: InputData) -> str:
    """Describe timestamp spacing without claiming an unknown averaging window."""

    timestamps = sorted({sample.timestamp for sample in data.usage_samples})
    if len(timestamps) < 2:
        return "Not available (single scenario)"
    intervals = tuple(later - earlier for earlier, later in pairwise(timestamps))
    if len(set(intervals)) == 1:
        return _format_duration(intervals[0])
    return (
        f"Variable ({_format_duration(min(intervals))}–"
        f"{_format_duration(max(intervals))})"
    )


def generate_html_report(
    data: InputData,
    result: OptimizationResult,
    config: OptimizationConfig,
    output_directory: Path,
) -> Path:
    """Generate SVG charts plus an HTML report and return the index path."""

    output_directory.mkdir(parents=True, exist_ok=True)
    node_directory = output_directory / "nodes"
    workload_directory = output_directory / "workloads"
    node_directory.mkdir(exist_ok=True)
    workload_directory.mkdir(exist_ok=True)

    node_cpu = build_node_series(
        data, result, Resource.CPU, config.cpu_limit_overcommit
    )
    node_memory = build_node_series(
        data, result, Resource.MEMORY, config.memory_limit_overcommit
    )
    node_images: list[tuple[str, str]] = []
    for node_cpu_item, node_memory_item in zip(node_cpu, node_memory, strict=True):
        filename = _filename(node_cpu_item.node_id)
        save_node_chart(node_cpu_item, node_memory_item, node_directory / filename)
        node_images.append((node_cpu_item.node_id, f"nodes/{filename}"))

    workload_cpu = build_workload_series(data, result, Resource.CPU)
    workload_memory = build_workload_series(data, result, Resource.MEMORY)
    workload_images: list[tuple[str, str]] = []
    for workload_cpu_item, workload_memory_item in zip(
        workload_cpu, workload_memory, strict=True
    ):
        filename = _filename(workload_cpu_item.workload_id)
        save_workload_chart(
            workload_cpu_item, workload_memory_item, workload_directory / filename
        )
        workload_images.append((workload_cpu_item.workload_id, f"workloads/{filename}"))

    timestamps = sorted({sample.timestamp for sample in data.usage_samples})
    period = f"{timestamps[0].isoformat()} to {timestamps[-1].isoformat()}"
    summary = _table(
        [
            ("Solver status", result.solver_status.value),
            ("Active nodes", f"{result.active_node_count}/{len(result.nodes)}"),
            ("Total node cost", f"{result.total_node_cost:g}"),
            ("Objective value", f"{result.objective_value:g}"),
            ("Solve time", f"{result.solve_time_seconds:.3f} s"),
            ("Historical period", period),
            ("Historical scenarios", str(len(timestamps))),
            ("Scenario interval (inferred)", _scenario_interval(data)),
        ],
        ("Metric", "Value"),
    )
    workload_rows = [
        (
            workload.workload_id,
            workload.assigned_node,
            f"{workload.recommended_cpu_request:g}",
            f"{workload.recommended_cpu_limit:g}",
            f"{workload.recommended_memory_request:g}",
            f"{workload.recommended_memory_limit:g}",
        )
        for workload in result.workloads
    ]
    workload_table = _table(
        workload_rows,
        (
            "Workload",
            "Node",
            "CPU request",
            "CPU limit",
            "Memory request (MiB)",
            "Memory limit (MiB)",
        ),
    )
    settings_table = _table(
        [
            (
                "CPU request risk tolerance",
                f"{config.epsilon_cpu_request:.2%}",
                "Maximum share of historical scenarios in which CPU usage may exceed the recommended request.",
            ),
            (
                "Memory request risk tolerance",
                f"{config.epsilon_memory_request:.2%}",
                "Maximum share of historical scenarios in which memory usage may exceed the recommended request.",
            ),
            (
                "CPU limit risk tolerance",
                f"{config.epsilon_cpu_limit:.2%}",
                "Maximum share of historical scenarios in which CPU usage may exceed the recommended limit.",
            ),
            (
                "Memory limit risk tolerance",
                f"{config.epsilon_memory_limit:.2%}",
                "Maximum share of historical scenarios in which memory usage may exceed the recommended limit.",
            ),
            (
                "CPU limit overcommit",
                f"{config.cpu_limit_overcommit:g}×",
                "Maximum aggregate configured CPU limits allowed relative to a node's CPU capacity.",
            ),
            (
                "Memory limit overcommit",
                f"{config.memory_limit_overcommit:g}×",
                "Maximum aggregate configured memory limits allowed relative to a node's memory capacity.",
            ),
        ],
        ("Setting", "Value", "Meaning"),
    )
    active_node_ids = {node.node_id for node in result.nodes if node.active}
    selected_nodes_table = _table(
        [
            (
                node.node_id,
                f"{node.cpu_capacity:g}",
                f"{node.memory_capacity:g}",
                f"{node.cost:g}",
            )
            for node in data.nodes
            if node.node_id in active_node_ids
        ],
        ("Node", "CPU capacity (cores)", "Memory capacity (MiB)", "Cost"),
    )
    node_sections = "".join(
        f'<section><h3>{html.escape(identifier)}</h3><img src="{html.escape(path)}" alt="Node {html.escape(identifier)} allocation chart"></section>'
        for identifier, path in node_images
    )
    workload_sections = "".join(
        f'<section><h3>{html.escape(identifier)}</h3><img src="{html.escape(path)}" alt="Workload {html.escape(identifier)} usage chart"></section>'
        for identifier, path in workload_images
    )
    document = f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>Kubernetes Resource Optimizer report</title>
<style>
body{{font-family:system-ui,-apple-system,"Segoe UI",sans-serif;max-width:1500px;margin:auto;padding:2rem;color:#263238;background:#fafafa}}
h1,h2,h3{{color:#102A43}} section{{background:white;padding:1rem 1.25rem;margin:1rem 0;border:1px solid #dfe3e6;border-radius:8px}}
table{{border-collapse:collapse;width:100%;background:white;margin:1rem 0}} th,td{{border:1px solid #dfe3e6;padding:.55rem;text-align:left}} th{{background:#eef3f7}}
img{{display:block;max-width:100%;height:auto;margin:auto}} .note{{padding:.8rem 1rem;background:#fff8e1;border-left:4px solid #f9a825}}
</style></head><body>
<h1>Kubernetes Resource Optimizer report</h1>
<p class="note">Effective node demand is computed as <code>max(historical usage, recommended request)</code> for each placed workload. SVG files are portable and can be opened independently.</p>
<h2>Summary</h2>{summary}
<h2>Optimization settings</h2>{settings_table}
<h2>Selected nodes</h2>{selected_nodes_table}
<h2>Recommendations</h2>{workload_table}
<h2>Active node allocation</h2>{node_sections}
<h2>Workload usage and boundaries</h2>{workload_sections}
</body></html>"""
    index = output_directory / "index.html"
    index.write_text(document, encoding="utf-8")
    return index
