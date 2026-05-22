"""Bluesky firehose filter + parser per ADR-015.

Subscribes to the AT-Proto Jetstream firehose and keeps only posts that:

1. Originate from a handle on the allowlist
   (``pipeline/scrapers/bluesky/handles.yaml``)
2. Declare Spanish (``es`` or any ``es-*`` regional variant) in the
   record's ``langs`` field

Everything else is dropped *before* deserialisation so memory stays bounded
under firehose load. Matching events are written to ``social_posts`` with
``platform='bluesky'``; the canonical AT-URI is stored as ``url``.

Layers (mirroring the Telegram scraper):

1. ``load_handles`` — YAML config.
2. ``is_spanish`` / ``filter_event`` / ``parse_event`` — pure logic.
3. ``insert_post`` + ``run`` — DB writer + orchestrator. ``run`` takes a
   ``stream_events`` callable for tests (so we don't import ``atproto``).

Idempotency: ``social_posts.url UNIQUE`` plus ON CONFLICT DO NOTHING.
"""

from __future__ import annotations

import json
import logging
from collections.abc import Callable, Iterable, Iterator, Mapping
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

import yaml

logger = logging.getLogger(__name__)

SCRAPE_RUN_SOURCE = "bluesky"
PLATFORM = "bluesky"

DEFAULT_HANDLES_PATH = Path(__file__).parent / "bluesky" / "handles.yaml"
DEFAULT_FIXTURE_PATH = (
    Path(__file__).parent / "bluesky" / "fixtures" / "sample_events.json"
)

# AT-Proto firehose messages we accept. A post is "Spanish" if any declared
# lang starts with "es" — this catches "es", "es-GT", "es-419", etc.
SPANISH_LANG_PREFIX = "es"


@dataclass(frozen=True)
class BlueskyPost:
    """One parsed Bluesky post ready to be written to ``social_posts``."""

    handle: str
    uri: str
    published_at: datetime
    body_text: str
    langs: tuple[str, ...]

    @property
    def source_handle(self) -> str:
        return f"@{self.handle}"


@dataclass(frozen=True)
class RunResult:
    events_seen: int
    events_matched: int
    posts_inserted: int
    posts_skipped: int  # matched but already in DB


class BlueskyScraperError(RuntimeError):
    """Raised on YAML / event-shape problems the parser can't recover from."""


# ---- Layer 1: YAML config ------------------------------------------------


def load_handles(path: Path = DEFAULT_HANDLES_PATH) -> frozenset[str]:
    """Parse the YAML allowlist into a frozenset of handles (no '@' prefix)."""
    if not path.exists():
        raise FileNotFoundError(f"bluesky handles config not found at {path}")
    with path.open("r", encoding="utf-8") as fh:
        raw = yaml.safe_load(fh) or {}
    if not isinstance(raw, dict) or "handles" not in raw:
        raise BlueskyScraperError(
            f"{path}: expected top-level mapping with 'handles' key"
        )
    items = raw["handles"]
    if not isinstance(items, list):
        raise BlueskyScraperError(f"{path}: 'handles' must be a list")
    out: set[str] = set()
    for entry in items:
        if not isinstance(entry, str) or not entry:
            raise BlueskyScraperError(f"{path}: handle entry must be a non-empty string")
        if entry.startswith("@"):
            raise BlueskyScraperError(
                f"{path}: handle {entry!r} must omit the leading '@'"
            )
        out.add(entry)
    return frozenset(out)


# ---- Layer 2: filter + parse --------------------------------------------


def is_spanish(langs: Iterable[str] | None) -> bool:
    """Accept langs containing any ``es`` / ``es-*`` entry; reject empty."""
    if not langs:
        return False
    for raw in langs:
        if not isinstance(raw, str):
            continue
        normalised = raw.strip().lower()
        if normalised == SPANISH_LANG_PREFIX or normalised.startswith(
            SPANISH_LANG_PREFIX + "-"
        ):
            return True
    return False


def _author_handle(event: Mapping[str, Any]) -> str | None:
    author = event.get("author")
    if not isinstance(author, dict):
        return None
    handle = author.get("handle")
    if isinstance(handle, str) and handle:
        return handle
    return None


def _record_langs(event: Mapping[str, Any]) -> tuple[str, ...]:
    record = event.get("record")
    if not isinstance(record, dict):
        return ()
    langs = record.get("langs")
    if not isinstance(langs, list):
        return ()
    return tuple(str(x) for x in langs if isinstance(x, str))


def _record_text(event: Mapping[str, Any]) -> str:
    record = event.get("record")
    if not isinstance(record, dict):
        return ""
    text = record.get("text")
    return text.strip() if isinstance(text, str) else ""


def _record_created_at(event: Mapping[str, Any]) -> str | None:
    record = event.get("record")
    if not isinstance(record, dict):
        return None
    created = record.get("createdAt")
    return created if isinstance(created, str) else None


def filter_event(event: Mapping[str, Any], allowed_handles: frozenset[str]) -> bool:
    """Cheap pre-filter: drop everything not from a watched GT handle in Spanish.

    Runs *before* full deserialisation so the firehose tail stays bounded.
    Empty-body posts also dropped here (no content for sentiment).
    """
    handle = _author_handle(event)
    if handle is None or handle not in allowed_handles:
        return False
    if not is_spanish(_record_langs(event)):
        return False
    if not _record_text(event):
        return False
    return True


def parse_event(event: Mapping[str, Any]) -> BlueskyPost:
    """Convert a filtered event into a typed ``BlueskyPost``.

    Caller is expected to have run ``filter_event`` first; if a required
    field is missing here we raise ``BlueskyScraperError`` because the
    pre-filter should have removed it.
    """
    handle = _author_handle(event)
    if handle is None:
        raise BlueskyScraperError(f"event missing author.handle: {event!r}")
    uri = event.get("uri")
    if not isinstance(uri, str) or not uri:
        raise BlueskyScraperError(f"event missing uri: {event!r}")
    text = _record_text(event)
    if not text:
        raise BlueskyScraperError(f"event {uri}: empty record.text")
    created_at_raw = _record_created_at(event)
    if not created_at_raw:
        raise BlueskyScraperError(f"event {uri}: missing record.createdAt")
    try:
        # AT-Proto serialises createdAt as ISO-8601 with a trailing "Z".
        # Python's fromisoformat handles the offset directly from 3.11.
        published_at = datetime.fromisoformat(created_at_raw.replace("Z", "+00:00"))
    except ValueError as exc:
        raise BlueskyScraperError(
            f"event {uri}: invalid createdAt {created_at_raw!r}: {exc}"
        ) from exc
    return BlueskyPost(
        handle=handle,
        uri=uri,
        published_at=published_at,
        body_text=text,
        langs=_record_langs(event),
    )


def parse_events(
    events: Iterable[Mapping[str, Any]],
    allowed_handles: frozenset[str],
) -> Iterator[BlueskyPost]:
    """Filter + parse a stream of firehose events into typed posts."""
    for event in events:
        if not filter_event(event, allowed_handles):
            continue
        yield parse_event(event)


def load_fixture(path: Path = DEFAULT_FIXTURE_PATH) -> list[Mapping[str, Any]]:
    """Load recorded firehose events from JSON for offline tests / demos."""
    with path.open("r", encoding="utf-8") as fh:
        blob = json.load(fh)
    events = blob.get("events")
    if not isinstance(events, list):
        raise BlueskyScraperError(f"{path}: 'events' must be a list")
    return [e for e in events if isinstance(e, dict)]


# ---- Layer 3: DB writer + orchestrator -----------------------------------


def insert_post(conn: Any, post: BlueskyPost) -> bool:
    """INSERT ON CONFLICT (url) DO NOTHING; return True iff the row was new."""
    with conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO social_posts
                (platform, source_handle, url, published_at, body_text)
            VALUES (%s, %s, %s, %s, %s)
            ON CONFLICT (url) DO NOTHING
            RETURNING post_id
            """,
            (
                PLATFORM,
                post.source_handle,
                post.uri,
                post.published_at,
                post.body_text,
            ),
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


# A stream-events callable yields raw firehose dicts. The live implementation
# in ``_default_stream_events`` subscribes to the AT-Proto Jetstream; tests
# inject an in-memory iterator returning the fixture.
StreamEvents = Callable[[], Iterable[Mapping[str, Any]]]


def run(
    conn: Any,
    *,
    allowed_handles: frozenset[str] | None = None,
    handles_path: Path = DEFAULT_HANDLES_PATH,
    stream_events: StreamEvents | None = None,
    max_events: int | None = None,
) -> RunResult:
    """End-to-end: stream the firehose, filter+parse, insert, stamp audit.

    ``stream_events`` defaults to the live atproto-backed iterator; tests
    pass a finite fixture iterator. ``max_events`` caps how many *raw*
    firehose events are inspected before returning; the live scraper passes
    it so a single ``run`` call exits cleanly under operational supervision.
    """
    if allowed_handles is None:
        allowed_handles = load_handles(handles_path)
    if stream_events is None:
        stream_events = _default_stream_events

    seen = 0
    matched = 0
    inserted = 0
    skipped = 0
    try:
        for event in stream_events():
            seen += 1
            if not filter_event(event, allowed_handles):
                if max_events is not None and seen >= max_events:
                    break
                continue
            post = parse_event(event)
            matched += 1
            if insert_post(conn, post):
                inserted += 1
            else:
                skipped += 1
            if max_events is not None and seen >= max_events:
                break
    except Exception as exc:
        conn.rollback()
        _safe_stamp(conn, success=False, error_message=str(exc)[:500])
        raise
    else:
        conn.commit()
        stamp_scrape_run(conn, success=True)
        conn.commit()

    return RunResult(
        events_seen=seen,
        events_matched=matched,
        posts_inserted=inserted,
        posts_skipped=skipped,
    )


# Backwards-compat alias: the issue spec spells the entrypoint ``Run(...)``.
Run = run


def _safe_stamp(conn: Any, *, success: bool, error_message: str | None) -> None:
    try:
        stamp_scrape_run(conn, success=success, error_message=error_message)
        conn.commit()
    except Exception:
        logger.exception("stamp_scrape_run failed for bluesky")
        conn.rollback()


def _default_stream_events() -> Iterable[Mapping[str, Any]]:
    """Live atproto Jetstream subscriber. Lazy-imported.

    Configured via env vars:
        - ``BLUESKY_JETSTREAM_URL`` (defaults to the public jetstream endpoint)
        - ``BLUESKY_RELAY_SERVICE`` (atproto relay; defaults to bsky.network)
    """
    raise NotImplementedError(
        "live bluesky firehose subscriber not wired in this issue; pass "
        "stream_events= to run() with a recorded fixture or a live atproto "
        "subscriber. See pipeline/scrapers/bluesky/handles.yaml for the "
        "allowlist and the module docstring for the firehose contract."
    )


__all__ = [
    "DEFAULT_FIXTURE_PATH",
    "DEFAULT_HANDLES_PATH",
    "PLATFORM",
    "SCRAPE_RUN_SOURCE",
    "SPANISH_LANG_PREFIX",
    "BlueskyPost",
    "BlueskyScraperError",
    "Run",
    "RunResult",
    "StreamEvents",
    "filter_event",
    "insert_post",
    "is_spanish",
    "load_fixture",
    "load_handles",
    "parse_event",
    "parse_events",
    "run",
    "stamp_scrape_run",
]
