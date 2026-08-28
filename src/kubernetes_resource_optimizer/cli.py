"""Command-line orchestration for the offline optimization workflow."""

from __future__ import annotations

import argparse
from collections.abc import Sequence
from pathlib import Path

from kubernetes_resource_optimizer.data.csv_loader import load_input_data
from kubernetes_resource_optimizer.data.validation import InputValidationError
from kubernetes_resource_optimizer.optimization.config import OptimizationConfig
from kubernetes_resource_optimizer.optimization.model import build_model
from kubernetes_resource_optimizer.optimization.solver import CbcSolver, SolverStatus
from kubernetes_resource_optimizer.reporting import generate_html_report
from kubernetes_resource_optimizer.solution import OptimizationResult, extract_solution


def build_parser() -> argparse.ArgumentParser:
    """Create the CLI parser without performing application work."""

    parser = argparse.ArgumentParser(
        prog="kubernetes-resource-optimizer",
        description="Run offline Kubernetes workload rightsizing and placement.",
    )
    parser.add_argument("--nodes", type=Path, required=True, help="Path to nodes.csv")
    parser.add_argument(
        "--workloads", type=Path, required=True, help="Path to workloads.csv"
    )
    parser.add_argument("--usage", type=Path, required=True, help="Path to usage.csv")
    parser.add_argument("--epsilon-cpu-request", type=float, default=0.05)
    parser.add_argument("--epsilon-memory-request", type=float, default=0.05)
    parser.add_argument("--epsilon-cpu-limit", type=float, default=0.01)
    parser.add_argument("--epsilon-memory-limit", type=float, default=0.01)
    parser.add_argument("--cpu-limit-overcommit", type=float, default=1.5)
    parser.add_argument("--memory-limit-overcommit", type=float, default=1.25)
    parser.add_argument(
        "--output-dir",
        type=Path,
        help="Generate a static HTML/SVG report in this directory.",
    )
    return parser


def _print_summary(result: OptimizationResult) -> None:
    """Print a compact presentation of the solver-independent result."""

    print(f"Solver status: {result.solver_status.value}")
    print(f"Active nodes: {result.active_node_count}/{len(result.nodes)}")
    print(f"Total node cost: {result.total_node_cost:g}")
    print(f"Objective value: {result.objective_value:g}")
    print(f"Solve time: {result.solve_time_seconds:.3f}s")
    print("Workload recommendations:")
    for workload in result.workloads:
        print(
            f"  {workload.workload_id} -> {workload.assigned_node}: "
            f"request cpu={workload.recommended_cpu_request:g} cores, "
            f"memory={workload.recommended_memory_request:g} MiB; "
            f"limit cpu={workload.recommended_cpu_limit:g} cores, "
            f"memory={workload.recommended_memory_limit:g} MiB"
        )


def main(argv: Sequence[str] | None = None) -> int:
    """Execute the complete offline workflow and return a process exit code."""

    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        data = load_input_data(args.nodes, args.workloads, args.usage)
        config = OptimizationConfig(
            epsilon_cpu_request=args.epsilon_cpu_request,
            epsilon_memory_request=args.epsilon_memory_request,
            epsilon_cpu_limit=args.epsilon_cpu_limit,
            epsilon_memory_limit=args.epsilon_memory_limit,
            cpu_limit_overcommit=args.cpu_limit_overcommit,
            memory_limit_overcommit=args.memory_limit_overcommit,
        )
    except (InputValidationError, ValueError) as error:
        parser.error(str(error))

    model = build_model(data, config)
    solver_result = CbcSolver().solve(model.problem)
    if solver_result.status not in {SolverStatus.OPTIMAL, SolverStatus.FEASIBLE}:
        print(f"Solver status: {solver_result.status.value}")
        print("No feasible recommendation is available.")
        return 1

    result = extract_solution(data, model, solver_result)
    _print_summary(result)
    if args.output_dir is not None:
        report_path = generate_html_report(data, result, config, args.output_dir)
        print(f"Report: {report_path}")
    return 0
