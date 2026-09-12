"""Input diagnostics identify conflicts without reading solver variable values."""

from datetime import UTC, datetime

from kubernetes_resource_optimizer.data.models import InputData, Node, Pod, UsageSample
from kubernetes_resource_optimizer.optimization.config import OptimizationConfig
from kubernetes_resource_optimizer.optimization.diagnostics import (
    feasibility_diagnostics,
)


def test_replica_caps_and_request_upper_conflicts() -> None:
    data = InputData(
        (Node("n", 100, 100),),
        (Pod("a", "s", cpu_request_max=1), Pod("b", "s")),
        (
            UsageSample(datetime(2026, 1, 1, tzinfo=UTC), "a", 4, 4),
            UsageSample(datetime(2026, 1, 1, tzinfo=UTC), "b", 1, 1),
        ),
    )
    output = "\n".join(
        feasibility_diagnostics(data, OptimizationConfig(0, 0, 0, 0, 1, 1))
    )
    assert "request > request_upper" in output
    assert "shared minimum limit > shared cap" in output
    assert "limit_coverage_at_shared_cap=0/1 required=1" in output
    assert "shared_cap=1.5 minimum_limit=4" in output


def test_joint_resource_candidates_and_aggregate_overcommit() -> None:
    data = InputData(
        (Node("cpu", 10, 1), Node("memory", 1, 10)),
        (Pod("p"),),
        (UsageSample(datetime(2026, 1, 1, tzinfo=UTC), "p", 2, 2),),
    )
    output = "\n".join(
        feasibility_diagnostics(data, OptimizationConfig(0, 0, 0, 0, 0.1, 0.1))
    )
    assert "CONFLICT: zero candidate nodes" in output
    assert "minimum_total_limits=2 overcommit_capacity=1.1" in output
    assert "CONFLICT: aggregate capacity exceeded" in output


def test_request_floor_increases_aligned_scenario_total() -> None:
    data = InputData(
        (Node("n", 3, 3),),
        (Pod("a"), Pod("b")),
        tuple(
            UsageSample(datetime(2026, 1, day, tzinfo=UTC), pod, usage, usage)
            for day, pod, usage in [(1, "a", 2), (1, "b", 0), (2, "a", 0), (2, "b", 2)]
        ),
    )
    output = "\n".join(
        feasibility_diagnostics(data, OptimizationConfig(0, 0, 0, 0, 2, 2))
    )
    assert "maximum_scenario_demand=4" in output
    assert "timestamp=2026-01-02T00:00:00+00:00" in output
    assert "CONFLICT: aggregate capacity exceeded" in output
