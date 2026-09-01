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
    document = index.read_text(encoding="utf-8")
    assert "max(historical usage, recommended request)" in document
    assert "Optimization settings" in document
    assert "<td>Solver</td><td>CBC</td>" in document
    assert "CPU request risk tolerance" in document
    assert "50.00%" in document
    assert "2×" in document
    assert "epsilon" not in document
    assert "Historical period" in document
    assert "Scenario interval (inferred)" in document
    assert "1h" in document
    assert "Selected nodes" in document
    assert "CPU capacity (cores)" in document
    assert "Memory capacity (MiB)" in document
    assert "pod-a" in document
    assert len(tuple((index.parent / "nodes").glob("*.svg"))) == 1
    assert len(tuple((index.parent / "workloads").glob("*.svg"))) == 2
