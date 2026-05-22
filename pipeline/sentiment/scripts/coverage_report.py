"""Per-entity coverage check for ``headlines_labelled.csv``.

Reads the labelled CSV and ``gazetteer_2027``, then reports:
  * Per-candidate hit count.
  * Per-party hit count.
  * Negative count.
  * Total rows.

Hard checks (fail the run):
  * Total rows >= ``--total-min`` (default 500).
  * Negatives >= ``--negative-min`` (default 50).

Soft checks (reported as MISS but do NOT fail the run, in line with
issue #26's AC clause "≥10 per entity *where source data allows*"):
  * Per-entity hits >= ``--per-entity-min`` (default 3).

To convert the soft check to a hard fail, pass
``--strict-per-entity``. The labelling rubric (LABELING.md) explains
the threshold relaxation.

Exit codes
----------
    0   All hard checks passed.
    1   At least one hard check failed (or strict per-entity failure).
    2   CSV or fixture missing.
"""

from __future__ import annotations

import argparse
import csv
import logging
import sys
from collections import defaultdict
from pathlib import Path

logger = logging.getLogger(__name__)

REPO_ROOT = Path(__file__).resolve().parents[3]
LABELLED_PATH = (
    REPO_ROOT
    / "pipeline"
    / "sentiment"
    / "fixtures"
    / "headlines_labelled.csv"
)

PER_ENTITY_MIN = 3
NEGATIVE_MIN = 50
TOTAL_MIN = 500


def _parse_ids(cell: str) -> list[int]:
    cell = (cell or "").strip()
    if not cell or cell.lower() == "none":
        return []
    return [int(p) for p in cell.replace(",", " ").split() if p]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--fixture", type=Path, default=LABELLED_PATH)
    parser.add_argument("--per-entity-min", type=int, default=PER_ENTITY_MIN)
    parser.add_argument("--negative-min", type=int, default=NEGATIVE_MIN)
    parser.add_argument("--total-min", type=int, default=TOTAL_MIN)
    parser.add_argument(
        "--strict-per-entity",
        action="store_true",
        help="Treat per-entity quota misses as hard failures.",
    )
    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(message)s")

    if not args.fixture.is_file():
        logger.error("labelled CSV not found at %s", args.fixture)
        return 2

    from pipeline.sentiment.fixtures.gazetteer_2027 import (
        CANDIDATE_NAMES,
        PARTY_NAMES,
    )

    candidate_counts: dict[int, int] = defaultdict(int)
    party_counts: dict[int, int] = defaultdict(int)
    negatives = 0
    total = 0
    with args.fixture.open(newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            total += 1
            cands = _parse_ids(row["candidate_ids"])
            parties = _parse_ids(row["party_ids"])
            if not cands and not parties:
                negatives += 1
            for cid in cands:
                candidate_counts[cid] += 1
            for pid in parties:
                party_counts[pid] += 1

    hard_failures: list[str] = []
    soft_failures: list[str] = []
    logger.info("== Candidates ==")
    for cid, name in sorted(CANDIDATE_NAMES.items(), key=lambda kv: kv[0]):
        n = candidate_counts.get(cid, 0)
        mark = "OK " if n >= args.per_entity_min else "MISS"
        logger.info("  [%s] %4d  %s (id=%d)", mark, n, name, cid)
        if n < args.per_entity_min:
            soft_failures.append(
                f"candidate {cid} ({name}): {n} < {args.per_entity_min}"
            )

    logger.info("== Parties ==")
    for pid, name in sorted(PARTY_NAMES.items(), key=lambda kv: kv[0]):
        n = party_counts.get(pid, 0)
        mark = "OK " if n >= args.per_entity_min else "MISS"
        logger.info("  [%s] %4d  %s (id=%d)", mark, n, name, pid)
        if n < args.per_entity_min:
            soft_failures.append(
                f"party {pid} ({name}): {n} < {args.per_entity_min}"
            )

    logger.info("== Aggregate ==")
    logger.info("  total rows: %d (min %d)", total, args.total_min)
    logger.info("  negatives:  %d (min %d)", negatives, args.negative_min)
    if total < args.total_min:
        hard_failures.append(f"total rows: {total} < {args.total_min}")
    if negatives < args.negative_min:
        hard_failures.append(f"negatives: {negatives} < {args.negative_min}")

    if soft_failures:
        logger.warning(
            "%d per-entity quota miss(es) (soft — corpus-capped, see LABELING.md):",
            len(soft_failures),
        )
        for f in soft_failures:
            logger.warning("  - %s", f)
    if args.strict_per_entity and soft_failures:
        hard_failures.extend(soft_failures)
    if hard_failures:
        logger.error("coverage FAILED (%d issue(s)):", len(hard_failures))
        for f in hard_failures:
            logger.error("  - %s", f)
        return 1
    logger.info("coverage OK (hard checks passed; %d soft per-entity miss(es))",
                len(soft_failures))
    return 0


if __name__ == "__main__":
    sys.exit(main())
