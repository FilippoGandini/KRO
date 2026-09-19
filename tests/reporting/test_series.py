"""Tests for solver-independent reporting series."""

from conftest import REPORT_CONFIG, SolvedProblem

from kubernetes_resource_optimizer.data.models import Resource
from kubernetes_resource_optimizer.reporting.series import build_node_series
from kubernetes_resource_optimizer.solution import extract_solution


def test_node_series_uses_maximum_of_usage_and_request(
    solved_report_problem: SolvedProblem,
) -> None:
    data, built, solver_result = solved_report_problem
    result = extract_solution(data, built, solver_result)

    series = build_node_series(
        data, result, Resource.CPU, REPORT_CONFIG.cpu_limit_overcommit
    )

    assert len(series) == 1
    by_workload = dict(
        zip(series[0].workload_ids, series[0].effective_demand, strict=True)
    )
    assert by_workload["pod-a"] == (2.0, 3.0)
    assert by_workload["pod-b"] == (1.0, 1.0)
    assert series[0].total_effective_demand == (3.0, 4.0)
    assert series[0].capacity == 4.0
    assert series[0].aggregate_request == 3.0
    assert series[0].aggregate_limit == 4.5
    assert series[0].limit_boundary == 8.0


def test_coverage_includes_ties_and_numeric_tolerance() -> None:
    from kubernetes_resource_optimizer.reporting.series import WorkloadSeries

    series = WorkloadSeries("pod", "node", Resource.CPU, (),
                            (0.0, 1.0, 1.0 + 5e-8, 1.0 + 2e-7), 1.0, 2.0)
    assert series.coverage(1.0) == 0.75
    assert series.coverage(0.0) == 0.25
    assert series.coverage(2.0) == 1.0
