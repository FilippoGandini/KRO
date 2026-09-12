"""Command-line orchestration for the offline optimization workflow."""

from __future__ import annotations

import argparse
import sys
from collections.abc import Sequence
from pathlib import Path
from time import perf_counter

from kubernetes_resource_optimizer.data.csv_loader import load_input_data
from kubernetes_resource_optimizer.data.validation import InputValidationError
from kubernetes_resource_optimizer.optimization.config import OptimizationConfig
from kubernetes_resource_optimizer.optimization.diagnostics import (
    feasibility_diagnostics,
)
from kubernetes_resource_optimizer.optimization.model import build_model
from kubernetes_resource_optimizer.optimization.objectives.lexicographic import (
    solve_lexicographic,
)
from kubernetes_resource_optimizer.optimization.solver import (
    SolverName,
    SolverStatus,
    create_solver,
)
from kubernetes_resource_optimizer.reporting import generate_html_report
from kubernetes_resource_optimizer.solution import OptimizationResult, extract_solution


def build_parser() -> argparse.ArgumentParser:
    """Create the CLI parser without performing application work."""

    parser = argparse.ArgumentParser(
        prog="kubernetes-resource-optimizer",
        description="Run offline resource request and limit rightsizing and pod placement.",
    )
    parser.add_argument("--nodes", type=Path, required=True, help="Path to nodes.csv")
    parser.add_argument(
        "--workloads", type=Path, required=True, help="Path to workloads.csv"
    )
    parser.add_argument("--usage", type=Path, required=True, help="Path to usage.csv")
    parser.add_argument(
        "--epsilon-cpu-request",
        type=float,
        default=0.05,
        help="Allowed historical CPU request exceedance share; choose conservatively because requests are calculated at the coverage floor.",
    )
    parser.add_argument(
        "--epsilon-memory-request",
        type=float,
        default=0.05,
        help="Allowed historical memory request exceedance share; choose conservatively because requests are calculated at the coverage floor.",
    )
    parser.add_argument("--epsilon-cpu-limit", type=float, default=0.01)
    parser.add_argument("--epsilon-memory-limit", type=float, default=0.01)
    parser.add_argument("--cpu-limit-overcommit", type=float, default=1.5)
    parser.add_argument("--memory-limit-overcommit", type=float, default=1.25)
    parser.add_argument(
        "--limit-peak-multiplier",
        type=float,
        default=1.5,
        help="Individual candidate cap multiplier; replicas share their maximum cap (default: 1.5).",
    )
    parser.add_argument(
        "--fairness-mip-gap",
        type=float,
        default=0.0,
        help="Relative MIP gap accepted only for fairness (default: 0).",
    )
    parser.add_argument(
        "--fairness",
        action="store_true",
        help="Optimize minimum normalized request-limit headroom before maximizing weighted limits (default: disabled).",
    )
    parser.add_argument(
        "--solver",
        type=SolverName,
        choices=tuple(SolverName),
        default=SolverName.HIGHS,
        help="Local MILP solver executable (default: highs).",
    )
    parser.add_argument(
        "--time-limit-seconds",
        type=float,
        default=None,
        help="Maximum total runtime across all optimization phases in seconds (default: unlimited).",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        help="Generate a static HTML/SVG report in this directory.",
    )
    return parser


def _progress(message: str) -> None:
    """Show progress immediately, keeping stdout available for results."""

    print(message, file=sys.stderr, flush=True)


def _print_summary(result: OptimizationResult) -> None:
    """Print a compact presentation of the solver-independent result."""

    print(f"Solver: {result.solver.display_name}")
    print(f"Solver status: {result.solver_status.value}")
    print(f"Active nodes: {result.active_node_count}/{len(result.nodes)}")
    print(f"Total node cost: {result.total_node_cost:g}")
    print(f"Last solved objective value: {result.objective_value:g}")
    print(f"Lexicographic optimization complete: {result.lexicographic_complete}")
    for stage in result.stages:
        print(
            f"  {stage.name}: {stage.status.value}, value={stage.objective_value}; gap={stage.mip_gap}; bound={stage.best_bound}"
        )
    if result.optimization_message:
        print(result.optimization_message)
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
        _progress("Loading and validating CSV data...")
        data = load_input_data(args.nodes, args.workloads, args.usage)
        _progress(
            f"Data validated: {len(data.pods):,} workloads, "
            f"{len(data.nodes):,} candidate nodes, "
            f"{len({sample.timestamp for sample in data.usage_samples}):,} scenarios."
        )
        _progress("Validating optimization configuration...")
        config = OptimizationConfig(
            epsilon_cpu_request=args.epsilon_cpu_request,
            epsilon_memory_request=args.epsilon_memory_request,
            epsilon_cpu_limit=args.epsilon_cpu_limit,
            epsilon_memory_limit=args.epsilon_memory_limit,
            cpu_limit_overcommit=args.cpu_limit_overcommit,
            memory_limit_overcommit=args.memory_limit_overcommit,
            limit_peak_multiplier=args.limit_peak_multiplier,
            fairness_mip_gap=args.fairness_mip_gap,
            fairness=args.fairness,
        )
    except (InputValidationError, ValueError) as error:
        parser.error(str(error))

    _progress("Building model...")
    build_started = perf_counter()
    try:
        model = build_model(data, config)
    except ValueError as error:
        parser.error(str(error))
    _progress(
        f"Model built: {model.problem.numVariables():,} variables, "
        f"{model.problem.numConstraints():,} constraints "
        f"({perf_counter() - build_started:.3f}s)."
    )
    try:
        _progress(f"Running solver ({args.solver.display_name})...")
        solver_result = solve_lexicographic(
            model,
            create_solver(args.solver, time_limit_seconds=args.time_limit_seconds),
            progress=_progress,
        )
    except (RuntimeError, ValueError) as error:
        parser.error(str(error))
    _progress(f"Solver finished: {solver_result.status.value}. {solver_result.message}")
    if solver_result.status is SolverStatus.INFEASIBLE or any(
        stage.status is SolverStatus.INFEASIBLE for stage in solver_result.stages
    ):
        for line in feasibility_diagnostics(data, config):
            _progress(line)
    if solver_result.status not in {SolverStatus.OPTIMAL, SolverStatus.FEASIBLE}:
        print(f"Solver status: {solver_result.status.value}")
        print("No feasible recommendation is available.")
        return 1

    _progress("Extracting recommendations and computing diagnostics...")
    result = extract_solution(data, model, solver_result)
    _progress(f"Recommendations ready for {len(result.workloads):,} workloads.")
    _print_summary(result)
    if args.output_dir is not None:
        _progress(f"Generating HTML/SVG report in {args.output_dir}...")
        report_path = generate_html_report(data, result, config, args.output_dir)
        _progress(f"Report generated: {report_path}")
        print(f"Report: {report_path}")
    return 0
