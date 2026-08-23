"""Modular constraints mapped directly to the MILP formulation."""

from kubernetes_resource_optimizer.optimization.constraints.placement import (
    add_assignment_constraints,
    add_node_activation_constraints,
)
from kubernetes_resource_optimizer.optimization.constraints.requests import (
    add_request_limit_ordering_constraints,
)

__all__ = [
    "add_assignment_constraints",
    "add_node_activation_constraints",
    "add_request_limit_ordering_constraints",
]
