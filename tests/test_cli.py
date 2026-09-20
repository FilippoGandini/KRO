"""End-to-end test for the offline command-line workflow."""

from pathlib import Path

import pytest

from kubernetes_resource_optimizer.cli import build_parser, main


def test_cli_optimizes_example_csv_files(
    capsys: pytest.CaptureFixture[str],
) -> None:
    example_dir = Path(__file__).parents[1] / "data" / "examples"

    exit_code = main(
        [
            "--nodes",
            str(example_dir / "nodes.csv"),
            "--pods",
            str(example_dir / "pods.csv"),
            "--usage",
            str(example_dir / "usage.csv"),
        ]
    )

    assert exit_code == 0
    output = capsys.readouterr().out
    assert "Solver: HiGHS" in output
    assert "Solver status: optimal" in output
    assert "Active nodes: 3/6" in output
    assert "Total node cost: 3" in output
    assert "backend-0 ->" in output
    assert "backend-1 ->" in output


def test_cli_defaults_to_highs_with_an_unlimited_runtime() -> None:
    args = build_parser().parse_args(
        ["--nodes", "nodes.csv", "--pods", "pods.csv", "--usage", "usage.csv"]
    )

    assert args.solver.value == "highs"
    assert args.time_limit_seconds is None


def test_priority_and_fairness_options() -> None:
    base = ["--nodes", "n.csv", "--pods", "w.csv", "--usage", "u.csv"]
    defaults = build_parser().parse_args(base)
    assert defaults.cpu_limit_peak_multiplier == 1.5
    assert defaults.memory_limit_peak_multiplier == 1.5
    assert defaults.limits_mip_gap == 0
    assert defaults.fairness_mip_gap == 0
    assert not defaults.fairness
    selected = build_parser().parse_args(
        [
            *base,
            "--cpu-limit-peak-multiplier",
            "2",
            "--memory-limit-peak-multiplier",
            "1.2",
            "--fairness-mip-gap",
            "0.05",
            "--limits-mip-gap",
            "0.02",
            "--fairness",
        ]
    )
    assert selected.cpu_limit_peak_multiplier == 2
    assert selected.memory_limit_peak_multiplier == 1.2
    assert selected.limits_mip_gap == 0.02
    assert selected.fairness_mip_gap == 0.05
    assert selected.fairness
    with pytest.raises(SystemExit):
        build_parser().parse_args([*base, "--cpu-limit-peak-multiplier", "invalid"])


def test_cli_prints_infeasibility_diagnostics(
    capsys: pytest.CaptureFixture[str],
) -> None:
    example_dir = Path(__file__).parents[1] / "data" / "examples"
    exit_code = main(
        [
            "--nodes",
            str(example_dir / "nodes.csv"),
            "--pods",
            str(example_dir / "pods.csv"),
            "--usage",
            str(example_dir / "usage.csv"),
            "--cpu-limit-overcommit",
            "0",
        ]
    )
    output = capsys.readouterr()
    assert exit_code == 1
    assert "Phase node_cost: status=infeasible; incumbent=False" in output.err
    assert "Feasibility diagnostics" in output.err
    assert "CONFLICT: zero candidate nodes" in output.err
    assert "CONFLICT: aggregate capacity exceeded" in output.err
    assert "No feasible recommendation is available." in output.out
