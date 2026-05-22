"""Memoria Electoral 2019 PDF extractor with typed table-drift errors.

The 2019 Memoria is the cleanest Memoria-PDF cycle in scope (per the
Operational Commitments backfill ordering). It also supplies the
cross-validation gate for the #19 Excel loader: the row count and the
national totals must match between the two pipelines, or the maintainer
hears about it via a typed exception rather than silently mis-loaded rows.

The module is split into three layers so unit tests can exercise the
parser logic without an actual PDF on disk:

1. **Schemas** declare what each race-type table is expected to look like
   (required columns, integer columns, a human label used in error
   messages).
2. **Pure-logic parsers** take an already-extracted list of row mappings
   plus a schema and emit a tuple of typed result rows. They raise
   ``MissingColumnError`` / ``RowTotalMismatchError`` / ``TableDriftError``
   on every drift mode we know how to detect.
3. **PDF I/O** wraps ``pdfplumber`` (and, where the table grid is too fine
   for pdfplumber's heuristics, ``camelot``) to extract the raw tables.
   Lazy-imported so the unit tests don't pay the cost.

The top-level entry point :func:`extract_from_pdf` chains all three.
A best-effort :func:`stamp_scrape_run` writes the ``memoria_2019`` row to
the ``scrape_runs`` table when it exists.
"""

from __future__ import annotations

import hashlib
import logging
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Any, Literal

if TYPE_CHECKING:  # pragma: no cover - import only used for type hints
    import psycopg

LOG = logging.getLogger(__name__)

CYCLE: int = 2019
SCRAPE_RUNS_SOURCE: str = "memoria_2019"

Chamber = Literal["congress_distrital", "congress_nacional", "parlacen"]
RawRow = Mapping[str, Any]


# ---------------------------------------------------------------------------
# Typed errors
# ---------------------------------------------------------------------------


class MemoriaParserError(Exception):
    """Base class for every typed error this module raises."""


class TableDriftError(MemoriaParserError):
    """Raised when a PDF table's overall layout doesn't match what we expect.

    Use cases: the table has the wrong number of columns, the table is empty,
    the header row is unrecognisable, or no candidate / party / municipality
    table could be located in the PDF at all.
    """


class MissingColumnError(MemoriaParserError):
    """Raised when a *specific* expected column is missing from a table."""

    def __init__(self, label: str, missing: Iterable[str]) -> None:
        self.label = label
        self.missing = tuple(missing)
        super().__init__(
            f"{label}: missing required column(s): {', '.join(self.missing)}"
        )


class RowTotalMismatchError(MemoriaParserError):
    """Raised when a row's summed vote columns don't match its reported total.

    The Memoria publishes per-table totals (e.g. "Votos válidos") that must
    equal the sum of the per-candidate / per-party columns. Drift in either
    direction signals that the PDF's table structure shifted under us.
    """

    def __init__(
        self,
        label: str,
        row_key: str,
        observed: int,
        expected: int,
    ) -> None:
        self.label = label
        self.row_key = row_key
        self.observed = observed
        self.expected = expected
        super().__init__(
            f"{label}: row {row_key!r} summed to {observed} but expected {expected}"
        )


# ---------------------------------------------------------------------------
# Typed output rows
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class PresidentialRow:
    """A single (election, candidate, geography) cell from the Memoria."""

    cycle: int
    round_number: int
    candidate_name: str
    geography_level: str
    geography_code: str
    votes: int


@dataclass(frozen=True)
class CongressRow:
    """A single (election, district, party, chamber) cell from the Memoria."""

    cycle: int
    chamber: Chamber
    district_code: str
    party_name: str
    votes: int
    seats: int


@dataclass(frozen=True)
class MunicipalRow:
    """A single (election, municipality, party) alcalde-vote cell."""

    cycle: int
    municipality_code: str
    party_name: str
    alcalde_votes: int
    alcalde_won: bool


@dataclass(frozen=True)
class ExtractionResult:
    """The output of one Memoria 2019 extraction pass.

    Tuples (not lists) so the result is hashable and idempotent re-extraction
    can be checked with simple equality.
    """

    presidential: tuple[PresidentialRow, ...]
    congress: tuple[CongressRow, ...]
    municipal: tuple[MunicipalRow, ...]
    source_path: Path
    source_sha256: str

    def fingerprint(self) -> str:
        """Stable digest of the extraction; equal across idempotent re-runs."""
        h = hashlib.sha256()
        h.update(self.source_sha256.encode())
        for sequence in (self.presidential, self.congress, self.municipal):
            for row in sequence:
                h.update(repr(row).encode())
        return h.hexdigest()


# ---------------------------------------------------------------------------
# Schemas
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class TableSchema:
    """Declares what a raw extracted table is expected to look like."""

    label: str
    required_columns: tuple[str, ...]
    integer_columns: tuple[str, ...] = ()


PRESIDENTIAL_SCHEMA = TableSchema(
    label="presidential_results",
    required_columns=("geography_level", "geography_code", "candidate", "votes"),
    integer_columns=("votes",),
)

CONGRESS_DISTRITAL_SCHEMA = TableSchema(
    label="congress_distrital_results",
    required_columns=("district_code", "party", "votes", "seats"),
    integer_columns=("votes", "seats"),
)

CONGRESS_NACIONAL_SCHEMA = TableSchema(
    label="congress_nacional_results",
    required_columns=("party", "votes", "seats"),
    integer_columns=("votes", "seats"),
)

PARLACEN_SCHEMA = TableSchema(
    label="parlacen_results",
    required_columns=("party", "votes", "seats"),
    integer_columns=("votes", "seats"),
)

MUNICIPAL_SCHEMA = TableSchema(
    label="municipal_alcalde_results",
    required_columns=("municipality_code", "party", "alcalde_votes", "alcalde_won"),
    integer_columns=("alcalde_votes",),
)


# ---------------------------------------------------------------------------
# Validation helpers
# ---------------------------------------------------------------------------


def _check_required_columns(rows: Sequence[RawRow], schema: TableSchema) -> None:
    if not rows:
        raise TableDriftError(f"{schema.label}: table is empty")
    first = rows[0]
    missing = [c for c in schema.required_columns if c not in first]
    if missing:
        raise MissingColumnError(schema.label, missing)


def _coerce_int(label: str, column: str, row_key: str, value: Any) -> int:
    if isinstance(value, bool):
        # bool is a subclass of int — exclude explicitly because votes/seats
        # are never booleans, and `True + 0 == 1` silently masks layout drift.
        raise TableDriftError(
            f"{label}: row {row_key!r} column {column!r} is bool, expected int"
        )
    if isinstance(value, int):
        return value
    if isinstance(value, str):
        cleaned = value.replace(",", "").replace(" ", "").replace(".", "")
        if cleaned.lstrip("-").isdigit():
            return int(cleaned)
    raise TableDriftError(
        f"{label}: row {row_key!r} column {column!r} not an integer: {value!r}"
    )


def _check_row_total(
    label: str,
    row_key: str,
    component_values: Iterable[int],
    expected_total: int,
) -> None:
    observed = sum(component_values)
    if observed != expected_total:
        raise RowTotalMismatchError(label, row_key, observed, expected_total)


# ---------------------------------------------------------------------------
# Pure-logic parsers
# ---------------------------------------------------------------------------


def parse_presidential_table(
    rows: Sequence[RawRow],
    *,
    round_number: int,
    schema: TableSchema = PRESIDENTIAL_SCHEMA,
    cycle: int = CYCLE,
) -> tuple[PresidentialRow, ...]:
    """Convert raw presidential table rows to typed :class:`PresidentialRow`.

    Each row is expected to carry ``geography_level``, ``geography_code``,
    ``candidate`` and ``votes`` keys. When the table also provides an
    ``expected_total`` key, the parser asserts that the sum of ``votes`` for
    that geography matches and raises :class:`RowTotalMismatchError` if not.
    """
    _check_required_columns(rows, schema)
    if round_number not in (1, 2):
        raise TableDriftError(
            f"{schema.label}: round_number must be 1 or 2, got {round_number}"
        )

    out: list[PresidentialRow] = []
    totals: dict[str, list[int]] = {}
    expected_totals: dict[str, int] = {}
    for row in rows:
        votes = _coerce_int(
            schema.label, "votes", str(row.get("candidate")), row["votes"]
        )
        out.append(
            PresidentialRow(
                cycle=cycle,
                round_number=round_number,
                candidate_name=str(row["candidate"]).strip(),
                geography_level=str(row["geography_level"]).strip(),
                geography_code=str(row["geography_code"]).strip(),
                votes=votes,
            )
        )
        geo_key = f"{row['geography_level']}/{row['geography_code']}"
        totals.setdefault(geo_key, []).append(votes)
        if "expected_total" in row and row["expected_total"] is not None:
            expected_totals[geo_key] = _coerce_int(
                schema.label, "expected_total", geo_key, row["expected_total"]
            )

    for geo_key, expected in expected_totals.items():
        _check_row_total(schema.label, geo_key, totals[geo_key], expected)
    return tuple(out)


def parse_congress_table(
    rows: Sequence[RawRow],
    *,
    chamber: Chamber,
    schema: TableSchema | None = None,
    cycle: int = CYCLE,
) -> tuple[CongressRow, ...]:
    """Convert raw congress rows to typed :class:`CongressRow`.

    ``chamber`` selects the schema; pass ``schema`` to override (test hook).
    For ``congress_nacional`` and ``parlacen`` rows there is no per-district
    column, so the synthetic district code ``'GT'`` (or ``'GT-PARLACEN'``) is
    written instead.
    """
    if schema is None:
        schema = {
            "congress_distrital": CONGRESS_DISTRITAL_SCHEMA,
            "congress_nacional": CONGRESS_NACIONAL_SCHEMA,
            "parlacen": PARLACEN_SCHEMA,
        }[chamber]
    _check_required_columns(rows, schema)

    out: list[CongressRow] = []
    for row in rows:
        party = str(row["party"]).strip()
        votes = _coerce_int(schema.label, "votes", party, row["votes"])
        seats = _coerce_int(schema.label, "seats", party, row["seats"])
        if chamber == "congress_distrital":
            district_code = str(row["district_code"]).strip()
        elif chamber == "parlacen":
            district_code = "GT-PARLACEN"
        else:
            district_code = "GT"
        out.append(
            CongressRow(
                cycle=cycle,
                chamber=chamber,
                district_code=district_code,
                party_name=party,
                votes=votes,
                seats=seats,
            )
        )
    return tuple(out)


def parse_municipal_table(
    rows: Sequence[RawRow],
    *,
    schema: TableSchema = MUNICIPAL_SCHEMA,
    cycle: int = CYCLE,
) -> tuple[MunicipalRow, ...]:
    """Convert raw alcalde rows to typed :class:`MunicipalRow`.

    Per municipality, exactly one row may carry ``alcalde_won == True``;
    that invariant is checked and a :class:`TableDriftError` is raised
    otherwise.
    """
    _check_required_columns(rows, schema)

    by_muni: dict[str, list[MunicipalRow]] = {}
    for row in rows:
        muni = str(row["municipality_code"]).strip()
        party = str(row["party"]).strip()
        votes = _coerce_int(
            schema.label, "alcalde_votes", f"{muni}/{party}", row["alcalde_votes"]
        )
        won_raw = row["alcalde_won"]
        if isinstance(won_raw, bool):
            won = won_raw
        elif isinstance(won_raw, str):
            won = won_raw.strip().lower() in ("true", "t", "yes", "1", "si", "sí")
        else:
            raise TableDriftError(
                f"{schema.label}: row {muni}/{party}: alcalde_won not boolean-like"
            )
        m = MunicipalRow(
            cycle=cycle,
            municipality_code=muni,
            party_name=party,
            alcalde_votes=votes,
            alcalde_won=won,
        )
        by_muni.setdefault(muni, []).append(m)

    for muni, party_rows in by_muni.items():
        winners = [r for r in party_rows if r.alcalde_won]
        if len(winners) > 1:
            raise TableDriftError(
                f"{MUNICIPAL_SCHEMA.label}: municipality {muni!r} has "
                f"{len(winners)} winners, expected at most 1"
            )

    return tuple(r for rows_ in by_muni.values() for r in rows_)


# ---------------------------------------------------------------------------
# Cross-validation against the #19 Excel loader
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class CrossValidation:
    """Result of comparing the Memoria PDF rows against the #19 Excel rows."""

    pdf_row_count: int
    excel_row_count: int
    pdf_national_total_round1: int
    excel_national_total_round1: int
    pdf_national_total_round2: int
    excel_national_total_round2: int

    @property
    def matches(self) -> bool:
        return (
            self.pdf_row_count == self.excel_row_count
            and self.pdf_national_total_round1 == self.excel_national_total_round1
            and self.pdf_national_total_round2 == self.excel_national_total_round2
        )


def cross_validate_presidential(
    pdf_rows: Sequence[PresidentialRow],
    excel_rows: Sequence[PresidentialRow],
) -> CrossValidation:
    """Compare PDF-extracted presidential rows to the #19 Excel-loaded rows.

    Raises :class:`RowTotalMismatchError` if the national totals diverge
    (per the issue acceptance criteria — "Presidential rows match the #19
    loader's row count and national totals (cross-validation gate)").
    """

    def _national_total(rows: Sequence[PresidentialRow], round_n: int) -> int:
        return sum(r.votes for r in rows if r.round_number == round_n)

    pdf_r1 = _national_total(pdf_rows, 1)
    pdf_r2 = _national_total(pdf_rows, 2)
    excel_r1 = _national_total(excel_rows, 1)
    excel_r2 = _national_total(excel_rows, 2)

    result = CrossValidation(
        pdf_row_count=len(pdf_rows),
        excel_row_count=len(excel_rows),
        pdf_national_total_round1=pdf_r1,
        excel_national_total_round1=excel_r1,
        pdf_national_total_round2=pdf_r2,
        excel_national_total_round2=excel_r2,
    )

    if pdf_r1 != excel_r1:
        raise RowTotalMismatchError(
            "presidential_results", "round1_national", pdf_r1, excel_r1
        )
    if pdf_r2 != excel_r2:
        raise RowTotalMismatchError(
            "presidential_results", "round2_national", pdf_r2, excel_r2
        )
    if len(pdf_rows) != len(excel_rows):
        raise TableDriftError(
            f"presidential_results: PDF has {len(pdf_rows)} rows but Excel "
            f"loader has {len(excel_rows)}"
        )
    return result


# ---------------------------------------------------------------------------
# PDF I/O — lazy imports so unit tests don't pay the cost
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class RawTable:
    """An untyped table grabbed from the PDF before schema dispatch."""

    page_number: int
    header: tuple[str, ...]
    body: tuple[tuple[str, ...], ...]


def _sha256_of_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def read_raw_tables_pdfplumber(path: Path) -> tuple[RawTable, ...]:
    """Read every table on every page using ``pdfplumber``.

    Lazy import so test runs that don't touch a real PDF don't pay the
    ``pdfplumber`` import cost.
    """
    import pdfplumber

    out: list[RawTable] = []
    with pdfplumber.open(path) as pdf:
        for page in pdf.pages:
            for table in page.extract_tables() or []:
                if not table or not table[0]:
                    continue
                header = tuple((c or "").strip() for c in table[0])
                body = tuple(
                    tuple((c or "").strip() for c in row) for row in table[1:]
                )
                out.append(
                    RawTable(page_number=page.page_number, header=header, body=body)
                )
    return tuple(out)


def read_raw_tables_camelot(path: Path, *, pages: str = "all") -> tuple[RawTable, ...]:
    """Read tables with ``camelot-py`` (lattice flavour).

    Used as a fallback when pdfplumber's heuristic table-finder misses a
    finely-ruled table. Lazy-imported.
    """
    import camelot

    tables = camelot.read_pdf(  # type: ignore[attr-defined]
        str(path), pages=pages, flavor="lattice"
    )
    out: list[RawTable] = []
    for t in tables:
        df = t.df
        if df.empty:
            continue
        header = tuple(str(c).strip() for c in df.iloc[0].tolist())
        body = tuple(
            tuple(str(c).strip() for c in row) for row in df.iloc[1:].values.tolist()
        )
        out.append(
            RawTable(page_number=int(t.page), header=header, body=body)
        )
    return tuple(out)


# ---------------------------------------------------------------------------
# Dispatcher — header signature → schema → parser
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class _Dispatch:
    schema: TableSchema
    parser: str  # presidential | congress_distrital | congress_nacional | parlacen | municipal
    header_signature: frozenset[str] = field(default_factory=frozenset)


def _table_to_dicts(table: RawTable, key_map: Mapping[str, str]) -> list[dict[str, str]]:
    """Convert a RawTable into a list of dicts keyed by canonical column names.

    ``key_map`` translates header-cell text to canonical column names. Missing
    canonical columns are simply absent from the row — the schema validator
    will raise :class:`MissingColumnError` if any required ones aren't there.
    """
    out: list[dict[str, str]] = []
    indices = {key_map[h]: i for i, h in enumerate(table.header) if h in key_map}
    for body_row in table.body:
        record = {col: body_row[i] for col, i in indices.items() if i < len(body_row)}
        out.append(record)
    return out


# ---------------------------------------------------------------------------
# scrape_runs stamping (best-effort)
# ---------------------------------------------------------------------------


def stamp_scrape_run(
    conn: psycopg.Connection,
    *,
    source: str = SCRAPE_RUNS_SOURCE,
    success: bool,
    error_message: str | None = None,
) -> bool:
    """UPSERT a row into ``scrape_runs`` for this extraction pass.

    Returns ``True`` if a row was written, ``False`` if the table doesn't
    exist (the migration that creates it lands in a later issue). Any other
    DB error propagates — silently swallowing them would mask a real bug.
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
# Top-level orchestration
# ---------------------------------------------------------------------------


def extract_from_pdf(
    path: Path,
    *,
    presidential_round_1: Sequence[RawRow] | None = None,
    presidential_round_2: Sequence[RawRow] | None = None,
    congress_distrital: Sequence[RawRow] | None = None,
    congress_nacional: Sequence[RawRow] | None = None,
    parlacen: Sequence[RawRow] | None = None,
    municipal: Sequence[RawRow] | None = None,
    cycle: int = CYCLE,
) -> ExtractionResult:
    """Run the full Memoria extraction.

    The keyword arguments let callers (and tests) inject already-extracted
    raw rows for each table. When all are ``None``, the function reads
    ``path`` with pdfplumber and tries to discover the tables itself — but
    raises ``TableDriftError`` rather than silently emitting empty results.

    ``cycle`` defaults to 2019 but per-cycle wrappers (e.g.
    :mod:`pipeline.parsers.memoria_2007`) pass their own value so the
    typed rows are stamped with the correct election year.

    Idempotency: calling twice on the same PDF returns equal ``ExtractionResult``
    objects (``==``-equal, and identical ``fingerprint()``).
    """
    if not path.exists():
        raise FileNotFoundError(f"Memoria PDF not found: {path}")

    sha = _sha256_of_file(path)

    any_injected = any(
        rs is not None
        for rs in (
            presidential_round_1,
            presidential_round_2,
            congress_distrital,
            congress_nacional,
            parlacen,
            municipal,
        )
    )
    if not any_injected:
        # Live-PDF path: read every table on every page. The real per-cycle
        # dispatch (header-text -> schema) varies by Memoria; in the absence
        # of a dispatch map we fail loud rather than emit empty results.
        try:
            raw_tables = read_raw_tables_pdfplumber(path)
        except Exception as exc:  # pdfminer / pdfplumber bubble many shapes
            raise TableDriftError(
                f"pdfplumber failed to open {path}: {exc!r}"
            ) from exc
        if not raw_tables:
            raise TableDriftError(
                "No tables extractable from PDF; layout has drifted (or "
                "pdfplumber returned nothing — try the camelot fallback)"
            )
        raise TableDriftError(
            f"PDF parsed but no race-type dispatch supplied "
            f"({len(raw_tables)} raw tables found at {path})"
        )

    presidential: list[PresidentialRow] = []
    if presidential_round_1 is not None:
        presidential.extend(
            parse_presidential_table(
                presidential_round_1, round_number=1, cycle=cycle
            )
        )
    if presidential_round_2 is not None:
        presidential.extend(
            parse_presidential_table(
                presidential_round_2, round_number=2, cycle=cycle
            )
        )

    congress: list[CongressRow] = []
    if congress_distrital is not None:
        congress.extend(
            parse_congress_table(
                congress_distrital, chamber="congress_distrital", cycle=cycle
            )
        )
    if congress_nacional is not None:
        congress.extend(
            parse_congress_table(
                congress_nacional, chamber="congress_nacional", cycle=cycle
            )
        )
    if parlacen is not None:
        congress.extend(
            parse_congress_table(parlacen, chamber="parlacen", cycle=cycle)
        )

    municipal_rows: tuple[MunicipalRow, ...] = ()
    if municipal is not None:
        municipal_rows = parse_municipal_table(municipal, cycle=cycle)

    return ExtractionResult(
        presidential=tuple(presidential),
        congress=tuple(congress),
        municipal=municipal_rows,
        source_path=path,
        source_sha256=sha,
    )
