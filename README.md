# Kubernetes Resource Optimizer

Kubernetes Resource Optimizer (KRO) is an offline tool that uses historical CPU
and memory data to determine jointly:

- the requests and limits of each workload;
- the candidate node on which each workload should be placed;
- the subset of nodes to activate while minimizing total node cost.

The problem is formulated as a Mixed-Integer Linear Program (MILP).
Its objective first minimizes the total cost associated to the active nodes,
then minimizes normalized requests, maximizes fair normalized limit headroom,
and finally maximizes normalized limits with the remaining node budget.
Recommendations satisfy capacity constraints in every historical scenario,
configurable tolerances for request and limit exceedances, and configurable
limit-overcommit thresholds. Workloads with complementary temporal profiles may
share a node when their aggregate demand remains compatible with the node capacity.

The project does not connect to Kubernetes, OpenShift, or Prometheus and never
changes a cluster. All inputs are local CSV files. The formulation, assumptions,
parameters, and limitations are described in the
docs/.

## Requirements and installation

- Python 3.12 or newer
- [uv](https://docs.astral.sh/uv/)

From the repository root:

```console
uv sync
```

PuLP builds the MILP. HiGHS (the default) and CBC are supported through local
command-line executables; the optimizer makes no remote API calls.
See the [HiGHS installation documentation](https://github.com/ERGO-Code/HiGHS#installation)
for binaries and source builds. CBC remains available through the executable
bundled with PuLP.

## Preparing the inputs

Create three CSV files. CPU values use cores and memory values use MiB. Every
workload must have the same set of timestamps.

`nodes.csv`:

```csv
node_id,cpu_capacity,memory_capacity,cost
node-a,4,4096,0.25
node-b,8,8192,0.40
```

`workloads.csv`:

```csv
workload_id,service_id,cpu_request_max,memory_request_max,cpu_limit_max,memory_limit_max
api-0,api,4,4096,4,4096
api-1,api,4,4096,4,4096
```

`service_id` and the four maximum values are optional. Replicas with the same
`service_id` receive identical requests and limits. A missing node `cost`
defaults to `1`.

`usage.csv`:

```csv
timestamp,workload_id,cpu_usage,memory_usage
2026-08-01T10:00:00Z,api-0,0.50,512
2026-08-01T10:00:00Z,api-1,0.60,540
2026-08-01T11:00:00Z,api-0,0.80,620
2026-08-01T11:00:00Z,api-1,0.45,500
```

Complete example files are available in [`data/examples`](data/examples). Empty,
misaligned, duplicate, negative, non-finite, incomplete, or otherwise invalid
inputs are rejected explicitly.

## Running the optimizer

```console
uv run kubernetes-resource-optimizer \
  --nodes data/examples/nodes.csv \
  --workloads data/examples/workloads.csv \
  --usage data/examples/usage.csv \
  --solver highs \
  --time-limit-seconds 300 \
  --output-dir output/example
```

The short alias is `uv run kro`. `--solver` accepts `highs` or `cbc` and defaults
to `highs`. Omit `--time-limit-seconds` for an unlimited solve.
Risk tolerances and limit-overcommit factors are also configurable. See all
options with:

```console
uv run kro --help
```

## Results

The terminal and HTML reports include the selected solver and its status,
active-node count and cost, solve time, placement, and recommended requests and
limits. When `--output-dir` is
provided, the optimizer creates a portable `index.html` report with tables and
SVG charts. Open it directly in a browser; no web server is required.



The command writes `data/private/usage.csv` by default. Use `--help` for the
supported units and metric-label options.

## Development checks

```console
uv run pytest
uv run ruff check .
uv run mypy src
```
