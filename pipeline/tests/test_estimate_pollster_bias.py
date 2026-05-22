"""Tests for `pipeline.scripts.estimate_pollster_bias` (issue #29, ADR-017).

The pure-logic tests (CLI argument parsing, SQL read/write via a fake
conn) run unconditionally. The PyMC fit + ProDatos backtest tests are
gated by ``pytest.importorskip("pymc")`` so the lighter
scraping/scoring layers keep passing without the heavy modelling extra
installed.

End-to-end Postgres tests run only when ``POLITYK_TEST_DATABASE_URL``
is set, mirroring the pattern used by other ``pipeline/tests/test_*``
modules.
"""

from __future__ import annotations

import os
from datetime import UTC, datetime
from typing import Any

import pytest

from pipeline.scripts import estimate_pollster_bias as ebp

# ---------------------------------------------------------------------------
# Pure-logic: CLI argument parsing + helpers
# ---------------------------------------------------------------------------


def test_cli_rejects_missing_cycles(capsys: pytest.CaptureFixture[str]) -> None:
    with pytest.raises(SystemExit) as exc:
        ebp.main(["--draws", "10"])
    assert exc.value.code == 2
    assert "--cycles" in capsys.readouterr().err


def test_cli_rejects_missing_database_url(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("DATABASE_URL", raising=False)
    rc = ebp.main(["--cycles", "2019"])
    assert rc == 2


def test_poll_error_row_computes_signed_error() -> None:
    row = ebp.PollErrorRow(
        pollster_id=1,
        pollster_name="ProDatos",
        cycle=2023,
        candidate_id=42,
        poll_prediction=0.029,
        actual_result=0.155,
    )
    # Matches the DB GENERATED column: prediction - actual.
    assert row.error == pytest.approx(0.029 - 0.155)


# ---------------------------------------------------------------------------
# Pure-logic: read_poll_errors via fake conn
# ---------------------------------------------------------------------------


class _FakeCursor:
    def __init__(self, rows: list[tuple[Any, ...]]) -> None:
        self.executed: list[tuple[str, tuple[Any, ...]]] = []
        self._rows = rows
        self.rowcount = 1

    def execute(self, sql: str, params: tuple[Any, ...] = ()) -> None:
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
    def __init__(self, rows: list[tuple[Any, ...]] | None = None) -> None:
        self.cur = _FakeCursor(rows or [])
        self.committed = False

    def cursor(self) -> _FakeCursor:
        return self.cur

    def commit(self) -> None:
        self.committed = True


def test_read_poll_errors_returns_typed_rows() -> None:
    conn = _FakeConn(
        rows=[
            (2, "ProDatos", 2023, 42, 0.029, 0.155),
            (1, "CID Gallup", 2023, 42, 0.150, 0.155),
        ]
    )
    out = ebp.read_poll_errors(conn, [2023])
    assert len(out) == 2
    assert out[0].pollster_id == 2
    assert out[0].pollster_name == "ProDatos"
    assert out[0].error == pytest.approx(-0.126)
    assert out[1].pollster_name == "CID Gallup"


def test_read_poll_errors_empty_cycles_short_circuits() -> None:
    conn = _FakeConn(rows=[(1, "X", 2019, 1, 0.3, 0.31)])
    out = ebp.read_poll_errors(conn, [])
    # No SQL roundtrip on empty cycles.
    assert out == []
    assert conn.cur.executed == []


def test_read_poll_errors_orders_for_reproducibility() -> None:
    """The SELECT must ORDER BY pollster_id, cycle, candidate_id."""
    conn = _FakeConn(rows=[])
    ebp.read_poll_errors(conn, [2019, 2023])
    sql, _ = conn.cur.executed[0]
    assert "ORDER BY pe.pollster_id, pe.cycle, pe.candidate_id" in sql


# ---------------------------------------------------------------------------
# Pure-logic: write_pollster_estimates idempotency
# ---------------------------------------------------------------------------


class _RecordingCursor(_FakeCursor):
    def __init__(self) -> None:
        super().__init__(rows=[])
        self.rowcount = 1
        self.updates: list[tuple[Any, ...]] = []

    def execute(self, sql: str, params: tuple[Any, ...] = ()) -> None:
        super().execute(sql, params)
        if "UPDATE pollsters" in sql:
            self.updates.append(params)


class _RecordingConn:
    def __init__(self) -> None:
        self.cur = _RecordingCursor()
        self.committed = False

    def cursor(self) -> _RecordingCursor:
        return self.cur

    def commit(self) -> None:
        self.committed = True


def test_write_pollster_estimates_uses_now_when_unset() -> None:
    conn = _RecordingConn()
    est = ebp.PollsterEstimate(
        pollster_id=2,
        pollster_name="ProDatos",
        historical_bias_mean=-0.03,
        historical_bias_sd=0.12,
        sample_count_used=25,
        r_hat_bias=1.001,
        bulk_ess_bias=2400.0,
    )
    n = ebp.write_pollster_estimates(conn, [est])
    assert n == 1
    assert len(conn.cur.updates) == 1
    params = conn.cur.updates[0]
    # ordering: mean, sd, samples, stamp, pollster_id
    assert params[0] == pytest.approx(-0.03)
    assert params[1] == pytest.approx(0.12)
    assert params[2] == 25
    assert isinstance(params[3], datetime)
    assert params[4] == 2


def test_write_pollster_estimates_stamps_each_run() -> None:
    """Acceptance: `bias_last_estimated_at` updated on each run."""
    conn = _RecordingConn()
    est = ebp.PollsterEstimate(
        pollster_id=1,
        pollster_name="CID Gallup",
        historical_bias_mean=0.0,
        historical_bias_sd=0.05,
        sample_count_used=10,
        r_hat_bias=1.002,
        bulk_ess_bias=1900.0,
    )
    stamp = datetime(2026, 5, 22, 12, 0, tzinfo=UTC)
    ebp.write_pollster_estimates(conn, [est], now=stamp)
    assert conn.cur.updates[0][3] == stamp


def test_write_pollster_estimates_idempotent_overwrite() -> None:
    """Same estimates -> same UPDATE SQL each time (idempotent semantics)."""
    conn = _RecordingConn()
    est = ebp.PollsterEstimate(
        pollster_id=3,
        pollster_name="Borge y Asociados",
        historical_bias_mean=0.01,
        historical_bias_sd=0.06,
        sample_count_used=12,
        r_hat_bias=1.000,
        bulk_ess_bias=3000.0,
    )
    stamp = datetime(2026, 5, 22, 12, 0, tzinfo=UTC)
    ebp.write_pollster_estimates(conn, [est], now=stamp)
    ebp.write_pollster_estimates(conn, [est], now=stamp)
    # Same UPDATE column values both times.
    assert conn.cur.updates[0] == conn.cur.updates[1]


# ---------------------------------------------------------------------------
# Pure-logic: fit gracefully rejects an empty dataset
# ---------------------------------------------------------------------------


def test_fit_pollster_bias_rejects_empty_rows() -> None:
    with pytest.raises(ebp.NoPollErrorsError):
        ebp.fit_pollster_bias([])


# ---------------------------------------------------------------------------
# PyMC fit — gated by `pytest.importorskip("pymc")`
# ---------------------------------------------------------------------------


def _make_rows(seed: int = 7) -> list[ebp.PollErrorRow]:
    """Three pollsters: one calibrated, one biased low, one slightly high.

    Three groups (not two) so the partial-pooling hierarchical model's
    population-level ``tau_bias`` is identifiable — with two groups the
    funnel is too sharp and the diagnostics gate fluctuates run-to-run.
    """
    import random

    rng = random.Random(seed)
    rows: list[ebp.PollErrorRow] = []
    specs = [
        (1, "CID Gallup", 0.0, 0.015),
        (2, "ProDatos", -0.04, 0.05),
        (3, "Borge y Asociados", 0.01, 0.02),
    ]
    for cycle in (2007, 2011, 2015, 2019):
        for cand in range(6):
            for pid, name, mu, sd in specs:
                rows.append(
                    ebp.PollErrorRow(
                        pollster_id=pid,
                        pollster_name=name,
                        cycle=cycle,
                        candidate_id=cand + 1,
                        poll_prediction=0.20 + rng.gauss(mu, sd),
                        actual_result=0.20,
                    )
                )
    return rows


@pytest.mark.slow
def test_fit_pollster_bias_recovers_per_pollster_bias_direction() -> None:
    """Synthetic: a known-biased pollster has a negative posterior mean.

    Uses small draws for CI speed but with enough samples to clear the
    `r_hat < 1.01` and `bulk_ess > 400` thresholds on a 48-observation
    fit.
    """
    pytest.importorskip("pymc")

    rows = _make_rows(seed=7)
    result = ebp.fit_pollster_bias(
        rows,
        draws=1500,
        tune=1500,
        chains=4,
        seed=17,
        # Looser ESS threshold for the small-draws fast variant; the
        # production CLI default (400) still applies in #36's gate.
        ess_threshold=200.0,
    )
    assert result.n_observations == len(rows)
    assert result.n_pollsters == 3
    # Diagnostics gate.
    assert result.max_r_hat < 1.01
    by_name = {e.pollster_name: e for e in result.estimates}
    # CID Gallup centred near zero; ProDatos noticeably negative.
    assert abs(by_name["CID Gallup"].historical_bias_mean) < 0.025
    assert by_name["ProDatos"].historical_bias_mean < -0.01
    # ProDatos must have a wider posterior SD than CID Gallup.
    assert by_name["ProDatos"].historical_bias_sd > by_name["CID Gallup"].historical_bias_sd
    # Sample counts equal the raw count per pollster.
    assert by_name["CID Gallup"].sample_count_used == 24
    assert by_name["ProDatos"].sample_count_used == 24
    assert by_name["Borge y Asociados"].sample_count_used == 24


@pytest.mark.slow
def test_fit_pollster_bias_is_reproducible() -> None:
    """Fixed seed -> same per-pollster posterior mean across re-runs."""
    pytest.importorskip("pymc")

    rows = _make_rows(seed=7)
    # Reproducibility only — convergence is exercised in the other slow
    # test. Loosen the rhat gate here because chains=2 is below the
    # production default (4) and gives noisier diagnostics.
    a = ebp.fit_pollster_bias(
        rows,
        draws=1000,
        tune=1000,
        chains=2,
        seed=42,
        ess_threshold=100.0,
        rhat_threshold=1.05,
    )
    b = ebp.fit_pollster_bias(
        rows,
        draws=1000,
        tune=1000,
        chains=2,
        seed=42,
        ess_threshold=100.0,
        rhat_threshold=1.05,
    )
    a_by = {e.pollster_name: e for e in a.estimates}
    b_by = {e.pollster_name: e for e in b.estimates}
    for name in ("CID Gallup", "ProDatos"):
        assert a_by[name].historical_bias_mean == pytest.approx(
            b_by[name].historical_bias_mean, abs=1e-9
        )
        assert a_by[name].historical_bias_sd == pytest.approx(
            b_by[name].historical_bias_sd, abs=1e-9
        )


@pytest.mark.slow
def test_fit_pollster_bias_raises_on_rhat_failure() -> None:
    """Pin the diagnostics gate: an absurdly tight threshold trips the gate."""
    pytest.importorskip("pymc")

    rows = _make_rows(seed=7)
    with pytest.raises(ebp.SamplingDiagnosticsError):
        ebp.fit_pollster_bias(
            rows,
            draws=400,
            tune=400,
            chains=2,
            seed=17,
            rhat_threshold=1.0000001,  # unreachable
            ess_threshold=10.0,
        )


# ---------------------------------------------------------------------------
# Postgres integration
# ---------------------------------------------------------------------------


_TEST_DSN = os.environ.get("POLITYK_TEST_DATABASE_URL")


@pytest.mark.skipif(_TEST_DSN is None, reason="POLITYK_TEST_DATABASE_URL not set")
def test_write_pollster_estimates_round_trips_against_real_db() -> None:
    """Acceptance: writes mean/sd/sample-count + advances timestamp."""
    import psycopg

    assert _TEST_DSN is not None
    with psycopg.connect(_TEST_DSN) as conn:
        # Pick an arbitrary seeded pollster (every seed includes 'CID Gallup').
        with conn.cursor() as cur:
            cur.execute(
                "SELECT pollster_id FROM pollsters WHERE name=%s",
                ("CID Gallup",),
            )
            row = cur.fetchone()
        assert row is not None, "0004_polls seed did not run"
        pid = int(row[0])

        est = ebp.PollsterEstimate(
            pollster_id=pid,
            pollster_name="CID Gallup",
            historical_bias_mean=0.012,
            historical_bias_sd=0.078,
            sample_count_used=42,
            r_hat_bias=1.001,
            bulk_ess_bias=2400.0,
        )
        stamp = datetime(2026, 5, 22, 12, 0, tzinfo=UTC)
        n = ebp.write_pollster_estimates(conn, [est], now=stamp)
        assert n == 1

        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT historical_bias_mean, historical_bias_sd,
                       sample_count_used, bias_last_estimated_at
                  FROM pollsters
                 WHERE pollster_id = %s
                """,
                (pid,),
            )
            row = cur.fetchone()
        assert row is not None
        assert float(row[0]) == pytest.approx(0.012)
        assert float(row[1]) == pytest.approx(0.078)
        assert int(row[2]) == 42
        assert row[3] == stamp

        # Rollback so the test leaves no state behind.
        conn.rollback()
