"""Objective coefficients derived from explicit historical parameters."""

from dataclasses import dataclass
from math import fsum

from kubernetes_resource_optimizer.optimization.bounds import BoundKey
from kubernetes_resource_optimizer.optimization.history import HistoricalParameters


@dataclass(frozen=True, slots=True)
class LimitPriority:
    """Dimensionless reward for historical excess above the request."""

    spike_score: float


def derive_limit_priorities(
    history: HistoricalParameters,
) -> dict[BoundKey, LimitPriority]:
    """Average normalized excess over the ranked request-coverage tail.

    Shared replica requests do not change individual tail splits. Empty tails
    and all-zero histories receive zero reward.
    """
    priorities: dict[BoundKey, LimitPriority] = {}
    for key, values in history.sorted_usage.items():
        request = history.requests[key]
        scale = max(request, history.peaks[key])
        upper = values[history.coverage_splits[key] :]
        spike = (
            fsum(max(0.0, value - request) / scale for value in upper) / len(upper)
            if scale > 0 and upper
            else 0.0
        )
        priorities[key] = LimitPriority(spike_score=spike)
    return priorities
