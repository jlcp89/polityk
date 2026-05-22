"""Calibration gate (issue #36, ADR-013, Operational Commitments).

Re-runs the calibration C1-C6 gates against a forecast (#33) and either
flips ``forecasts.is_published = TRUE`` (all pass) or inserts one row per
failed gate into ``calibration_failures`` (any fail). Also covers US22
(publication audit trail).

The six gates per ADR-013:

* **C1** — 80% CI (``p10``-``p90`` per ADR-014) covers truth in ≥80% of
  (cycle × candidate) holdout pairs.
* **C2** — 95% CI (``p05``-``p95``) covers truth in ≥95% of pairs.
* **C3** — top-3 (by truth share, per cycle) median absolute error
  (``|p50 - truth|``) ≤ 5pp.
* **C4** — no NaN/Inf/all-zero quantile vectors in the production payload.
* **C5** — runoff matrix's ``pair_probability`` sums to 1.0 ± 1e-6; every
  ``pair_probability`` and ``winner_a_probability`` ∈ ``[0, 1]``.
* **C6** — every monitored quantity has ``r_hat < 1.01`` and
  ``bulk_ess > 400``.

C1/C2/C3/C6 inputs come from re-fitting #32 against the 2019 + 2023
holdouts (#19–#22 truth). C4/C5 read the production payload directly.
The library entry point :func:`evaluate_and_apply_gates` takes a
pre-built :class:`BacktestResult` so tests can synthesise the holdout
evidence without re-running PyMC; the CLI path that wires the real
backtest in is a separate ticket (the loaders for #19–#22 are out of
scope for this issue).

Idempotence: re-running on a ``run_id`` that already reflects the
computed result is a no-op — the function returns the cached pass/fail
verdict without re-issuing the UPDATE or duplicating
``calibration_failures`` rows.

Usage (library)::

    from pipeline.scripts import calibrate

    results = calibrate.evaluate_all_gates(
        payload=payload,
        backtest=backtest_result,
    )
    published = calibrate.apply_calibration_result(conn, run_id, results)
    conn.commit()
"""

from __future__ import annotations

import argparse
import dataclasses
import logging
import math
import os
import sys
import uuid
from collections.abc import Iterable, Sequence
from typing import Any, cast

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Gate names + thresholds (the wire-format values written into
# ``calibration_failures.gate``). Kept as module-level constants so the
# Go API and any downstream alerting can pin against them.
# ---------------------------------------------------------------------------

GATE_C1: str = "C1_coverage_80"
GATE_C2: str = "C2_coverage_95"
GATE_C3: str = "C3_top3_mae"
GATE_C4: str = "C4_payload_finite"
GATE_C5: str = "C5_runoff_simplex"
GATE_C6: str = "C6_diagnostics"

GATE_NAMES: tuple[str, ...] = (
    GATE_C1,
    GATE_C2,
    GATE_C3,
    GATE_C4,
    GATE_C5,
    GATE_C6,
)

C1_THRESHOLD: float = 0.80
C2_THRESHOLD: float = 0.95
C3_THRESHOLD_PP: float = 0.05
C5_THRESHOLD: float = 1e-6
C6_RHAT_THRESHOLD: float = 1.01
C6_ESS_THRESHOLD: float = 400.0


# ---------------------------------------------------------------------------
# Public dataclasses
# ---------------------------------------------------------------------------


@dataclasses.dataclass(frozen=True)
class BacktestEntry:
    """One (cycle, candidate) holdout prediction-vs-truth pair.

    ``quantiles`` carries the ADR-014 ``p05/p10/p25/p50/p75/p90/p95`` keys
    so the coverage gates (C1, C2) and the point-error gate (C3) can read
    a single bundled record per candidate.
    """

    cycle: int
    candidate_id: int
    candidate_name: str
    quantiles: dict[str, float]
    truth_share: float


@dataclasses.dataclass(frozen=True)
class BacktestResult:
    """Aggregated holdout backtest evidence consumed by C1/C2/C3/C6.

    Produced by re-fitting #32 against the 2019 + 2023 holdouts (#19-#22
    truth) with the same config as the production run. The diagnostics
    fields hold the worst-case r_hat / best-case ess from the holdout
    refit; C6 reads them directly.
    """

    entries: tuple[BacktestEntry, ...]
    max_r_hat: float
    min_bulk_ess: float


@dataclasses.dataclass(frozen=True)
class GateResult:
    """One C1-C6 evaluation outcome.

    ``observed`` and ``threshold`` are persisted into
    ``calibration_failures`` on the fail path so analysts can see *how
    badly* a gate missed without re-running the backtest.
    """

    gate: str
    passed: bool
    observed: float
    threshold: float


# ---------------------------------------------------------------------------
# Gate primitives — each returns a GateResult; never raises on bad data
# (the orchestrator must keep evaluating other gates even if one fails).
# ---------------------------------------------------------------------------


def c1_coverage_80(entries: Sequence[BacktestEntry]) -> GateResult:
    """C1 — 80% CI covers truth in ≥80% of (cycle × candidate) pairs."""
    n = len(entries)
    if n == 0:
        return GateResult(GATE_C1, False, 0.0, C1_THRESHOLD)
    covered = 0
    for e in entries:
        lo = e.quantiles.get("p10")
        hi = e.quantiles.get("p90")
        if lo is None or hi is None:
            continue
        if lo <= e.truth_share <= hi:
            covered += 1
    fraction = covered / n
    return GateResult(GATE_C1, fraction >= C1_THRESHOLD, fraction, C1_THRESHOLD)


def c2_coverage_95(entries: Sequence[BacktestEntry]) -> GateResult:
    """C2 — 95% CI covers truth in ≥95% of (cycle × candidate) pairs."""
    n = len(entries)
    if n == 0:
        return GateResult(GATE_C2, False, 0.0, C2_THRESHOLD)
    covered = 0
    for e in entries:
        lo = e.quantiles.get("p05")
        hi = e.quantiles.get("p95")
        if lo is None or hi is None:
            continue
        if lo <= e.truth_share <= hi:
            covered += 1
    fraction = covered / n
    return GateResult(GATE_C2, fraction >= C2_THRESHOLD, fraction, C2_THRESHOLD)


def c3_top3_mae(entries: Sequence[BacktestEntry]) -> GateResult:
    """C3 — top-3 candidates' median absolute error ≤ 5pp.

    Top-3 is picked per cycle by descending ``truth_share`` (so the gate
    judges the model on the candidates that actually matter to a
    forecast, not the long tail). Absolute error uses ``p50`` as the
    point estimate; the median across the union of per-cycle top-3 sets
    is the reported observed value.
    """
    if not entries:
        return GateResult(GATE_C3, False, float("inf"), C3_THRESHOLD_PP)

    by_cycle: dict[int, list[BacktestEntry]] = {}
    for e in entries:
        by_cycle.setdefault(e.cycle, []).append(e)

    abs_errors: list[float] = []
    for cycle_entries in by_cycle.values():
        top3 = sorted(cycle_entries, key=lambda e: -e.truth_share)[:3]
        for e in top3:
            p50 = e.quantiles.get("p50")
            if p50 is None:
                continue
            abs_errors.append(abs(float(p50) - float(e.truth_share)))

    if not abs_errors:
        return GateResult(GATE_C3, False, float("inf"), C3_THRESHOLD_PP)
    median = _median(abs_errors)
    return GateResult(
        GATE_C3, median <= C3_THRESHOLD_PP, median, C3_THRESHOLD_PP
    )


def _median(values: Sequence[float]) -> float:
    """Numpy-free median so the gate works without numpy in callers."""
    s = sorted(values)
    n = len(s)
    if n == 0:
        return float("nan")
    if n % 2 == 1:
        return float(s[n // 2])
    return float((s[n // 2 - 1] + s[n // 2]) / 2.0)


def c4_payload_finite(payload: dict[str, Any]) -> GateResult:
    """C4 — no NaN/Inf/all-zero quantile vectors in the payload.

    Catches a class of bugs in #32/#33 where the combiner emits a
    candidate whose quantile vector is all-zero (e.g. shares clipped to
    1e-6 and rounded out), or where a probability comes through as NaN.
    Returns False on the FIRST offending candidate so the failure row's
    ``observed`` is meaningful (1.0 = "found a bad candidate"; 0.0 =
    "everything is finite").
    """
    candidates = payload.get("candidates")
    if not candidates:
        return GateResult(GATE_C4, False, 1.0, 0.0)

    for c in candidates:
        vs = c.get("vote_share", {})
        vals = [float(v) for v in vs.values()]
        if not vals:
            return GateResult(GATE_C4, False, 1.0, 0.0)
        if all(v == 0.0 for v in vals):
            return GateResult(GATE_C4, False, 1.0, 0.0)
        if any(not math.isfinite(v) for v in vals):
            return GateResult(GATE_C4, False, 1.0, 0.0)
        for k in ("win_probability_round1", "qualifies_for_runoff_probability"):
            val = c.get(k)
            if val is None or not math.isfinite(float(val)):
                return GateResult(GATE_C4, False, 1.0, 0.0)
    return GateResult(GATE_C4, True, 0.0, 0.0)


def c5_runoff_simplex(payload: dict[str, Any]) -> GateResult:
    """C5 — runoff matrix pair probabilities sum to 1.0 ± 1e-6, all in [0,1].

    Reports the absolute deviation from 1.0 on the sum as ``observed``;
    a per-entry [0,1] violation short-circuits with ``observed = 1.0``
    so the failure row carries a clean signal.
    """
    runoff = payload.get("runoff_matrix")
    if not runoff:
        return GateResult(GATE_C5, False, 1.0, C5_THRESHOLD)

    total = 0.0
    for e in runoff:
        pp = e.get("pair_probability")
        wp = e.get("winner_a_probability")
        if pp is None or wp is None:
            return GateResult(GATE_C5, False, 1.0, C5_THRESHOLD)
        if not math.isfinite(float(pp)) or not (0.0 <= float(pp) <= 1.0):
            return GateResult(GATE_C5, False, 1.0, C5_THRESHOLD)
        if not math.isfinite(float(wp)) or not (0.0 <= float(wp) <= 1.0):
            return GateResult(GATE_C5, False, 1.0, C5_THRESHOLD)
        total += float(pp)
    deviation = abs(total - 1.0)
    return GateResult(GATE_C5, deviation <= C5_THRESHOLD, deviation, C5_THRESHOLD)


def c6_diagnostics(*, max_r_hat: float, min_bulk_ess: float) -> GateResult:
    """C6 — every monitored quantity has ``r_hat < 1.01`` and ``bulk_ess > 400``.

    The r_hat leg is checked first; if it fails the result reports
    ``observed = max_r_hat`` against the r_hat threshold. Otherwise the
    ess leg is checked and reports against the ess threshold. On full
    pass the result reports ``max_r_hat`` against the r_hat threshold
    so the audit trail carries the worst-case statistic.
    """
    if not math.isfinite(max_r_hat) or max_r_hat >= C6_RHAT_THRESHOLD:
        return GateResult(GATE_C6, False, float(max_r_hat), C6_RHAT_THRESHOLD)
    if not math.isfinite(min_bulk_ess) or min_bulk_ess <= C6_ESS_THRESHOLD:
        return GateResult(GATE_C6, False, float(min_bulk_ess), C6_ESS_THRESHOLD)
    return GateResult(GATE_C6, True, float(max_r_hat), C6_RHAT_THRESHOLD)


# ---------------------------------------------------------------------------
# Orchestration
# ---------------------------------------------------------------------------


def evaluate_all_gates(
    *,
    payload: dict[str, Any],
    backtest: BacktestResult,
) -> tuple[GateResult, ...]:
    """Evaluate all six gates in canonical order.

    The return tuple's element order matches :data:`GATE_NAMES` so the
    downstream audit-trail UI can render them in a stable sequence.
    """
    return (
        c1_coverage_80(backtest.entries),
        c2_coverage_95(backtest.entries),
        c3_top3_mae(backtest.entries),
        c4_payload_finite(payload),
        c5_runoff_simplex(payload),
        c6_diagnostics(
            max_r_hat=backtest.max_r_hat,
            min_bulk_ess=backtest.min_bulk_ess,
        ),
    )


def all_passed(results: Iterable[GateResult]) -> bool:
    """Return True iff every gate result passed."""
    return all(r.passed for r in results)


# ---------------------------------------------------------------------------
# DB writer + idempotence
# ---------------------------------------------------------------------------


def _fetch_forecast_state(
    conn: Any, run_id: uuid.UUID
) -> tuple[bool, str] | None:
    """Return ``(is_published, run_kind)`` for ``run_id``, or None if missing."""
    with conn.cursor() as cur:
        cur.execute(
            "SELECT is_published, run_kind FROM forecasts WHERE run_id = %s",
            (str(run_id),),
        )
        row = cur.fetchone()
    if row is None:
        return None
    return bool(row[0]), str(row[1])


def _fetch_recorded_failure_gates(conn: Any, run_id: uuid.UUID) -> set[str]:
    """Return the set of gate names already recorded for ``run_id``."""
    with conn.cursor() as cur:
        cur.execute(
            "SELECT gate FROM calibration_failures WHERE run_id = %s",
            (str(run_id),),
        )
        return {str(row[0]) for row in cur.fetchall()}


def _is_idempotent_noop(
    conn: Any,
    run_id: uuid.UUID,
    results: Sequence[GateResult],
) -> bool:
    """Return True iff the current DB state already reflects ``results``.

    All-pass case: idempotent when ``forecasts.is_published`` is already
    TRUE for the run (and the row exists).

    Any-fail case: idempotent when ``forecasts.is_published`` is FALSE
    and every failed gate already has a row in ``calibration_failures``.
    A second re-run that matches an existing fail set writes nothing
    further.
    """
    state = _fetch_forecast_state(conn, run_id)
    if state is None:
        return False
    is_published, _ = state
    if all_passed(results):
        return is_published
    if is_published:
        return False
    failed_gates = {r.gate for r in results if not r.passed}
    existing = _fetch_recorded_failure_gates(conn, run_id)
    return failed_gates.issubset(existing)


def apply_calibration_result(
    conn: Any,
    run_id: uuid.UUID,
    results: Sequence[GateResult],
) -> bool:
    """Apply gate results to the DB; return True iff all gates passed.

    On all-pass the function issues an ``UPDATE forecasts SET
    is_published = TRUE`` filtered to ``run_kind = 'scheduled'`` (whatif
    rows are never published per ADR-006 / migration 0006). On any-fail
    it inserts one ``calibration_failures`` row per failed gate, skipping
    gates that already have a row for this ``run_id`` so re-running on a
    partially-applied state is safe.

    Caller owns the transaction; commits are the caller's responsibility
    so the integration test can wrap a call in a transaction that rolls
    back, and so the CLI commits atomically.
    """
    if _is_idempotent_noop(conn, run_id, results):
        return all_passed(results)

    if all_passed(results):
        with conn.cursor() as cur:
            cur.execute(
                "UPDATE forecasts SET is_published = TRUE "
                "WHERE run_id = %s AND run_kind = 'scheduled'",
                (str(run_id),),
            )
        return True

    existing = _fetch_recorded_failure_gates(conn, run_id)
    with conn.cursor() as cur:
        for r in results:
            if r.passed or r.gate in existing:
                continue
            cur.execute(
                """
                INSERT INTO calibration_failures
                    (run_id, gate, observed_value, threshold)
                VALUES (%s, %s, %s, %s)
                """,
                (str(run_id), r.gate, float(r.observed), float(r.threshold)),
            )
    return False


# ---------------------------------------------------------------------------
# Payload loader (DB integration helper used by the library entry point)
# ---------------------------------------------------------------------------


def load_payload(conn: Any, run_id: uuid.UUID) -> dict[str, Any]:
    """Read ``forecasts.payload`` for ``run_id``; raise KeyError if missing.

    Used by the production CLI path so the gate can read the
    just-written payload from the same row that ``predict.py`` inserted.
    """
    with conn.cursor() as cur:
        cur.execute(
            "SELECT payload FROM forecasts WHERE run_id = %s",
            (str(run_id),),
        )
        row = cur.fetchone()
    if row is None:
        raise KeyError(f"forecasts row not found for run_id={run_id}")
    return cast(dict[str, Any], row[0])


def evaluate_and_apply_gates(
    conn: Any,
    *,
    run_id: uuid.UUID,
    backtest: BacktestResult,
    payload: dict[str, Any] | None = None,
) -> tuple[bool, tuple[GateResult, ...]]:
    """Library entry point: evaluate gates and apply to DB in one shot.

    ``payload`` is read from ``forecasts`` when not supplied; the test
    suite injects a synthetic payload so it can exercise the DB writer
    without round-tripping through a real INSERT.
    """
    p = payload if payload is not None else load_payload(conn, run_id)
    results = evaluate_all_gates(payload=p, backtest=backtest)
    published = apply_calibration_result(conn, run_id, results)
    return published, results


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="calibrate",
        description=(
            "Run the calibration gate (#36, ADR-013) against an existing "
            "forecasts row. Either flips is_published=TRUE on all-pass or "
            "writes per-gate calibration_failures rows on any-fail."
        ),
    )
    parser.add_argument(
        "--run-id",
        required=True,
        type=str,
        help="UUID of the forecasts row to gate (output of predict.py)",
    )
    return parser


def _load_backtest_from_db(_conn: Any) -> BacktestResult:
    """Stub for the production backtest-refit path. Not implemented in this iteration.

    Producing a :class:`BacktestResult` from the database requires the
    #19-#22 truth loaders to be live so the gate can re-fit #32 against
    the 2019 + 2023 holdouts. Issue #36 ships the gate library; the
    production backtest wiring is a separate ticket. The library entry
    point :func:`evaluate_and_apply_gates` is the testable surface.
    """
    raise NotImplementedError(
        "calibrate.py CLI path requires the holdout backtest loaders "
        "(#19-#22) to be live; the library function "
        "evaluate_and_apply_gates() is the testable entry point in #36."
    )


def main(argv: list[str] | None = None) -> int:
    logging.basicConfig(
        level=logging.INFO, format="%(levelname)s %(name)s %(message)s"
    )
    args = _build_parser().parse_args(argv)

    try:
        run_id = uuid.UUID(args.run_id)
    except ValueError:
        logger.error("calibrate: --run-id is not a valid UUID: %s", args.run_id)
        return 2

    dsn = os.environ.get("DATABASE_URL")
    if not dsn:
        logger.error("DATABASE_URL not set")
        return 2

    import psycopg  # noqa: PLC0415

    with psycopg.connect(dsn) as conn:
        try:
            backtest = _load_backtest_from_db(conn)
        except NotImplementedError as exc:
            logger.error("calibrate: %s", exc)
            return 2
        published, results = evaluate_and_apply_gates(
            conn, run_id=run_id, backtest=backtest
        )
        conn.commit()

    for r in results:
        flag = "PASS" if r.passed else "FAIL"
        print(
            f"{r.gate} {flag} observed={r.observed:.6g} threshold={r.threshold:.6g}"
        )
    print(f"published={'true' if published else 'false'}")
    return 0


__all__ = [
    "C1_THRESHOLD",
    "C2_THRESHOLD",
    "C3_THRESHOLD_PP",
    "C5_THRESHOLD",
    "C6_ESS_THRESHOLD",
    "C6_RHAT_THRESHOLD",
    "GATE_C1",
    "GATE_C2",
    "GATE_C3",
    "GATE_C4",
    "GATE_C5",
    "GATE_C6",
    "GATE_NAMES",
    "BacktestEntry",
    "BacktestResult",
    "GateResult",
    "all_passed",
    "apply_calibration_result",
    "c1_coverage_80",
    "c2_coverage_95",
    "c3_top3_mae",
    "c4_payload_finite",
    "c5_runoff_simplex",
    "c6_diagnostics",
    "evaluate_all_gates",
    "evaluate_and_apply_gates",
    "load_payload",
    "main",
]


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
