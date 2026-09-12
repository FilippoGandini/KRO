"""Hard historical caps, zero histories, and deterministic request compatibility."""

from dataclasses import replace
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
from kubernetes_resource_optimizer.optimization.model import build_model
from kubernetes_resource_optimizer.optimization.objectives.lexicographic import (
    solve_lexicographic,
)
from kubernetes_resource_optimizer.optimization.solver import (
    CbcSolver,
    HighsSolver,
    SolverStatus,
)

CONFIG = OptimizationConfig(0.5, 0.5, 0, 0, 2, 2)


def source() -> InputData:
    return InputData(
        (Node("n", 100, 10000),),
        (Pod("p"),),
        tuple(
            UsageSample(
                datetime(2026, 1, 1, tzinfo=UTC) + timedelta(hours=t), "p", cpu, memory
            )
            for t, (cpu, memory) in enumerate([(1, 100), (4, 400)])
        ),
    )


@pytest.mark.parametrize("solver_type", [HighsSolver, CbcSolver])
@pytest.mark.parametrize("multiplier", [1, 1.5, 2])
def test_reward_reaches_configured_hard_cap(solver_type, multiplier) -> None:
    model = build_model(source(), replace(CONFIG, limit_peak_multiplier=multiplier))
    result = solve_lexicographic(model, solver_type())
    assert result.status is SolverStatus.OPTIMAL
    assert model.requests["p", Resource.CPU] == 1
    assert model.variables.limit["p", Resource.CPU].varValue == pytest.approx(
        4 * multiplier
    )
    assert model.variables.limit["p", Resource.MEMORY].varValue == pytest.approx(
        400 * multiplier
    )
    model.problem.addConstraint(
        model.variables.limit["p", Resource.CPU] >= 4 * multiplier + 0.1
    )
    assert solver_type().solve(model.problem).status is SolverStatus.INFEASIBLE


def test_supplied_limit_bound_still_applies() -> None:
    data = replace(source(), pods=(Pod("p", cpu_limit_max=5),))
    model = build_model(data, CONFIG)
    assert solve_lexicographic(model, HighsSolver()).status is SolverStatus.OPTIMAL
    assert model.variables.limit["p", Resource.CPU].varValue == pytest.approx(5)


def test_request_upper_below_coverage_is_infeasible() -> None:
    data = replace(source(), pods=(Pod("p", cpu_request_max=0.5),))
    model = build_model(data, CONFIG)
    assert solve_lexicographic(model, HighsSolver()).status is SolverStatus.INFEASIBLE


def test_replica_common_request_uses_largest_service_cap() -> None:
    data = source()
    samples = tuple(
        replace(s, pod_id="other", cpu_usage=0.1) for s in data.usage_samples
    )
    data = replace(
        data,
        pods=(Pod("p", service_id="s"), Pod("other", service_id="s")),
        usage_samples=data.usage_samples + samples,
    )
    model = build_model(data, CONFIG)
    assert (
        model.requests["p", Resource.CPU] == model.requests["other", Resource.CPU] == 1
    )
    assert solve_lexicographic(model, HighsSolver()).status is SolverStatus.OPTIMAL
    assert model.variables.limit["other", Resource.CPU].upBound == 6
    assert (
        model.variables.limit["other", Resource.CPU].varValue
        == model.variables.limit["p", Resource.CPU].varValue
    )


@pytest.mark.parametrize("solver_type", [HighsSolver, CbcSolver])
def test_zero_history_has_zero_caps_even_with_fairness(solver_type) -> None:
    data = source()
    data = replace(
        data,
        usage_samples=tuple(
            replace(s, cpu_usage=0, memory_usage=0) for s in data.usage_samples
        ),
    )
    model = build_model(data, replace(CONFIG, fairness=True))
    result = solve_lexicographic(model, solver_type())
    assert result.lexicographic_complete
    assert all(v.varValue == 0 for v in model.variables.limit.values())
    assert all(v.varValue == 0 for v in model.variables.minimum_limit_headroom.values())
