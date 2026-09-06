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


def test_scores_are_dimensionless_and_preference_changes_ranking() -> None:
    steady_weights, spike_weights = [], []
    for preference in range(-2, 3):
        priorities = derive_limit_priorities(
            profiles(), replace(CONFIG, limit_priority=preference)
        )
        for pod in ("steady", "spiky"):
            assert priorities[pod, Resource.CPU] == priorities[
                pod, Resource.MEMORY
            ].__class__(
                priorities[pod, Resource.MEMORY].request_reference / 10,
                priorities[pod, Resource.MEMORY].steady_score,
                priorities[pod, Resource.MEMORY].spike_score,
                priorities[pod, Resource.MEMORY].weight,
            )
        steady_weights.append(priorities["steady", Resource.CPU].weight)
        spike_weights.append(priorities["spiky", Resource.CPU].weight)
    assert steady_weights == sorted(steady_weights, reverse=True)
    assert steady_weights[0] > spike_weights[0]
    assert steady_weights[-1] < spike_weights[-1]
    assert steady_weights[2] == 0.5


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
    priorities = derive_limit_priorities(
        data,
        replace(CONFIG, epsilon_cpu_request=epsilon, epsilon_memory_request=epsilon),
    )
    for priority in priorities.values():
        assert math.isfinite(priority.weight)
        assert 0 <= priority.weight <= 1
        assert priority.request_reference == (0 if epsilon == 1 else value)
        if value == 0:
            assert priority.weight == 0
        if epsilon == 0:
            assert priority.spike_score == 0
        if epsilon == 1:
            assert priority.steady_score == 0


def test_replica_reference_uses_hottest_replica_and_tail_cannot_be_negative() -> None:
    data = profiles()
    data = replace(
        data, pods=tuple(replace(p, service_id="service") for p in data.pods)
    )
    priorities = derive_limit_priorities(data, CONFIG)
    assert priorities["steady", Resource.CPU].request_reference == 2
    assert priorities["spiky", Resource.CPU].request_reference == 2
    assert priorities["spiky", Resource.CPU].spike_score == 0.75


def test_missing_service_does_not_collide_with_pod_id() -> None:
    data = profiles()
    data = replace(data, pods=(Pod("steady"), Pod("spiky", service_id="steady")))
    assert (
        derive_limit_priorities(data, CONFIG)["spiky", Resource.CPU].request_reference
        == 1
    )


@pytest.mark.parametrize("preference", [-3, 3, 0.5, True])
def test_invalid_preference_rejected(preference: int) -> None:
    with pytest.raises(ValueError, match="limit_priority"):
        replace(CONFIG, limit_priority=preference)
