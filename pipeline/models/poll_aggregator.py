"""Linzer / Kremp state-space poll aggregator (issue #30, ADR-017).

Implements the Section C step 1 reference model in ``docs/requirement.md``
for the Guatemalan presidential first round:

* Latent national vote share per candidate ``j`` follows a Gaussian
  random walk on a daily grid spanning the polling window.
* Each observed poll is treated as a noisy measurement of the latent
  share *shifted by the pollster's historical bias* and *with the
  pollster's per-poll noise scale added to the binomial SE in
  quadrature*:

      observed_share_ij ~ Normal(
          true_share_{j, t_i} + bias_pi,
          sqrt(poll_se_ij**2 + sigma_pi**2)
      )

  Both ``bias_pi`` and ``sigma_pi`` are read from
  ``pollsters.historical_bias_mean`` / ``historical_bias_sd`` (estimated
  in issue #29) and treated as fixed inputs — see
  ``docs/methodology/pollster_bias.md`` for the rationale (the pollster
  fit upstream is the prior; the aggregator does not re-fit the bias).

The diffuse default ``(mean=0, sd=0.05)`` from the migration 0004 seed
is the cold-start used for any pollster whose historical fit has not
yet run (``sample_count_used = 0``).

Public surface
--------------

``fit(polls, pollsters, candidates, ...) -> AggregatorPosterior``
    Single entry point. Sequences of typed dataclasses keep the
    interface stable across DataFrame backends; ``read_polls`` and
    ``read_pollster_priors`` are the DB helpers that emit them.

PyMC sampler config matches the project's Operational Commitments
(4 chains, 2000 warmup, 4000 draws, ``target_accept=0.95``, seed=17)
and ADR-013's C6 calibration gate (``r_hat < 1.01``,
``bulk_ess > 400``). A diagnostics failure raises
:class:`SamplingDiagnosticsError` rather than emit a broken posterior.

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
# error type across the modelling pipeline (#29 → #30 → #32).
from pipeline.scripts.estimate_pollster_bias import SamplingDiagnosticsError

# Default per-poll standard error used when neither sample_size nor
# margin_of_error is recorded. ~0.03 is the binomial SE for a typical
# Guatemalan national poll (n≈1100, p≈0.2): sqrt(0.2*0.8/1100) ≈ 0.012,
# inflated to 0.03 to account for design effects + clustering on
# stratified samples. Better-than-nothing fallback; the loader logs a
# warning when this path is taken.
DEFAULT_POLL_SE = 0.03

# Diffuse default per ADR-017 / migration 0004_polls.sql seed. Used as
# the cold-start when a pollster has no historical fit yet.
DIFFUSE_BIAS_MEAN = 0.0
DIFFUSE_BIAS_SD = 0.05


# ---------------------------------------------------------------------------
# Public dataclasses
# ---------------------------------------------------------------------------


@dataclasses.dataclass(frozen=True)
class CandidateRef:
    """Identity row for a candidate the aggregator tracks."""

    candidate_id: int
    full_name: str


@dataclasses.dataclass(frozen=True)
class PollsterPrior:
    """House-effect prior for one pollster (from #29's estimator)."""

    pollster_id: int
    name: str
    bias_mean: float
    bias_sd: float
    sample_count_used: int = 0

    @property
    def is_diffuse(self) -> bool:
        """True when the pollster row is still the migration seed default."""
        return self.sample_count_used == 0


@dataclasses.dataclass(frozen=True)
class PollObservation:
    """One observed (poll, candidate) row consumed by the aggregator.

    ``poll_se`` is the binomial standard error derived from
    ``sample_size`` (``sqrt(p*(1-p)/n)``) when available, falling back
    to ``margin_of_error / 1.96`` then to :data:`DEFAULT_POLL_SE`. The
    aggregator adds it in quadrature with the pollster's ``bias_sd``.
    """

    poll_id: int
    pollster_id: int
    candidate_id: int
    field_end: date
    share: float
    poll_se: float

    def __post_init__(self) -> None:
        if not 0.0 <= self.share <= 1.0:
            raise ValueError(f"share must be in [0,1], got {self.share}")
        if self.poll_se <= 0.0:
            raise ValueError(f"poll_se must be > 0, got {self.poll_se}")


@dataclasses.dataclass(frozen=True)
class AggregatorPosterior:
    """Daily posterior over candidate vote shares.

    ``samples`` is a ``(n_samples, n_days, n_candidates)`` ndarray of
    posterior draws (chains × draws stacked). ``days`` and
    ``candidates`` index the second and third axes respectively. The
    final-day slice ``samples[:, -1, :]`` is the canonical "now-cast"
    used by the presidential combiner (#32).
    """

    samples: Any  # numpy.ndarray, kept loose to avoid hard import
    days: tuple[date, ...]
    candidates: tuple[CandidateRef, ...]
    max_r_hat: float
    min_bulk_ess: float
    n_observations: int

    def final_day_quantiles(
        self, levels: Sequence[float] = (0.05, 0.1, 0.25, 0.5, 0.75, 0.9, 0.95)
    ) -> dict[int, dict[float, float]]:
        """Quantile table at the latest day, keyed by candidate_id.

        Layout matches the ADR-014 payload contract (p05/p10/.../p95) so
        the forecast writer (#33) can consume it directly without
        reshaping.
        """
        import numpy as np  # noqa: PLC0415

        final = np.asarray(self.samples)[:, -1, :]  # (S, J)
        out: dict[int, dict[float, float]] = {}
        for j, cand in enumerate(self.candidates):
            qs = np.quantile(final[:, j], list(levels))
            out[cand.candidate_id] = {
                float(lvl): float(q) for lvl, q in zip(levels, qs, strict=True)
            }
        return out

    def final_day_ci_covers(
        self,
        actuals: dict[int, float],
        *,
        level: float = 0.80,
    ) -> dict[int, bool]:
        """Return whether the final-day CI at ``level`` contains the actual.

        ``actuals`` maps ``candidate_id`` to the observed vote share.
        Returned dict is keyed by ``candidate_id`` -> covered flag.
        Missing candidates raise to surface caller bugs early.
        """
        import numpy as np  # noqa: PLC0415

        alpha = (1.0 - level) / 2.0
        final = np.asarray(self.samples)[:, -1, :]
        out: dict[int, bool] = {}
        for j, cand in enumerate(self.candidates):
            if cand.candidate_id not in actuals:
                raise KeyError(f"no actual for candidate_id={cand.candidate_id}")
            lo, hi = np.quantile(final[:, j], [alpha, 1.0 - alpha])
            actual = actuals[cand.candidate_id]
            out[cand.candidate_id] = bool(lo <= actual <= hi)
        return out


# ---------------------------------------------------------------------------
# Helpers — derive a poll SE from sample_size / margin_of_error / fallback
# ---------------------------------------------------------------------------


def compute_poll_se(
    share: float,
    *,
    sample_size: int | None = None,
    margin_of_error: float | None = None,
    fallback: float = DEFAULT_POLL_SE,
) -> float:
    """Derive a per-poll standard error for the aggregator.

    Preference order: binomial SE from sample_size → MOE/1.96 → fallback.
    The fallback path is hit by hand-entered legacy polls where neither
    sample_size nor MOE was recorded.
    """
    if sample_size is not None and sample_size > 0:
        # Binomial SE under simple random sampling. Design effects
        # (clustering, stratification) are folded into the pollster's
        # `sigma_i` (added in quadrature by the aggregator) so this is
        # the right starting point even for stratified national samples.
        clipped = min(max(share, 1e-4), 1.0 - 1e-4)
        se = math.sqrt(clipped * (1.0 - clipped) / sample_size)
        return max(se, 1e-4)
    if margin_of_error is not None and margin_of_error > 0:
        # MOE is reported at 95% CI by convention in Guatemalan polls.
        return max(margin_of_error / 1.959963984540054, 1e-4)
    return fallback


# ---------------------------------------------------------------------------
# DB I/O — read polls + pollster priors for a given cycle
# ---------------------------------------------------------------------------


def read_pollster_priors(conn: Any) -> list[PollsterPrior]:
    """Read every row from ``pollsters`` as a :class:`PollsterPrior`.

    The result is ordered by ``pollster_id`` so callers can build a
    stable lookup; missing rows in the polls slice are NOT pruned here
    — the aggregator may need the diffuse default for a pollster who
    has not yet appeared in the live polls table for the current cycle.
    """
    sql = """
        SELECT pollster_id, name, historical_bias_mean,
               historical_bias_sd, sample_count_used
          FROM pollsters
         ORDER BY pollster_id
    """
    with conn.cursor() as cur:
        cur.execute(sql)
        rows = cur.fetchall()
    return [
        PollsterPrior(
            pollster_id=int(r[0]),
            name=str(r[1]),
            bias_mean=float(r[2]),
            bias_sd=float(r[3]),
            sample_count_used=int(r[4]),
        )
        for r in rows
    ]


def read_polls(
    conn: Any,
    *,
    cycle: int,
    candidate_ids: Sequence[int] | None = None,
) -> list[PollObservation]:
    """Read poll observations for a cycle.

    A poll belongs to ``cycle`` when its ``field_end`` falls in the year.
    For Guatemala the first round is in late June, so polls fielded in
    Jan–Jun of the election year are the in-cycle set the aggregator
    fits against (the same window is used by the #29 backtest variant).
    """
    params: list[Any] = [cycle]
    cand_clause = ""
    if candidate_ids is not None:
        cand_clause = "AND pr.candidate_id = ANY(%s)"
        params.append(list(candidate_ids))
    sql = f"""
        SELECT p.poll_id, p.pollster_id, pr.candidate_id,
               p.field_end, pr.share, p.sample_size, pr.margin_of_error
          FROM poll_responses AS pr
          JOIN polls         AS p ON p.poll_id = pr.poll_id
         WHERE EXTRACT(YEAR FROM p.field_end) = %s
               {cand_clause}
         ORDER BY p.field_end, p.poll_id, pr.candidate_id
    """
    with conn.cursor() as cur:
        cur.execute(sql, tuple(params))
        rows = cur.fetchall()
    out: list[PollObservation] = []
    for r in rows:
        share = float(r[4])
        se = compute_poll_se(
            share,
            sample_size=int(r[5]) if r[5] is not None else None,
            margin_of_error=float(r[6]) if r[6] is not None else None,
        )
        out.append(
            PollObservation(
                poll_id=int(r[0]),
                pollster_id=int(r[1]),
                candidate_id=int(r[2]),
                field_end=r[3],
                share=share,
                poll_se=se,
            )
        )
    return out


# ---------------------------------------------------------------------------
# PyMC state-space fit
# ---------------------------------------------------------------------------


def _build_lookups(
    polls: Sequence[PollObservation],
    pollsters: Sequence[PollsterPrior],
    candidates: Sequence[CandidateRef],
) -> tuple[dict[int, int], dict[int, int], tuple[date, ...]]:
    """Build (pollster_id→idx, candidate_id→idx, sorted days) lookups.

    Validates that every poll references a pollster and a candidate the
    caller declared. The day grid is the dense daily index from the
    earliest to the latest ``field_end`` across the input polls.
    """
    pollster_idx = {p.pollster_id: i for i, p in enumerate(pollsters)}
    candidate_idx = {c.candidate_id: i for i, c in enumerate(candidates)}

    missing_pollsters = {
        p.pollster_id for p in polls if p.pollster_id not in pollster_idx
    }
    if missing_pollsters:
        raise ValueError(
            f"polls reference unknown pollster_ids={sorted(missing_pollsters)}"
        )
    missing_candidates = {
        p.candidate_id for p in polls if p.candidate_id not in candidate_idx
    }
    if missing_candidates:
        raise ValueError(
            f"polls reference unknown candidate_ids={sorted(missing_candidates)}"
        )

    field_ends = sorted({p.field_end for p in polls})
    first = field_ends[0]
    last = field_ends[-1]
    span_days = (last - first).days + 1
    days = tuple(
        date.fromordinal(first.toordinal() + offset) for offset in range(span_days)
    )
    return pollster_idx, candidate_idx, days


def fit(
    polls: Sequence[PollObservation],
    pollsters: Sequence[PollsterPrior],
    candidates: Sequence[CandidateRef],
    *,
    draws: int = 4000,
    tune: int = 2000,
    chains: int = 4,
    target_accept: float = 0.95,
    seed: int = 17,
    rhat_threshold: float = 1.01,
    ess_threshold: float = 400.0,
    walk_sigma_prior: float = 0.02,
) -> AggregatorPosterior:
    """Fit the Linzer/Kremp state-space model and return the posterior.

    ``walk_sigma_prior`` is the HalfNormal scale for the latent
    random-walk step size — 2pp/day is well above the realistic drift
    rate for a national vote share but loose enough that fast late-cycle
    movement (like Arévalo's 2023 surge) can be recovered by the model.
    """
    if not polls:
        raise ValueError("no polls to fit")
    if not candidates:
        raise ValueError("no candidates declared")
    if not pollsters:
        raise ValueError("no pollster priors provided")

    try:
        import arviz as az  # noqa: PLC0415
        import numpy as np  # noqa: PLC0415
        import pymc as pm  # noqa: PLC0415
    except ImportError as exc:  # pragma: no cover - exercised when extra missing
        raise RuntimeError(
            "PyMC not installed. Install with `uv sync --extra modelling`."
        ) from exc

    pollster_idx, candidate_idx, days = _build_lookups(polls, pollsters, candidates)
    n_candidates = len(candidates)
    n_days = len(days)
    n_obs = len(polls)

    first_day = days[0]
    obs_day = np.array(
        [(p.field_end - first_day).days for p in polls], dtype=int
    )
    obs_cand = np.array(
        [candidate_idx[p.candidate_id] for p in polls], dtype=int
    )
    obs_share = np.array([p.share for p in polls], dtype=float)
    obs_se = np.array([p.poll_se for p in polls], dtype=float)
    # Bias / sigma per observation come from the stored prior — the
    # aggregator does NOT re-fit them. ADR-017: the pollster bias
    # estimator (#29) is the prior; this layer just plugs it in.
    bias_per_obs = np.array(
        [pollsters[pollster_idx[p.pollster_id]].bias_mean for p in polls],
        dtype=float,
    )
    sigma_per_obs = np.array(
        [pollsters[pollster_idx[p.pollster_id]].bias_sd for p in polls],
        dtype=float,
    )
    # Per ADR-017 the per-poll noise scale is added in quadrature with
    # the binomial SE — the pollster's house-effect noise compounds the
    # sampling noise rather than replacing it.
    total_sigma_obs = np.sqrt(obs_se**2 + sigma_per_obs**2)

    coords = {
        "candidate": [c.full_name for c in candidates],
        "day": [d.isoformat() for d in days],
    }

    with pm.Model(coords=coords):
        # Vague initial-share prior — vote share in [0,1] but a Normal
        # is preferred over a beta/Dirichlet here because (i) it
        # matches the Linzer/Kremp formulation directly and (ii) it
        # keeps the model conjugate-friendly for NUTS. Posterior
        # samples may stray <0 / >1 in theory but in practice the
        # data pin them inside the simplex.
        init_share = pm.Normal(
            "init_share", mu=0.2, sigma=0.2, dims="candidate"
        )
        # Daily walk variance — small and HalfNormal. Larger values
        # produce noisy, over-fitted posteriors; smaller ones
        # over-smooth a fast surge.
        sigma_walk = pm.HalfNormal("sigma_walk", sigma=walk_sigma_prior)
        # Non-centered RW: avoid a tau funnel as n_days grows. step_offset
        # is N(0,1) per (candidate, day-1); the actual step is
        # sigma_walk * step_offset. Cumsum reconstructs the latent path.
        if n_days > 1:
            step_offset = pm.Normal(
                "step_offset",
                mu=0.0,
                sigma=1.0,
                shape=(n_candidates, n_days - 1),
            )
            steps = sigma_walk * step_offset  # (J, T-1)
            walk_cumsum = pm.math.concatenate(
                [
                    pm.math.zeros((n_candidates, 1)),
                    pm.math.cumsum(steps, axis=1),
                ],
                axis=1,
            )  # (J, T)
        else:
            walk_cumsum = pm.math.zeros((n_candidates, 1))
        # true_share[j, t] = init_share[j] + cumulative walk
        true_share = pm.Deterministic(
            "true_share",
            init_share[:, None] + walk_cumsum,
            dims=("candidate", "day"),
        )

        # Each obs sees the latent share + the *fixed* pollster bias.
        mu_obs = true_share[obs_cand, obs_day] + bias_per_obs
        pm.Normal(
            "obs",
            mu=mu_obs,
            sigma=total_sigma_obs,
            observed=obs_share,
        )

        trace = pm.sample(
            draws=draws,
            tune=tune,
            chains=chains,
            target_accept=target_accept,
            random_seed=seed,
            progressbar=False,
            compute_convergence_checks=False,
        )

    # Gate on every monitored quantity — `true_share` is the only
    # quantity downstream consumers care about, but if `init_share`
    # / `sigma_walk` / `step_offset` mix badly the posterior is
    # untrustworthy too. ADR-013 C6.
    summary = az.summary(
        trace,
        var_names=["init_share", "sigma_walk", "true_share"]
        + (["step_offset"] if n_days > 1 else []),
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

    # Stack (chain, draw) into a single sample axis. Resulting shape:
    # (n_samples, n_days, n_candidates) — that's the layout the forecast
    # writer (#33) expects for the quantile payload.
    posterior_share = (
        trace.posterior["true_share"]
        .stack(sample=("chain", "draw"))
        .transpose("sample", "day", "candidate")
        .values
    )

    return AggregatorPosterior(
        samples=posterior_share,
        days=days,
        candidates=tuple(candidates),
        max_r_hat=max_rhat,
        min_bulk_ess=min_ess,
        n_observations=n_obs,
    )


__all__ = [
    "DEFAULT_POLL_SE",
    "DIFFUSE_BIAS_MEAN",
    "DIFFUSE_BIAS_SD",
    "AggregatorPosterior",
    "CandidateRef",
    "PollObservation",
    "PollsterPrior",
    "SamplingDiagnosticsError",
    "compute_poll_se",
    "fit",
    "read_polls",
    "read_pollster_priors",
]
