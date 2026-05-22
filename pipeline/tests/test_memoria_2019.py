"""Tests for the Memoria Electoral 2019 PDF extractor (issue #20).

The pure-logic parsers run unconditionally. The end-to-end Postgres test
for ``stamp_scrape_run`` runs only when ``POLITYK_TEST_DATABASE_URL`` is
set — same pattern as ``test_geographies_seed.py``.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import TYPE_CHECKING, cast

import pytest

from pipeline.parsers import memoria_2019 as m

if TYPE_CHECKING:
    import psycopg


# ---------------------------------------------------------------------------
# Fixtures: hand-built raw tables that stand in for what pdfplumber would
# return after we'd dispatched a real PDF table to canonical column names.
# ---------------------------------------------------------------------------


def _presidential_round1_rows() -> list[dict[str, object]]:
    """Two candidates × one geography (the country roll-up)."""
    return [
        {
            "geography_level": "country",
            "geography_code": "GT",
            "candidate": "Sandra Torres",
            "votes": 1_113_433,
            "expected_total": 4_469_961,
        },
        {
            "geography_level": "country",
            "geography_code": "GT",
            "candidate": "Alejandro Giammattei",
            "votes": 612_419,
            "expected_total": 4_469_961,
        },
        {
            "geography_level": "country",
            "geography_code": "GT",
            "candidate": "Edmond Mulet",
            "votes": 489_754,
            "expected_total": 4_469_961,
        },
        # the remainder bucketed for total reconciliation
        {
            "geography_level": "country",
            "geography_code": "GT",
            "candidate": "Otros (resto del campo)",
            "votes": 2_254_355,
            "expected_total": 4_469_961,
        },
    ]


def _presidential_round2_rows() -> list[dict[str, object]]:
    return [
        {
            "geography_level": "country",
            "geography_code": "GT",
            "candidate": "Alejandro Giammattei",
            "votes": 1_907_771,
            "expected_total": 3_577_173,
        },
        {
            "geography_level": "country",
            "geography_code": "GT",
            "candidate": "Sandra Torres",
            "votes": 1_384_215,
            "expected_total": 3_577_173,
        },
        {
            "geography_level": "country",
            "geography_code": "GT",
            "candidate": "Nulos+Blancos",
            "votes": 285_187,
            "expected_total": 3_577_173,
        },
    ]


def _congress_distrital_rows() -> list[dict[str, object]]:
    return [
        {"district_code": "01", "party": "UNE", "votes": 91_000, "seats": 3},
        {"district_code": "01", "party": "VAMOS", "votes": 73_000, "seats": 3},
        {"district_code": "02", "party": "UNE", "votes": 58_000, "seats": 2},
    ]


def _congress_nacional_rows() -> list[dict[str, object]]:
    return [
        {"party": "UNE", "votes": "510,000", "seats": 7},
        {"party": "VAMOS", "votes": "410,000", "seats": 6},
    ]


def _parlacen_rows() -> list[dict[str, object]]:
    return [
        {"party": "UNE", "votes": 480_000, "seats": 4},
        {"party": "VAMOS", "votes": 390_000, "seats": 3},
    ]


def _municipal_rows() -> list[dict[str, object]]:
    return [
        {
            "municipality_code": "0101",
            "party": "VAMOS",
            "alcalde_votes": 42_000,
            "alcalde_won": True,
        },
        {
            "municipality_code": "0101",
            "party": "UNE",
            "alcalde_votes": 31_000,
            "alcalde_won": False,
        },
        {
            "municipality_code": "0102",
            "party": "UNE",
            "alcalde_votes": 22_000,
            "alcalde_won": True,
        },
    ]


# ---------------------------------------------------------------------------
# Pure-logic parser tests
# ---------------------------------------------------------------------------


def test_parse_presidential_round1_happy_path() -> None:
    rows = m.parse_presidential_table(_presidential_round1_rows(), round_number=1)
    assert len(rows) == 4
    assert all(r.cycle == 2019 for r in rows)
    assert all(r.round_number == 1 for r in rows)
    assert {r.candidate_name for r in rows} == {
        "Sandra Torres",
        "Alejandro Giammattei",
        "Edmond Mulet",
        "Otros (resto del campo)",
    }


def test_parse_presidential_round2_happy_path() -> None:
    rows = m.parse_presidential_table(_presidential_round2_rows(), round_number=2)
    assert len(rows) == 3
    assert all(r.round_number == 2 for r in rows)


def test_parse_presidential_invalid_round() -> None:
    with pytest.raises(m.TableDriftError, match="round_number"):
        m.parse_presidential_table(
            _presidential_round1_rows(), round_number=99
        )


def test_parse_presidential_empty_table_drift() -> None:
    with pytest.raises(m.TableDriftError, match="empty"):
        m.parse_presidential_table([], round_number=1)


def test_parse_presidential_missing_column_typed_error() -> None:
    mangled = [
        {
            "geography_level": "country",
            "geography_code": "GT",
            # 'candidate' deleted — mimics a Memoria PDF that re-labels the
            # candidate column to "Postulante" (real failure mode in 2007).
            "votes": 1_113_433,
        }
    ]
    with pytest.raises(m.MissingColumnError) as exc:
        m.parse_presidential_table(mangled, round_number=1)
    assert "candidate" in exc.value.missing


def test_parse_presidential_row_total_mismatch() -> None:
    bad = [
        {
            "geography_level": "country",
            "geography_code": "GT",
            "candidate": "Sandra Torres",
            "votes": 100,
            "expected_total": 1000,  # sum is 100 + 200 = 300, not 1000
        },
        {
            "geography_level": "country",
            "geography_code": "GT",
            "candidate": "Alejandro Giammattei",
            "votes": 200,
            "expected_total": 1000,
        },
    ]
    with pytest.raises(m.RowTotalMismatchError) as exc:
        m.parse_presidential_table(bad, round_number=1)
    assert exc.value.observed == 300
    assert exc.value.expected == 1000


def test_parse_presidential_non_integer_vote_raises() -> None:
    bad = [
        {
            "geography_level": "country",
            "geography_code": "GT",
            "candidate": "Sandra Torres",
            "votes": "not-a-number",
        }
    ]
    with pytest.raises(m.TableDriftError, match="not an integer"):
        m.parse_presidential_table(bad, round_number=1)


def test_parse_presidential_bool_in_vote_column_raises() -> None:
    # Drift mode: pdfplumber sometimes returns a checkbox glyph as the
    # cell value, which Python parses as True. That must NOT silently
    # become `votes=1`.
    bad = [
        {
            "geography_level": "country",
            "geography_code": "GT",
            "candidate": "Sandra Torres",
            "votes": True,
        }
    ]
    with pytest.raises(m.TableDriftError, match="bool"):
        m.parse_presidential_table(bad, round_number=1)


def test_parse_congress_distrital_happy_path() -> None:
    rows = m.parse_congress_table(
        _congress_distrital_rows(), chamber="congress_distrital"
    )
    assert len(rows) == 3
    assert all(r.chamber == "congress_distrital" for r in rows)
    assert {r.district_code for r in rows} == {"01", "02"}


def test_parse_congress_nacional_synthesises_country_code() -> None:
    rows = m.parse_congress_table(
        _congress_nacional_rows(), chamber="congress_nacional"
    )
    assert all(r.district_code == "GT" for r in rows)


def test_parse_congress_nacional_coerces_string_vote_with_commas() -> None:
    rows = m.parse_congress_table(
        _congress_nacional_rows(), chamber="congress_nacional"
    )
    une = next(r for r in rows if r.party_name == "UNE")
    assert une.votes == 510_000


def test_parse_parlacen_synthesises_parlacen_code() -> None:
    rows = m.parse_congress_table(_parlacen_rows(), chamber="parlacen")
    assert all(r.district_code == "GT-PARLACEN" for r in rows)
    assert all(r.chamber == "parlacen" for r in rows)


def test_parse_congress_missing_seats_column() -> None:
    bad = [{"district_code": "01", "party": "UNE", "votes": 91_000}]
    with pytest.raises(m.MissingColumnError) as exc:
        m.parse_congress_table(bad, chamber="congress_distrital")
    assert "seats" in exc.value.missing


def test_parse_municipal_happy_path() -> None:
    rows = m.parse_municipal_table(_municipal_rows())
    assert len(rows) == 3
    winners = [r for r in rows if r.alcalde_won]
    assert len(winners) == 2
    assert {r.municipality_code for r in winners} == {"0101", "0102"}


def test_parse_municipal_double_winner_raises() -> None:
    bad = [
        {
            "municipality_code": "0101",
            "party": "VAMOS",
            "alcalde_votes": 42_000,
            "alcalde_won": True,
        },
        {
            "municipality_code": "0101",
            "party": "UNE",
            "alcalde_votes": 31_000,
            "alcalde_won": True,  # two winners — must raise
        },
    ]
    with pytest.raises(m.TableDriftError, match="2 winners"):
        m.parse_municipal_table(bad)


def test_parse_municipal_string_boolean_coerced() -> None:
    rows = m.parse_municipal_table(
        [
            {
                "municipality_code": "0101",
                "party": "VAMOS",
                "alcalde_votes": 42_000,
                "alcalde_won": "true",
            }
        ]
    )
    assert rows[0].alcalde_won is True


def test_parse_municipal_garbage_boolean_raises() -> None:
    with pytest.raises(m.TableDriftError, match="alcalde_won"):
        m.parse_municipal_table(
            [
                {
                    "municipality_code": "0101",
                    "party": "VAMOS",
                    "alcalde_votes": 42_000,
                    "alcalde_won": 17,  # not bool-like
                }
            ]
        )


# ---------------------------------------------------------------------------
# Cross-validation against the (future) #19 Excel loader
# ---------------------------------------------------------------------------


def _build_excel_presidential() -> tuple[m.PresidentialRow, ...]:
    """Stand-in: what the #19 loader would emit for the same country roll-up."""
    pdf_rows = m.parse_presidential_table(
        _presidential_round1_rows(), round_number=1
    ) + m.parse_presidential_table(_presidential_round2_rows(), round_number=2)
    return pdf_rows


def test_cross_validate_matches_when_identical() -> None:
    pdf_rows = _build_excel_presidential()
    excel_rows = _build_excel_presidential()
    result = m.cross_validate_presidential(pdf_rows, excel_rows)
    assert result.matches
    assert result.pdf_row_count == result.excel_row_count


def test_cross_validate_row_count_drift_raises() -> None:
    pdf_rows = _build_excel_presidential()
    excel_rows = pdf_rows[:-1]  # drop one row — same totals, fewer rows
    # Same totals so the total-check passes; the row count check should
    # then trip TableDriftError.
    excel_rows_with_topup = (
        *excel_rows,
        m.PresidentialRow(
            cycle=2019,
            round_number=2,
            candidate_name="Nulos+Blancos",
            geography_level="country",
            geography_code="GT",
            votes=pdf_rows[-1].votes,
        ),
    )
    # Build a divergent count without touching totals: drop two rows and
    # roll their votes into one.
    excel_rows_short = pdf_rows[:-2] + (
        m.PresidentialRow(
            cycle=2019,
            round_number=2,
            candidate_name="Merged",
            geography_level="country",
            geography_code="GT",
            votes=pdf_rows[-2].votes + pdf_rows[-1].votes,
        ),
    )
    assert excel_rows_with_topup  # keep mypy/ruff happy about unused locals
    with pytest.raises(m.TableDriftError, match="PDF has"):
        m.cross_validate_presidential(pdf_rows, excel_rows_short)


def test_cross_validate_national_total_drift_raises() -> None:
    pdf_rows = _build_excel_presidential()
    excel_rows = (
        *pdf_rows[:-1],
        m.PresidentialRow(
            cycle=pdf_rows[-1].cycle,
            round_number=pdf_rows[-1].round_number,
            candidate_name=pdf_rows[-1].candidate_name,
            geography_level=pdf_rows[-1].geography_level,
            geography_code=pdf_rows[-1].geography_code,
            votes=pdf_rows[-1].votes + 999,  # off by 999
        ),
    )
    with pytest.raises(m.RowTotalMismatchError) as exc:
        m.cross_validate_presidential(pdf_rows, excel_rows)
    assert exc.value.observed != exc.value.expected


# ---------------------------------------------------------------------------
# extract_from_pdf orchestration (uses injected rows, no real PDF needed)
# ---------------------------------------------------------------------------


def _write_empty_pdf(tmp_path: Path) -> Path:
    """Write a minimal valid PDF stub so ``Path.exists()`` and SHA-256
    work; we never actually parse the bytes when injecting raw rows."""
    p = tmp_path / "memoria_2019.pdf"
    p.write_bytes(b"%PDF-1.4\n%fake test stub\n%%EOF\n")
    return p


def test_extract_from_pdf_with_injected_rows_round_trips(tmp_path: Path) -> None:
    path = _write_empty_pdf(tmp_path)
    result = m.extract_from_pdf(
        path,
        presidential_round_1=_presidential_round1_rows(),
        presidential_round_2=_presidential_round2_rows(),
        congress_distrital=_congress_distrital_rows(),
        congress_nacional=_congress_nacional_rows(),
        parlacen=_parlacen_rows(),
        municipal=_municipal_rows(),
    )
    assert len(result.presidential) == 7
    assert {r.chamber for r in result.congress} == {
        "congress_distrital",
        "congress_nacional",
        "parlacen",
    }
    assert len(result.municipal) == 3
    assert result.source_sha256


def test_extract_from_pdf_is_idempotent(tmp_path: Path) -> None:
    path = _write_empty_pdf(tmp_path)
    kwargs: dict[str, object] = dict(
        presidential_round_1=_presidential_round1_rows(),
        presidential_round_2=_presidential_round2_rows(),
        congress_distrital=_congress_distrital_rows(),
        congress_nacional=_congress_nacional_rows(),
        parlacen=_parlacen_rows(),
        municipal=_municipal_rows(),
    )
    a = m.extract_from_pdf(path, **kwargs)  # type: ignore[arg-type]
    b = m.extract_from_pdf(path, **kwargs)  # type: ignore[arg-type]
    assert a == b
    assert a.fingerprint() == b.fingerprint()


def test_extract_from_pdf_missing_file_raises(tmp_path: Path) -> None:
    with pytest.raises(FileNotFoundError):
        m.extract_from_pdf(tmp_path / "does-not-exist.pdf")


def test_extract_from_pdf_without_dispatch_raises_drift(tmp_path: Path) -> None:
    """When no raw rows are injected and pdfplumber returns nothing useful
    from our stub PDF, the function must fail loudly with TableDriftError —
    never silently emit an empty result."""
    path = _write_empty_pdf(tmp_path)
    with pytest.raises(m.TableDriftError):
        m.extract_from_pdf(path)


# ---------------------------------------------------------------------------
# scrape_runs stamping (best-effort)
# ---------------------------------------------------------------------------


class _FakeCursor:
    def __init__(self, table_exists: bool) -> None:
        self._table_exists = table_exists
        self.executed: list[tuple[str, object]] = []
        self._fetch_one: object = (table_exists,)

    def execute(self, sql: str, params: object = ()) -> None:
        self.executed.append((sql, params))
        if "information_schema.tables" in sql:
            self._fetch_one = (self._table_exists,)
        else:
            self._fetch_one = None

    def fetchone(self) -> object:
        return self._fetch_one

    def __enter__(self) -> _FakeCursor:
        return self

    def __exit__(self, *args: object) -> None:
        return None


class _FakeConn:
    def __init__(self, table_exists: bool) -> None:
        self.cursor_inst = _FakeCursor(table_exists)

    def cursor(self) -> _FakeCursor:
        return self.cursor_inst


def test_stamp_scrape_run_skips_when_table_absent() -> None:
    conn = _FakeConn(table_exists=False)
    wrote = m.stamp_scrape_run(cast("psycopg.Connection", conn), success=True)
    assert wrote is False
    # Only the existence-check SQL fired; no INSERT.
    sql_executed = [sql for sql, _ in conn.cursor_inst.executed]
    assert len(sql_executed) == 1
    assert "information_schema.tables" in sql_executed[0]


def test_stamp_scrape_run_writes_when_table_present() -> None:
    conn = _FakeConn(table_exists=True)
    wrote = m.stamp_scrape_run(
        cast("psycopg.Connection", conn),
        source="memoria_2019",
        success=True,
        error_message=None,
    )
    assert wrote is True
    sql_executed = [sql for sql, _ in conn.cursor_inst.executed]
    assert any("INSERT INTO scrape_runs" in s for s in sql_executed)


# ---------------------------------------------------------------------------
# End-to-end Postgres test — guarded by env var, like the seed tests
# ---------------------------------------------------------------------------


_TEST_DSN = os.environ.get("POLITYK_TEST_DATABASE_URL")


@pytest.mark.skipif(_TEST_DSN is None, reason="POLITYK_TEST_DATABASE_URL not set")
def test_stamp_scrape_run_against_real_postgres() -> None:
    """When the scrape_runs table exists, stamping writes and upserts.

    The migration that creates ``scrape_runs`` lands in a later issue, so
    we create it inside the test transaction (and roll back at the end)
    rather than asserting against the live schema. That way we don't
    pre-empt the migration's PK / column definitions.
    """
    import psycopg

    assert _TEST_DSN is not None
    with psycopg.connect(_TEST_DSN) as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                CREATE TEMPORARY TABLE IF NOT EXISTS scrape_runs (
                    source TEXT PRIMARY KEY,
                    last_run_at TIMESTAMPTZ NOT NULL,
                    success BOOLEAN NOT NULL,
                    error_message TEXT
                )
                """
            )
        first = m.stamp_scrape_run(conn, success=True)
        second = m.stamp_scrape_run(conn, success=False, error_message="boom")
        assert first and second
        with conn.cursor() as cur:
            cur.execute(
                "SELECT source, success, error_message FROM scrape_runs"
            )
            rows = cur.fetchall()
        # Idempotent upsert: still exactly one row, with the second values.
        assert len(rows) == 1
        assert rows[0] == ("memoria_2019", False, "boom")
        conn.rollback()
