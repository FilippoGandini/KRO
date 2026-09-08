"""Explicit mathematical tuning parameters for the optimizer."""

import math
from dataclasses import dataclass

from kubernetes_resource_optimizer.data.models import Resource
from kubernetes_resource_optimizer.optimization.bounds import maximum_violation_count


@dataclass(frozen=True, slots=True)
class OptimizationConfig:
    """Independent coverage tolerances, burst cap, and optional fairness gap."""

    epsilon_cpu_request: float
    epsilon_memory_request: float
    epsilon_cpu_limit: float
    epsilon_memory_limit: float
    cpu_limit_overcommit: float
    memory_limit_overcommit: float

    limit_peak_multiplier: float = 1.5
    fairness_mip_gap: float = 0.0
    fairness: bool = False
    lexicographic_tolerance: float = 1e-9

    def __post_init__(self) -> None:
        if (
            not math.isfinite(self.limit_peak_multiplier)
            or self.limit_peak_multiplier < 1
        ):
            raise ValueError("limit_peak_multiplier must be finite and at least 1")
        if (
            not math.isfinite(self.fairness_mip_gap)
            or not 0 <= self.fairness_mip_gap <= 1
        ):
            raise ValueError("fairness_mip_gap must be finite and between 0 and 1")
        if type(self.fairness) is not bool:
            raise ValueError("fairness must be a boolean")
        if (
            not math.isfinite(self.lexicographic_tolerance)
            or self.lexicographic_tolerance < 0
        ):
            raise ValueError("lexicographic_tolerance must be finite and non-negative")
        epsilon_fields = (
            "epsilon_cpu_request",
            "epsilon_memory_request",
            "epsilon_cpu_limit",
            "epsilon_memory_limit",
        )
        for field in epsilon_fields:
            value = getattr(self, field)
            if not math.isfinite(value) or not 0 <= value <= 1:
                raise ValueError(f"{field} must be finite and between 0 and 1")

        overcommit_fields = ("cpu_limit_overcommit", "memory_limit_overcommit")
        for field in overcommit_fields:
            value = getattr(self, field)
            if not math.isfinite(value) or value < 0:
                raise ValueError(f"{field} must be finite and non-negative")

    def epsilon_request(self, resource: Resource) -> float:
        """Return epsilon_request[h] for ``resource``."""

        if resource is Resource.CPU:
            return self.epsilon_cpu_request
        return self.epsilon_memory_request

    def epsilon_limit(self, resource: Resource) -> float:
        """Return epsilon_limit[h] for ``resource``."""

        if resource is Resource.CPU:
            return self.epsilon_cpu_limit
        return self.epsilon_memory_limit

    def limit_overcommit(self, resource: Resource) -> float:
        """Return K_limit[h] for ``resource``."""

        if resource is Resource.CPU:
            return self.cpu_limit_overcommit
        return self.memory_limit_overcommit

    def maximum_request_violations(
        self, resource: Resource, scenario_count: int
    ) -> int:
        """Return floor(epsilon_request[h] * |T|)."""

        return maximum_violation_count(self.epsilon_request(resource), scenario_count)

    def maximum_limit_violations(self, resource: Resource, scenario_count: int) -> int:
        """Return floor(epsilon_limit[h] * |T|)."""

        return maximum_violation_count(self.epsilon_limit(resource), scenario_count)
