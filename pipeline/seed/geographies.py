"""Idempotent loader for the GT `geographies` dimension.

Reads `pipeline/seed/data/geographies_gt.csv` (387 rows: 2 country + 22
department + 23 district + 340 municipality) and UPSERTs into
`geographies` keyed by `(level, code)`. Parent links are resolved in a
second pass so each row's parent is guaranteed to exist when we set it.

Per ADR-016, one of the country rows is the synthetic `GT-PARLACEN`
geography that PARLACEN result rows reference.
"""

from __future__ import annotations

import csv
import logging
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path
from typing import Any, cast

logger = logging.getLogger(__name__)

DATA_FILE = Path(__file__).parent / "data" / "geographies_gt.csv"

# Acceptance criterion: 22 + 340 + 23 + 1 + 1 = 387 rows total.
EXPECTED_ROW_COUNT = 387


@dataclass(frozen=True)
class GeographyRow:
    level: str
    code: str
    name: str
    parent_code: str | None
    parent_level: str | None


def load_rows(path: Path = DATA_FILE) -> list[GeographyRow]:
    """Parse the seed CSV; fail loudly on row-count drift."""
    rows: list[GeographyRow] = []
    with path.open(newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for raw in reader:
            rows.append(
                GeographyRow(
                    level=raw["level"],
                    code=raw["code"],
                    name=raw["name"],
                    parent_code=raw["parent_code"] or None,
                    parent_level=raw["parent_level"] or None,
                )
            )
    if len(rows) != EXPECTED_ROW_COUNT:
        raise ValueError(
            f"geographies seed: expected {EXPECTED_ROW_COUNT} rows, got {len(rows)} "
            f"from {path}"
        )
    return rows


def seed(conn: Any, rows: Iterable[GeographyRow] | None = None) -> int:
    """UPSERT all rows; resolve parents in a second pass. Returns total rows seen.

    `conn` is a psycopg-style connection (a `psycopg.Connection` in practice).
    Idempotent: re-running yields zero net changes.
    """
    materialised = list(rows) if rows is not None else load_rows()

    with conn.cursor() as cur:
        for row in materialised:
            cur.execute(
                """
                INSERT INTO geographies (level, code, name)
                VALUES (%s, %s, %s)
                ON CONFLICT (level, code) DO UPDATE
                  SET name = EXCLUDED.name
                """,
                (row.level, row.code, row.name),
            )

        for row in materialised:
            if row.parent_code is None or row.parent_level is None:
                continue
            cur.execute(
                """
                UPDATE geographies AS child
                SET parent_id = parent.geography_id
                FROM geographies AS parent
                WHERE child.level = %s
                  AND child.code = %s
                  AND parent.level = %s
                  AND parent.code = %s
                """,
                (row.level, row.code, row.parent_level, row.parent_code),
            )
    conn.commit()
    return len(materialised)


def count(conn: Any) -> int:
    """Current `geographies` row count — used by tests and the health check."""
    with conn.cursor() as cur:
        cur.execute("SELECT COUNT(*) FROM geographies")
        result = cur.fetchone()
    if result is None:
        return 0
    return cast(int, result[0])
