"""Stratified sampler for issue #26's labelled headline set.

Reads ``news_articles`` and emits a scaffold CSV
(``fixtures/headlines_labelled.scaffold.csv``) with empty label columns
that the labelling pass (``label_headlines.py``) fills in per the
``LABELING.md`` rubric.

Quotas (per ``LABELING.md``):
  * ≥ 10 headlines per candidate in ``gazetteer_2027.CANDIDATE_NAMES``.
  * ≥ 10 headlines per party    in ``gazetteer_2027.PARTY_NAMES``.
  * ≥ 50 negatives (no gazetteer match).
  * Total = 500 rows (cap; sampler stops early if quotas met).

Idempotency: deterministic ordering by ``article_id`` across the
chosen pool — re-running produces the same CSV given the same DB.
"""

from __future__ import annotations

import argparse
import csv
import logging
import os
import re
import sys
import unicodedata
from collections import defaultdict
from pathlib import Path

logger = logging.getLogger(__name__)

REPO_ROOT = Path(__file__).resolve().parents[3]
SCAFFOLD_PATH = (
    REPO_ROOT
    / "pipeline"
    / "sentiment"
    / "fixtures"
    / "headlines_labelled.scaffold.csv"
)

PER_ENTITY_QUOTA = 15  # over-sample slightly to leave room for AC ≥ 10.
NEGATIVE_QUOTA = 60  # over-sample slightly to leave room for AC ≥ 50.
TOTAL_CAP = 500


def _normalize(text: str) -> str:
    decomposed = unicodedata.normalize("NFKD", text)
    return "".join(c for c in decomposed if not unicodedata.combining(c)).lower()


def _compile_alias_regex(aliases: list[str]) -> re.Pattern[str]:
    parts = sorted({_normalize(a) for a in aliases if a.strip()}, key=len, reverse=True)
    escaped = [re.escape(p) for p in parts]
    return re.compile(r"(?<!\w)(?:" + "|".join(escaped) + r")(?!\w)")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--output",
        type=Path,
        default=SCAFFOLD_PATH,
        help="Scaffold CSV path (default: fixtures/headlines_labelled.scaffold.csv).",
    )
    parser.add_argument(
        "--per-entity-quota",
        type=int,
        default=PER_ENTITY_QUOTA,
        help="Headlines per gazetteer entity (default 15; AC requires ≥ 10).",
    )
    parser.add_argument(
        "--negative-quota",
        type=int,
        default=NEGATIVE_QUOTA,
        help="Negative-case headlines (default 60; AC requires ≥ 50).",
    )
    parser.add_argument(
        "--total",
        type=int,
        default=TOTAL_CAP,
        help="Total row cap (default 500).",
    )
    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(message)s")

    dsn = os.environ.get("DATABASE_URL")
    if not dsn:
        logger.error("DATABASE_URL is required")
        return 2

    # Lazy import so unit tests don't need psycopg installed.
    import psycopg

    from pipeline.sentiment.fixtures.gazetteer_2027 import (
        CANDIDATE_NAMES,
        PARTY_NAMES,
        build_gazetteer,
    )

    # Group aliases per (kind, id) so we can probe each entity independently.
    aliases_per_entity: dict[tuple[str, int], list[str]] = defaultdict(list)
    for entry in build_gazetteer():
        aliases_per_entity[(entry.subject_kind, entry.subject_id)].append(entry.surface)

    # All-entity union regex for negative detection.
    all_aliases: list[str] = [
        a for group in aliases_per_entity.values() for a in group
    ]
    all_regex = _compile_alias_regex(all_aliases)

    with psycopg.connect(dsn) as conn, conn.cursor() as cur:
        cur.execute(
            "SELECT article_id, title FROM news_articles "
            "WHERE title IS NOT NULL AND length(trim(title)) > 0 "
            "ORDER BY article_id"
        )
        rows: list[tuple[int, str]] = list(cur.fetchall())

    logger.info("loaded %d news_articles", len(rows))
    if len(rows) < args.total // 2:
        logger.warning(
            "only %d articles available; scaffold will be shorter than --total=%d",
            len(rows),
            args.total,
        )

    chosen: dict[int, str] = {}  # article_id -> title
    per_entity_counts: dict[tuple[str, int], int] = defaultdict(int)

    # Pass 1: fill per-entity quotas.
    for (kind, sid), aliases in aliases_per_entity.items():
        if (kind, sid) not in {("candidate", c) for c in CANDIDATE_NAMES} | {
            ("party", p) for p in PARTY_NAMES
        }:
            continue
        regex = _compile_alias_regex(aliases)
        for article_id, title in rows:
            if per_entity_counts[(kind, sid)] >= args.per_entity_quota:
                break
            if article_id in chosen:
                continue
            if regex.search(_normalize(title)):
                chosen[article_id] = title
                per_entity_counts[(kind, sid)] += 1

    # Pass 2: fill negatives.
    negatives_taken = 0
    for article_id, title in rows:
        if negatives_taken >= args.negative_quota:
            break
        if article_id in chosen:
            continue
        if not all_regex.search(_normalize(title)):
            chosen[article_id] = title
            negatives_taken += 1

    # Pass 3: pad to total cap with any remaining rows (prefer ones that
    # mention something, to keep the set political-ish).
    for article_id, title in rows:
        if len(chosen) >= args.total:
            break
        if article_id in chosen:
            continue
        chosen[article_id] = title

    if len(chosen) > args.total:
        keep = sorted(chosen.items())[: args.total]
        chosen = dict(keep)

    # Write scaffold.
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open("w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(
            [
                "headline_id",
                "headline_text",
                "candidate_ids",
                "party_ids",
                "labeled_at",
                "labeled_by",
            ]
        )
        for article_id, title in sorted(chosen.items()):
            writer.writerow([article_id, title, "", "", "", ""])

    logger.info(
        "wrote %d rows to %s (per-entity quotas hit: %d/%d entities; negatives: %d)",
        len(chosen),
        args.output,
        sum(1 for v in per_entity_counts.values() if v >= 10),
        len(aliases_per_entity),
        negatives_taken,
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
