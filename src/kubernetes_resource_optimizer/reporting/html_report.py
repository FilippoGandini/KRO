"""Generation of a self-contained static HTML index and SVG charts."""

from __future__ import annotations

import hashlib
import html
import re
from collections.abc import Sequence
from datetime import UTC, datetime, timedelta
from itertools import pairwise
from pathlib import Path

from kubernetes_resource_optimizer.data.models import InputData, Resource
from kubernetes_resource_optimizer.optimization.config import OptimizationConfig
from kubernetes_resource_optimizer.reporting.charts import (
    save_node_chart,
    save_workload_chart,
)
from kubernetes_resource_optimizer.reporting.comparison import (
    NOTE,
    STYLES,
    comparison_table,
)
from kubernetes_resource_optimizer.reporting.formatting import (
    format_number,
    format_percent,
)
from kubernetes_resource_optimizer.reporting.impact import STYLES as IMPACT_STYLES
from kubernetes_resource_optimizer.reporting.impact import impact_section
from kubernetes_resource_optimizer.reporting.series import (
    build_node_series,
    build_workload_series,
)
from kubernetes_resource_optimizer.solution.models import OptimizationResult


def _format_memory(memory_mib: float, *, fixed_precision: bool = False) -> str:
    """Choose a binary memory unit independently for each table cell."""
    if fixed_precision:
        if memory_mib >= 1024:
            return f"{format_number(memory_mib / 1024)} GiB"
        return f"{format_number(memory_mib)} MiB"
    precision = "g"
    if memory_mib >= 1024:
        return f"{memory_mib / 1024:{precision}} GiB"
    return f"{memory_mib:{precision}} MiB"


def _filename(identifier: str) -> str:
    slug = re.sub(r"[^A-Za-z0-9._-]+", "-", identifier).strip("-.") or "item"
    digest = hashlib.sha256(identifier.encode()).hexdigest()[:8]
    return f"{slug}-{digest}.svg"


def _table(
    rows: Sequence[tuple[str, ...]],
    headings: tuple[str, ...],
    *,
    column_groups: tuple[tuple[str, tuple[str, ...]], ...] = (),
) -> str:
    rowspan = ' rowspan="2"' if column_groups else ""
    header = "".join(
        f'<th scope="col"{rowspan}>{html.escape(value)}</th>' for value in headings
    )
    header += "".join(
        f'<th scope="colgroup" colspan="{len(children)}">{html.escape(label)}</th>'
        for label, children in column_groups
    )
    header = f"<tr>{header}</tr>"
    if column_groups:
        subheader = "".join(
            f'<th scope="col">{html.escape(child)}</th>'
            for _, children in column_groups
            for child in children
        )
        header += f"<tr>{subheader}</tr>"
    body = "".join(
        "<tr>" + "".join(f"<td>{html.escape(value)}</td>" for value in row) + "</tr>"
        for row in rows
    )
    return f"<table><thead>{header}</thead><tbody>{body}</tbody></table>"


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


def _historical_period(timestamps: Sequence[datetime]) -> str:
    """Show compact start and end dates and times in a consistent timezone."""

    start = timestamps[0].astimezone(UTC)
    end = timestamps[-1].astimezone(UTC)
    if start == end:
        return f"{start:%d %b %Y}, {start:%H:%M} UTC"
    if start.date() == end.date():
        return f"{start:%d %b %Y}, {start:%H:%M}–{end:%H:%M} UTC"
    return f"{start:%d %b %Y, %H:%M} – {end:%d %b %Y, %H:%M} (UTC)"


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
    period = _historical_period(timestamps)
    summary = _table(
        [
            ("Solver", result.solver.display_name),
            ("Solver status", result.solver_status.value),
            ("Active nodes", f"{result.active_node_count}/{len(result.nodes)}"),
            ("Total node cost", f"{result.total_node_cost:g}"),
            ("Last solved objective value", f"{result.objective_value:g}"),
            ("Lexicographic optimization complete", str(result.lexicographic_complete)),
            ("Optimization message", result.optimization_message),
            *(
                (
                    f"Phase: {stage.name}",
                    f"{stage.status.value}; value={stage.objective_value}; gap={stage.mip_gap}; bound={stage.best_bound}; {format_number(stage.solve_time_seconds)} s",
                )
                for stage in result.stages
            ),
            ("Solve time", f"{format_number(result.solve_time_seconds)} s"),
            (
                "Model size",
                (
                    f"{format_number(result.model_variable_count, 0)} variables - "
                    f"{format_number(result.model_constraint_count, 0)} constraints"
                ),
            ),
            ("Historical period", period),
            ("Historical scenarios", str(len(timestamps))),
            ("Scenario interval (inferred)", _scenario_interval(data)),
        ],
        ("Metric", "Value"),
    )
    violations = {(item.workload_id, item.resource): item for item in result.violations}
    workload_rows = [
        (
            workload.workload_id,
            workload.assigned_node,
            f"{format_number(workload.recommended_cpu_request)}",
            f"{format_number(workload.recommended_cpu_limit)}",
            _format_memory(workload.recommended_memory_request, fixed_precision=True),
            _format_memory(workload.recommended_memory_limit, fixed_precision=True),
            *(
                f"{format_percent(violations[workload.workload_id, resource].request_violation_rate, 2)}"
                for resource in (Resource.CPU, Resource.MEMORY)
            ),
            *(
                f"{format_percent(violations[workload.workload_id, resource].limit_violation_rate, 2)}"
                for resource in (Resource.CPU, Resource.MEMORY)
            ),
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
            "Memory request",
            "Memory limit",
        ),
        column_groups=(
            ("Request violations", ("CPU", "Memory")),
            ("Limit violations", ("CPU", "Memory")),
        ),
    )
    has_current = any(
        item.current_request is not None or item.current_limit is not None
        for item in (*workload_cpu, *workload_memory)
    )
    if has_current:
        workload_table = comparison_table(
            workload_cpu, workload_memory,
            (config.epsilon_cpu_request, config.epsilon_cpu_limit,
             config.epsilon_memory_request, config.epsilon_memory_limit),
        )
    settings_table = _table(
        [
            (
                "Limit peak multiplier",
                str(config.limit_peak_multiplier),
                "Hard limit cap relative to each pod historical maximum.",
            ),
            *(
                [
                    (
                        "Fairness MIP gap",
                        f"{format_percent(config.fairness_mip_gap, 2)}",
                        "Relative optimality gap accepted only in the optional fairness phase.",
                    )
                ]
                if config.fairness
                else []
            ),
            (
                "Limits MIP gap",
                f"{format_percent(config.limits_mip_gap, 2)}",
                "Relative optimality gap accepted in the final weighted-limit phase.",
            ),
            (
                "Fairness",
                "Enabled" if config.fairness else "Disabled",
                "Preserve achieved minimum-headroom score before optimizing demand-weighted limits.",
            ),
            (
                "CPU request risk tolerance",
                f"{format_percent(config.epsilon_cpu_request, 2)}",
                "Maximum historical CPU exceedance share. Choose conservatively: requests are calculated deterministically from coverage.",
            ),
            (
                "Memory request risk tolerance",
                f"{format_percent(config.epsilon_memory_request, 2)}",
                "Maximum historical memory exceedance share. Choose conservatively: requests are calculated deterministically from coverage.",
            ),
            (
                "CPU limit risk tolerance",
                f"{format_percent(config.epsilon_cpu_limit, 2)}",
                "Maximum share of historical scenarios in which CPU usage may exceed the recommended limit.",
            ),
            (
                "Memory limit risk tolerance",
                f"{format_percent(config.epsilon_memory_limit, 2)}",
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
                _format_memory(node.memory_capacity),
                f"{node.cost:g}",
            )
            for node in data.nodes
            if node.node_id in active_node_ids
        ],
        ("Node", "CPU capacity (cores)", "Memory capacity", "Cost"),
    )
    node_bars: list[str] = []
    for cpu, memory in zip(node_cpu, node_memory, strict=True):
        bars = []
        for series in (cpu, memory):
            peak = max(series.total_effective_demand, default=0.0)
            ratio = peak / series.capacity
            remaining = series.capacity - peak
            margin = (
                f"{format_number(remaining)} cores"
                if series.resource is Resource.CPU
                else _format_memory(remaining)
            )
            alert = " alert" if ratio > 1 + 1e-7 else ""
            bars.append(
                f'<div class="node-bar{alert}"><span>{series.resource.value.upper()}: '
                f'{format_percent(ratio, 1)} · Remaining: {margin}</span>'
                f'<div class="bar-track"><div class="bar-fill" '
                f'style="width:{min(100, max(0, ratio * 100)):.4f}%"></div></div></div>'
            )
        node_bars.append(f'<div class="node-comparison-row"><strong>{html.escape(cpu.node_id)}</strong><div class="node-resources">{"".join(bars)}</div></div>')
    node_comparison = '<div class="node-comparison"><p>Peak effective demand / capacity</p>' + "".join(node_bars) + '</div>'
    node_options = "".join(
        f'<option value="{html.escape(identifier, quote=True)}">{html.escape(identifier)}</option>'
        for identifier in sorted(active_node_ids)
    )
    node_sections = "".join(
        f'<section><h3>{html.escape(identifier)}</h3><img src="{html.escape(path)}" alt="Node {html.escape(identifier)} allocation chart"></section>'
        for identifier, path in node_images
    )
    workload_sections = "".join(
        f'<section><h3>{html.escape(identifier)}</h3><img src="{html.escape(path)}" alt="Workload {html.escape(identifier)} usage chart"></section>'
        for identifier, path in workload_images
    )
    report_title = html.escape(f"KRO Report: {output_directory.resolve().name}")
    document = f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>{report_title}</title>
<style>
body{{font-family:system-ui,-apple-system,"Segoe UI",sans-serif;max-width:1500px;margin:auto;padding:2rem;color:#263238;background:#f5f5f5}}
h1,h2,h3{{color:#102A43}} section{{background:white;padding:1rem 1.25rem;margin:1rem 0;border:1px solid #dfe3e6;border-radius:8px}}
table{{border-collapse:collapse;width:100%;background:white;margin:1rem 0}} th,td{{border:1px solid #dfe3e6;padding:.55rem;text-align:center}} th{{background:#eef3f7}}
img{{display:block;max-width:100%;height:auto;margin:auto}} .note{{padding:.8rem 1rem;background:#eceff1;border-left:4px solid #78909c}}
.selected-nodes{{display:grid;grid-template-columns:minmax(0,1fr) minmax(0,1fr);gap:1.5rem;align-items:center}}
.selected-nodes table{{margin:0}}
.node-comparison{{background:white;padding:1rem;border:1px solid #dfe3e6;border-radius:8px}}
.node-comparison>p{{margin:0 0 .8rem}} .node-comparison-row+ .node-comparison-row{{border-top:1px solid #e5e7eb;margin-top:.75rem;padding-top:.75rem}}
.node-resources{{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:1rem}} .node-bar{{margin:.4rem 0 0;min-width:0}} .node-bar span{{display:block;font-size:.85rem;line-height:1.5;margin-bottom:.25rem}} .bar-track{{height:12px;background:#e5e7eb;border-radius:3px;overflow:hidden}} .bar-fill{{height:100%;background:#4C78A8}} .alert .bar-fill{{background:#C62828}}
.table-controls{{display:flex;gap:1rem;align-items:center;flex-wrap:wrap}} input,select{{font:inherit;padding:.4rem}}
.table-scroll{{max-height:650px;overflow:auto}} #recommendations table{{margin:0}} #recommendations thead{{position:sticky;top:0;z-index:1;background:#eef3f7}}
#recommendations td{{text-align:right;font-variant-numeric:tabular-nums}} #recommendations td:nth-child(-n+2){{text-align:left}}
#recommendations th button{{font:inherit;font-weight:600;color:inherit;border:0;background:transparent;cursor:pointer;width:100%}}
.chart-tabs{{display:flex;gap:.25rem;margin-top:1.25rem;border-bottom:2px solid #dfe3e6}}
.chart-tabs button{{flex:1;padding:.8rem 1rem;font:inherit;font-weight:600;border:0;border-radius:6px 6px 0 0;background:#e8edf2;color:#52616b;cursor:pointer}}
.chart-tabs button[aria-selected="true"]{{background:#1565C0;color:white}}
.chart-tabs button:focus-visible{{outline:3px solid #102A43;outline-offset:2px}}
.chart-panel[hidden]{{display:none}}
@media print{{.chart-tabs{{display:none}}.chart-panel[hidden]{{display:block}}}}
@media(max-width:900px){{.selected-nodes{{grid-template-columns:1fr}}}}
@media(max-width:500px){{.node-resources{{grid-template-columns:1fr;gap:.5rem}}}}
{STYLES + IMPACT_STYLES if has_current else ""}
</style></head><body>
<h1>{report_title}</h1>
<h2>Summary</h2>{summary}
<h2>Optimization settings</h2>{settings_table}
<h2>Selected nodes</h2><div class="selected-nodes"><div>{selected_nodes_table}</div>{node_comparison}</div>
<p class="note">Effective node demand is computed as <code>max(historical usage, recommended request)</code> for each placed workload. SVG files are portable and can be opened independently.</p>
<h2>Recommendations</h2>
{NOTE if has_current else ""}
<div class="table-controls"><label>Workload <input id="workload-search" type="search" placeholder="Search workload"></label>
<label>Node <select id="node-filter"><option value="">All nodes</option>{node_options}</select></label>
<span id="row-count" role="status"></span></div>
<div id="recommendations" class="table-scroll">{workload_table}</div>
{impact_section(data, result, config, workload_cpu, workload_memory) if has_current else ""}
<div class="chart-tabs" role="tablist" aria-label="Allocation charts">
<button type="button" id="nodes-tab" role="tab" aria-selected="true" aria-controls="nodes-panel" tabindex="0">Nodes</button>
<button type="button" id="workloads-tab" role="tab" aria-selected="false" aria-controls="workloads-panel" tabindex="-1">Workloads</button>
</div>
<div class="chart-panel" id="nodes-panel" role="tabpanel" aria-labelledby="nodes-tab" tabindex="0">
<h2>Active node allocation</h2>{node_sections}</div>
<div class="chart-panel" id="workloads-panel" role="tabpanel" aria-labelledby="workloads-tab" tabindex="0" hidden>
<h2>Workload usage and boundaries</h2>{workload_sections}</div>
<noscript><style>.chart-tabs{{display:none}}.chart-panel[hidden]{{display:block}}</style></noscript>
{_CHART_TABS_SCRIPT}
{_TABLE_SCRIPT}
</body></html>"""
    index = output_directory / "index.html"
    index.write_text(document, encoding="utf-8")
    return index


_TABLE_SCRIPT = r"""<script>
(() => {
  const table = document.querySelector('#recommendations table');
  const rows = Array.from(table.tBodies[0].rows);
  const search = document.getElementById('workload-search');
  const filter = document.getElementById('node-filter');
  const update = () => {
    let count = 0;
    rows.forEach(row => {
      row.hidden = !row.cells[0].textContent.toLowerCase().includes(search.value.toLowerCase()) ||
        (filter.value !== '' && row.cells[1].textContent !== filter.value);
      if (!row.hidden) count++;
    });
    document.getElementById('row-count').textContent = `${count} / ${rows.length} workloads`;
  };
  search.addEventListener('input', update);
  filter.addEventListener('change', update);
  const headings = Array.from(table.querySelectorAll('th[scope="col"]'));
  headings.forEach((heading, column) => {
    const button = document.createElement('button');
    button.type = 'button';
    const label = heading.textContent;
    button.textContent = label + ' ↕';
    heading.textContent = '';
    heading.append(button);
    heading.setAttribute('aria-sort', 'none');
    button.addEventListener('click', () => {
      const ascending = heading.getAttribute('aria-sort') !== 'ascending';
      headings.forEach(item => {
        item.setAttribute('aria-sort', 'none');
        item.firstChild.textContent = item.firstChild.textContent.replace(/ [↕↑↓]$/, ' ↕');
      });
      heading.setAttribute('aria-sort', ascending ? 'ascending' : 'descending');
      button.textContent = label + (ascending ? ' ↑' : ' ↓');
      const value = row => {
        if (row.cells[column].dataset.sort !== undefined) return Number(row.cells[column].dataset.sort);
        const text = row.cells[column].textContent;
        return column < 2 ? text : parseFloat(text.replace(/\s/g, '')) * (text.includes('GiB') ? 1024 : 1);
      };
      rows.sort((a, b) => {
        const x = value(a), y = value(b);
        const order = column < 2 ? x.localeCompare(y, undefined, {numeric:true}) : x - y;
        return ascending ? order : -order;
      });
      rows.forEach(row => table.tBodies[0].append(row));
    });
  });
  update();
})();
</script>"""


_CHART_TABS_SCRIPT = """<script>
(() => {
  const tabs = Array.from(document.querySelectorAll('.chart-tabs [role="tab"]'));
  const activate = selected => {
    tabs.forEach(tab => {
      const active = tab === selected;
      tab.setAttribute('aria-selected', String(active));
      tab.tabIndex = active ? 0 : -1;
      document.getElementById(tab.getAttribute('aria-controls')).hidden = !active;
    });
  };
  tabs.forEach((tab, index) => {
    tab.addEventListener('click', () => activate(tab));
    tab.addEventListener('keydown', event => {
      let next;
      if (event.key === 'ArrowRight') next = (index + 1) % tabs.length;
      else if (event.key === 'ArrowLeft') next = (index + tabs.length - 1) % tabs.length;
      else if (event.key === 'Home') next = 0;
      else if (event.key === 'End') next = tabs.length - 1;
      else return;
      event.preventDefault();
      activate(tabs[next]);
      tabs[next].focus();
    });
  });
})();
</script>"""
