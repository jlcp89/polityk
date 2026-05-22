"""Apply the GT geographies seed against `DATABASE_URL`.

Usage:
    DATABASE_URL=postgres://... uv run python -m pipeline.scripts.seed_geographies

Idempotent; safe to run on every CI bootstrap and developer fresh-clone.
"""

from __future__ import annotations

import logging
import os
import sys

from pipeline.seed import geographies

logger = logging.getLogger(__name__)


def main() -> int:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s %(message)s")

    dsn = os.environ.get("DATABASE_URL")
    if not dsn:
        logger.error("DATABASE_URL not set")
        return 2

    # Import psycopg lazily so unit tests can exercise pure-logic paths
    # without requiring the binary wheel.
    import psycopg

    with psycopg.connect(dsn) as conn:
        applied = geographies.seed(conn)
        total = geographies.count(conn)

    logger.info("geographies_seed_done applied=%d total=%d", applied, total)
    if total != geographies.EXPECTED_ROW_COUNT:
        logger.error(
            "geographies row count drift: expected=%d got=%d",
            geographies.EXPECTED_ROW_COUNT,
            total,
        )
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
