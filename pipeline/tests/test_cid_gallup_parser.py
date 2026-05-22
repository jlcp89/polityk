"""Tests for the CID Gallup PDF poll parser (issue #23).

Layered:

* Pure parser tests use a hand-crafted text fixture (no PDF, no pdfplumber).
* One smoke test exercises pdfplumber against the committed
  `cid_gallup_2027_march.pdf` fixture. Skipped if pdfplumber isn't
  installed (`uv sync --extra parsers`).
* Integration tests against a real Postgres are gated on
  `POLITYK_TEST_DATABASE_URL`; they verify the (pollster_id, field_end,
  source_url) idempotency and the scrape_runs no-op-when-absent path.
"""

from __future__ import annotations

import importlib.util
import os
from datetime import date
from pathlib import Path
from typing import Any

import pytest

from pipeline.parsers.cid_gallup import (
    POLLSTER_NAME,
    SCRAPE_SOURCE,
    CandidateShare,
    CIDGallupParseError,
    ParsedPoll,
    extract_text,
    load_poll,
    parse_poll,
)

FIXTURE_PDF = Path(__file__).parent.parent / "parsers" / "fixtures" / "cid_gallup_2027_march.pdf"

_HAS_PDFPLUMBER = importlib.util.find_spec("pdfplumber") is not None

# ---- Pure-text fixtures --------------------------------------------------

SAMPLE_TEXT = """CID Gallup
Encuesta Nacional Presidencial Guatemala 2027

Metodología: Encuesta nacional cara a cara, muestreo estratificado
multi-etápico con cuotas por sexo y edad.

Trabajo de campo: 12 al 16 de marzo de 2027
Tamaño de la muestra: n = 1,200 personas

Intención de voto presidencial (%):
Bernardo Arévalo de León 36.5% ± 2.8%
Sandra Torres 22.1% ± 2.8%
Zury Ríos 12.7% ± 2.8%
Edmond Mulet 9.4% ± 2.8%
Otros 8.0%
No sabe / No responde 5.1%
"""

SAMPLE_URL = "https://example.com/cid-gallup-marzo-2027.pdf"


# ---- Pure parser tests ---------------------------------------------------


def test_parse_poll_extracts_field_window() -> None:
    parsed = parse_poll(SAMPLE_TEXT, SAMPLE_URL)
    assert parsed.field_start == date(2027, 3, 12)
    assert parsed.field_end == date(2027, 3, 16)


def test_parse_poll_extracts_sample_size() -> None:
    parsed = parse_poll(SAMPLE_TEXT, SAMPLE_URL)
    assert parsed.sample_size == 1200


def test_parse_poll_extracts_methodology() -> None:
    parsed = parse_poll(SAMPLE_TEXT, SAMPLE_URL)
    assert "muestreo estratificado" in parsed.methodology
    assert "cuotas por sexo" in parsed.methodology
    # Methodology stops before the field-window line.
    assert "Trabajo de campo" not in parsed.methodology


def test_parse_poll_extracts_candidates_with_moe() -> None:
    parsed = parse_poll(SAMPLE_TEXT, SAMPLE_URL)
    names = [c.name for c in parsed.candidates]
    assert names == [
        "Bernardo Arévalo de León",
        "Sandra Torres",
        "Zury Ríos",
        "Edmond Mulet",
    ]
    shares = {c.name: c.share for c in parsed.candidates}
    assert shares["Bernardo Arévalo de León"] == pytest.approx(0.365)
    assert shares["Sandra Torres"] == pytest.approx(0.221)
    moes = {c.name: c.margin_of_error for c in parsed.candidates}
    assert moes["Bernardo Arévalo de León"] == pytest.approx(0.028)
    assert all(c.margin_of_error == pytest.approx(0.028) for c in parsed.candidates)


def test_parse_poll_filters_non_candidate_rows() -> None:
    parsed = parse_poll(SAMPLE_TEXT, SAMPLE_URL)
    names = {c.name.lower() for c in parsed.candidates}
    assert "otros" not in names
    assert not any("no sabe" in n for n in names)


def test_parse_poll_carries_source_url_and_pollster_name() -> None:
    parsed = parse_poll(SAMPLE_TEXT, SAMPLE_URL)
    assert parsed.pollster_name == POLLSTER_NAME
    assert parsed.source_url == SAMPLE_URL


def test_parse_poll_rejects_non_cid_gallup_text() -> None:
    with pytest.raises(CIDGallupParseError, match="CID Gallup"):
        parse_poll("ProDatos Encuesta Libre 2027 ...", SAMPLE_URL)


def test_parse_poll_rejects_text_without_candidates() -> None:
    text = (
        "CID Gallup\n"
        "Metodología: muestreo nacional\n"
        "Trabajo de campo: 1 al 5 de mayo de 2027\n"
        "Tamaño de la muestra: n = 1000 personas\n"
    )
    with pytest.raises(CIDGallupParseError, match="No candidate-share"):
        parse_poll(text, SAMPLE_URL)


def test_parse_poll_rejects_field_window_inverted() -> None:
    text = SAMPLE_TEXT.replace(
        "Trabajo de campo: 12 al 16 de marzo de 2027",
        "Trabajo de campo: 28 al 03 de marzo de 2027",
    )
    with pytest.raises(CIDGallupParseError, match="precedes"):
        parse_poll(text, SAMPLE_URL)


def test_parse_poll_rejects_implausible_sample_size() -> None:
    text = SAMPLE_TEXT.replace("n = 1,200", "n = 17")
    with pytest.raises(CIDGallupParseError, match="outside plausible bounds"):
        parse_poll(text, SAMPLE_URL)


def test_parse_poll_handles_cross_month_field_window() -> None:
    text = SAMPLE_TEXT.replace(
        "Trabajo de campo: 12 al 16 de marzo de 2027",
        "Trabajo de campo: 28 de febrero al 03 de marzo de 2027",
    )
    parsed = parse_poll(text, SAMPLE_URL)
    assert parsed.field_start == date(2027, 2, 28)
    assert parsed.field_end == date(2027, 3, 3)


def test_parse_poll_share_bounded_in_zero_one() -> None:
    parsed = parse_poll(SAMPLE_TEXT, SAMPLE_URL)
    for c in parsed.candidates:
        assert 0.0 <= c.share <= 1.0
        if c.margin_of_error is not None:
            assert c.margin_of_error >= 0


# ---- PDF extraction smoke test -------------------------------------------


@pytest.mark.skipif(not _HAS_PDFPLUMBER, reason="pdfplumber extra not installed")
def test_extract_text_then_parse_fixture_pdf() -> None:
    text = extract_text(FIXTURE_PDF)
    assert "CID Gallup" in text
    parsed = parse_poll(text, "https://prensalibre.com/cid-gallup-marzo-2027.pdf")
    assert parsed.field_start == date(2027, 3, 12)
    assert parsed.field_end == date(2027, 3, 16)
    assert parsed.sample_size == 1200
    assert len(parsed.candidates) == 5
    assert parsed.candidates[0].name == "Bernardo Arévalo de León"
    assert parsed.candidates[0].share == pytest.approx(0.365)


# ---- DB integration ------------------------------------------------------

_TEST_DSN = os.environ.get("POLITYK_TEST_DATABASE_URL")


def _seed_candidates(cur: Any) -> None:
    """Insert the five fixture candidates if missing. Idempotent."""
    rows = [
        ("Bernardo Arévalo de León", ["Arévalo", "Bernardo Arévalo"]),
        ("Sandra Torres", ["Torres"]),
        ("Zury Ríos", ["Ríos"]),
        ("Edmond Mulet", ["Mulet"]),
        ("Manuel Conde", ["Conde"]),
    ]
    for full_name, aliases in rows:
        cur.execute(
            "INSERT INTO candidates (full_name) VALUES (%s) "
            "ON CONFLICT DO NOTHING RETURNING candidate_id",
            (full_name,),
        )
        cur.execute(
            "SELECT candidate_id FROM candidates WHERE full_name = %s",
            (full_name,),
        )
        cand_id = cur.fetchone()[0]
        for alias in aliases:
            cur.execute(
                "INSERT INTO candidate_aliases (candidate_id, alias_name) "
                "VALUES (%s, %s) ON CONFLICT DO NOTHING",
                (cand_id, alias),
            )


@pytest.mark.skipif(_TEST_DSN is None, reason="POLITYK_TEST_DATABASE_URL not set")
def test_load_poll_inserts_poll_and_responses() -> None:
    import psycopg

    assert _TEST_DSN is not None
    parsed = parse_poll(SAMPLE_TEXT, SAMPLE_URL)
    with psycopg.connect(_TEST_DSN) as conn:
        with conn.cursor() as cur:
            _seed_candidates(cur)
        conn.commit()

        poll_id = load_poll(conn, parsed)
        assert poll_id is not None and poll_id > 0

        with conn.cursor() as cur:
            cur.execute(
                "SELECT pollster_id, field_start, field_end, sample_size "
                "FROM polls WHERE poll_id = %s",
                (poll_id,),
            )
            row = cur.fetchone()
            assert row is not None
            _, fs, fe, n = row
            assert fs == date(2027, 3, 12)
            assert fe == date(2027, 3, 16)
            assert n == 1200

            cur.execute(
                "SELECT COUNT(*) FROM poll_responses WHERE poll_id = %s",
                (poll_id,),
            )
            count_row = cur.fetchone()
            assert count_row is not None
            assert count_row[0] == len(parsed.candidates)

        # Cleanup so other tests on the same DB stay isolated.
        with conn.cursor() as cur:
            cur.execute("DELETE FROM polls WHERE poll_id = %s", (poll_id,))
        conn.commit()


@pytest.mark.skipif(_TEST_DSN is None, reason="POLITYK_TEST_DATABASE_URL not set")
def test_load_poll_idempotent_on_same_source_url() -> None:
    import psycopg

    assert _TEST_DSN is not None
    parsed = parse_poll(SAMPLE_TEXT, SAMPLE_URL)
    with psycopg.connect(_TEST_DSN) as conn:
        with conn.cursor() as cur:
            _seed_candidates(cur)
        conn.commit()

        first = load_poll(conn, parsed)
        second = load_poll(conn, parsed)
        assert first is not None
        assert second is None  # ON CONFLICT swallowed the second insert

        with conn.cursor() as cur:
            cur.execute(
                "SELECT COUNT(*) FROM polls WHERE source_url = %s", (SAMPLE_URL,)
            )
            count_row = cur.fetchone()
            assert count_row is not None
            assert count_row[0] == 1

            cur.execute("DELETE FROM polls WHERE poll_id = %s", (first,))
        conn.commit()


@pytest.mark.skipif(_TEST_DSN is None, reason="POLITYK_TEST_DATABASE_URL not set")
def test_load_poll_resolves_cid_gallup_pollster_seeded_in_0004() -> None:
    import psycopg

    assert _TEST_DSN is not None
    parsed = parse_poll(SAMPLE_TEXT, SAMPLE_URL)
    with psycopg.connect(_TEST_DSN) as conn:
        with conn.cursor() as cur:
            _seed_candidates(cur)
        conn.commit()
        poll_id = load_poll(conn, parsed)
        assert poll_id is not None
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT p.name
                FROM polls poll
                JOIN pollsters p ON p.pollster_id = poll.pollster_id
                WHERE poll.poll_id = %s
                """,
                (poll_id,),
            )
            row = cur.fetchone()
            assert row is not None and row[0] == POLLSTER_NAME
            cur.execute("DELETE FROM polls WHERE poll_id = %s", (poll_id,))
        conn.commit()


@pytest.mark.skipif(_TEST_DSN is None, reason="POLITYK_TEST_DATABASE_URL not set")
def test_load_poll_stamps_scrape_runs_when_table_exists() -> None:
    """When `scrape_runs` is present, every load updates last_run_at.

    Issue #15 introduces the scrape_runs table; if it isn't there yet
    we just verify the parser doesn't crash (the no-op path).
    """
    import psycopg

    assert _TEST_DSN is not None
    parsed = parse_poll(SAMPLE_TEXT, SAMPLE_URL)
    with psycopg.connect(_TEST_DSN) as conn:
        # Provision a minimal scrape_runs table for this test if absent so
        # we can exercise the stamping path. We tear it back down at the
        # end if we created it.
        created_table = False
        with conn.cursor() as cur:
            cur.execute("SELECT to_regclass('scrape_runs')")
            existed = cur.fetchone()
            if existed is None or existed[0] is None:
                cur.execute(
                    "CREATE TABLE scrape_runs ("
                    "  source TEXT PRIMARY KEY,"
                    "  last_run_at TIMESTAMPTZ NOT NULL,"
                    "  success BOOLEAN NOT NULL,"
                    "  error_message TEXT"
                    ")"
                )
                created_table = True
            _seed_candidates(cur)
        conn.commit()

        poll_id = load_poll(conn, parsed)
        assert poll_id is not None

        with conn.cursor() as cur:
            cur.execute(
                "SELECT success, error_message FROM scrape_runs WHERE source = %s",
                (SCRAPE_SOURCE,),
            )
            row = cur.fetchone()
            assert row is not None
            assert row[0] is True and row[1] is None

            cur.execute("DELETE FROM polls WHERE poll_id = %s", (poll_id,))
            cur.execute("DELETE FROM scrape_runs WHERE source = %s", (SCRAPE_SOURCE,))
            if created_table:
                cur.execute("DROP TABLE scrape_runs")
        conn.commit()


# ---- Dataclass sanity ---------------------------------------------------


def test_parsed_poll_is_frozen_dataclass() -> None:
    from dataclasses import FrozenInstanceError

    p = ParsedPoll(
        pollster_name=POLLSTER_NAME,
        field_start=date(2027, 3, 12),
        field_end=date(2027, 3, 16),
        sample_size=1200,
        methodology="...",
        candidates=(CandidateShare("X", 0.5, None),),
        source_url=SAMPLE_URL,
    )
    with pytest.raises(FrozenInstanceError):
        p.sample_size = 1201  # type: ignore[misc]
