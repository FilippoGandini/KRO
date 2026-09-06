"""Tests for shared requests and limits across service replicas."""

from datetime import UTC, datetime

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
from kubernetes_resource_optimizer.optimization.solver import CbcSolver, SolverStatus

TIMESTAMP = datetime(2026, 8, 1, tzinfo=UTC)
ZERO_RISK = OptimizationConfig(0, 0, 0, 0, 2, 2)


def test_replicas_receive_identical_requests_and_limits() -> None:
    data = InputData(
        nodes=(Node("node-0", 8, 8192),),
        pods=(
            Pod("api-0", service_id="api"),
            Pod("api-1", service_id="api"),
        ),
        usage_samples=(
            UsageSample(TIMESTAMP, "api-0", 1, 512),
            UsageSample(TIMESTAMP, "api-1", 2, 1024),
        ),
    )
    built = build_model(data, ZERO_RISK)

    result = solve_lexicographic(built, CbcSolver())

    assert result.status is SolverStatus.OPTIMAL
    for resource in Resource:
        assert built.variables.request["api-0", resource].varValue == pytest.approx(
            built.variables.request["api-1", resource].varValue
        )
        assert built.variables.limit["api-0", resource].varValue == pytest.approx(
            built.variables.limit["api-1", resource].varValue
        )
    assert built.variables.request["api-0", Resource.CPU].varValue == pytest.approx(2)
    assert built.variables.request["api-0", Resource.MEMORY].varValue == pytest.approx(1024)


def test_pods_without_service_id_are_not_tied_together() -> None:
    data = InputData(
        nodes=(Node("node-0", 8, 8192),),
        pods=(Pod("pod-0"), Pod("pod-1")),
        usage_samples=(
            UsageSample(TIMESTAMP, "pod-0", 1, 512),
            UsageSample(TIMESTAMP, "pod-1", 2, 1024),
        ),
    )
    built = build_model(data, ZERO_RISK)

    result = solve_lexicographic(built, CbcSolver())

    assert result.status is SolverStatus.OPTIMAL
    assert built.variables.request["pod-0", Resource.CPU].varValue == pytest.approx(1)
    assert built.variables.request["pod-1", Resource.CPU].varValue == pytest.approx(2)
