"""Smoke tests for the Memoria Electoral 2011 PDF extractor (issue #21).

The fixtures here are the published TSE national totals for the 2011
cycle, with the same reconciliation strategy as
:mod:`test_memoria_2007`.

Published references:
* First round (11 Sep 2011), votos válidos: 4,400,432
  (Otto Pérez Molina 1,610,910 + Manuel Baldizón 1,066,041 + rest)
* Second round (6 Nov 2011), votos válidos: 4,282,367
  (Otto Pérez Molina 2,300,979 + Manuel Baldizón 1,981,388)
* Congress 2011: 158 seats (127 distrital + 31 nacional)
"""

from __future__ import annotations

from pathlib import Path

import pytest

from pipeline.parsers import memoria_2011 as m


def _r1_rows() -> list[dict[str, object]]:
    return [
        {
            "geography_level": "country",
            "geography_code": "GT",
            "candidate": "Otto Pérez Molina",
            "votes": 1_610_910,
            "expected_total": m.PUBLISHED_PRESIDENTIAL_TOTAL_ROUND_1,
        },
        {
            "geography_level": "country",
            "geography_code": "GT",
            "candidate": "Manuel Baldizón",
            "votes": 1_066_041,
            "expected_total": m.PUBLISHED_PRESIDENTIAL_TOTAL_ROUND_1,
        },
        {
            "geography_level": "country",
            "geography_code": "GT",
            "candidate": "Otros (resto del campo)",
            # 4_400_432 - 1_610_910 - 1_066_041 = 1_723_481
            "votes": 1_723_481,
            "expected_total": m.PUBLISHED_PRESIDENTIAL_TOTAL_ROUND_1,
        },
    ]


def _r2_rows() -> list[dict[str, object]]:
    return [
        {
            "geography_level": "country",
            "geography_code": "GT",
            "candidate": "Otto Pérez Molina",
            "votes": 2_300_979,
            "expected_total": m.PUBLISHED_PRESIDENTIAL_TOTAL_ROUND_2,
        },
        {
            "geography_level": "country",
            "geography_code": "GT",
            "candidate": "Manuel Baldizón",
            "votes": 1_981_388,
            "expected_total": m.PUBLISHED_PRESIDENTIAL_TOTAL_ROUND_2,
        },
    ]


def _congress_distrital_rows() -> list[dict[str, object]]:
    return [
        {"district_code": "01", "party": "PP", "votes": 220_000, "seats": 60},
        {"district_code": "01", "party": "LIDER", "votes": 200_000, "seats": 67},
    ]


def _congress_nacional_rows() -> list[dict[str, object]]:
    return [
        {"party": "PP", "votes": 1_300_000, "seats": 17},
        {"party": "LIDER", "votes": 1_200_000, "seats": 14},
    ]


def _municipal_rows() -> list[dict[str, object]]:
    return [
        {
            "municipality_code": "0101",
            "party": "PP",
            "alcalde_votes": 60_000,
            "alcalde_won": True,
        },
        {
            "municipality_code": "0101",
            "party": "LIDER",
            "alcalde_votes": 42_000,
            "alcalde_won": False,
        },
    ]


def _write_stub_pdf(tmp_path: Path) -> Path:
    p = tmp_path / "memoria_2011.pdf"
    p.write_bytes(b"%PDF-1.4\n%fake 2011 stub\n%%EOF\n")
    return p


def test_cycle_constants_match_2011() -> None:
    assert m.CYCLE == 2011
    assert m.SCRAPE_RUNS_SOURCE == "memoria_2011"
    assert m.EXPECTED_CONGRESS_SEATS == 158
    assert m.PUBLISHED_PRESIDENTIAL_TOTAL_ROUND_1 == 4_400_432
    assert m.PUBLISHED_PRESIDENTIAL_TOTAL_ROUND_2 == 4_282_367


def test_parse_presidential_round1_stamps_cycle_2011() -> None:
    rows = m.parse_presidential_table(_r1_rows(), round_number=1)
    assert len(rows) == 3
    assert all(r.cycle == 2011 for r in rows)
    assert sum(r.votes for r in rows) == m.PUBLISHED_PRESIDENTIAL_TOTAL_ROUND_1


def test_parse_presidential_round2_stamps_cycle_2011() -> None:
    rows = m.parse_presidential_table(_r2_rows(), round_number=2)
    assert len(rows) == 2
    assert all(r.cycle == 2011 for r in rows)
    assert sum(r.votes for r in rows) == m.PUBLISHED_PRESIDENTIAL_TOTAL_ROUND_2


def test_parse_presidential_missing_column_typed_error() -> None:
    bad = [
        {
            "geography_level": "country",
            "geography_code": "GT",
            # 'candidate' deleted — mimics a 2011 PDF that re-labelled the
            # column. Shared typed-error contract from memoria_2019.
            "votes": 100,
        }
    ]
    with pytest.raises(m.MissingColumnError) as exc:
        m.parse_presidential_table(bad, round_number=1)
    assert "candidate" in exc.value.missing


def test_parse_congress_seats_sum_to_158() -> None:
    distrital = m.parse_congress_table(
        _congress_distrital_rows(), chamber="congress_distrital"
    )
    nacional = m.parse_congress_table(
        _congress_nacional_rows(), chamber="congress_nacional"
    )
    total_seats = sum(r.seats for r in distrital) + sum(r.seats for r in nacional)
    assert total_seats == m.EXPECTED_CONGRESS_SEATS == 158
    assert all(r.cycle == 2011 for r in distrital)
    assert all(r.cycle == 2011 for r in nacional)


def test_parse_municipal_stamps_cycle_2011() -> None:
    rows = m.parse_municipal_table(_municipal_rows())
    assert len(rows) == 2
    assert all(r.cycle == 2011 for r in rows)


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
    assert all(r.cycle == 2011 for r in result.presidential)
    assert all(r.cycle == 2011 for r in result.congress)
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


def test_stamp_scrape_run_uses_memoria_2011_source() -> None:
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
    assert params[0] == "memoria_2011"
