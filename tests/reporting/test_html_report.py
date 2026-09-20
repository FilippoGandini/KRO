"""Smoke tests for the portable static report."""

import base64
import re
from datetime import UTC, datetime
from pathlib import Path
from unittest.mock import Mock
from xml.etree import ElementTree

import pytest
from conftest import REPORT_CONFIG, SolvedProblem

from kubernetes_resource_optimizer.reporting import generate_html_report, html_report
from kubernetes_resource_optimizer.solution import extract_solution


def test_generates_only_dated_html_with_embedded_charts(
    tmp_path: Path, solved_report_problem: SolvedProblem, monkeypatch: pytest.MonkeyPatch
) -> None:
    clock = Mock(wraps=datetime)
    clock.now.return_value = datetime(2027, 1, 2, 12, tzinfo=UTC).astimezone()
    monkeypatch.setattr(html_report, "datetime", clock)
    data, built, solver_result = solved_report_problem
    result = extract_solution(data, built, solver_result)

    index = generate_html_report(data, result, REPORT_CONFIG, tmp_path / "report")

    assert index.is_file()
    assert index.name == "report_20270102.html"
    assert list(index.parent.iterdir()) == [index]
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
    # Every image must carry the complete SVG, with no companion-file dependency.
    sources = re.findall(r'<img src="([^"]+)"', document)
    assert len(sources) == 3
    assert all(source.startswith("data:image/svg+xml;base64,") for source in sources)
    charts = [base64.b64decode(source.split(",", 1)[1], validate=True) for source in sources]
    assert all(ElementTree.fromstring(chart).tag == "{http://www.w3.org/2000/svg}svg"
               for chart in charts)
    assert b"Node node-a" in charts[0]
    assert b"Workload pod-a" in charts[1]
    assert b"Workload pod-b" in charts[2]


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
    sources = re.findall(r'<img src="([^"]+)"', document)
    charts = [base64.b64decode(source.split(",", 1)[1]).decode() for source in sources]
    svg = next(chart for chart in charts if "Workload pod-a" in chart)
    assert "Current request (0% coverage)" in svg
    assert "Current limit (50% coverage)" in svg
    assert "Recommended limit (100% coverage)" in svg
    other_svg = next(chart for chart in charts if "Workload pod-b" in chart)
    assert "Current request" not in other_svg
