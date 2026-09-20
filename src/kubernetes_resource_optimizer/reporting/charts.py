"""Matplotlib chart generation with a headless, cross-platform backend."""

from datetime import UTC, datetime
from io import BytesIO
from pathlib import Path

import matplotlib

matplotlib.use("Agg")

import matplotlib.dates as mdates
import matplotlib.pyplot as plt
from matplotlib.ticker import StrMethodFormatter

from kubernetes_resource_optimizer.data.models import Resource
from kubernetes_resource_optimizer.reporting.formatting import format_percent
from kubernetes_resource_optimizer.reporting.series import (
    NodeSeries,
    WorkloadSeries,
)

_COLORS = (
    "#4C78A8",
    "#F58518",
    "#54A24B",
    "#E45756",
    "#72B7B2",
    "#B279A2",
    "#FF9DA6",
    "#9D755D",
)


def _unit(resource: Resource) -> str:
    return "cores" if resource is Resource.CPU else "MiB"


def _configure_scenario_axis(axis: plt.Axes, timestamps: tuple[datetime, ...]) -> None:
    count = len(timestamps)
    if count == 0:
        return
    step = max(1, count // 8)
    positions = list(range(0, count, step))
    if positions[-1] != count - 1:
        positions.append(count - 1)
    axis.set_xticks(mdates.date2num([timestamps[index] for index in positions]))
    axis.set_xticklabels(
        [timestamps[index].astimezone(UTC).strftime("%Y-%m-%d\n%H:%M") for index in positions],
        rotation=30,
        ha="right",
    )
    axis.set_xlabel("Time (UTC)")


def save_node_chart(cpu: NodeSeries, memory: NodeSeries, destination: Path | BytesIO) -> None:
    """Save one two-panel active-node allocation chart as SVG."""

    figure, axes = plt.subplots(2, 1, figsize=(12, 9), constrained_layout=True)
    for axis, series in zip(axes, (cpu, memory), strict=True):
        x_values = mdates.date2num(series.timestamps)
        if series.effective_demand:
            axis.stackplot(
                x_values,
                *series.effective_demand,
                labels=series.workload_ids,
                colors=[
                    _COLORS[index % len(_COLORS)]
                    for index in range(len(series.workload_ids))
                ],
                alpha=0.82,
            )
        axis.axhline(
            series.capacity, color="#455A64", linewidth=2, label="Node capacity"
        )
        axis.axhline(
            series.aggregate_request,
            color="#1565C0",
            linestyle="--",
            linewidth=1.5,
            label="Aggregate request",
        )
        axis.axhline(
            series.aggregate_limit,
            color="#6A1B9A",
            linestyle=":",
            linewidth=1.8,
            label="Aggregate limit",
        )
        axis.axhline(
            series.limit_boundary,
            color="#607D8B",
            linestyle="-.",
            linewidth=1.5,
            label="Limit overcommit boundary",
        )
        axis.set_title(f"{series.resource.value.upper()} allocation")
        axis.set_ylabel(_unit(series.resource))
        axis.yaxis.set_major_formatter(StrMethodFormatter("{x:g}"))
        axis.set_ylim(bottom=0)
        axis.grid(axis="y", alpha=0.25)
        _configure_scenario_axis(axis, series.timestamps)
        axis.legend(loc="upper left", bbox_to_anchor=(1.01, 1), fontsize="small")
    figure.suptitle(f"Node {cpu.node_id}: effective demand by scenario", fontsize=15)
    figure.savefig(destination, format="svg", bbox_inches="tight")
    plt.close(figure)


def save_workload_chart(
    cpu: WorkloadSeries, memory: WorkloadSeries, destination: Path | BytesIO
) -> None:
    """Save one two-panel workload usage/request/limit chart as SVG."""

    figure, axes = plt.subplots(2, 1, figsize=(12, 8), constrained_layout=True)
    for axis, series in zip(axes, (cpu, memory), strict=True):
        x_values = mdates.date2num(series.timestamps)
        axis.plot(
            x_values,
            series.usage,
            color="#37474F",
            marker="o",
            markersize=3,
            label="Usage",
        )
        comparison = series.current_request is not None or series.current_limit is not None
        for boundary, label, color, style in (
            (series.current_request, "Current request", "#64A5E8", "--"),
            (series.current_limit, "Current limit", "#B47ACF", ":"),
        ):
            if boundary is not None:
                axis.axhline(
                    boundary, color=color, linestyle=style, linewidth=2.6,
                    label=f"{label} ({format_percent(series.coverage(boundary), 1)} coverage)",
                )
        axis.axhline(
            series.request,
            color="#1565C0",
            linestyle="-" if comparison else "--",
            linewidth=1.8,
            label=(f"Recommended request ({format_percent(series.coverage(series.request), 1)} coverage)"
                   if comparison else "Recommended request"),
        )
        axis.axhline(
            series.limit,
            color="#6A1B9A",
            linestyle="-",
            linewidth=2,
            label=(f"Recommended limit ({format_percent(series.coverage(series.limit), 1)} coverage)"
                   if comparison else "Recommended limit"),
        )
        request_x = [
            index
            for index, value in enumerate(series.usage)
            if value > series.request + 1e-7
        ]
        limit_x = [
            index
            for index, value in enumerate(series.usage)
            if value > series.limit + 1e-7
        ]
        if request_x:
            axis.scatter(
                [x_values[index] for index in request_x],
                [series.usage[index] for index in request_x],
                color="#EF6C00",
                s=30,
                zorder=3,
                label="Recommended request violation" if comparison else "Request violation",
            )
        if limit_x:
            axis.scatter(
                [x_values[index] for index in limit_x],
                [series.usage[index] for index in limit_x],
                color="#C62828",
                marker="x",
                s=55,
                zorder=4,
                label="Recommended limit violation" if comparison else "Limit violation",
            )
        axis.set_title(series.resource.value.upper())
        axis.set_ylabel(_unit(series.resource))
        axis.yaxis.set_major_formatter(StrMethodFormatter("{x:g}"))
        axis.set_ylim(bottom=0)
        axis.grid(axis="y", alpha=0.25)
        _configure_scenario_axis(axis, series.timestamps)
        axis.legend(loc="upper left", bbox_to_anchor=(1.01, 1), fontsize="small")
    figure.suptitle(f"Pod {cpu.workload_id} on {cpu.assigned_node}", fontsize=15)
    figure.savefig(destination, format="svg", bbox_inches="tight")
    plt.close(figure)
