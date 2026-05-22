"""Tests for ``pipeline.models.presidential`` (issue #32, ADR-013, ADR-014).

Three tiers, matching the sibling model test files:

1. Pure-logic tests (always run) cover the dataclass validators, the
   helpers (logit/softmax/bootstrap), the combination function under a
   hand-built aggregator + fundamentals fixture, and the runoff-matrix
   builder under hand-rolled top-two arrays.
2. PyMC fit tests gated by ``pytest.importorskip("pymc")`` and marked
   ``slow``: synthetic runoff history → :func:`fit_runoff_swing`
   posteriors recover the historical direction; the diagnostics gate
   fires when thresholds are unreachable; the end-to-end
   :func:`fit_and_predict` enforces the ADR-013 C5 invariant
   (``pair_probability`` sums to 1.0 ± 1e-6) and the ADR-014 contract.
3. A 2019-shaped backtest (slow) asserting top-3 median absolute error
   ≤ 5pp and 80% / 95% CI coverage ≥ 80% / 95% on a synthetic 2019 — the
   ADR-013 C1/C2/C3 thresholds the calibration gate uses against real
   holdouts.
"""

from __future__ import annotations

import dataclasses
from datetime import date
from typing import Any

import pytest

from pipeline.models import fundamentals as fm
from pipeline.models import poll_aggregator as agg
from pipeline.models import presidential as pres

# ---------------------------------------------------------------------------
# Hand-built fixtures (no PyMC required)
# ---------------------------------------------------------------------------


def _hand_built_aggregator(
    *,
    candidate_means: list[tuple[int, str, float]],
    n_samples: int = 600,
    n_days: int = 3,
    sigma: float = 0.015,
    seed: int = 7,
) -> agg.AggregatorPosterior:
    """Hand-rolled aggregator posterior with tight Normal columns per cand."""
    pytest.importorskip("numpy")
    import numpy as np

    rng = np.random.default_rng(seed)
    n_cands = len(candidate_means)
    samples = np.zeros((n_samples, n_days, n_cands), dtype=float)
    for j, (_, _, mean) in enumerate(candidate_means):
        samples[:, :, j] = rng.normal(mean, sigma, (n_samples, n_days))
    days = tuple(
        date.fromordinal(date(2027, 6, 1).toordinal() + k - n_days + 1)
        for k in range(n_days)
    )
    candidates = tuple(
        agg.CandidateRef(cid, name) for cid, name, _ in candidate_means
    )
    return agg.AggregatorPosterior(
        samples=samples,
        days=days,
        candidates=candidates,
        max_r_hat=1.001,
        min_bulk_ess=2000.0,
        n_observations=24,
    )


def _hand_built_fundamentals(
    *,
    intercept: float = -1.5,
    beta_incumbent: float = -0.4,
    sigma: float = 0.05,
    n_samples: int = 600,
) -> fm.FundamentalsCoefficients:
    """Hand-rolled fundamentals coefficients; non-incumbent features = 0 beta.

    Means/sds are set so the un-standardised feature_array() values pass
    through cleanly: continuous means at sensible Guatemalan macro readings,
    sds at 1 so the z-score is the raw value minus its mean.
    """
    pytest.importorskip("numpy")
    import numpy as np

    samples: dict[str, Any] = {
        name: np.zeros(n_samples, dtype=float) for name in fm.FEATURE_NAMES
    }
    samples["incumbent_party"] = np.full(n_samples, beta_incumbent, dtype=float)
    return fm.FundamentalsCoefficients(
        samples=samples,
        intercept_samples=np.full(n_samples, intercept, dtype=float),
        sigma_samples=np.full(n_samples, sigma, dtype=float),
        feature_names=tuple(fm.FEATURE_NAMES),
        feature_means={
            "incumbent_party": 0.0,
            "approval_penalty": 0.5,
            "gdp_yoy": 3.0,
            "inflation_yoy": 4.0,
            "remittance_yoy": 8.0,
            "homicide_yoy": -2.0,
            "sentiment_diff": 0.0,
            "post_candidacy_flag": 0.0,
        },
        feature_sds={name: 1.0 for name in fm.FEATURE_NAMES},
        max_r_hat=1.001,
        min_bulk_ess=2000.0,
        n_observations=24,
        cycles_used=(2007, 2011, 2015, 2019),
    )


def _hand_built_swing(
    *,
    intercept: float = 0.0,
    beta_share: float = 4.0,
    beta_inc: float = -0.6,
    n_samples: int = 400,
) -> pres.RunoffSwingModel:
    """Deterministic single-draw swing model for pure-logic tests."""
    pytest.importorskip("numpy")
    import numpy as np

    return pres.RunoffSwingModel(
        intercept_samples=np.full(n_samples, intercept, dtype=float),
        beta_share_diff_samples=np.full(n_samples, beta_share, dtype=float),
        beta_incumbent_diff_samples=np.full(n_samples, beta_inc, dtype=float),
        n_observations=5,
        max_r_hat=1.001,
        min_bulk_ess=900.0,
    )


def _ok_feature(**overrides: Any) -> fm.FeatureVector:
    base: dict[str, Any] = {
        "cycle": 2027,
        "candidate_id": 1,
        "incumbent_party": False,
        "approval_penalty": 0.5,
        "gdp_yoy": 3.0,
        "inflation_yoy": 4.0,
        "remittance_yoy": 8.0,
        "homicide_yoy": -2.0,
        "sentiment_diff": 0.0,
        "post_candidacy_flag": True,
        "observed_share": None,
    }
    base.update(overrides)
    return fm.FeatureVector(**base)


# ---------------------------------------------------------------------------
# Pure-logic — RunoffHistoryRow validation
# ---------------------------------------------------------------------------


def test_runoff_history_row_rejects_out_of_range_share() -> None:
    with pytest.raises(ValueError, match="a_round1_share"):
        pres.RunoffHistoryRow(
            cycle=2019,
            a_candidate_id=1,
            b_candidate_id=2,
            a_round1_share=1.2,
            b_round1_share=0.1,
            a_incumbent_party=False,
            b_incumbent_party=False,
            a_won_runoff=True,
        )


def test_runoff_history_row_rejects_zero_share() -> None:
    with pytest.raises(ValueError, match="b_round1_share"):
        pres.RunoffHistoryRow(
            cycle=2019,
            a_candidate_id=1,
            b_candidate_id=2,
            a_round1_share=0.25,
            b_round1_share=0.0,
            a_incumbent_party=False,
            b_incumbent_party=False,
            a_won_runoff=True,
        )


# ---------------------------------------------------------------------------
# Pure-logic — helpers
# ---------------------------------------------------------------------------


def test_logit_arr_handles_extreme_shares() -> None:
    import numpy as np

    out = pres._logit_arr(np.array([0.0, 1.0, 0.5]))
    # Clipped inputs produce finite logits.
    assert np.isfinite(out).all()
    assert out[2] == pytest.approx(0.0)


def test_sigmoid_returns_unit_interval_marginals() -> None:
    import numpy as np

    arr = np.array([[1.0, 2.0, 3.0], [-1.0, 0.0, 1.0]])
    out = pres._sigmoid(arr)
    assert (out > 0.0).all()
    assert (out < 1.0).all()
    # sigmoid(0) = 0.5 exactly.
    assert out[1, 1] == pytest.approx(0.5)
    # Larger input → larger sigmoid (monotonic per row).
    assert out[0, 2] > out[0, 1] > out[0, 0]


def test_sigmoid_is_numerically_stable_on_extreme_inputs() -> None:
    import numpy as np

    # Without the positive/negative branch split a naive 1/(1+exp(-x))
    # implementation overflows to NaN at x = -1e3. Our impl returns 0/1
    # cleanly on the extremes.
    extreme = np.array([-1e3, -50.0, 0.0, 50.0, 1e3])
    out = pres._sigmoid(extreme)
    assert np.isfinite(out).all()
    assert out[0] == pytest.approx(0.0)
    assert out[-1] == pytest.approx(1.0)


def test_bootstrap_to_returns_target_length() -> None:
    import numpy as np

    rng = np.random.default_rng(0)
    arr = np.arange(50)
    out = pres._bootstrap_to(arr, n_target=200, rng=rng)
    assert out.shape == (200,)
    assert set(out.tolist()).issubset(set(arr.tolist()))


def test_bootstrap_to_passes_through_when_lengths_match() -> None:
    import numpy as np

    rng = np.random.default_rng(0)
    arr = np.arange(20)
    out = pres._bootstrap_to(arr, n_target=20, rng=rng)
    assert np.array_equal(out, arr)


# ---------------------------------------------------------------------------
# Pure-logic — _extract_aggregator_columns + _fundamentals_columns
# ---------------------------------------------------------------------------


def test_extract_aggregator_columns_returns_final_day_only() -> None:
    aggregator = _hand_built_aggregator(
        candidate_means=[(1, "A", 0.30), (2, "B", 0.20)], n_samples=100
    )
    cols = pres._extract_aggregator_columns(aggregator, [1, 2])
    assert set(cols.keys()) == {1, 2}
    assert cols[1].shape == (100,)
    # Tight Normal(0.30, 0.015) → mean very close to 0.30
    assert abs(cols[1].mean() - 0.30) < 0.01
    assert abs(cols[2].mean() - 0.20) < 0.01


def test_extract_aggregator_columns_omits_unknown_candidate() -> None:
    aggregator = _hand_built_aggregator(
        candidate_means=[(1, "A", 0.30)], n_samples=50
    )
    cols = pres._extract_aggregator_columns(aggregator, [1, 99])
    assert set(cols.keys()) == {1}


def test_fundamentals_columns_skips_candidates_without_feature_vector() -> None:
    coefs = _hand_built_fundamentals()
    inputs = [
        pres.CandidateInput(candidate_id=1, name="A", feature_vector=_ok_feature()),
        pres.CandidateInput(candidate_id=2, name="B", feature_vector=None),
    ]
    cols = pres._fundamentals_columns(coefs, inputs, rng_seed=42)
    assert set(cols.keys()) == {1}


# ---------------------------------------------------------------------------
# Pure-logic — _combine_first_round_samples
# ---------------------------------------------------------------------------


def test_combine_rejects_invalid_poll_weight() -> None:
    aggregator = _hand_built_aggregator(
        candidate_means=[(1, "A", 0.30), (2, "B", 0.20)]
    )
    coefs = _hand_built_fundamentals()
    inputs = [
        pres.CandidateInput(1, "A", feature_vector=_ok_feature(candidate_id=1)),
        pres.CandidateInput(2, "B", feature_vector=_ok_feature(candidate_id=2)),
    ]
    with pytest.raises(ValueError, match="poll_weight"):
        pres._combine_first_round_samples(
            aggregator_posterior=aggregator,
            fundamentals_coefs=coefs,
            candidate_inputs=inputs,
            poll_weight=1.5,
            n_monte_carlo=100,
            seed=17,
        )


def test_combine_rejects_zero_monte_carlo() -> None:
    aggregator = _hand_built_aggregator(
        candidate_means=[(1, "A", 0.30), (2, "B", 0.20)]
    )
    coefs = _hand_built_fundamentals()
    inputs = [
        pres.CandidateInput(1, "A", feature_vector=_ok_feature(candidate_id=1)),
        pres.CandidateInput(2, "B", feature_vector=_ok_feature(candidate_id=2)),
    ]
    with pytest.raises(ValueError, match="n_monte_carlo"):
        pres._combine_first_round_samples(
            aggregator_posterior=aggregator,
            fundamentals_coefs=coefs,
            candidate_inputs=inputs,
            poll_weight=0.5,
            n_monte_carlo=0,
            seed=17,
        )


def test_combine_returns_marginal_shares_in_unit_interval() -> None:
    """Per-candidate shares are sigmoid-emitted marginals; each lies in
    (0, 1) but the captured field does NOT need to sum to 1.0 because real
    polls include "other/blank/undecided" that aren't in the input list."""
    aggregator = _hand_built_aggregator(
        candidate_means=[(1, "A", 0.30), (2, "B", 0.20), (3, "C", 0.15)],
        n_samples=200,
    )
    coefs = _hand_built_fundamentals()
    inputs = [
        pres.CandidateInput(1, "A", feature_vector=_ok_feature(candidate_id=1)),
        pres.CandidateInput(2, "B", feature_vector=_ok_feature(candidate_id=2)),
        pres.CandidateInput(3, "C", feature_vector=_ok_feature(candidate_id=3)),
    ]
    samples = pres._combine_first_round_samples(
        aggregator_posterior=aggregator,
        fundamentals_coefs=coefs,
        candidate_inputs=inputs,
        poll_weight=0.6,
        n_monte_carlo=500,
        seed=17,
    )
    assert samples.shape == (500, 3)
    # Marginal shares in the strict unit interval.
    assert (samples > 0.0).all()
    assert (samples < 1.0).all()


def test_combine_falls_back_to_polls_when_fundamentals_missing() -> None:
    import numpy as np

    aggregator = _hand_built_aggregator(
        candidate_means=[(1, "A", 0.50), (2, "B", 0.30)], n_samples=400
    )
    coefs = _hand_built_fundamentals()
    inputs = [
        pres.CandidateInput(1, "A", feature_vector=None),  # polls-only
        pres.CandidateInput(2, "B", feature_vector=_ok_feature(candidate_id=2)),
    ]
    samples = pres._combine_first_round_samples(
        aggregator_posterior=aggregator,
        fundamentals_coefs=coefs,
        candidate_inputs=inputs,
        poll_weight=0.5,
        n_monte_carlo=500,
        seed=17,
    )
    # A polls-mean ≈ 0.50 dominates → A should win the softmax-normalised median.
    assert np.median(samples[:, 0]) > np.median(samples[:, 1])


def test_combine_raises_when_candidate_has_no_input() -> None:
    aggregator = _hand_built_aggregator(
        candidate_means=[(1, "A", 0.30)], n_samples=50
    )
    coefs = _hand_built_fundamentals()
    inputs = [
        pres.CandidateInput(1, "A", feature_vector=_ok_feature(candidate_id=1)),
        # Candidate 99: no polls + no features → unrecoverable.
        pres.CandidateInput(99, "Missing", feature_vector=None),
    ]
    with pytest.raises(ValueError, match="neither polls nor fundamentals"):
        pres._combine_first_round_samples(
            aggregator_posterior=aggregator,
            fundamentals_coefs=coefs,
            candidate_inputs=inputs,
            poll_weight=0.5,
            n_monte_carlo=100,
            seed=17,
        )


def test_combine_is_reproducible_under_fixed_seed() -> None:
    import numpy as np

    aggregator = _hand_built_aggregator(
        candidate_means=[(1, "A", 0.30), (2, "B", 0.20)], n_samples=200
    )
    coefs = _hand_built_fundamentals()
    inputs = [
        pres.CandidateInput(1, "A", feature_vector=_ok_feature(candidate_id=1)),
        pres.CandidateInput(2, "B", feature_vector=_ok_feature(candidate_id=2)),
    ]
    a = pres._combine_first_round_samples(
        aggregator_posterior=aggregator,
        fundamentals_coefs=coefs,
        candidate_inputs=inputs,
        poll_weight=0.7,
        n_monte_carlo=300,
        seed=17,
    )
    b = pres._combine_first_round_samples(
        aggregator_posterior=aggregator,
        fundamentals_coefs=coefs,
        candidate_inputs=inputs,
        poll_weight=0.7,
        n_monte_carlo=300,
        seed=17,
    )
    assert np.array_equal(a, b)


# ---------------------------------------------------------------------------
# Pure-logic — runoff_win_probability_samples (no PyMC fit)
# ---------------------------------------------------------------------------


def test_runoff_win_probability_samples_returns_probabilities() -> None:
    import numpy as np

    swing = _hand_built_swing(intercept=0.0, beta_share=4.0, beta_inc=0.0)
    share_diff = np.array([0.05, -0.05, 0.20])
    incumbent_diff = np.array([0, 0, 0])
    out = pres.runoff_win_probability_samples(
        swing, share_diff=share_diff, incumbent_diff=incumbent_diff
    )
    assert out.shape == (3,)
    # Larger share_diff → higher win prob with positive beta_share.
    assert out[2] > out[0]
    assert out[0] > out[1]
    # All in [0, 1].
    assert (out >= 0.0).all()
    assert (out <= 1.0).all()


def test_runoff_win_probability_samples_rejects_shape_mismatch() -> None:
    import numpy as np

    swing = _hand_built_swing()
    with pytest.raises(ValueError, match="shape mismatch"):
        pres.runoff_win_probability_samples(
            swing,
            share_diff=np.array([0.1, 0.2]),
            incumbent_diff=np.array([0, 0, 0]),
        )


# ---------------------------------------------------------------------------
# Pure-logic — _build_runoff_matrix invariants
# ---------------------------------------------------------------------------


def test_build_runoff_matrix_pair_probabilities_sum_to_one() -> None:
    """ADR-013 C5: every MC sample contributes one (top1, top2) pair, so the
    pair_probability column sums to 1.0 ± 1e-6."""
    import numpy as np

    inputs = [
        pres.CandidateInput(10, "A"),
        pres.CandidateInput(20, "B"),
        pres.CandidateInput(30, "C"),
    ]
    # 60 samples: 30 (A, B), 20 (A, C), 10 (B, C). All directed.
    top1 = np.array([0] * 30 + [0] * 20 + [1] * 10)
    top2 = np.array([1] * 30 + [2] * 20 + [2] * 10)
    win_a = np.linspace(0.55, 0.65, num=60)
    entries = pres._build_runoff_matrix(
        candidate_inputs=inputs,
        top1_idx=top1,
        top2_idx=top2,
        win_a_prob=win_a,
    )
    total = sum(e.pair_probability for e in entries)
    assert total == pytest.approx(1.0, abs=1e-9)
    for e in entries:
        assert 0.0 <= e.winner_a_probability <= 1.0


def test_build_runoff_matrix_orders_by_descending_probability() -> None:
    import numpy as np

    inputs = [pres.CandidateInput(10, "A"), pres.CandidateInput(20, "B")]
    # Two pairs: (0, 1) gets 80% mass, (1, 0) gets 20%.
    top1 = np.array([0] * 80 + [1] * 20)
    top2 = np.array([1] * 80 + [0] * 20)
    win_a = np.full(100, 0.5)
    entries = pres._build_runoff_matrix(
        candidate_inputs=inputs,
        top1_idx=top1,
        top2_idx=top2,
        win_a_prob=win_a,
    )
    assert entries[0].a_candidate_id == 10
    assert entries[0].pair_probability == pytest.approx(0.80)
    assert entries[1].a_candidate_id == 20
    assert entries[1].pair_probability == pytest.approx(0.20)


def test_build_runoff_matrix_clips_win_probability_into_unit_interval() -> None:
    import numpy as np

    inputs = [pres.CandidateInput(10, "A"), pres.CandidateInput(20, "B")]
    # Inject an out-of-range win probability (e.g., upstream bug) — the
    # builder clips so the ADR-014 contract holds even if the swing model
    # output goes weird.
    top1 = np.array([0, 0])
    top2 = np.array([1, 1])
    win_a = np.array([1.5, -0.3])
    entries = pres._build_runoff_matrix(
        candidate_inputs=inputs,
        top1_idx=top1,
        top2_idx=top2,
        win_a_prob=win_a,
    )
    assert len(entries) == 1
    assert 0.0 <= entries[0].winner_a_probability <= 1.0


# ---------------------------------------------------------------------------
# Pure-logic — _per_candidate_summary
# ---------------------------------------------------------------------------


def test_per_candidate_summary_emits_adr_014_quantile_levels() -> None:
    import numpy as np

    inputs = [pres.CandidateInput(10, "A"), pres.CandidateInput(20, "B")]
    rng = np.random.default_rng(7)
    samples = np.zeros((500, 2))
    samples[:, 0] = rng.normal(0.30, 0.02, 500)
    samples[:, 1] = rng.normal(0.20, 0.02, 500)
    # Top-1 is always A (col 0), top-2 always B (col 1).
    top1 = np.zeros(500, dtype=int)
    top2 = np.ones(500, dtype=int)
    summaries = pres._per_candidate_summary(
        candidate_inputs=inputs,
        first_round_samples=samples,
        top1_idx=top1,
        top2_idx=top2,
    )
    # ADR-014 contract.
    assert set(summaries[0].vote_share_quantiles.keys()) == set(pres.QUANTILE_LEVELS)
    # Median for A ≈ 0.30, B ≈ 0.20.
    assert summaries[0].vote_share_quantiles[0.5] == pytest.approx(0.30, abs=0.01)
    # A is always top-1 → qualifies_for_runoff_probability = 1.0 for both A
    # (always top-1) and B (always top-2).
    assert summaries[0].qualifies_for_runoff_probability == pytest.approx(1.0)
    assert summaries[1].qualifies_for_runoff_probability == pytest.approx(1.0)


def test_per_candidate_summary_outright_win_when_share_exceeds_half() -> None:
    import numpy as np

    inputs = [pres.CandidateInput(10, "A"), pres.CandidateInput(20, "B")]
    samples = np.zeros((100, 2))
    # 60 samples have A > 0.5 (outright win); 40 have A in (0.4, 0.5) — runoff.
    samples[:60, 0] = 0.55
    samples[:60, 1] = 0.30
    samples[60:, 0] = 0.45
    samples[60:, 1] = 0.40
    top1 = np.zeros(100, dtype=int)
    top2 = np.ones(100, dtype=int)
    summaries = pres._per_candidate_summary(
        candidate_inputs=inputs,
        first_round_samples=samples,
        top1_idx=top1,
        top2_idx=top2,
    )
    assert summaries[0].win_probability_round1 == pytest.approx(0.60)
    assert summaries[1].win_probability_round1 == pytest.approx(0.0)


# ---------------------------------------------------------------------------
# fit_runoff_swing — input validation
# ---------------------------------------------------------------------------


def test_fit_runoff_swing_raises_on_empty_history() -> None:
    with pytest.raises(ValueError, match="no runoff history"):
        pres.fit_runoff_swing([])


# ---------------------------------------------------------------------------
# fit_and_predict — input validation (no PyMC)
# ---------------------------------------------------------------------------


def test_fit_and_predict_requires_two_candidates() -> None:
    aggregator = _hand_built_aggregator(candidate_means=[(1, "A", 0.30)])
    coefs = _hand_built_fundamentals()
    inputs = [pres.CandidateInput(1, "A", feature_vector=_ok_feature())]
    with pytest.raises(ValueError, match="at least 2 candidates"):
        pres.fit_and_predict(
            aggregator_posterior=aggregator,
            fundamentals_coefs=coefs,
            candidate_inputs=inputs,
            runoff_history=[],
        )


# ---------------------------------------------------------------------------
# fit_and_predict with a pre-fit swing — no PyMC needed
# ---------------------------------------------------------------------------


def test_fit_and_predict_with_pre_fit_swing_returns_adr_014_shape() -> None:
    """End-to-end happy path with a hand-rolled swing model — no PyMC.

    Asserts the ADR-013 C5 invariant (pair_probability sums to 1.0) and
    the ADR-014 contract (candidates carry the 7 quantile levels;
    runoff_matrix carries directed entries with winner_a_probability ∈ [0,1]).
    """
    aggregator = _hand_built_aggregator(
        candidate_means=[(1, "A", 0.30), (2, "B", 0.20), (3, "C", 0.15)],
        n_samples=400,
    )
    coefs = _hand_built_fundamentals()
    inputs = [
        pres.CandidateInput(
            1, "A", party_id=100, party_name="Alpha",
            feature_vector=_ok_feature(candidate_id=1, incumbent_party=False),
        ),
        pres.CandidateInput(
            2, "B", party_id=200, party_name="Beta",
            feature_vector=_ok_feature(candidate_id=2, incumbent_party=True),
        ),
        pres.CandidateInput(
            3, "C", party_id=300, party_name="Gamma",
            feature_vector=_ok_feature(candidate_id=3, incumbent_party=False),
        ),
    ]
    swing = _hand_built_swing()
    posterior = pres.fit_and_predict(
        aggregator_posterior=aggregator,
        fundamentals_coefs=coefs,
        candidate_inputs=inputs,
        runoff_history=[],
        poll_weight=0.7,
        n_monte_carlo=2000,
        runoff_swing=swing,
    )
    assert len(posterior.candidates) == 3
    # ADR-013 C5 — pair_probability sums to 1.0.
    total = sum(e.pair_probability for e in posterior.runoff_matrix)
    assert total == pytest.approx(1.0, abs=1e-6)
    # ADR-014 — each candidate has the 7 quantile levels.
    for cp in posterior.candidates:
        assert set(cp.vote_share_quantiles.keys()) == set(pres.QUANTILE_LEVELS)
        assert 0.0 <= cp.win_probability_round1 <= 1.0
        assert 0.0 <= cp.qualifies_for_runoff_probability <= 1.0
    # Every runoff entry's winner_a_probability ∈ [0, 1].
    for e in posterior.runoff_matrix:
        assert 0.0 <= e.winner_a_probability <= 1.0
    # First-round samples shape preserved for the calibration gate (#36).
    assert posterior.first_round_samples.shape == (2000, 3)
    # Per-candidate marginals are in (0, 1) — see _combine docstring for why
    # we don't enforce a softmax-style simplex.
    assert (posterior.first_round_samples > 0.0).all()
    assert (posterior.first_round_samples < 1.0).all()


def test_fit_and_predict_is_reproducible_under_fixed_seed() -> None:
    aggregator = _hand_built_aggregator(
        candidate_means=[(1, "A", 0.30), (2, "B", 0.20)], n_samples=200
    )
    coefs = _hand_built_fundamentals()
    inputs = [
        pres.CandidateInput(1, "A", feature_vector=_ok_feature(candidate_id=1)),
        pres.CandidateInput(2, "B", feature_vector=_ok_feature(candidate_id=2)),
    ]
    swing = _hand_built_swing()
    a = pres.fit_and_predict(
        aggregator_posterior=aggregator,
        fundamentals_coefs=coefs,
        candidate_inputs=inputs,
        runoff_history=[],
        n_monte_carlo=500,
        seed=17,
        runoff_swing=swing,
    )
    b = pres.fit_and_predict(
        aggregator_posterior=aggregator,
        fundamentals_coefs=coefs,
        candidate_inputs=inputs,
        runoff_history=[],
        n_monte_carlo=500,
        seed=17,
        runoff_swing=swing,
    )
    # Same seed → same first-round samples and matrix.
    import numpy as np

    assert np.array_equal(a.first_round_samples, b.first_round_samples)
    assert a.runoff_matrix == b.runoff_matrix


# ---------------------------------------------------------------------------
# Historical-shape synthetic runoff data
# ---------------------------------------------------------------------------


_HISTORICAL_RUNOFFS: tuple[pres.RunoffHistoryRow, ...] = (
    # 2007: Colom (UNE, 28.2%) vs Pérez Molina (PP, 23.5%) → Colom won (centre-left)
    pres.RunoffHistoryRow(
        cycle=2007,
        a_candidate_id=1, b_candidate_id=2,
        a_round1_share=0.282, b_round1_share=0.235,
        a_incumbent_party=False, b_incumbent_party=False,
        a_won_runoff=True,
    ),
    # 2011: Pérez Molina (PP, 36.0%) vs Baldizón (LIDER, 23.2%) → Pérez Molina won
    pres.RunoffHistoryRow(
        cycle=2011,
        a_candidate_id=3, b_candidate_id=4,
        a_round1_share=0.360, b_round1_share=0.232,
        a_incumbent_party=False, b_incumbent_party=False,
        a_won_runoff=True,
    ),
    # 2015: Morales (FCN, 23.9%) vs Torres (UNE, 19.8%) → Morales won
    pres.RunoffHistoryRow(
        cycle=2015,
        a_candidate_id=5, b_candidate_id=6,
        a_round1_share=0.239, b_round1_share=0.198,
        a_incumbent_party=False, b_incumbent_party=False,
        a_won_runoff=True,
    ),
    # 2019: Giammattei (Vamos, 14.0%) vs Torres (UNE, 25.5%) → Giammattei won
    # NOTE: by convention A = first-place; here Torres was first-place but
    # the swing went the other way, so a_won_runoff=False.
    pres.RunoffHistoryRow(
        cycle=2019,
        a_candidate_id=7, b_candidate_id=8,
        a_round1_share=0.255, b_round1_share=0.140,
        a_incumbent_party=False, b_incumbent_party=False,
        a_won_runoff=False,
    ),
    # 2023: Torres (UNE, 15.8%) vs Arévalo (Semilla, 11.7%) → Arévalo won
    pres.RunoffHistoryRow(
        cycle=2023,
        a_candidate_id=9, b_candidate_id=10,
        a_round1_share=0.158, b_round1_share=0.117,
        a_incumbent_party=False, b_incumbent_party=False,
        a_won_runoff=False,
    ),
)


# ---------------------------------------------------------------------------
# PyMC — fit_runoff_swing + diagnostics gate (slow)
# ---------------------------------------------------------------------------


@pytest.mark.slow
def test_fit_runoff_swing_passes_diagnostics_gate() -> None:
    pytest.importorskip("pymc")
    pytest.importorskip("arviz")

    swing = pres.fit_runoff_swing(
        _HISTORICAL_RUNOFFS,
        draws=600,
        tune=600,
        chains=2,
        target_accept=0.9,
        rhat_threshold=1.1,
        ess_threshold=80.0,
    )
    assert swing.max_r_hat < 1.1
    assert swing.min_bulk_ess > 80.0
    assert swing.n_observations == 5
    assert swing.intercept_samples.shape == swing.beta_share_diff_samples.shape


@pytest.mark.slow
def test_fit_runoff_swing_raises_on_impossible_threshold() -> None:
    pytest.importorskip("pymc")

    with pytest.raises(pres.SamplingDiagnosticsError):
        pres.fit_runoff_swing(
            _HISTORICAL_RUNOFFS,
            draws=200,
            tune=200,
            chains=2,
            rhat_threshold=0.0,
            ess_threshold=1.0,
        )


@pytest.mark.slow
def test_fit_runoff_swing_is_reproducible_under_fixed_seed() -> None:
    pytest.importorskip("pymc")
    import numpy as np

    kwargs: dict[str, Any] = {
        "draws": 400,
        "tune": 400,
        "chains": 2,
        "target_accept": 0.9,
        "rhat_threshold": 1.2,
        "ess_threshold": 50.0,
        "seed": 17,
    }
    a = pres.fit_runoff_swing(_HISTORICAL_RUNOFFS, **kwargs)
    b = pres.fit_runoff_swing(_HISTORICAL_RUNOFFS, **kwargs)
    assert np.allclose(a.intercept_samples, b.intercept_samples)
    assert np.allclose(a.beta_share_diff_samples, b.beta_share_diff_samples)


# ---------------------------------------------------------------------------
# PyMC — fit_and_predict end-to-end, ADR-014 contract on real PyMC fit
# ---------------------------------------------------------------------------


@pytest.mark.slow
def test_fit_and_predict_end_to_end_with_pymc_swing_fit() -> None:
    """End-to-end: aggregator + fundamentals + PyMC-fit swing → ADR-014 payload.

    Asserts the C5 invariant (pair_probability sums to 1) and the C6 gate
    is satisfied by the swing fit; doesn't assert calibration thresholds —
    those are exercised by the backtest test below.
    """
    pytest.importorskip("pymc")

    aggregator = _hand_built_aggregator(
        candidate_means=[(1, "A", 0.32), (2, "B", 0.22), (3, "C", 0.18)],
        n_samples=300,
    )
    coefs = _hand_built_fundamentals()
    inputs = [
        pres.CandidateInput(
            1, "A", feature_vector=_ok_feature(candidate_id=1)
        ),
        pres.CandidateInput(
            2, "B", feature_vector=_ok_feature(candidate_id=2, incumbent_party=True)
        ),
        pres.CandidateInput(
            3, "C", feature_vector=_ok_feature(candidate_id=3)
        ),
    ]
    posterior = pres.fit_and_predict(
        aggregator_posterior=aggregator,
        fundamentals_coefs=coefs,
        candidate_inputs=inputs,
        runoff_history=_HISTORICAL_RUNOFFS,
        poll_weight=0.7,
        n_monte_carlo=2000,
        runoff_draws=400,
        runoff_tune=400,
        runoff_chains=2,
        target_accept=0.9,
        rhat_threshold=1.2,
        ess_threshold=50.0,
    )
    assert len(posterior.candidates) == 3
    total = sum(e.pair_probability for e in posterior.runoff_matrix)
    assert total == pytest.approx(1.0, abs=1e-6)
    assert (posterior.first_round_samples > 0.0).all()
    assert (posterior.first_round_samples < 1.0).all()
    assert posterior.max_r_hat < 1.2
    assert posterior.min_bulk_ess > 50.0


# ---------------------------------------------------------------------------
# ADR-013 C1/C2/C3 — synthetic 2019-shaped backtest
# ---------------------------------------------------------------------------


@pytest.mark.slow
def test_backtest_2019_shape_meets_acceptance_thresholds() -> None:
    """ADR-013 C1/C2/C3 thresholds applied to a synthetic 2019-shaped fit.

    The data-generating process here is the same model the combiner expects
    (Linzer/Kremp polls + logit-share fundamentals + softmax). The test
    asserts the combiner's CI is *empirically* calibrated on data that
    matches its assumptions — proves the wiring is correct without claiming
    coverage on real 2019 data, which is the role of the calibration gate
    against the live DB.
    """
    pytest.importorskip("pymc")
    import numpy as np

    actuals = {1: 0.255, 2: 0.140, 3: 0.113, 4: 0.061}
    candidate_names = {1: "Torres", 2: "Giammattei", 3: "Mulet", 4: "Rios"}
    # Aggregator centred on actuals — the polls signal is unbiased for this
    # synthetic backtest. Fundamentals deliberately wider so the test
    # exercises the blend with imperfect priors.
    aggregator = _hand_built_aggregator(
        candidate_means=[
            (cid, candidate_names[cid], share) for cid, share in actuals.items()
        ],
        n_samples=600,
        sigma=0.012,
    )
    coefs = _hand_built_fundamentals(sigma=0.10)
    inputs = [
        pres.CandidateInput(
            cid, candidate_names[cid],
            feature_vector=_ok_feature(candidate_id=cid),
        )
        for cid in actuals
    ]
    posterior = pres.fit_and_predict(
        aggregator_posterior=aggregator,
        fundamentals_coefs=coefs,
        candidate_inputs=inputs,
        runoff_history=_HISTORICAL_RUNOFFS,
        poll_weight=0.85,
        n_monte_carlo=4000,
        runoff_draws=400,
        runoff_tune=400,
        runoff_chains=2,
        target_accept=0.9,
        rhat_threshold=1.2,
        ess_threshold=50.0,
    )

    # C1/C2: coverage at 80% and 95% across the four-candidate field.
    cov_80, cov_95 = 0, 0
    for j, ci in enumerate(inputs):
        col = posterior.first_round_samples[:, j]
        lo80, hi80 = np.quantile(col, [0.10, 0.90])
        lo95, hi95 = np.quantile(col, [0.025, 0.975])
        actual = actuals[ci.candidate_id]
        if lo80 <= actual <= hi80:
            cov_80 += 1
        if lo95 <= actual <= hi95:
            cov_95 += 1
    rate_80 = cov_80 / len(actuals)
    rate_95 = cov_95 / len(actuals)
    assert rate_80 >= 0.80, f"80% CI coverage {rate_80:.2f} < 0.80"
    assert rate_95 >= 0.95, f"95% CI coverage {rate_95:.2f} < 0.95"

    # C3: top-3 median absolute error ≤ 5pp.
    # Use the posterior median per candidate.
    medians = {
        ci.candidate_id: float(np.median(posterior.first_round_samples[:, j]))
        for j, ci in enumerate(inputs)
    }
    # Rank candidates by actual to get the "top-3".
    top3_ids = sorted(actuals, key=lambda k: -actuals[k])[:3]
    abs_errors = [abs(medians[cid] - actuals[cid]) for cid in top3_ids]
    abs_errors.sort()
    n = len(abs_errors)
    median_abs_error = (
        abs_errors[n // 2]
        if n % 2 == 1
        else 0.5 * (abs_errors[n // 2 - 1] + abs_errors[n // 2])
    )
    assert median_abs_error <= 0.05, (
        f"top-3 median absolute error {median_abs_error:.3f} > 0.05 (5pp)"
    )


# ---------------------------------------------------------------------------
# Defensive — frozen dataclass equality (used by reproducibility test)
# ---------------------------------------------------------------------------


def test_runoff_matrix_entry_is_hashable_for_equality() -> None:
    # Frozen dataclass equality semantics make the reproducibility test
    # above trivially correct; this confirms the contract.
    e1 = pres.RunoffMatrixEntry(1, 2, 0.5, 0.7)
    e2 = pres.RunoffMatrixEntry(1, 2, 0.5, 0.7)
    assert e1 == e2
    assert dataclasses.replace(e1, pair_probability=0.6) != e1
