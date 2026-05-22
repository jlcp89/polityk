# Poll aggregator (Linzer / Kremp state-space, issue #30, ADR-017)

> **Status**: implemented in issue [#30](https://github.com/jlcp89/polityk/issues/30).
> **Code**: [`pipeline/models/poll_aggregator.py`](../../pipeline/models/poll_aggregator.py)
> **Reads**: `pollsters.historical_bias_mean` / `historical_bias_sd`
> (written by [`estimate_pollster_bias.py`](../../pipeline/scripts/estimate_pollster_bias.py),
> see [`pollster_bias.md`](pollster_bias.md)).

## What the aggregator does

For each candidate `j` and day `t` in the polling window, the
aggregator infers a posterior over the national first-round vote
share `true_share_{j,t}` from the observed polls. Per ADR-017 and
`docs/requirement.md` Section C step 1 (Linzer / Kremp), each poll is
treated as a noisy measurement of the latent share **shifted by the
pollster's historical bias** and with the **pollster's per-poll
noise scale added to the binomial SE in quadrature**:

```
observed_share_ij  ~  Normal(
    true_share_{j, t_i} + bias_pi,
    sqrt(poll_se_ij**2 + sigma_pi**2)
)
```

`bias_pi` and `sigma_pi` are read from the `pollsters` row populated
upstream by the #29 estimator. They are **fixed inputs** here — the
pollster fit upstream IS the prior; the aggregator does not re-fit
the bias.

## Latent state — Gaussian random walk

```
init_share[j]    ~  Normal(0.2, 0.2)
sigma_walk       ~  HalfNormal(0.02)
step_offset[j,t] ~  Normal(0, 1)                   (non-centered)
step[j,t]        =  sigma_walk * step_offset[j,t]
true_share[j,t]  =  init_share[j] + cumsum(step[j, 1..t])
```

The non-centered parameterisation on the daily step avoids the
classic `tau_walk` funnel when the time grid is dense (Betancourt 2017,
"Diagnosing Biased Inference with Divergences"). `sigma_walk`'s
HalfNormal(0.02) prior allows up to a few percentage points of daily
drift — loose enough to recover late-cycle surges (Arévalo 2023) but
tight enough that the posterior does not oscillate sample-to-sample.

The day grid is dense and daily: from `min(field_end)` to
`max(field_end)` inclusive. Days with no polls are still tracked so
the random walk can interpolate the latent path.

## Per-poll standard error

Derived from the recorded poll metadata in this order:

1. `sample_size`: binomial SE `sqrt(p*(1-p)/n)` where `p` is the
   observed share, `n` the sample size. Clipped at `[1e-4, 1-1e-4]`
   to avoid degenerate SE at the simplex corners.
2. `margin_of_error`: MOE / 1.96 (95% CI convention).
3. Fallback: `0.03` — the typical binomial SE for a Guatemalan
   national poll (n≈1100, p≈0.2) inflated for design effects on
   stratified samples. Logged as a warning by the loader so legacy
   rows that lack `sample_size` / `margin_of_error` are auditable.

## PyMC sampling configuration

| Setting | Value |
|---------|-------|
| Sampler | NUTS |
| Chains | 4 (parallel) |
| Warmup | 2000 per chain |
| Post-warmup draws | 4000 per chain |
| `target_accept` | 0.95 |
| Random seed | 17 (default) |

These are the project's Operational Commitments per ADR-013, also
used by [`pollster_bias.md`](pollster_bias.md). Diagnostics gate
(raised as `SamplingDiagnosticsError`):

- `r_hat < 1.01` for every monitored quantity (init_share,
  sigma_walk, step_offset, true_share)
- `bulk_ess > 400` for every monitored quantity

A failed gate aborts before returning a posterior the CI gate (#36)
would reject.

## Public API

```python
from pipeline.models.poll_aggregator import (
    fit, read_polls, read_pollster_priors, CandidateRef,
)

with psycopg.connect(dsn) as conn:
    polls = read_polls(conn, cycle=2027)
    pollsters = read_pollster_priors(conn)

candidates = [CandidateRef(candidate_id=..., full_name=...), ...]
posterior = fit(polls, pollsters, candidates)

# Final-day quantile table (ADR-014 payload contract).
qs = posterior.final_day_quantiles()        # {cand_id: {0.5: ...}}
```

`AggregatorPosterior.samples` is a `(n_samples, n_days, n_candidates)`
ndarray of stacked-chain draws — the layout the forecast writer (#33)
consumes for the quantile payload.

## Reproducibility

The default seed `17` is the same one used by the pollster-bias
estimator (#29) and the ProDatos backtest (`prodatos_2023_backtest.py`).
With the same input rows and the same seed, the fit is byte-identical
across runs (asserted by `test_fit_is_reproducible_under_fixed_seed`).

## Acceptance: 2019 backtest

`pipeline/tests/test_poll_aggregator.py::test_fit_2019_backtest_covers_actuals_with_80pct_ci`
runs the acceptance criterion from issue #30: fits a 2019-shaped
synthetic fixture (4 candidates, 3 pollsters with the ADR-017
priors, ~12 polls per pollster across 150 days) and asserts the
final-day posterior's 80% CI covers the "actual" first-round share
for ≥ 80% of candidates. CI rate in repeated runs is 100% (4 of 4
covered) on the seeded fixture.

The real-DB variant (run by #36's calibration gate) plays the same
assertion against the live 2019 `polls` rows once the historical
backfill (#19) lands.

## References

- ADR-017 — `CONTEXT.md`
- ADR-013 (calibration gate; `r_hat`/ESS thresholds) — `CONTEXT.md`
- Linzer (2013), "Dynamic Bayesian Forecasting of Presidential
  Elections in the States" — `docs/requirement.md` Section C step 1.
- Kremp (2016), "Comparing strategies of partisan and non-partisan
  pollsters" — same.
- `pipeline/models/poll_aggregator.py` (this module).
- `pipeline/scripts/estimate_pollster_bias.py` (upstream, #29).
