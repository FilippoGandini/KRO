# Project instructions

## Project

This project implements an offline Kubernetes/OpenShift workload resource
rightsizing and placement optimizer.

The optimizer uses historical CPU and memory utilization to jointly determine:

- CPU requests;
- memory requests;
- CPU limits;
- memory limits;
- workload-to-node placement;
- which candidate nodes are required.

The first version is entirely offline.

There is currently NO connection to a real Kubernetes or OpenShift cluster.

All inputs must come from local CSV files.

The project is intended to implement a transparent Mixed-Integer Linear
Programming (MILP) formulation for:

> Joint Kubernetes workload rightsizing and placement under uncertain
> resource demand.

Do not replace the mathematical optimization model with heuristics unless
explicitly requested.

---

## Main goals

The optimizer must jointly answer:

1. What CPU request should each workload have?
2. What memory request should each workload have?
3. What CPU limit should each workload have?
4. What memory limit should each workload have?
5. On which node should each workload be placed?
6. What is the minimum number of nodes required?
7. Are all historical resource-demand scenarios feasible under the proposed
   configuration?

---

## Scope of version 1

Version 1 must:

- read all input data from CSV files;
- optimize a static set of workloads;
- optimize a static set of candidate nodes;
- use historical utilization observations as demand scenarios;
- support CPU;
- support memory;
- optimize requests;
- optimize limits;
- optimize placement;
- minimize the number of active nodes;
- output recommendations and placement results;
- provide useful optimization diagnostics.

Version 1 must NOT:

- connect to Kubernetes;
- connect to OpenShift;
- query Prometheus;
- query Thanos;
- modify workloads;
- modify cluster configuration;
- call cloud APIs;
- implement controllers/operators;
- implement real-time autoscaling.

---

## Mathematical formulation

The mathematical model described below is the source of truth.

Do not silently modify its semantics.

If implementation requires a mathematical change, document the proposed change
before implementing it.

---

## Sets and indices

Use:

- `i in I`: workload/pod;
- `j in J`: candidate node;
- `t in T`: historical time point / demand scenario;
- `h in H`: resource type.

Initially:

`H = {cpu, memory}`

---

## Parameters

### Historical utilization

For each workload `i`, time `t`, and resource `h`:

`u[i,t,h]`

Historical observed utilization.

Examples:

- CPU expressed in CPU cores;
- memory expressed in MiB.

Use one consistent internal unit for each resource.

---

### Node capacity

For each node `j` and resource `h`:

`C[j,h]`

Physical capacity of the node.

Examples:

- `C[j,cpu] = 8.0`
- `C[j,memory] = 32768`

---

### Request risk tolerance

For each resource `h`:

`epsilon_request[h]`

Interpretation:

The selected request may be lower than historical observed utilization in at
most:

`epsilon_request[h] * |T|`

historical scenarios.

Example:

`epsilon_request[cpu] = 0.05`

means that CPU request may be lower than observed CPU utilization in at most
5% of the historical scenarios.

---

### Limit risk tolerance

For each resource `h`:

`epsilon_limit[h]`

Interpretation:

The selected limit may be lower than historical observed utilization in at
most:

`epsilon_limit[h] * |T|`

historical scenarios.

Normally:

`epsilon_limit[h] < epsilon_request[h]`

because limits should generally be more conservative than requests.

Example:

- `epsilon_request[cpu] = 0.05`
- `epsilon_limit[cpu] = 0.01`

---

### Limit overcommit factor

For each resource `h`:

`K_limit[h]`

This controls the maximum aggregate configured limits allowed on one node.

Initial defaults:

- `K_limit[cpu] = 1.5`
- `K_limit[memory] = 1.5`

Interpretation:

If a node has CPU capacity equal to 8 cores and:

`K_limit[cpu] = 1.5`

then the sum of CPU limits of workloads assigned to that node may not exceed:

`12 CPU cores`

These values must be configurable.

Do not hard-code them in the mathematical model.

---

### Request upper bound

For each workload `i` and resource `h`:

`R_max[i,h]`

with:

`0 <= r[i,h] <= R_max[i,h]`

This parameter is required by the effective-demand linearization.

Use a meaningful and tight upper bound whenever possible.

A safe initial fallback may be the maximum compatible node capacity for that
resource.

---

### Limit upper bound

For each workload `i` and resource `h`:

`L_max[i,h]`

with:

`0 <= l[i,h] <= L_max[i,h]`

This parameter is required by the linearization of:

`l[i,h] * x[i,j]`

For a first implementation, a safe default may be:

`L_max[i,h] = max compatible node capacity for resource h`

Prefer tighter workload-specific bounds when they can be derived safely.

---

### Big-M parameters

Use:

- `M_request[i,h]`
- `M_limit[i,h]`

Big-M values must be finite and as tight as practical.

Avoid arbitrary values such as:

`1e9`

when meaningful bounds can be derived from:

- historical utilization;
- request upper bounds;
- limit upper bounds;
- node capacities.

Document how each Big-M value is derived.

---

## Decision variables

### Placement variable

For every workload `i` and node `j`:

`x[i,j] in {0,1}`

Interpretation:

`x[i,j] = 1`

if workload `i` is assigned to node `j`.

---

### Node activation variable

For every node `j`:

`y[j] in {0,1}`

Interpretation:

`y[j] = 1`

if node `j` is active / required by the solution.

---

### Request variable

For every workload `i` and resource `h`:

`r[i,h] >= 0`

This is the optimized resource request.

---

### Limit variable

For every workload `i` and resource `h`:

`l[i,h] >= 0`

This is the optimized resource limit.

---

### Request violation variable

For every workload `i`, time `t`, and resource `h`:

`z[i,t,h] in {0,1}`

Interpretation:

`z[i,t,h] = 1`

allows historical utilization in scenario `t` to exceed the selected request.

---

### Limit violation variable

For every workload `i`, time `t`, and resource `h`:

`w[i,t,h] in {0,1}`

Interpretation:

`w[i,t,h] = 1`

allows historical utilization in scenario `t` to exceed the selected limit.

---

### Effective demand variable

For every workload `i`, node `j`, time `t`, and resource `h`:

`q[i,j,t,h] >= 0`

This variable linearizes the intended expression:

`max(u[i,t,h], r[i,h]) * x[i,j]`

Do not implement the nonlinear `max()` directly.

---

### Limit-placement auxiliary variable

For every workload `i`, node `j`, and resource `h`:

`s[i,j,h] >= 0`

This variable linearizes:

`l[i,h] * x[i,j]`

---

## Objective function

The primary objective for version 1 is:

`minimize sum_j y[j]`

That is:

Minimize the number of active nodes.

Do not automatically replace this objective with:

- utilization balancing;
- cost minimization;
- request minimization;
- limit minimization.

---

## Secondary objective

The primary objective may produce multiple optimal solutions with different
requests and limits.

The architecture should allow later introduction of a secondary objective.

Possible future secondary objectives:

`minimize sum_i,h r[i,h]`

or:

`minimize sum_i,h l[i,h]`

or a weighted combination.

If the chosen solver supports hierarchical or lexicographic objectives cleanly,
keep this extension possible.

Do not introduce a secondary objective unless explicitly requested.

---

## Constraints

### 1. Every workload must be assigned exactly once

For every workload `i`:

`sum_j x[i,j] = 1`

This guarantees exactly one placement for every workload.

---

### 2. Placement requires an active node

For every workload `i` and node `j`:

`x[i,j] <= y[j]`

A workload cannot be assigned to an inactive node.

---

### 3. Request chance constraint

For every workload `i`, time `t`, and resource `h`:

`u[i,t,h] <= r[i,h] + M_request[i,h] * z[i,t,h]`

and:

`sum_t z[i,t,h] <= epsilon_request[h] * |T|`

Interpretation:

The request must cover historical utilization in at least:

`1 - epsilon_request[h]`

of the scenarios.

Because the left side is integer-valued, the implementation must convert the
maximum allowed violations into an explicit integer count.

For example:

`max_request_violations = floor(epsilon_request[h] * |T|)`

Use a deterministic rule and test it.

---

### 4. Limit chance constraint

For every workload `i`, time `t`, and resource `h`:

`u[i,t,h] <= l[i,h] + M_limit[i,h] * w[i,t,h]`

and:

`sum_t w[i,t,h] <= epsilon_limit[h] * |T|`

Interpretation:

The limit must cover historical utilization in at least:

`1 - epsilon_limit[h]`

of the scenarios.

As with requests, convert the maximum allowed number of violations into an
explicit integer count.

---

### 5. Request must not exceed limit

For every workload `i` and resource `h`:

`r[i,h] <= l[i,h]`

This constraint is mandatory.

---

### 6. Request upper bound

For every workload `i` and resource `h`:

`r[i,h] <= R_max[i,h]`

Also require:

`r[i,h] >= 0`

---

### 7. Limit upper bound

For every workload `i` and resource `h`:

`l[i,h] <= L_max[i,h]`

Also require:

`l[i,h] >= 0`

---

## Effective demand formulation

The intended runtime demand for workload `i` in scenario `t` is:

`max(u[i,t,h], r[i,h])`

when the workload is assigned to node `j`.

The nonlinear expression:

`max(u[i,t,h], r[i,h]) * x[i,j]`

must NOT be implemented directly.

Use variable:

`q[i,j,t,h]`

---

### Effective demand lower bound from utilization

For every `i,j,t,h`:

`q[i,j,t,h] >= u[i,t,h] * x[i,j]`

This is linear because:

`u[i,t,h]`

is input data, not a decision variable.

---

### Effective demand lower bound from request

For every `i,j,t,h`:

`q[i,j,t,h] >= r[i,h] - R_max[i,h] * (1 - x[i,j])`

When:

`x[i,j] = 1`

this becomes:

`q[i,j,t,h] >= r[i,h]`

When:

`x[i,j] = 0`

the right-hand side becomes non-positive or zero because:

`r[i,h] <= R_max[i,h]`

allowing:

`q[i,j,t,h] = 0`

---

### Effective demand non-negativity

For every `i,j,t,h`:

`q[i,j,t,h] >= 0`

---

## Runtime node-capacity constraint

For every node `j`, time `t`, and resource `h`:

`sum_i q[i,j,t,h] <= C[j,h] * y[j]`

Interpretation:

For every historical demand scenario, the effective demand assigned to an
active node must fit within the physical node capacity.

This is intentionally conservative in version 1.

Do not introduce node-level overload probabilities unless explicitly requested.

---

## Limit overcommit constraint

The intended constraint is:

`sum_i l[i,h] * x[i,j] <= K_limit[h] * C[j,h] * y[j]`

for every node `j` and resource `h`.

This expression is bilinear because both:

- `l[i,h]`
- `x[i,j]`

are decision variables.

Do NOT implement the bilinear product directly.

Use auxiliary variable:

`s[i,j,h]`

representing:

`s[i,j,h] = l[i,h] * x[i,j]`

---

## Linearization of limit times placement

For every workload `i`, node `j`, and resource `h`:

`s[i,j,h] <= l[i,h]`

`s[i,j,h] <= L_max[i,h] * x[i,j]`

`s[i,j,h] >= l[i,h] - L_max[i,h] * (1 - x[i,j])`

`s[i,j,h] >= 0`

This is the exact linearization of:

`s[i,j,h] = l[i,h] * x[i,j]`

given:

`0 <= l[i,h] <= L_max[i,h]`

---

## Linearized limit overcommit constraint

For every node `j` and resource `h`:

`sum_i s[i,j,h] <= K_limit[h] * C[j,h] * y[j]`

Example:

If:

`K_limit[cpu] = 1.5`

and:

`C[j,cpu] = 8`

then:

`sum_i s[i,j,cpu] <= 12`

for that node.

---

## Important modeling requirements

The model must remain a MILP.

Do not introduce:

- nonlinear max expressions;
- products between decision variables;
- quadratic constraints;
- quadratic objectives;
- nonlinear objectives;

unless explicitly requested.

Do not replace:

`max(usage, request)`

with only:

`usage`

or only:

`request`

because this changes the intended semantics.

Do not remove:

- request violation variables;
- limit violation variables;
- effective-demand variables;
- limit-placement linearization;
- limit overcommit constraints.

Do not silently replace chance constraints with percentiles.

Percentile-based heuristics may later be introduced as comparison baselines,
but they are not the optimization formulation.

---

## CPU and memory

CPU and memory must use the same general mathematical structure.

However, they must remain independently configurable.

Support separate values for:

- `epsilon_request[cpu]`
- `epsilon_request[memory]`
- `epsilon_limit[cpu]`
- `epsilon_limit[memory]`
- `K_limit[cpu]`
- `K_limit[memory]`
- `R_max[i,cpu]`
- `R_max[i,memory]`
- `L_max[i,cpu]`
- `L_max[i,memory]`
- `M_request[i,cpu]`
- `M_request[i,memory]`
- `M_limit[i,cpu]`
- `M_limit[i,memory]`

Do not assume CPU and memory have identical operational risk.

---

## Input data

Keep CSV parsing independent from optimization logic.

A reasonable initial directory structure is:

```text
data/
    nodes.csv
    workloads.csv
    usage.csv



## nodes.csv

Suggested schema:

    node_id,cpu_capacity,memory_capacity
    node-1,8,32768
    node-2,8,32768
    node-3,16,65536

Requirements:

- `node_id` must be unique;
- CPU capacity must be positive;
- memory capacity must be positive.

---

## workloads.csv

Minimum schema:

    workload_id

Optional fields:

    current_cpu_request
    current_memory_request
    current_cpu_limit
    current_memory_limit
    cpu_request_max
    memory_request_max
    cpu_limit_max
    memory_limit_max

Current requests and limits are informational in version 1 unless explicitly
used in the model.

Do not automatically add penalties relative to current configuration.

---

## usage.csv

Prefer long format:

    timestamp,workload_id,cpu_usage,memory_usage
    2026-08-01T10:00:00Z,pod-a,0.25,512
    2026-08-01T11:00:00Z,pod-a,0.31,530
    2026-08-01T10:00:00Z,pod-b,1.20,2048
    2026-08-01T11:00:00Z,pod-b,0.90,1980

Each row represents one historical scenario observation for one workload.

---

## Scenario consistency

All workloads must have a well-defined scenario set.

Prefer a common aligned time index across workloads.

Input validation must detect:

- unknown workload IDs;
- duplicate `(timestamp, workload_id)` rows;
- missing workloads;
- missing node capacities;
- negative CPU utilization;
- negative memory utilization;
- invalid timestamps;
- invalid maximum bounds;
- empty usage history;
- inconsistent scenario timestamps;
- missing utilization values;
- non-finite values.

Do not silently drop malformed rows.

---

## Internal units

Use canonical internal units.

Recommended:

- CPU: cores as float;
- memory: MiB as float.

Examples:

- `500m CPU` -> `0.5`
- `1 CPU` -> `1.0`
- `1 GiB` -> `1024 MiB`

Do not mix:

- millicores and cores;
- bytes and MiB;
- MiB and GiB;

inside optimization expressions.

All conversions belong in the input/domain layer.

---

## Domain model

Represent parsed and validated input data using explicit domain objects.

Prefer dataclasses where appropriate.

Example conceptual objects:

    @dataclass(frozen=True)
    class Node:
        node_id: str
        cpu_capacity: float
        memory_capacity: float


    @dataclass(frozen=True)
    class Workload:
        workload_id: str
        cpu_request_max: float | None = None
        memory_request_max: float | None = None
        cpu_limit_max: float | None = None
        memory_limit_max: float | None = None


    @dataclass(frozen=True)
    class UsageSample:
        timestamp: datetime
        workload_id: str
        cpu_usage: float
        memory_usage: float

Exact class names may change if needed.

---

## Optimization configuration

All mathematical tuning parameters must be explicit.

Prefer a dedicated configuration object.

Example:

    @dataclass(frozen=True)
    class OptimizationConfig:
        epsilon_cpu_request: float
        epsilon_memory_request: float
        epsilon_cpu_limit: float
        epsilon_memory_limit: float
        cpu_limit_overcommit: float
        memory_limit_overcommit: float

Potential additional fields:

    solver_time_limit_seconds: float | None
    mip_gap: float | None

Do not hide mathematical constants inside implementation functions.

---

## Internal architecture

Prefer a structure similar to:

    src/
        kubernetes_resource_optimizer/
            __init__.py

            data/
                models.py
                csv_loader.py
                validation.py
                units.py

            optimization/
                config.py
                bounds.py
                variables.py
                request_constraints.py
                limit_constraints.py
                placement_constraints.py
                capacity_constraints.py
                objective.py
                model.py
                solver.py

            results/
                models.py
                extraction.py
                diagnostics.py
                reporting.py

            cli.py

    tests/
        data/
        optimization/
        results/

Exact filenames may change if there is a strong reason.

The important separation is:

    CSV/input parsing
        !=
    domain model
        !=
    optimization model construction
        !=
    solver execution
        !=
    solution extraction
        !=
    reporting

---

## Solver architecture

Keep solver-specific code isolated.

The mathematical formulation must not be scattered across CLI code or CSV
parsing code.

Prefer a conceptual API such as:

    problem = OptimizationProblem(...)
    model = build_model(problem, config)
    solution = solve(model)
    result = extract_solution(problem, model, solution)

Do not mix input parsing directly into the MILP builder.

---

## Solver choice

Use a MILP-capable solver.

Prefer a solver that:

- supports integer and continuous variables;
- supports linear constraints;
- exposes solver status clearly;
- is practical for local development;
- has a Python API suitable for testing.

Do not introduce multiple solver backends in version 1 unless explicitly
requested.

Keep solver-dependent APIs behind a small abstraction layer.

---

## Bound derivation

Create dedicated logic for deriving:

- `R_max[i,h]`
- `L_max[i,h]`
- `M_request[i,h]`
- `M_limit[i,h]`

Do not compute these values ad hoc inside constraint-building loops.

Prefer deterministic functions such as:

    derive_request_upper_bound(...)
    derive_limit_upper_bound(...)
    derive_request_big_m(...)
    derive_limit_big_m(...)

Document the formulas.

---

## Suggested default upper bounds

For version 1, when workload-specific values are not supplied:

CPU:

    L_max[i,cpu] = maximum CPU capacity among candidate nodes
    R_max[i,cpu] = L_max[i,cpu]

Memory:

    L_max[i,memory] = maximum memory capacity among candidate nodes
    R_max[i,memory] = L_max[i,memory]

These are safe fallback bounds.

If tighter bounds can be safely derived from historical utilization, prefer
them.

---

## Suggested Big-M derivation

For the request chance constraint:

    u[i,t,h] <= r[i,h] + M_request[i,h] * z[i,t,h]

a valid bound may be derived from:

    M_request[i,h] >= max_t u[i,t,h]

because:

    r[i,h] >= 0

Prefer the tightest valid value.

For the limit chance constraint:

    u[i,t,h] <= l[i,h] + M_limit[i,h] * w[i,t,h]

a similar bound may be used.

Document the exact chosen derivation in code and README.

---

## Result model

The optimizer must produce structured output.

For every workload:

    workload_id
    recommended_cpu_request
    recommended_memory_request
    recommended_cpu_limit
    recommended_memory_limit
    assigned_node

For every node:

    node_id
    active
    assigned_workloads

---

## Summary results

At minimum report:

    solver_status
    objective_value
    active_node_count
    total_node_count
    solve_time_seconds

---

## Diagnostics

Where practical, also compute:

    request_violation_count
    request_violation_rate
    limit_violation_count
    limit_violation_rate
    peak_effective_cpu_per_node
    peak_effective_memory_per_node
    configured_cpu_limit_overcommit_per_node
    configured_memory_limit_overcommit_per_node
    cpu_capacity_utilization_per_scenario
    memory_capacity_utilization_per_scenario

Diagnostics must be computed from the returned solution, not guessed from input.

---

## Output formats

Version 1 may initially print human-readable output.

Design the result model so it can later support:

- CSV export;
- JSON export;
- tables;
- charts;
- README examples.

Do not couple optimization logic to terminal formatting.

---

## Correctness requirements

Optimization correctness is more important than implementation speed.

Use small deterministic test instances where the mathematically correct result
is known.

At minimum include tests for:

1. one workload and one node;
2. multiple workloads and one node;
3. two nodes where only one is required;
4. two nodes where both are required;
5. request chance constraint;
6. limit chance constraint;
7. `request <= limit`;
8. `R_max` enforcement;
9. `L_max` enforcement;
10. effective-demand linearization;
11. limit-placement product linearization;
12. limit overcommit constraint;
13. CPU capacity;
14. memory capacity;
15. infeasible instances;
16. solver status handling;
17. zero allowed violations;
18. non-zero allowed violations;
19. heterogeneous node capacities;
20. both CPU and memory active simultaneously.

---

## Effective-demand linearization tests

Explicitly verify both placement states.

Case:

    x[i,j] = 0

must allow:

    q[i,j,t,h] = 0

Case:

    x[i,j] = 1

must enforce:

    q[i,j,t,h] >= max(u[i,t,h], r[i,h])

Test both:

    usage < request

and:

    usage > request

---

## Limit-placement linearization tests

For:

    s[i,j,h] = l[i,h] * x[i,j]

verify:

Case:

    x[i,j] = 0

Expected:

    s[i,j,h] = 0

Case:

    x[i,j] = 1

Expected:

    s[i,j,h] = l[i,h]

---

## Risk-constraint tests

For a known number of scenarios, explicitly test the conversion from epsilon to
maximum allowed violations.

Example:

If:

    |T| = 20

and:

    epsilon_request = 0.05

then:

    floor(20 * 0.05) = 1

request violation is allowed.

Boundary behavior must be deterministic and documented.

---

## Numerical quality

Avoid loose Big-M constants.

Derive bounds from:

- node capacities;
- `R_max`;
- `L_max`;
- maximum observed utilization.

All generated Big-M values must be:

- finite;
- non-negative;
- documented;
- validated.

Tests should assert this.

---

## Infeasibility

The optimizer must handle infeasible instances explicitly.

Examples:

- one workload requires more memory than every candidate node can support;
- risk tolerances are too strict;
- `L_max` is below the required historical demand;
- limit-overcommit restrictions make placement impossible.

Do not crash with an obscure stack trace.

Return a clear solver status and diagnostic message.

---

## Development rules

- Use Python 3.12+.
- Use type hints.
- Use dataclasses where appropriate.
- Use pytest for tests.
- Use ruff for linting.
- Use mypy where practical.
- Prefer small and testable modules.
- Keep functions focused.
- Prefer explicit code over clever abstractions.
- Avoid premature optimization.
- Avoid unnecessary frameworks.
- Document mathematical assumptions.
- Add docstrings where mathematical meaning is not obvious.
- Preserve reproducibility.
- Keep optimization logic deterministic whenever possible.

---

## Dependency rules

Do not introduce heavy frameworks unless needed.

Do not add:

- Kubernetes Python client;
- OpenShift clients;
- cloud SDKs;
- Prometheus clients;
- web frameworks;
- databases;

unless explicitly requested.

Prefer the smallest dependency set needed to:

- parse data;
- build the MILP;
- solve it;
- test it.

---

## Implementation workflow

Implement incrementally.

Preferred order:

1. domain models;
2. units;
3. CSV schemas;
4. CSV loading;
5. validation;
6. optimization configuration;
7. bound derivation;
8. small synthetic datasets;
9. placement variables;
10. node activation variables;
11. request variables;
12. limit variables;
13. request violation variables;
14. limit violation variables;
15. chance constraints;
16. effective-demand variables;
17. effective-demand linearization;
18. runtime capacity constraints;
19. limit-placement auxiliary variables;
20. limit-placement linearization;
21. limit-overcommit constraints;
22. objective function;
23. solver execution;
24. solution extraction;
25. diagnostics;
26. CLI;
27. reporting;
28. larger integration tests.

Do not implement the entire application as one monolithic change.

---

## CLI

The CLI should remain thin.

It should:

1. parse command-line arguments;
2. load CSV files;
3. validate inputs;
4. build the optimization problem;
5. invoke the solver;
6. print or save results.

Do not place mathematical constraints directly inside the CLI.

A possible future interface may look like:

    kubernetes-resource-optimizer optimize \
      --nodes data/nodes.csv \
      --workloads data/workloads.csv \
      --usage data/usage.csv

Do not finalize the CLI syntax unless explicitly requested.

---

## Logging

Use standard Python logging if logging is needed.

Do not introduce a logging framework.

Useful log points include:

- number of workloads;
- number of nodes;
- number of scenarios;
- number of optimization variables;
- number of constraints;
- solver status;
- solve duration.

Do not log full input datasets by default.

---

## Documentation

Keep the README understandable to both:

- Kubernetes / Cloud engineers;
- Operations Research / optimization readers.

Explain:

- the problem;
- why requests matter for scheduling;
- why limits are modeled separately;
- why historical utilization is treated as scenarios;
- why `max(usage, request)` is used;
- why the formulation is MILP;
- how nonlinear-looking expressions are linearized;
- the meaning of `epsilon_request`;
- the meaning of `epsilon_limit`;
- the meaning of `K_limit`;
- the role of `R_max`;
- the role of `L_max`;
- current limitations.

---

## Mathematical documentation

Whenever a mathematical constraint is implemented, preserve a direct mapping
between code and formulation.

Prefer function names such as:

    add_assignment_constraints(...)
    add_node_activation_constraints(...)
    add_request_chance_constraints(...)
    add_limit_chance_constraints(...)
    add_effective_demand_constraints(...)
    add_runtime_capacity_constraints(...)
    add_limit_linearization_constraints(...)
    add_limit_overcommit_constraints(...)

Avoid generic functions such as:

    add_constraints(...)

when they hide mathematical meaning.

---

## Code comments

Comments should explain mathematical intent, not restate Python syntax.

Good:

    # Enforce q >= request when the workload is placed on this node.

Bad:

    # Add constraint.

---

## Naming conventions

Use names close to the mathematical notation where practical.

Suggested mapping:

    x -> placement
    y -> node_active
    r -> request
    l -> limit
    z -> request_violation
    w -> limit_violation
    q -> effective_demand
    s -> placed_limit

Avoid cryptic internal names that make model inspection difficult.

---

## Model inspectability

Where supported by the solver, make it possible to:

- inspect variable names;
- inspect constraints;
- export the model;
- understand infeasibility.

Use descriptive variable names, for example:

    placement[pod-a,node-1]
    request[pod-a,cpu]
    limit[pod-a,memory]
    effective_demand[pod-a,node-1,t10,cpu]

---

## Performance considerations

Correctness comes first.

Do not prematurely optimize the implementation.

However, be aware that:

    q[i,j,t,h]

creates a variable for every combination of:

- workload;
- node;
- scenario;
- resource.

This may become large.

Version 1 may use small and medium offline datasets.

Do not redesign the formulation for scale unless explicitly requested.

Document model size when practical.

---

## Reproducibility

For deterministic inputs and deterministic solver settings, results should be
reproducible where the solver allows it.

If solver seeds or deterministic modes exist and are practical, expose them
through configuration rather than hard-coding them.

---

## Baselines

Future comparisons may include:

- current Kubernetes requests and limits;
- P95 request heuristic;
- P99 or P99.9 limit heuristic;
- Kubernetes VPA recommendations.

Do NOT implement these baselines unless explicitly requested.

The MILP remains the core model.

---

## Security

- Work only inside this repository.
- Never inspect files outside this repository.
- Never access `~/.ssh`.
- Never access `~/.aws`.
- Never access `~/.azure`.
- Never access `~/.kube`.
- Never access credentials.
- Never run `sudo`.
- Never install system-wide software.
- Never modify system configuration.
- Never push to GitHub.
- Do not use external network access unless explicitly requested.
- Do not read unrelated private data.

---

## Git

Codex may inspect:

    git status
    git diff
    git log
    git branch

Do not commit unless explicitly requested.

Do not push unless explicitly requested.

Never force-push.

Do not rewrite Git history unless explicitly requested.

---

## Verification

After modifying Python code:

1. run the relevant pytest tests;
2. run the full pytest suite when practical;
3. run `ruff check`;
4. run `mypy` if configured;
5. report exactly what was executed;
6. report failures clearly;
7. do not hide failing tests;
8. do not disable tests merely to make CI pass;
9. do not weaken assertions merely to make tests pass.

---

## Decision policy for Codex

When a requirement is ambiguous:

1. preserve the mathematical formulation;
2. choose the simplest implementation;
3. avoid adding dependencies;
4. avoid adding features not requested;
5. state assumptions explicitly.

If a requested implementation change would alter the optimization semantics,
explain the mathematical consequence before implementing it.

---

## Non-goals

Do not turn this project into:

- a Kubernetes operator;
- a real-time scheduler;
- an autoscaler;
- a monitoring platform;
- a Prometheus collector;
- a cloud cost platform;
- a generic optimization framework.

The current goal is a clear, testable, offline MILP implementation of joint
workload rightsizing and placement.
