"""Memoria Electoral 2011 PDF extractor.

The 2011 cycle (11 Sep 2011 first round, 6 Nov 2011 runoff) used the
**158-seat** Congress (127 distrital + 31 nacional). Like
:mod:`pipeline.parsers.memoria_2007`, this module is a thin per-cycle
wrapper around the shared pure-logic parsers in
:mod:`pipeline.parsers.memoria_2019`; only the cycle constant, the
scrape-runs source label and the published-totals reference constants
differ.

Published national totals (per TSE and the Memoria Electoral 2011 —
used as the cross-check reference in the smoke test):

* First round (11 Sep 2011), votos válidos:  4,400,432
* Second round (6 Nov 2011), votos válidos:  4,282,367
"""

from __future__ import annotations

from collections.abc import Sequence
from pathlib import Path
from typing import TYPE_CHECKING

from pipeline.parsers.memoria_2019 import (
    CongressRow,
    ExtractionResult,
    MemoriaParserError,
    MissingColumnError,
    MunicipalRow,
    PresidentialRow,
    RawRow,
    RowTotalMismatchError,
    TableDriftError,
)
from pipeline.parsers.memoria_2019 import (
    extract_from_pdf as _shared_extract_from_pdf,
)
from pipeline.parsers.memoria_2019 import (
    parse_congress_table as _shared_parse_congress_table,
)
from pipeline.parsers.memoria_2019 import (
    parse_municipal_table as _shared_parse_municipal_table,
)
from pipeline.parsers.memoria_2019 import (
    parse_presidential_table as _shared_parse_presidential_table,
)
from pipeline.parsers.memoria_2019 import (
    stamp_scrape_run as _shared_stamp_scrape_run,
)

if TYPE_CHECKING:  # pragma: no cover - import only used for type hints
    import psycopg

    from pipeline.parsers.memoria_2019 import Chamber

CYCLE: int = 2011
SCRAPE_RUNS_SOURCE: str = "memoria_2011"
EXPECTED_CONGRESS_SEATS: int = 158
PUBLISHED_PRESIDENTIAL_TOTAL_ROUND_1: int = 4_400_432
PUBLISHED_PRESIDENTIAL_TOTAL_ROUND_2: int = 4_282_367

__all__ = [
    "CYCLE",
    "EXPECTED_CONGRESS_SEATS",
    "PUBLISHED_PRESIDENTIAL_TOTAL_ROUND_1",
    "PUBLISHED_PRESIDENTIAL_TOTAL_ROUND_2",
    "SCRAPE_RUNS_SOURCE",
    "CongressRow",
    "ExtractionResult",
    "MemoriaParserError",
    "MissingColumnError",
    "MunicipalRow",
    "PresidentialRow",
    "RowTotalMismatchError",
    "TableDriftError",
    "extract_from_pdf",
    "parse_congress_table",
    "parse_municipal_table",
    "parse_presidential_table",
    "stamp_scrape_run",
]


def parse_presidential_table(
    rows: Sequence[RawRow],
    *,
    round_number: int,
) -> tuple[PresidentialRow, ...]:
    """Parse a 2011 presidential table into typed rows (cycle=2011)."""
    return _shared_parse_presidential_table(
        rows, round_number=round_number, cycle=CYCLE
    )


def parse_congress_table(
    rows: Sequence[RawRow],
    *,
    chamber: Chamber,
) -> tuple[CongressRow, ...]:
    """Parse a 2011 congress table into typed rows (cycle=2011)."""
    return _shared_parse_congress_table(rows, chamber=chamber, cycle=CYCLE)


def parse_municipal_table(rows: Sequence[RawRow]) -> tuple[MunicipalRow, ...]:
    """Parse a 2011 municipal-alcalde table into typed rows (cycle=2011)."""
    return _shared_parse_municipal_table(rows, cycle=CYCLE)


def extract_from_pdf(
    path: Path,
    *,
    presidential_round_1: Sequence[RawRow] | None = None,
    presidential_round_2: Sequence[RawRow] | None = None,
    congress_distrital: Sequence[RawRow] | None = None,
    congress_nacional: Sequence[RawRow] | None = None,
    parlacen: Sequence[RawRow] | None = None,
    municipal: Sequence[RawRow] | None = None,
) -> ExtractionResult:
    """Run the full Memoria 2011 extraction, stamping every row cycle=2011."""
    return _shared_extract_from_pdf(
        path,
        presidential_round_1=presidential_round_1,
        presidential_round_2=presidential_round_2,
        congress_distrital=congress_distrital,
        congress_nacional=congress_nacional,
        parlacen=parlacen,
        municipal=municipal,
        cycle=CYCLE,
    )


def stamp_scrape_run(
    conn: psycopg.Connection,
    *,
    success: bool,
    error_message: str | None = None,
) -> bool:
    """UPSERT a row into ``scrape_runs`` with source='memoria_2011'."""
    return _shared_stamp_scrape_run(
        conn,
        source=SCRAPE_RUNS_SOURCE,
        success=success,
        error_message=error_message,
    )
