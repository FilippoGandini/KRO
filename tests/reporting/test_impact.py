"""Aggregate comparisons use matched pods and observation-weighted coverage."""

from dataclasses import replace

import pytest

from kubernetes_resource_optimizer.data.models import Resource
from kubernetes_resource_optimizer.reporting.impact import (
    _bars,
    _card,
    aggregate_impact,
)
from kubernetes_resource_optimizer.reporting.series import PodSeries


def test_partial_cohorts_and_pooled_coverage() -> None:
    first = PodSeries("a", "node", Resource.CPU, (), (1, 2, 3), 2, 3, 1, None)
    second = PodSeries("b", "node", Resource.CPU, (), (0,), 1, 2, 0, None)
    missing = PodSeries("c", "node", Resource.CPU, (), (100,), 100, 100)
    impact = aggregate_impact((first, second, missing), "request", 0.5)
    assert impact is not None
    assert (impact.pods, impact.total_pods) == (2, 3)
    assert impact.current == 1
    assert impact.recommended == 3
    assert impact.current_coverage == 0.5
    assert impact.recommended_coverage == 0.75
    assert impact.current_at_risk == 1
    assert impact.recommended_at_risk == 0
    assert aggregate_impact((first, second, missing), "limit", 0.5) is None


def test_zero_base_does_not_fabricate_percentage_and_ties_are_covered() -> None:
    series = PodSeries("a", "node", Resource.CPU, (), (0, 5e-8), 1, 1, 0, 0)
    impact = aggregate_impact((series,), "request", 0)
    assert impact is not None
    assert impact.current_coverage == 1
    assert "base is zero" in _card(impact, Resource.CPU, "request")
    assert "Increase: 1 cores" in _card(impact, Resource.CPU, "request")
    decreased = aggregate_impact((replace(series, current_request=2),), "request", 0)
    assert "Reduction: 1 cores (-50%)" in _card(decreased, Resource.CPU, "request")


def test_bar_scale_preserves_values_above_capacity_and_overcommit() -> None:
    series = PodSeries("a", "node", Resource.CPU, (), (1,), 1, 8, 2, 12)
    impacts = (aggregate_impact((series,), "request", 0),
               aggregate_impact((series,), "limit", 0))
    chart = _bars(Resource.CPU, 4, 2, impacts)
    assert "300%" in chart
    assert "Limit boundary: 8 cores (2×)" in chart
    assert "width:95.2381%" in chart  # 12 / (12 * 1.05), not clipped at capacity.
    assert _bars(Resource.CPU, 4, 2, (None, None)) == ""


@pytest.mark.parametrize("kind", ["request", "limit"])
def test_absent_current_data_produces_no_aggregate(kind: str) -> None:
    series = PodSeries("a", "node", Resource.CPU, (), (1,), 1, 2)
    assert aggregate_impact((series,), kind, 0) is None
