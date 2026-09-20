# Kubernetes Resource Optimizer

KRO uses historical CPU and memory data to calculate pod requests and optimize
limits, placement, and active-node cost through a MILP. It runs entirely offline
on local CSV files and does not connect to or modify a cluster.

## Setup

Requires Python 3.12+ and [uv](https://docs.astral.sh/uv/).

```console
uv sync
```

## Usage

Provide `nodes.csv`, `workloads.csv`, and `usage.csv`. CPU is measured in cores,
memory in MiB, and all pods must share aligned timestamps.
See [example inputs](data/examples).

```console
uv run kro \
  --nodes data/examples/nodes.csv \
  --workloads data/examples/workloads.csv \
  --usage data/examples/usage.csv \
  --time-limit-seconds 300 \
  --output-dir output/example
```

HiGHS is the default solver; CBC is also available. The command prints
recommendations and diagnostics and writes a single HTML report when `--output-dir`
is supplied. Its name is `<output-directory-name>_<YYYYMMDD>.html`, using the
current local date (for example, `output/example/example_20260920.html`). All
charts, styles and scripts are embedded.

Run `uv run kro --help` for all options.

Use `--limits-mip-gap 0.01` to accept a 1% relative optimality gap in the final
weighted-limit phase. The default is `0`. Optional fairness has its independent
`--fairness-mip-gap`; node cost always requires zero gap. Gap termination is
reported as approximate, and a time limit alone does not complete the hierarchy.

## Documentation

See the [technical documentation](docs/mathematical-formulation.tex) for the
complete model, input schemas, parameters, fairness, solver behavior, and
limitations.

## Development

```console
uv run pytest
uv run ruff check .
uv run mypy src
```
