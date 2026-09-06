"""Shared solved instance for reporting tests."""

from datetime import UTC, datetime, timedelta

import pytest

from kubernetes_resource_optimizer.data.models import (
    InputData,
    Node,
    Pod,
    Resource,
    UsageSample,
)
from kubernetes_resource_optimizer.optimization.config import OptimizationConfig
from kubernetes_resource_optimizer.optimization.model import (
    OptimizationModel,
    build_model,
)
from kubernetes_resource_optimizer.optimization.objectives.lexicographic import (
    solve_lexicographic,
)
from kubernetes_resource_optimizer.optimization.solver import (
    CbcSolver,
    SolverResult,
    SolverStatus,
)

REPORT_CONFIG = OptimizationConfig(0.5, 0.5, 0.5, 0.5, 2.0, 2.0)
SolvedProblem = tuple[InputData, OptimizationModel, SolverResult]


@pytest.fixture
def solved_report_problem() -> SolvedProblem:
    """Return a deterministic solved problem with fixed rightsizing values."""

    start = datetime(2026, 8, 1, tzinfo=UTC)
    data = InputData(
        nodes=(Node("node-a", 4.0, 4000.0), Node("node-b", 4.0, 4000.0)),
        pods=(
            Pod(
                "pod-a",
                cpu_request_max=4.0,
                memory_request_max=4000.0,
                cpu_limit_max=4.0,
                memory_limit_max=4000.0,
            ),
            Pod(
                "pod-b",
                cpu_request_max=4.0,
                memory_request_max=4000.0,
                cpu_limit_max=4.0,
                memory_limit_max=4000.0,
            ),
        ),
        usage_samples=(
            UsageSample(start, "pod-a", 1.0, 100.0),
            UsageSample(start, "pod-b", 0.5, 200.0),
            UsageSample(start + timedelta(hours=1), "pod-a", 3.0, 300.0),
            UsageSample(start + timedelta(hours=1), "pod-b", 1.0, 400.0),
        ),
    )
    built = build_model(data, REPORT_CONFIG)
    fixed_values = {
        ("pod-a", Resource.CPU, "request"): 2.0,
        ("pod-a", Resource.MEMORY, "request"): 250.0,
        ("pod-a", Resource.CPU, "limit"): 3.0,
        ("pod-a", Resource.MEMORY, "limit"): 350.0,
        ("pod-b", Resource.CPU, "request"): 1.0,
        ("pod-b", Resource.MEMORY, "request"): 300.0,
        ("pod-b", Resource.CPU, "limit"): 1.5,
        ("pod-b", Resource.MEMORY, "limit"): 500.0,
    }
    for (pod_id, resource, family), value in fixed_values.items():
        variable = (
            built.variables.request[pod_id, resource]
            if family == "request"
            else built.variables.limit[pod_id, resource]
        )
        built.problem.addConstraint(
            variable == value, f"fix_report_{family}_{pod_id}_{resource.value}"
        )
    solver_result = solve_lexicographic(built, CbcSolver())
    assert solver_result.status is SolverStatus.OPTIMAL
    return data, built, solver_result
