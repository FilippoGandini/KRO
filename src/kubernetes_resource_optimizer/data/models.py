"""Validated domain objects used by later application layers."""

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum


class Resource(StrEnum):
    """A resource represented in canonical model units."""

    CPU = "cpu"
    MEMORY = "memory"


@dataclass(frozen=True, slots=True)
class Node:
    """A candidate node, with CPU in cores and memory in MiB."""

    node_id: str
    cpu_capacity: float
    memory_capacity: float


@dataclass(frozen=True, slots=True)
class Pod:
    """A pod and its optional current values and optimization bounds."""

    pod_id: str
    service_id: str | None = None
    current_cpu_request: float | None = None
    current_memory_request: float | None = None
    current_cpu_limit: float | None = None
    current_memory_limit: float | None = None
    cpu_request_max: float | None = None
    memory_request_max: float | None = None
    cpu_limit_max: float | None = None
    memory_limit_max: float | None = None

    @property
    def replica_group_id(self) -> str:
        """Return the service grouping this pod, or a pod-local singleton."""

        return self.service_id if self.service_id is not None else self.pod_id


@dataclass(frozen=True, slots=True)
class UsageSample:
    """One pod observation at an aware timestamp."""

    timestamp: datetime
    pod_id: str
    cpu_usage: float
    memory_usage: float


@dataclass(frozen=True, slots=True)
class InputData:
    """Complete, validated input for a future optimization problem."""

    nodes: tuple[Node, ...]
    pods: tuple[Pod, ...]
    usage_samples: tuple[UsageSample, ...]
