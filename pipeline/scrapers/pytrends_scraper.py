"""Google Trends scraper per ADR-004 (Python-owned source).

Reads candidate full names + active party names from the DB, queries each
through ``pytrends.interest_over_time()`` for ``geo='GT'``, and writes one
``trends`` row per ``(query, observed_at, geo)`` tuple.

Layered so unit tests never touch the live pytrends client:

1. ``load_queries`` — DB-backed query builder (``candidates.full_name`` +
   active ``parties.name``). Accepts an injected ``extra_queries`` list so
   the integration test can pin a small fixture set.
2. ``parse_response`` / ``load_fixture`` — pure parsers turning the
   ``TrendResponse`` JSON shape (one record per query) into typed
   ``TrendRow`` rows.
3. ``insert_row`` + ``run`` — DB writer + orchestrator. ``run`` takes a
   ``fetch_trends`` callable so tests inject an in-memory fetcher and
   never import ``pytrends``.

Rate-limit discipline (CLAUDE.md domain rule #5):

* Minimum ``MIN_SECONDS_BETWEEN_CALLS`` (3.0s) sleep between *successful*
  pytrends requests.
* On ``RateLimitedError`` (HTTP 429 / pytrends ``TooManyRequestsError``)
  the orchestrator sleeps ``THROTTLE_BACKOFF_SECONDS`` (60.0s) before
  retrying the same query exactly once. A second 429 surfaces as an
  exception and the run is marked failed in ``scrape_runs``.

Idempotency: ``trends UNIQUE(query, observed_at, geo)`` plus ON CONFLICT
DO NOTHING. Re-running the same fixture yields zero net inserts.
"""

from __future__ import annotations

import json
import logging
import time
from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

SCRAPE_RUN_SOURCE = "pytrends"
DEFAULT_GEO = "GT"

DEFAULT_FIXTURE_PATH = (
    Path(__file__).parent / "pytrends" / "fixtures" / "sample_response.json"
)

# Per docs/requirement.md + CLAUDE.md domain rule #5:
#   * 60 seconds of sleep between requests once throttled.
#   * 3-5 seconds minimum gap between requests always.
# We use the lower 3s floor so a fresh run completes in reasonable time,
# but the 60s post-throttle backoff is non-negotiable.
MIN_SECONDS_BETWEEN_CALLS = 3.0
THROTTLE_BACKOFF_SECONDS = 60.0


@dataclass(frozen=True)
class TrendRow:
    """One Google Trends datapoint ready to be written to ``trends``."""

    query: str
    observed_at: date
    geo: str
    interest: int


@dataclass(frozen=True)
class RunResult:
    queries_fetched: int
    rows_inserted: int
    rows_skipped: int  # already existed (unique conflict)
    throttle_retries: int  # number of times a 429 was hit + retried


class PytrendsScraperError(RuntimeError):
    """Raised on fixture / response-shape problems the parser can't recover from."""


class RateLimitedError(RuntimeError):
    """Fetcher signals an HTTP 429 / pytrends ``TooManyRequestsError``.

    The orchestrator catches this, sleeps ``THROTTLE_BACKOFF_SECONDS``, and
    retries the same query exactly once.
    """


# ---- Layer 1: DB-backed query builder ------------------------------------


def load_queries(
    conn: Any,
    *,
    extra_queries: Sequence[str] = (),
) -> list[str]:
    """Build the query list: candidate full names + active-party names.

    Deduplicated case-insensitively but the original casing of the first
    occurrence is preserved (so pytrends sees the human-friendly form).
    """
    queries: list[str] = []
    seen: set[str] = set()

    def _add(name: str) -> None:
        normalised = name.strip()
        if not normalised:
            return
        key = normalised.casefold()
        if key in seen:
            return
        seen.add(key)
        queries.append(normalised)

    with conn.cursor() as cur:
        cur.execute("SELECT full_name FROM candidates ORDER BY full_name")
        for (name,) in cur.fetchall():
            if isinstance(name, str):
                _add(name)
        cur.execute(
            "SELECT name FROM parties WHERE status = 'active' ORDER BY name"
        )
        for (name,) in cur.fetchall():
            if isinstance(name, str):
                _add(name)

    for extra in extra_queries:
        _add(extra)

    return queries


# ---- Layer 2: response parser --------------------------------------------


def parse_response(payload: Mapping[str, Any]) -> list[TrendRow]:
    """Convert one ``TrendResponse`` payload into typed ``TrendRow`` rows.

    Payload shape (mirrors a normalised ``pytrends.interest_over_time()``
    DataFrame, one record per query):

        {
          "query": "Sandra Torres",
          "geo": "GT",
          "interest_over_time": [
            {"date": "2026-04-21", "value": 12},
            ...
          ]
        }
    """
    query_raw = payload.get("query")
    if not isinstance(query_raw, str) or not query_raw.strip():
        raise PytrendsScraperError(
            f"response missing non-empty 'query' (got {query_raw!r})"
        )
    query = query_raw.strip()

    geo_raw = payload.get("geo", DEFAULT_GEO)
    if not isinstance(geo_raw, str) or not geo_raw.strip():
        raise PytrendsScraperError(
            f"response for query={query!r} missing non-empty 'geo' "
            f"(got {geo_raw!r})"
        )
    geo = geo_raw.strip()

    series = payload.get("interest_over_time")
    if not isinstance(series, list):
        raise PytrendsScraperError(
            f"response for query={query!r}: 'interest_over_time' must be a list"
        )

    rows: list[TrendRow] = []
    for idx, point in enumerate(series):
        if not isinstance(point, dict):
            raise PytrendsScraperError(
                f"query={query!r} point[{idx}]: expected mapping (got {point!r})"
            )
        date_raw = point.get("date")
        if not isinstance(date_raw, str):
            raise PytrendsScraperError(
                f"query={query!r} point[{idx}]: missing string 'date' "
                f"(got {date_raw!r})"
            )
        try:
            observed_at = date.fromisoformat(date_raw)
        except ValueError as exc:
            raise PytrendsScraperError(
                f"query={query!r} point[{idx}]: invalid ISO date {date_raw!r}: "
                f"{exc}"
            ) from exc
        value_raw = point.get("value")
        if not isinstance(value_raw, int) or isinstance(value_raw, bool):
            raise PytrendsScraperError(
                f"query={query!r} point[{idx}]: 'value' must be int "
                f"(got {value_raw!r})"
            )
        if value_raw < 0 or value_raw > 100:
            raise PytrendsScraperError(
                f"query={query!r} point[{idx}]: value {value_raw} outside 0..100"
            )
        rows.append(
            TrendRow(query=query, observed_at=observed_at, geo=geo, interest=value_raw)
        )
    return rows


def load_fixture(path: Path = DEFAULT_FIXTURE_PATH) -> list[Mapping[str, Any]]:
    """Load the committed sample-response JSON for offline tests / demos."""
    with path.open("r", encoding="utf-8") as fh:
        blob = json.load(fh)
    responses = blob.get("responses")
    if not isinstance(responses, list):
        raise PytrendsScraperError(f"{path}: 'responses' must be a list")
    return [r for r in responses if isinstance(r, dict)]


# ---- Layer 3: DB writer + orchestrator -----------------------------------


def insert_row(conn: Any, row: TrendRow) -> bool:
    """INSERT ON CONFLICT (query, observed_at, geo) DO NOTHING.

    Returns True iff a row was written (False on conflict).
    """
    with conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO trends (query, observed_at, geo, interest)
            VALUES (%s, %s, %s, %s)
            ON CONFLICT (query, observed_at, geo) DO NOTHING
            RETURNING trend_id
            """,
            (row.query, row.observed_at, row.geo, row.interest),
        )
        return cur.fetchone() is not None


def stamp_scrape_run(
    conn: Any,
    source: str = SCRAPE_RUN_SOURCE,
    *,
    success: bool,
    error_message: str | None = None,
) -> None:
    """UPSERT one row into ``scrape_runs`` keyed by this scraper's source."""
    with conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO scrape_runs (source, last_run_at, success, error_message)
            VALUES (%s, now(), %s, %s)
            ON CONFLICT (source) DO UPDATE
              SET last_run_at = EXCLUDED.last_run_at,
                  success = EXCLUDED.success,
                  error_message = EXCLUDED.error_message
            """,
            (source, success, error_message),
        )


# A fetcher returns the normalised TrendResponse mapping for one query.
# Live implementation in ``_default_fetch_trends`` calls pytrends; tests
# inject an in-memory fetcher returning the fixture and never touch
# pytrends.
FetchTrends = Callable[[str, str], Mapping[str, Any]]


def run(
    conn: Any,
    queries: Sequence[str],
    *,
    geo: str = DEFAULT_GEO,
    fetch_trends: FetchTrends | None = None,
    min_seconds_between_calls: float = MIN_SECONDS_BETWEEN_CALLS,
    throttle_backoff_seconds: float = THROTTLE_BACKOFF_SECONDS,
    sleep: Callable[[float], None] = time.sleep,
    monotonic: Callable[[], float] = time.monotonic,
) -> RunResult:
    """End-to-end: for each query, fetch, parse, insert, stamp audit.

    Rate-limit discipline:
      * After a *successful* fetch, sleep ``min_seconds_between_calls`` before
        the next request (CLAUDE.md domain rule #5: ≥3s always).
      * On ``RateLimitedError`` (HTTP 429), sleep ``throttle_backoff_seconds``
        (≥60s) and retry the same query once. A second 429 surfaces as
        an exception and the run is marked failed.

    ``sleep`` and ``monotonic`` are injectable so tests assert the rate-limit
    schedule without waiting.
    """
    if fetch_trends is None:
        fetch_trends = _default_fetch_trends

    queries_fetched = 0
    inserted = 0
    skipped = 0
    throttle_retries = 0
    last_call_at: float | None = None
    try:
        for query in queries:
            if not query.strip():
                continue
            if last_call_at is not None:
                elapsed = monotonic() - last_call_at
                wait = min_seconds_between_calls - elapsed
                if wait > 0:
                    sleep(wait)

            try:
                payload = fetch_trends(query, geo)
            except RateLimitedError:
                logger.warning(
                    "pytrends rate-limited on query=%r; sleeping %.0fs before retry",
                    query,
                    throttle_backoff_seconds,
                )
                sleep(throttle_backoff_seconds)
                throttle_retries += 1
                payload = fetch_trends(query, geo)

            last_call_at = monotonic()
            queries_fetched += 1

            rows = parse_response(payload)
            for row in rows:
                if insert_row(conn, row):
                    inserted += 1
                else:
                    skipped += 1
    except RateLimitedError:
        conn.rollback()
        _safe_stamp(conn, success=False, error_message="rate-limited after retry")
        raise
    except Exception as exc:
        conn.rollback()
        _safe_stamp(conn, success=False, error_message=str(exc)[:500])
        raise
    else:
        conn.commit()
        stamp_scrape_run(conn, success=True)
        conn.commit()

    return RunResult(
        queries_fetched=queries_fetched,
        rows_inserted=inserted,
        rows_skipped=skipped,
        throttle_retries=throttle_retries,
    )


def _safe_stamp(conn: Any, *, success: bool, error_message: str | None) -> None:
    try:
        stamp_scrape_run(conn, success=success, error_message=error_message)
        conn.commit()
    except Exception:
        logger.exception("stamp_scrape_run failed for pytrends")
        conn.rollback()


def _default_fetch_trends(query: str, geo: str) -> Mapping[str, Any]:
    """Live pytrends fetcher. Lazy-imported so tests don't pay the cost.

    Translates ``pytrends.interest_over_time()`` (a pandas DataFrame) into
    the normalised ``TrendResponse`` mapping ``parse_response`` consumes.

    Raises ``RateLimitedError`` when pytrends signals an HTTP 429; the
    orchestrator catches that and applies the 60s backoff.
    """
    try:
        from pytrends.exceptions import TooManyRequestsError  # type: ignore[import-not-found]
        from pytrends.request import TrendReq  # type: ignore[import-not-found]
    except ImportError as exc:
        raise PytrendsScraperError(
            "live pytrends fetcher requires the 'pytrends' package; install "
            "with `uv add pytrends` or pass fetch_trends= to run()"
        ) from exc

    pytrends = TrendReq(hl="es-GT", tz=360)
    try:
        pytrends.build_payload(kw_list=[query], geo=geo, timeframe="today 3-m")
        df = pytrends.interest_over_time()
    except TooManyRequestsError as exc:
        raise RateLimitedError(str(exc)) from exc

    series: list[Mapping[str, Any]] = []
    if df is not None and not df.empty:
        for ts, value in df[query].items():
            series.append(
                {"date": ts.date().isoformat(), "value": int(value)}
            )
    return {"query": query, "geo": geo, "interest_over_time": series}


# Backwards-compat alias.
Run = run


def parse_responses(
    payloads: Iterable[Mapping[str, Any]],
) -> list[TrendRow]:
    """Convenience helper -- parse + flatten a batch of fixture responses."""
    out: list[TrendRow] = []
    for payload in payloads:
        out.extend(parse_response(payload))
    return out


__all__ = [
    "DEFAULT_FIXTURE_PATH",
    "DEFAULT_GEO",
    "MIN_SECONDS_BETWEEN_CALLS",
    "SCRAPE_RUN_SOURCE",
    "THROTTLE_BACKOFF_SECONDS",
    "FetchTrends",
    "PytrendsScraperError",
    "RateLimitedError",
    "Run",
    "RunResult",
    "TrendRow",
    "insert_row",
    "load_fixture",
    "load_queries",
    "parse_response",
    "parse_responses",
    "run",
    "stamp_scrape_run",
]
