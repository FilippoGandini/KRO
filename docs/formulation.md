# MILP formulation

## Sets and indices

| Symbol | Definition |
|---|---|
| $`I, i`$ | Pods. |
| $`J, j`$ | Candidate nodes. |
| $`T, t`$ | Scenarios; $`N = \lvert T \rvert`$. |
| $`H, h`$ | Resources: CPU, memory. |
| $`\mathcal{G}`$ | Collection of replica groups and independent singleton groups. |
| $`G\in\mathcal{G}`$ | One group of pods; a singleton contains one independent pod. |
| $`i_G`$ | First pod in sorted group ID order. |
| $`\mathcal{E}`$ | Collection of equivalent-node groups (same capacities and cost). |
| $`E\in\mathcal{E}`$ | One equivalent-node group, $`E = (j_1, \ldots, j_{\lvert E \rvert})`$ in input order; $`p`$ indexes positions. |
| $`q`$ | Observation rank, $`1, \ldots, N`$. |


## Parameters

| Symbol | Definition |
|---|---|
| $`u_{ith}\ge0`$ | Usage; $`u_{i(q)h}`$ is the ascending order statistic. |
| $`C_{jh}>0,c_j>0`$ | Node capacity and cost. |
| $`\varepsilon^{\mathrm{req}}_h,\varepsilon^{\mathrm{lim}}_h\in[0,1]`$ | Request and limit exceedance tolerances. |
| $`k_h,b_h`$ | $`\lfloor\varepsilon^{\mathrm{req}}_hN\rfloor,\lfloor\varepsilon^{\mathrm{lim}}_hN\rfloor`$. |
| $`R^{\mathrm{max}}_{ih},B_{ih}\ge0`$ | Request and limit input maxima; each defaults to $`\max_j C_{jh}`$. |
| $`\alpha_h\ge1`$ | Resource-specific peak multiplier; CPU and memory configured independently.|
| $`K_h\ge0`$ | Limit-overcommit factor. |
| $`P_{ih}`$ | $`\max_t u_{ith}`$; coverage Big-M. |
| $`r_{ih}`$ | Shared deterministic request, below. |
| $`U_{ih}`$ | Shared effective limit cap, below. |
| $`a_{ih}`$ | Normalized spike coefficient, below. |

For $`G\in\mathcal{G}`$, $`i\in G`$, $`h\in H`$:

When $`k_h<N`$, the shared request is:

```math
r_{ih}=\max_{v\in G}u_{v(N-k_h)h}.
```

When $`k_h=N`$, set $`r_{ih}=0`$. The shared effective limit cap is:

```math
U_{ih}=\max_{v\in G}\min\{B_{vh},\alpha_h P_{vh}\}.
```

For $`i\in I,h\in H`$:

```math
a_{ih}=\begin{cases}
\displaystyle\frac1{k_h}\sum_{q=N-k_h+1}^{N}
\frac{\max\{0,u_{i(q)h}-r_{ih}\}}{\max\{r_{ih},P_{ih}\}},
&k_h>0,\ \max\{r_{ih},P_{ih}\}>0,\\
0,&\text{otherwise}.
\end{cases}
```

## Decision variables

| Symbol | Domain | Definition |
|---|---|---|
| $`x_{ij}`$ | Binary | Pod assigned to node. |
| $`y_j`$ | Binary | Active node. |
| $`l_{ih}`$ | $`[0,U_{ih}]`$ | Limit. |
| $`w_{ith}`$ | Binary | Permitted limit exceedance. |
| $`s_{ijh}`$ | Nonnegative | Placed limit. |
| $`f_h`$ | $`[0,1]`$, optional | Minimum normalized headroom lower bound. |

## Base MILP

```math
\begin{aligned}
\mathop{\mathrm{lex\,min}}_{x,y,l,w,s}\quad&
\left(\sum_{j\in J}c_jy_j,\;
-\sum_{h\in H}\sum_{\substack{G\in\mathcal{G}\\U_{i_Gh}>0}}
\left(\max_{i\in G}a_{ih}\right)\frac{l_{i_Gh}}{U_{i_Gh}}\right)\\
\text{subject to}\quad
\sum_{j\in J}x_{ij}&=1 &&i\in I,\\
x_{ij}&\le y_j &&i\in I,\ j\in J,\\
y_{j_p}&\ge y_{j_{p+1}} &&E\in\mathcal{E},\ p=1,\ldots,|E|-1,\\
r_{ih}&\le R^{\mathrm{max}}_{ih} &&i\in I,\ h\in H,\\
r_{ih}&\le l_{ih} &&i\in I,\ h\in H,\\
l_{ih}&=l_{i_Gh} &&G\in\mathcal{G},\ i\in G\setminus\{i_G\},\ h\in H,\\
u_{ith}&\le l_{ih}+P_{ih}w_{ith} &&i\in I,\ t\in T,\ h\in H,\\
\sum_{t\in T}w_{ith}&\le b_h &&i\in I,\ h\in H,\\
\sum_{i\in I}\max\{u_{ith},r_{ih}\}x_{ij}&\le C_{jh}y_j &&j\in J,\ t\in T,\ h\in H,\\
s_{ijh}&\le l_{ih} &&i\in I,\ j\in J,\ h\in H,\\
s_{ijh}&\le U_{ih}x_{ij} &&i\in I,\ j\in J,\ h\in H,\\
s_{ijh}&\ge l_{ih}-U_{ih}(1-x_{ij}) &&i\in I,\ j\in J,\ h\in H,\\
\sum_{i\in I}s_{ijh}&\le K_hC_{jh}y_j &&j\in J,\ h\in H,\\
x_{ij}&\in\{0,1\} &&i\in I,\ j\in J,\\
y_j&\in\{0,1\} &&j\in J,\\
w_{ith}&\in\{0,1\} &&i\in I,\ t\in T,\ h\in H,\\
0\le l_{ih}&\le U_{ih} &&i\in I,\ h\in H,\\
s_{ijh}&\ge0 &&i\in I,\ j\in J,\ h\in H.
\end{aligned}
```

## Optional fairness extension

Add the constraints:

```math
\begin{aligned}
f_h&\le\frac{l_{i_Gh}-r_{i_Gh}}{U_{i_Gh}}
&&h\in H,\ G\in\mathcal{G}:\ U_{i_Gh}>0,\\
f_h&=0&&h\in H:\ U_{i_Gh}=0\text{ for every }G\in\mathcal{G},\\
0\le f_h&\le1&&h\in H.
\end{aligned}
```

Maximize $`\sum_h f_h`$ between cost minimization and spike-weighted limits.

---


Full definitions and interpretation: [technical document (PDF)](KRO.pdf).
