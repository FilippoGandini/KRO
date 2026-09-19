"""Smoke tests for the portable static report."""

from pathlib import Path

from conftest import REPORT_CONFIG, SolvedProblem

from kubernetes_resource_optimizer.reporting import generate_html_report
from kubernetes_resource_optimizer.solution import extract_solution


def test_generates_html_and_svg_charts(
    tmp_path: Path, solved_report_problem: SolvedProblem
) -> None:
    data, built, solver_result = solved_report_problem
    result = extract_solution(data, built, solver_result)

    index = generate_html_report(data, result, REPORT_CONFIG, tmp_path / "report")

    assert index.is_file()
    assert "<title>KRO Report: report</title>" in index.read_text()
    assert "<h1>KRO Report: report</h1>" in index.read_text()
    document = index.read_text(encoding="utf-8")
    assert "max(historical usage, recommended request)" in document
    assert "allocation-impact" not in document
    assert "comparison-key" not in document
    assert "<small>Current</small>" not in document
    assert 'id="nodes-tab" role="tab" aria-selected="true"' in document
    assert 'id="workloads-tab" role="tab" aria-selected="false"' in document
    assert 'aria-labelledby="workloads-tab" tabindex="0" hidden' in document
    assert "Optimization settings" in document
    assert "<td>Solver</td><td>CBC</td>" in document
    assert "CPU request risk tolerance" in document
    assert "50%" in document
    assert "2×" in document
    assert "epsilon" not in document
    assert "Historical period" in document
    assert "Scenario interval (inferred)" in document
    assert "1h" in document
    assert "Selected nodes" in document
    assert "CPU capacity (cores)" in document
    assert "Memory capacity</th>" in document
    assert "<td>3.90625 GiB</td>" in document
    assert "<td>250 MiB</td><td>350 MiB</td>" in document
    assert "CPU request (cores)" in document
    assert "CPU limit (cores)" in document
    assert "pod-a" in document
    assert len(tuple((index.parent / "nodes").glob("*.svg"))) == 1
    assert len(tuple((index.parent / "workloads").glob("*.svg"))) == 2


def test_current_comparison_is_optional_and_handles_partial_values(
    tmp_path: Path, solved_report_problem: SolvedProblem,
) -> None:
    from dataclasses import replace

    data, built, solver_result = solved_report_problem
    result = extract_solution(data, built, solver_result)
    data = replace(data, pods=(
        replace(data.pods[0], current_cpu_request=0.25, current_cpu_limit=2.0,
                current_memory_request=0.0, current_memory_limit=512.0),
        replace(data.pods[1], current_memory_limit=1024.0),
    ))
    index = generate_html_report(data, result, REPORT_CONFIG, tmp_path / "comparison")
    document = index.read_text()
    assert document.index('id="recommendations"') < document.index('id="allocation-impact"')
    assert document.index('id="allocation-impact"') < document.index('class="chart-tabs"')
    assert "1/2 comparable pods" in document
    assert "2/2 comparable pods" in document
    assert "CPU / selected capacity: 4 cores" in document
    assert ">0.25 cores<" in document
    assert ">512 MiB<" in document
    assert ">1 GiB<" in document
    assert ">0 MiB<" in document
    assert "0% coverage · 2/2 exceed" in document
    assert "50% coverage · 1/2 exceed" in document
    assert "100% coverage · 0/2 exceed" in document
    assert 'allocation request current over-risk' in document
    assert 'allocation request recommended exceeded' in document
    assert 'allocation limit current exceeded' in document
    assert '<small>Current</small>—' in document
    assert 'data-sort="2"' in document
    svg = next((index.parent / "workloads").glob("pod-a-*.svg")).read_text()
    assert "Current request (0% coverage)" in svg
    assert "Current limit (50% coverage)" in svg
    assert "Recommended limit (100% coverage)" in svg
    other_svg = next((index.parent / "workloads").glob("pod-b-*.svg")).read_text()
    assert "Current request" not in other_svg
