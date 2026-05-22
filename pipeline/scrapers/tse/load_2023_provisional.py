"""Provisional 2023 presidential ingest from TSE Acuerdos (issue #22).

The 2023 Memoria Electoral has not been published as of 2026-05; the
forecasting model still needs 2023 ground truth to fit the runoff swing
matrix (#32) and to anchor the pollster bias estimator (#29). This loader
holds the line until the Memoria publishes:

- Reads the committed Acuerdo CSV fixtures (one per round) from
  ``pipeline/scrapers/tse/data/`` — the maintainer regenerates them from
  the TSE Acuerdo 1659-2023 (first round) and 1361-2023 (runoff) PDFs.
- Asserts the per-candidate vote sum equals the declared official total
  per round (acceptance criterion: "national vote totals match Acuerdo
  NNNN-2023"). Drift raises :class:`ProvisionalTotalsMismatchError`.
- UPSERTs candidates, parties, the two ``elections`` rows (with
  ``is_provisional = TRUE`` per migration ``0022``), and the
  ``presidential_results`` rows keyed at the country ('GT') geography.
- Stamps ``scrape_runs`` source ``tse_provisional_2023`` on every run,
  success or failure (same pattern as the Go TSE scraper from #15).
- Idempotent: re-running yields zero net changes — both candidate /
  party / election dimensions and the results facts UPSERT on their
  natural keys.

When the 2023 Memoria publishes, a future issue will introduce a
``load_2023_memoria.py`` that overwrites these rows and flips
``elections.is_provisional`` to FALSE; this loader stays in place as a
fallback for the time window before that lands.
"""

from __future__ import annotations

import csv
import json
import logging
import os
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, cast

if TYPE_CHECKING:  # pragma: no cover - typing only
    import psycopg

LOG = logging.getLogger(__name__)

CYCLE: int = 2023
SCRAPE_RUNS_SOURCE: str = "tse_provisional_2023"
NATIONAL_GEOGRAPHY_LEVEL: str = "country"
NATIONAL_GEOGRAPHY_CODE: str = "GT"

DATA_DIR = Path(__file__).parent / "data"
MANIFEST_FILE = DATA_DIR / "2023_provisional.json"


# ---------------------------------------------------------------------------
# Typed errors
# ---------------------------------------------------------------------------


class ProvisionalLoadError(Exception):
    """Base class for every typed error this loader raises."""


class ProvisionalTotalsMismatchError(ProvisionalLoadError):
    """Per-candidate vote sum diverges from the published Acuerdo total."""

    def __init__(self, round_number: int, acuerdo: str, observed: int, declared: int):
        self.round_number = round_number
        self.acuerdo = acuerdo
        self.observed = observed
        self.declared = declared
        super().__init__(
            f"round={round_number} acuerdo={acuerdo}: per-candidate sum "
            f"{observed} != declared total {declared}"
        )


class ProvisionalManifestError(ProvisionalLoadError):
    """The manifest JSON is malformed or references a missing CSV."""


# ---------------------------------------------------------------------------
# Typed rows
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class CandidateVote:
    """A single (candidate, party, votes) row from an Acuerdo CSV."""

    candidate_name: str
    party_tse_code: str
    votes: int


@dataclass(frozen=True)
class RoundManifest:
    """One round's metadata: which Acuerdo, which CSV, declared total."""

    round_number: int
    acuerdo: str
    csv_path: Path
    declared_total_valid_votes: int


@dataclass(frozen=True)
class ProvisionalLoadResult:
    """Outcome of one :func:`run` pass; used by tests and ops dashboards."""

    rounds: tuple[RoundManifest, ...]
    rows_per_round: tuple[tuple[int, int], ...]  # (round_number, row_count)
    election_ids: tuple[tuple[int, int], ...]   # (round_number, election_id)


# ---------------------------------------------------------------------------
# Manifest + CSV parsing (pure logic — no DB)
# ---------------------------------------------------------------------------


def load_manifest(path: Path = MANIFEST_FILE) -> tuple[RoundManifest, ...]:
    """Parse the manifest JSON and return one :class:`RoundManifest` per round."""
    if not path.exists():
        raise ProvisionalManifestError(f"manifest not found: {path}")
    raw = json.loads(path.read_text(encoding="utf-8"))
    rounds_raw = raw.get("rounds")
    if not isinstance(rounds_raw, list) or not rounds_raw:
        raise ProvisionalManifestError(f"manifest missing 'rounds' list: {path}")
    out: list[RoundManifest] = []
    for entry in rounds_raw:
        if not isinstance(entry, dict):
            raise ProvisionalManifestError(f"manifest round entry not a dict: {entry!r}")
        for required in ("round", "acuerdo", "csv", "declared_total_valid_votes"):
            if required not in entry:
                raise ProvisionalManifestError(
                    f"manifest round missing {required!r}: {entry!r}"
                )
        csv_path = path.parent / cast(str, entry["csv"])
        if not csv_path.exists():
            raise ProvisionalManifestError(f"manifest references missing CSV: {csv_path}")
        out.append(
            RoundManifest(
                round_number=int(entry["round"]),
                acuerdo=str(entry["acuerdo"]),
                csv_path=csv_path,
                declared_total_valid_votes=int(entry["declared_total_valid_votes"]),
            )
        )
    rounds = sorted(out, key=lambda r: r.round_number)
    seen = {r.round_number for r in rounds}
    if seen != {1, 2}:
        raise ProvisionalManifestError(
            f"manifest must declare rounds 1 and 2, got {sorted(seen)}"
        )
    return tuple(rounds)


def load_round_csv(path: Path) -> tuple[CandidateVote, ...]:
    """Parse an Acuerdo CSV; preserve original row order."""
    if not path.exists():
        raise ProvisionalManifestError(f"acuerdo CSV not found: {path}")
    rows: list[CandidateVote] = []
    seen_pairs: set[tuple[str, str]] = set()
    with path.open(newline="", encoding="utf-8") as fh:
        reader = csv.DictReader(fh)
        for raw in reader:
            for col in ("candidate_name", "party_tse_code", "votes"):
                if col not in raw or raw[col] is None or raw[col] == "":
                    raise ProvisionalManifestError(
                        f"CSV {path}: row {raw!r} missing column {col!r}"
                    )
            try:
                votes = int(str(raw["votes"]).replace(",", "").replace(" ", ""))
            except ValueError as exc:  # pragma: no cover — guarded by csv format
                raise ProvisionalManifestError(
                    f"CSV {path}: row {raw!r} has non-integer votes"
                ) from exc
            if votes < 0:
                raise ProvisionalManifestError(
                    f"CSV {path}: row {raw!r} has negative votes"
                )
            name = str(raw["candidate_name"]).strip()
            party = str(raw["party_tse_code"]).strip()
            key = (name, party)
            if key in seen_pairs:
                raise ProvisionalManifestError(
                    f"CSV {path}: duplicate (candidate, party) row {key!r}"
                )
            seen_pairs.add(key)
            rows.append(
                CandidateVote(candidate_name=name, party_tse_code=party, votes=votes)
            )
    if not rows:
        raise ProvisionalManifestError(f"CSV {path} has no data rows")
    return tuple(rows)


def validate_round_totals(
    manifest: RoundManifest, rows: Sequence[CandidateVote]
) -> None:
    """Assert per-candidate sum == declared total. Raises on drift."""
    observed = sum(r.votes for r in rows)
    if observed != manifest.declared_total_valid_votes:
        raise ProvisionalTotalsMismatchError(
            round_number=manifest.round_number,
            acuerdo=manifest.acuerdo,
            observed=observed,
            declared=manifest.declared_total_valid_votes,
        )


# ---------------------------------------------------------------------------
# DB-side helpers (psycopg)
# ---------------------------------------------------------------------------


def _ensure_election(
    conn: psycopg.Connection, *, cycle: int, round_number: int, is_provisional: bool
) -> int:
    """UPSERT an ``elections`` row and return its id. Idempotent on (cycle, round)."""
    with conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO elections (cycle, round, is_provisional)
            VALUES (%s, %s, %s)
            ON CONFLICT (cycle, round) DO UPDATE
                SET is_provisional = EXCLUDED.is_provisional
            RETURNING election_id
            """,
            (cycle, round_number, is_provisional),
        )
        row = cur.fetchone()
    if row is None:  # pragma: no cover - UPSERT always returns
        raise ProvisionalLoadError(
            f"failed to UPSERT elections row for cycle={cycle} round={round_number}"
        )
    return cast(int, row[0])


def _resolve_country_geography(conn: psycopg.Connection) -> int:
    """Return the geography_id for (level='country', code='GT')."""
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT geography_id FROM geographies
            WHERE level = %s AND code = %s
            """,
            (NATIONAL_GEOGRAPHY_LEVEL, NATIONAL_GEOGRAPHY_CODE),
        )
        row = cur.fetchone()
    if row is None:
        raise ProvisionalLoadError(
            "country GT geography missing — run pipeline.scripts.seed_geographies first"
        )
    return cast(int, row[0])


def _ensure_party(conn: psycopg.Connection, tse_code: str) -> int:
    """UPSERT a ``parties`` row keyed on tse_code; returns party_id.

    Uses ``tse_code`` as the natural key for re-runnability. ``name`` is set
    to the tse_code on first insert (a maintainer can rename later — the
    party-list scraper from #15 owns canonical names).
    """
    with conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO parties (name, tse_code)
            VALUES (%s, %s)
            ON CONFLICT (tse_code) DO UPDATE
                SET tse_code = EXCLUDED.tse_code
            RETURNING party_id
            """,
            (tse_code, tse_code),
        )
        row = cur.fetchone()
    if row is None:  # pragma: no cover
        raise ProvisionalLoadError(f"failed to UPSERT party tse_code={tse_code}")
    return cast(int, row[0])


def _ensure_candidate(conn: psycopg.Connection, full_name: str) -> int:
    """UPSERT a ``candidates`` row keyed on ``full_name``.

    ``candidates`` has no UNIQUE on ``full_name`` in the base schema, so this
    helper does a SELECT-or-INSERT to stay idempotent on re-run. Two
    candidates with the same name will collapse to one row — acceptable for
    the 2023 provisional path; the entity-resolution work (issue #27) will
    sharpen this when it lands.
    """
    with conn.cursor() as cur:
        cur.execute(
            "SELECT candidate_id FROM candidates WHERE full_name = %s",
            (full_name,),
        )
        row = cur.fetchone()
        if row is not None:
            return cast(int, row[0])
        cur.execute(
            "INSERT INTO candidates (full_name) VALUES (%s) RETURNING candidate_id",
            (full_name,),
        )
        row = cur.fetchone()
    if row is None:  # pragma: no cover
        raise ProvisionalLoadError(f"failed to INSERT candidate {full_name!r}")
    return cast(int, row[0])


def _upsert_presidential_results(
    conn: psycopg.Connection,
    *,
    election_id: int,
    geography_id: int,
    rows: Sequence[tuple[int, int]],  # (candidate_id, votes)
) -> int:
    """UPSERT ``presidential_results`` rows; returns the row count written."""
    with conn.cursor() as cur:
        for candidate_id, votes in rows:
            cur.execute(
                """
                INSERT INTO presidential_results
                    (election_id, candidate_id, geography_id, votes)
                VALUES (%s, %s, %s, %s)
                ON CONFLICT (election_id, candidate_id, geography_id) DO UPDATE
                    SET votes = EXCLUDED.votes
                """,
                (election_id, candidate_id, geography_id, votes),
            )
    return len(rows)


def stamp_scrape_run(
    conn: psycopg.Connection,
    *,
    source: str = SCRAPE_RUNS_SOURCE,
    success: bool,
    error_message: str | None = None,
) -> bool:
    """UPSERT a row into ``scrape_runs`` for this load. Best-effort.

    Returns ``True`` if the row was written, ``False`` if the table doesn't
    exist (the migration that creates it landed in #15; this loader is
    re-runnable against schemas predating that migration).
    """
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT EXISTS (
                SELECT 1 FROM information_schema.tables
                WHERE table_schema = current_schema()
                  AND table_name = 'scrape_runs'
            )
            """
        )
        row = cur.fetchone()
        if not row or not row[0]:
            LOG.info("scrape_runs table not present; skipping stamp for %s", source)
            return False
        cur.execute(
            """
            INSERT INTO scrape_runs (source, last_run_at, success, error_message)
            VALUES (%s, now(), %s, %s)
            ON CONFLICT (source) DO UPDATE
                SET last_run_at = EXCLUDED.last_run_at,
                    success = EXCLUDED.success,
                    error_message = EXCLUDED.error_message
            """,
            (source, success, error_message),
        )
    return True


# ---------------------------------------------------------------------------
# Orchestration
# ---------------------------------------------------------------------------


def run(
    conn: psycopg.Connection,
    *,
    manifest_path: Path = MANIFEST_FILE,
) -> ProvisionalLoadResult:
    """Run the full provisional 2023 ingest and stamp ``scrape_runs``.

    On any error, ``scrape_runs`` is still stamped with ``success=False`` and
    the error message before re-raising — operations dashboards (#14) see
    the failure rather than a silent stale row.
    """
    try:
        rounds = load_manifest(manifest_path)
        geography_id = _resolve_country_geography(conn)

        rows_per_round: list[tuple[int, int]] = []
        election_ids: list[tuple[int, int]] = []

        for round_manifest in rounds:
            csv_rows = load_round_csv(round_manifest.csv_path)
            validate_round_totals(round_manifest, csv_rows)

            election_id = _ensure_election(
                conn,
                cycle=CYCLE,
                round_number=round_manifest.round_number,
                is_provisional=True,
            )
            election_ids.append((round_manifest.round_number, election_id))

            db_rows: list[tuple[int, int]] = []
            for cv in csv_rows:
                _ensure_party(conn, cv.party_tse_code)
                candidate_id = _ensure_candidate(conn, cv.candidate_name)
                db_rows.append((candidate_id, cv.votes))

            written = _upsert_presidential_results(
                conn,
                election_id=election_id,
                geography_id=geography_id,
                rows=db_rows,
            )
            rows_per_round.append((round_manifest.round_number, written))
            LOG.info(
                "loaded round=%d acuerdo=%s rows=%d election_id=%d",
                round_manifest.round_number,
                round_manifest.acuerdo,
                written,
                election_id,
            )

        stamp_scrape_run(conn, success=True, error_message=None)
        conn.commit()
        return ProvisionalLoadResult(
            rounds=rounds,
            rows_per_round=tuple(rows_per_round),
            election_ids=tuple(election_ids),
        )
    except Exception as exc:
        try:
            conn.rollback()
        except Exception:  # pragma: no cover - rollback best-effort
            pass
        try:
            stamp_scrape_run(conn, success=False, error_message=str(exc))
            conn.commit()
        except Exception:  # pragma: no cover - stamp best-effort
            pass
        raise


def main() -> int:
    """CLI entrypoint. Reads DATABASE_URL from env; returns POSIX exit code."""
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s %(message)s")
    dsn = os.environ.get("DATABASE_URL")
    if not dsn:
        LOG.error("DATABASE_URL not set")
        return 2
    import psycopg

    with psycopg.connect(dsn) as conn:
        result = run(conn)
    LOG.info(
        "tse_provisional_2023_done rounds=%d totals=%s",
        len(result.rounds),
        result.rows_per_round,
    )
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
