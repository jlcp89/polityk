"""Tests for the TSE 2019 presidential loader.

Pure-logic tests (XLSX parsing) run unconditionally. End-to-end Postgres
tests run only when `POLITYK_TEST_DATABASE_URL` is set so CI without a
DB still passes.
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest
from openpyxl import Workbook

from pipeline.scrapers.tse import load_2019_excel
from pipeline.scrapers.tse.fixtures import build_fixture

# ---- Pure-logic: XLSX parsing --------------------------------------------


def test_fixture_exists() -> None:
    assert load_2019_excel.FIXTURE_PATH.exists(), (
        "committed fixture is missing — regenerate with "
        "`uv run python -m pipeline.scrapers.tse.fixtures.build_fixture`"
    )


def test_parse_fixture_row_count() -> None:
    rows = load_2019_excel.parse_xlsx()
    assert len(rows) == len(build_fixture.ROUND_1_ROWS) + len(build_fixture.ROUND_2_ROWS)


def test_parse_fixture_round1_totals() -> None:
    rows = load_2019_excel.parse_xlsx()
    r1 = [r for r in rows if r.round == 1]
    assert sum(r.votes for r in r1) == build_fixture.EXPECTED_ROUND_1_TOTAL


def test_parse_fixture_round2_totals() -> None:
    rows = load_2019_excel.parse_xlsx()
    r2 = [r for r in rows if r.round == 2]
    assert sum(r.votes for r in r2) == build_fixture.EXPECTED_ROUND_2_TOTAL


def test_parse_fixture_unique_candidates() -> None:
    rows = load_2019_excel.parse_xlsx()
    r1_cands = {r.candidate_full_name for r in rows if r.round == 1}
    r2_cands = {r.candidate_full_name for r in rows if r.round == 2}
    assert len(r1_cands) == 5
    assert len(r2_cands) == 2
    assert r2_cands.issubset(r1_cands)


def test_parse_rejects_missing_sheet(tmp_path: Path) -> None:
    bad = tmp_path / "bad.xlsx"
    wb = Workbook()
    assert wb.active is not None
    wb.active.title = "wrong_sheet_name"
    wb.save(bad)
    with pytest.raises(ValueError, match="missing required 'results' sheet"):
        load_2019_excel.parse_xlsx(bad)


def test_parse_rejects_wrong_header(tmp_path: Path) -> None:
    bad = tmp_path / "bad.xlsx"
    wb = Workbook()
    ws = wb.active
    assert ws is not None
    ws.title = "results"
    ws.append(["wrong", "header", "columns", "here", "now"])
    ws.append([1, "01", "0101", "Foo", 100])
    wb.save(bad)
    with pytest.raises(ValueError, match="unexpected header"):
        load_2019_excel.parse_xlsx(bad)


def test_parse_missing_file_raises(tmp_path: Path) -> None:
    with pytest.raises(FileNotFoundError):
        load_2019_excel.parse_xlsx(tmp_path / "does_not_exist.xlsx")


# ---- Pure-logic: TotalMismatchError --------------------------------------


def test_assert_total_within_tolerance() -> None:
    # exact match
    load_2019_excel._assert_total(1, 100, 100, tolerance=1)
    # within tolerance
    load_2019_excel._assert_total(1, 99, 100, tolerance=1)
    load_2019_excel._assert_total(1, 101, 100, tolerance=1)


def test_assert_total_outside_tolerance() -> None:
    with pytest.raises(load_2019_excel.TotalMismatchError, match="round 1"):
        load_2019_excel._assert_total(1, 98, 100, tolerance=1)


def test_assert_total_skipped_when_expected_none() -> None:
    load_2019_excel._assert_total(1, 9999, None, tolerance=1)


# ---- End-to-end Postgres -------------------------------------------------

_TEST_DSN = os.environ.get("POLITYK_TEST_DATABASE_URL")


def _seed_geographies(conn: object) -> None:
    """Seed the geographies dim — required by `resolve_geography`."""
    from pipeline.seed import geographies

    geographies.seed(conn)


@pytest.mark.skipif(_TEST_DSN is None, reason="POLITYK_TEST_DATABASE_URL not set")
def test_load_writes_presidential_results_and_is_idempotent() -> None:
    import psycopg

    assert _TEST_DSN is not None
    with psycopg.connect(_TEST_DSN) as conn:
        _truncate_all(conn)
        _seed_geographies(conn)

        first = load_2019_excel.load(
            conn,
            expected_round1_total=build_fixture.EXPECTED_ROUND_1_TOTAL,
            expected_round2_total=build_fixture.EXPECTED_ROUND_2_TOTAL,
        )

        with conn.cursor() as cur:
            cur.execute("SELECT COUNT(*) FROM presidential_results")
            count_after_first = cur.fetchone()
            cur.execute("SELECT COUNT(*) FROM candidates")
            cands_after_first = cur.fetchone()

        # Re-run: idempotent.
        second = load_2019_excel.load(
            conn,
            expected_round1_total=build_fixture.EXPECTED_ROUND_1_TOTAL,
            expected_round2_total=build_fixture.EXPECTED_ROUND_2_TOTAL,
        )

        with conn.cursor() as cur:
            cur.execute("SELECT COUNT(*) FROM presidential_results")
            count_after_second = cur.fetchone()
            cur.execute("SELECT COUNT(*) FROM candidates")
            cands_after_second = cur.fetchone()

    assert first.round1_rows == 15
    assert first.round2_rows == 6
    assert first.round1_total == build_fixture.EXPECTED_ROUND_1_TOTAL
    assert first.round2_total == build_fixture.EXPECTED_ROUND_2_TOTAL
    assert first.candidates_created == 5

    assert count_after_first is not None and count_after_first[0] == 21
    assert cands_after_first is not None and cands_after_first[0] == 5

    # Second run: zero new candidates, presidential_results row count stable.
    assert second.candidates_created == 0
    assert count_after_second is not None and count_after_second[0] == 21
    assert cands_after_second is not None and cands_after_second[0] == 5


@pytest.mark.skipif(_TEST_DSN is None, reason="POLITYK_TEST_DATABASE_URL not set")
def test_load_assertion_failure_does_not_publish_partial() -> None:
    import psycopg

    assert _TEST_DSN is not None
    with psycopg.connect(_TEST_DSN) as conn:
        _truncate_all(conn)
        _seed_geographies(conn)

        # Pass a wrong expected total; loader must raise and roll back.
        with pytest.raises(load_2019_excel.TotalMismatchError):
            load_2019_excel.load(
                conn,
                expected_round1_total=build_fixture.EXPECTED_ROUND_1_TOTAL + 100,
            )

        with conn.cursor() as cur:
            cur.execute("SELECT COUNT(*) FROM presidential_results")
            count = cur.fetchone()
            cur.execute("SELECT success, error_message FROM scrape_runs WHERE source = %s",
                        (load_2019_excel.SCRAPE_RUN_SOURCE,))
            audit = cur.fetchone()

    # Rollback: no presidential_results rows persisted.
    assert count is not None and count[0] == 0
    # Failure audit row IS stamped (separate transaction).
    assert audit is not None
    assert audit[0] is False
    assert audit[1] is not None and "round 1 national total mismatch" in audit[1]


@pytest.mark.skipif(_TEST_DSN is None, reason="POLITYK_TEST_DATABASE_URL not set")
def test_load_stamps_scrape_runs_on_success() -> None:
    import psycopg

    assert _TEST_DSN is not None
    with psycopg.connect(_TEST_DSN) as conn:
        _truncate_all(conn)
        _seed_geographies(conn)

        load_2019_excel.load(
            conn,
            expected_round1_total=build_fixture.EXPECTED_ROUND_1_TOTAL,
            expected_round2_total=build_fixture.EXPECTED_ROUND_2_TOTAL,
        )

        with conn.cursor() as cur:
            cur.execute(
                "SELECT source, success, error_message FROM scrape_runs WHERE source = %s",
                (load_2019_excel.SCRAPE_RUN_SOURCE,),
            )
            row = cur.fetchone()

    assert row is not None
    assert row[0] == "tse_excel_2019_presidential"
    assert row[1] is True
    assert row[2] is None


@pytest.mark.skipif(_TEST_DSN is None, reason="POLITYK_TEST_DATABASE_URL not set")
def test_load_national_totals_match_fixture() -> None:
    import psycopg

    assert _TEST_DSN is not None
    with psycopg.connect(_TEST_DSN) as conn:
        _truncate_all(conn)
        _seed_geographies(conn)

        load_2019_excel.load(conn)

        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT e.round, SUM(pr.votes)
                FROM presidential_results pr
                JOIN elections e ON e.election_id = pr.election_id
                WHERE e.cycle = %s
                GROUP BY e.round
                ORDER BY e.round
                """,
                (load_2019_excel.CYCLE,),
            )
            sums = {int(round_): int(total) for round_, total in cur.fetchall()}

    # ±1 vote tolerance (here we built the fixture from exact ints).
    assert abs(sums[1] - build_fixture.EXPECTED_ROUND_1_TOTAL) <= 1
    assert abs(sums[2] - build_fixture.EXPECTED_ROUND_2_TOTAL) <= 1


@pytest.mark.skipif(_TEST_DSN is None, reason="POLITYK_TEST_DATABASE_URL not set")
def test_load_creates_election_rows() -> None:
    import psycopg

    assert _TEST_DSN is not None
    with psycopg.connect(_TEST_DSN) as conn:
        _truncate_all(conn)
        _seed_geographies(conn)

        load_2019_excel.load(
            conn,
            expected_round1_total=build_fixture.EXPECTED_ROUND_1_TOTAL,
            expected_round2_total=build_fixture.EXPECTED_ROUND_2_TOTAL,
        )

        with conn.cursor() as cur:
            cur.execute(
                "SELECT cycle, round FROM elections WHERE cycle = %s ORDER BY round",
                (load_2019_excel.CYCLE,),
            )
            rows = cur.fetchall()

    assert rows == [(2019, 1), (2019, 2)]


def _truncate_all(conn: object) -> None:
    """Wipe state between tests. CASCADE handles every FK edge."""
    with conn.cursor() as cur:  # type: ignore[attr-defined]
        cur.execute(
            "TRUNCATE TABLE presidential_results, congress_results, municipal_results, "
            "candidate_party, candidate_aliases, candidates, party_aliases, "
            "party_eligibility, parties, geographies, elections, scrape_runs "
            "RESTART IDENTITY CASCADE"
        )
    conn.commit()  # type: ignore[attr-defined]
