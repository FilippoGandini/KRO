# Kubernetes Resource Optimizer

Kubernetes Resource Optimizer (KRO) is an offline tool for resource request and
limit rightsizing and pod placement. It uses historical CPU and memory data to
determine jointly:

- the requests and limits of each pod;
- the candidate node on which each pod should be placed;
- the subset of nodes to activate while minimizing total node cost.

The problem is formulated as a Mixed-Integer Linear Program (MILP).
It first minimizes active-node cost, then normalized requests, and finally
maximizes demand-weighted normalized limits. Optional fairness inserts a phase
that maximizes the sum of the minimum normalized request–limit margins for CPU
and memory before limit allocation. Each phase preserves preceding objective
optima; these are successive MILP solves, not a weighted approximation.
Recommendations satisfy capacity constraints in every historical scenario,
configurable tolerances for request and limit exceedances, and configurable
limit-overcommit thresholds. Workloads with complementary temporal profiles may
share a node when their aggregate demand remains compatible with the node capacity.

The project does not connect to Kubernetes and never
changes a cluster. All inputs are local CSV files. The formulation, assumptions,
parameters, and limitations are described in the
/docs.

Here, “workload” refers to an application or service in general; each modeled
entity is an individual pod, including one replica of a service. Requests and
limits are represented at pod level.

## Requirements and installation

- Python 3.12 or newer
- [uv](https://docs.astral.sh/uv/)

From the repository root:

```console
uv sync
```

PuLP builds the MILP. HiGHS is the default and runs locally in-process through
the `highspy` dependency; CBC remains available through the executable bundled
with PuLP. The optimizer makes no remote API calls. `uv sync` installs HiGHS
automatically from the locked project dependencies. 

## Preparing the input

Create three CSV files. CPU values use cores and memory values use MiB. Every
pod must have the same set of timestamps. Each `workload_id` identifies one
pod, and each row in `workloads.csv` describes that pod. The existing CSV names
and field names are preserved.

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

`service_id` and the four maximum values are optional. Pods with the same
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
Risk tolerances and limit-overcommit parameters are also configurable. See all
options with:

```console
uv run kro --help
```

## Limit priorities and optional fairness

`--limit-priority` selects a demand preference (default: `0`):

| Value | Steady demand near request | Strong peaks | Preference |
| --- | --- | --- | --- |
| -2 | 90% | 10% | Strongest steady-demand preference |
| -1 | 75% | 25% | Moderate steady-demand preference |
| 0 | 50% | 50% | Balanced indicator weights |
| +1 | 25% | 75% | Moderate peak-demand preference |
| +2 | 10% | 90% | Strongest peak-demand preference |

Both indicators are dimensionless and bounded between zero and one. The steady
indicator rewards a lower-history mean close to the minimum coverage request;
the peak indicator rewards average positive tail exceedance. Chance constraints remain in the MILP; the implied request coverage floor is
also included as a redundant bound to strengthen the relaxation.


Use `--fairness` to enable the additional fairness phase (disabled by default).
The final phase preserves the **optimal fairness score**, allowing individual
limits and placements to change. CPU and memory minima are summed, so they may
trade off while preserving that score. Without fairness, larger weights can
concentrate limit budget on selected pods. 
Choose request tolerances (`--epsilon-cpu-request` and
`--epsilon-memory-request`) **conservatively**. Requests are minimized subject
to the selected coverage, jointly with placement, to leave flexibility for
placement and limit headroom. The optimizer does not add an extra request safety
margin. Lower requests do not directly increase the configured limit budget or
physical capacity.

`--time-limit-seconds` is a total budget for all phases. If any phase stops
without certified optimality, subsequent phases are skipped. Reports identify
an incomplete hierarchy and retain the last available feasible recommendation.
Cost is preserved without intentional degradation; normalized objectives use
an absolute tolerance of `1e-9` (`OptimizationConfig.lexicographic_tolerance`),
in addition to solver numerical tolerances. A non-zero MIP gap is rejected for
the lexicographic workflow.

## Results

The CLI shows progress on stderr while loading and validating CSV data, building
the model, running the solver, extracting recommendations, and generating reports.
It includes input counts, model size, and model build time. Results remain on stdout.

The terminal and HTML reports include the selected solver and its status,
active-node count and cost, solve time, placement, and recommended requests and
limits, plus each phase's status, value, and time and whether the hierarchy
completed. The scalar objective is the last phase with an incumbent.
When `--output-dir` is
provided, the optimizer creates a portable `index.html` report with tables and
SVG charts. Open it directly in a browser; no web server is required.


Use `--help` for the supported units and metric-label options.


## Development checks

```console
uv run pytest
uv run ruff check .
uv run mypy src
```
