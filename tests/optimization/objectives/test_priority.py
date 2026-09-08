"""Demand priorities must be finite, unit invariant, and meaningful at boundaries."""

import math
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
from kubernetes_resource_optimizer.optimization.history import derive_history_parameters
from kubernetes_resource_optimizer.optimization.objectives.priority import (
    derive_limit_priorities,
)

CONFIG = OptimizationConfig(0.25, 0.25, 0.25, 0.25, 1, 1)


def profiles() -> InputData:
    return InputData(
        (Node("n", 10, 100),),
        (Pod("steady"), Pod("spiky")),
        tuple(
            UsageSample(
                datetime(2026, 1, 1, tzinfo=UTC) + timedelta(hours=t),
                pod,
                value,
                value * 10,
            )
            for pod, values in [("steady", [2, 2, 2, 2]), ("spiky", [0, 0, 1, 8])]
            for t, value in enumerate(values)
        ),
    )


def test_spike_is_unit_invariant_and_rewards_tail_exceedance() -> None:
    priorities = derive_limit_priorities(derive_history_parameters(profiles(), CONFIG))
    assert priorities["steady", Resource.CPU].spike_score == 0
    assert priorities["spiky", Resource.CPU].spike_score == pytest.approx(7 / 8)
    for pod in ("steady", "spiky"):
        assert (
            priorities[pod, Resource.CPU].spike_score
            == priorities[pod, Resource.MEMORY].spike_score
        )


@pytest.mark.parametrize("epsilon", [0, 0.25, 1])
@pytest.mark.parametrize("value", [0, 3])
def test_constant_zero_history_and_empty_partitions(
    epsilon: float, value: float
) -> None:
    data = profiles()
    data = replace(
        data,
        usage_samples=tuple(
            replace(s, cpu_usage=value, memory_usage=value) for s in data.usage_samples
        ),
    )
    history = derive_history_parameters(
        data,
        replace(CONFIG, epsilon_cpu_request=epsilon, epsilon_memory_request=epsilon),
    )
    priorities = derive_limit_priorities(history)
    assert all(
        request == (0 if epsilon == 1 else value)
        for request in history.requests.values()
    )
    for priority in priorities.values():
        assert math.isfinite(priority.spike_score)
        assert 0 <= priority.spike_score <= 1
        if value == 0:
            assert priority.spike_score == 0
        if epsilon == 0:
            assert priority.spike_score == 0


def test_replica_reference_uses_hottest_replica_and_tail_cannot_be_negative() -> None:
    data = profiles()
    data = replace(
        data, pods=tuple(replace(p, service_id="service") for p in data.pods)
    )
    priorities = derive_limit_priorities(derive_history_parameters(data, CONFIG))
    assert derive_history_parameters(data, CONFIG).requests["steady", Resource.CPU] == 2
    assert derive_history_parameters(data, CONFIG).requests["spiky", Resource.CPU] == 2
    assert priorities["spiky", Resource.CPU].spike_score == 0.75


def test_missing_service_does_not_collide_with_pod_id() -> None:
    data = profiles()
    data = replace(data, pods=(Pod("steady"), Pod("spiky", service_id="steady")))
    assert derive_history_parameters(data, CONFIG).requests["spiky", Resource.CPU] == 1


@pytest.mark.parametrize("multiplier", [0, 0.9, float("inf"), float("nan")])
def test_invalid_peak_multiplier_rejected(multiplier: float) -> None:
    with pytest.raises(ValueError, match="limit_peak_multiplier"):
        replace(CONFIG, limit_peak_multiplier=multiplier)


@pytest.mark.parametrize("gap", [-0.1, 1.1, float("inf"), float("nan")])
def test_invalid_fairness_gap_rejected(gap: float) -> None:
    with pytest.raises(ValueError, match="fairness_mip_gap"):
        replace(CONFIG, fairness_mip_gap=gap)
