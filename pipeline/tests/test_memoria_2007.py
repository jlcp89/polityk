"""Smoke tests for the Memoria Electoral 2007 PDF extractor (issue #21).

The fixtures here are the published TSE national totals for the 2007
cycle. The parser reconciles each row's vote bucket against the
published total via :class:`RowTotalMismatchError` — so a passing test
proves the per-cycle wiring (cycle stamp, scrape-runs source, seat
total) without needing the real PDF binary in the repo.

Published references:
* First round (9 Sep 2007), votos válidos: 3,402,335
  (Álvaro Colom 926,236 + Otto Pérez Molina 771,813 + rest of field)
* Second round (4 Nov 2007), votos válidos: 2,685,169
  (Álvaro Colom 1,449,153 + Otto Pérez Molina 1,236,016)
* Congress 2007: 158 seats (127 distrital + 31 nacional)
"""

from __future__ import annotations

from pathlib import Path

import pytest

from pipeline.parsers import memoria_2007 as m


def _r1_rows() -> list[dict[str, object]]:
    """Two named candidates + "Otros" bucket totalling 3,402,335."""
    return [
        {
            "geography_level": "country",
            "geography_code": "GT",
            "candidate": "Álvaro Colom",
            "votes": 926_236,
            "expected_total": m.PUBLISHED_PRESIDENTIAL_TOTAL_ROUND_1,
        },
        {
            "geography_level": "country",
            "geography_code": "GT",
            "candidate": "Otto Pérez Molina",
            "votes": 771_813,
            "expected_total": m.PUBLISHED_PRESIDENTIAL_TOTAL_ROUND_1,
        },
        {
            "geography_level": "country",
            "geography_code": "GT",
            "candidate": "Otros (resto del campo)",
            # 3_402_335 - 926_236 - 771_813 = 1_704_286
            "votes": 1_704_286,
            "expected_total": m.PUBLISHED_PRESIDENTIAL_TOTAL_ROUND_1,
        },
    ]


def _r2_rows() -> list[dict[str, object]]:
    """Runoff is a two-candidate race; sum = 2,685,169."""
    return [
        {
            "geography_level": "country",
            "geography_code": "GT",
            "candidate": "Álvaro Colom",
            "votes": 1_449_153,
            "expected_total": m.PUBLISHED_PRESIDENTIAL_TOTAL_ROUND_2,
        },
        {
            "geography_level": "country",
            "geography_code": "GT",
            "candidate": "Otto Pérez Molina",
            "votes": 1_236_016,
            "expected_total": m.PUBLISHED_PRESIDENTIAL_TOTAL_ROUND_2,
        },
    ]


def _congress_distrital_rows() -> list[dict[str, object]]:
    """Synthetic distrital fixture totalling 127 seats across 2 parties."""
    return [
        {"district_code": "01", "party": "UNE", "votes": 200_000, "seats": 70},
        {"district_code": "01", "party": "PP", "votes": 180_000, "seats": 57},
    ]


def _congress_nacional_rows() -> list[dict[str, object]]:
    """Lista nacional fixture totalling 31 seats (so combined = 158)."""
    return [
        {"party": "UNE", "votes": 1_200_000, "seats": 17},
        {"party": "PP", "votes": 1_050_000, "seats": 14},
    ]


def _municipal_rows() -> list[dict[str, object]]:
    return [
        {
            "municipality_code": "0101",
            "party": "UNE",
            "alcalde_votes": 50_000,
            "alcalde_won": True,
        },
        {
            "municipality_code": "0101",
            "party": "PP",
            "alcalde_votes": 38_000,
            "alcalde_won": False,
        },
    ]


def _write_stub_pdf(tmp_path: Path) -> Path:
    p = tmp_path / "memoria_2007.pdf"
    p.write_bytes(b"%PDF-1.4\n%fake 2007 stub\n%%EOF\n")
    return p


# ---------------------------------------------------------------------------
# Per-cycle wiring tests
# ---------------------------------------------------------------------------


def test_cycle_constants_match_2007() -> None:
    assert m.CYCLE == 2007
    assert m.SCRAPE_RUNS_SOURCE == "memoria_2007"
    assert m.EXPECTED_CONGRESS_SEATS == 158
    assert m.PUBLISHED_PRESIDENTIAL_TOTAL_ROUND_1 == 3_402_335
    assert m.PUBLISHED_PRESIDENTIAL_TOTAL_ROUND_2 == 2_685_169


def test_parse_presidential_round1_stamps_cycle_2007() -> None:
    rows = m.parse_presidential_table(_r1_rows(), round_number=1)
    assert len(rows) == 3
    assert all(r.cycle == 2007 for r in rows)
    assert all(r.round_number == 1 for r in rows)
    # National total reconciles to the published Memoria figure.
    assert sum(r.votes for r in rows) == m.PUBLISHED_PRESIDENTIAL_TOTAL_ROUND_1


def test_parse_presidential_round2_stamps_cycle_2007() -> None:
    rows = m.parse_presidential_table(_r2_rows(), round_number=2)
    assert len(rows) == 2
    assert all(r.cycle == 2007 for r in rows)
    assert sum(r.votes for r in rows) == m.PUBLISHED_PRESIDENTIAL_TOTAL_ROUND_2


def test_parse_presidential_drift_raises_typed_error() -> None:
    """The shared typed-error contract still applies in 2007."""
    bad = [
        {
            "geography_level": "country",
            "geography_code": "GT",
            "candidate": "Álvaro Colom",
            "votes": 100,
            "expected_total": 200,  # 100 != 200 → mismatch
        }
    ]
    with pytest.raises(m.RowTotalMismatchError) as exc:
        m.parse_presidential_table(bad, round_number=1)
    assert exc.value.observed == 100
    assert exc.value.expected == 200


def test_parse_congress_seats_sum_to_158() -> None:
    """Congress 2007 had 158 seats (127 distrital + 31 nacional).

    Verifies the acceptance criterion "Congressional seat totals per
    cycle == 158 in 2007".
    """
    distrital = m.parse_congress_table(
        _congress_distrital_rows(), chamber="congress_distrital"
    )
    nacional = m.parse_congress_table(
        _congress_nacional_rows(), chamber="congress_nacional"
    )
    total_seats = sum(r.seats for r in distrital) + sum(r.seats for r in nacional)
    assert total_seats == m.EXPECTED_CONGRESS_SEATS == 158
    assert all(r.cycle == 2007 for r in distrital)
    assert all(r.cycle == 2007 for r in nacional)
    assert all(r.district_code == "GT" for r in nacional)


def test_parse_municipal_stamps_cycle_2007() -> None:
    rows = m.parse_municipal_table(_municipal_rows())
    assert len(rows) == 2
    assert all(r.cycle == 2007 for r in rows)
    winners = [r for r in rows if r.alcalde_won]
    assert len(winners) == 1


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
    assert len(result.presidential) == 5
    assert all(r.cycle == 2007 for r in result.presidential)
    assert all(r.cycle == 2007 for r in result.congress)
    assert all(r.cycle == 2007 for r in result.municipal)
    # National totals reconcile to the published Memoria figures.
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


# ---------------------------------------------------------------------------
# scrape_runs stamping uses the 'memoria_2007' source
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


def test_stamp_scrape_run_uses_memoria_2007_source() -> None:
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
    assert params[0] == "memoria_2007"
