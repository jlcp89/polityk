"""Smoke tests for the Memoria Electoral 2015 PDF extractor (issue #21).

The fixtures here are the published TSE national totals for the 2015
cycle, with the same reconciliation strategy as
:mod:`test_memoria_2007`.

Published references:
* First round (6 Sep 2015), votos válidos:   4,540,772
  (Jimmy Morales 1,142,070 + Sandra Torres 869,576 + Manuel Baldizón
   856,777 + rest of field)
* Second round (25 Oct 2015), votos válidos: 4,198,978
  (Jimmy Morales 2,750,138 + Sandra Torres 1,448,840)
* Congress 2015: 158 seats (127 distrital + 31 nacional)
"""

from __future__ import annotations

from pathlib import Path

import pytest

from pipeline.parsers import memoria_2015 as m


def _r1_rows() -> list[dict[str, object]]:
    return [
        {
            "geography_level": "country",
            "geography_code": "GT",
            "candidate": "Jimmy Morales",
            "votes": 1_142_070,
            "expected_total": m.PUBLISHED_PRESIDENTIAL_TOTAL_ROUND_1,
        },
        {
            "geography_level": "country",
            "geography_code": "GT",
            "candidate": "Sandra Torres",
            "votes": 869_576,
            "expected_total": m.PUBLISHED_PRESIDENTIAL_TOTAL_ROUND_1,
        },
        {
            "geography_level": "country",
            "geography_code": "GT",
            "candidate": "Manuel Baldizón",
            "votes": 856_777,
            "expected_total": m.PUBLISHED_PRESIDENTIAL_TOTAL_ROUND_1,
        },
        {
            "geography_level": "country",
            "geography_code": "GT",
            "candidate": "Otros (resto del campo)",
            # 4_540_772 - 1_142_070 - 869_576 - 856_777 = 1_672_349
            "votes": 1_672_349,
            "expected_total": m.PUBLISHED_PRESIDENTIAL_TOTAL_ROUND_1,
        },
    ]


def _r2_rows() -> list[dict[str, object]]:
    return [
        {
            "geography_level": "country",
            "geography_code": "GT",
            "candidate": "Jimmy Morales",
            "votes": 2_750_138,
            "expected_total": m.PUBLISHED_PRESIDENTIAL_TOTAL_ROUND_2,
        },
        {
            "geography_level": "country",
            "geography_code": "GT",
            "candidate": "Sandra Torres",
            "votes": 1_448_840,
            "expected_total": m.PUBLISHED_PRESIDENTIAL_TOTAL_ROUND_2,
        },
    ]


def _congress_distrital_rows() -> list[dict[str, object]]:
    return [
        {"district_code": "01", "party": "LIDER", "votes": 240_000, "seats": 65},
        {"district_code": "01", "party": "UNE", "votes": 220_000, "seats": 62},
    ]


def _congress_nacional_rows() -> list[dict[str, object]]:
    return [
        {"party": "LIDER", "votes": 1_400_000, "seats": 17},
        {"party": "UNE", "votes": 1_250_000, "seats": 14},
    ]


def _municipal_rows() -> list[dict[str, object]]:
    return [
        {
            "municipality_code": "0101",
            "party": "LIDER",
            "alcalde_votes": 55_000,
            "alcalde_won": True,
        },
        {
            "municipality_code": "0101",
            "party": "UNE",
            "alcalde_votes": 41_000,
            "alcalde_won": False,
        },
    ]


def _write_stub_pdf(tmp_path: Path) -> Path:
    p = tmp_path / "memoria_2015.pdf"
    p.write_bytes(b"%PDF-1.4\n%fake 2015 stub\n%%EOF\n")
    return p


def test_cycle_constants_match_2015() -> None:
    assert m.CYCLE == 2015
    assert m.SCRAPE_RUNS_SOURCE == "memoria_2015"
    assert m.EXPECTED_CONGRESS_SEATS == 158
    assert m.PUBLISHED_PRESIDENTIAL_TOTAL_ROUND_1 == 4_540_772
    assert m.PUBLISHED_PRESIDENTIAL_TOTAL_ROUND_2 == 4_198_978


def test_parse_presidential_round1_stamps_cycle_2015() -> None:
    rows = m.parse_presidential_table(_r1_rows(), round_number=1)
    assert len(rows) == 4
    assert all(r.cycle == 2015 for r in rows)
    assert sum(r.votes for r in rows) == m.PUBLISHED_PRESIDENTIAL_TOTAL_ROUND_1


def test_parse_presidential_round2_stamps_cycle_2015() -> None:
    rows = m.parse_presidential_table(_r2_rows(), round_number=2)
    assert len(rows) == 2
    assert all(r.cycle == 2015 for r in rows)
    assert sum(r.votes for r in rows) == m.PUBLISHED_PRESIDENTIAL_TOTAL_ROUND_2


def test_parse_presidential_bool_in_vote_column_typed_error() -> None:
    """Shared bool-in-vote-column drift detector still applies in 2015."""
    bad = [
        {
            "geography_level": "country",
            "geography_code": "GT",
            "candidate": "Jimmy Morales",
            "votes": True,
        }
    ]
    with pytest.raises(m.TableDriftError, match="bool"):
        m.parse_presidential_table(bad, round_number=1)


def test_parse_congress_seats_sum_to_158() -> None:
    distrital = m.parse_congress_table(
        _congress_distrital_rows(), chamber="congress_distrital"
    )
    nacional = m.parse_congress_table(
        _congress_nacional_rows(), chamber="congress_nacional"
    )
    total_seats = sum(r.seats for r in distrital) + sum(r.seats for r in nacional)
    assert total_seats == m.EXPECTED_CONGRESS_SEATS == 158
    assert all(r.cycle == 2015 for r in distrital)
    assert all(r.cycle == 2015 for r in nacional)


def test_parse_municipal_stamps_cycle_2015() -> None:
    rows = m.parse_municipal_table(_municipal_rows())
    assert len(rows) == 2
    assert all(r.cycle == 2015 for r in rows)


def test_extract_from_pdf_full_roundtrip(tmp_path: Path) -> None:
    path = _write_stub_pdf(tmp_path)
    result = m.extract_from_pdf(
        path,
        presidential_round_1=_r1_rows(),
        presidential_round_2=_r2_rows(),
        congress_distrital=_congress_distrital_rows(),
        congress_nacional=_congress_nacional_rows(),
        municipal=_municipal_rows(),
    )
    assert all(r.cycle == 2015 for r in result.presidential)
    assert all(r.cycle == 2015 for r in result.congress)
    r1 = [r for r in result.presidential if r.round_number == 1]
    r2 = [r for r in result.presidential if r.round_number == 2]
    assert sum(r.votes for r in r1) == m.PUBLISHED_PRESIDENTIAL_TOTAL_ROUND_1
    assert sum(r.votes for r in r2) == m.PUBLISHED_PRESIDENTIAL_TOTAL_ROUND_2


def test_extract_from_pdf_is_idempotent(tmp_path: Path) -> None:
    path = _write_stub_pdf(tmp_path)
    a = m.extract_from_pdf(
        path,
        presidential_round_1=_r1_rows(),
        presidential_round_2=_r2_rows(),
        congress_distrital=_congress_distrital_rows(),
        congress_nacional=_congress_nacional_rows(),
        municipal=_municipal_rows(),
    )
    b = m.extract_from_pdf(
        path,
        presidential_round_1=_r1_rows(),
        presidential_round_2=_r2_rows(),
        congress_distrital=_congress_distrital_rows(),
        congress_nacional=_congress_nacional_rows(),
        municipal=_municipal_rows(),
    )
    assert a == b
    assert a.fingerprint() == b.fingerprint()


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


def test_stamp_scrape_run_uses_memoria_2015_source() -> None:
    from typing import cast

    import psycopg

    conn = _FakeConn(table_exists=True)
    wrote = m.stamp_scrape_run(cast("psycopg.Connection", conn), success=True)
    assert wrote is True
    inserts = [
        (sql, params)
        for sql, params in conn.cursor_inst.executed
        if "INSERT INTO scrape_runs" in sql
    ]
    assert len(inserts) == 1
    _, params = inserts[0]
    assert isinstance(params, tuple)
    assert params[0] == "memoria_2015"
