"""Tests for the Bluesky firehose-filter scraper (issue #25).

Pure-logic tests (YAML, language filter, parsing, fake-conn dedup) run
unconditionally. The Postgres integration test runs only when
``POLITYK_TEST_DATABASE_URL`` is set so CI without a DB stays green.

No live API calls — ``atproto`` is never imported by these tests.
"""

from __future__ import annotations

import os
from collections.abc import Iterable, Mapping
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest

from pipeline.scrapers import bluesky_scraper as b

# ---- YAML config ---------------------------------------------------------


def test_load_handles_default_file_parses() -> None:
    handles = b.load_handles()
    assert isinstance(handles, frozenset)
    assert len(handles) >= 1
    for h in handles:
        assert not h.startswith("@")


def test_load_handles_rejects_missing_file(tmp_path: Path) -> None:
    with pytest.raises(FileNotFoundError):
        b.load_handles(tmp_path / "does_not_exist.yaml")


def test_load_handles_rejects_at_prefix(tmp_path: Path) -> None:
    p = tmp_path / "bad.yaml"
    p.write_text("handles:\n  - '@prensalibre.bsky.social'\n", encoding="utf-8")
    with pytest.raises(b.BlueskyScraperError, match="leading '@'"):
        b.load_handles(p)


def test_load_handles_rejects_non_string_entry(tmp_path: Path) -> None:
    p = tmp_path / "bad.yaml"
    p.write_text("handles:\n  - 1234\n", encoding="utf-8")
    with pytest.raises(b.BlueskyScraperError, match="non-empty string"):
        b.load_handles(p)


def test_load_handles_rejects_missing_key(tmp_path: Path) -> None:
    p = tmp_path / "bad.yaml"
    p.write_text("not_handles: []\n", encoding="utf-8")
    with pytest.raises(b.BlueskyScraperError, match="handles"):
        b.load_handles(p)


# ---- Language filter -----------------------------------------------------


@pytest.mark.parametrize(
    "langs,expected",
    [
        (["es"], True),
        (["es-GT"], True),
        (["es-419"], True),
        (["en", "es"], True),
        (["ES"], True),
        (["en"], False),
        (["pt-BR"], False),
        ([], False),
        (None, False),
        (["esperanto"], False),  # not an es- prefix variant
    ],
)
def test_is_spanish(langs: Iterable[str] | None, expected: bool) -> None:
    assert b.is_spanish(langs) is expected


# ---- Event filter + parser ----------------------------------------------


ALLOWED = frozenset({"prensalibre.bsky.social", "soy502.bsky.social"})


def _event(
    *,
    handle: str = "prensalibre.bsky.social",
    text: str = "Hola Guatemala",
    langs: list[str] | None = None,
    uri: str = "at://did:plc:abc/app.bsky.feed.post/3kxx2gtgt2c2a",
    created_at: str = "2026-05-21T15:00:00.000Z",
) -> dict[str, Any]:
    return {
        "uri": uri,
        "cid": "bafyfake",
        "author": {"did": "did:plc:abc", "handle": handle},
        "record": {
            "$type": "app.bsky.feed.post",
            "text": text,
            "createdAt": created_at,
            "langs": langs if langs is not None else ["es"],
        },
    }


def test_filter_event_accepts_allowed_spanish_post() -> None:
    assert b.filter_event(_event(), ALLOWED) is True


def test_filter_event_rejects_unknown_handle() -> None:
    assert b.filter_event(_event(handle="random.bsky.social"), ALLOWED) is False


def test_filter_event_rejects_non_spanish() -> None:
    assert b.filter_event(_event(langs=["en"]), ALLOWED) is False


def test_filter_event_rejects_empty_text() -> None:
    assert b.filter_event(_event(text=""), ALLOWED) is False
    assert b.filter_event(_event(text="   "), ALLOWED) is False


def test_filter_event_rejects_missing_record() -> None:
    bad = _event()
    del bad["record"]
    assert b.filter_event(bad, ALLOWED) is False


def test_filter_event_rejects_missing_author() -> None:
    bad = _event()
    del bad["author"]
    assert b.filter_event(bad, ALLOWED) is False


def test_parse_event_happy_path() -> None:
    post = b.parse_event(_event())
    assert post.handle == "prensalibre.bsky.social"
    assert post.source_handle == "@prensalibre.bsky.social"
    assert post.uri.startswith("at://")
    assert post.published_at == datetime(2026, 5, 21, 15, 0, 0, tzinfo=UTC)
    assert post.langs == ("es",)
    assert post.body_text == "Hola Guatemala"


def test_parse_event_bad_created_at_raises() -> None:
    with pytest.raises(b.BlueskyScraperError, match="invalid createdAt"):
        b.parse_event(_event(created_at="not-a-date"))


def test_parse_events_filters_and_parses_stream() -> None:
    events = [
        _event(uri="at://x/1", handle="prensalibre.bsky.social"),
        _event(uri="at://x/2", handle="random.bsky.social"),
        _event(uri="at://x/3", langs=["en"]),
        _event(uri="at://x/4", handle="soy502.bsky.social"),
    ]
    posts = list(b.parse_events(events, ALLOWED))
    assert [p.uri for p in posts] == ["at://x/1", "at://x/4"]


# ---- Fixture ------------------------------------------------------------


def test_load_fixture_parses_committed_sample() -> None:
    events = b.load_fixture()
    assert isinstance(events, list)
    assert len(events) >= 4
    # Walk the full handle allowlist from the live YAML and assert the
    # fixture's filter outcome.
    allowed = b.load_handles()
    posts = list(b.parse_events(events, allowed))
    handles = sorted({p.handle for p in posts})
    # Fixture builds in: 1 GT-Spanish (prensalibre), 1 GT-English (drop),
    # 1 non-GT-English (drop), 1 GT-Spanish (soy502), 1 GT-Spanish-empty (drop).
    assert handles == ["prensalibre.bsky.social", "soy502.bsky.social"]


# ---- Fake-conn DB writer + orchestrator ----------------------------------


class _FakeCursor:
    def __init__(self, urls_already_present: set[str]) -> None:
        self._urls = urls_already_present
        self.insert_calls: list[tuple[Any, ...]] = []
        self.audit_calls: list[tuple[Any, ...]] = []
        self._last_returning: tuple[Any, ...] | None = None

    def execute(self, sql: str, params: tuple[Any, ...]) -> None:
        if "INSERT INTO social_posts" in sql:
            self.insert_calls.append(params)
            url = str(params[2])
            if url in self._urls:
                self._last_returning = None
            else:
                self._urls.add(url)
                self._last_returning = (len(self._urls),)
        elif "INSERT INTO scrape_runs" in sql:
            self.audit_calls.append(params)
            self._last_returning = None
        else:
            self._last_returning = None

    def fetchone(self) -> Any:
        return self._last_returning

    def __enter__(self) -> _FakeCursor:
        return self

    def __exit__(self, *args: object) -> None:
        return None


class _FakeConn:
    def __init__(self, urls_already_present: set[str] | None = None) -> None:
        self.cur = _FakeCursor(urls_already_present or set())
        self.commits = 0
        self.rollbacks = 0

    def cursor(self) -> _FakeCursor:
        return self.cur

    def commit(self) -> None:
        self.commits += 1

    def rollback(self) -> None:
        self.rollbacks += 1


def test_insert_post_new_returns_true() -> None:
    post = b.parse_event(_event())
    conn = _FakeConn()
    assert b.insert_post(conn, post) is True


def test_insert_post_existing_returns_false() -> None:
    post = b.parse_event(_event())
    conn = _FakeConn(urls_already_present={post.uri})
    assert b.insert_post(conn, post) is False


def test_run_orchestrator_filters_inserts_dedups_and_stamps() -> None:
    events = b.load_fixture()
    allowed = b.load_handles()

    conn = _FakeConn()

    def stream() -> Iterable[Mapping[str, Any]]:
        return events

    first = b.run(conn, allowed_handles=allowed, stream_events=stream)
    assert first.events_seen == len(events)
    assert first.events_matched == 2  # see fixture composition
    assert first.posts_inserted == 2
    assert first.posts_skipped == 0
    assert len(conn.cur.audit_calls) == 1
    assert conn.cur.audit_calls[0][1] is True

    # Re-run: same URIs already present, both dedup as skips.
    second = b.run(conn, allowed_handles=allowed, stream_events=stream)
    assert second.posts_inserted == 0
    assert second.posts_skipped == 2


def test_run_orchestrator_max_events_caps_loop() -> None:
    events = b.load_fixture()
    allowed = b.load_handles()
    conn = _FakeConn()

    def stream() -> Iterable[Mapping[str, Any]]:
        return events

    result = b.run(
        conn, allowed_handles=allowed, stream_events=stream, max_events=2
    )
    # We inspect at most 2 raw events. The first fixture event is a match
    # (prensalibre/es), so events_matched should be >= 1 and inserted == 1.
    assert result.events_seen == 2
    assert result.posts_inserted == 1


def test_run_orchestrator_stamps_failure_and_reraises() -> None:
    allowed = frozenset({"prensalibre.bsky.social"})
    conn = _FakeConn()

    def explosive() -> Iterable[Mapping[str, Any]]:
        raise RuntimeError("firehose dropped")

    with pytest.raises(RuntimeError, match="firehose dropped"):
        b.run(conn, allowed_handles=allowed, stream_events=explosive)

    assert conn.rollbacks >= 1
    assert len(conn.cur.audit_calls) == 1
    audit = conn.cur.audit_calls[0]
    assert audit[0] == b.SCRAPE_RUN_SOURCE
    assert audit[1] is False
    assert audit[2] is not None and "firehose dropped" in audit[2]


def test_run_alias_capital_r() -> None:
    """Issue #25 spec spells the entrypoint as ``Run`` — the alias must work."""
    assert b.Run is b.run


def test_live_subscriber_unimplemented_until_atproto_wired() -> None:
    """The live atproto subscriber is intentionally stubbed in this issue.

    The acceptance criterion is fixture-driven testing. When the live
    subscriber lands (a later issue), this test should be deleted along
    with the NotImplementedError.
    """
    with pytest.raises(NotImplementedError, match="live bluesky firehose"):
        list(b._default_stream_events())


# ---- Postgres integration ------------------------------------------------


_TEST_DSN = os.environ.get("POLITYK_TEST_DATABASE_URL")


@pytest.mark.skipif(_TEST_DSN is None, reason="POLITYK_TEST_DATABASE_URL not set")
def test_run_against_postgres_is_idempotent_and_stamps_audit() -> None:
    import psycopg

    assert _TEST_DSN is not None
    events = b.load_fixture()
    allowed = b.load_handles()
    with psycopg.connect(_TEST_DSN) as conn:
        with conn.cursor() as cur:
            cur.execute(
                "TRUNCATE TABLE social_posts, scrape_runs RESTART IDENTITY CASCADE"
            )
        conn.commit()

        def stream() -> Iterable[Mapping[str, Any]]:
            return events

        first = b.run(conn, allowed_handles=allowed, stream_events=stream)
        second = b.run(conn, allowed_handles=allowed, stream_events=stream)

        with conn.cursor() as cur:
            cur.execute(
                "SELECT COUNT(*) FROM social_posts WHERE platform = 'bluesky'"
            )
            count_row = cur.fetchone()
            cur.execute(
                "SELECT source, success, error_message FROM scrape_runs WHERE source = 'bluesky'"
            )
            audit_row = cur.fetchone()

    assert first.posts_inserted == 2
    assert second.posts_inserted == 0
    assert second.posts_skipped == 2
    assert count_row is not None and count_row[0] == 2
    assert audit_row is not None
    assert audit_row[0] == "bluesky"
    assert audit_row[1] is True
    assert audit_row[2] is None
