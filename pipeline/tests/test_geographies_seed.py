"""Tests for the GT geographies seed loader.

Pure-logic tests run unconditionally. The end-to-end Postgres test runs
only when `POLITYK_TEST_DATABASE_URL` is set in the environment, so CI
that doesn't provision Postgres still passes.
"""

from __future__ import annotations

import os
from collections import Counter
from pathlib import Path

import pytest

from pipeline.seed import geographies


def test_csv_row_count_matches_expected() -> None:
    rows = geographies.load_rows()
    assert len(rows) == geographies.EXPECTED_ROW_COUNT == 387


def test_csv_level_counts() -> None:
    rows = geographies.load_rows()
    counts = Counter(r.level for r in rows)
    assert counts == {
        "country": 2,
        "department": 22,
        "district": 23,
        "municipality": 340,
    }


def test_parlacen_row_present() -> None:
    rows = geographies.load_rows()
    parlacen = [r for r in rows if r.level == "country" and r.code == "GT-PARLACEN"]
    assert len(parlacen) == 1
    assert parlacen[0].name == "Nacional (PARLACEN)"


def test_country_rows_have_no_parent() -> None:
    rows = geographies.load_rows()
    for r in rows:
        if r.level == "country":
            assert r.parent_code is None and r.parent_level is None


def test_non_country_rows_have_parent() -> None:
    rows = geographies.load_rows()
    for r in rows:
        if r.level == "country":
            continue
        assert r.parent_code is not None
        assert r.parent_level is not None


def test_no_duplicate_level_code_pairs() -> None:
    rows = geographies.load_rows()
    keys = [(r.level, r.code) for r in rows]
    assert len(keys) == len(set(keys))


def test_load_rows_raises_on_count_drift(tmp_path: Path) -> None:
    bad = tmp_path / "geographies_short.csv"
    bad.write_text("level,code,name,parent_code,parent_level\ncountry,GT,Guatemala,,\n")
    with pytest.raises(ValueError, match="expected 387 rows"):
        geographies.load_rows(bad)


# ---- End-to-end Postgres test --------------------------------------------

_TEST_DSN = os.environ.get("POLITYK_TEST_DATABASE_URL")


@pytest.mark.skipif(_TEST_DSN is None, reason="POLITYK_TEST_DATABASE_URL not set")
def test_seed_is_idempotent_against_real_postgres() -> None:
    import psycopg

    assert _TEST_DSN is not None
    with psycopg.connect(_TEST_DSN) as conn:
        # First seed.
        applied_1 = geographies.seed(conn)
        total_1 = geographies.count(conn)
        # Second seed must not duplicate.
        applied_2 = geographies.seed(conn)
        total_2 = geographies.count(conn)

    assert applied_1 == applied_2 == geographies.EXPECTED_ROW_COUNT
    assert total_1 == total_2 == geographies.EXPECTED_ROW_COUNT


@pytest.mark.skipif(_TEST_DSN is None, reason="POLITYK_TEST_DATABASE_URL not set")
def test_seed_resolves_parent_links() -> None:
    import psycopg

    assert _TEST_DSN is not None
    with psycopg.connect(_TEST_DSN) as conn:
        geographies.seed(conn)
        with conn.cursor() as cur:
            # No row above level=country may have a NULL parent.
            cur.execute(
                """
                SELECT COUNT(*)
                FROM geographies
                WHERE level <> 'country' AND parent_id IS NULL
                """
            )
            orphans = cur.fetchone()
            assert orphans is not None and orphans[0] == 0

            # A spot-check: '0101 Guatemala' municipality parent is the
            # '01 Guatemala' department.
            cur.execute(
                """
                SELECT p.level, p.code
                FROM geographies c
                JOIN geographies p ON p.geography_id = c.parent_id
                WHERE c.level = 'municipality' AND c.code = '0101'
                """
            )
            parent = cur.fetchone()
            assert parent == ("department", "01")
