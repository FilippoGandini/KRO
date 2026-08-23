import math
from datetime import UTC, datetime

import pytest

from kubernetes_resource_optimizer.data.models import (
    InputData,
    Node,
    Pod,
    Resource,
    UsageSample,
)
from kubernetes_resource_optimizer.optimization.bounds import (
    derive_bounds,
    maximum_violation_count,
)


def sample_data() -> InputData:
    timestamp = datetime(2026, 8, 1, tzinfo=UTC)
    return InputData(
        nodes=(Node("small", 4.0, 8192.0), Node("large", 16.0, 65536.0)),
        pods=(
            Pod("default"),
            Pod(
                "bounded",
                cpu_request_max=3.0,
                memory_request_max=4096.0,
                cpu_limit_max=6.0,
                memory_limit_max=8192.0,
            ),
        ),
        usage_samples=(
            UsageSample(timestamp, "default", 1.5, 1024.0),
            UsageSample(timestamp, "bounded", 2.0, 2048.0),
            UsageSample(timestamp.replace(hour=1), "default", 2.5, 1536.0),
            UsageSample(timestamp.replace(hour=1), "bounded", 1.0, 3072.0),
        ),
    )


def test_default_bounds_use_largest_heterogeneous_node_capacity() -> None:
    bounds = derive_bounds(sample_data())

    assert bounds.request_upper["default", Resource.CPU] == 16.0
    assert bounds.limit_upper["default", Resource.CPU] == 16.0
    assert bounds.request_upper["default", Resource.MEMORY] == 65536.0
    assert bounds.limit_upper["default", Resource.MEMORY] == 65536.0


def test_workload_specific_bounds_take_precedence() -> None:
    bounds = derive_bounds(sample_data())

    assert bounds.request_upper["bounded", Resource.CPU] == 3.0
    assert bounds.request_upper["bounded", Resource.MEMORY] == 4096.0
    assert bounds.limit_upper["bounded", Resource.CPU] == 6.0
    assert bounds.limit_upper["bounded", Resource.MEMORY] == 8192.0


def test_big_m_is_finite_non_negative_and_tight_to_peak_usage() -> None:
    bounds = derive_bounds(sample_data())

    assert bounds.request_big_m["default", Resource.CPU] == 2.5
    assert bounds.limit_big_m["default", Resource.MEMORY] == 1536.0
    assert bounds.request_big_m == bounds.limit_big_m
    assert all(
        math.isfinite(value) and value >= 0
        for value in bounds.request_big_m.values()
    )


@pytest.mark.parametrize(
    ("epsilon", "scenario_count", "expected"),
    [(0, 20, 0), (0.05, 20, 1), (0.099, 10, 0), (0.1, 10, 1), (1, 20, 20)],
)
def test_maximum_violation_count(
    epsilon: float, scenario_count: int, expected: int
) -> None:
    assert maximum_violation_count(epsilon, scenario_count) == expected


def test_zero_scenarios_allows_zero_violations() -> None:
    assert maximum_violation_count(1, 0) == 0


@pytest.mark.parametrize("epsilon", [-0.1, 1.1, float("inf"), float("nan")])
def test_maximum_violation_count_rejects_invalid_epsilon(epsilon: float) -> None:
    with pytest.raises(ValueError, match="epsilon"):
        maximum_violation_count(epsilon, 10)


def test_bounds_require_usage_for_every_pod() -> None:
    data = sample_data()
    incomplete = InputData(data.nodes, data.pods, data.usage_samples[:1])

    with pytest.raises(ValueError, match="bounded.*no usage samples"):
        derive_bounds(incomplete)
