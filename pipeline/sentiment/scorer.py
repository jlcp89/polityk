"""Per-sentence × per-entity sentiment scorer (ADR-011 / ADR-015, issue #28).

For each new ``news_articles`` and ``social_posts`` row this module:

1. Splits the text into sentences (spaCy when available, deterministic
   regex fallback otherwise).
2. Resolves Guatemalan candidate / party mentions per sentence via
   :class:`pipeline.sentiment.entity_resolver.EntityResolver`.
3. Scores each sentence with pysentimiento (BETO base, FP32 -- see
   CLAUDE.md, INT8 only if throughput becomes the bottleneck).
4. Writes one ``sentiment_scores`` row per
   ``(source_kind, source_id, sentence_index, subject_kind, subject_id)``.
   If no entity resolves in a sentence an "overall" row is written with
   ``subject_id = NULL``.

At the end of each batch the materialised view
``sentiment_per_source_subject`` (migration 0009) is refreshed so the
fundamentals layer (#31) sees the new aggregates.

Layering mirrors the other Python scrapers (pytrends/bluesky/telegram) so
unit tests never load BETO or spaCy:

1. ``split_sentences`` / ``ScoringBackend`` -- pure functions / Protocol.
2. ``score_text`` -- given pre-split sentences + resolved mentions + a
   backend, returns the list of ``SentimentRow`` rows for one source.
3. ``insert_row`` / ``refresh_matview`` -- DB writers.
4. ``run`` -- orchestrator. Accepts injected iter_articles / iter_posts
   + backend + sentence_splitter so the integration test pins fixtures.
"""

from __future__ import annotations

import logging
import re
from collections.abc import Callable, Iterable, Sequence
from dataclasses import dataclass
from typing import Any, Protocol

from pipeline.sentiment.entity_resolver import EntityResolver, Mention

logger = logging.getLogger(__name__)

SOURCE_KIND_ARTICLE = "article"
SOURCE_KIND_POST = "post"
SUBJECT_KIND_OVERALL = "overall"

LABEL_POS = "POS"
LABEL_NEG = "NEG"
LABEL_NEU = "NEU"
_VALID_LABELS = frozenset({LABEL_POS, LABEL_NEG, LABEL_NEU})

# The ``score`` column stores signed valence in [-1, 1]:
#     score = P(POS) - P(NEG)
# That lines up with the fundamentals-layer feature spec'd in #31
# ("rolling 30-day differential POS-NEG share per candidate").
SCORE_MIN = -1.0
SCORE_MAX = 1.0

# Deterministic regex sentence splitter used when spaCy isn't installed.
# Splits on ``.``, ``!``, ``?``, ``…`` followed by whitespace -- conservative
# enough for Spanish news headlines + body text. Trailing/leading whitespace
# is stripped; empty fragments are skipped.
_SENTENCE_SPLIT_RE = re.compile(r"(?<=[\.\!\?…])\s+")


@dataclass(frozen=True)
class ScoredSentence:
    """One pysentimiento (or test stub) output for a single sentence."""

    label: str
    score: float

    def __post_init__(self) -> None:
        if self.label not in _VALID_LABELS:
            raise ValueError(
                f"label must be one of {sorted(_VALID_LABELS)}, got {self.label!r}"
            )
        if not (SCORE_MIN <= self.score <= SCORE_MAX):
            raise ValueError(
                f"score must be in [{SCORE_MIN}, {SCORE_MAX}], got {self.score!r}"
            )


@dataclass(frozen=True)
class SentimentRow:
    """One row destined for ``sentiment_scores``."""

    source_kind: str
    source_id: int
    sentence_index: int
    subject_kind: str
    subject_id: int | None
    score: float
    label: str
    model_version: str


@dataclass(frozen=True)
class SourceText:
    """A piece of text to score: title and body fused into one document.

    Used by the orchestrator to iterate over un-scored ``news_articles`` and
    ``social_posts`` rows without coupling the caller to either schema.
    """

    source_kind: str
    source_id: int
    text: str


@dataclass(frozen=True)
class RunResult:
    articles_scored: int
    posts_scored: int
    sentences_scored: int
    rows_inserted: int
    rows_skipped: int  # already existed (UNIQUE conflict)


class SentimentScorerError(RuntimeError):
    """Raised on input-shape / backend-load problems the scorer can't recover."""


# ---- Layer 1: sentence splitter + scoring backend ------------------------


def split_sentences(text: str) -> list[str]:
    """Deterministic sentence splitter. Used unless a spaCy splitter is injected.

    Strips empties, preserves order. Idempotent on already-trimmed input.
    """
    if not text or not text.strip():
        return []
    fragments = _SENTENCE_SPLIT_RE.split(text)
    return [f.strip() for f in fragments if f and f.strip()]


class ScoringBackend(Protocol):
    """Score one sentence. Implementations: pysentimiento, test fakes."""

    model_version: str

    def score(self, sentence: str) -> ScoredSentence: ...


SentenceSplitter = Callable[[str], list[str]]


# ---- Layer 2: per-source scoring ----------------------------------------


def score_source_text(
    source: SourceText,
    *,
    resolver: EntityResolver,
    backend: ScoringBackend,
    sentence_splitter: SentenceSplitter = split_sentences,
) -> list[SentimentRow]:
    """Score one document end-to-end, yielding rows for ``sentiment_scores``.

    For each sentence:

    * If the entity resolver returns ≥1 mentions, emit one row per
      ``(subject_kind, subject_id)`` mention (deduped).
    * Otherwise emit one "overall" row (``subject_kind='overall'``,
      ``subject_id=None``).
    """
    sentences = sentence_splitter(source.text)
    rows: list[SentimentRow] = []
    for idx, sentence in enumerate(sentences):
        scored = backend.score(sentence)
        mentions = resolver.resolve(sentence)
        subjects = _dedup_subjects(mentions)
        if not subjects:
            rows.append(
                SentimentRow(
                    source_kind=source.source_kind,
                    source_id=source.source_id,
                    sentence_index=idx,
                    subject_kind=SUBJECT_KIND_OVERALL,
                    subject_id=None,
                    score=scored.score,
                    label=scored.label,
                    model_version=backend.model_version,
                )
            )
            continue
        for subject_kind, subject_id in subjects:
            rows.append(
                SentimentRow(
                    source_kind=source.source_kind,
                    source_id=source.source_id,
                    sentence_index=idx,
                    subject_kind=subject_kind,
                    subject_id=subject_id,
                    score=scored.score,
                    label=scored.label,
                    model_version=backend.model_version,
                )
            )
    return rows


def _dedup_subjects(mentions: Iterable[Mention]) -> list[tuple[str, int]]:
    seen: set[tuple[str, int]] = set()
    out: list[tuple[str, int]] = []
    for m in mentions:
        key = (m.subject_kind, m.subject_id)
        if key in seen:
            continue
        seen.add(key)
        out.append(key)
    return out


# ---- Layer 3: DB writers ------------------------------------------------


def insert_row(conn: Any, row: SentimentRow) -> bool:
    """INSERT ON CONFLICT DO NOTHING. Returns True iff a row was written.

    The UNIQUE constraint (NULLS NOT DISTINCT) on
    ``(source_kind, source_id, sentence_index, subject_kind, subject_id)``
    prevents duplicates on a re-score.
    """
    with conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO sentiment_scores (
                source_kind, source_id, sentence_index,
                subject_kind, subject_id,
                score, label, model_version
            )
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
            ON CONFLICT (
                source_kind, source_id, sentence_index, subject_kind, subject_id
            ) DO NOTHING
            RETURNING score_id
            """,
            (
                row.source_kind,
                row.source_id,
                row.sentence_index,
                row.subject_kind,
                row.subject_id,
                row.score,
                row.label,
                row.model_version,
            ),
        )
        return cur.fetchone() is not None


def refresh_matview(conn: Any) -> None:
    """Refresh ``sentiment_per_source_subject`` at the end of a batch.

    A non-CONCURRENT refresh is used because it's correct on an empty
    matview too (the CONCURRENT variant errors when the matview has never
    been populated). Workload here is small enough that the brief
    AccessExclusiveLock is acceptable.
    """
    with conn.cursor() as cur:
        cur.execute("REFRESH MATERIALIZED VIEW sentiment_per_source_subject")


# ---- Layer 4: orchestrator ----------------------------------------------


def iter_unscored_articles(conn: Any) -> Iterable[SourceText]:
    """Yield ``SourceText`` rows for ``news_articles`` without a sentiment row.

    Title + body_text are concatenated with ". " so a sentence-level
    splitter sees the headline as the first sentence.
    """
    sql = """
        SELECT a.article_id,
               COALESCE(a.title, ''),
               COALESCE(a.body_text, '')
        FROM news_articles a
        WHERE NOT EXISTS (
            SELECT 1 FROM sentiment_scores s
            WHERE s.source_kind = 'article'
              AND s.source_id   = a.article_id
        )
        ORDER BY a.article_id
    """
    with conn.cursor() as cur:
        cur.execute(sql)
        for article_id, title, body_text in cur.fetchall():
            text = _fuse_title_body(title, body_text)
            if not text:
                continue
            yield SourceText(SOURCE_KIND_ARTICLE, int(article_id), text)


def iter_unscored_posts(conn: Any) -> Iterable[SourceText]:
    """Yield ``SourceText`` rows for ``social_posts`` without a sentiment row."""
    sql = """
        SELECT p.post_id, COALESCE(p.body_text, '')
        FROM social_posts p
        WHERE NOT EXISTS (
            SELECT 1 FROM sentiment_scores s
            WHERE s.source_kind = 'post'
              AND s.source_id   = p.post_id
        )
        ORDER BY p.post_id
    """
    with conn.cursor() as cur:
        cur.execute(sql)
        for post_id, body_text in cur.fetchall():
            if not body_text or not body_text.strip():
                continue
            yield SourceText(SOURCE_KIND_POST, int(post_id), body_text)


def _fuse_title_body(title: str, body_text: str) -> str:
    """Concat title + body with ". " separator, trimming whitespace."""
    t = (title or "").strip()
    b = (body_text or "").strip()
    if t and b:
        joiner = "" if t.endswith((".", "!", "?", "…")) else ". "
        return f"{t}{joiner}{b}"
    return t or b


IterSources = Callable[[Any], Iterable[SourceText]]


def run(
    conn: Any,
    *,
    resolver: EntityResolver,
    backend: ScoringBackend,
    iter_articles: IterSources | None = None,
    iter_posts: IterSources | None = None,
    sentence_splitter: SentenceSplitter = split_sentences,
    refresh_after: bool = True,
) -> RunResult:
    """End-to-end: score every unscored article + post, refresh the matview.

    ``iter_articles`` / ``iter_posts`` default to the DB-backed iterators
    above; tests pass an in-memory iterator returning ``SourceText`` rows
    so the integration path stays decoupled from the live schema.
    """
    if iter_articles is None:
        iter_articles = iter_unscored_articles
    if iter_posts is None:
        iter_posts = iter_unscored_posts

    articles_scored = 0
    posts_scored = 0
    sentences_scored = 0
    inserted = 0
    skipped = 0

    try:
        for source in iter_articles(conn):
            rows = score_source_text(
                source,
                resolver=resolver,
                backend=backend,
                sentence_splitter=sentence_splitter,
            )
            articles_scored += 1
            sentences_scored += _count_sentences(rows)
            ins, skp = _write_rows(conn, rows)
            inserted += ins
            skipped += skp

        for source in iter_posts(conn):
            rows = score_source_text(
                source,
                resolver=resolver,
                backend=backend,
                sentence_splitter=sentence_splitter,
            )
            posts_scored += 1
            sentences_scored += _count_sentences(rows)
            ins, skp = _write_rows(conn, rows)
            inserted += ins
            skipped += skp

        if refresh_after and (articles_scored or posts_scored):
            refresh_matview(conn)
        conn.commit()
    except Exception:
        conn.rollback()
        raise

    return RunResult(
        articles_scored=articles_scored,
        posts_scored=posts_scored,
        sentences_scored=sentences_scored,
        rows_inserted=inserted,
        rows_skipped=skipped,
    )


def _count_sentences(rows: Sequence[SentimentRow]) -> int:
    return len({r.sentence_index for r in rows})


def _write_rows(conn: Any, rows: Sequence[SentimentRow]) -> tuple[int, int]:
    inserted = 0
    skipped = 0
    for row in rows:
        if insert_row(conn, row):
            inserted += 1
        else:
            skipped += 1
    return inserted, skipped


# ---- Live pysentimiento backend (lazy-loaded) ---------------------------


class PysentimientoBackend:
    """ScoringBackend backed by pysentimiento's Spanish BETO analyzer.

    Loaded lazily because the model is ~430 MB and pulling it in at import
    time would punish CI / lighter installs. Tests never construct this --
    they pass a fake ``ScoringBackend``.
    """

    def __init__(self, *, model_version: str | None = None) -> None:
        try:
            from pysentimiento import create_analyzer
        except ImportError as exc:  # pragma: no cover - exercised in ImportError test
            raise SentimentScorerError(
                "pysentimiento is required for the live scorer; install with "
                "`uv sync --extra sentiment` and ensure transformers + torch "
                "are available"
            ) from exc
        self._analyzer = create_analyzer(task="sentiment", lang="es")
        self.model_version = model_version or _default_model_version()

    def score(self, sentence: str) -> ScoredSentence:
        out = self._analyzer.predict(sentence)
        probas = getattr(out, "probas", None)
        if not isinstance(probas, dict):
            raise SentimentScorerError(
                f"pysentimiento returned unexpected shape (probas={probas!r})"
            )
        p_pos = float(probas.get("POS", 0.0))
        p_neg = float(probas.get("NEG", 0.0))
        score = max(SCORE_MIN, min(SCORE_MAX, p_pos - p_neg))
        label_raw = getattr(out, "output", LABEL_NEU)
        label = str(label_raw).upper()
        if label not in _VALID_LABELS:
            label = LABEL_NEU
        return ScoredSentence(label=label, score=score)


def _default_model_version() -> str:
    try:
        from importlib.metadata import version

        return f"pysentimiento-{version('pysentimiento')}"
    except Exception:  # pragma: no cover - defensive
        return "pysentimiento-unknown"


# Convenience alias mirroring the bluesky/pytrends scrapers' Run shim.
Run = run
