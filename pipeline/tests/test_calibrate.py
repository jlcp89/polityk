"""Tests for ``pipeline.scripts.calibrate`` (issue #36, ADR-013).

Three tiers:

1. Pure-logic tests (always run) — each C1-C6 gate against synthetic
   inputs, plus the orchestrator + idempotence/DB writer against a
   FakeConn that records executed statements.
2. End-to-end Postgres tests gated by ``POLITYK_TEST_DATABASE_URL`` —
   seed a real ``forecasts`` row, run the gate, assert ``is_published``
   flipped (good forecast) or the ``calibration_failures`` audit rows
   landed (bad forecast). Also asserts idempotence: a second call after
   the first writes nothing new.

The synthetic payload helper mirrors the ADR-014 shape exactly so the
gate-vs-payload contract is what would fire in production.
"""

from __future__ import annotations

import math
import os
import uuid
from datetime import UTC, datetime
from typing import Any

import pytest

from pipeline.scripts import calibrate

# ---------------------------------------------------------------------------
# Synthetic payload + backtest helpers
# ---------------------------------------------------------------------------


def _good_quantiles(point: float, width: float = 0.06) -> dict[str, float]:
    """Build an ADR-014 quantile dict centred at ``point`` with given width.

    Width here is the full p05-p95 span; intermediate quantiles are
    spaced linearly so that C1 (p10-p90) covers truth when truth is within
    +/- 0.40*width of point.
    """
    return {
        "p05": point - 0.50 * width,
        "p10": point - 0.40 * width,
        "p25": point - 0.20 * width,
        "p50": point,
        "p75": point + 0.20 * width,
        "p90": point + 0.40 * width,
        "p95": point + 0.50 * width,
    }


def _good_payload(n_candidates: int = 4) -> dict[str, Any]:
    """ADR-014-shaped payload with finite shares + valid runoff matrix."""
    candidates = []
    for j in range(n_candidates):
        candidates.append(
            {
                "candidate_id": 10 + j,
                "name": f"Cand {10 + j}",
                "wikidata_qid": None,
                "party_id": None,
                "party_name": None,
                "vote_share": _good_quantiles(0.30 - 0.05 * j, width=0.06),
                "win_probability_round1": 0.10,
                "qualifies_for_runoff_probability": 0.40,
            }
        )
    return {
        "run_id": str(uuid.uuid4()),
        "model_version": "0.1.0",
        "generated_at": datetime(2027, 6, 1, 18, 0, tzinfo=UTC).isoformat(),
        "race": {"type": "presidential", "cycle": 2027, "round": 1},
        "candidates": candidates,
        "runoff_matrix": [
            {
                "candidate_a_id": 10,
                "candidate_b_id": 11,
                "pair_probability": 0.6,
                "winner_a_probability": 0.55,
            },
            {
                "candidate_a_id": 10,
                "candidate_b_id": 12,
                "pair_probability": 0.4,
                "winner_a_probability": 0.50,
            },
        ],
        "interventions_applied": [],
        "methodology_url": "https://polityk.gt/methodology#presidential-0.1.0",
    }


def _good_backtest(seed: int = 17) -> calibrate.BacktestResult:
    """Holdout backtest where every truth lies inside the 80% CI."""
    entries = []
    # Two cycles × 5 candidates so C3 (top-3 per cycle) has 6 observations.
    for cycle in (2019, 2023):
        for cand in range(5):
            # Truth share descends with candidate index per cycle.
            truth = 0.35 - 0.05 * cand + 0.001 * (cycle - 2019)
            # Tight quantiles centred close to the truth — C1/C2/C3 all pass.
            point = truth + 0.005  # within 5pp easily
            entries.append(
                calibrate.BacktestEntry(
                    cycle=cycle,
                    candidate_id=100 + cycle * 10 + cand,
                    candidate_name=f"{cycle} cand {cand}",
                    quantiles=_good_quantiles(point, width=0.10),
                    truth_share=truth,
                )
            )
    return calibrate.BacktestResult(
        entries=tuple(entries),
        max_r_hat=1.005,
        min_bulk_ess=900.0,
    )


# ---------------------------------------------------------------------------
# Pure-logic: C1 coverage 80
# ---------------------------------------------------------------------------


def test_c1_passes_on_well_calibrated_intervals() -> None:
    bt = _good_backtest()
    res = calibrate.c1_coverage_80(bt.entries)
    assert res.gate == calibrate.GATE_C1
    assert res.passed is True
    assert res.observed >= calibrate.C1_THRESHOLD
    assert res.threshold == calibrate.C1_THRESHOLD


def test_c1_fails_when_truth_outside_p10_p90() -> None:
    entries = [
        calibrate.BacktestEntry(
            cycle=2019,
            candidate_id=1,
            candidate_name="x",
            quantiles=_good_quantiles(0.30, width=0.02),
            truth_share=0.50,  # well outside the band
        ),
        calibrate.BacktestEntry(
            cycle=2019,
            candidate_id=2,
            candidate_name="y",
            quantiles=_good_quantiles(0.20, width=0.02),
            truth_share=0.40,
        ),
    ]
    res = calibrate.c1_coverage_80(entries)
    assert res.passed is False
    assert res.observed == 0.0


def test_c1_fails_on_empty_entries() -> None:
    res = calibrate.c1_coverage_80(())
    assert res.passed is False
    assert res.observed == 0.0
    assert res.threshold == calibrate.C1_THRESHOLD


# ---------------------------------------------------------------------------
# Pure-logic: C2 coverage 95
# ---------------------------------------------------------------------------


def test_c2_passes_on_well_calibrated_intervals() -> None:
    bt = _good_backtest()
    res = calibrate.c2_coverage_95(bt.entries)
    assert res.gate == calibrate.GATE_C2
    assert res.passed is True
    assert res.observed >= calibrate.C2_THRESHOLD


def test_c2_fails_below_95pct() -> None:
    """5 entries; one with truth outside p05/p95 → 4/5 = 0.8 < 0.95."""
    entries = []
    for i in range(5):
        truth = 0.30
        # First 4 covered, last one wildly off.
        point = 0.30 if i < 4 else 0.10
        entries.append(
            calibrate.BacktestEntry(
                cycle=2019,
                candidate_id=i,
                candidate_name=str(i),
                quantiles=_good_quantiles(point, width=0.02),
                truth_share=truth,
            )
        )
    res = calibrate.c2_coverage_95(entries)
    assert res.passed is False
    assert math.isclose(res.observed, 0.8)


# ---------------------------------------------------------------------------
# Pure-logic: C3 top-3 MAE
# ---------------------------------------------------------------------------


def test_c3_passes_on_tight_predictions() -> None:
    bt = _good_backtest()
    res = calibrate.c3_top3_mae(bt.entries)
    assert res.gate == calibrate.GATE_C3
    assert res.passed is True
    assert res.observed <= calibrate.C3_THRESHOLD_PP


def test_c3_fails_when_top3_error_above_5pp() -> None:
    entries = []
    # Two cycles, three "big" candidates each with 10pp error.
    for cycle in (2019, 2023):
        for cand in range(3):
            truth = 0.30 - 0.05 * cand
            point = truth + 0.10  # 10pp error
            entries.append(
                calibrate.BacktestEntry(
                    cycle=cycle,
                    candidate_id=cand,
                    candidate_name=str(cand),
                    quantiles=_good_quantiles(point, width=0.04),
                    truth_share=truth,
                )
            )
    res = calibrate.c3_top3_mae(entries)
    assert res.passed is False
    assert res.observed > calibrate.C3_THRESHOLD_PP


def test_c3_picks_top3_by_truth_share() -> None:
    """The long tail's error shouldn't count — only the top-3 do."""
    entries = []
    # Cycle 2019: top-3 with 1pp errors; rest with 20pp errors.
    for cand in range(6):
        truth = 0.40 - 0.05 * cand
        if cand < 3:
            point = truth + 0.01
        else:
            point = truth + 0.20
        entries.append(
            calibrate.BacktestEntry(
                cycle=2019,
                candidate_id=cand,
                candidate_name=str(cand),
                quantiles=_good_quantiles(point, width=0.04),
                truth_share=truth,
            )
        )
    res = calibrate.c3_top3_mae(entries)
    # Median of [0.01, 0.01, 0.01] = 0.01 < 0.05 → pass
    assert res.passed is True
    assert res.observed == pytest.approx(0.01)


def test_c3_empty_entries_fail() -> None:
    res = calibrate.c3_top3_mae(())
    assert res.passed is False
    assert res.observed == float("inf")


# ---------------------------------------------------------------------------
# Pure-logic: C4 payload finite
# ---------------------------------------------------------------------------


def test_c4_passes_on_well_formed_payload() -> None:
    payload = _good_payload()
    res = calibrate.c4_payload_finite(payload)
    assert res.passed is True
    assert res.gate == calibrate.GATE_C4


def test_c4_fails_on_nan_quantile() -> None:
    payload = _good_payload()
    payload["candidates"][0]["vote_share"]["p50"] = float("nan")
    res = calibrate.c4_payload_finite(payload)
    assert res.passed is False


def test_c4_fails_on_inf_quantile() -> None:
    payload = _good_payload()
    payload["candidates"][1]["vote_share"]["p95"] = float("inf")
    res = calibrate.c4_payload_finite(payload)
    assert res.passed is False


def test_c4_fails_on_all_zero_quantile_vector() -> None:
    payload = _good_payload()
    payload["candidates"][2]["vote_share"] = {
        k: 0.0 for k in payload["candidates"][2]["vote_share"]
    }
    res = calibrate.c4_payload_finite(payload)
    assert res.passed is False


def test_c4_fails_on_missing_candidates() -> None:
    payload = _good_payload()
    payload["candidates"] = []
    res = calibrate.c4_payload_finite(payload)
    assert res.passed is False


def test_c4_fails_on_nan_probability() -> None:
    payload = _good_payload()
    payload["candidates"][0]["win_probability_round1"] = float("nan")
    res = calibrate.c4_payload_finite(payload)
    assert res.passed is False


# ---------------------------------------------------------------------------
# Pure-logic: C5 runoff simplex
# ---------------------------------------------------------------------------


def test_c5_passes_when_sum_equals_one() -> None:
    payload = _good_payload()
    res = calibrate.c5_runoff_simplex(payload)
    assert res.passed is True
    assert res.observed <= calibrate.C5_THRESHOLD


def test_c5_fails_when_sum_drifts_above_tolerance() -> None:
    payload = _good_payload()
    payload["runoff_matrix"][0]["pair_probability"] = 0.7
    payload["runoff_matrix"][1]["pair_probability"] = 0.4  # total 1.1
    res = calibrate.c5_runoff_simplex(payload)
    assert res.passed is False
    assert res.observed > calibrate.C5_THRESHOLD


def test_c5_fails_on_winner_a_above_one() -> None:
    payload = _good_payload()
    payload["runoff_matrix"][0]["winner_a_probability"] = 1.5
    res = calibrate.c5_runoff_simplex(payload)
    assert res.passed is False


def test_c5_fails_on_negative_pair_probability() -> None:
    payload = _good_payload()
    payload["runoff_matrix"][0]["pair_probability"] = -0.1
    res = calibrate.c5_runoff_simplex(payload)
    assert res.passed is False


def test_c5_fails_on_empty_runoff_matrix() -> None:
    payload = _good_payload()
    payload["runoff_matrix"] = []
    res = calibrate.c5_runoff_simplex(payload)
    assert res.passed is False


# ---------------------------------------------------------------------------
# Pure-logic: C6 diagnostics
# ---------------------------------------------------------------------------


def test_c6_passes_under_thresholds() -> None:
    res = calibrate.c6_diagnostics(max_r_hat=1.005, min_bulk_ess=900.0)
    assert res.passed is True
    assert res.observed == 1.005


def test_c6_fails_on_high_rhat() -> None:
    res = calibrate.c6_diagnostics(max_r_hat=1.05, min_bulk_ess=900.0)
    assert res.passed is False
    assert res.observed == 1.05
    assert res.threshold == calibrate.C6_RHAT_THRESHOLD


def test_c6_fails_on_low_ess() -> None:
    res = calibrate.c6_diagnostics(max_r_hat=1.005, min_bulk_ess=200.0)
    assert res.passed is False
    assert res.observed == 200.0
    assert res.threshold == calibrate.C6_ESS_THRESHOLD


def test_c6_fails_on_nan_rhat() -> None:
    res = calibrate.c6_diagnostics(max_r_hat=float("nan"), min_bulk_ess=900.0)
    assert res.passed is False


# ---------------------------------------------------------------------------
# Orchestrator
# ---------------------------------------------------------------------------


def test_evaluate_all_gates_returns_six_in_canonical_order() -> None:
    payload = _good_payload()
    backtest = _good_backtest()
    results = calibrate.evaluate_all_gates(payload=payload, backtest=backtest)
    assert tuple(r.gate for r in results) == calibrate.GATE_NAMES
    assert all(r.passed for r in results)


def test_evaluate_all_gates_marks_failing_gates() -> None:
    """A payload with bad runoff + low ess fails C5 and C6 but passes others."""
    payload = _good_payload()
    payload["runoff_matrix"][0]["pair_probability"] = 0.9
    payload["runoff_matrix"][1]["pair_probability"] = 0.9  # sum 1.8

    backtest = calibrate.BacktestResult(
        entries=_good_backtest().entries,
        max_r_hat=1.005,
        min_bulk_ess=200.0,  # below 400
    )
    results = calibrate.evaluate_all_gates(payload=payload, backtest=backtest)
    by_gate = {r.gate: r for r in results}
    assert by_gate[calibrate.GATE_C1].passed
    assert by_gate[calibrate.GATE_C2].passed
    assert by_gate[calibrate.GATE_C3].passed
    assert by_gate[calibrate.GATE_C4].passed
    assert not by_gate[calibrate.GATE_C5].passed
    assert not by_gate[calibrate.GATE_C6].passed


def test_all_passed_helper() -> None:
    results = (
        calibrate.GateResult(gate="x", passed=True, observed=0.0, threshold=0.0),
        calibrate.GateResult(gate="y", passed=False, observed=0.0, threshold=0.0),
    )
    assert calibrate.all_passed(results) is False
    assert calibrate.all_passed(results[:1]) is True


# ---------------------------------------------------------------------------
# Fake-conn DB writer + idempotence tests
# ---------------------------------------------------------------------------


class _FakeCursor:
    def __init__(self, fetch_queue: list[Any] | None = None) -> None:
        self.executed: list[tuple[str, tuple[Any, ...]]] = []
        self._fetch_queue: list[Any] = list(fetch_queue or [])
        self._last_fetchall: list[Any] = []

    def execute(self, sql: str, params: tuple[Any, ...] = ()) -> None:
        self.executed.append((sql, params))
        # Pre-seed responses for SELECTs in execution order.
        if "SELECT is_published, run_kind" in sql:
            self._last_fetchall = []
            # Front of fetch_queue is the (is_published, run_kind) row.
            self._last_fetchone_row = self._fetch_queue.pop(0) if self._fetch_queue else None
        elif "SELECT gate FROM calibration_failures" in sql:
            # Next queue entry is the list of existing gates.
            self._last_fetchall = list(self._fetch_queue.pop(0)) if self._fetch_queue else []
            self._last_fetchone_row = None
        elif "SELECT payload FROM forecasts" in sql:
            self._last_fetchone_row = self._fetch_queue.pop(0) if self._fetch_queue else None
            self._last_fetchall = []
        else:
            self._last_fetchone_row = None

    def fetchone(self) -> Any:
        return self._last_fetchone_row

    def fetchall(self) -> list[Any]:
        return self._last_fetchall

    def __enter__(self) -> _FakeCursor:
        return self

    def __exit__(self, *args: object) -> None:
        return None


class _FakeConn:
    def __init__(self, fetch_queue: list[Any] | None = None) -> None:
        self._fetch_queue = list(fetch_queue or [])
        self.cursors: list[_FakeCursor] = []

    def cursor(self) -> _FakeCursor:
        cur = _FakeCursor(self._fetch_queue)
        # Share the queue across cursors so successive calls progress.
        cur._fetch_queue = self._fetch_queue
        self.cursors.append(cur)
        return cur

    def all_statements(self) -> list[tuple[str, tuple[Any, ...]]]:
        out: list[tuple[str, tuple[Any, ...]]] = []
        for c in self.cursors:
            out.extend(c.executed)
        return out


def test_apply_calibration_all_pass_issues_update() -> None:
    """Forecast row exists, is_published=FALSE → UPDATE fires."""
    run_id = uuid.uuid4()
    # Fetch queue: (is_published=False, run_kind='scheduled')
    conn = _FakeConn(fetch_queue=[(False, "scheduled")])
    results = tuple(
        calibrate.GateResult(gate=g, passed=True, observed=0.0, threshold=0.0)
        for g in calibrate.GATE_NAMES
    )
    published = calibrate.apply_calibration_result(conn, run_id, results)
    assert published is True
    stmts = conn.all_statements()
    update_stmts = [s for s in stmts if "UPDATE forecasts" in s[0]]
    assert len(update_stmts) == 1
    assert update_stmts[0][1] == (str(run_id),)
    assert "is_published = TRUE" in update_stmts[0][0]
    assert "run_kind = 'scheduled'" in update_stmts[0][0]


def test_apply_calibration_any_fail_writes_one_row_per_failed_gate() -> None:
    run_id = uuid.uuid4()
    # Fetch queue:
    # 1) is_published check → (False, 'scheduled')
    # 2) existing failures (in idempotence check) → []
    # 3) existing failures (in writer) → []
    conn = _FakeConn(fetch_queue=[(False, "scheduled"), [], []])
    results = (
        calibrate.GateResult(gate=calibrate.GATE_C1, passed=True, observed=0.9, threshold=0.8),
        calibrate.GateResult(gate=calibrate.GATE_C2, passed=False, observed=0.85, threshold=0.95),
        calibrate.GateResult(gate=calibrate.GATE_C3, passed=False, observed=0.08, threshold=0.05),
        calibrate.GateResult(gate=calibrate.GATE_C4, passed=True, observed=0.0, threshold=0.0),
        calibrate.GateResult(gate=calibrate.GATE_C5, passed=True, observed=0.0, threshold=1e-6),
        calibrate.GateResult(gate=calibrate.GATE_C6, passed=True, observed=1.0, threshold=1.01),
    )
    published = calibrate.apply_calibration_result(conn, run_id, results)
    assert published is False
    stmts = conn.all_statements()
    inserts = [s for s in stmts if "INSERT INTO calibration_failures" in s[0]]
    assert len(inserts) == 2
    gates_inserted = {s[1][1] for s in inserts}
    assert gates_inserted == {calibrate.GATE_C2, calibrate.GATE_C3}
    # No UPDATE on any-fail.
    assert not any("UPDATE forecasts" in s[0] for s in stmts)


def test_apply_calibration_idempotent_when_already_published() -> None:
    """All-pass results re-run on an already-published forecast = no-op."""
    run_id = uuid.uuid4()
    conn = _FakeConn(fetch_queue=[(True, "scheduled")])
    results = tuple(
        calibrate.GateResult(gate=g, passed=True, observed=0.0, threshold=0.0)
        for g in calibrate.GATE_NAMES
    )
    published = calibrate.apply_calibration_result(conn, run_id, results)
    assert published is True
    stmts = conn.all_statements()
    # Only the SELECT — no UPDATE re-issued.
    assert not any("UPDATE" in s[0] for s in stmts)
    assert not any("INSERT" in s[0] for s in stmts)


def test_apply_calibration_idempotent_when_failure_rows_match() -> None:
    """Any-fail re-run on a row whose calibration_failures already covers
    the failed gates is a no-op."""
    run_id = uuid.uuid4()
    # Fetch queue: (False, 'scheduled'), existing gates includes both fails.
    # Postgres rows come back as tuples — match that shape so set comprehension
    # on row[0] picks up the gate name, not its first character.
    conn = _FakeConn(
        fetch_queue=[
            (False, "scheduled"),
            [(calibrate.GATE_C2,), (calibrate.GATE_C3,)],
        ]
    )
    results = (
        calibrate.GateResult(gate=calibrate.GATE_C1, passed=True, observed=0.9, threshold=0.8),
        calibrate.GateResult(gate=calibrate.GATE_C2, passed=False, observed=0.85, threshold=0.95),
        calibrate.GateResult(gate=calibrate.GATE_C3, passed=False, observed=0.08, threshold=0.05),
    )
    published = calibrate.apply_calibration_result(conn, run_id, results)
    assert published is False
    stmts = conn.all_statements()
    assert not any("INSERT" in s[0] for s in stmts)


def test_apply_calibration_missing_forecast_row_is_not_idempotent() -> None:
    """If the run_id has no forecasts row, apply still attempts the writes
    (which will raise an FK error on a real DB)."""
    run_id = uuid.uuid4()
    # Fetch queue: SELECT returns None → not idempotent → proceeds to UPDATE.
    conn = _FakeConn(fetch_queue=[None])
    results = tuple(
        calibrate.GateResult(gate=g, passed=True, observed=0.0, threshold=0.0)
        for g in calibrate.GATE_NAMES
    )
    calibrate.apply_calibration_result(conn, run_id, results)
    stmts = conn.all_statements()
    # UPDATE was attempted (DB will treat as a no-op if row missing).
    assert any("UPDATE forecasts" in s[0] for s in stmts)


# ---------------------------------------------------------------------------
# CLI surface
# ---------------------------------------------------------------------------


def test_main_returns_two_when_run_id_not_uuid(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("DATABASE_URL", "postgres://fake/fake")
    rc = calibrate.main(["--run-id", "not-a-uuid"])
    assert rc == 2


def test_main_returns_two_when_database_url_missing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("DATABASE_URL", raising=False)
    rc = calibrate.main(["--run-id", str(uuid.uuid4())])
    assert rc == 2


# ---------------------------------------------------------------------------
# End-to-end Postgres
# ---------------------------------------------------------------------------

_TEST_DSN = os.environ.get("POLITYK_TEST_DATABASE_URL")


def _seed_forecast(conn: Any, run_id: uuid.UUID, payload: dict[str, Any]) -> None:
    """Insert a minimal forecasts row so the gate can target it."""
    import json

    with conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO forecasts
                (run_id, model_version, generated_at, race_type, run_kind, payload)
            VALUES (%s, %s, %s, %s, %s, %s::jsonb)
            """,
            (
                str(run_id),
                "0.1.0",
                datetime.now(UTC),
                "presidential",
                "scheduled",
                json.dumps(payload),
            ),
        )


def _truncate(conn: Any) -> None:
    with conn.cursor() as cur:
        cur.execute(
            "TRUNCATE TABLE posterior_archives, calibration_failures, "
            "calibration_overrides, forecasts CASCADE"
        )
    conn.commit()


@pytest.mark.skipif(_TEST_DSN is None, reason="POLITYK_TEST_DATABASE_URL not set")
def test_integration_good_forecast_flips_is_published() -> None:
    """Acceptance: seed a good forecast → gate flips is_published=TRUE."""
    import psycopg

    assert _TEST_DSN is not None
    run_id = uuid.uuid4()
    payload = _good_payload()
    backtest = _good_backtest()

    with psycopg.connect(_TEST_DSN) as conn:
        _truncate(conn)
        _seed_forecast(conn, run_id, payload)
        conn.commit()

        published, results = calibrate.evaluate_and_apply_gates(
            conn, run_id=run_id, backtest=backtest, payload=payload
        )
        conn.commit()
        assert published is True
        assert all(r.passed for r in results)

        with conn.cursor() as cur:
            cur.execute(
                "SELECT is_published FROM forecasts WHERE run_id = %s",
                (str(run_id),),
            )
            row = cur.fetchone()
        assert row is not None
        assert row[0] is True

        with conn.cursor() as cur:
            cur.execute(
                "SELECT COUNT(*) FROM calibration_failures WHERE run_id = %s",
                (str(run_id),),
            )
            row = cur.fetchone()
        assert row is not None
        assert row[0] == 0


@pytest.mark.skipif(_TEST_DSN is None, reason="POLITYK_TEST_DATABASE_URL not set")
def test_integration_bad_forecast_records_failure_rows() -> None:
    """Acceptance: seed a bad forecast → is_published stays FALSE,
    calibration_failures has one row per failed gate."""
    import psycopg

    assert _TEST_DSN is not None
    run_id = uuid.uuid4()
    payload = _good_payload()
    # Break C5: simplex broken.
    payload["runoff_matrix"][0]["pair_probability"] = 0.9
    payload["runoff_matrix"][1]["pair_probability"] = 0.9
    # Break C4: NaN quantile.
    payload["candidates"][0]["vote_share"]["p50"] = float("nan")

    # Break C6: low ess.
    backtest = calibrate.BacktestResult(
        entries=_good_backtest().entries,
        max_r_hat=1.005,
        min_bulk_ess=100.0,
    )

    # JSONB NaN: Postgres rejects NaN in JSONB. The C4 gate runs against
    # the in-memory payload before the DB read, so we don't need the
    # NaN to be in JSONB — just pass the payload directly.
    payload_for_db = dict(payload)
    payload_for_db["candidates"] = [dict(c) for c in payload["candidates"]]
    payload_for_db["candidates"][0]["vote_share"] = {
        k: (1e9 if math.isnan(v) else v)
        for k, v in payload["candidates"][0]["vote_share"].items()
    }

    with psycopg.connect(_TEST_DSN) as conn:
        _truncate(conn)
        _seed_forecast(conn, run_id, payload_for_db)
        conn.commit()

        published, results = calibrate.evaluate_and_apply_gates(
            conn, run_id=run_id, backtest=backtest, payload=payload
        )
        conn.commit()
        assert published is False

        failed_gates = {r.gate for r in results if not r.passed}
        assert calibrate.GATE_C4 in failed_gates
        assert calibrate.GATE_C5 in failed_gates
        assert calibrate.GATE_C6 in failed_gates

        with conn.cursor() as cur:
            cur.execute(
                "SELECT is_published FROM forecasts WHERE run_id = %s",
                (str(run_id),),
            )
            row = cur.fetchone()
        assert row is not None
        assert row[0] is False

        with conn.cursor() as cur:
            cur.execute(
                "SELECT gate FROM calibration_failures WHERE run_id = %s "
                "ORDER BY gate",
                (str(run_id),),
            )
            recorded = {row[0] for row in cur.fetchall()}
        assert recorded == failed_gates


@pytest.mark.skipif(_TEST_DSN is None, reason="POLITYK_TEST_DATABASE_URL not set")
def test_integration_idempotent_re_run_on_published() -> None:
    """Re-running the gate on an already-published forecast writes nothing."""
    import psycopg

    assert _TEST_DSN is not None
    run_id = uuid.uuid4()
    payload = _good_payload()
    backtest = _good_backtest()

    with psycopg.connect(_TEST_DSN) as conn:
        _truncate(conn)
        _seed_forecast(conn, run_id, payload)
        conn.commit()

        # First call: publish.
        calibrate.evaluate_and_apply_gates(
            conn, run_id=run_id, backtest=backtest, payload=payload
        )
        conn.commit()

        # Second call: no-op.
        published, _ = calibrate.evaluate_and_apply_gates(
            conn, run_id=run_id, backtest=backtest, payload=payload
        )
        conn.commit()
        assert published is True

        with conn.cursor() as cur:
            cur.execute(
                "SELECT COUNT(*) FROM calibration_failures WHERE run_id = %s",
                (str(run_id),),
            )
            row = cur.fetchone()
        assert row is not None
        assert row[0] == 0


@pytest.mark.skipif(_TEST_DSN is None, reason="POLITYK_TEST_DATABASE_URL not set")
def test_integration_idempotent_re_run_on_failed() -> None:
    """Re-running the gate on a previously-failed forecast doesn't
    duplicate calibration_failures rows."""
    import psycopg

    assert _TEST_DSN is not None
    run_id = uuid.uuid4()
    payload = _good_payload()
    payload["runoff_matrix"][0]["pair_probability"] = 0.9
    payload["runoff_matrix"][1]["pair_probability"] = 0.9
    backtest = _good_backtest()

    with psycopg.connect(_TEST_DSN) as conn:
        _truncate(conn)
        _seed_forecast(conn, run_id, payload)
        conn.commit()

        # First call: records C5 failure.
        calibrate.evaluate_and_apply_gates(
            conn, run_id=run_id, backtest=backtest, payload=payload
        )
        conn.commit()

        # Second call: idempotent — no new rows.
        calibrate.evaluate_and_apply_gates(
            conn, run_id=run_id, backtest=backtest, payload=payload
        )
        conn.commit()

        with conn.cursor() as cur:
            cur.execute(
                "SELECT COUNT(*) FROM calibration_failures WHERE run_id = %s",
                (str(run_id),),
            )
            row = cur.fetchone()
        assert row is not None
        assert row[0] == 1


@pytest.mark.skipif(_TEST_DSN is None, reason="POLITYK_TEST_DATABASE_URL not set")
def test_integration_load_payload_reads_jsonb_round_trip() -> None:
    """``load_payload`` reads the JSONB payload back from forecasts."""
    import psycopg

    assert _TEST_DSN is not None
    run_id = uuid.uuid4()
    payload = _good_payload()

    with psycopg.connect(_TEST_DSN) as conn:
        _truncate(conn)
        _seed_forecast(conn, run_id, payload)
        conn.commit()

        loaded = calibrate.load_payload(conn, run_id)
        assert loaded["race"]["type"] == "presidential"
        assert len(loaded["candidates"]) == len(payload["candidates"])


@pytest.mark.skipif(_TEST_DSN is None, reason="POLITYK_TEST_DATABASE_URL not set")
def test_integration_load_payload_raises_on_missing_run_id() -> None:
    import psycopg

    assert _TEST_DSN is not None
    with psycopg.connect(_TEST_DSN) as conn:
        _truncate(conn)
        with pytest.raises(KeyError):
            calibrate.load_payload(conn, uuid.uuid4())
