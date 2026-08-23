# Kubernetes Resource Optimizer

An offline MILP optimizer that jointly recommends CPU and memory requests and
limits, places workloads, and minimizes the number of active candidate nodes.
All inputs are local CSV files; it does not connect to a cluster or external
service.

## Run the included example

From the repository root:

```console
uv run kubernetes-resource-optimizer \
  --nodes data/examples/nodes.csv \
  --workloads data/examples/workloads.csv \
  --usage data/examples/usage.csv
```

The mathematical risk and overcommit settings are explicit CLI options. Run
`uv run kubernetes-resource-optimizer --help` to see them and their defaults.
