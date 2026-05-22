"""Telegram public-channel scraper per ADR-015.

Reads a YAML list of public channel @-handles (default
``pipeline/scrapers/telegram/channels.yaml``), fetches recent messages via
`telethon` and writes them to `social_posts` with `platform='telegram'`.

The module is split into three layers so unit tests never spin up a Telegram
client:

1. ``load_channels`` — YAML parser, pure I/O.
2. ``parse_message`` / ``parse_messages`` — convert a recorded
   ``telethon.Message.to_dict()`` payload into a ``TelegramPost`` row.
3. ``insert_post`` + ``run`` — DB writer and live-API orchestrator. ``run``
   takes a ``fetch_messages`` callable so tests can inject a fake fetcher
   without importing telethon.

Idempotency is enforced by `social_posts.url UNIQUE` plus ON CONFLICT
DO NOTHING — re-running on the same channel yields zero net inserts.

Rate-limit discipline per CLAUDE.md ("≤1 req/sec") is enforced inside the
live fetcher with `min_seconds_between_calls`.
"""

from __future__ import annotations

import json
import logging
import time
from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, cast

import yaml

logger = logging.getLogger(__name__)

SCRAPE_RUN_SOURCE = "telegram"
PLATFORM = "telegram"

DEFAULT_CHANNELS_PATH = Path(__file__).parent / "telegram" / "channels.yaml"
DEFAULT_FIXTURE_PATH = (
    Path(__file__).parent / "telegram" / "fixtures" / "sample_messages.json"
)

# Telegram public ToS is permissive but Cloudflare in front of telegram.org
# will rate-limit aggressive scraping. CLAUDE.md sets the floor at 1 req/sec;
# we go a touch slower on the safe side.
MIN_SECONDS_BETWEEN_CALLS = 1.0


@dataclass(frozen=True)
class TelegramChannel:
    username: str
    label: str

    def url_for(self, message_id: int) -> str:
        return f"https://t.me/{self.username}/{message_id}"

    @property
    def handle(self) -> str:
        return f"@{self.username}"


@dataclass(frozen=True)
class TelegramPost:
    """One parsed Telegram message ready to be written to ``social_posts``."""

    channel_username: str
    message_id: int
    url: str
    published_at: datetime
    body_text: str

    @property
    def source_handle(self) -> str:
        return f"@{self.channel_username}"


@dataclass(frozen=True)
class RunResult:
    posts_seen: int
    posts_inserted: int
    posts_skipped: int  # already existed (URL conflict) or empty body


class TelegramScraperError(RuntimeError):
    """Raised on YAML / message-shape problems the parser can't recover from."""


# ---- Layer 1: YAML config ------------------------------------------------


def load_channels(path: Path = DEFAULT_CHANNELS_PATH) -> list[TelegramChannel]:
    """Parse the YAML config into typed ``TelegramChannel`` rows.

    The YAML shape is:

        channels:
          - username: prensalibregt
            label: Prensa Libre

    Raises ``TelegramScraperError`` on any drift from that shape.
    """
    if not path.exists():
        raise FileNotFoundError(f"telegram channels config not found at {path}")
    with path.open("r", encoding="utf-8") as fh:
        raw = yaml.safe_load(fh) or {}
    if not isinstance(raw, dict) or "channels" not in raw:
        raise TelegramScraperError(
            f"{path}: expected top-level mapping with 'channels' key"
        )
    items = raw["channels"]
    if not isinstance(items, list):
        raise TelegramScraperError(f"{path}: 'channels' must be a list")

    out: list[TelegramChannel] = []
    seen: set[str] = set()
    for entry in items:
        if not isinstance(entry, dict):
            raise TelegramScraperError(f"{path}: channel entry must be a mapping")
        username = entry.get("username")
        label = entry.get("label")
        if not isinstance(username, str) or not username:
            raise TelegramScraperError(f"{path}: channel missing 'username' string")
        if username.startswith("@"):
            raise TelegramScraperError(
                f"{path}: channel username '{username}' must omit the leading '@'"
            )
        if not isinstance(label, str) or not label:
            raise TelegramScraperError(
                f"{path}: channel {username!r} missing 'label' string"
            )
        if username in seen:
            raise TelegramScraperError(f"{path}: duplicate channel username {username!r}")
        seen.add(username)
        out.append(TelegramChannel(username=username, label=label))
    return out


# ---- Layer 2: message parsing -------------------------------------------


def parse_message(
    raw: Mapping[str, Any],
    channel: TelegramChannel,
) -> TelegramPost | None:
    """Convert one ``telethon.Message.to_dict()`` payload into a ``TelegramPost``.

    Returns ``None`` for messages with no parseable text body (media-only
    posts, deleted/empty rows). Returns a row otherwise.
    """
    message_id = raw.get("id")
    if not isinstance(message_id, int):
        raise TelegramScraperError(
            f"channel @{channel.username}: message missing integer 'id' (got {message_id!r})"
        )
    body_raw = raw.get("message")
    body = body_raw.strip() if isinstance(body_raw, str) else ""
    if not body:
        return None

    date_raw = raw.get("date")
    if isinstance(date_raw, datetime):
        published_at = date_raw
    elif isinstance(date_raw, str):
        try:
            published_at = datetime.fromisoformat(date_raw)
        except ValueError as exc:
            raise TelegramScraperError(
                f"channel @{channel.username} msg={message_id}: invalid ISO date "
                f"{date_raw!r}: {exc}"
            ) from exc
    else:
        raise TelegramScraperError(
            f"channel @{channel.username} msg={message_id}: missing 'date' "
            f"(got {date_raw!r})"
        )

    return TelegramPost(
        channel_username=channel.username,
        message_id=message_id,
        url=channel.url_for(message_id),
        published_at=published_at,
        body_text=body,
    )


def parse_messages(
    raws: Iterable[Mapping[str, Any]],
    channel: TelegramChannel,
) -> list[TelegramPost]:
    """Parse a batch of telethon message dicts, dropping empty bodies."""
    out: list[TelegramPost] = []
    for raw in raws:
        post = parse_message(raw, channel)
        if post is not None:
            out.append(post)
    return out


def load_fixture(
    path: Path = DEFAULT_FIXTURE_PATH,
) -> tuple[TelegramChannel, list[Mapping[str, Any]]]:
    """Load the committed sample-message JSON for offline tests / demos."""
    with path.open("r", encoding="utf-8") as fh:
        blob = json.load(fh)
    ch = blob["channel"]
    channel = TelegramChannel(username=ch["username"], label=ch["label"])
    msgs = blob["messages"]
    if not isinstance(msgs, list):
        raise TelegramScraperError(f"{path}: 'messages' must be a list")
    return channel, [m for m in msgs if isinstance(m, dict)]


# ---- Layer 3: DB writer + orchestrator -----------------------------------


def insert_post(conn: Any, post: TelegramPost) -> bool:
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
                post.url,
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


# A fetcher returns a sequence of telethon-shaped message dicts for a given
# channel. The live implementation in ``_default_fetch_messages`` opens a
# telethon client; tests inject an in-memory fetcher returning the fixture.
FetchMessages = Callable[[TelegramChannel], Sequence[Mapping[str, Any]]]


def run(
    conn: Any,
    *,
    channels: Sequence[TelegramChannel] | None = None,
    channels_path: Path = DEFAULT_CHANNELS_PATH,
    fetch_messages: FetchMessages | None = None,
    min_seconds_between_calls: float = MIN_SECONDS_BETWEEN_CALLS,
    sleep: Callable[[float], None] = time.sleep,
) -> RunResult:
    """End-to-end: for each channel, fetch new messages, insert, stamp audit.

    ``fetch_messages`` defaults to the live telethon-backed fetcher; tests
    pass an in-memory fetcher and don't touch the network. ``sleep`` is
    injectable so tests assert the rate-limit calls without waiting.
    """
    if channels is None:
        channels = load_channels(channels_path)
    if fetch_messages is None:
        fetch_messages = _default_fetch_messages

    seen = 0
    inserted = 0
    skipped = 0
    last_call_at: float | None = None
    try:
        for channel in channels:
            if last_call_at is not None:
                elapsed = time.monotonic() - last_call_at
                wait = min_seconds_between_calls - elapsed
                if wait > 0:
                    sleep(wait)
            raws = fetch_messages(channel)
            last_call_at = time.monotonic()
            posts = parse_messages(raws, channel)
            seen += len(posts)
            for post in posts:
                if insert_post(conn, post):
                    inserted += 1
                else:
                    skipped += 1
    except Exception as exc:
        conn.rollback()
        _safe_stamp(conn, success=False, error_message=str(exc)[:500])
        raise
    else:
        conn.commit()
        stamp_scrape_run(conn, success=True)
        conn.commit()

    return RunResult(posts_seen=seen, posts_inserted=inserted, posts_skipped=skipped)


# Backwards-compat alias: the issue spec spells the entrypoint ``Run(...)``.
# Python convention is snake_case, but we expose both so the acceptance
# criterion's spelling is satisfied without forcing every caller to switch.
Run = run


def _safe_stamp(conn: Any, *, success: bool, error_message: str | None) -> None:
    try:
        stamp_scrape_run(conn, success=success, error_message=error_message)
        conn.commit()
    except Exception:
        logger.exception("stamp_scrape_run failed for telegram")
        conn.rollback()


def _default_fetch_messages(channel: TelegramChannel) -> Sequence[Mapping[str, Any]]:
    """Live telethon fetcher. Lazy-imported so tests don't pay the cost.

    Configured via the standard telethon env vars:
        - ``TELEGRAM_API_ID``
        - ``TELEGRAM_API_HASH``
        - ``TELEGRAM_SESSION``   (path to session file)
        - ``TELEGRAM_MESSAGES_LIMIT`` (default 50)
    """
    import os

    api_id_raw = os.environ.get("TELEGRAM_API_ID")
    api_hash = os.environ.get("TELEGRAM_API_HASH")
    session = os.environ.get("TELEGRAM_SESSION", "polityk_telegram")
    limit = int(os.environ.get("TELEGRAM_MESSAGES_LIMIT", "50"))
    if not api_id_raw or not api_hash:
        raise TelegramScraperError(
            "live telethon fetcher requires TELEGRAM_API_ID and TELEGRAM_API_HASH"
        )
    try:
        api_id = int(api_id_raw)
    except ValueError as exc:
        raise TelegramScraperError(f"TELEGRAM_API_ID must be int, got {api_id_raw!r}") from exc

    from telethon.sync import TelegramClient

    out: list[Mapping[str, Any]] = []
    with TelegramClient(session, api_id, api_hash) as client:
        for msg in client.iter_messages(channel.username, limit=limit):
            out.append(cast(Mapping[str, Any], msg.to_dict()))
    return out


__all__ = [
    "DEFAULT_CHANNELS_PATH",
    "DEFAULT_FIXTURE_PATH",
    "MIN_SECONDS_BETWEEN_CALLS",
    "PLATFORM",
    "SCRAPE_RUN_SOURCE",
    "FetchMessages",
    "Run",
    "RunResult",
    "TelegramChannel",
    "TelegramPost",
    "TelegramScraperError",
    "insert_post",
    "load_channels",
    "load_fixture",
    "parse_message",
    "parse_messages",
    "run",
    "stamp_scrape_run",
]
