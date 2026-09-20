"""Structured optimization solutions and extraction."""

from kubernetes_resource_optimizer.solution.extraction import extract_solution
from kubernetes_resource_optimizer.solution.models import (
    NodeDiagnostics,
    NodeResult,
    OptimizationResult,
    PodResult,
    ViolationDiagnostics,
)

__all__ = [
    "NodeDiagnostics",
    "NodeResult",
    "OptimizationResult",
    "PodResult",
    "ViolationDiagnostics",
    "extract_solution",
]
