"""Tests for symmetry breaking among equivalent candidate nodes."""

from datetime import UTC, datetime

import pytest

from kubernetes_resource_optimizer.data.models import InputData, Node, Pod, UsageSample
from kubernetes_resource_optimizer.optimization.config import OptimizationConfig
from kubernetes_resource_optimizer.optimization.model import build_model
from kubernetes_resource_optimizer.optimization.solver import CbcSolver, SolverStatus

TIMESTAMP = datetime(2026, 8, 1, tzinfo=UTC)
ZERO_RISK = OptimizationConfig(0, 0, 0, 0, 1.5, 1.5)


def make_data(nodes: tuple[Node, ...]) -> InputData:
    return InputData(
        nodes=nodes,
        pods=(Pod("pod-0"),),
        usage_samples=(UsageSample(TIMESTAMP, "pod-0", 1, 100),),
    )


def test_equivalent_nodes_are_activated_in_csv_order() -> None:
    built = build_model(
        make_data(
            (
                Node("node-a", 8, 8192, 1),
                Node("node-b", 8, 8192, 1),
                Node("node-c", 8, 8192, 1),
            )
        ),
        ZERO_RISK,
    )

    assert (
        built.problem.get_constraint_by_name(
            "equivalent_node_activation_order_node_a,node_b_"
        )
        is not None
    )
    assert (
        built.problem.get_constraint_by_name(
            "equivalent_node_activation_order_node_b,node_c_"
        )
        is not None
    )

    result = CbcSolver().solve(built.problem)

    assert result.status is SolverStatus.OPTIMAL
    assert built.variables.node_active["node-a"].varValue == pytest.approx(1)
    assert built.variables.node_active["node-b"].varValue == pytest.approx(0)
    assert built.variables.node_active["node-c"].varValue == pytest.approx(0)


def test_only_nodes_with_equal_cpu_memory_and_cost_are_grouped() -> None:
    built = build_model(
        make_data(
            (
                Node("equivalent-a", 8, 8192, 1),
                Node("different-cpu", 16, 8192, 1),
                Node("different-memory", 8, 16384, 1),
                Node("different-cost", 8, 8192, 2),
                Node("equivalent-b", 8, 8192, 1),
            )
        ),
        ZERO_RISK,
    )

    symmetry_constraints = {
        constraint.name
        for constraint in built.problem.constraints()
        if constraint.name.startswith("equivalent_node_activation_order_")
    }
    assert symmetry_constraints == {
        "equivalent_node_activation_order_equivalent_a,equivalent_b_"
    }


def test_later_equivalent_node_cannot_be_active_before_earlier_node() -> None:
    built = build_model(
        make_data((Node("first", 8, 8192, 1), Node("second", 8, 8192, 1))),
        ZERO_RISK,
    )
    built.problem.addConstraint(
        built.variables.node_active["first"] == 0, "force_first_inactive"
    )
    built.problem.addConstraint(
        built.variables.node_active["second"] == 1, "force_second_active"
    )

    result = CbcSolver().solve(built.problem)

    assert result.status is SolverStatus.INFEASIBLE
