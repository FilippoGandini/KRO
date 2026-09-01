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
            "--workloads",
            str(example_dir / "workloads.csv"),
            "--usage",
            str(example_dir / "usage.csv"),
        ]
    )

    assert exit_code == 0
    output = capsys.readouterr().out
    assert "Solver: HiGHS" in output
    assert "Solver status: optimal" in output
    assert "Active nodes: 4/5" in output
    assert "Total node cost: 4" in output
    assert "api-replica-0 ->" in output
    assert "api-replica-1 ->" in output


def test_cli_defaults_to_highs_with_an_unlimited_runtime() -> None:
    args = build_parser().parse_args(
        ["--nodes", "nodes.csv", "--workloads", "workloads.csv", "--usage", "usage.csv"]
    )

    assert args.solver.value == "highs"
    assert args.time_limit_seconds is None
