"""Memoria Electoral 2015 PDF extractor.

The 2015 cycle (6 Sep 2015 first round, 25 Oct 2015 runoff) was the
last cycle to use the **158-seat** Congress — the 2016 reforms (Decreto
26-2016) raised the seat count to 160 starting in 2019. Per-cycle
wiring otherwise mirrors :mod:`pipeline.parsers.memoria_2007` and
:mod:`pipeline.parsers.memoria_2011`: thin wrappers around the shared
pure-logic parsers in :mod:`pipeline.parsers.memoria_2019`.

Published national totals (per TSE and the Memoria Electoral 2015 —
used as the cross-check reference in the smoke test):

* First round (6 Sep 2015), votos válidos:   4,540,772
* Second round (25 Oct 2015), votos válidos: 4,198,978
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

CYCLE: int = 2015
SCRAPE_RUNS_SOURCE: str = "memoria_2015"
EXPECTED_CONGRESS_SEATS: int = 158
PUBLISHED_PRESIDENTIAL_TOTAL_ROUND_1: int = 4_540_772
PUBLISHED_PRESIDENTIAL_TOTAL_ROUND_2: int = 4_198_978

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
    """Parse a 2015 presidential table into typed rows (cycle=2015)."""
    return _shared_parse_presidential_table(
        rows, round_number=round_number, cycle=CYCLE
    )


def parse_congress_table(
    rows: Sequence[RawRow],
    *,
    chamber: Chamber,
) -> tuple[CongressRow, ...]:
    """Parse a 2015 congress table into typed rows (cycle=2015)."""
    return _shared_parse_congress_table(rows, chamber=chamber, cycle=CYCLE)


def parse_municipal_table(rows: Sequence[RawRow]) -> tuple[MunicipalRow, ...]:
    """Parse a 2015 municipal-alcalde table into typed rows (cycle=2015)."""
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
    """Run the full Memoria 2015 extraction, stamping every row cycle=2015."""
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
    """UPSERT a row into ``scrape_runs`` with source='memoria_2015'."""
    return _shared_stamp_scrape_run(
        conn,
        source=SCRAPE_RUNS_SOURCE,
        success=success,
        error_message=error_message,
    )
