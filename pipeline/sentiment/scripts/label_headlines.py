"""Apply the LABELING.md rubric to the scaffold CSV.

Input:  ``fixtures/headlines_labelled.scaffold.csv``
Output: ``fixtures/headlines_labelled.csv``

Labelling logic (NOT a call to the entity resolver — that would defeat the
validation purpose):
  1. Normalize the headline (NFKD + lowercase).
  2. Find every gazetteer alias as a word-bounded substring. Longest-first
     so "Bernardo Arévalo" beats "Arévalo" when both appear.
  3. Apply rubric ambiguity rules:
     - Discard surname-only matches when the surname is a registered
       AMBIGUOUS_SURNAME (no first-name or role context resolves it).
     - Discard candidate matches when the headline is one of the
       NON_POLITICAL_HINTS contexts (sports, weather, culture without a
       political verb).
  4. Emit ascending-sorted, space-separated IDs into ``candidate_ids``
     and ``party_ids``. Empty cells encode "no in-system mention."

Idempotent. The labeller identity is stamped per row.
"""

from __future__ import annotations

import argparse
import csv
import logging
import re
import sys
import unicodedata
from collections import defaultdict
from dataclasses import dataclass
from datetime import date
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
LABELLED_PATH = (
    REPO_ROOT
    / "pipeline"
    / "sentiment"
    / "fixtures"
    / "headlines_labelled.csv"
)

DEFAULT_LABELED_BY = "claude-opus-4-7+gazetteer-anchored/jlcp89"

# Surnames that are too ambiguous to label without first-name / role context.
# The rubric (rule 3) says: ambiguous → do not label. These are
# headline-normalized (lowercased, no accents).
AMBIGUOUS_SURNAME_NORMS: set[str] = {
    "torres",   # could be Sandra or any number of others
    "molina",   # only label if "Molina Barreto"
    "rivera",   # only label if "Amílcar Rivera" or "Neto Bran"
    "pineda",   # only label if "Carlos Pineda"
    "conde",    # only label if "Manuel Conde"
    "estrada",  # only label if "Mario Estrada"
    "herrera",  # only label if "Karin Herrera"
    "aldana",   # only label if "Thelma Aldana" or "exfiscal Aldana"
}

# Party aliases that collide with common Spanish words. Single-token
# matches are dropped unless a multi-token alias of the same party
# (e.g. "partido Vamos", "Movimiento Semilla") is also present in the
# headline. The rubric (rule 2 anti-rule) says: caucus / bench / party
# qualifier required when the bare token is a common word.
AMBIGUOUS_PARTY_NORMS: set[str] = {
    "vamos",   # 1st-person plural verb / let's
    "valor",   # noun (value, courage)
    "cabal",   # adjective (complete, exact)
    "todos",   # pronoun (everyone)
    "vos",     # pronoun (you, in voseo)
    "bien",    # adverb (well)
    "lider",   # noun (leader) — normalized form of "líder"
    "podemos", # 1st-person plural verb (we can)
    "creo",    # 1st-person verb (I believe)
    "gana",    # 3rd-person verb (he/she wins)
    "viva",    # subjunctive (long live)
}

# Surrounding words that hint a candidate mention is non-political under
# rule 1.4. Conservatively narrow — sports + culture verbs only. Most
# Guatemalan political news uses verbs like "anuncia", "propone", "rechaza".
NON_POLITICAL_PATTERN = re.compile(
    r"\b(?:gol|partido de futbol|estren[oa]|pelicula|musical|"
    r"cantante|cumpleano|gana[r]? la copa|maraton)\b"
)


@dataclass(frozen=True)
class AliasHit:
    surface_norm: str
    subject_kind: str
    subject_id: int
    full_phrase: bool  # True if alias contains a space (multi-token)


def _normalize(text: str) -> str:
    decomposed = unicodedata.normalize("NFKD", text)
    return "".join(c for c in decomposed if not unicodedata.combining(c)).lower()


def _label_row(
    headline: str,
    aliases_by_norm: dict[str, list[AliasHit]],
    sorted_norms: list[str],
) -> tuple[list[int], list[int]]:
    norm_text = _normalize(headline)

    # Track which character positions we've already consumed by a longer
    # alias, so "Bernardo Arévalo" suppresses a second match on "Arévalo".
    covered = [False] * len(norm_text)
    mentions: list[AliasHit] = []
    for alias_norm in sorted_norms:
        if not alias_norm:
            continue
        start = 0
        while True:
            idx = norm_text.find(alias_norm, start)
            if idx < 0:
                break
            end = idx + len(alias_norm)
            # Word boundary check: previous/next char must not be alphanumeric.
            left = norm_text[idx - 1] if idx > 0 else " "
            right = norm_text[end] if end < len(norm_text) else " "
            if (not left.isalnum() or left == "_") and (
                not right.isalnum() or right == "_"
            ):
                if not any(covered[idx:end]):
                    for hit in aliases_by_norm[alias_norm]:
                        mentions.append(hit)
                    for k in range(idx, end):
                        covered[k] = True
            start = idx + 1

    # Apply rubric rule 3 (ambiguous surnames) + rule 2 anti-rule
    # (party tokens that collide with common Spanish words).
    filtered: list[AliasHit] = []
    for m in mentions:
        if not m.full_phrase:
            ambiguous = (
                m.surface_norm in AMBIGUOUS_SURNAME_NORMS
                if m.subject_kind == "candidate"
                else m.surface_norm in AMBIGUOUS_PARTY_NORMS
            )
            if ambiguous:
                # Keep only if a multi-token alias of the same entity was
                # also matched (e.g. "partido Vamos", "Movimiento Semilla").
                multi_present = any(
                    other.subject_id == m.subject_id
                    and other.subject_kind == m.subject_kind
                    and other.full_phrase
                    for other in mentions
                )
                if not multi_present:
                    continue
        filtered.append(m)

    # Apply rubric rule 1.4 (non-political context).
    if filtered and NON_POLITICAL_PATTERN.search(norm_text):
        filtered = [m for m in filtered if m.subject_kind != "candidate"]

    candidate_ids = sorted({m.subject_id for m in filtered if m.subject_kind == "candidate"})
    party_ids = sorted({m.subject_id for m in filtered if m.subject_kind == "party"})
    return candidate_ids, party_ids


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, default=SCAFFOLD_PATH)
    parser.add_argument("--output", type=Path, default=LABELLED_PATH)
    parser.add_argument("--labeled-by", default=DEFAULT_LABELED_BY)
    parser.add_argument(
        "--labeled-at",
        default=date.today().isoformat(),
        help="ISO-8601 date stamp; defaults to today.",
    )
    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(message)s")

    from pipeline.sentiment.fixtures.gazetteer_2027 import build_gazetteer

    aliases_by_norm: dict[str, list[AliasHit]] = defaultdict(list)
    for entry in build_gazetteer():
        norm = _normalize(entry.surface)
        if not norm.strip():
            continue
        aliases_by_norm[norm].append(
            AliasHit(
                surface_norm=norm,
                subject_kind=entry.subject_kind,
                subject_id=entry.subject_id,
                full_phrase=" " in norm,
            )
        )
    sorted_norms = sorted(aliases_by_norm.keys(), key=len, reverse=True)

    if not args.input.is_file():
        logger.error("scaffold not found at %s", args.input)
        return 2

    rows_out: list[list[str]] = []
    with args.input.open(newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            headline = row["headline_text"]
            cands, parties = _label_row(headline, aliases_by_norm, sorted_norms)
            rows_out.append(
                [
                    row["headline_id"],
                    headline,
                    " ".join(str(i) for i in cands),
                    " ".join(str(i) for i in parties),
                    args.labeled_at,
                    args.labeled_by,
                ]
            )

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
        writer.writerows(rows_out)

    n_with_labels = sum(1 for r in rows_out if r[2] or r[3])
    n_negatives = len(rows_out) - n_with_labels
    logger.info(
        "wrote %d rows to %s (%d labelled, %d negatives)",
        len(rows_out),
        args.output,
        n_with_labels,
        n_negatives,
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
