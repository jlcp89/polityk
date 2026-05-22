"""Extract presidential-poll rows from a CID Gallup PDF.

CID Gallup publishes presidential intent polls as branded PDFs. The
layout varies across cycles but a single poll always carries the same
load-bearing fields:

* the pollster brand ("CID Gallup")
* the field window ("Trabajo de campo: 12 al 16 de marzo de 2027")
* the sample size ("n = 1 200 personas")
* a free-form methodology paragraph (sample design, geographic spread)
* a per-candidate vote-share table with optional margin of error

The parser is intentionally split into two stages so the brittle pdfplumber
extraction stays out of the pure-logic tests:

    extract_text(pdf_path)  ->  raw text
    parse_poll(text, url)   ->  ParsedPoll dataclass    (pure function)

`load_poll(conn, parsed)` then does the DB write — idempotent on
(pollster_id, field_end, source_url) per migration 0004's UNIQUE
constraint, so re-running the same PDF is a no-op.

Candidate resolution
--------------------
We re-use `pipeline.sentiment.entity_resolver.normalize` to NFKD-strip
accents and lowercase before matching against `candidates.full_name`
∪ `candidate_aliases.alias_name`. The lookup is a Python dict built from
a single round trip so the parser stays O(N_candidates_in_poll).

scrape_runs
-----------
The audit table `scrape_runs (source TEXT PK, ...)` is owned by issue
#15. Until that lands, `stamp_scrape_run` checks for the table via
`to_regclass` and no-ops if missing — keeps this parser unblocked.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Any, cast

from pipeline.sentiment.entity_resolver import normalize

logger = logging.getLogger(__name__)

POLLSTER_NAME = "CID Gallup"
SCRAPE_SOURCE = "cid_gallup_pdf"

_SPANISH_MONTHS = {
    "enero": 1,
    "febrero": 2,
    "marzo": 3,
    "abril": 4,
    "mayo": 5,
    "junio": 6,
    "julio": 7,
    "agosto": 8,
    "septiembre": 9,
    "setiembre": 9,
    "octubre": 10,
    "noviembre": 11,
    "diciembre": 12,
}

_FIELD_WINDOW_RE = re.compile(
    r"trabajo\s+de\s+campo\s*[:\-]?\s*"
    r"(?:del\s+)?(\d{1,2})"
    r"(?:\s+de\s+([a-záéíóúñ]+))?"
    r"\s+al\s+(\d{1,2})"
    r"\s+de\s+([a-záéíóúñ]+)"
    r"\s+(?:de\s+|del\s+)?(\d{4})",
    re.IGNORECASE,
)

_SAMPLE_SIZE_RE = re.compile(
    r"(?:tama[nñ]o\s+(?:de\s+)?(?:la\s+)?muestra|muestra(?:\s+nacional)?|n)\s*"
    r"[:=]?\s*(\d{1,2}(?:[.,\s]\d{3})+|\d{3,5}|\d{1,2})"
    r"\s*(?:personas|entrevistas|casos)?",
    re.IGNORECASE,
)

_METHODOLOGY_RE = re.compile(
    r"metodolog[ií]a\s*[:\-]?\s*(.+?)(?=\n\s*\n|\Z|tama[nñ]o\s+de|"
    r"trabajo\s+de\s+campo|intenci[oó]n\s+de\s+voto|candidato)",
    re.IGNORECASE | re.DOTALL,
)

_CANDIDATE_ROW_RE = re.compile(
    r"^\s*"
    r"(?P<name>[A-Za-zÁÉÍÓÚÑáéíóúñ][A-Za-zÁÉÍÓÚÑáéíóúñ\.\-'/ ]+?)"
    r"\s+(?P<share>\d{1,2}[.,]\d)\s*%"
    r"(?:\s*[±+\-]\s*(?P<moe>\d{1,2}[.,]\d)\s*%)?"
    r"\s*$",
    re.MULTILINE,
)

# Lines that look like a candidate row but are actually header/footer noise.
# Matched as exact-equality on the normalised name.
_NOT_A_CANDIDATE_EXACT = {
    "candidato",
    "candidata",
    "intencion de voto",
    "otros",
    "ninguno",
    "blanco",
    "nulo",
    "voto en blanco",
    "voto nulo",
    "total",
    "margen de error",
    "margen",
}

# Substring fragments that, if present in the normalised name, mark the
# row as non-candidate noise ("No sabe / No responde", "NS/NR", etc.).
_NOT_A_CANDIDATE_CONTAINS = (
    "no sabe",
    "no responde",
    "no contesta",
    "ns/nr",
    "no opina",
)


@dataclass(frozen=True)
class CandidateShare:
    name: str
    share: float
    margin_of_error: float | None


@dataclass(frozen=True)
class ParsedPoll:
    pollster_name: str
    field_start: date
    field_end: date
    sample_size: int
    methodology: str
    candidates: tuple[CandidateShare, ...]
    source_url: str


class CIDGallupParseError(ValueError):
    """Raised when a required field can't be extracted from the PDF text."""


def extract_text(pdf_path: Path) -> str:
    """Read every page of `pdf_path` and concatenate the extracted text.

    pdfplumber is an optional extra. Install with `uv sync --extra parsers`.
    """
    try:
        import pdfplumber
    except ImportError as exc:
        raise RuntimeError(
            "pdfplumber not installed; install with: uv sync --extra parsers"
        ) from exc

    pages: list[str] = []
    with pdfplumber.open(str(pdf_path)) as pdf:
        for page in pdf.pages:
            text = page.extract_text() or ""
            pages.append(text)
    return "\n".join(pages)


def parse_poll(text: str, source_url: str) -> ParsedPoll:
    """Pure parser: text → ParsedPoll. Raises CIDGallupParseError on missing fields."""
    if POLLSTER_NAME.lower() not in normalize(text):
        raise CIDGallupParseError(
            f"Text does not mention {POLLSTER_NAME!r}; refusing to parse as CID Gallup."
        )

    field_start, field_end = _extract_field_window(text)
    sample_size = _extract_sample_size(text)
    methodology = _extract_methodology(text)
    candidates = tuple(_extract_candidate_rows(text))
    if not candidates:
        raise CIDGallupParseError("No candidate-share rows found in PDF text.")

    return ParsedPoll(
        pollster_name=POLLSTER_NAME,
        field_start=field_start,
        field_end=field_end,
        sample_size=sample_size,
        methodology=methodology,
        candidates=candidates,
        source_url=source_url,
    )


def _extract_field_window(text: str) -> tuple[date, date]:
    match = _FIELD_WINDOW_RE.search(text)
    if match is None:
        raise CIDGallupParseError("Could not find 'Trabajo de campo' window in text.")
    start_day_s, start_month_s, end_day_s, end_month_s, year_s = match.groups()
    start_day = int(start_day_s)
    end_day = int(end_day_s)
    year = int(year_s)
    end_month = _spanish_month(end_month_s)
    start_month = _spanish_month(start_month_s) if start_month_s else end_month
    try:
        start = date(year, start_month, start_day)
        end = date(year, end_month, end_day)
    except ValueError as exc:
        raise CIDGallupParseError(f"Invalid date in field window: {exc}") from exc
    if end < start:
        raise CIDGallupParseError(
            f"Field-end {end} precedes field-start {start}; layout drift?"
        )
    return start, end


def _spanish_month(token: str) -> int:
    key = normalize(token).strip()
    if key not in _SPANISH_MONTHS:
        raise CIDGallupParseError(f"Unrecognised Spanish month name: {token!r}")
    return _SPANISH_MONTHS[key]


def _extract_sample_size(text: str) -> int:
    match = _SAMPLE_SIZE_RE.search(text)
    if match is None:
        raise CIDGallupParseError("Could not find sample size (n=) in text.")
    raw = match.group(1)
    digits = re.sub(r"[.,\s]", "", raw)
    n = int(digits)
    if n < 100 or n > 50_000:
        raise CIDGallupParseError(
            f"Sample size {n} outside plausible bounds [100, 50000] — layout drift?"
        )
    return n


def _extract_methodology(text: str) -> str:
    match = _METHODOLOGY_RE.search(text)
    if match is None:
        return ""
    body = re.sub(r"\s+", " ", match.group(1)).strip()
    return body[:2000]


def _extract_candidate_rows(text: str) -> list[CandidateShare]:
    seen: set[str] = set()
    out: list[CandidateShare] = []
    for match in _CANDIDATE_ROW_RE.finditer(text):
        name = match.group("name").strip()
        normalized = normalize(name).strip()
        if normalized in _NOT_A_CANDIDATE_EXACT:
            continue
        if any(fragment in normalized for fragment in _NOT_A_CANDIDATE_CONTAINS):
            continue
        if normalized in seen:
            continue
        share = _parse_percent(match.group("share"))
        if share is None or share > 1.0:
            continue
        moe_raw = match.group("moe")
        moe = _parse_percent(moe_raw) if moe_raw else None
        seen.add(normalized)
        out.append(CandidateShare(name=name, share=share, margin_of_error=moe))
    return out


def _parse_percent(raw: str) -> float | None:
    try:
        value = float(raw.replace(",", "."))
    except ValueError:
        return None
    if value < 0:
        return None
    return value / 100.0


def load_poll(
    conn: Any,
    parsed: ParsedPoll,
    *,
    scrape_source: str = SCRAPE_SOURCE,
) -> int | None:
    """Insert `parsed` into polls + poll_responses; idempotent.

    Returns the new `poll_id` on insert, `None` if the row already existed
    (re-running the same PDF). Stamps `scrape_runs` (when the table is
    present — see module docstring).
    """
    try:
        with conn.cursor() as cur:
            pollster_id = _resolve_pollster_id(cur, parsed.pollster_name)
            poll_id = _insert_poll(cur, pollster_id, parsed)
            if poll_id is None:
                conn.commit()
                _stamp_scrape_run(conn, scrape_source, success=True)
                return None
            resolved = _resolve_candidates(cur, parsed.candidates)
            _insert_responses(cur, poll_id, parsed.candidates, resolved)
        conn.commit()
    except Exception as exc:
        conn.rollback()
        _stamp_scrape_run(conn, scrape_source, success=False, error=str(exc))
        raise
    _stamp_scrape_run(conn, scrape_source, success=True)
    return poll_id


def _resolve_pollster_id(cur: Any, name: str) -> int:
    cur.execute("SELECT pollster_id FROM pollsters WHERE name = %s", (name,))
    row = cur.fetchone()
    if row is None:
        raise CIDGallupParseError(
            f"Pollster {name!r} not seeded — migration 0004 should have inserted it."
        )
    return cast(int, row[0])


def _insert_poll(cur: Any, pollster_id: int, parsed: ParsedPoll) -> int | None:
    cur.execute(
        """
        INSERT INTO polls (
            pollster_id, field_start, field_end, sample_size, methodology, source_url
        )
        VALUES (%s, %s, %s, %s, %s, %s)
        ON CONFLICT (pollster_id, field_end, source_url) DO NOTHING
        RETURNING poll_id
        """,
        (
            pollster_id,
            parsed.field_start,
            parsed.field_end,
            parsed.sample_size,
            parsed.methodology,
            parsed.source_url,
        ),
    )
    row = cur.fetchone()
    if row is None:
        return None
    return cast(int, row[0])


def _resolve_candidates(
    cur: Any, candidates: tuple[CandidateShare, ...]
) -> dict[str, int]:
    """Return normalised-name → candidate_id, raising if any candidate is unknown."""
    cur.execute(
        """
        SELECT candidate_id, full_name FROM candidates
        UNION ALL
        SELECT candidate_id, alias_name FROM candidate_aliases
        """
    )
    lookup: dict[str, int] = {}
    for cand_id, surface in cur.fetchall():
        key = normalize(surface).strip()
        if key and key not in lookup:
            lookup[key] = cand_id

    resolved: dict[str, int] = {}
    unresolved: list[str] = []
    for cand in candidates:
        key = normalize(cand.name).strip()
        if key in lookup:
            resolved[key] = lookup[key]
        else:
            unresolved.append(cand.name)
    if unresolved:
        raise CIDGallupParseError(
            "Unresolved candidate names — add to candidate_aliases first: "
            + ", ".join(repr(n) for n in unresolved)
        )
    return resolved


def _insert_responses(
    cur: Any,
    poll_id: int,
    candidates: tuple[CandidateShare, ...],
    resolved: dict[str, int],
) -> None:
    for cand in candidates:
        key = normalize(cand.name).strip()
        candidate_id = resolved[key]
        cur.execute(
            """
            INSERT INTO poll_responses (poll_id, candidate_id, share, margin_of_error)
            VALUES (%s, %s, %s, %s)
            ON CONFLICT (poll_id, candidate_id) DO NOTHING
            """,
            (poll_id, candidate_id, cand.share, cand.margin_of_error),
        )


def _stamp_scrape_run(
    conn: Any,
    source: str,
    *,
    success: bool,
    error: str | None = None,
) -> None:
    """UPSERT a row in `scrape_runs`. No-op if the table doesn't exist yet.

    `scrape_runs` is owned by issue #15. Until that migration lands, this
    parser still works — the audit row simply isn't written.
    """
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT to_regclass('scrape_runs')")
            row = cur.fetchone()
            if row is None or row[0] is None:
                return
            cur.execute(
                """
                INSERT INTO scrape_runs (source, last_run_at, success, error_message)
                VALUES (%s, now(), %s, %s)
                ON CONFLICT (source) DO UPDATE
                  SET last_run_at = EXCLUDED.last_run_at,
                      success = EXCLUDED.success,
                      error_message = EXCLUDED.error_message
                """,
                (source, success, error),
            )
        conn.commit()
    except Exception:
        logger.exception("scrape_runs stamp failed for source=%s", source)
        conn.rollback()
