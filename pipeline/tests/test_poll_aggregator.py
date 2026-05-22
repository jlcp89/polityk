"""Tests for ``pipeline.models.poll_aggregator`` (issue #30, ADR-017).

Three tiers:

1. Pure-logic tests (run unconditionally) cover the data validators,
   SE derivation, the lookup builder, and the DB read helpers (via a
   fake conn).
2. PyMC fit tests gated by ``pytest.importorskip("pymc")`` and marked
   ``slow``: a tiny synthetic dataset to assert (a) the diagnostics
   gate fires, (b) the fit is reproducible under a fixed seed, and
   (c) a known per-pollster bias is correctly absorbed into the
   observation likelihood so the latent share does NOT shift to chase
   it.
3. A 2019-shaped backtest (slow, importorskip) asserting that the
   final-day posterior's 80% CI covers the synthetic "actual" first-
   round share for ≥ 80% of candidates — the acceptance criterion in
   the issue body.

Postgres integration (gated by ``POLITYK_TEST_DATABASE_URL``) just
round-trips ``read_pollster_priors`` against the seeded pollsters
table.
"""

from __future__ import annotations

import os
import random
from datetime import date, timedelta
from typing import Any

import pytest

from pipeline.models import poll_aggregator as agg

# ---------------------------------------------------------------------------
# Pure-logic: SE derivation
# ---------------------------------------------------------------------------


def test_compute_poll_se_prefers_sample_size() -> None:
    se = agg.compute_poll_se(0.25, sample_size=1200, margin_of_error=0.05)
    # sqrt(0.25 * 0.75 / 1200) ≈ 0.01250
    assert se == pytest.approx(0.0125, abs=1e-4)


def test_compute_poll_se_uses_moe_when_no_sample_size() -> None:
    se = agg.compute_poll_se(0.25, sample_size=None, margin_of_error=0.0392)
    # MOE @ 95% → divide by 1.96
    assert se == pytest.approx(0.02, abs=2e-3)


def test_compute_poll_se_falls_back_to_default() -> None:
    se = agg.compute_poll_se(0.25, sample_size=None, margin_of_error=None)
    assert se == agg.DEFAULT_POLL_SE


def test_compute_poll_se_handles_extreme_shares() -> None:
    # Clipping prevents a divide-by-zero / NaN at share=0 or share=1.
    se_zero = agg.compute_poll_se(0.0, sample_size=1000)
    se_one = agg.compute_poll_se(1.0, sample_size=1000)
    assert se_zero > 0
    assert se_one > 0


# ---------------------------------------------------------------------------
# Pure-logic: PollObservation validation
# ---------------------------------------------------------------------------


def test_poll_observation_rejects_out_of_range_share() -> None:
    with pytest.raises(ValueError, match="share must be in"):
        agg.PollObservation(
            poll_id=1, pollster_id=1, candidate_id=1,
            field_end=date(2023, 5, 1), share=1.5, poll_se=0.03,
        )


def test_poll_observation_rejects_nonpositive_se() -> None:
    with pytest.raises(ValueError, match="poll_se must be > 0"):
        agg.PollObservation(
            poll_id=1, pollster_id=1, candidate_id=1,
            field_end=date(2023, 5, 1), share=0.25, poll_se=0.0,
        )


def test_pollster_prior_is_diffuse_flag() -> None:
    seeded = agg.PollsterPrior(
        pollster_id=1, name="CID Gallup",
        bias_mean=0.0, bias_sd=0.05, sample_count_used=0,
    )
    estimated = agg.PollsterPrior(
        pollster_id=2, name="ProDatos",
        bias_mean=-0.02, bias_sd=0.08, sample_count_used=25,
    )
    assert seeded.is_diffuse is True
    assert estimated.is_diffuse is False


# ---------------------------------------------------------------------------
# Pure-logic: _build_lookups validation + day grid
# ---------------------------------------------------------------------------


def _make_polls(
    field_ends: list[date], pollster_id: int = 1, candidate_id: int = 1
) -> list[agg.PollObservation]:
    return [
        agg.PollObservation(
            poll_id=i + 1,
            pollster_id=pollster_id,
            candidate_id=candidate_id,
            field_end=fe,
            share=0.25,
            poll_se=0.03,
        )
        for i, fe in enumerate(field_ends)
    ]


def test_build_lookups_dense_daily_grid() -> None:
    polls = _make_polls([date(2023, 5, 1), date(2023, 5, 5), date(2023, 5, 10)])
    pollsters = [agg.PollsterPrior(1, "X", 0.0, 0.05, 0)]
    candidates = [agg.CandidateRef(1, "Cand")]
    pollster_idx, candidate_idx, days = agg._build_lookups(polls, pollsters, candidates)
    assert pollster_idx == {1: 0}
    assert candidate_idx == {1: 0}
    # Dense daily grid from 2023-05-01 → 2023-05-10 inclusive.
    assert len(days) == 10
    assert days[0] == date(2023, 5, 1)
    assert days[-1] == date(2023, 5, 10)


def test_build_lookups_rejects_unknown_pollster() -> None:
    polls = _make_polls([date(2023, 5, 1)], pollster_id=99)
    pollsters = [agg.PollsterPrior(1, "X", 0.0, 0.05, 0)]
    candidates = [agg.CandidateRef(1, "Cand")]
    with pytest.raises(ValueError, match="unknown pollster_ids"):
        agg._build_lookups(polls, pollsters, candidates)


def test_build_lookups_rejects_unknown_candidate() -> None:
    polls = _make_polls([date(2023, 5, 1)], candidate_id=42)
    pollsters = [agg.PollsterPrior(1, "X", 0.0, 0.05, 0)]
    candidates = [agg.CandidateRef(1, "Cand")]
    with pytest.raises(ValueError, match="unknown candidate_ids"):
        agg._build_lookups(polls, pollsters, candidates)


# ---------------------------------------------------------------------------
# Pure-logic: fit() input validation
# ---------------------------------------------------------------------------


def test_fit_rejects_empty_polls() -> None:
    with pytest.raises(ValueError, match="no polls"):
        agg.fit(
            polls=[],
            pollsters=[agg.PollsterPrior(1, "X", 0.0, 0.05, 0)],
            candidates=[agg.CandidateRef(1, "Cand")],
        )


def test_fit_rejects_no_candidates() -> None:
    polls = _make_polls([date(2023, 5, 1)])
    with pytest.raises(ValueError, match="no candidates"):
        agg.fit(
            polls=polls,
            pollsters=[agg.PollsterPrior(1, "X", 0.0, 0.05, 0)],
            candidates=[],
        )


def test_fit_rejects_no_pollsters() -> None:
    polls = _make_polls([date(2023, 5, 1)])
    with pytest.raises(ValueError, match="no pollster priors"):
        agg.fit(
            polls=polls,
            pollsters=[],
            candidates=[agg.CandidateRef(1, "Cand")],
        )


# ---------------------------------------------------------------------------
# Pure-logic: read helpers via a fake conn
# ---------------------------------------------------------------------------


class _FakeCursor:
    def __init__(self, rows: list[tuple[Any, ...]]) -> None:
        self.executed: list[tuple[str, tuple[Any, ...]]] = []
        self._rows = rows

    def execute(self, sql: str, params: tuple[Any, ...] = ()) -> None:
        self.executed.append((sql, params))

    def fetchall(self) -> list[tuple[Any, ...]]:
        return self._rows

    def __enter__(self) -> _FakeCursor:
        return self

    def __exit__(self, *args: object) -> None:
        return None


class _FakeConn:
    def __init__(self, rows: list[tuple[Any, ...]]) -> None:
        self.cur = _FakeCursor(rows)

    def cursor(self) -> _FakeCursor:
        return self.cur


def test_read_pollster_priors_returns_typed_rows() -> None:
    conn = _FakeConn(
        rows=[
            (1, "CID Gallup", 0.0, 0.05, 0),
            (2, "ProDatos", -0.02, 0.08, 25),
        ]
    )
    out = agg.read_pollster_priors(conn)
    assert out == [
        agg.PollsterPrior(1, "CID Gallup", 0.0, 0.05, 0),
        agg.PollsterPrior(2, "ProDatos", -0.02, 0.08, 25),
    ]


def test_read_pollster_priors_orders_by_pollster_id() -> None:
    """The SELECT must ORDER BY pollster_id so callers can rely on the
    list-index matching the seeded order."""
    conn = _FakeConn(rows=[])
    agg.read_pollster_priors(conn)
    sql, _ = conn.cur.executed[0]
    assert "ORDER BY pollster_id" in sql


def test_read_polls_derives_se_from_sample_size() -> None:
    conn = _FakeConn(
        rows=[
            # poll_id, pollster_id, candidate_id, field_end, share,
            # sample_size, margin_of_error
            (1, 1, 1, date(2023, 5, 1), 0.25, 1200, None),
            (1, 1, 2, date(2023, 5, 1), 0.20, 1200, None),
        ]
    )
    out = agg.read_polls(conn, cycle=2023)
    assert len(out) == 2
    # SE derived from sample_size, not the fallback.
    assert out[0].poll_se != agg.DEFAULT_POLL_SE
    assert out[0].poll_se == pytest.approx(0.0125, abs=1e-4)


def test_read_polls_filters_by_candidate_ids() -> None:
    conn = _FakeConn(rows=[])
    agg.read_polls(conn, cycle=2023, candidate_ids=[1, 2])
    sql, params = conn.cur.executed[0]
    # candidate filter present + cycle param present
    assert "pr.candidate_id = ANY(%s)" in sql
    assert params == (2023, [1, 2])


def test_read_polls_orders_for_reproducibility() -> None:
    conn = _FakeConn(rows=[])
    agg.read_polls(conn, cycle=2023)
    sql, _ = conn.cur.executed[0]
    assert "ORDER BY p.field_end, p.poll_id, pr.candidate_id" in sql


# ---------------------------------------------------------------------------
# Pure-logic: AggregatorPosterior helpers (numpy required but trivially light)
# ---------------------------------------------------------------------------


def _hand_built_posterior() -> agg.AggregatorPosterior:
    """Hand-built (n_samples=200, n_days=3, n_candidates=2) draws.

    Candidate 0 distributed N(0.30, 0.02); candidate 1 N(0.20, 0.02).
    Lets us verify final_day_quantiles / final_day_ci_covers without
    spinning up PyMC.
    """
    pytest.importorskip("numpy")
    import numpy as np

    rng = np.random.default_rng(7)
    n_samples, n_days = 200, 3
    samples = np.zeros((n_samples, n_days, 2))
    samples[:, :, 0] = rng.normal(0.30, 0.02, (n_samples, n_days))
    samples[:, :, 1] = rng.normal(0.20, 0.02, (n_samples, n_days))
    days = (date(2023, 5, 1), date(2023, 5, 2), date(2023, 5, 3))
    candidates = (
        agg.CandidateRef(10, "A"),
        agg.CandidateRef(20, "B"),
    )
    return agg.AggregatorPosterior(
        samples=samples,
        days=days,
        candidates=candidates,
        max_r_hat=1.001,
        min_bulk_ess=900.0,
        n_observations=12,
    )


def test_final_day_quantiles_layout() -> None:
    post = _hand_built_posterior()
    qs = post.final_day_quantiles()
    assert set(qs.keys()) == {10, 20}
    # Median for candidate A ~ 0.30, candidate B ~ 0.20.
    assert qs[10][0.5] == pytest.approx(0.30, abs=0.01)
    assert qs[20][0.5] == pytest.approx(0.20, abs=0.01)
    # ADR-014 levels present.
    assert set(qs[10].keys()) == {0.05, 0.1, 0.25, 0.5, 0.75, 0.9, 0.95}


def test_final_day_ci_covers_actual() -> None:
    post = _hand_built_posterior()
    cover = post.final_day_ci_covers({10: 0.31, 20: 0.21}, level=0.80)
    # Both actuals well inside the 80% CI of a tight N(0.30, 0.02).
    assert cover == {10: True, 20: True}


def test_final_day_ci_covers_misses_far_actual() -> None:
    post = _hand_built_posterior()
    cover = post.final_day_ci_covers({10: 0.30, 20: 0.50}, level=0.80)
    assert cover[20] is False


def test_final_day_ci_covers_raises_on_missing_actual() -> None:
    post = _hand_built_posterior()
    with pytest.raises(KeyError, match="no actual"):
        post.final_day_ci_covers({10: 0.30}, level=0.80)


# ---------------------------------------------------------------------------
# PyMC fit — gated by `pytest.importorskip("pymc")`
# ---------------------------------------------------------------------------


def _synthetic_polls(
    *,
    true_shares: dict[int, float],
    pollster_biases: dict[int, float],
    n_polls_per_pollster: int = 8,
    sample_size: int = 1200,
    n_days_span: int = 60,
    seed: int = 42,
) -> tuple[list[agg.PollObservation], list[agg.PollsterPrior]]:
    """Build a polls + pollsters fixture for the aggregator fit.

    Each pollster publishes ``n_polls_per_pollster`` polls evenly across
    a ``n_days_span``-day window. Each poll reports every candidate.
    Observed share = true_share + pollster_bias + gaussian noise scaled
    by the binomial SE; this is exactly the data-generating process the
    aggregator assumes, so a correct fit should recover ``true_shares``
    on the latent layer (bias is absorbed; latent stays clean).
    """
    rng = random.Random(seed)
    polls: list[agg.PollObservation] = []
    pollsters: list[agg.PollsterPrior] = [
        agg.PollsterPrior(
            pollster_id=pid,
            name=f"P{pid}",
            bias_mean=bias,
            # Tight observation-noise sigma — keeps the latent recovery
            # informative without driving the obs likelihood SE so wide
            # that ANY latent share fits.
            bias_sd=0.005,
            sample_count_used=10,
        )
        for pid, bias in pollster_biases.items()
    ]
    poll_id = 0
    start = date(2023, 5, 1)
    for pid, bias in pollster_biases.items():
        for k in range(n_polls_per_pollster):
            offset = (k * (n_days_span - 1)) // max(n_polls_per_pollster - 1, 1)
            field_end = start + timedelta(days=offset)
            poll_id += 1
            for cand_id, true_share in true_shares.items():
                noise = rng.gauss(0.0, 0.008)
                observed = max(0.0, min(1.0, true_share + bias + noise))
                polls.append(
                    agg.PollObservation(
                        poll_id=poll_id,
                        pollster_id=pid,
                        candidate_id=cand_id,
                        field_end=field_end,
                        share=observed,
                        poll_se=agg.compute_poll_se(observed, sample_size=sample_size),
                    )
                )
    return polls, pollsters


@pytest.mark.slow
def test_fit_recovers_latent_share_when_pollster_is_biased() -> None:
    """Synthetic: a known-biased pollster's bias must NOT contaminate
    the latent share.

    Setup: two pollsters, one calibrated (bias=0), one biased +0.05.
    True shares (0.30, 0.20, 0.15). Aggregator should recover the
    LATENT shares — the biased pollster's offset is absorbed by the
    stored prior, not by the random walk.
    """
    pytest.importorskip("pymc")

    true_shares = {1: 0.30, 2: 0.20, 3: 0.15}
    pollster_biases = {1: 0.0, 2: 0.05}
    polls, pollsters = _synthetic_polls(
        true_shares=true_shares, pollster_biases=pollster_biases,
        n_polls_per_pollster=6,
    )
    candidates = [
        agg.CandidateRef(1, "Alpha"),
        agg.CandidateRef(2, "Beta"),
        agg.CandidateRef(3, "Gamma"),
    ]
    posterior = agg.fit(
        polls, pollsters, candidates,
        draws=800, tune=800, chains=2,
        seed=17,
        # Slightly loosened gates for the fast/CI variant; the
        # production CLI default still enforces 1.01 / 400.
        rhat_threshold=1.05,
        ess_threshold=100.0,
    )
    assert posterior.max_r_hat < 1.05
    # Final-day medians of the latent shares.
    qs = posterior.final_day_quantiles(levels=(0.5,))
    for cand_id, true_share in true_shares.items():
        assert abs(qs[cand_id][0.5] - true_share) < 0.025, (
            f"latent share for cand {cand_id} drifted: "
            f"median={qs[cand_id][0.5]:.4f}, true={true_share:.4f}"
        )


@pytest.mark.slow
def test_fit_is_reproducible_under_fixed_seed() -> None:
    """Acceptance: fixed seed → byte-identical posterior medians."""
    pytest.importorskip("pymc")

    true_shares = {1: 0.30, 2: 0.20}
    polls, pollsters = _synthetic_polls(
        true_shares=true_shares, pollster_biases={1: 0.0, 2: 0.02},
        n_polls_per_pollster=4, seed=99,
    )
    candidates = [agg.CandidateRef(1, "A"), agg.CandidateRef(2, "B")]
    a = agg.fit(
        polls, pollsters, candidates,
        draws=500, tune=500, chains=2, seed=17,
        rhat_threshold=1.10, ess_threshold=50.0,
    )
    b = agg.fit(
        polls, pollsters, candidates,
        draws=500, tune=500, chains=2, seed=17,
        rhat_threshold=1.10, ess_threshold=50.0,
    )
    qs_a = a.final_day_quantiles(levels=(0.5,))
    qs_b = b.final_day_quantiles(levels=(0.5,))
    for cand_id in true_shares:
        assert qs_a[cand_id][0.5] == pytest.approx(
            qs_b[cand_id][0.5], abs=1e-9
        )


@pytest.mark.slow
def test_fit_raises_on_rhat_failure() -> None:
    """Diagnostics gate: an unreachable rhat threshold must trip."""
    pytest.importorskip("pymc")

    polls, pollsters = _synthetic_polls(
        true_shares={1: 0.25}, pollster_biases={1: 0.0},
        n_polls_per_pollster=4,
    )
    candidates = [agg.CandidateRef(1, "A")]
    with pytest.raises(agg.SamplingDiagnosticsError):
        agg.fit(
            polls, pollsters, candidates,
            draws=200, tune=200, chains=2, seed=17,
            rhat_threshold=1.0000001,
            ess_threshold=10.0,
        )


@pytest.mark.slow
def test_fit_2019_backtest_covers_actuals_with_80pct_ci() -> None:
    """Acceptance criterion (issue body): 2019-shaped fit covers ≥ 80%
    of actuals at the 80% CI on the final day.

    Synthetic 2019: 4 candidates, ~3 pollsters with bias priors learned
    upstream by #29, ~12 polls per pollster across a 5-month window.
    Each poll reports all candidates; pollster bias and binomial noise
    applied as in the real data. The "actual" first-round share is the
    same vector the polls were drawn from — i.e. the test asks whether
    the aggregator's CI is *empirically* calibrated given the data the
    model assumes.
    """
    pytest.importorskip("pymc")

    # Approximate 2019 GT presidential first-round shape (rounded):
    # Torres 25.5, Giammattei 14.0, Mulet 11.3, Rios 6.1.
    actuals = {1: 0.255, 2: 0.140, 3: 0.113, 4: 0.061}
    # ADR-017 priors. Mix of calibrated and slightly biased pollsters.
    pollster_biases = {1: 0.0, 2: -0.015, 3: 0.01}
    polls, pollsters = _synthetic_polls(
        true_shares=actuals,
        pollster_biases=pollster_biases,
        n_polls_per_pollster=12,
        n_days_span=150,
        seed=2019,
    )
    candidates = [
        agg.CandidateRef(1, "Torres"),
        agg.CandidateRef(2, "Giammattei"),
        agg.CandidateRef(3, "Mulet"),
        agg.CandidateRef(4, "Rios"),
    ]
    posterior = agg.fit(
        polls, pollsters, candidates,
        draws=800, tune=800, chains=2, seed=17,
        rhat_threshold=1.05,
        ess_threshold=100.0,
    )
    cover = posterior.final_day_ci_covers(actuals, level=0.80)
    covered = sum(1 for ok in cover.values() if ok)
    rate = covered / len(actuals)
    assert rate >= 0.80, (
        f"80% CI coverage = {rate:.2f} < 0.80 for {cover}"
    )


# ---------------------------------------------------------------------------
# Postgres integration
# ---------------------------------------------------------------------------


_TEST_DSN = os.environ.get("POLITYK_TEST_DATABASE_URL")


@pytest.mark.skipif(_TEST_DSN is None, reason="POLITYK_TEST_DATABASE_URL not set")
def test_read_pollster_priors_round_trips_against_real_db() -> None:
    """Round-trips against the seeded `pollsters` row set from 0004_polls.sql."""
    import psycopg

    assert _TEST_DSN is not None
    with psycopg.connect(_TEST_DSN) as conn:
        priors = agg.read_pollster_priors(conn)
    # Migration 0004 seeds at least the four launch pollsters.
    assert len(priors) >= 4
    names = {p.name for p in priors}
    assert {"CID Gallup", "ProDatos"}.issubset(names)
    # Every prior has a finite bias_mean/bias_sd.
    for p in priors:
        assert isinstance(p.bias_mean, float)
        assert p.bias_sd > 0
