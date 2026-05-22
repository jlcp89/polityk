"""Run the 2019 TSE presidential loader against `DATABASE_URL`.

Usage:
    DATABASE_URL=postgres://... \\
        uv run python -m pipeline.scripts.load_2019_presidential \\
        [--xlsx PATH] \\
        [--round1-total N] [--round2-total N]

`--round1-total` / `--round2-total` are the *published* TSE national
totals; when supplied the loader asserts the loaded sum matches within
±1 vote. When omitted the assertion is skipped (useful when loading
the synthetic test fixture by hand).

Idempotent: re-running yields zero net changes to `presidential_results`.
"""

from __future__ import annotations

import argparse
import logging
import os
import sys
from pathlib import Path

from pipeline.scrapers.tse import load_2019_excel

logger = logging.getLogger(__name__)


def main(argv: list[str] | None = None) -> int:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s %(message)s")

    parser = argparse.ArgumentParser(description="Load TSE 2019 presidential results.")
    parser.add_argument(
        "--xlsx",
        type=Path,
        default=load_2019_excel.FIXTURE_PATH,
        help=f"path to long-format XLSX (default: {load_2019_excel.FIXTURE_PATH})",
    )
    parser.add_argument("--round1-total", type=int, default=None)
    parser.add_argument("--round2-total", type=int, default=None)
    args = parser.parse_args(argv)

    dsn = os.environ.get("DATABASE_URL")
    if not dsn:
        logger.error("DATABASE_URL not set")
        return 2

    import psycopg

    with psycopg.connect(dsn) as conn:
        result = load_2019_excel.load(
            conn,
            args.xlsx,
            expected_round1_total=args.round1_total,
            expected_round2_total=args.round2_total,
        )

    logger.info(
        "load_2019_presidential_done rows_r1=%d rows_r2=%d total_r1=%d total_r2=%d "
        "candidates_created=%d",
        result.round1_rows,
        result.round2_rows,
        result.round1_total,
        result.round2_total,
        result.candidates_created,
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
