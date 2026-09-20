"""Regression coverage for elapsed-time chart coordinates."""

from datetime import UTC, datetime, timedelta
from pathlib import Path

import matplotlib.dates as mdates
import matplotlib.pyplot as plt
import pytest
from matplotlib.figure import Figure

from kubernetes_resource_optimizer.data.models import Resource
from kubernetes_resource_optimizer.reporting.charts import save_pod_chart
from kubernetes_resource_optimizer.reporting.series import PodSeries


def test_irregular_timestamps_position_usage_and_violations(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    start = datetime(2026, 8, 1, tzinfo=UTC)
    timestamps = (start, start + timedelta(hours=1), start + timedelta(hours=4))
    captured: list[plt.Axes] = []

    def capture(figure: Figure, *args: object, **kwargs: object) -> None:
        captured.extend(figure.axes)

    monkeypatch.setattr(Figure, "savefig", capture)
    cpu = PodSeries("pod", "node", Resource.CPU, timestamps, (1, 3, 5), 2, 4)
    memory = PodSeries("pod", "node", Resource.MEMORY, timestamps, (1, 3, 5), 2, 4)
    save_pod_chart(cpu, memory, tmp_path / "chart.svg")
    expected = mdates.date2num(timestamps)
    for axis in captured:
        assert axis.lines[0].get_xdata() == pytest.approx(expected, rel=0, abs=1e-10)
        assert axis.collections[0].get_offsets()[:, 0].tolist() == pytest.approx(expected[1:], rel=0, abs=1e-10)
        assert axis.collections[1].get_offsets()[:, 0].tolist() == pytest.approx(expected[2:], rel=0, abs=1e-10)
        assert axis.get_xticks() == pytest.approx(expected, rel=0, abs=1e-10)
        assert axis.get_xlabel() == "Time (UTC)"
