"""Fundamentals-layer regression (issue #31, ADR-011, Operational Commitments).

Per-cycle Bayesian regression on the eight features enumerated in
``CONTEXT.md`` Operational Commitments "Fundamentals-layer features
(presidential v1)":

  1. incumbent_party        — binary; True when this candidate's party held
                              the presidency at election time
  2. approval_penalty       — continuous in [0,1]; 1 minus the most-recent
                              pre-election approval reading for the
                              party-of-government (cohort mean fallback)
  3. gdp_yoy                — Real GDP growth YoY (percent, Banguat)
  4. inflation_yoy          — Inflation YoY (percent, Banguat/INE)
  5. remittance_yoy         — Remittance inflow YoY (percent, Banguat)
  6. homicide_yoy           — Homicide-rate change YoY (percent, INE)
  7. sentiment_diff         — Rolling 30-day differential POS-NEG share per
                              candidate from ``sentiment_per_source_subject``
  8. post_candidacy_flag    — Binary; True once the cycle's candidate
                              registry has closed (Feature 8 polling-
                              environment flag)

The target is the candidate's *first-round* national vote share (one row
per ``(cycle, candidate_id)`` with ``elections.round = 1``). The model is
a logit-Normal regression so a bounded share is a natural fit:

      mu_i = beta_0 + sum_k beta_k * X_{i,k}
      logit(share_i) ~ Normal(mu_i, sigma)

Priors:
  * ``beta_0 ~ Normal(-1.5, 1)`` — a four-candidate field averages ~25%
    share, which is logit(0.25) ≈ -1.10; the slightly tighter mean keeps
    the prior centred on a typical multi-candidate Guatemalan field
  * ``beta_k ~ Normal(0, 1)`` after z-scoring continuous features so the
    unit prior is on the standard-deviation scale
  * ``sigma ~ HalfNormal(0.5)`` — observed logit-share noise across
    candidates within a cycle is well under one logit unit

Continuous features are z-scored within the training set; the (mean, sd)
pair is stored on :class:`FundamentalsCoefficients` so :func:`predict`
applies the same transform at inference time. Binary features pass
through unchanged.

Output: per-feature posterior coefficient samples on
:class:`FundamentalsCoefficients`. The presidential combiner (#32)
applies them to candidate-specific feature vectors itself, so the
fundamentals layer stays decoupled from candidate identity. The
:meth:`FundamentalsCoefficients.predict` helper composes the posterior
predictive share for a single feature row and is used by the in-module
backtest.

PyMC sampler config matches the project's Operational Commitments
(4 chains, 2000 warmup, 4000 draws, ``target_accept=0.95``, seed=17)
and ADR-013's C6 calibration gate (``r_hat < 1.01``, ``bulk_ess > 400``).
A diagnostics failure raises :class:`SamplingDiagnosticsError` rather
than emit a broken posterior.

The module is import-safe without PyMC installed; the heavy stack is
lazy-imported inside :func:`fit` so the lighter scraping / scoring
layers don't drag in ``pytensor``.
"""

from __future__ import annotations

import dataclasses
import math
from collections.abc import Sequence
from datetime import date
from typing import Any

# Re-use the estimator's diagnostics exception so callers handle a single
# error type across the modelling pipeline (#29 → #30 → #31 → #32).
from pipeline.scripts.estimate_pollster_bias import SamplingDiagnosticsError

# Feature ordering is part of the public contract: the combiner (#32)
# reads ``FundamentalsCoefficients.samples`` keyed by these names and the
# z-scoring lookups index them too.
FEATURE_NAMES: tuple[str, ...] = (
    "incumbent_party",
    "approval_penalty",
    "gdp_yoy",
    "inflation_yoy",
    "remittance_yoy",
    "homicide_yoy",
    "sentiment_diff",
    "post_candidacy_flag",
)

# Binary features pass through unchanged; the rest are z-scored within
# the training set. Keeping the membership explicit (rather than inferring
# from dtype) makes the test fakes obvious and the contract auditable.
BINARY_FEATURES: frozenset[str] = frozenset({"incumbent_party", "post_candidacy_flag"})

# Canonical macro-indicator codes per the Banguat / INE scraper fixtures
# in ``internal/scrapers/macro/`` (issue #18). Sourced from the loader
# config, NOT hardcoded in the SQL itself — the constants below are the
# values the training-feature query filters against.
MACRO_INDICATOR_CODES: dict[str, tuple[str, str]] = {
    # feature_name -> (source, code) per the macro_indicators schema
    "gdp_yoy": ("banguat", "gdp_yoy_growth"),
    "inflation_yoy": ("banguat", "inflation_yoy"),
    "remittance_yoy": ("banguat", "remittance_inflow_yoy"),
    "homicide_yoy": ("ine", "homicide_rate_yoy"),
}

# Cohort fallback when an approval reading is missing for the incumbent's
# cycle — neutral 0.5 approval gives a 0.5 penalty, which standardises to
# the cohort mean once we z-score. ADR-013 calibration gate (#36) is the
# safety net if missing data hurts coverage.
DEFAULT_APPROVAL_SHARE: float = 0.5


# ---------------------------------------------------------------------------
# Public dataclasses
# ---------------------------------------------------------------------------


@dataclasses.dataclass(frozen=True)
class FeatureVector:
    """One ``(cycle, candidate)`` training/prediction row.

    ``observed_share`` is the round-1 historical vote share (target);
    ``None`` is permitted at prediction time but :func:`fit` requires it.
    """

    cycle: int
    candidate_id: int
    incumbent_party: bool
    approval_penalty: float
    gdp_yoy: float
    inflation_yoy: float
    remittance_yoy: float
    homicide_yoy: float
    sentiment_diff: float
    post_candidacy_flag: bool
    observed_share: float | None = None

    def __post_init__(self) -> None:
        if not 0.0 <= self.approval_penalty <= 1.0:
            raise ValueError(
                f"approval_penalty must be in [0,1], got {self.approval_penalty}"
            )
        if self.observed_share is not None and not 0.0 < self.observed_share < 1.0:
            # Strict-open interval: a share of exactly 0 or 1 is rejected
            # because logit(0)=-inf / logit(1)=+inf breaks the model.
            raise ValueError(
                f"observed_share must be in (0,1) (strict), got {self.observed_share}"
            )

    def feature_array(self) -> list[float]:
        """Return the 8-feature vector in :data:`FEATURE_NAMES` order."""
        return [
            float(self.incumbent_party),
            self.approval_penalty,
            self.gdp_yoy,
            self.inflation_yoy,
            self.remittance_yoy,
            self.homicide_yoy,
            self.sentiment_diff,
            float(self.post_candidacy_flag),
        ]


@dataclasses.dataclass(frozen=True)
class FundamentalsCoefficients:
    """Posterior over the regression coefficients.

    ``samples`` maps feature name to a 1-D ``numpy.ndarray`` of shape
    ``(n_samples,)`` (chain × draw stacked). ``intercept_samples`` and
    ``sigma_samples`` follow the same convention. ``feature_means`` and
    ``feature_sds`` are the training-set z-scoring parameters; binary
    features carry ``mean=0`` and ``sd=1`` so :meth:`predict` can apply
    a uniform transform.
    """

    samples: dict[str, Any]  # name -> numpy.ndarray (n_samples,)
    intercept_samples: Any  # numpy.ndarray (n_samples,)
    sigma_samples: Any  # numpy.ndarray (n_samples,)
    feature_names: tuple[str, ...]
    feature_means: dict[str, float]
    feature_sds: dict[str, float]
    max_r_hat: float
    min_bulk_ess: float
    n_observations: int
    cycles_used: tuple[int, ...]

    def standardize(self, features: FeatureVector) -> list[float]:
        """Apply the training-set z-scoring to a feature vector.

        Binary features pass through with ``mean=0, sd=1``. Returns a
        list aligned with :attr:`feature_names`.
        """
        raw = features.feature_array()
        out: list[float] = []
        for name, value in zip(self.feature_names, raw, strict=True):
            mean = self.feature_means[name]
            sd = self.feature_sds[name]
            if sd <= 0.0:
                out.append(0.0)  # zero-variance training column → no contribution
            else:
                out.append((value - mean) / sd)
        return out

    def predict(
        self,
        features: FeatureVector,
        *,
        include_noise: bool = True,
        rng_seed: int | None = None,
    ) -> Any:
        """Return posterior predictive *share* samples for one feature row.

        ``include_noise=False`` returns the deterministic logit-mean
        sigmoid — i.e., the central tendency. The default ``True`` adds
        per-draw Normal(0, sigma) residual noise so the spread is a
        valid posterior predictive interval (this is what the backtest
        coverage check needs).
        """
        import numpy as np  # noqa: PLC0415

        x = self.standardize(features)
        # mu_samples = intercept + sum_k beta_k * x_k  (broadcasts across draws)
        mu = np.asarray(self.intercept_samples, dtype=float).copy()
        for name, x_k in zip(self.feature_names, x, strict=True):
            mu = mu + np.asarray(self.samples[name], dtype=float) * x_k
        if include_noise:
            rng = np.random.default_rng(rng_seed)
            sigma = np.asarray(self.sigma_samples, dtype=float)
            mu = mu + rng.normal(0.0, sigma)
        # sigmoid → share in (0,1)
        return 1.0 / (1.0 + np.exp(-mu))


@dataclasses.dataclass(frozen=True)
class BacktestCoverage:
    """Per-cycle holdout coverage from :func:`backtest`."""

    holdout_cycle: int
    n_candidates: int
    coverage_80: float
    coverage_95: float
    max_r_hat: float
    min_bulk_ess: float


# ---------------------------------------------------------------------------
# DB I/O helpers — each accepts ``conn: Any`` for fake-conn unit tests
# ---------------------------------------------------------------------------


def read_party_of_government(conn: Any) -> dict[int, int]:
    """Return ``{cycle: party_id}`` from ``party_of_government``."""
    with conn.cursor() as cur:
        cur.execute("SELECT cycle, party_id FROM party_of_government ORDER BY cycle")
        rows = cur.fetchall()
    return {int(r[0]): int(r[1]) for r in rows}


def read_election_key_dates(conn: Any) -> dict[int, date]:
    """Return ``{cycle: candidate_list_closed_at}`` joining ``elections``."""
    sql = """
        SELECT e.cycle, ekd.candidate_list_closed_at
          FROM election_key_dates ekd
          JOIN elections e ON e.election_id = ekd.election_id
         WHERE e.round = 1
         ORDER BY e.cycle
    """
    with conn.cursor() as cur:
        cur.execute(sql)
        rows = cur.fetchall()
    return {int(r[0]): r[1] for r in rows}


def read_approval_penalty(
    conn: Any,
    *,
    cycle: int,
    party_id: int,
    fallback: float = DEFAULT_APPROVAL_SHARE,
) -> float:
    """Return ``1 - approval_share`` for the incumbent at cycle's election.

    Picks the most recent reading for ``(party_id, cycle)`` from
    ``approval_ratings``. Falls back to ``1 - fallback`` (default 0.5)
    when no reading is present so callers don't need to special-case
    sparse historical data.
    """
    sql = """
        SELECT approval_share
          FROM approval_ratings
         WHERE party_id = %s AND cycle = %s
         ORDER BY measured_at DESC
         LIMIT 1
    """
    with conn.cursor() as cur:
        cur.execute(sql, (party_id, cycle))
        row = cur.fetchone()
    if row is None or row[0] is None:
        return 1.0 - fallback
    return 1.0 - float(row[0])


def read_sentiment_differential(
    conn: Any,
    *,
    candidate_id: int,
    election_date: date,
    window_days: int = 30,
) -> float:
    """Return rolling POS-NEG share differential for one candidate.

    Joins ``sentiment_per_source_subject`` (candidate-keyed rows) to
    ``news_articles`` for ``published_at`` and aggregates the dominant
    labels over the trailing ``window_days`` ending at ``election_date``.
    Returns ``pos_count / total - neg_count / total`` in roughly
    ``[-1, 1]``; returns ``0.0`` when no sentiment rows fall in the
    window (pre-2023 cycles before sentiment ingest existed).
    """
    sql = """
        WITH labelled AS (
            SELECT sps.dominant_label
              FROM sentiment_per_source_subject sps
              JOIN news_articles na
                ON sps.source_kind = 'article' AND sps.source_id = na.article_id
             WHERE sps.subject_kind = 'candidate'
               AND sps.subject_id = %s
               AND na.published_at >= (%s::date - %s::int * INTERVAL '1 day')
               AND na.published_at <= %s::date
        )
        SELECT
            COUNT(*) FILTER (WHERE dominant_label = 'POS') AS pos_count,
            COUNT(*) FILTER (WHERE dominant_label = 'NEG') AS neg_count,
            COUNT(*) AS total
          FROM labelled
    """
    with conn.cursor() as cur:
        cur.execute(sql, (candidate_id, election_date, window_days, election_date))
        row = cur.fetchone()
    if row is None:
        return 0.0
    pos = int(row[0] or 0)
    neg = int(row[1] or 0)
    total = int(row[2] or 0)
    if total == 0:
        return 0.0
    return (pos - neg) / total


def _read_training_core(
    conn: Any, *, cycles: Sequence[int]
) -> list[tuple[Any, ...]]:
    """Run the joined training SQL and return raw rows.

    Split from :func:`read_training_features` so per-row enrichment
    (approval, sentiment) can attach without re-running the bulk join.
    """
    sql = """
        WITH cycle_election AS (
            SELECT election_id, cycle
              FROM elections
             WHERE round = 1 AND cycle = ANY(%(cycles)s)
        ),
        cycle_totals AS (
            SELECT ce.cycle, SUM(pr.votes)::bigint AS total_votes
              FROM presidential_results pr
              JOIN cycle_election ce USING (election_id)
             GROUP BY ce.cycle
        ),
        candidate_shares AS (
            SELECT ce.cycle,
                   pr.candidate_id,
                   SUM(pr.votes)::float / NULLIF(ct.total_votes, 0) AS observed_share
              FROM presidential_results pr
              JOIN cycle_election ce USING (election_id)
              JOIN cycle_totals ct USING (cycle)
             GROUP BY ce.cycle, pr.candidate_id, ct.total_votes
        ),
        latest_macro AS (
            SELECT DISTINCT ON (e.cycle, mi.source, mi.code)
                   e.cycle, mi.source, mi.code, mi.value
              FROM elections e
              JOIN macro_indicators mi
                ON mi.observed_at >= make_date(e.cycle - 2, 1, 1)
               AND mi.observed_at <  make_date(e.cycle, 6, 1)
             WHERE e.round = 1
               AND e.cycle = ANY(%(cycles)s)
             ORDER BY e.cycle, mi.source, mi.code, mi.observed_at DESC
        ),
        macro_by_cycle AS (
            SELECT cycle,
                   MAX(value) FILTER (
                       WHERE source = 'banguat' AND code = 'gdp_yoy_growth'
                   ) AS gdp_yoy,
                   MAX(value) FILTER (
                       WHERE source = 'banguat' AND code = 'inflation_yoy'
                   ) AS inflation_yoy,
                   MAX(value) FILTER (
                       WHERE source = 'banguat' AND code = 'remittance_inflow_yoy'
                   ) AS remittance_yoy,
                   MAX(value) FILTER (
                       WHERE source = 'ine' AND code = 'homicide_rate_yoy'
                   ) AS homicide_yoy
              FROM latest_macro
             GROUP BY cycle
        )
        SELECT cs.cycle,
               cs.candidate_id,
               cs.observed_share,
               cp.party_id,
               (cp.party_id = pog.party_id) AS incumbent_party,
               COALESCE(mac.gdp_yoy, 0)::float        AS gdp_yoy,
               COALESCE(mac.inflation_yoy, 0)::float  AS inflation_yoy,
               COALESCE(mac.remittance_yoy, 0)::float AS remittance_yoy,
               COALESCE(mac.homicide_yoy, 0)::float   AS homicide_yoy,
               ekd.candidate_list_closed_at,
               make_date(cs.cycle, 6, 1) AS approx_election_date
          FROM candidate_shares cs
          JOIN candidate_party cp
            ON cp.candidate_id = cs.candidate_id AND cp.cycle = cs.cycle
          LEFT JOIN party_of_government pog ON pog.cycle = cs.cycle
          LEFT JOIN macro_by_cycle mac ON mac.cycle = cs.cycle
          JOIN cycle_election ce ON ce.cycle = cs.cycle
          LEFT JOIN election_key_dates ekd ON ekd.election_id = ce.election_id
         ORDER BY cs.cycle, cs.candidate_id
    """
    with conn.cursor() as cur:
        cur.execute(sql, {"cycles": list(cycles)})
        return list(cur.fetchall())


def read_training_features(
    conn: Any,
    *,
    cycles: Sequence[int],
    sentiment_window_days: int = 30,
) -> list[FeatureVector]:
    """Build :class:`FeatureVector` rows for ``cycles`` from the DB.

    Wires all 8 features via DB joins per issue #31 acceptance criterion.
    Per-row sentiment and approval are fetched after the bulk join so
    cycles without scraped sentiment cleanly degrade to ``0.0`` and
    cycles without approval data fall back to the cohort mean. The
    polling-environment flag is computed from the
    ``approx_election_date`` (1 June of the cycle, the historical TSE
    first-round window) against ``candidate_list_closed_at``: True when
    the registry has closed before the election, which is the training-
    time situation for every backfilled cycle.
    """
    rows = _read_training_core(conn, cycles=cycles)
    out: list[FeatureVector] = []
    for r in rows:
        cycle = int(r[0])
        candidate_id = int(r[1])
        observed_share = float(r[2]) if r[2] is not None else None
        party_id = int(r[3])
        incumbent = bool(r[4])
        gdp_yoy = float(r[5])
        inflation_yoy = float(r[6])
        remittance_yoy = float(r[7])
        homicide_yoy = float(r[8])
        closed_at: date | None = r[9]
        election_date: date = r[10]
        post_candidacy = bool(closed_at is not None and closed_at <= election_date)
        approval_penalty = read_approval_penalty(conn, cycle=cycle, party_id=party_id)
        sentiment_diff = read_sentiment_differential(
            conn,
            candidate_id=candidate_id,
            election_date=election_date,
            window_days=sentiment_window_days,
        )
        out.append(
            FeatureVector(
                cycle=cycle,
                candidate_id=candidate_id,
                incumbent_party=incumbent,
                approval_penalty=approval_penalty,
                gdp_yoy=gdp_yoy,
                inflation_yoy=inflation_yoy,
                remittance_yoy=remittance_yoy,
                homicide_yoy=homicide_yoy,
                sentiment_diff=sentiment_diff,
                post_candidacy_flag=post_candidacy,
                observed_share=observed_share,
            )
        )
    return out


# ---------------------------------------------------------------------------
# Standardisation helpers (pure-logic, no PyMC)
# ---------------------------------------------------------------------------


def _compute_standardization(
    features: Sequence[FeatureVector],
) -> tuple[dict[str, float], dict[str, float]]:
    """Return per-feature ``(mean, sd)`` for z-scoring continuous features.

    Binary features get ``mean=0, sd=1`` so :meth:`standardize` is a
    no-op for them. Zero-variance continuous columns get ``sd=0`` and
    are dropped in the design matrix (the regression coefficient on a
    zero-variance column is unidentified).
    """
    means: dict[str, float] = {}
    sds: dict[str, float] = {}
    n = len(features)
    for name in FEATURE_NAMES:
        if name in BINARY_FEATURES:
            means[name] = 0.0
            sds[name] = 1.0
            continue
        values = [getattr(f, name) for f in features]
        mean = sum(values) / n
        var = sum((v - mean) ** 2 for v in values) / n
        means[name] = mean
        sds[name] = math.sqrt(var)
    return means, sds


def _design_matrix(
    features: Sequence[FeatureVector],
    means: dict[str, float],
    sds: dict[str, float],
) -> Any:
    """Build the ``(n, k)`` design matrix with standardisation applied."""
    import numpy as np  # noqa: PLC0415

    n = len(features)
    k = len(FEATURE_NAMES)
    matrix = np.zeros((n, k), dtype=float)
    for i, f in enumerate(features):
        raw = f.feature_array()
        for j, name in enumerate(FEATURE_NAMES):
            sd = sds[name]
            if sd <= 0.0:
                matrix[i, j] = 0.0
            else:
                matrix[i, j] = (raw[j] - means[name]) / sd
    return matrix


def _logit(share: float) -> float:
    """Numerically-safe logit for shares in the strict-open interval."""
    return math.log(share / (1.0 - share))


# ---------------------------------------------------------------------------
# PyMC fit
# ---------------------------------------------------------------------------


def fit(
    features: Sequence[FeatureVector],
    *,
    draws: int = 4000,
    tune: int = 2000,
    chains: int = 4,
    target_accept: float = 0.95,
    seed: int = 17,
    rhat_threshold: float = 1.01,
    ess_threshold: float = 400.0,
) -> FundamentalsCoefficients:
    """Fit the fundamentals regression and return posterior coefficients.

    Every ``FeatureVector`` must carry a non-``None`` ``observed_share``.
    Sampler config matches the Operational Commitments; the diagnostics
    gate is the ADR-013 C6 leg.
    """
    if not features:
        raise ValueError("no features to fit")
    targets: list[float] = []
    cycles_seen: set[int] = set()
    for f in features:
        if f.observed_share is None:
            raise ValueError(
                f"observed_share is None for cycle={f.cycle} candidate_id={f.candidate_id}"
            )
        targets.append(_logit(f.observed_share))
        cycles_seen.add(f.cycle)

    try:
        import arviz as az  # noqa: PLC0415
        import numpy as np  # noqa: PLC0415
        import pymc as pm  # noqa: PLC0415
    except ImportError as exc:  # pragma: no cover - exercised when extra missing
        raise RuntimeError(
            "PyMC not installed. Install with `uv sync --extra modelling`."
        ) from exc

    means, sds = _compute_standardization(features)
    design = _design_matrix(features, means, sds)
    y = np.asarray(targets, dtype=float)

    coords = {"feature": list(FEATURE_NAMES)}

    with pm.Model(coords=coords):
        # logit-share intercept ≈ -1.5 corresponds to ~18% share, close to
        # the historical mean across multi-candidate Guatemalan first rounds.
        intercept = pm.Normal("intercept", mu=-1.5, sigma=1.0)
        # Unit Normal prior on standardised coefficients; binary features
        # pass through unchanged but they share the same regularisation
        # scale because their {0,1} encoding lives on the same order of
        # magnitude as a one-sd z-score.
        beta = pm.Normal("beta", mu=0.0, sigma=1.0, dims="feature")
        sigma = pm.HalfNormal("sigma", sigma=0.5)
        mu = intercept + pm.math.dot(design, beta)
        pm.Normal("obs", mu=mu, sigma=sigma, observed=y)

        trace = pm.sample(
            draws=draws,
            tune=tune,
            chains=chains,
            target_accept=target_accept,
            random_seed=seed,
            progressbar=False,
            compute_convergence_checks=False,
        )

    summary = az.summary(trace, var_names=["intercept", "beta", "sigma"])
    max_rhat = float(summary["r_hat"].max())
    min_ess = float(summary["ess_bulk"].min())
    if not math.isfinite(max_rhat) or max_rhat >= rhat_threshold:
        raise SamplingDiagnosticsError(
            f"r_hat gate failed: max r_hat={max_rhat:.4f} >= {rhat_threshold}"
        )
    if not math.isfinite(min_ess) or min_ess <= ess_threshold:
        raise SamplingDiagnosticsError(
            f"bulk_ess gate failed: min bulk_ess={min_ess:.1f} <= {ess_threshold}"
        )

    intercept_samples = (
        trace.posterior["intercept"].stack(sample=("chain", "draw")).values
    )
    sigma_samples = (
        trace.posterior["sigma"].stack(sample=("chain", "draw")).values
    )
    # beta has shape (chain, draw, feature); stack to (sample, feature) then
    # split into a per-feature 1-D map for the public surface.
    beta_arr = (
        trace.posterior["beta"]
        .stack(sample=("chain", "draw"))
        .transpose("sample", "feature")
        .values
    )
    samples: dict[str, Any] = {
        name: beta_arr[:, j] for j, name in enumerate(FEATURE_NAMES)
    }

    return FundamentalsCoefficients(
        samples=samples,
        intercept_samples=intercept_samples,
        sigma_samples=sigma_samples,
        feature_names=tuple(FEATURE_NAMES),
        feature_means=means,
        feature_sds=sds,
        max_r_hat=max_rhat,
        min_bulk_ess=min_ess,
        n_observations=len(features),
        cycles_used=tuple(sorted(cycles_seen)),
    )


# ---------------------------------------------------------------------------
# Leave-one-cycle-out backtest
# ---------------------------------------------------------------------------


def backtest(
    features: Sequence[FeatureVector],
    *,
    holdout_cycle: int,
    predict_rng_seed: int = 19,
    **fit_kwargs: Any,
) -> BacktestCoverage:
    """Leave-one-cycle-out coverage check for the fundamentals model.

    Refits on every ``FeatureVector`` whose ``cycle`` differs from
    ``holdout_cycle`` and computes the posterior predictive share for
    each held-out candidate. Reports the empirical 80% and 95% CI
    coverage rate against the held-out actuals. The integration test
    drives this once per holdout cycle and asserts the issue #31
    threshold (≥80% at 80%, ≥95% at 95%) on the pooled holdout set.
    """
    import numpy as np  # noqa: PLC0415

    train = [f for f in features if f.cycle != holdout_cycle]
    test = [f for f in features if f.cycle == holdout_cycle]
    if not train:
        raise ValueError(f"no training rows after excluding cycle={holdout_cycle}")
    if not test:
        raise ValueError(f"no test rows for cycle={holdout_cycle}")

    coefs = fit(train, **fit_kwargs)
    covered_80: list[bool] = []
    covered_95: list[bool] = []
    for f in test:
        if f.observed_share is None:
            raise ValueError(
                f"test row missing observed_share: cycle={f.cycle} "
                f"candidate_id={f.candidate_id}"
            )
        samples = coefs.predict(f, include_noise=True, rng_seed=predict_rng_seed)
        lo80, hi80 = np.quantile(samples, [0.10, 0.90])
        lo95, hi95 = np.quantile(samples, [0.025, 0.975])
        covered_80.append(bool(lo80 <= f.observed_share <= hi80))
        covered_95.append(bool(lo95 <= f.observed_share <= hi95))

    return BacktestCoverage(
        holdout_cycle=holdout_cycle,
        n_candidates=len(test),
        coverage_80=float(np.mean(covered_80)),
        coverage_95=float(np.mean(covered_95)),
        max_r_hat=coefs.max_r_hat,
        min_bulk_ess=coefs.min_bulk_ess,
    )


__all__ = [
    "BINARY_FEATURES",
    "DEFAULT_APPROVAL_SHARE",
    "FEATURE_NAMES",
    "MACRO_INDICATOR_CODES",
    "BacktestCoverage",
    "FeatureVector",
    "FundamentalsCoefficients",
    "SamplingDiagnosticsError",
    "backtest",
    "fit",
    "read_approval_penalty",
    "read_election_key_dates",
    "read_party_of_government",
    "read_sentiment_differential",
    "read_training_features",
]
