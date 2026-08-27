"""Matplotlib chart generation with a headless, cross-platform backend."""

from datetime import datetime
from pathlib import Path

import matplotlib

matplotlib.use("Agg")

import matplotlib.pyplot as plt

from kubernetes_resource_optimizer.data.models import Resource
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
    axis.set_xticks(positions)
    axis.set_xticklabels(
        [timestamps[index].strftime("%Y-%m-%d\n%H:%M") for index in positions],
        rotation=30,
        ha="right",
    )
    axis.set_xlabel("Historical scenario")


def save_node_chart(cpu: NodeSeries, memory: NodeSeries, destination: Path) -> None:
    """Save one two-panel active-node allocation chart as SVG."""

    figure, axes = plt.subplots(2, 1, figsize=(12, 9), constrained_layout=True)
    for axis, series in zip(axes, (cpu, memory), strict=True):
        x_values = list(range(len(series.timestamps)))
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
            series.capacity, color="#C62828", linewidth=2, label="Node capacity"
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
            color="#EF6C00",
            linestyle="-.",
            linewidth=1.5,
            label="Limit overcommit boundary",
        )
        axis.set_title(f"{series.resource.value.upper()} allocation")
        axis.set_ylabel(_unit(series.resource))
        axis.set_ylim(bottom=0)
        axis.grid(axis="y", alpha=0.25)
        _configure_scenario_axis(axis, series.timestamps)
        axis.legend(loc="upper left", bbox_to_anchor=(1.01, 1), fontsize="small")
    figure.suptitle(f"Node {cpu.node_id}: effective demand by scenario", fontsize=15)
    figure.savefig(destination, format="svg", bbox_inches="tight")
    plt.close(figure)


def save_workload_chart(
    cpu: WorkloadSeries, memory: WorkloadSeries, destination: Path
) -> None:
    """Save one two-panel workload usage/request/limit chart as SVG."""

    figure, axes = plt.subplots(2, 1, figsize=(12, 8), constrained_layout=True)
    for axis, series in zip(axes, (cpu, memory), strict=True):
        x_values = list(range(len(series.timestamps)))
        axis.plot(
            x_values,
            series.usage,
            color="#37474F",
            marker="o",
            markersize=3,
            label="Usage",
        )
        axis.axhline(
            series.request,
            color="#1565C0",
            linestyle="--",
            linewidth=1.8,
            label="Recommended request",
        )
        axis.axhline(
            series.limit,
            color="#6A1B9A",
            linestyle=":",
            linewidth=2,
            label="Recommended limit",
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
                request_x,
                [series.usage[index] for index in request_x],
                color="#EF6C00",
                s=30,
                zorder=3,
                label="Request violation",
            )
        if limit_x:
            axis.scatter(
                limit_x,
                [series.usage[index] for index in limit_x],
                color="#C62828",
                marker="x",
                s=55,
                zorder=4,
                label="Limit violation",
            )
        axis.set_title(series.resource.value.upper())
        axis.set_ylabel(_unit(series.resource))
        axis.set_ylim(bottom=0)
        axis.grid(axis="y", alpha=0.25)
        _configure_scenario_axis(axis, series.timestamps)
        axis.legend(loc="upper left", bbox_to_anchor=(1.01, 1), fontsize="small")
    figure.suptitle(f"Workload {cpu.workload_id} on {cpu.assigned_node}", fontsize=15)
    figure.savefig(destination, format="svg", bbox_inches="tight")
    plt.close(figure)
