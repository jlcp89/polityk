"""Pollster house-effects estimator per ADR-017 / issue #29.

After truth lands for a cycle, fits a hierarchical normal model

    error_ij  ~  Normal(bias_i, sigma_i)
    bias_i    ~  Normal(mu_bias, tau_bias)        # partial pooling
    sigma_i   ~  HalfNormal(sigma_scale)
    mu_bias   ~  Normal(0, 0.1)
    tau_bias  ~  HalfNormal(0.1)

over the `poll_errors` rows for a given cycle, then writes posterior
``mean`` / ``sd`` / sample-count / timestamp back to the ``pollsters``
table.

Usage
-----

    DATABASE_URL=postgres://... \\
        uv run python -m pipeline.scripts.estimate_pollster_bias \\
        --cycles 2007 2011 2015 2019 2023 \\
        [--draws 4000] [--tune 2000] [--chains 4] \\
        [--seed 17] [--rhat-threshold 1.01] [--dry-run]

Idempotent: re-running for the same cycles with the same data yields the
same ``historical_bias_mean`` / ``historical_bias_sd`` posteriors (PyMC
seed is fixed by `--seed`) and overwrites the same row, so the
``UPDATE`` is a no-op when nothing has changed. ``--dry-run`` skips the
write step and prints the fitted estimates.

PyMC NUTS config follows the project's Operational Commitments
(4 chains × 2000 warmup × 4000 samples × target_accept=0.95) and the
ADR-013 calibration gate (``r_hat < 1.01``, ``bulk_ess > 400``). A
divergent fit raises :class:`SamplingDiagnosticsError` so the caller
(CI gate, cron job) can fail loudly instead of writing a bad prior.
"""

from __future__ import annotations

import argparse
import dataclasses
import logging
import math
import os
import sys
from collections.abc import Iterable, Sequence
from datetime import UTC, datetime
from typing import Any

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Public dataclasses
# ---------------------------------------------------------------------------


@dataclasses.dataclass(frozen=True)
class PollErrorRow:
    """One row from ``poll_errors`` consumed by the estimator."""

    pollster_id: int
    pollster_name: str
    cycle: int
    candidate_id: int
    poll_prediction: float
    actual_result: float

    @property
    def error(self) -> float:
        """Signed prediction error (matches the DB GENERATED column)."""
        return self.poll_prediction - self.actual_result


@dataclasses.dataclass(frozen=True)
class PollsterEstimate:
    """Posterior summary written back to ``pollsters``."""

    pollster_id: int
    pollster_name: str
    historical_bias_mean: float
    historical_bias_sd: float
    sample_count_used: int
    r_hat_bias: float
    bulk_ess_bias: float


@dataclasses.dataclass(frozen=True)
class FitResult:
    """Output of :func:`fit_pollster_bias` — per-pollster estimates plus diag."""

    estimates: tuple[PollsterEstimate, ...]
    max_r_hat: float
    min_bulk_ess: float
    n_observations: int
    n_pollsters: int


class SamplingDiagnosticsError(RuntimeError):
    """Raised when the PyMC NUTS diagnostics gate (``r_hat``, ESS) fails.

    Carries the offending statistic so the CI gate can log it without
    re-running diagnostics.
    """


class NoPollErrorsError(RuntimeError):
    """Raised when no ``poll_errors`` rows are available for the request.

    Distinct from a sampling failure so the CLI can exit cleanly with a
    helpful message rather than try to fit an empty model.
    """


# ---------------------------------------------------------------------------
# DB I/O — read poll_errors, write pollsters
# ---------------------------------------------------------------------------


def read_poll_errors(conn: Any, cycles: Sequence[int]) -> list[PollErrorRow]:
    """Read every ``poll_errors`` row for the requested cycles.

    The join against ``pollsters`` carries the pollster name so the
    estimator can log human-readable per-pollster posteriors without a
    second roundtrip. Ordered by ``pollster_id, cycle, candidate_id`` so
    the input matrix is stable across runs (NUTS seed alone is not
    sufficient — observation order also matters for reproducibility).
    """
    if not cycles:
        return []
    sql = """
        SELECT pe.pollster_id, p.name, pe.cycle, pe.candidate_id,
               pe.poll_prediction, pe.actual_result
        FROM poll_errors AS pe
        JOIN pollsters    AS p ON p.pollster_id = pe.pollster_id
        WHERE pe.cycle = ANY(%s)
        ORDER BY pe.pollster_id, pe.cycle, pe.candidate_id
    """
    with conn.cursor() as cur:
        cur.execute(sql, (list(cycles),))
        rows = cur.fetchall()
    return [
        PollErrorRow(
            pollster_id=int(r[0]),
            pollster_name=str(r[1]),
            cycle=int(r[2]),
            candidate_id=int(r[3]),
            poll_prediction=float(r[4]),
            actual_result=float(r[5]),
        )
        for r in rows
    ]


def write_pollster_estimates(
    conn: Any,
    estimates: Iterable[PollsterEstimate],
    *,
    now: datetime | None = None,
) -> int:
    """Write posterior mean/sd/sample-count back to ``pollsters``.

    Returns the number of rows updated. Idempotent: re-running with the
    same estimates is a no-op modulo ``bias_last_estimated_at``, which
    the issue acceptance criterion explicitly requires to update on each
    run (so operators can confirm a run actually happened).
    """
    stamp = now if now is not None else datetime.now(tz=UTC)
    n = 0
    with conn.cursor() as cur:
        for est in estimates:
            cur.execute(
                """
                UPDATE pollsters
                   SET historical_bias_mean    = %s,
                       historical_bias_sd      = %s,
                       sample_count_used       = %s,
                       bias_last_estimated_at  = %s
                 WHERE pollster_id = %s
                """,
                (
                    est.historical_bias_mean,
                    est.historical_bias_sd,
                    est.sample_count_used,
                    stamp,
                    est.pollster_id,
                ),
            )
            n += cur.rowcount
    return n


# ---------------------------------------------------------------------------
# PyMC hierarchical normal fit
# ---------------------------------------------------------------------------


def fit_pollster_bias(
    rows: Sequence[PollErrorRow],
    *,
    draws: int = 4000,
    tune: int = 2000,
    chains: int = 4,
    target_accept: float = 0.95,
    seed: int = 17,
    rhat_threshold: float = 1.01,
    ess_threshold: float = 400.0,
) -> FitResult:
    """Fit the hierarchical bias model and return per-pollster posteriors.

    The PyMC import is deferred so the wider Python pipeline can be
    imported (and unit-tested) without the heavy ``pymc`` extra. The
    function raises a friendly error when the extra is missing.

    Diagnostics gate
    ----------------
    Every monitored quantity (``mu_bias``, ``tau_bias``, per-pollster
    ``bias`` and ``sigma``) must satisfy ``r_hat < rhat_threshold`` and
    ``bulk_ess > ess_threshold`` — failure raises
    :class:`SamplingDiagnosticsError`. This is the C6 leg of ADR-013's
    calibration gate.
    """
    if not rows:
        raise NoPollErrorsError("no poll_errors rows to fit")

    try:
        import arviz as az  # noqa: PLC0415
        import numpy as np  # noqa: PLC0415
        import pymc as pm  # noqa: PLC0415
    except ImportError as exc:  # pragma: no cover - exercised when extra missing
        raise RuntimeError("PyMC not installed. Install with `uv sync --extra modelling`.") from exc

    # Stable pollster ordering: by first-seen pollster_id.
    seen_ids: list[int] = []
    name_by_id: dict[int, str] = {}
    for r in rows:
        if r.pollster_id not in name_by_id:
            seen_ids.append(r.pollster_id)
            name_by_id[r.pollster_id] = r.pollster_name
    pollster_index = {pid: idx for idx, pid in enumerate(seen_ids)}

    errors = np.array([r.error for r in rows], dtype=float)
    pollster_idx = np.array([pollster_index[r.pollster_id] for r in rows], dtype=int)
    sample_counts = {pid: 0 for pid in seen_ids}
    for r in rows:
        sample_counts[r.pollster_id] += 1

    n_pollsters = len(seen_ids)

    # Non-centered parameterization for `bias`: avoids the classic funnel
    # in `tau_bias` when group counts are small (Betancourt 2017,
    # "Diagnosing Biased Inference with Divergences"). Without this, fits
    # with <=3 pollsters routinely fail the r_hat<1.01 gate.
    coords = {"pollster": [name_by_id[pid] for pid in seen_ids]}
    with pm.Model(coords=coords):
        mu_bias = pm.Normal("mu_bias", mu=0.0, sigma=0.1)
        tau_bias = pm.HalfNormal("tau_bias", sigma=0.1)
        bias_offset = pm.Normal("bias_offset", mu=0.0, sigma=1.0, dims="pollster")
        bias = pm.Deterministic("bias", mu_bias + tau_bias * bias_offset, dims="pollster")
        # `sigma_i` prior wide enough to admit the ADR-017 documented
        # widening to ~0.10-0.15 when the data demands it. A Normal
        # observation likelihood (rather than Student-t) is deliberate:
        # the goal is for a pollster with chaotic errors to grow a
        # large sigma_i so the aggregator down-weights it, which a
        # heavy-tailed likelihood would defeat by absorbing outliers
        # in the tails.
        sigma = pm.HalfNormal("sigma", sigma=0.1, dims="pollster")
        pm.Normal(
            "obs",
            mu=bias[pollster_idx],
            sigma=sigma[pollster_idx],
            observed=errors,
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

    summary = az.summary(trace, var_names=["mu_bias", "tau_bias", "bias", "sigma"])
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

    posterior = trace.posterior
    # Per-pollster summaries. We write back:
    #   historical_bias_mean = posterior mean of bias_i
    #   historical_bias_sd   = posterior mean of sigma_i (the per-poll
    #                          noise scale).
    # The aggregator (#30, ADR-017) consumes these as:
    #       observed_share_ij ~ Normal(true_share_j + bias_i,
    #                                  poll_se_ij + sigma_i)
    # so historical_bias_sd must be the per-poll noise the aggregator
    # adds in quadrature, not the (much narrower) posterior SD of the
    # mean bias. This is also why ADR-017 expects ProDatos' sd to
    # *widen* on the 2023 evidence (a more chaotic pollster has bigger
    # sigma_i); the posterior SD of bias_i would shrink with more data,
    # not widen.
    bias_arr = posterior["bias"].stack(sample=("chain", "draw")).values  # (P, S)
    sigma_arr = posterior["sigma"].stack(sample=("chain", "draw")).values  # (P, S)
    bias_means = bias_arr.mean(axis=1)
    sigma_means = sigma_arr.mean(axis=1)

    estimates: list[PollsterEstimate] = []
    bias_summary = summary.loc[
        [f"bias[{name_by_id[pid]}]" for pid in seen_ids],
        ["r_hat", "ess_bulk"],
    ]
    for i, pid in enumerate(seen_ids):
        estimates.append(
            PollsterEstimate(
                pollster_id=pid,
                pollster_name=name_by_id[pid],
                historical_bias_mean=float(bias_means[i]),
                historical_bias_sd=float(sigma_means[i]),
                sample_count_used=sample_counts[pid],
                r_hat_bias=float(bias_summary.iloc[i]["r_hat"]),
                bulk_ess_bias=float(bias_summary.iloc[i]["ess_bulk"]),
            )
        )

    return FitResult(
        estimates=tuple(estimates),
        max_r_hat=max_rhat,
        min_bulk_ess=min_ess,
        n_observations=len(rows),
        n_pollsters=n_pollsters,
    )


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="estimate_pollster_bias",
        description=(
            "Fit the ADR-017 hierarchical pollster-bias model on poll_errors "
            "for the requested cycles and write posterior mean/sd back to "
            "the pollsters table."
        ),
    )
    parser.add_argument(
        "--cycles",
        type=int,
        nargs="+",
        required=True,
        help="Election cycles to include (e.g. --cycles 2007 2011 2015 2019 2023)",
    )
    parser.add_argument("--draws", type=int, default=4000, help="Post-warmup draws per chain")
    parser.add_argument("--tune", type=int, default=2000, help="NUTS warmup samples per chain")
    parser.add_argument("--chains", type=int, default=4, help="Number of parallel NUTS chains")
    parser.add_argument(
        "--target-accept",
        type=float,
        default=0.95,
        help="NUTS target acceptance rate (Operational Commitments default 0.95)",
    )
    parser.add_argument("--seed", type=int, default=17, help="Random seed (reproducibility)")
    parser.add_argument(
        "--rhat-threshold",
        type=float,
        default=1.01,
        help="Max acceptable r_hat (ADR-013 C6 default 1.01)",
    )
    parser.add_argument(
        "--ess-threshold",
        type=float,
        default=400.0,
        help="Min acceptable bulk_ess (ADR-013 C6 default 400)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Fit and print estimates but skip the UPDATE on pollsters.",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s %(message)s")
    args = _build_parser().parse_args(argv)

    dsn = os.environ.get("DATABASE_URL")
    if not dsn:
        logger.error("DATABASE_URL not set")
        return 2

    import psycopg  # noqa: PLC0415

    with psycopg.connect(dsn) as conn:
        rows = read_poll_errors(conn, args.cycles)
        if not rows:
            logger.error("no poll_errors rows for cycles=%s", args.cycles)
            return 1

        try:
            result = fit_pollster_bias(
                rows,
                draws=args.draws,
                tune=args.tune,
                chains=args.chains,
                target_accept=args.target_accept,
                seed=args.seed,
                rhat_threshold=args.rhat_threshold,
                ess_threshold=args.ess_threshold,
            )
        except SamplingDiagnosticsError as exc:
            logger.error("pollster_bias_diagnostics_failed: %s", exc)
            return 1

        for est in result.estimates:
            logger.info(
                "pollster_bias_estimate name=%s mean=%.4f sd=%.4f samples=%d r_hat=%.4f ess=%.0f",
                est.pollster_name,
                est.historical_bias_mean,
                est.historical_bias_sd,
                est.sample_count_used,
                est.r_hat_bias,
                est.bulk_ess_bias,
            )

        if args.dry_run:
            logger.info("dry_run set — skipping UPDATE on pollsters")
            return 0

        n = write_pollster_estimates(conn, result.estimates)
        conn.commit()
        logger.info("pollster_bias_write_done rows_updated=%d", n)

    return 0


__all__ = [
    "FitResult",
    "NoPollErrorsError",
    "PollErrorRow",
    "PollsterEstimate",
    "SamplingDiagnosticsError",
    "fit_pollster_bias",
    "main",
    "read_poll_errors",
    "write_pollster_estimates",
]


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
