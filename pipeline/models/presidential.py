"""Presidential combiner — first round + runoff (issue #32, ADR-013, ADR-014).

Blends the Linzer/Kremp poll aggregator (#30, :mod:`pipeline.models.poll_aggregator`)
with the fundamentals regression (#31, :mod:`pipeline.models.fundamentals`) into a
single first-round vote-share posterior per candidate, then Monte-Carlo simulates
``n_monte_carlo`` first-round outcomes and applies a learned second-round swing
matrix to the top-two of each outcome.

Pipeline shape::

    AggregatorPosterior   ──┐
                            ├──► combine on logit scale + softmax over candidates
    FundamentalsCoefs ──────┘   per Monte-Carlo sample → first_round_samples
                                                                  │
                                ┌─────────────────────────────────┘
                                ▼
    For each sample s:
      * identify top-two (a*, b*)
      * compute P(a* wins runoff | s) via the swing model
      * accumulate per-candidate / per-pair counts
                                │
                                ▼
                  PresidentialPosterior  (ADR-014 contract)

Combination
-----------

For each Monte-Carlo sample ``s`` and candidate ``c``:

    polls_share[s, c]   ← row-bootstrapped from
                          ``aggregator_posterior.samples[:, -1, c]``
    fund_share[s, c]    ← independent draw from
                          ``fundamentals_coefs.predict(features_c, include_noise=True)``
    logit_blend[s, c]   ← poll_weight * logit(polls_share)
                          + (1 - poll_weight) * logit(fund_share)
    share[s, c]         ← sigmoid(logit_blend[s, c])

Per ADR-020 the blend is on the logit scale. Shares are emitted as
*marginal* draws (sigmoid, not softmax) because real Guatemalan presidential
fields don't sum to 1 within the captured candidates: 5-15% of the electorate
typically lands on "other/blank/undecided" candidates that don't appear in
the polls or the fundamentals features. Forcing the captured field onto the
simplex would mechanically over-state each candidate's share. The runoff
matrix's ``pair_probability`` invariant (∑ = 1.0) holds independently because
every Monte-Carlo sample contributes exactly one (top-1, top-2) pair.

Candidates with only one of the two inputs available fall back to that side
alone — the caller passes ``None`` for ``feature_vector`` or omits the
candidate from the aggregator's candidate list.

Runoff swing matrix
-------------------

A Bayesian logistic regression fit on historical first-round → second-round
outcomes (2007/2011/2015/2019/2023)::

    a_won_runoff_i ~ Bernoulli(sigmoid(
        intercept
        + β_share_diff * (a_round1_share - b_round1_share)
        + β_incumbent_diff * (int(a_incumbent_party) - int(b_incumbent_party))
    ))

With only 5 historical observations the priors dominate; they are deliberately
informative but symmetric so the data can move them. The fit emits a
:class:`RunoffSwingModel` with per-coefficient posterior samples; per Monte-Carlo
first-round sample we evaluate ``P(a* wins | features)`` against ONE swing-model
draw to keep the runoff uncertainty correlated with the swing-model uncertainty.

PyMC NUTS configuration matches the project's Operational Commitments
(4 chains × 2000 warmup × 4000 draws × ``target_accept=0.95``, seed=17). Per
ADR-013 C5 the runoff matrix's ``pair_probability`` entries sum to 1.0 ± 1e-6
and every ``winner_a_probability`` lies in ``[0, 1]``. Per ADR-013 C6 every
monitored quantity has ``r_hat < 1.01`` and ``bulk_ess > 400``; failures raise
:class:`SamplingDiagnosticsError`.

The module is import-safe without PyMC; the heavy stack is lazy-imported inside
:func:`fit_runoff_swing`.
"""

from __future__ import annotations

import dataclasses
import math
from collections.abc import Sequence
from typing import Any

from pipeline.models.fundamentals import (
    FeatureVector,
    FundamentalsCoefficients,
)
from pipeline.models.poll_aggregator import (
    AggregatorPosterior,
    SamplingDiagnosticsError,
)

# ADR-014 quantile contract — keep in sync with the API payload schema.
QUANTILE_LEVELS: tuple[float, ...] = (0.05, 0.10, 0.25, 0.50, 0.75, 0.90, 0.95)

# Numerical clip applied before taking logit() so we never feed 0 or 1 into
# log(p / (1 - p)). 1e-6 keeps the resulting logit values bounded inside
# roughly ±14, well within numpy float64 precision.
_LOGIT_EPS: float = 1e-6


# ---------------------------------------------------------------------------
# Public dataclasses
# ---------------------------------------------------------------------------


@dataclasses.dataclass(frozen=True)
class CandidateInput:
    """One candidate's identity + per-cycle feature vector for prediction.

    ``feature_vector`` may be ``None`` when no fundamentals features have been
    constructed for this candidate (e.g., a late entrant before the macro /
    sentiment joins land). In that case the combiner uses only the polls
    signal for this candidate.
    """

    candidate_id: int
    name: str
    party_id: int | None = None
    party_name: str | None = None
    wikidata_qid: str | None = None
    feature_vector: FeatureVector | None = None


@dataclasses.dataclass(frozen=True)
class RunoffHistoryRow:
    """One historical first-round → second-round outcome.

    ``a_won_runoff`` is the outcome for candidate A (the first-place finisher
    by convention; the loader normalises so A is the higher round-1 share).
    """

    cycle: int
    a_candidate_id: int
    b_candidate_id: int
    a_round1_share: float
    b_round1_share: float
    a_incumbent_party: bool
    b_incumbent_party: bool
    a_won_runoff: bool

    def __post_init__(self) -> None:
        if not 0.0 < self.a_round1_share < 1.0:
            raise ValueError(
                f"a_round1_share must be in (0,1), got {self.a_round1_share}"
            )
        if not 0.0 < self.b_round1_share < 1.0:
            raise ValueError(
                f"b_round1_share must be in (0,1), got {self.b_round1_share}"
            )


@dataclasses.dataclass(frozen=True)
class RunoffSwingModel:
    """Posterior over the runoff logistic-regression coefficients.

    Sample arrays are 1-D of shape ``(n_samples,)``; the per-sample triple
    ``(intercept_samples[s], beta_share_diff_samples[s],
    beta_incumbent_diff_samples[s])`` defines one draw of the runoff outcome
    model, used in :func:`runoff_win_probability_samples`.
    """

    intercept_samples: Any  # numpy.ndarray (n_samples,)
    beta_share_diff_samples: Any  # numpy.ndarray (n_samples,)
    beta_incumbent_diff_samples: Any  # numpy.ndarray (n_samples,)
    n_observations: int
    max_r_hat: float
    min_bulk_ess: float


@dataclasses.dataclass(frozen=True)
class RunoffMatrixEntry:
    """One (top-1, top-2) pair entry in the runoff matrix per ADR-014."""

    a_candidate_id: int
    b_candidate_id: int
    pair_probability: float
    winner_a_probability: float


@dataclasses.dataclass(frozen=True)
class CandidatePosterior:
    """Per-candidate first-round summary per ADR-014."""

    candidate_id: int
    name: str
    party_id: int | None
    party_name: str | None
    wikidata_qid: str | None
    vote_share_quantiles: dict[float, float]
    win_probability_round1: float
    qualifies_for_runoff_probability: float


@dataclasses.dataclass(frozen=True)
class PresidentialPosterior:
    """Combined first-round + runoff posterior per ADR-014.

    ``first_round_samples`` is an ``(n_monte_carlo, n_candidates)`` ndarray of
    softmax-normalised share draws, retained so the calibration gate (#36) and
    the posterior archive (#33) can recompute custom intervals without
    re-running the combiner.
    """

    candidates: tuple[CandidatePosterior, ...]
    runoff_matrix: tuple[RunoffMatrixEntry, ...]
    first_round_samples: Any  # numpy.ndarray (n_monte_carlo, n_candidates)
    n_monte_carlo: int
    max_r_hat: float
    min_bulk_ess: float


# ---------------------------------------------------------------------------
# Helpers — logit / softmax / sampling
# ---------------------------------------------------------------------------


def _clip_for_logit(arr: Any) -> Any:
    """Clip an ndarray of shares into ``[eps, 1-eps]`` for safe ``logit``."""
    import numpy as np  # noqa: PLC0415

    return np.clip(arr, _LOGIT_EPS, 1.0 - _LOGIT_EPS)


def _logit_arr(arr: Any) -> Any:
    """Logit of an ndarray, with clipping."""
    import numpy as np  # noqa: PLC0415

    clipped = _clip_for_logit(arr)
    return np.log(clipped / (1.0 - clipped))


def _sigmoid(arr: Any) -> Any:
    """Element-wise sigmoid; numerically stable for large-magnitude inputs."""
    import numpy as np  # noqa: PLC0415

    a = np.asarray(arr, dtype=float)
    # Split positive/negative branches so exp never overflows on +∞ inputs.
    out = np.empty_like(a)
    pos_mask = a >= 0
    neg_mask = ~pos_mask
    out[pos_mask] = 1.0 / (1.0 + np.exp(-a[pos_mask]))
    exp_pos = np.exp(a[neg_mask])
    out[neg_mask] = exp_pos / (1.0 + exp_pos)
    return out


def _bootstrap_to(samples: Any, n_target: int, rng: Any) -> Any:
    """Resample ``samples`` along axis 0 to length ``n_target`` (with replacement).

    Used to align the aggregator's posterior draw count and the fundamentals'
    predictive draw count to a common ``n_monte_carlo``. Aggregator output is
    typically 16k draws; fundamentals predictive is 16k draws by default; we
    target 10k MC samples per the issue spec.
    """
    import numpy as np  # noqa: PLC0415

    arr = np.asarray(samples)
    if arr.shape[0] == n_target:
        return arr
    idx = rng.integers(0, arr.shape[0], size=n_target)
    return arr[idx]


# ---------------------------------------------------------------------------
# Combination: aggregator + fundamentals → first-round shares per MC sample
# ---------------------------------------------------------------------------


def _extract_aggregator_columns(
    aggregator_posterior: AggregatorPosterior,
    candidate_ids: Sequence[int],
) -> dict[int, Any]:
    """Return ``{candidate_id: final_day_samples_1d}`` for candidates the
    aggregator covers; candidates not in the aggregator are simply omitted.

    The aggregator stores ``samples`` as ``(n_samples, n_days, n_candidates)``.
    The final-day slice is the "now-cast" used as the input to the combiner.
    """
    import numpy as np  # noqa: PLC0415

    arr = np.asarray(aggregator_posterior.samples)
    final = arr[:, -1, :]  # (S, J)
    cand_to_col = {
        c.candidate_id: j for j, c in enumerate(aggregator_posterior.candidates)
    }
    out: dict[int, Any] = {}
    for cand_id in candidate_ids:
        if cand_id in cand_to_col:
            out[cand_id] = final[:, cand_to_col[cand_id]]
    return out


def _fundamentals_columns(
    fundamentals_coefs: FundamentalsCoefficients,
    candidate_inputs: Sequence[CandidateInput],
    *,
    rng_seed: int,
) -> dict[int, Any]:
    """Return ``{candidate_id: fundamentals_predictive_1d}`` for candidates
    whose ``feature_vector`` is set; others are omitted.

    Each candidate is predicted with its own RNG offset so the per-sample
    residual noise is independent across candidates (matching how their
    sentiment / approval idiosyncrasies are uncorrelated).
    """
    out: dict[int, Any] = {}
    for offset, ci in enumerate(candidate_inputs):
        if ci.feature_vector is None:
            continue
        out[ci.candidate_id] = fundamentals_coefs.predict(
            ci.feature_vector,
            include_noise=True,
            rng_seed=rng_seed + offset,
        )
    return out


def _combine_first_round_samples(
    *,
    aggregator_posterior: AggregatorPosterior,
    fundamentals_coefs: FundamentalsCoefficients,
    candidate_inputs: Sequence[CandidateInput],
    poll_weight: float,
    n_monte_carlo: int,
    seed: int,
) -> Any:
    """Build ``(n_monte_carlo, n_candidates)`` per-candidate marginal share draws.

    Per candidate, blend ``poll_weight * logit(polls)`` with
    ``(1 - poll_weight) * logit(fundamentals)`` on the per-MC-sample logit
    scale, then apply sigmoid so each marginal share lies in (0, 1). The
    captured candidates don't sum to 1 — see the module docstring for why
    softmax would be wrong here. Candidates with only one signal available
    use that one alone (the missing side contributes weight 0).
    """
    import numpy as np  # noqa: PLC0415

    if not 0.0 <= poll_weight <= 1.0:
        raise ValueError(f"poll_weight must be in [0,1], got {poll_weight}")
    if n_monte_carlo <= 0:
        raise ValueError(f"n_monte_carlo must be positive, got {n_monte_carlo}")
    if not candidate_inputs:
        raise ValueError("no candidate inputs")

    rng = np.random.default_rng(seed)
    cand_ids = [ci.candidate_id for ci in candidate_inputs]
    polls_cols = _extract_aggregator_columns(aggregator_posterior, cand_ids)
    fund_cols = _fundamentals_columns(
        fundamentals_coefs, candidate_inputs, rng_seed=seed + 1
    )

    n_candidates = len(candidate_inputs)
    logit_blend = np.zeros((n_monte_carlo, n_candidates), dtype=float)
    for j, ci in enumerate(candidate_inputs):
        polls = polls_cols.get(ci.candidate_id)
        fund = fund_cols.get(ci.candidate_id)
        if polls is None and fund is None:
            raise ValueError(
                f"candidate_id={ci.candidate_id} has neither polls nor "
                "fundamentals input; cannot combine"
            )
        if polls is None:
            # Fundamentals-only candidate: blend reduces to the fundamentals
            # logit directly (effective poll_weight = 0 for this candidate).
            fund_samples = _bootstrap_to(fund, n_monte_carlo, rng)
            logit_blend[:, j] = _logit_arr(fund_samples)
            continue
        if fund is None:
            # Polls-only candidate: effective poll_weight = 1.
            polls_samples = _bootstrap_to(polls, n_monte_carlo, rng)
            logit_blend[:, j] = _logit_arr(polls_samples)
            continue
        polls_samples = _bootstrap_to(polls, n_monte_carlo, rng)
        fund_samples = _bootstrap_to(fund, n_monte_carlo, rng)
        logit_blend[:, j] = poll_weight * _logit_arr(polls_samples) + (
            1.0 - poll_weight
        ) * _logit_arr(fund_samples)

    return _sigmoid(logit_blend)


# ---------------------------------------------------------------------------
# Runoff swing model — Bayesian logistic regression on historical outcomes
# ---------------------------------------------------------------------------


def fit_runoff_swing(
    history: Sequence[RunoffHistoryRow],
    *,
    draws: int = 4000,
    tune: int = 2000,
    chains: int = 4,
    target_accept: float = 0.95,
    seed: int = 17,
    rhat_threshold: float = 1.01,
    ess_threshold: float = 400.0,
) -> RunoffSwingModel:
    """Fit the logistic runoff-outcome model on ``history``.

    With the historical run-off corpus (5 cycles) the priors dominate; that
    is by design — informative-but-symmetric priors keep the model from
    over-claiming on a tiny sample while still letting the data move the
    posterior. Diagnostics gate is the ADR-013 C6 leg.
    """
    if not history:
        raise ValueError("no runoff history to fit")

    try:
        import arviz as az  # noqa: PLC0415
        import numpy as np  # noqa: PLC0415
        import pymc as pm  # noqa: PLC0415
    except ImportError as exc:  # pragma: no cover - exercised when extra missing
        raise RuntimeError(
            "PyMC not installed. Install with `uv sync --extra modelling`."
        ) from exc

    share_diff = np.array(
        [h.a_round1_share - h.b_round1_share for h in history], dtype=float
    )
    incumbent_diff = np.array(
        [int(h.a_incumbent_party) - int(h.b_incumbent_party) for h in history],
        dtype=float,
    )
    y = np.array([int(h.a_won_runoff) for h in history], dtype=int)

    with pm.Model():
        intercept = pm.Normal("intercept", mu=0.0, sigma=0.5)
        # First-round gap should mildly predict winning; share_diff ranges in
        # roughly [-0.2, 0.2] historically so a unit-scale prior is generous.
        beta_share_diff = pm.Normal("beta_share_diff", mu=2.0, sigma=2.0)
        # Anti-incumbent dynamic is the historical Guatemalan pattern (every
        # incumbent-party finalist since 2007 has lost the runoff). Centred
        # negative with moderate spread.
        beta_incumbent_diff = pm.Normal(
            "beta_incumbent_diff", mu=-0.5, sigma=1.0
        )
        logits = (
            intercept
            + beta_share_diff * share_diff
            + beta_incumbent_diff * incumbent_diff
        )
        pm.Bernoulli("y", logit_p=logits, observed=y)

        trace = pm.sample(
            draws=draws,
            tune=tune,
            chains=chains,
            target_accept=target_accept,
            random_seed=seed,
            progressbar=False,
            compute_convergence_checks=False,
        )

    summary = az.summary(
        trace, var_names=["intercept", "beta_share_diff", "beta_incumbent_diff"]
    )
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
    beta_share_samples = (
        trace.posterior["beta_share_diff"].stack(sample=("chain", "draw")).values
    )
    beta_inc_samples = (
        trace.posterior["beta_incumbent_diff"]
        .stack(sample=("chain", "draw")).values
    )
    return RunoffSwingModel(
        intercept_samples=intercept_samples,
        beta_share_diff_samples=beta_share_samples,
        beta_incumbent_diff_samples=beta_inc_samples,
        n_observations=len(history),
        max_r_hat=max_rhat,
        min_bulk_ess=min_ess,
    )


def runoff_win_probability_samples(
    swing: RunoffSwingModel,
    *,
    share_diff: Any,
    incumbent_diff: Any,
) -> Any:
    """Return per-MC-sample ``P(A wins | features, swing)`` aligned to the
    swing model's posterior draws.

    ``share_diff`` and ``incumbent_diff`` are ndarrays of length
    ``n_monte_carlo``; the swing model carries ``n_swing`` posterior draws.
    We bootstrap one swing draw per MC sample so the runoff uncertainty is
    correlated with the swing-model uncertainty rather than averaging it out.
    """
    import numpy as np  # noqa: PLC0415

    sd = np.asarray(share_diff, dtype=float)
    incd = np.asarray(incumbent_diff, dtype=float)
    if sd.shape != incd.shape:
        raise ValueError(
            f"share_diff and incumbent_diff shape mismatch: {sd.shape} vs {incd.shape}"
        )
    n_mc = sd.shape[0]
    n_swing = swing.intercept_samples.shape[0]
    # Deterministic bootstrap of swing draws — seed in fit_and_predict
    # propagates here via the caller passing a seeded rng would be ideal,
    # but for testability we use a fixed mapping over MC samples.
    idx = np.arange(n_mc) % n_swing
    intercept = swing.intercept_samples[idx]
    beta_sd = swing.beta_share_diff_samples[idx]
    beta_inc = swing.beta_incumbent_diff_samples[idx]
    logits = intercept + beta_sd * sd + beta_inc * incd
    # numerically stable sigmoid
    return 1.0 / (1.0 + np.exp(-logits))


# ---------------------------------------------------------------------------
# Monte Carlo summary — top-two pairs + per-candidate probabilities
# ---------------------------------------------------------------------------


def _per_candidate_summary(
    *,
    candidate_inputs: Sequence[CandidateInput],
    first_round_samples: Any,
    top1_idx: Any,
    top2_idx: Any,
) -> tuple[CandidatePosterior, ...]:
    """Build the per-candidate ADR-014 summary from MC sample arrays.

    ``top1_idx`` and ``top2_idx`` are ndarrays of shape ``(n_mc,)`` carrying
    the column index of the first- and second-place candidate per sample.
    """
    import numpy as np  # noqa: PLC0415

    n_mc, n_candidates = first_round_samples.shape
    posteriors: list[CandidatePosterior] = []
    for j, ci in enumerate(candidate_inputs):
        col = first_round_samples[:, j]
        quantiles = {
            float(lvl): float(np.quantile(col, lvl)) for lvl in QUANTILE_LEVELS
        }
        # Outright round-1 win when the candidate has > 50% AND is top-1.
        outright = float(
            np.mean((top1_idx == j) & (col > 0.5))
        )
        qualifies = float(np.mean((top1_idx == j) | (top2_idx == j)))
        posteriors.append(
            CandidatePosterior(
                candidate_id=ci.candidate_id,
                name=ci.name,
                party_id=ci.party_id,
                party_name=ci.party_name,
                wikidata_qid=ci.wikidata_qid,
                vote_share_quantiles=quantiles,
                win_probability_round1=outright,
                qualifies_for_runoff_probability=qualifies,
            )
        )
    return tuple(posteriors)


def _build_runoff_matrix(
    *,
    candidate_inputs: Sequence[CandidateInput],
    top1_idx: Any,
    top2_idx: Any,
    win_a_prob: Any,
) -> tuple[RunoffMatrixEntry, ...]:
    """Aggregate per-sample (top1, top2, P(A wins)) into matrix entries.

    Every sample contributes to exactly one (a, b) pair, so the sum of all
    ``pair_probability`` entries is 1.0 by construction (ADR-013 C5).
    """
    import numpy as np  # noqa: PLC0415

    n_mc = top1_idx.shape[0]
    cand_ids = [ci.candidate_id for ci in candidate_inputs]
    # Group samples by (top1, top2) pair via stable counts + accumulators.
    pair_counts: dict[tuple[int, int], int] = {}
    pair_win_sums: dict[tuple[int, int], float] = {}
    for s in range(n_mc):
        key = (int(top1_idx[s]), int(top2_idx[s]))
        pair_counts[key] = pair_counts.get(key, 0) + 1
        pair_win_sums[key] = pair_win_sums.get(key, 0.0) + float(win_a_prob[s])

    entries: list[RunoffMatrixEntry] = []
    # Stable ordering — by descending pair probability, breaking ties on
    # (top1, top2) so the test output is deterministic.
    for key, count in sorted(
        pair_counts.items(), key=lambda kv: (-kv[1], kv[0])
    ):
        a_col, b_col = key
        prob = count / n_mc
        win_a = pair_win_sums[key] / count
        entries.append(
            RunoffMatrixEntry(
                a_candidate_id=cand_ids[a_col],
                b_candidate_id=cand_ids[b_col],
                pair_probability=float(prob),
                winner_a_probability=float(np.clip(win_a, 0.0, 1.0)),
            )
        )
    return tuple(entries)


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------


def fit_and_predict(
    *,
    aggregator_posterior: AggregatorPosterior,
    fundamentals_coefs: FundamentalsCoefficients,
    candidate_inputs: Sequence[CandidateInput],
    runoff_history: Sequence[RunoffHistoryRow],
    poll_weight: float = 0.7,
    n_monte_carlo: int = 10_000,
    runoff_draws: int = 4000,
    runoff_tune: int = 2000,
    runoff_chains: int = 4,
    target_accept: float = 0.95,
    seed: int = 17,
    rhat_threshold: float = 1.01,
    ess_threshold: float = 400.0,
    runoff_swing: RunoffSwingModel | None = None,
) -> PresidentialPosterior:
    """Combine polls + fundamentals into the ADR-014 presidential payload.

    Workflow:

    1. Combine the aggregator final-day posterior and the fundamentals
       predictive into ``n_monte_carlo`` softmax-normalised first-round share
       draws (logit-scale blend, weighted by ``poll_weight``).
    2. Fit (or accept a pre-fit) Bayesian logistic runoff swing model on
       ``runoff_history``.
    3. For each MC sample, identify top-two; evaluate the swing model's
       ``P(A wins runoff | first-round)`` against one swing posterior draw.
    4. Aggregate to per-candidate quantiles + per-pair runoff matrix.

    ``poll_weight`` defaults to 0.7 — polls carry most of the late-cycle
    signal in Guatemalan presidential races but the fundamentals layer is a
    meaningful prior, especially for candidates with sparse polling. The
    weight can be moved by the calibration gate (#36) and recorded in
    ``methodology.presidential.poll_weight``.

    Per ADR-013 C5 the runoff matrix's ``pair_probability`` entries sum to
    1.0 ± 1e-6 and every ``winner_a_probability`` lies in ``[0, 1]``. Per
    ADR-013 C6 every monitored quantity has ``r_hat < 1.01`` and
    ``bulk_ess > 400``; failures raise :class:`SamplingDiagnosticsError`.

    Passing ``runoff_swing`` (pre-fit) skips the runoff fit — used by the
    calibration gate (#36) and any backtest that wants to fix the swing
    layer across re-fits of the first-round combination.
    """
    import numpy as np  # noqa: PLC0415

    if len(candidate_inputs) < 2:
        raise ValueError(
            f"need at least 2 candidates, got {len(candidate_inputs)}"
        )

    first_round_samples = _combine_first_round_samples(
        aggregator_posterior=aggregator_posterior,
        fundamentals_coefs=fundamentals_coefs,
        candidate_inputs=candidate_inputs,
        poll_weight=poll_weight,
        n_monte_carlo=n_monte_carlo,
        seed=seed,
    )

    if runoff_swing is None:
        runoff_swing = fit_runoff_swing(
            runoff_history,
            draws=runoff_draws,
            tune=runoff_tune,
            chains=runoff_chains,
            target_accept=target_accept,
            seed=seed,
            rhat_threshold=rhat_threshold,
            ess_threshold=ess_threshold,
        )

    # Identify top-two per sample. argpartition is O(n) and we only need the
    # top-two ordering, so sort the last two indices.
    order = np.argsort(first_round_samples, axis=1)  # ascending
    top1_idx = order[:, -1]
    top2_idx = order[:, -2]
    n_mc = first_round_samples.shape[0]
    a_share = first_round_samples[np.arange(n_mc), top1_idx]
    b_share = first_round_samples[np.arange(n_mc), top2_idx]
    share_diff = a_share - b_share

    incumbent_flags = np.array(
        [
            bool(
                ci.feature_vector is not None
                and ci.feature_vector.incumbent_party
            )
            for ci in candidate_inputs
        ],
        dtype=int,
    )
    incumbent_a = incumbent_flags[top1_idx]
    incumbent_b = incumbent_flags[top2_idx]
    incumbent_diff = incumbent_a - incumbent_b

    win_a_prob = runoff_win_probability_samples(
        runoff_swing,
        share_diff=share_diff,
        incumbent_diff=incumbent_diff,
    )

    candidates = _per_candidate_summary(
        candidate_inputs=candidate_inputs,
        first_round_samples=first_round_samples,
        top1_idx=top1_idx,
        top2_idx=top2_idx,
    )
    runoff_matrix = _build_runoff_matrix(
        candidate_inputs=candidate_inputs,
        top1_idx=top1_idx,
        top2_idx=top2_idx,
        win_a_prob=win_a_prob,
    )

    return PresidentialPosterior(
        candidates=candidates,
        runoff_matrix=runoff_matrix,
        first_round_samples=first_round_samples,
        n_monte_carlo=n_mc,
        max_r_hat=runoff_swing.max_r_hat,
        min_bulk_ess=runoff_swing.min_bulk_ess,
    )


__all__ = [
    "QUANTILE_LEVELS",
    "CandidateInput",
    "CandidatePosterior",
    "PresidentialPosterior",
    "RunoffHistoryRow",
    "RunoffMatrixEntry",
    "RunoffSwingModel",
    "SamplingDiagnosticsError",
    "fit_and_predict",
    "fit_runoff_swing",
    "runoff_win_probability_samples",
]
