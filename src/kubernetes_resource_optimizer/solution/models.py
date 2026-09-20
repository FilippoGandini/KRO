"""Solver-independent structured solution objects."""

from dataclasses import dataclass

from kubernetes_resource_optimizer.data.models import Resource
from kubernetes_resource_optimizer.optimization.solver import (
    SolverName,
    SolverStatus,
    StageResult,
)


@dataclass(frozen=True, slots=True)
class PodResult:
    """Rightsizing and placement recommendation for one pod."""

    pod_id: str
    recommended_cpu_request: float
    recommended_memory_request: float
    recommended_cpu_limit: float
    recommended_memory_limit: float
    assigned_node: str


@dataclass(frozen=True, slots=True)
class NodeResult:
    """Activation and assigned pods for one candidate node."""

    node_id: str
    cost: float
    active: bool
    assigned_pods: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class ViolationDiagnostics:
    """Observed exceedances for one pod and resource."""

    pod_id: str
    resource: Resource
    request_violation_count: int
    request_violation_rate: float
    limit_violation_count: int
    limit_violation_rate: float


@dataclass(frozen=True, slots=True)
class NodeDiagnostics:
    """Runtime peaks and configured limit ratios for one node."""

    node_id: str
    peak_effective_cpu: float
    peak_effective_memory: float
    configured_cpu_limit_overcommit: float
    configured_memory_limit_overcommit: float


@dataclass(frozen=True, slots=True)
class OptimizationResult:
    """Complete structured result, independent of terminal presentation."""

    solver_status: SolverStatus
    solver: SolverName
    objective_value: float
    total_node_cost: float
    active_node_count: int
    solve_time_seconds: float
    model_variable_count: int
    model_constraint_count: int
    pods: tuple[PodResult, ...]
    nodes: tuple[NodeResult, ...]
    violations: tuple[ViolationDiagnostics, ...]
    node_diagnostics: tuple[NodeDiagnostics, ...]
    stages: tuple[StageResult, ...] = ()
    lexicographic_complete: bool = False
    optimization_message: str = ""
