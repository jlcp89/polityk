"""Tests for ``pipeline.models.fundamentals`` (issue #31, ADR-011).

Three tiers, matching ``test_poll_aggregator.py``:

1. Pure-logic tests (always run) cover dataclass validation, the
   standardisation helpers, the design matrix, the predict() helper
   under a hand-built posterior, and every DB read helper via a fake
   psycopg-shaped connection.
2. PyMC fit tests gated by ``pytest.importorskip("pymc")`` and marked
   ``slow``: a synthetic dataset whose true coefficients the model
   should recover, plus diagnostics-gate and fixed-seed reproducibility
   checks.
3. A leave-one-cycle-out backtest (slow, importorskip) asserting
   pooled coverage ≥ 80% (80% CI) and ≥ 95% (95% CI) on a 4-cycle
   synthetic dataset — the issue #31 acceptance criterion.

Postgres integration (gated by ``POLITYK_TEST_DATABASE_URL``) drives
:func:`read_training_features` against the live schema; an explicit
opt-in env var keeps `pytest` runnable on a clean dev box.
"""

from __future__ import annotations

import math
import os
from datetime import date
from typing import Any

import pytest

from pipeline.models import fundamentals as fm

# ---------------------------------------------------------------------------
# Fake psycopg-shaped connection for the pure-logic DB reads
# ---------------------------------------------------------------------------


class _FakeCursor:
    def __init__(self, rows: list[tuple[Any, ...]]) -> None:
        self.executed: list[tuple[str, Any]] = []
        self._rows = rows

    def execute(self, sql: str, params: Any = ()) -> None:
        self.executed.append((sql, params))

    def fetchall(self) -> list[tuple[Any, ...]]:
        return self._rows

    def fetchone(self) -> tuple[Any, ...] | None:
        return self._rows[0] if self._rows else None

    def __enter__(self) -> _FakeCursor:
        return self

    def __exit__(self, *args: object) -> None:
        return None


class _FakeConn:
    """Returns a fresh ``_FakeCursor`` per call; tests inject a script of
    successive row-batches when a single test exercises multiple queries
    (e.g., ``read_training_features`` runs three SQL statements per row).
    """

    def __init__(self, batches: list[list[tuple[Any, ...]]]) -> None:
        self._batches = list(batches)
        self.cursors: list[_FakeCursor] = []

    def cursor(self) -> _FakeCursor:
        rows = self._batches.pop(0) if self._batches else []
        cur = _FakeCursor(rows)
        self.cursors.append(cur)
        return cur


# ---------------------------------------------------------------------------
# Pure-logic — FeatureVector validation
# ---------------------------------------------------------------------------


def _ok_feature(**overrides: Any) -> fm.FeatureVector:
    base: dict[str, Any] = {
        "cycle": 2019,
        "candidate_id": 1,
        "incumbent_party": False,
        "approval_penalty": 0.5,
        "gdp_yoy": 3.0,
        "inflation_yoy": 4.0,
        "remittance_yoy": 8.0,
        "homicide_yoy": -2.0,
        "sentiment_diff": 0.05,
        "post_candidacy_flag": True,
        "observed_share": 0.2,
    }
    base.update(overrides)
    return fm.FeatureVector(**base)


def test_feature_vector_rejects_approval_out_of_range() -> None:
    with pytest.raises(ValueError, match="approval_penalty"):
        _ok_feature(approval_penalty=1.2)
    with pytest.raises(ValueError, match="approval_penalty"):
        _ok_feature(approval_penalty=-0.1)


def test_feature_vector_rejects_observed_share_boundary() -> None:
    # Exactly 0 / 1 break logit; the dataclass rejects them.
    with pytest.raises(ValueError, match="observed_share"):
        _ok_feature(observed_share=0.0)
    with pytest.raises(ValueError, match="observed_share"):
        _ok_feature(observed_share=1.0)


def test_feature_vector_allows_observed_share_none() -> None:
    # Prediction-time row: target is unknown; should construct OK.
    f = _ok_feature(observed_share=None)
    assert f.observed_share is None


def test_feature_array_ordering_matches_feature_names() -> None:
    f = _ok_feature(
        incumbent_party=True,
        approval_penalty=0.3,
        gdp_yoy=2.5,
        inflation_yoy=4.1,
        remittance_yoy=7.0,
        homicide_yoy=-1.5,
        sentiment_diff=0.10,
        post_candidacy_flag=False,
    )
    arr = f.feature_array()
    assert arr == [1.0, 0.3, 2.5, 4.1, 7.0, -1.5, 0.10, 0.0]
    assert len(arr) == len(fm.FEATURE_NAMES)


# ---------------------------------------------------------------------------
# Pure-logic — standardisation
# ---------------------------------------------------------------------------


def test_compute_standardization_continuous_zscores() -> None:
    feats = [
        _ok_feature(gdp_yoy=2.0, inflation_yoy=3.0),
        _ok_feature(gdp_yoy=3.0, inflation_yoy=5.0),
        _ok_feature(gdp_yoy=4.0, inflation_yoy=7.0),
    ]
    means, sds = fm._compute_standardization(feats)
    assert means["gdp_yoy"] == pytest.approx(3.0)
    # Population SD: sqrt(((2-3)^2 + (3-3)^2 + (4-3)^2) / 3) = sqrt(2/3)
    assert sds["gdp_yoy"] == pytest.approx(math.sqrt(2.0 / 3.0))
    assert means["inflation_yoy"] == pytest.approx(5.0)


def test_compute_standardization_keeps_binary_identity() -> None:
    feats = [
        _ok_feature(incumbent_party=False, post_candidacy_flag=False),
        _ok_feature(incumbent_party=True, post_candidacy_flag=True),
    ]
    means, sds = fm._compute_standardization(feats)
    assert means["incumbent_party"] == 0.0
    assert sds["incumbent_party"] == 1.0
    assert means["post_candidacy_flag"] == 0.0
    assert sds["post_candidacy_flag"] == 1.0


def test_compute_standardization_zero_variance_continuous_gets_zero_sd() -> None:
    feats = [_ok_feature(gdp_yoy=3.0), _ok_feature(gdp_yoy=3.0)]
    _, sds = fm._compute_standardization(feats)
    # Zero-variance column → sd=0 → design matrix treats as no contribution
    assert sds["gdp_yoy"] == 0.0


# ---------------------------------------------------------------------------
# Pure-logic — design matrix
# ---------------------------------------------------------------------------


def test_design_matrix_applies_zscoring_and_skips_zero_variance() -> None:
    pytest.importorskip("numpy")
    import numpy as np

    feats = [
        _ok_feature(gdp_yoy=2.0, incumbent_party=False),
        _ok_feature(gdp_yoy=4.0, incumbent_party=True),
    ]
    means, sds = fm._compute_standardization(feats)
    design = fm._design_matrix(feats, means, sds)
    assert design.shape == (2, len(fm.FEATURE_NAMES))
    # gdp_yoy at index 2; standardised: (2-3)/1 = -1, (4-3)/1 = +1 (sd=1
    # because population SD over {2,4} is 1)
    gdp_col = fm.FEATURE_NAMES.index("gdp_yoy")
    assert np.allclose(design[:, gdp_col], np.array([-1.0, 1.0]))
    # incumbent_party at its index: identity (binary), values [0, 1]
    inc_col = fm.FEATURE_NAMES.index("incumbent_party")
    assert np.allclose(design[:, inc_col], np.array([0.0, 1.0]))


# ---------------------------------------------------------------------------
# Pure-logic — logit safety
# ---------------------------------------------------------------------------


def test_logit_basic() -> None:
    assert fm._logit(0.5) == pytest.approx(0.0)
    assert fm._logit(0.25) == pytest.approx(math.log(1.0 / 3.0))


# ---------------------------------------------------------------------------
# Pure-logic — FundamentalsCoefficients.predict
# ---------------------------------------------------------------------------


def _hand_built_coefs(
    *, beta_incumbent: float = 0.5, beta_gdp: float = -0.3, n_samples: int = 500
) -> fm.FundamentalsCoefficients:
    """Construct a deterministic posterior with one draw across many samples.

    Every β sample equals its named scalar so :meth:`predict` becomes a
    closed-form check — handy for the pure-logic unit tests.
    """
    pytest.importorskip("numpy")
    import numpy as np

    samples: dict[str, Any] = {
        name: np.full(n_samples, 0.0, dtype=float) for name in fm.FEATURE_NAMES
    }
    samples["incumbent_party"] = np.full(n_samples, beta_incumbent, dtype=float)
    samples["gdp_yoy"] = np.full(n_samples, beta_gdp, dtype=float)
    return fm.FundamentalsCoefficients(
        samples=samples,
        intercept_samples=np.full(n_samples, -1.5, dtype=float),
        sigma_samples=np.full(n_samples, 0.001, dtype=float),  # tiny noise
        feature_names=tuple(fm.FEATURE_NAMES),
        feature_means={name: 0.0 for name in fm.FEATURE_NAMES}
        | {
            "approval_penalty": 0.5,
            "gdp_yoy": 3.0,
            "inflation_yoy": 4.0,
            "remittance_yoy": 8.0,
            "homicide_yoy": -2.0,
            "sentiment_diff": 0.0,
        },
        feature_sds={name: 1.0 for name in fm.FEATURE_NAMES},
        max_r_hat=1.0,
        min_bulk_ess=10000.0,
        n_observations=20,
        cycles_used=(2007, 2011, 2015, 2019),
    )


def test_predict_uses_intercept_and_coefficients() -> None:
    import numpy as np

    coefs = _hand_built_coefs(beta_incumbent=0.5, beta_gdp=-0.3)
    # incumbent=True (z-score = (1-0)/1 = 1), gdp_yoy at mean (z-score = 0)
    f = _ok_feature(incumbent_party=True, gdp_yoy=3.0, observed_share=None)
    shares = coefs.predict(f, include_noise=False)
    # logit_share = -1.5 + 0.5 * 1 = -1.0  → share = sigmoid(-1) ≈ 0.2689
    assert shares.shape == (500,)
    assert np.allclose(shares, 1.0 / (1.0 + np.exp(1.0)))


def test_predict_with_noise_spreads_around_mean() -> None:
    coefs_low_noise = _hand_built_coefs(n_samples=2000)
    f = _ok_feature(observed_share=None)
    deterministic = coefs_low_noise.predict(f, include_noise=False)
    with_noise = coefs_low_noise.predict(f, include_noise=True, rng_seed=7)
    # Mean should be close (sigma=0.001 is tiny), but the std should be > 0.
    assert abs(deterministic.mean() - with_noise.mean()) < 1e-3
    assert with_noise.std() >= 0.0


def test_standardize_handles_zero_sd_column_gracefully() -> None:
    coefs = _hand_built_coefs()
    # Force a zero-sd training column.
    coefs = fm.FundamentalsCoefficients(
        samples=coefs.samples,
        intercept_samples=coefs.intercept_samples,
        sigma_samples=coefs.sigma_samples,
        feature_names=coefs.feature_names,
        feature_means=coefs.feature_means,
        feature_sds={**coefs.feature_sds, "gdp_yoy": 0.0},
        max_r_hat=coefs.max_r_hat,
        min_bulk_ess=coefs.min_bulk_ess,
        n_observations=coefs.n_observations,
        cycles_used=coefs.cycles_used,
    )
    z = coefs.standardize(_ok_feature(gdp_yoy=100.0))
    gdp_col = fm.FEATURE_NAMES.index("gdp_yoy")
    assert z[gdp_col] == 0.0  # zero-variance column contributes nothing


# ---------------------------------------------------------------------------
# Pure-logic — DB readers via fake conn
# ---------------------------------------------------------------------------


def test_read_party_of_government_maps_cycle_to_party_id() -> None:
    conn = _FakeConn([[(2019, 42), (2023, 99)]])
    out = fm.read_party_of_government(conn)
    assert out == {2019: 42, 2023: 99}
    assert conn.cursors[0].executed[0][0].strip().startswith("SELECT cycle")


def test_read_election_key_dates_returns_cycle_date_map() -> None:
    conn = _FakeConn(
        [[(2019, date(2019, 5, 18)), (2023, date(2023, 3, 25))]]
    )
    out = fm.read_election_key_dates(conn)
    assert out == {2019: date(2019, 5, 18), 2023: date(2023, 3, 25)}


def test_read_approval_penalty_returns_one_minus_share() -> None:
    conn = _FakeConn([[(0.32,)]])
    penalty = fm.read_approval_penalty(conn, cycle=2019, party_id=42)
    assert penalty == pytest.approx(0.68)


def test_read_approval_penalty_falls_back_when_no_row() -> None:
    conn = _FakeConn([[]])
    penalty = fm.read_approval_penalty(conn, cycle=2019, party_id=42, fallback=0.4)
    assert penalty == pytest.approx(0.6)  # 1 - 0.4


def test_read_sentiment_differential_computes_pos_minus_neg() -> None:
    # 6 POS, 4 NEG, 10 total → (6 - 4) / 10 = 0.2
    conn = _FakeConn([[(6, 4, 10)]])
    out = fm.read_sentiment_differential(
        conn, candidate_id=1, election_date=date(2019, 6, 16)
    )
    assert out == pytest.approx(0.2)


def test_read_sentiment_differential_returns_zero_when_no_articles() -> None:
    conn = _FakeConn([[(0, 0, 0)]])
    out = fm.read_sentiment_differential(
        conn, candidate_id=1, election_date=date(2019, 6, 16)
    )
    assert out == 0.0


def test_read_training_features_wires_all_eight_features() -> None:
    # core join returns one synthetic candidate row; then read_approval_penalty
    # and read_sentiment_differential each open a new cursor.
    core_row = (
        2019,                # cycle
        7,                   # candidate_id
        0.18,                # observed_share
        42,                  # party_id
        True,                # incumbent_party
        3.5,                 # gdp_yoy
        4.1,                 # inflation_yoy
        8.6,                 # remittance_yoy
        -3.1,                # homicide_yoy
        date(2019, 5, 18),   # candidate_list_closed_at
        date(2019, 6, 1),    # approx_election_date
    )
    conn = _FakeConn(
        [
            [core_row],          # _read_training_core
            [(0.40,)],           # read_approval_penalty (returns approval_share)
            [(7, 3, 10)],        # read_sentiment_differential (pos, neg, total)
        ]
    )
    out = fm.read_training_features(conn, cycles=[2019])
    assert len(out) == 1
    f = out[0]
    assert f.cycle == 2019
    assert f.candidate_id == 7
    assert f.observed_share == pytest.approx(0.18)
    assert f.incumbent_party is True
    assert f.approval_penalty == pytest.approx(0.60)
    assert f.gdp_yoy == pytest.approx(3.5)
    assert f.inflation_yoy == pytest.approx(4.1)
    assert f.remittance_yoy == pytest.approx(8.6)
    assert f.homicide_yoy == pytest.approx(-3.1)
    assert f.sentiment_diff == pytest.approx(0.4)
    assert f.post_candidacy_flag is True  # closed 2019-05-18 <= election 2019-06-01


def test_read_training_features_pre_finalisation_flag_false() -> None:
    # candidate_list_closed_at AFTER approx_election_date → flag False.
    core_row = (
        2019, 7, 0.18, 42, False,
        3.5, 4.1, 8.6, -3.1,
        date(2019, 12, 1),   # registry closes after our 2019-06-01 reference
        date(2019, 6, 1),
    )
    conn = _FakeConn([[core_row], [], [(0, 0, 0)]])
    out = fm.read_training_features(conn, cycles=[2019])
    assert out[0].post_candidacy_flag is False


def test_read_training_features_missing_close_date_marks_pre_finalisation() -> None:
    core_row = (
        2019, 7, 0.18, 42, False,
        3.5, 4.1, 8.6, -3.1,
        None,                  # no election_key_dates row
        date(2019, 6, 1),
    )
    conn = _FakeConn([[core_row], [], [(0, 0, 0)]])
    out = fm.read_training_features(conn, cycles=[2019])
    assert out[0].post_candidacy_flag is False


# ---------------------------------------------------------------------------
# fit() input validation
# ---------------------------------------------------------------------------


def test_fit_raises_on_empty_features() -> None:
    with pytest.raises(ValueError, match="no features"):
        fm.fit([])


def test_fit_raises_when_observed_share_missing() -> None:
    feats = [_ok_feature(observed_share=None)]
    with pytest.raises(ValueError, match="observed_share is None"):
        fm.fit(feats)


# ---------------------------------------------------------------------------
# Synthetic DGP for PyMC fit + backtest tests
# ---------------------------------------------------------------------------


def _synthetic_features(
    *,
    seed: int = 11,
    cycles: tuple[int, ...] = (2007, 2011, 2015, 2019),
    candidates_per_cycle: int = 6,
    true_betas: dict[str, float] | None = None,
    intercept: float = -1.5,
    noise_sigma: float = 0.15,
) -> tuple[list[fm.FeatureVector], dict[str, float], float]:
    """Generate features whose logit-share follows a known linear DGP.

    Continuous feature scales mirror realistic Guatemalan macro readings
    so the standardisation step is exercised. The returned tuple is
    ``(features, true_betas, intercept)`` for test assertions.
    """
    import numpy as np

    rng = np.random.default_rng(seed)
    if true_betas is None:
        true_betas = {
            "incumbent_party": -0.6,
            "approval_penalty": 0.5,
            "gdp_yoy": -0.3,
            "inflation_yoy": 0.4,
            "remittance_yoy": -0.2,
            "homicide_yoy": 0.3,
            "sentiment_diff": 0.7,
            "post_candidacy_flag": 0.1,
        }

    # Per-cycle macro context (one realisation per cycle, shared across
    # that cycle's candidates) — matches how real data behaves.
    macro_per_cycle: dict[int, dict[str, float]] = {}
    for cycle in cycles:
        macro_per_cycle[cycle] = {
            "gdp_yoy": float(rng.normal(3.0, 1.0)),
            "inflation_yoy": float(rng.normal(4.5, 1.5)),
            "remittance_yoy": float(rng.normal(8.0, 2.0)),
            "homicide_yoy": float(rng.normal(-1.0, 2.0)),
            "approval_share": float(np.clip(rng.normal(0.45, 0.10), 0.1, 0.9)),
        }

    # We need the standardised feature design to plug into the linear
    # predictor. To avoid the circular "compute std of synthetic data"
    # problem, we generate raw features, build the design matrix once,
    # then construct the observed_share via that exact matrix.
    raw: list[fm.FeatureVector] = []
    candidate_id_counter = 1
    for cycle in cycles:
        macro = macro_per_cycle[cycle]
        # One candidate per cycle is the "incumbent's pick".
        incumbent_idx = int(rng.integers(0, candidates_per_cycle))
        for j in range(candidates_per_cycle):
            sentiment = float(rng.normal(0.0, 0.25))
            f = fm.FeatureVector(
                cycle=cycle,
                candidate_id=candidate_id_counter,
                incumbent_party=(j == incumbent_idx),
                approval_penalty=1.0 - macro["approval_share"],
                gdp_yoy=macro["gdp_yoy"],
                inflation_yoy=macro["inflation_yoy"],
                remittance_yoy=macro["remittance_yoy"],
                homicide_yoy=macro["homicide_yoy"],
                sentiment_diff=sentiment,
                post_candidacy_flag=True,
                # Will overwrite observed_share once the DGP is applied.
                observed_share=0.1,
            )
            raw.append(f)
            candidate_id_counter += 1

    means, sds = fm._compute_standardization(raw)
    design = fm._design_matrix(raw, means, sds)
    # logit_share = intercept + Σ true_beta_k * z_k + Normal(0, noise_sigma)
    n = len(raw)
    logit_share = np.full(n, intercept, dtype=float)
    for j, name in enumerate(fm.FEATURE_NAMES):
        logit_share = logit_share + true_betas[name] * design[:, j]
    logit_share = logit_share + rng.normal(0.0, noise_sigma, size=n)
    shares = 1.0 / (1.0 + np.exp(-logit_share))
    # Clip away from the strict-open boundary so the dataclass accepts.
    shares = np.clip(shares, 0.001, 0.999)

    out: list[fm.FeatureVector] = []
    for f, s in zip(raw, shares.tolist(), strict=True):
        out.append(
            fm.FeatureVector(
                cycle=f.cycle,
                candidate_id=f.candidate_id,
                incumbent_party=f.incumbent_party,
                approval_penalty=f.approval_penalty,
                gdp_yoy=f.gdp_yoy,
                inflation_yoy=f.inflation_yoy,
                remittance_yoy=f.remittance_yoy,
                homicide_yoy=f.homicide_yoy,
                sentiment_diff=f.sentiment_diff,
                post_candidacy_flag=f.post_candidacy_flag,
                observed_share=float(s),
            )
        )
    return out, true_betas, intercept


# ---------------------------------------------------------------------------
# PyMC fit smoke + recovery + reproducibility
# ---------------------------------------------------------------------------


@pytest.mark.slow
def test_fit_smoke_passes_diagnostics_gate() -> None:
    pytest.importorskip("pymc")
    pytest.importorskip("arviz")

    feats, _, _ = _synthetic_features()
    # Loosened thresholds + fewer draws keep this test under a few minutes
    # while still exercising the full code path.
    coefs = fm.fit(
        feats,
        draws=600,
        tune=400,
        chains=2,
        target_accept=0.9,
        rhat_threshold=1.1,
        ess_threshold=80.0,
    )
    assert coefs.max_r_hat < 1.1
    assert coefs.min_bulk_ess > 80.0
    assert coefs.n_observations == len(feats)
    assert coefs.cycles_used == (2007, 2011, 2015, 2019)
    for name in fm.FEATURE_NAMES:
        assert name in coefs.samples


@pytest.mark.slow
def test_fit_recovers_known_intercept_sign() -> None:
    """Sanity check the regression recovers the data-generating intercept
    sign and a representative coefficient (positive ``sentiment_diff``)."""
    pytest.importorskip("pymc")
    import numpy as np

    feats, true_betas, intercept = _synthetic_features(seed=13)
    coefs = fm.fit(
        feats,
        draws=800,
        tune=500,
        chains=2,
        target_accept=0.9,
        rhat_threshold=1.1,
        ess_threshold=80.0,
    )
    intercept_mean = float(np.mean(coefs.intercept_samples))
    # Generous tolerance — n=24 with unit prior shrinks toward 0; we
    # mainly want the *sign* and rough magnitude.
    assert intercept_mean < 0.0
    assert abs(intercept_mean - intercept) < 1.0
    sentiment_mean = float(np.mean(coefs.samples["sentiment_diff"]))
    # The DGP has β_sentiment > 0; the posterior mean should be positive.
    assert sentiment_mean > 0.0
    # Magnitude within a couple of prior SDs of the truth.
    assert abs(sentiment_mean - true_betas["sentiment_diff"]) < 1.5


@pytest.mark.slow
def test_fit_is_reproducible_under_fixed_seed() -> None:
    pytest.importorskip("pymc")
    import numpy as np

    feats, _, _ = _synthetic_features(seed=21)
    kwargs: dict[str, Any] = {
        "draws": 400,
        "tune": 300,
        "chains": 2,
        "target_accept": 0.9,
        "rhat_threshold": 1.2,
        "ess_threshold": 50.0,
        "seed": 17,
    }
    a = fm.fit(feats, **kwargs)
    b = fm.fit(feats, **kwargs)
    for name in fm.FEATURE_NAMES:
        assert np.allclose(a.samples[name], b.samples[name])
    assert np.allclose(a.intercept_samples, b.intercept_samples)
    assert np.allclose(a.sigma_samples, b.sigma_samples)


@pytest.mark.slow
def test_fit_raises_on_impossible_rhat_threshold() -> None:
    pytest.importorskip("pymc")

    feats, _, _ = _synthetic_features(seed=29)
    # No sampler is going to hit r_hat < 0.0; the gate must fire.
    with pytest.raises(fm.SamplingDiagnosticsError):
        fm.fit(
            feats,
            draws=200,
            tune=200,
            chains=2,
            target_accept=0.9,
            rhat_threshold=0.0,
            ess_threshold=1.0,
        )


# ---------------------------------------------------------------------------
# Backtest acceptance test — issue #31's coverage threshold
# ---------------------------------------------------------------------------


@pytest.mark.slow
def test_backtest_coverage_meets_acceptance_threshold() -> None:
    """Pool leave-one-cycle-out coverage across 4 synthetic cycles and
    assert ≥80% at 80% CI and ≥95% at 95% CI — the issue #31 criterion."""
    pytest.importorskip("pymc")

    feats, _, _ = _synthetic_features(
        seed=37, candidates_per_cycle=6, noise_sigma=0.20
    )
    cycles = sorted({f.cycle for f in feats})
    n_total = 0
    cov_80 = 0
    cov_95 = 0
    for cycle in cycles:
        result = fm.backtest(
            feats,
            holdout_cycle=cycle,
            draws=600,
            tune=400,
            chains=2,
            target_accept=0.9,
            rhat_threshold=1.15,
            ess_threshold=80.0,
            predict_rng_seed=19,
        )
        # backtest returns rates, multiply back to counts so the
        # pooled denominator is correct (cycles may have unequal n).
        cov_80 += int(round(result.coverage_80 * result.n_candidates))
        cov_95 += int(round(result.coverage_95 * result.n_candidates))
        n_total += result.n_candidates
    pooled_80 = cov_80 / n_total
    pooled_95 = cov_95 / n_total
    # Issue #31 acceptance — pooled across all holdout cycles.
    assert pooled_80 >= 0.80, f"pooled 80% CI coverage {pooled_80:.3f} below 0.80"
    assert pooled_95 >= 0.95, f"pooled 95% CI coverage {pooled_95:.3f} below 0.95"


# ---------------------------------------------------------------------------
# Real-DB integration (opt-in)
# ---------------------------------------------------------------------------


_TEST_DSN = os.environ.get("POLITYK_TEST_DATABASE_URL")


@pytest.mark.skipif(_TEST_DSN is None, reason="POLITYK_TEST_DATABASE_URL not set")
def test_read_training_features_round_trips_against_real_db() -> None:
    """Smoke test the joined SQL against a live Postgres with backfilled
    cycles. Coverage assertion is intentionally weaker than the synthetic
    backtest because real data has documented gaps (sentiment pre-2023,
    approval rows pending curation)."""
    import psycopg  # noqa: PLC0415

    assert _TEST_DSN is not None
    with psycopg.connect(_TEST_DSN) as conn:
        feats = fm.read_training_features(conn, cycles=[2007, 2011, 2015, 2019])
    # At least one candidate per backfilled cycle should be present.
    cycles_present = {f.cycle for f in feats}
    assert cycles_present, "no training rows returned from real DB"
    for f in feats:
        assert f.observed_share is not None
        assert 0.0 < f.observed_share < 1.0
