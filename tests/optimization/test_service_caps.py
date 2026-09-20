"""Shared caps, service rewards, fairness and placed limits remain consistent."""

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


@pytest.mark.parametrize("solver_type", [HighsSolver, CbcSolver])
def test_service_maximum_caps_reward_and_fairness(solver_type) -> None:
    data = InputData(
        (Node("n1", 20, 200), Node("n2", 20, 200)),
        (Pod("a", "s", cpu_limit_max=0.2, memory_limit_max=2), Pod("b", "s")),
        tuple(
            UsageSample(
                datetime(2026, 1, 1, tzinfo=UTC) + timedelta(hours=t), pod, u, u * 10
            )
            for pod, values in [("a", [0, 0]), ("b", [1, 4])]
            for t, u in enumerate(values)
        ),
    )
    model = build_model(data, OptimizationConfig(0.5, 0.5, 0, 0, 2, 2, fairness=True))
    for resource, cap in [(Resource.CPU, 6), (Resource.MEMORY, 60)]:
        assert model.variables.limit["a", resource].upBound == cap
        assert model.variables.limit["b", resource].upBound == cap
        objective = model.stages[-1].expression
        assert objective.get(model.variables.limit["a", resource], 0) == pytest.approx(
            0.75 / cap
        )
        assert objective.get(model.variables.limit["b", resource], 0) == 0
    assert (
        sum(
            name.startswith("minimum_limit_headroom_bound")
            for name in model.problem.constraints
        )
        == 2
    )
    result = solve_lexicographic(model, solver_type())
    assert result.status is SolverStatus.OPTIMAL
    for resource, cap in [(Resource.CPU, 6), (Resource.MEMORY, 60)]:
        for pod in data.pods:
            limit = model.variables.limit[pod.pod_id, resource].varValue
            assert limit == pytest.approx(cap)
            for node in data.nodes:
                placement = model.variables.placement[pod.pod_id, node.node_id].varValue
                assert model.variables.placed_limit[
                    pod.pod_id, node.node_id, resource
                ].varValue == pytest.approx(limit * placement)
        assert model.variables.minimum_limit_headroom[
            resource
        ].varValue == pytest.approx(5 / 6)


def test_singleton_id_does_not_merge_with_service() -> None:
    data = InputData(
        (Node("n", 20, 200),),
        (Pod("s"), Pod("member", "s")),
        (
            UsageSample(datetime(2026, 1, 1, tzinfo=UTC), "s", 1, 10),
            UsageSample(datetime(2026, 1, 1, tzinfo=UTC), "member", 4, 40),
        ),
    )
    model = build_model(data, OptimizationConfig(0, 0, 0, 0, 2, 2))
    assert model.variables.limit["s", Resource.CPU].upBound == 1.5
    assert model.variables.limit["member", Resource.CPU].upBound == 6
    assert model.requests["s", Resource.CPU] == 1
    assert model.requests["member", Resource.CPU] == 4


def test_custom_bounds_match_diagnostics_without_mutating_candidates() -> None:
    from kubernetes_resource_optimizer.optimization.bounds import (
        derive_bounds,
        resolve_bounds,
    )
    from kubernetes_resource_optimizer.optimization.diagnostics import (
        feasibility_diagnostics,
    )
    from kubernetes_resource_optimizer.optimization.history import (
        derive_history_parameters,
    )

    data = InputData(
        (Node("n", 20, 200),),
        (Pod("a", "s"), Pod("b", "s")),
        (
            UsageSample(datetime(2026, 1, 1, tzinfo=UTC), "a", 1, 10),
            UsageSample(datetime(2026, 1, 1, tzinfo=UTC), "b", 4, 40),
        ),
    )
    config = OptimizationConfig(0, 0, 0, 0, 2, 2)
    history = derive_history_parameters(data, config)
    base = derive_bounds(data, history.peaks)
    base.limit_upper["b", Resource.CPU] = 5
    resolved = resolve_bounds(data, history.peaks, {r: 1.5 for r in Resource}, base)
    assert base.limit_upper["a", Resource.CPU] == 20
    assert resolved.individual_candidates.limit_upper["a", Resource.CPU] == 1.5
    assert resolved.effective_service.limit_upper["a", Resource.CPU] == 5
    assert resolved.effective_service.request_upper == base.request_upper
    assert resolved.effective_service.limit_big_m == base.limit_big_m
    model = build_model(data, config, base)
    assert model.variables.limit["a", Resource.CPU].upBound == 5
    output = "\n".join(feasibility_diagnostics(data, config, base))
    assert "candidate_cap=1.5 shared_cap=5 minimum_limit=4" in output
