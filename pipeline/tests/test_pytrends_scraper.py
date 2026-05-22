"""Tests for the pytrends Google Trends scraper (issue #24).

Pure-logic tests (fixture parse, fake-conn dedup, rate-limit schedule) run
unconditionally. The Postgres integration test runs only when
``POLITYK_TEST_DATABASE_URL`` is set, so CI without a DB stays green.

No live pytrends calls -- ``pytrends`` is never imported by these tests.
"""

from __future__ import annotations

import os
from collections.abc import Mapping
from datetime import date
from pathlib import Path
from typing import Any

import pytest

from pipeline.scrapers import pytrends_scraper as p

# ---- Fixture parser ------------------------------------------------------


def test_load_fixture_default_file_parses() -> None:
    responses = p.load_fixture()
    assert isinstance(responses, list)
    assert len(responses) >= 1
    # Every response has a non-empty interest_over_time series.
    for r in responses:
        assert isinstance(r["query"], str) and r["query"]
        assert isinstance(r["interest_over_time"], list)
        assert len(r["interest_over_time"]) > 0


def test_parse_response_happy_path() -> None:
    payload: Mapping[str, Any] = {
        "query": "Sandra Torres",
        "geo": "GT",
        "interest_over_time": [
            {"date": "2026-05-10", "value": 64},
            {"date": "2026-05-17", "value": 72},
        ],
    }
    rows = p.parse_response(payload)
    assert len(rows) == 2
    assert rows[0] == p.TrendRow(
        query="Sandra Torres",
        observed_at=date(2026, 5, 10),
        geo="GT",
        interest=64,
    )
    assert rows[1].interest == 72


def test_parse_response_defaults_geo_when_omitted() -> None:
    rows = p.parse_response(
        {
            "query": "Bernardo Arevalo",
            "interest_over_time": [{"date": "2026-01-01", "value": 10}],
        }
    )
    assert rows[0].geo == p.DEFAULT_GEO == "GT"


def test_parse_response_rejects_empty_query() -> None:
    with pytest.raises(p.PytrendsScraperError, match="missing non-empty 'query'"):
        p.parse_response({"query": "", "interest_over_time": []})


def test_parse_response_rejects_bad_date() -> None:
    with pytest.raises(p.PytrendsScraperError, match="invalid ISO date"):
        p.parse_response(
            {
                "query": "Sandra Torres",
                "interest_over_time": [{"date": "not-a-date", "value": 10}],
            }
        )


def test_parse_response_rejects_out_of_range_interest() -> None:
    with pytest.raises(p.PytrendsScraperError, match="outside 0..100"):
        p.parse_response(
            {
                "query": "Sandra Torres",
                "interest_over_time": [{"date": "2026-05-01", "value": 101}],
            }
        )


def test_parse_response_rejects_non_int_value() -> None:
    with pytest.raises(p.PytrendsScraperError, match="must be int"):
        p.parse_response(
            {
                "query": "Sandra Torres",
                "interest_over_time": [{"date": "2026-05-01", "value": "12"}],
            }
        )


def test_parse_response_rejects_bool_value_masquerading_as_int() -> None:
    with pytest.raises(p.PytrendsScraperError, match="must be int"):
        p.parse_response(
            {
                "query": "Sandra Torres",
                "interest_over_time": [{"date": "2026-05-01", "value": True}],
            }
        )


def test_parse_responses_flattens_batch() -> None:
    responses = p.load_fixture()
    rows = p.parse_responses(responses)
    queries_in_rows = {r.query for r in rows}
    queries_in_fixture = {r["query"] for r in responses}
    assert queries_in_rows == queries_in_fixture


# ---- Fake-conn DB writer + orchestrator ---------------------------------


class _FakeCursor:
    def __init__(
        self,
        rows_already_present: set[tuple[str, date, str]],
        candidates: list[str],
        parties: list[str],
    ) -> None:
        self._rows = rows_already_present
        self._candidates = candidates
        self._parties = parties
        self.insert_calls: list[tuple[Any, ...]] = []
        self.audit_calls: list[tuple[Any, ...]] = []
        self._last_returning: tuple[Any, ...] | None = None
        self._last_select: list[tuple[Any, ...]] = []

    def execute(self, sql: str, params: tuple[Any, ...] | None = None) -> None:
        sql_norm = " ".join(sql.split())
        if "INSERT INTO trends" in sql_norm:
            assert params is not None
            self.insert_calls.append(params)
            key = (str(params[0]), params[1], str(params[2]))
            if key in self._rows:
                self._last_returning = None
            else:
                self._rows.add(key)
                self._last_returning = (len(self._rows),)
        elif "INSERT INTO scrape_runs" in sql_norm:
            assert params is not None
            self.audit_calls.append(params)
            self._last_returning = None
        elif "FROM candidates" in sql_norm:
            self._last_select = [(c,) for c in self._candidates]
            self._last_returning = None
        elif "FROM parties" in sql_norm:
            self._last_select = [(pname,) for pname in self._parties]
            self._last_returning = None
        else:
            self._last_returning = None
            self._last_select = []

    def fetchone(self) -> Any:
        return self._last_returning

    def fetchall(self) -> list[tuple[Any, ...]]:
        return list(self._last_select)

    def __enter__(self) -> _FakeCursor:
        return self

    def __exit__(self, *args: object) -> None:
        return None


class _FakeConn:
    def __init__(
        self,
        rows_already_present: set[tuple[str, date, str]] | None = None,
        candidates: list[str] | None = None,
        parties: list[str] | None = None,
    ) -> None:
        self.cur = _FakeCursor(
            rows_already_present or set(),
            candidates or [],
            parties or [],
        )
        self.commits = 0
        self.rollbacks = 0

    def cursor(self) -> _FakeCursor:
        return self.cur

    def commit(self) -> None:
        self.commits += 1

    def rollback(self) -> None:
        self.rollbacks += 1


# ---- load_queries (DB-backed builder) -----------------------------------


def test_load_queries_reads_candidates_and_active_parties() -> None:
    conn = _FakeConn(
        candidates=["Sandra Torres", "Bernardo Arevalo"],
        parties=["UNE", "Movimiento Semilla"],
    )
    queries = p.load_queries(conn)
    assert queries == [
        "Sandra Torres",
        "Bernardo Arevalo",
        "UNE",
        "Movimiento Semilla",
    ]


def test_load_queries_dedups_case_insensitively() -> None:
    conn = _FakeConn(
        candidates=["Sandra Torres"],
        parties=["sandra torres"],  # alias overlap
    )
    queries = p.load_queries(conn)
    assert queries == ["Sandra Torres"]


def test_load_queries_appends_extras() -> None:
    conn = _FakeConn(candidates=[], parties=[])
    queries = p.load_queries(conn, extra_queries=["TSE", "elecciones 2027"])
    assert queries == ["TSE", "elecciones 2027"]


def test_load_queries_strips_blank() -> None:
    conn = _FakeConn(candidates=["", "  ", "Sandra Torres"], parties=[])
    assert p.load_queries(conn) == ["Sandra Torres"]


# ---- insert_row ---------------------------------------------------------


def test_insert_row_new_returns_true() -> None:
    conn = _FakeConn()
    row = p.TrendRow(
        query="Sandra Torres", observed_at=date(2026, 5, 17), geo="GT", interest=72
    )
    assert p.insert_row(conn, row) is True


def test_insert_row_existing_returns_false() -> None:
    row = p.TrendRow(
        query="Sandra Torres", observed_at=date(2026, 5, 17), geo="GT", interest=72
    )
    conn = _FakeConn(
        rows_already_present={(row.query, row.observed_at, row.geo)},
    )
    assert p.insert_row(conn, row) is False


# ---- Run orchestrator: rate-limit schedule + 429 backoff ----------------


class _FakeClock:
    """Monotonic clock that advances only when sleep() is called.

    Lets tests pin the exact post-sleep state without real wallclock waits.
    """

    def __init__(self) -> None:
        self.now = 1000.0
        self.sleep_calls: list[float] = []

    def sleep(self, seconds: float) -> None:
        self.sleep_calls.append(seconds)
        self.now += seconds

    def monotonic(self) -> float:
        return self.now


def _fixture_payload(query: str) -> Mapping[str, Any]:
    return {
        "query": query,
        "geo": "GT",
        "interest_over_time": [{"date": "2026-05-17", "value": 50}],
    }


def test_run_sleeps_at_least_3s_between_successful_requests() -> None:
    conn = _FakeConn()
    clock = _FakeClock()
    queries = ["A", "B", "C"]

    def fetch(query: str, geo: str) -> Mapping[str, Any]:
        return _fixture_payload(query)

    result = p.run(
        conn,
        queries,
        fetch_trends=fetch,
        sleep=clock.sleep,
        monotonic=clock.monotonic,
    )
    assert result.queries_fetched == 3
    assert result.rows_inserted == 3
    # 3 queries -> 2 inter-call sleeps, each >= 3.0s (the MIN floor).
    inter_call_sleeps = [s for s in clock.sleep_calls if s < p.THROTTLE_BACKOFF_SECONDS]
    assert len(inter_call_sleeps) == 2
    for waited in inter_call_sleeps:
        assert waited >= p.MIN_SECONDS_BETWEEN_CALLS == 3.0
    # No throttle sleeps.
    assert all(s < p.THROTTLE_BACKOFF_SECONDS for s in clock.sleep_calls)


def test_run_sleeps_60s_on_429_then_retries_once() -> None:
    conn = _FakeConn()
    clock = _FakeClock()
    queries = ["A"]
    attempts = {"count": 0}

    def fetch(query: str, geo: str) -> Mapping[str, Any]:
        attempts["count"] += 1
        if attempts["count"] == 1:
            raise p.RateLimitedError("HTTP 429 from pytrends")
        return _fixture_payload(query)

    result = p.run(
        conn,
        queries,
        fetch_trends=fetch,
        sleep=clock.sleep,
        monotonic=clock.monotonic,
    )
    assert result.throttle_retries == 1
    assert result.queries_fetched == 1
    assert result.rows_inserted == 1
    assert attempts["count"] == 2
    # At least one sleep call was for the 60s backoff.
    long_sleeps = [s for s in clock.sleep_calls if s >= p.THROTTLE_BACKOFF_SECONDS]
    assert long_sleeps and long_sleeps[0] >= 60.0


def test_run_second_429_propagates_and_stamps_failure() -> None:
    conn = _FakeConn()
    clock = _FakeClock()

    def always_throttled(query: str, geo: str) -> Mapping[str, Any]:
        raise p.RateLimitedError("HTTP 429")

    with pytest.raises(p.RateLimitedError):
        p.run(
            conn,
            ["A"],
            fetch_trends=always_throttled,
            sleep=clock.sleep,
            monotonic=clock.monotonic,
        )
    # One audit row written, success=False, message references rate-limit.
    assert len(conn.cur.audit_calls) == 1
    audit = conn.cur.audit_calls[0]
    assert audit[0] == p.SCRAPE_RUN_SOURCE
    assert audit[1] is False
    assert audit[2] and "rate-limited" in audit[2]


def test_run_stamps_failure_on_arbitrary_exception() -> None:
    conn = _FakeConn()
    clock = _FakeClock()

    def boom(query: str, geo: str) -> Mapping[str, Any]:
        raise RuntimeError("network down")

    with pytest.raises(RuntimeError, match="network down"):
        p.run(
            conn,
            ["A"],
            fetch_trends=boom,
            sleep=clock.sleep,
            monotonic=clock.monotonic,
        )
    assert conn.rollbacks >= 1
    assert len(conn.cur.audit_calls) == 1
    audit = conn.cur.audit_calls[0]
    assert audit[1] is False
    assert audit[2] and "network down" in audit[2]


def test_run_dedups_against_already_present_rows() -> None:
    """ON CONFLICT DO NOTHING returns False for the second hit on the same key."""
    rows_present: set[tuple[str, date, str]] = {
        ("Sandra Torres", date(2026, 5, 17), "GT"),
    }
    conn = _FakeConn(rows_already_present=rows_present)
    clock = _FakeClock()

    def fetch(query: str, geo: str) -> Mapping[str, Any]:
        return _fixture_payload(query)

    result = p.run(
        conn,
        ["Sandra Torres"],
        fetch_trends=fetch,
        sleep=clock.sleep,
        monotonic=clock.monotonic,
    )
    assert result.rows_inserted == 0
    assert result.rows_skipped == 1


def test_run_uses_fixture_responses_end_to_end() -> None:
    """Fixture-driven smoke test -- the acceptance criterion."""
    responses = {r["query"]: r for r in p.load_fixture()}
    conn = _FakeConn()
    clock = _FakeClock()

    def fetch(query: str, geo: str) -> Mapping[str, Any]:
        return responses[query]

    result = p.run(
        conn,
        list(responses.keys()),
        fetch_trends=fetch,
        sleep=clock.sleep,
        monotonic=clock.monotonic,
    )
    expected_rows = sum(len(r["interest_over_time"]) for r in responses.values())
    assert result.queries_fetched == len(responses)
    assert result.rows_inserted == expected_rows
    assert result.rows_skipped == 0
    assert len(conn.cur.audit_calls) == 1
    assert conn.cur.audit_calls[0][1] is True


def test_run_skips_blank_queries() -> None:
    conn = _FakeConn()
    clock = _FakeClock()

    def fetch(query: str, geo: str) -> Mapping[str, Any]:
        return _fixture_payload(query)

    result = p.run(
        conn,
        ["", "  ", "Sandra Torres"],
        fetch_trends=fetch,
        sleep=clock.sleep,
        monotonic=clock.monotonic,
    )
    assert result.queries_fetched == 1


def test_run_alias_capital_r() -> None:
    """Issue #24 keeps the bluesky/telegram convention of a Run alias."""
    assert p.Run is p.run


def test_live_fetcher_requires_pytrends_package(monkeypatch: pytest.MonkeyPatch) -> None:
    """The live fetcher raises a clear PytrendsScraperError when pytrends is missing.

    We don't depend on the optional pytrends package at this layer; the
    error surface is what gets exercised in CI.
    """
    import builtins

    real_import = builtins.__import__

    def fake_import(
        name: str,
        globals: Mapping[str, Any] | None = None,
        locals: Mapping[str, Any] | None = None,
        fromlist: tuple[str, ...] = (),
        level: int = 0,
    ) -> Any:
        if name.startswith("pytrends"):
            raise ImportError("simulated missing pytrends")
        return real_import(name, globals, locals, fromlist, level)

    monkeypatch.setattr(builtins, "__import__", fake_import)

    with pytest.raises(p.PytrendsScraperError, match="pytrends"):
        p._default_fetch_trends("Sandra Torres", "GT")


# ---- Postgres integration ------------------------------------------------


_TEST_DSN = os.environ.get("POLITYK_TEST_DATABASE_URL")


@pytest.mark.skipif(_TEST_DSN is None, reason="POLITYK_TEST_DATABASE_URL not set")
def test_run_against_postgres_is_idempotent_and_stamps_audit() -> None:
    import psycopg

    assert _TEST_DSN is not None
    responses = {r["query"]: r for r in p.load_fixture()}

    with psycopg.connect(_TEST_DSN) as conn:
        with conn.cursor() as cur:
            cur.execute("TRUNCATE TABLE trends RESTART IDENTITY CASCADE")
            cur.execute("DELETE FROM scrape_runs WHERE source = 'pytrends'")
        conn.commit()

        def fetch(query: str, geo: str) -> Mapping[str, Any]:
            return responses[query]

        # First run inserts everything.
        first = p.run(
            conn,
            list(responses.keys()),
            fetch_trends=fetch,
            min_seconds_between_calls=0.0,  # no need to wait in tests
            sleep=lambda _: None,
        )
        # Second run is a no-op (ON CONFLICT DO NOTHING).
        second = p.run(
            conn,
            list(responses.keys()),
            fetch_trends=fetch,
            min_seconds_between_calls=0.0,
            sleep=lambda _: None,
        )

        with conn.cursor() as cur:
            cur.execute("SELECT COUNT(*) FROM trends")
            count_row = cur.fetchone()
            cur.execute(
                "SELECT source, success, error_message "
                "FROM scrape_runs WHERE source = 'pytrends'"
            )
            audit_row = cur.fetchone()

    expected_rows = sum(len(r["interest_over_time"]) for r in responses.values())
    assert first.rows_inserted == expected_rows
    assert second.rows_inserted == 0
    assert second.rows_skipped == expected_rows
    assert count_row is not None and count_row[0] == expected_rows
    assert audit_row is not None
    assert audit_row[0] == "pytrends"
    assert audit_row[1] is True
    assert audit_row[2] is None


@pytest.mark.skipif(_TEST_DSN is None, reason="POLITYK_TEST_DATABASE_URL not set")
def test_trends_unique_constraint_enforced_at_schema_level() -> None:
    """A raw INSERT bypassing the scraper still trips the UNIQUE key."""
    import psycopg

    assert _TEST_DSN is not None
    with psycopg.connect(_TEST_DSN) as conn:
        with conn.cursor() as cur:
            cur.execute("TRUNCATE TABLE trends RESTART IDENTITY CASCADE")
            cur.execute(
                "INSERT INTO trends (query, observed_at, geo, interest) "
                "VALUES (%s, %s, %s, %s)",
                ("Sandra Torres", date(2026, 5, 17), "GT", 72),
            )
            with pytest.raises(psycopg.errors.UniqueViolation):
                cur.execute(
                    "INSERT INTO trends (query, observed_at, geo, interest) "
                    "VALUES (%s, %s, %s, %s)",
                    ("Sandra Torres", date(2026, 5, 17), "GT", 80),
                )
        conn.rollback()


@pytest.mark.skipif(_TEST_DSN is None, reason="POLITYK_TEST_DATABASE_URL not set")
def test_trends_check_constraints_reject_out_of_range_interest(tmp_path: Path) -> None:
    import psycopg

    assert _TEST_DSN is not None
    with psycopg.connect(_TEST_DSN) as conn:
        with conn.cursor() as cur:
            cur.execute("TRUNCATE TABLE trends RESTART IDENTITY CASCADE")
            with pytest.raises(psycopg.errors.CheckViolation):
                cur.execute(
                    "INSERT INTO trends (query, observed_at, geo, interest) "
                    "VALUES (%s, %s, %s, %s)",
                    ("Sandra Torres", date(2026, 5, 17), "GT", 200),
                )
        conn.rollback()
