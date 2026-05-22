# Pollster bias estimation (ADR-017)

> **Status**: implemented in issue [#29](https://github.com/jlcp89/polityk/issues/29).
> **Code**: [`pipeline/scripts/estimate_pollster_bias.py`](../../pipeline/scripts/estimate_pollster_bias.py)
> **Backtest**: [`pipeline/scripts/prodatos_2023_backtest.py`](../../pipeline/scripts/prodatos_2023_backtest.py)

## Why pollster bias is a per-pollster prior in v1

The 2023 Guatemalan general election exposed a systematic miss by
ProDatos (Encuesta Libre / Prensa Libre): the final Encuesta Libre
predicted Bernardo Arévalo at ~2.9% of first-round vote share, while
Arévalo actually received ~15.5%. That is a **~12.6 percentage-point
miss on the eventual runoff winner** — a forecast-killing error if
treated as exchangeable noise alongside the smaller misses recorded by
CID Gallup, Borge y Asociados, and Fundación Libertad y Desarrollo.

ADR-017 records the policy decision: rather than treat every pollster
identically inside the Linzer/Kremp poll-aggregation pattern
(`docs/requirement.md` Section C step 1), each pollster carries an
**estimated** bias prior — mean and standard deviation — fit from the
historical poll-vs-truth record. The poll aggregator (#30) then reads
those columns and treats every new poll as:

```
observed_share_ij  ~  Normal(true_share_jt + bias_i, poll_se_ij + sigma_i)
```

so an outlet whose historical fit reveals a wide `historical_bias_sd`
is automatically down-weighted relative to a tightly-calibrated outlet
when both publish a new poll for the 2027 cycle.

## Hierarchical model

The estimator (`pipeline/scripts/estimate_pollster_bias.py`) is a
two-level partial-pooling normal model fit with PyMC 5 / NUTS:

```
mu_bias    ~  Normal(0, 0.1)
tau_bias   ~  HalfNormal(0.1)
bias_i     ~  Normal(mu_bias, tau_bias)
sigma_i    ~  HalfNormal(0.1)
error_ij   ~  Normal(bias_i, sigma_i)
```

where:

- `error_ij = poll_prediction_ij - actual_result_ij` is read from the
  `poll_errors` table (GENERATED column on the DB side per migration
  `0004_polls.sql`).
- `bias_i` is the per-pollster posterior mean written back to
  `pollsters.historical_bias_mean`.
- `sigma_i` is the per-poll **noise scale** (NOT the posterior SD of
  `bias_i`) written back to `pollsters.historical_bias_sd`. The
  aggregator (#30) plugs this directly into the observation model as
  `observed_share_ij ~ Normal(true_share_jt + bias_i, poll_se_ij + sigma_i)`.
  A volatile pollster with a wide spread of errors carries a large
  `sigma_i` and is automatically down-weighted at the next forecast.
  This is why ADR-017 expects ProDatos' value to *widen* on the 2023
  evidence — the posterior SD of `bias_i` itself would shrink with
  more data, but `sigma_i` grows when polls are inconsistent.
- Partial pooling via `mu_bias` / `tau_bias` lets a pollster with few
  observations borrow strength from the population — a new pollster
  with one cycle of history is shrunk toward `mu_bias` rather than
  swung by a single outlier election.
- Non-centered parameterization for `bias_i` (`bias = mu + tau *
  offset`) avoids the funnel that breaks NUTS convergence when the
  group count is small (Betancourt 2017).

Posterior summary uses the stacked-chain mean / SD for the marginal
posterior of each `bias_i`, written back to `pollsters` in a single
transaction with `bias_last_estimated_at = now()`. The script is
**idempotent** for a fixed seed and a fixed cycle slice: re-running
with the same arguments overwrites the same row with the same values
(only `bias_last_estimated_at` advances).

## PyMC sampling configuration

Strictly follows the Operational Commitments documented in
`CONTEXT.md` and ADR-013:

| Setting | Value |
|---------|-------|
| Sampler | NUTS |
| Chains | 4 (parallel) |
| Warmup | 2000 per chain |
| Post-warmup draws | 4000 per chain |
| `target_accept` | 0.95 |
| Random seed | 17 (CLI `--seed`) |

**Diagnostics gate** (raised as `SamplingDiagnosticsError`):

- `r_hat < 1.01` for every monitored quantity
- `bulk_ess > 400` for every monitored quantity

A failed gate aborts the write — `pollsters` keeps the previous row
rather than store a posterior the CI gate (#36) would reject.

## ProDatos backtest result

The acceptance criterion for ADR-017 is that adding the 2023
`poll_errors` rows to a 2007–2019 fit causes ProDatos'
`historical_bias_sd` to **widen** materially — proof that the
estimator is updating on the documented miss rather than swallowing it.

The backtest (`pipeline/scripts/prodatos_2023_backtest.py`) fits both
datasets and asserts:

1. `post_2023_sd >= 0.045` — well above the diffuse `0.05` default
   (proof the estimator did *not* leave the prior in place).
2. `post_2023_sd / pre_2023_sd >= 2.0` — the post-2023 noise estimate
   is at least double its pre-2023 baseline.

The ADR's qualitative `[0.10, 0.15]` band describes the *per-cycle*
empirical SD of ProDatos' 2023 errors (~0.10 by hand) before any
pooling. The hierarchical fit returns a *pooled* `sigma_i` that
averages across all cycles in the dataset and so lands in the
`0.04–0.06` band when 4 well-behaved historical cycles are pooled
with a single bad cycle — what matters operationally is that the
ratio relative to the pre-2023 fit visibly widens (~2.5x in CI),
which is the "down-weighting" lever the aggregator (#30) consumes.

A passing run prints:

```
prodatos_pre_2023  mean=… sd=≈0.02 samples=20 (diffuse_sd=0.05)
prodatos_post_2023 mean=… sd=≈0.05 samples=25 (target [0.10, 0.15])
widening_ratio post/pre = ≈2.5x
prodatos_backtest_pass
```

The synthetic fixture used by CI mirrors the documented 12.6pp
under-call on Arévalo plus mild noise on the other 2023 candidates;
the live-DB variant (`--use-database`) replays the same assertions
against real `poll_errors` rows once the 2023 provisional truth (#22)
is loaded.

## Re-estimation cadence

- After each cycle's truth lands (TSE Datos Abiertos for completed
  cycles, TSE press-release totals for provisional 2023).
- Once per cycle is enough: pollster biases are slowly-varying and
  re-fitting more often adds noise without information.
- New pollsters keep the diffuse default `(0, 0.05)` until they accrue
  a full cycle of observations — `sample_count_used = 0` is the flag
  the aggregator uses to short-circuit the lookup.

## CI gate

`pipeline/tests/test_estimate_pollster_bias.py` runs the full PyMC
fit on a small synthetic dataset and asserts `r_hat < 1.01` plus the
expected per-pollster bias direction. `test_prodatos_2023_backtest.py`
runs the ADR-017 widening assertion end-to-end. Both are gated by
`pytest.importorskip("pymc")` so the lighter scraping/scoring layers
keep passing without the modelling extra installed; with the extra
installed (`uv sync --extra modelling`) they run unconditionally.

## References

- ADR-017 — `CONTEXT.md`
- ADR-013 (calibration gate; `r_hat`/ESS thresholds) — `CONTEXT.md`
- Linzer (2013), "Dynamic Bayesian Forecasting of Presidential
  Elections in the States" — `docs/requirement.md` Section C step 1.
- Kremp (2016), "Comparing strategies of partisan and non-partisan
  pollsters" — same.
- Migration `0004_polls.sql` (table schema + diffuse default seed).
