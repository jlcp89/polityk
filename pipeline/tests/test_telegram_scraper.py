"""Tests for the Telegram public-channel scraper (issue #25).

Pure-logic tests (YAML loading, message parsing, fake-conn dedup) run
unconditionally. The Postgres integration test runs only when
``POLITYK_TEST_DATABASE_URL`` is set so CI without a DB stays green.

No live API calls — telethon is never imported by these tests.
"""

from __future__ import annotations

import os
from collections.abc import Mapping, Sequence
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest

from pipeline.scrapers import telegram_scraper as t

# ---- YAML config ---------------------------------------------------------


def test_load_channels_default_file_parses() -> None:
    channels = t.load_channels()
    assert len(channels) >= 1
    # All entries usable, no leading "@"
    for ch in channels:
        assert not ch.username.startswith("@")
        assert ch.handle == f"@{ch.username}"
        assert ch.label


def test_load_channels_rejects_missing_file(tmp_path: Path) -> None:
    with pytest.raises(FileNotFoundError):
        t.load_channels(tmp_path / "does_not_exist.yaml")


def test_load_channels_rejects_missing_top_level_key(tmp_path: Path) -> None:
    p = tmp_path / "bad.yaml"
    p.write_text("not_channels: []\n", encoding="utf-8")
    with pytest.raises(t.TelegramScraperError, match="channels"):
        t.load_channels(p)


def test_load_channels_rejects_at_prefixed_username(tmp_path: Path) -> None:
    p = tmp_path / "bad.yaml"
    p.write_text(
        "channels:\n  - username: '@prensalibregt'\n    label: Prensa Libre\n",
        encoding="utf-8",
    )
    with pytest.raises(t.TelegramScraperError, match="leading '@'"):
        t.load_channels(p)


def test_load_channels_rejects_duplicate_username(tmp_path: Path) -> None:
    p = tmp_path / "bad.yaml"
    p.write_text(
        "channels:\n"
        "  - {username: dup, label: A}\n"
        "  - {username: dup, label: B}\n",
        encoding="utf-8",
    )
    with pytest.raises(t.TelegramScraperError, match="duplicate"):
        t.load_channels(p)


# ---- Message parsing -----------------------------------------------------


CHANNEL = t.TelegramChannel(username="prensalibregt", label="Prensa Libre")


def _msg(**overrides: Any) -> dict[str, Any]:
    base: dict[str, Any] = {
        "id": 42,
        "date": "2026-05-21T13:42:11+00:00",
        "message": "Hola Guatemala",
        "peer_id": {"_": "PeerChannel", "channel_id": 1},
    }
    base.update(overrides)
    return base


def test_parse_message_happy_path() -> None:
    post = t.parse_message(_msg(), CHANNEL)
    assert post is not None
    assert post.message_id == 42
    assert post.url == "https://t.me/prensalibregt/42"
    assert post.source_handle == "@prensalibregt"
    assert post.body_text == "Hola Guatemala"
    assert post.published_at == datetime(2026, 5, 21, 13, 42, 11, tzinfo=UTC)


def test_parse_message_accepts_datetime_object() -> None:
    when = datetime(2026, 5, 21, 13, 42, 11, tzinfo=UTC)
    post = t.parse_message(_msg(date=when), CHANNEL)
    assert post is not None and post.published_at == when


def test_parse_message_drops_empty_body() -> None:
    assert t.parse_message(_msg(message=""), CHANNEL) is None
    assert t.parse_message(_msg(message="   "), CHANNEL) is None
    assert t.parse_message(_msg(message=None), CHANNEL) is None


def test_parse_message_rejects_missing_id() -> None:
    bad = _msg()
    del bad["id"]
    with pytest.raises(t.TelegramScraperError, match="integer 'id'"):
        t.parse_message(bad, CHANNEL)


def test_parse_message_rejects_bad_date() -> None:
    with pytest.raises(t.TelegramScraperError, match="invalid ISO date"):
        t.parse_message(_msg(date="not-a-date"), CHANNEL)


def test_parse_message_rejects_missing_date() -> None:
    bad = _msg()
    del bad["date"]
    with pytest.raises(t.TelegramScraperError, match="missing 'date'"):
        t.parse_message(bad, CHANNEL)


def test_parse_messages_filters_empties_in_batch() -> None:
    posts = t.parse_messages(
        [
            _msg(id=1, message="Aa"),
            _msg(id=2, message=""),
            _msg(id=3, message="Bb"),
        ],
        CHANNEL,
    )
    assert [p.message_id for p in posts] == [1, 3]


# ---- Fixture ------------------------------------------------------------


def test_load_fixture_parses_committed_sample() -> None:
    channel, msgs = t.load_fixture()
    assert channel.username == "prensalibregt"
    assert isinstance(msgs, list) and len(msgs) >= 3
    # The committed sample includes one empty-body row to exercise filtering.
    parsed = t.parse_messages(msgs, channel)
    assert len(parsed) == len(msgs) - 1
    assert all(p.url.startswith("https://t.me/prensalibregt/") for p in parsed)


# ---- Fake-conn DB writer + rate-limit orchestrator -----------------------


class _FakeCursor:
    def __init__(self, urls_already_present: set[str]) -> None:
        self._urls = urls_already_present
        self.insert_calls: list[tuple[str, ...]] = []
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
    conn = _FakeConn()
    channel, msgs = t.load_fixture()
    posts = t.parse_messages(msgs, channel)
    assert t.insert_post(conn, posts[0]) is True


def test_insert_post_existing_url_returns_false() -> None:
    channel, msgs = t.load_fixture()
    posts = t.parse_messages(msgs, channel)
    conn = _FakeConn(urls_already_present={posts[0].url})
    assert t.insert_post(conn, posts[0]) is False


def test_run_orchestrator_inserts_dedups_and_stamps_audit() -> None:
    channel, msgs = t.load_fixture()
    conn = _FakeConn(urls_already_present=set())

    sleep_calls: list[float] = []

    def fake_fetch(_: t.TelegramChannel) -> Sequence[Mapping[str, Any]]:
        return msgs

    first = t.run(
        conn,
        channels=[channel],
        fetch_messages=fake_fetch,
        sleep=sleep_calls.append,
    )

    # Fixture: 3 non-empty messages, all new.
    assert first.posts_seen == 3
    assert first.posts_inserted == 3
    assert first.posts_skipped == 0
    # First channel doesn't sleep (no prior call).
    assert sleep_calls == []
    # Audit row stamped on success.
    assert len(conn.cur.audit_calls) == 1
    assert conn.cur.audit_calls[0][1] is True  # success=True

    # Re-run: same URLs already present, all 3 dedup as skips.
    second = t.run(
        conn,
        channels=[channel],
        fetch_messages=fake_fetch,
        sleep=sleep_calls.append,
    )
    assert second.posts_inserted == 0
    assert second.posts_skipped == 3


def test_run_orchestrator_rate_limits_between_channels() -> None:
    a = t.TelegramChannel(username="chan_a", label="A")
    b = t.TelegramChannel(username="chan_b", label="B")
    conn = _FakeConn()

    msgs = [
        {
            "id": 1,
            "date": "2026-05-21T13:42:11+00:00",
            "message": "hola",
            "peer_id": {"_": "PeerChannel", "channel_id": 1},
        }
    ]

    def fake_fetch(_: t.TelegramChannel) -> Sequence[Mapping[str, Any]]:
        return msgs

    sleep_calls: list[float] = []
    t.run(
        conn,
        channels=[a, b],
        fetch_messages=fake_fetch,
        min_seconds_between_calls=1.0,
        sleep=sleep_calls.append,
    )

    # One sleep between the two channels.
    assert len(sleep_calls) == 1
    # The wait is positive and ≤ the configured floor.
    assert 0 < sleep_calls[0] <= 1.0


def test_run_orchestrator_stamps_failure_and_reraises() -> None:
    channel = t.TelegramChannel(username="chan", label="C")
    conn = _FakeConn()

    def explosive_fetch(_: t.TelegramChannel) -> Sequence[Mapping[str, Any]]:
        raise RuntimeError("telegram blew up")

    with pytest.raises(RuntimeError, match="telegram blew up"):
        t.run(conn, channels=[channel], fetch_messages=explosive_fetch)

    assert conn.rollbacks >= 1
    assert len(conn.cur.audit_calls) == 1
    audit = conn.cur.audit_calls[0]
    assert audit[0] == t.SCRAPE_RUN_SOURCE
    assert audit[1] is False
    assert audit[2] is not None and "telegram blew up" in audit[2]


def test_run_alias_capital_r() -> None:
    """Issue #25 spec spells the entrypoint as ``Run`` — the alias must work."""
    assert t.Run is t.run


# ---- Postgres integration ------------------------------------------------


_TEST_DSN = os.environ.get("POLITYK_TEST_DATABASE_URL")


@pytest.mark.skipif(_TEST_DSN is None, reason="POLITYK_TEST_DATABASE_URL not set")
def test_run_against_postgres_is_idempotent_and_stamps_audit() -> None:
    import psycopg

    assert _TEST_DSN is not None
    channel, msgs = t.load_fixture()
    with psycopg.connect(_TEST_DSN) as conn:
        with conn.cursor() as cur:
            cur.execute(
                "TRUNCATE TABLE social_posts, scrape_runs RESTART IDENTITY CASCADE"
            )
        conn.commit()

        def fetcher(_: t.TelegramChannel) -> Sequence[Mapping[str, Any]]:
            return msgs

        first = t.run(conn, channels=[channel], fetch_messages=fetcher)
        second = t.run(conn, channels=[channel], fetch_messages=fetcher)

        with conn.cursor() as cur:
            cur.execute(
                "SELECT COUNT(*) FROM social_posts WHERE platform = 'telegram'"
            )
            count_row = cur.fetchone()
            cur.execute(
                "SELECT source, success, error_message FROM scrape_runs WHERE source = 'telegram'"
            )
            audit_row = cur.fetchone()

    assert first.posts_inserted == 3
    assert second.posts_inserted == 0
    assert second.posts_skipped == 3
    assert count_row is not None and count_row[0] == 3
    assert audit_row is not None
    assert audit_row[0] == "telegram"
    assert audit_row[1] is True
    assert audit_row[2] is None
