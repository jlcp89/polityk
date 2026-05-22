"""Tests for the per-sentence × per-entity sentiment scorer (issue #28).

Unit tests run without spaCy, pysentimiento or Postgres. The optional
Postgres integration test runs only when ``POLITYK_TEST_DATABASE_URL`` is
set and validates the migration-0009 matview refresh + UNIQUE behaviour
end-to-end against a live schema.
"""

from __future__ import annotations

import os
from collections.abc import Iterable
from typing import Any

import pytest

from pipeline.sentiment import entity_resolver as er
from pipeline.sentiment import scorer as s
from pipeline.sentiment.entity_resolver import EntityResolver
from pipeline.sentiment.fixtures.gazetteer_2023 import (
    ARÉVALO,
    SEMILLA,
    TORRES,
    build_fixture_cycle_candidate_for_party,
    build_fixture_gazetteer,
)


def _SEMILLA_PARTY_ID() -> int:
    return SEMILLA
from pipeline.sentiment.scorer import (
    LABEL_NEG,
    LABEL_NEU,
    LABEL_POS,
    PysentimientoBackend,
    RunResult,
    ScoredSentence,
    SentimentRow,
    SentimentScorerError,
    SourceText,
    insert_row,
    refresh_matview,
    run,
    score_source_text,
    split_sentences,
)

# ---------------------------------------------------------------------------
# Fake backend / fake conn helpers (no spaCy, no pysentimiento, no Postgres)
# ---------------------------------------------------------------------------


class FakeBackend:
    """Lookup-driven scorer for tests.

    Looks up the exact sentence text; falls back to a sentinel NEU score so
    unseen text always returns a deterministic result instead of raising
    (which would mask test bugs).
    """

    model_version = "fake-v0"

    def __init__(self, mapping: dict[str, ScoredSentence] | None = None) -> None:
        self.mapping = mapping or {}
        self.calls: list[str] = []

    def score(self, sentence: str) -> ScoredSentence:
        self.calls.append(sentence)
        if sentence in self.mapping:
            return self.mapping[sentence]
        return ScoredSentence(label=LABEL_NEU, score=0.0)


class _FakeCursor:
    def __init__(self) -> None:
        self.rows: dict[tuple[str, int, int, str, int | None], dict[str, Any]] = {}
        self.refresh_calls: int = 0
        self._last_result: tuple[int] | None = None
        self._next_id = 1

    def __enter__(self) -> _FakeCursor:
        return self

    def __exit__(self, *exc: object) -> None:
        return None

    def execute(self, sql: str, params: tuple[Any, ...] = ()) -> None:
        sql_stripped = sql.strip().lower()
        if sql_stripped.startswith("insert into sentiment_scores"):
            (
                source_kind,
                source_id,
                sentence_index,
                subject_kind,
                subject_id,
                score,
                label,
                model_version,
            ) = params
            key = (
                source_kind,
                int(source_id),
                int(sentence_index),
                subject_kind,
                None if subject_id is None else int(subject_id),
            )
            if key in self.rows:
                self._last_result = None
                return
            self.rows[key] = {
                "source_kind": source_kind,
                "source_id": int(source_id),
                "sentence_index": int(sentence_index),
                "subject_kind": subject_kind,
                "subject_id": None if subject_id is None else int(subject_id),
                "score": float(score),
                "label": label,
                "model_version": model_version,
            }
            self._last_result = (self._next_id,)
            self._next_id += 1
        elif sql_stripped.startswith("refresh materialized view"):
            self.refresh_calls += 1
            self._last_result = None
        else:
            raise AssertionError(f"unexpected sql in fake cursor: {sql_stripped!r}")

    def fetchone(self) -> tuple[int] | None:
        return self._last_result


class _FakeConn:
    def __init__(self) -> None:
        self.cur = _FakeCursor()
        self.committed = 0
        self.rolled_back = 0

    def cursor(self) -> _FakeCursor:
        return self.cur

    def commit(self) -> None:
        self.committed += 1

    def rollback(self) -> None:
        self.rolled_back += 1


@pytest.fixture()
def resolver() -> EntityResolver:
    er._reset_nlp_for_tests()
    return EntityResolver(
        build_fixture_gazetteer(),
        build_fixture_cycle_candidate_for_party(),
    )


# ---------------------------------------------------------------------------
# sentence splitter + ScoredSentence
# ---------------------------------------------------------------------------


def test_split_sentences_basic() -> None:
    assert split_sentences("Hola. Adiós.") == ["Hola.", "Adiós."]


def test_split_sentences_empty() -> None:
    assert split_sentences("") == []
    assert split_sentences("    ") == []


def test_split_sentences_handles_multiple_punctuation() -> None:
    out = split_sentences("Una pregunta? Una exclamación! Y más…")
    assert out == ["Una pregunta?", "Una exclamación!", "Y más…"]


def test_split_sentences_preserves_no_punctuation() -> None:
    # A single fragment with no terminator should still surface as one sentence.
    assert split_sentences("Sin punto final") == ["Sin punto final"]


def test_scored_sentence_rejects_bad_label() -> None:
    with pytest.raises(ValueError, match="label must be one of"):
        ScoredSentence(label="WAT", score=0.0)


def test_scored_sentence_rejects_out_of_range_score() -> None:
    with pytest.raises(ValueError, match="score must be in"):
        ScoredSentence(label=LABEL_POS, score=1.5)
    with pytest.raises(ValueError, match="score must be in"):
        ScoredSentence(label=LABEL_NEG, score=-1.5)


# ---------------------------------------------------------------------------
# score_source_text
# ---------------------------------------------------------------------------


def test_score_source_text_writes_overall_row_when_no_entities(
    resolver: EntityResolver,
) -> None:
    backend = FakeBackend({"Es un día tranquilo en Guatemala.": ScoredSentence(LABEL_NEU, 0.0)})
    src = SourceText("article", 99, "Es un día tranquilo en Guatemala.")

    rows = score_source_text(src, resolver=resolver, backend=backend)

    assert len(rows) == 1
    row = rows[0]
    assert row.source_kind == "article"
    assert row.source_id == 99
    assert row.sentence_index == 0
    assert row.subject_kind == "overall"
    assert row.subject_id is None
    assert row.label == LABEL_NEU
    assert row.score == 0.0
    assert row.model_version == "fake-v0"


def test_score_source_text_one_row_per_entity(resolver: EntityResolver) -> None:
    sentence = "Bernardo Arévalo y Sandra Torres encabezan las encuestas."
    backend = FakeBackend({sentence: ScoredSentence(LABEL_POS, 0.7)})
    src = SourceText("article", 1, sentence)

    rows = score_source_text(src, resolver=resolver, backend=backend)

    # Two candidates → two entity rows, no "overall" row.
    assert len(rows) == 2
    subjects = {(r.subject_kind, r.subject_id) for r in rows}
    assert subjects == {("candidate", ARÉVALO), ("candidate", TORRES)}
    assert all(r.sentence_index == 0 for r in rows)
    assert all(r.label == LABEL_POS for r in rows)


def test_score_source_text_dedups_repeated_subject(resolver: EntityResolver) -> None:
    # "Sandra Torres" appears twice in the same sentence, but only via the
    # canonical surface so the gazetteer pass sees only one mention (consumed
    # spans block the longer alias from also matching). Use a sentence that
    # could mention the same subject through alias + canonical.
    sentence = "Sandra Torres encabezó el evento; Torres respondió a la prensa."
    backend = FakeBackend({sentence: ScoredSentence(LABEL_POS, 0.5)})
    src = SourceText("article", 2, sentence)

    rows = score_source_text(src, resolver=resolver, backend=backend)

    # Should produce exactly one row for Torres (dedup by (kind, id)).
    torres_rows = [r for r in rows if r.subject_id == TORRES]
    assert len(torres_rows) == 1


def test_score_source_text_trigger_phrase_resolves_party_to_candidate(
    resolver: EntityResolver,
) -> None:
    sentence = "El candidato de Semilla habló con la prensa."
    backend = FakeBackend({sentence: ScoredSentence(LABEL_NEU, 0.0)})
    src = SourceText("article", 3, sentence)

    rows = score_source_text(src, resolver=resolver, backend=backend)

    subjects = {(r.subject_kind, r.subject_id) for r in rows}
    # Trigger phrase should resolve to Arévalo via the cycle mapping.
    assert ("candidate", ARÉVALO) in subjects


def test_score_source_text_multi_sentence_indexes_in_order(
    resolver: EntityResolver,
) -> None:
    text = "Bernardo Arévalo lidera. Sandra Torres responde."
    backend = FakeBackend(
        {
            "Bernardo Arévalo lidera.": ScoredSentence(LABEL_POS, 0.6),
            "Sandra Torres responde.": ScoredSentence(LABEL_NEG, -0.4),
        }
    )
    rows = score_source_text(
        SourceText("article", 4, text),
        resolver=resolver,
        backend=backend,
    )

    by_idx = {r.sentence_index: r for r in rows}
    assert by_idx[0].subject_id == ARÉVALO
    assert by_idx[0].label == LABEL_POS
    assert by_idx[1].subject_id == TORRES
    assert by_idx[1].label == LABEL_NEG


def test_score_source_text_empty_text_returns_empty(resolver: EntityResolver) -> None:
    rows = score_source_text(
        SourceText("article", 5, "   "),
        resolver=resolver,
        backend=FakeBackend(),
    )
    assert rows == []


# ---------------------------------------------------------------------------
# insert_row / refresh_matview against fake conn
# ---------------------------------------------------------------------------


def _row(**overrides: Any) -> SentimentRow:
    defaults: dict[str, Any] = {
        "source_kind": "article",
        "source_id": 1,
        "sentence_index": 0,
        "subject_kind": "candidate",
        "subject_id": ARÉVALO,
        "score": 0.5,
        "label": LABEL_POS,
        "model_version": "fake-v0",
    }
    defaults.update(overrides)
    return SentimentRow(**defaults)


def test_insert_row_new_then_duplicate() -> None:
    conn = _FakeConn()
    row = _row()
    assert insert_row(conn, row) is True
    assert insert_row(conn, row) is False
    assert len(conn.cur.rows) == 1


def test_insert_row_overall_with_null_subject_id() -> None:
    conn = _FakeConn()
    row = _row(subject_kind="overall", subject_id=None)
    assert insert_row(conn, row) is True
    key = ("article", 1, 0, "overall", None)
    assert key in conn.cur.rows


def test_refresh_matview_issues_one_refresh() -> None:
    conn = _FakeConn()
    refresh_matview(conn)
    assert conn.cur.refresh_calls == 1


# ---------------------------------------------------------------------------
# run (orchestrator) with fake conn + injected iterators
# ---------------------------------------------------------------------------


def _articles_iter(*sources: SourceText) -> Any:
    def _it(_conn: Any) -> Iterable[SourceText]:
        yield from sources

    return _it


def _empty_iter(_conn: Any) -> Iterable[SourceText]:
    return iter(())


def test_run_writes_rows_and_refreshes_matview(resolver: EntityResolver) -> None:
    conn = _FakeConn()
    backend = FakeBackend(
        {
            "Bernardo Arévalo lidera.": ScoredSentence(LABEL_POS, 0.6),
            "Es un día tranquilo.": ScoredSentence(LABEL_NEU, 0.0),
        }
    )

    sources = [
        SourceText("article", 1, "Bernardo Arévalo lidera."),
        SourceText("article", 2, "Es un día tranquilo."),
    ]
    result: RunResult = run(
        conn,
        resolver=resolver,
        backend=backend,
        iter_articles=_articles_iter(*sources),
        iter_posts=_empty_iter,
    )

    assert result.articles_scored == 2
    assert result.posts_scored == 0
    assert result.sentences_scored == 2
    assert result.rows_inserted == 2  # 1 entity row + 1 overall row
    assert result.rows_skipped == 0
    assert conn.cur.refresh_calls == 1
    assert conn.committed == 1


def test_run_writes_one_overall_when_no_entities(resolver: EntityResolver) -> None:
    conn = _FakeConn()
    backend = FakeBackend({"Día tranquilo.": ScoredSentence(LABEL_NEU, 0.0)})

    result = run(
        conn,
        resolver=resolver,
        backend=backend,
        iter_articles=_articles_iter(SourceText("article", 7, "Día tranquilo.")),
        iter_posts=_empty_iter,
    )

    assert result.rows_inserted == 1
    written = next(iter(conn.cur.rows.values()))
    assert written["subject_kind"] == "overall"
    assert written["subject_id"] is None


def test_run_idempotent_on_second_pass(resolver: EntityResolver) -> None:
    conn = _FakeConn()
    backend = FakeBackend({"Bernardo Arévalo lidera.": ScoredSentence(LABEL_POS, 0.6)})
    sources = [SourceText("article", 1, "Bernardo Arévalo lidera.")]

    first = run(
        conn,
        resolver=resolver,
        backend=backend,
        iter_articles=_articles_iter(*sources),
        iter_posts=_empty_iter,
    )
    second = run(
        conn,
        resolver=resolver,
        backend=backend,
        iter_articles=_articles_iter(*sources),
        iter_posts=_empty_iter,
    )

    assert first.rows_inserted == 1
    assert first.rows_skipped == 0
    assert second.rows_inserted == 0
    assert second.rows_skipped == 1


def test_run_rolls_back_on_exception(resolver: EntityResolver) -> None:
    class BoomBackend:
        model_version = "boom-v0"

        def score(self, sentence: str) -> ScoredSentence:
            raise RuntimeError("boom")

    conn = _FakeConn()
    with pytest.raises(RuntimeError, match="boom"):
        run(
            conn,
            resolver=resolver,
            backend=BoomBackend(),
            iter_articles=_articles_iter(SourceText("article", 1, "Cualquier cosa.")),
            iter_posts=_empty_iter,
        )
    assert conn.rolled_back == 1
    assert conn.committed == 0


def test_run_skips_matview_when_nothing_scored(resolver: EntityResolver) -> None:
    conn = _FakeConn()
    result = run(
        conn,
        resolver=resolver,
        backend=FakeBackend(),
        iter_articles=_empty_iter,
        iter_posts=_empty_iter,
    )
    assert result.rows_inserted == 0
    # No work → no refresh (avoids paying the lock on a no-op batch).
    assert conn.cur.refresh_calls == 0
    assert conn.committed == 1


def test_run_handles_posts_as_well(resolver: EntityResolver) -> None:
    conn = _FakeConn()
    backend = FakeBackend({"Torres ganó debate.": ScoredSentence(LABEL_POS, 0.5)})

    result = run(
        conn,
        resolver=resolver,
        backend=backend,
        iter_articles=_empty_iter,
        iter_posts=_articles_iter(SourceText("post", 42, "Torres ganó debate.")),
    )
    assert result.posts_scored == 1
    written = next(iter(conn.cur.rows.values()))
    assert written["source_kind"] == "post"
    assert written["source_id"] == 42
    assert written["subject_id"] == TORRES


# ---------------------------------------------------------------------------
# Fixture-driven 3-article acceptance check (acceptance criterion)
# ---------------------------------------------------------------------------


def test_three_article_fixture_yields_expected_row_counts_and_labels(
    resolver: EntityResolver,
) -> None:
    """Three hand-validated articles → expected sentiment_scores row counts.

    Article 1 (one sentence, one candidate)  → 1 POS row for ARÉVALO
    Article 2 (two sentences, mixed)         → 1 NEG row for TORRES (sentence 0) +
                                              1 POS row for Semilla (party) and
                                              1 POS row for ARÉVALO (via trigger) on sentence 1
    Article 3 (one sentence, no entities)    → 1 overall NEU row

    Total: 5 rows; 4 entity rows, 1 overall.
    """
    articles = [
        SourceText(
            "article", 101, "Bernardo Arévalo lidera las encuestas."
        ),
        SourceText(
            "article",
            102,
            "Sandra Torres enfrenta críticas. El candidato de Semilla responde.",
        ),
        SourceText("article", 103, "Es un día tranquilo en Guatemala."),
    ]
    backend = FakeBackend(
        {
            "Bernardo Arévalo lidera las encuestas.": ScoredSentence(LABEL_POS, 0.8),
            "Sandra Torres enfrenta críticas.": ScoredSentence(LABEL_NEG, -0.6),
            "El candidato de Semilla responde.": ScoredSentence(LABEL_POS, 0.4),
            "Es un día tranquilo en Guatemala.": ScoredSentence(LABEL_NEU, 0.05),
        }
    )

    conn = _FakeConn()
    result = run(
        conn,
        resolver=resolver,
        backend=backend,
        iter_articles=_articles_iter(*articles),
        iter_posts=_empty_iter,
    )

    assert result.articles_scored == 3
    assert result.sentences_scored == 4  # 1 + 2 + 1 distinct sentence indexes

    rows = list(conn.cur.rows.values())
    by_source: dict[int, list[dict[str, Any]]] = {}
    for r in rows:
        by_source.setdefault(r["source_id"], []).append(r)

    # Article 101 → exactly one row for Arévalo, labelled POS.
    a1 = by_source[101]
    assert len(a1) == 1
    assert a1[0]["subject_kind"] == "candidate"
    assert a1[0]["subject_id"] == ARÉVALO
    assert a1[0]["label"] == LABEL_POS

    # Article 102 → one NEG row for Torres on sentence 0,
    # and on sentence 1 the resolver picks up both the party (Semilla) via the
    # gazetteer pass and the candidate (Arévalo) via the trigger phrase pass.
    a2 = sorted(by_source[102], key=lambda r: (r["sentence_index"], r["subject_kind"]))
    assert len(a2) == 3
    s0 = [r for r in a2 if r["sentence_index"] == 0]
    s1 = [r for r in a2 if r["sentence_index"] == 1]
    assert len(s0) == 1
    assert s0[0]["subject_id"] == TORRES
    assert s0[0]["label"] == LABEL_NEG
    assert {r["subject_id"] for r in s1} == {ARÉVALO, _SEMILLA_PARTY_ID()}
    assert all(r["label"] == LABEL_POS for r in s1)

    # Article 103 → overall row, NEU.
    a3 = by_source[103]
    assert len(a3) == 1
    assert a3[0]["subject_kind"] == "overall"
    assert a3[0]["subject_id"] is None
    assert a3[0]["label"] == LABEL_NEU


def test_run_alias_capital_r() -> None:
    """Run alias mirrors bluesky/telegram/pytrends scrapers."""
    assert s.Run is run


# ---------------------------------------------------------------------------
# PysentimientoBackend ImportError path (no live BETO needed)
# ---------------------------------------------------------------------------


def test_pysentimiento_backend_raises_when_package_missing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import builtins

    real_import = builtins.__import__

    def fake_import(
        name: str,
        globals: Any = None,
        locals: Any = None,
        fromlist: tuple[str, ...] = (),
        level: int = 0,
    ) -> Any:
        if name.startswith("pysentimiento"):
            raise ImportError("simulated missing pysentimiento")
        return real_import(name, globals, locals, fromlist, level)

    monkeypatch.setattr(builtins, "__import__", fake_import)

    with pytest.raises(SentimentScorerError, match="pysentimiento"):
        PysentimientoBackend()


# ---------------------------------------------------------------------------
# Postgres integration (gated on POLITYK_TEST_DATABASE_URL)
# ---------------------------------------------------------------------------


_TEST_DSN = os.environ.get("POLITYK_TEST_DATABASE_URL")


@pytest.mark.skipif(_TEST_DSN is None, reason="POLITYK_TEST_DATABASE_URL not set")
def test_run_against_postgres_writes_rows_refreshes_matview_idempotent(
    resolver: EntityResolver,
) -> None:
    import psycopg

    assert _TEST_DSN is not None

    articles = [
        SourceText("article", -1, "Bernardo Arévalo lidera las encuestas."),
        SourceText(
            "article",
            -2,
            "Sandra Torres enfrenta críticas. El candidato de Semilla responde.",
        ),
        SourceText("article", -3, "Es un día tranquilo en Guatemala."),
    ]
    backend = FakeBackend(
        {
            "Bernardo Arévalo lidera las encuestas.": ScoredSentence(LABEL_POS, 0.8),
            "Sandra Torres enfrenta críticas.": ScoredSentence(LABEL_NEG, -0.6),
            "El candidato de Semilla responde.": ScoredSentence(LABEL_POS, 0.4),
            "Es un día tranquilo en Guatemala.": ScoredSentence(LABEL_NEU, 0.05),
        }
    )

    with psycopg.connect(_TEST_DSN) as conn:
        with conn.cursor() as cur:
            cur.execute(
                "DELETE FROM sentiment_scores WHERE source_id IN (-1, -2, -3) "
                "AND source_kind = 'article'"
            )
        conn.commit()

        first = run(
            conn,
            resolver=resolver,
            backend=backend,
            iter_articles=_articles_iter(*articles),
            iter_posts=_empty_iter,
        )
        second = run(
            conn,
            resolver=resolver,
            backend=backend,
            iter_articles=_articles_iter(*articles),
            iter_posts=_empty_iter,
        )

        with conn.cursor() as cur:
            cur.execute(
                "SELECT COUNT(*) FROM sentiment_scores "
                "WHERE source_id IN (-1, -2, -3) AND source_kind = 'article'"
            )
            count_row = cur.fetchone()
            cur.execute(
                "SELECT subject_kind, subject_id, mean_score, sentence_count, "
                "       dominant_label "
                "FROM sentiment_per_source_subject "
                "WHERE source_id IN (-1, -2, -3) AND source_kind = 'article' "
                "ORDER BY source_id, subject_kind, subject_id"
            )
            matview_rows = cur.fetchall()

        # Cleanup so reruns stay green.
        with conn.cursor() as cur:
            cur.execute(
                "DELETE FROM sentiment_scores "
                "WHERE source_id IN (-1, -2, -3) AND source_kind = 'article'"
            )
        conn.commit()

    # Article -1 → 1 row (Arévalo candidate)
    # Article -2 → 1 NEG (Torres) on sentence 0, plus on sentence 1 both
    #              Semilla (party) and Arévalo (candidate via trigger) → 3 rows total
    # Article -3 → 1 overall row
    assert first.rows_inserted == 5
    assert first.rows_skipped == 0
    assert second.rows_inserted == 0
    assert second.rows_skipped == 5
    assert count_row is not None and count_row[0] == 5
    # Matview keys on (source_kind, source_id, subject_kind, subject_id):
    #   (-1, candidate, ARÉVALO)
    #   (-2, candidate, TORRES) + (-2, candidate, ARÉVALO) + (-2, party, SEMILLA)
    #   (-3, overall, NULL)
    # → 5 aggregated rows.
    assert len(matview_rows) == 5
    overall_rows = [r for r in matview_rows if r[0] == "overall"]
    assert len(overall_rows) == 1
    assert overall_rows[0][4] == LABEL_NEU


@pytest.mark.skipif(_TEST_DSN is None, reason="POLITYK_TEST_DATABASE_URL not set")
def test_sentiment_scores_unique_constraint_enforced_at_schema_level() -> None:
    """A raw INSERT bypassing the scorer still trips the UNIQUE NULLS NOT DISTINCT key."""
    import psycopg

    assert _TEST_DSN is not None
    with psycopg.connect(_TEST_DSN) as conn:
        with conn.cursor() as cur:
            cur.execute(
                "DELETE FROM sentiment_scores WHERE source_id = -42 "
                "AND source_kind = 'article'"
            )
            cur.execute(
                "INSERT INTO sentiment_scores "
                "(source_kind, source_id, sentence_index, subject_kind, subject_id, "
                " score, label, model_version) "
                "VALUES ('article', -42, 0, 'overall', NULL, 0.0, 'NEU', 't')"
            )
            with pytest.raises(psycopg.errors.UniqueViolation):
                cur.execute(
                    "INSERT INTO sentiment_scores "
                    "(source_kind, source_id, sentence_index, subject_kind, subject_id, "
                    " score, label, model_version) "
                    "VALUES ('article', -42, 0, 'overall', NULL, 0.1, 'POS', 't')"
                )
        conn.rollback()
        with conn.cursor() as cur:
            cur.execute(
                "DELETE FROM sentiment_scores WHERE source_id = -42 "
                "AND source_kind = 'article'"
            )
        conn.commit()
