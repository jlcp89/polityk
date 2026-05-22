"""Tests for the 2023 provisional TSE ingest (issue #22).

Pure-logic tests (manifest parsing, CSV parsing, totals validation) run
unconditionally. The end-to-end Postgres tests run only when
``POLITYK_TEST_DATABASE_URL`` is set in the environment, matching the
pattern used by :mod:`test_geographies_seed` and :mod:`test_memoria_2019`.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import TYPE_CHECKING, cast

import pytest

from pipeline.scrapers.tse import load_2023_provisional as L

if TYPE_CHECKING:
    import psycopg


# ---------------------------------------------------------------------------
# Manifest + CSV parsing
# ---------------------------------------------------------------------------


def test_manifest_parses_two_rounds() -> None:
    rounds = L.load_manifest()
    assert len(rounds) == 2
    round_numbers = [r.round_number for r in rounds]
    assert round_numbers == [1, 2]
    assert rounds[0].acuerdo == "1659-2023"
    assert rounds[1].acuerdo == "1361-2023"
    assert rounds[0].declared_total_valid_votes > 0
    assert rounds[1].declared_total_valid_votes > 0


def test_csv_round1_per_candidate_sum_matches_declared_total() -> None:
    rounds = L.load_manifest()
    r1 = next(r for r in rounds if r.round_number == 1)
    rows = L.load_round_csv(r1.csv_path)
    L.validate_round_totals(r1, rows)  # raises if mismatch
    assert sum(r.votes for r in rows) == r1.declared_total_valid_votes


def test_csv_round2_per_candidate_sum_matches_declared_total() -> None:
    rounds = L.load_manifest()
    r2 = next(r for r in rounds if r.round_number == 2)
    rows = L.load_round_csv(r2.csv_path)
    L.validate_round_totals(r2, rows)
    assert sum(r.votes for r in rows) == r2.declared_total_valid_votes


def test_csv_round2_has_two_candidates() -> None:
    rounds = L.load_manifest()
    r2 = next(r for r in rounds if r.round_number == 2)
    rows = L.load_round_csv(r2.csv_path)
    assert len(rows) == 2
    names = {r.candidate_name for r in rows}
    assert names == {"Bernardo Arévalo", "Sandra Torres"}


def test_validate_round_totals_raises_on_mismatch(tmp_path: Path) -> None:
    csv = tmp_path / "bad.csv"
    csv.write_text(
        "candidate_name,party_tse_code,votes\n"
        "A,P1,100\n"
        "B,P2,200\n",
        encoding="utf-8",
    )
    manifest = L.RoundManifest(
        round_number=1,
        acuerdo="TEST-2023",
        csv_path=csv,
        declared_total_valid_votes=999,  # ≠ 300
    )
    rows = L.load_round_csv(csv)
    with pytest.raises(L.ProvisionalTotalsMismatchError) as exc_info:
        L.validate_round_totals(manifest, rows)
    assert exc_info.value.round_number == 1
    assert exc_info.value.acuerdo == "TEST-2023"
    assert exc_info.value.observed == 300
    assert exc_info.value.declared == 999


def test_load_round_csv_rejects_negative_votes(tmp_path: Path) -> None:
    csv = tmp_path / "neg.csv"
    csv.write_text(
        "candidate_name,party_tse_code,votes\nA,P1,-5\n", encoding="utf-8"
    )
    with pytest.raises(L.ProvisionalManifestError, match="negative votes"):
        L.load_round_csv(csv)


def test_load_round_csv_rejects_duplicate_rows(tmp_path: Path) -> None:
    csv = tmp_path / "dup.csv"
    csv.write_text(
        "candidate_name,party_tse_code,votes\nA,P1,10\nA,P1,20\n",
        encoding="utf-8",
    )
    with pytest.raises(L.ProvisionalManifestError, match="duplicate"):
        L.load_round_csv(csv)


def test_load_round_csv_rejects_missing_column(tmp_path: Path) -> None:
    csv = tmp_path / "missing.csv"
    csv.write_text(
        "candidate_name,votes\nA,100\n", encoding="utf-8"
    )
    with pytest.raises(L.ProvisionalManifestError, match="party_tse_code"):
        L.load_round_csv(csv)


def test_load_round_csv_rejects_empty_csv(tmp_path: Path) -> None:
    csv = tmp_path / "empty.csv"
    csv.write_text("candidate_name,party_tse_code,votes\n", encoding="utf-8")
    with pytest.raises(L.ProvisionalManifestError, match="no data rows"):
        L.load_round_csv(csv)


def test_load_round_csv_parses_thousands_separators(tmp_path: Path) -> None:
    csv = tmp_path / "commas.csv"
    csv.write_text(
        "candidate_name,party_tse_code,votes\nA,P1,\"1,234,567\"\n",
        encoding="utf-8",
    )
    rows = L.load_round_csv(csv)
    assert rows[0].votes == 1_234_567


def test_load_manifest_missing_round_raises(tmp_path: Path) -> None:
    bad = tmp_path / "bad_manifest.json"
    bad.write_text(json.dumps({"rounds": [{"round": 1, "acuerdo": "x",
                  "csv": "x.csv", "declared_total_valid_votes": 1}]}),
                   encoding="utf-8")
    (tmp_path / "x.csv").write_text(
        "candidate_name,party_tse_code,votes\nA,P,1\n", encoding="utf-8"
    )
    with pytest.raises(L.ProvisionalManifestError, match="rounds 1 and 2"):
        L.load_manifest(bad)


def test_load_manifest_missing_csv_raises(tmp_path: Path) -> None:
    bad = tmp_path / "bad_manifest.json"
    bad.write_text(json.dumps({"rounds": [
        {"round": 1, "acuerdo": "x", "csv": "missing1.csv",
         "declared_total_valid_votes": 1},
        {"round": 2, "acuerdo": "x", "csv": "missing2.csv",
         "declared_total_valid_votes": 1},
    ]}), encoding="utf-8")
    with pytest.raises(L.ProvisionalManifestError, match="missing CSV"):
        L.load_manifest(bad)


def test_constants_exposed() -> None:
    assert L.CYCLE == 2023
    assert L.SCRAPE_RUNS_SOURCE == "tse_provisional_2023"
    assert L.NATIONAL_GEOGRAPHY_CODE == "GT"


# ---------------------------------------------------------------------------
# End-to-end Postgres tests — gated on POLITYK_TEST_DATABASE_URL
# ---------------------------------------------------------------------------


_TEST_DSN = os.environ.get("POLITYK_TEST_DATABASE_URL")
pytestmark_db = pytest.mark.skipif(
    _TEST_DSN is None, reason="POLITYK_TEST_DATABASE_URL not set"
)


def _connect() -> psycopg.Connection:
    import psycopg

    assert _TEST_DSN is not None
    return psycopg.connect(_TEST_DSN)


def _ensure_country_geography(conn: psycopg.Connection) -> None:
    """Make sure the country-level GT row exists for the FK target."""
    with conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO geographies (level, code, name)
            VALUES ('country', 'GT', 'Guatemala')
            ON CONFLICT (level, code) DO NOTHING
            """
        )
    conn.commit()


def _ensure_is_provisional_column(conn: psycopg.Connection) -> None:
    """Add elections.is_provisional if migration 0022 hasn't been applied."""
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT EXISTS (
                SELECT 1 FROM information_schema.columns
                WHERE table_name = 'elections' AND column_name = 'is_provisional'
            )
            """
        )
        row = cur.fetchone()
        if row is None or not row[0]:
            cur.execute(
                "ALTER TABLE elections ADD COLUMN is_provisional BOOLEAN "
                "NOT NULL DEFAULT FALSE"
            )
    conn.commit()


def _cleanup(conn: psycopg.Connection) -> None:
    """Wipe rows the loader created so each test starts clean."""
    with conn.cursor() as cur:
        cur.execute(
            """
            DELETE FROM presidential_results
            WHERE election_id IN (SELECT election_id FROM elections WHERE cycle = 2023)
            """
        )
        cur.execute("DELETE FROM elections WHERE cycle = 2023")
        all_names = sorted({
            r.candidate_name
            for r in L.load_round_csv(L.load_manifest()[0].csv_path)
        } | {
            r.candidate_name
            for r in L.load_round_csv(L.load_manifest()[1].csv_path)
        })
        if all_names:
            cur.execute(
                "DELETE FROM candidates WHERE full_name = ANY(%s)",
                (all_names,),
            )
        all_codes = sorted({
            r.party_tse_code
            for r in L.load_round_csv(L.load_manifest()[0].csv_path)
        } | {
            r.party_tse_code
            for r in L.load_round_csv(L.load_manifest()[1].csv_path)
        })
        if all_codes:
            cur.execute("DELETE FROM parties WHERE tse_code = ANY(%s)", (all_codes,))
        cur.execute(
            "DELETE FROM scrape_runs WHERE source = %s",
            (L.SCRAPE_RUNS_SOURCE,),
        )
    conn.commit()


@pytestmark_db
def test_run_happy_path_integration() -> None:
    with _connect() as conn:
        _ensure_is_provisional_column(conn)
        _ensure_country_geography(conn)
        _cleanup(conn)

        result = L.run(conn)

        # Two election rows, both provisional.
        with conn.cursor() as cur:
            cur.execute(
                "SELECT round, is_provisional FROM elections "
                "WHERE cycle = 2023 ORDER BY round"
            )
            elections = cur.fetchall()
        assert elections == [(1, True), (2, True)]

        # Round 1 national total matches the Acuerdo's declared total.
        r1, r2 = result.rounds
        r1_id = next(eid for round_n, eid in result.election_ids if round_n == 1)
        r2_id = next(eid for round_n, eid in result.election_ids if round_n == 2)
        with conn.cursor() as cur:
            cur.execute(
                "SELECT SUM(votes) FROM presidential_results WHERE election_id = %s",
                (r1_id,),
            )
            r1_sum = cast(int, cur.fetchone()[0])  # type: ignore[index]
            cur.execute(
                "SELECT SUM(votes) FROM presidential_results WHERE election_id = %s",
                (r2_id,),
            )
            r2_sum = cast(int, cur.fetchone()[0])  # type: ignore[index]
        assert r1_sum == r1.declared_total_valid_votes
        assert r2_sum == r2.declared_total_valid_votes

        # scrape_runs row stamped with success=true.
        with conn.cursor() as cur:
            cur.execute(
                "SELECT success, error_message FROM scrape_runs WHERE source = %s",
                (L.SCRAPE_RUNS_SOURCE,),
            )
            sr = cur.fetchone()
        assert sr is not None and sr[0] is True and sr[1] is None

        _cleanup(conn)


@pytestmark_db
def test_run_is_idempotent_integration() -> None:
    with _connect() as conn:
        _ensure_is_provisional_column(conn)
        _ensure_country_geography(conn)
        _cleanup(conn)

        L.run(conn)
        with conn.cursor() as cur:
            cur.execute(
                "SELECT COUNT(*) FROM presidential_results "
                "WHERE election_id IN (SELECT election_id FROM elections "
                "WHERE cycle = 2023)"
            )
            count_1 = cast(int, cur.fetchone()[0])  # type: ignore[index]
            cur.execute(
                "SELECT COUNT(*) FROM elections WHERE cycle = 2023"
            )
            elections_1 = cast(int, cur.fetchone()[0])  # type: ignore[index]

        # Second run — no net new rows.
        L.run(conn)
        with conn.cursor() as cur:
            cur.execute(
                "SELECT COUNT(*) FROM presidential_results "
                "WHERE election_id IN (SELECT election_id FROM elections "
                "WHERE cycle = 2023)"
            )
            count_2 = cast(int, cur.fetchone()[0])  # type: ignore[index]
            cur.execute(
                "SELECT COUNT(*) FROM elections WHERE cycle = 2023"
            )
            elections_2 = cast(int, cur.fetchone()[0])  # type: ignore[index]

        assert count_1 == count_2 > 0
        assert elections_1 == elections_2 == 2

        _cleanup(conn)


@pytestmark_db
def test_run_stamps_scrape_runs_on_failure_integration(tmp_path: Path) -> None:
    """When the manifest is bad, scrape_runs is stamped success=false."""
    with _connect() as conn:
        _ensure_is_provisional_column(conn)
        _ensure_country_geography(conn)
        _cleanup(conn)

        bad_manifest = tmp_path / "bad.json"
        bad_csv = tmp_path / "bad.csv"
        bad_csv.write_text(
            "candidate_name,party_tse_code,votes\nA,P1,100\n", encoding="utf-8"
        )
        # Round 2 missing — load_manifest will reject.
        bad_manifest.write_text(
            json.dumps({"rounds": [
                {"round": 1, "acuerdo": "X-2023", "csv": "bad.csv",
                 "declared_total_valid_votes": 100},
            ]}),
            encoding="utf-8",
        )

        with pytest.raises(L.ProvisionalManifestError):
            L.run(conn, manifest_path=bad_manifest)

        with conn.cursor() as cur:
            cur.execute(
                "SELECT success, error_message FROM scrape_runs WHERE source = %s",
                (L.SCRAPE_RUNS_SOURCE,),
            )
            sr = cur.fetchone()
        assert sr is not None
        assert sr[0] is False
        assert sr[1] is not None and len(sr[1]) > 0

        _cleanup(conn)
