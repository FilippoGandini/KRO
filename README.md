# Kubernetes Resource Optimizer

An offline Mixed-Integer Linear Programming (MILP) optimizer for joint
Kubernetes workload rightsizing and placement.

Given candidate nodes and historical CPU and memory observations, the optimizer
jointly recommends:

- CPU and memory requests;
- CPU and memory limits;
- one candidate node for each workload;
- the minimum set of candidate nodes required by the solution.

The project is intentionally offline. It reads local CSV files and does not
connect to Kubernetes, OpenShift, Prometheus, cloud APIs, or any other external
service.

## Project status

This project is in early development. The core version 1 MILP, CSV input layer,
CBC solver integration, structured result extraction, diagnostics, and a small
CLI are implemented and covered by deterministic tests. Interfaces and output
formats may still change before the first stable release.

## Mathematical model

Historical observations are treated as aligned demand scenarios. The primary
objective minimizes the number of active nodes while enforcing, for both CPU
and memory:

- exactly one placement per workload;
- placement only on active nodes;
- request and limit chance constraints with configurable risk tolerances;
- `request <= limit` and explicit workload upper bounds;
- runtime capacity in every historical scenario;
- configurable aggregate limit overcommit per node.

Runtime capacity uses `max(observed usage, request)` for a placed workload. The
model remains linear by introducing effective-demand and placed-limit auxiliary
variables instead of using nonlinear `max` expressions or products between
decision variables.

The current objective only minimizes active nodes. Requests and limits are not
yet subject to a secondary objective, so multiple optimal configurations may
exist.

## Requirements

- Python 3.12 or newer
- [uv](https://docs.astral.sh/uv/) for the documented development workflow

PuLP is used to build the MILP and its bundled CBC integration is used to solve
it locally.

## Run the included example

Install the locked dependencies and run the optimizer from the repository root:

```console
uv sync
uv run kubernetes-resource-optimizer \
  --nodes data/examples/nodes.csv \
  --workloads data/examples/workloads.csv \
  --usage data/examples/usage.csv
```

The shorter `uv run kro` command is also available. Run the CLI help to inspect
the configurable request-risk, limit-risk, and limit-overcommit options:

```console
uv run kubernetes-resource-optimizer --help
```

## Input files

The CLI expects three CSV files.

`nodes.csv`:

```csv
node_id,cpu_capacity,memory_capacity
node-a,4,4096
```

`workloads.csv`:

```csv
workload_id,cpu_request_max,memory_request_max,cpu_limit_max,memory_limit_max
api,4,4096,4,4096
```

`usage.csv`:

```csv
timestamp,workload_id,cpu_usage,memory_usage
2026-08-01T10:00:00Z,api,0.5,512
```

CPU values use cores and memory values use MiB internally. Usage timestamps
must form a common aligned scenario set across all workloads. Invalid,
incomplete, duplicate, negative, or non-finite input is rejected rather than
silently discarded.

See [`data/examples`](data/examples) for a complete runnable dataset.

## Development checks

```console
uv run pytest
uv run ruff check .
uv run mypy src
```

## Current limitations

- static workloads and candidate nodes only;
- historical scenarios only; no forecasts or live metrics;
- CPU and memory only;
- one local solver backend;
- human-readable CLI output only;
- no cluster changes, controllers, operators, or real-time autoscaling;
- no secondary objective for selecting among solutions with the same minimum
  node count.

## Roadmap

Near-term work includes strengthening type checking, expanding diagnostics and
reporting, adding export formats, improving infeasibility explanations, and
covering larger integration scenarios. The MILP remains the core model; simple
percentile heuristics are not used as a replacement for it.
