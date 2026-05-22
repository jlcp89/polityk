"""Validate the entity resolver against a labelled headline CSV.

CSV schema (per issue #26):
    headline_id, headline_text, candidate_ids, party_ids, labeled_at, labeled_by

`candidate_ids` and `party_ids` are space-separated integer lists; empty
cells encode "no in-system mention." A label of "none" is recorded as an
empty list — that headline contributes to the false-positive denominator
but not the true-positive numerator.

Metrics
-------
Computed per `(subject_kind, subject_id)` tuple across the full corpus.

    precision = TP / (TP + FP)
    recall    = TP / (TP + FN)
    F1        = 2 * P * R / (P + R)

The gate is `F1 ≥ 0.95` (ADR-011 / US36). Below that, the resolver still
ships but issue #38 zero-weights sentiment as a *modelled* input.

Exit codes
----------
    0   F1 ≥ threshold
    1   F1 < threshold
    2   CSV missing or unreadable
"""

from __future__ import annotations

import argparse
import csv
import logging
import sys
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path

from pipeline.sentiment.entity_resolver import EntityResolver, Mention

logger = logging.getLogger(__name__)

DEFAULT_CSV = Path(__file__).parent / "fixtures" / "headlines_labelled.csv"
SMOKE_CSV = Path(__file__).parent / "fixtures" / "headlines_smoke.csv"
DEFAULT_F1_THRESHOLD = 0.95


@dataclass(frozen=True)
class LabelledHeadline:
    headline_id: str
    text: str
    candidate_ids: frozenset[int]
    party_ids: frozenset[int]


@dataclass(frozen=True)
class ValidationReport:
    n_headlines: int
    true_positives: int
    false_positives: int
    false_negatives: int
    precision: float
    recall: float
    f1: float

    def passed(self, threshold: float = DEFAULT_F1_THRESHOLD) -> bool:
        return self.f1 >= threshold


def _parse_ids(cell: str) -> frozenset[int]:
    cell = (cell or "").strip()
    if not cell or cell.lower() == "none":
        return frozenset()
    parts = cell.replace(",", " ").split()
    return frozenset(int(p) for p in parts if p)


def load_csv(path: Path) -> list[LabelledHeadline]:
    if not path.is_file():
        raise FileNotFoundError(f"labelled headline CSV not found at {path}")
    out: list[LabelledHeadline] = []
    with path.open(newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        required = {"headline_id", "headline_text", "candidate_ids", "party_ids"}
        if reader.fieldnames is None or not required.issubset(reader.fieldnames):
            raise ValueError(
                f"CSV header missing required columns; got {reader.fieldnames!r}, "
                f"need at least {sorted(required)}"
            )
        for row in reader:
            out.append(
                LabelledHeadline(
                    headline_id=row["headline_id"].strip(),
                    text=row["headline_text"],
                    candidate_ids=_parse_ids(row["candidate_ids"]),
                    party_ids=_parse_ids(row["party_ids"]),
                )
            )
    return out


def _mentions_to_sets(mentions: Iterable[Mention]) -> tuple[set[int], set[int]]:
    cand: set[int] = set()
    party: set[int] = set()
    for m in mentions:
        if m.subject_kind == "candidate":
            cand.add(m.subject_id)
        elif m.subject_kind == "party":
            party.add(m.subject_id)
    return cand, party


def score(
    resolver: EntityResolver,
    headlines: Iterable[LabelledHeadline],
) -> ValidationReport:
    tp = fp = fn = 0
    n = 0
    for h in headlines:
        n += 1
        predicted_cand, predicted_party = _mentions_to_sets(resolver.resolve(h.text))
        tp += len(predicted_cand & h.candidate_ids) + len(predicted_party & h.party_ids)
        fp += len(predicted_cand - h.candidate_ids) + len(predicted_party - h.party_ids)
        fn += len(h.candidate_ids - predicted_cand) + len(h.party_ids - predicted_party)
    precision = tp / (tp + fp) if (tp + fp) > 0 else 1.0
    recall = tp / (tp + fn) if (tp + fn) > 0 else 1.0
    f1 = (2 * precision * recall / (precision + recall)) if (precision + recall) > 0 else 0.0
    return ValidationReport(
        n_headlines=n,
        true_positives=tp,
        false_positives=fp,
        false_negatives=fn,
        precision=precision,
        recall=recall,
        f1=f1,
    )


def _build_default_resolver(module_name: str | None = None) -> EntityResolver:
    """Build the resolver used when the harness runs standalone.

    Default imports the smoke-test fixture (`gazetteer_2023`) so the
    script works out-of-the-box against `headlines_smoke.csv`. Pass
    `module_name="pipeline.sentiment.fixtures.gazetteer_2027"` to validate
    against the issue #26 launch gate fixture. Production callers should
    construct their own `EntityResolver.from_db_rows(...)`.

    The fixture module must expose either
    `build_gazetteer() + build_cycle_candidate_for_party()` (gazetteer_2027)
    or the legacy `build_fixture_gazetteer() +
    build_fixture_cycle_candidate_for_party()` (gazetteer_2023).
    """
    import importlib

    target = module_name or "pipeline.sentiment.fixtures.gazetteer_2023"
    mod = importlib.import_module(target)
    if hasattr(mod, "build_gazetteer"):
        gaz = mod.build_gazetteer()
        cycle = mod.build_cycle_candidate_for_party()
    else:
        gaz = mod.build_fixture_gazetteer()
        cycle = mod.build_fixture_cycle_candidate_for_party()
    return EntityResolver(gaz, cycle)


def _select_csv_path(csv_arg: str | None) -> Path | None:
    if csv_arg:
        return Path(csv_arg)
    if DEFAULT_CSV.is_file():
        return DEFAULT_CSV
    if SMOKE_CSV.is_file():
        logger.warning(
            "Issue #26 labelled set not present at %s; falling back to %s "
            "(smoke fixture, not the launch gate).",
            DEFAULT_CSV,
            SMOKE_CSV,
        )
        return SMOKE_CSV
    return None


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--csv", help="Path to labelled headline CSV.", default=None)
    parser.add_argument(
        "--gazetteer-module",
        default=None,
        help=(
            "Python module path of the gazetteer fixture to use. Defaults to "
            "gazetteer_2023 (smoke). Pass "
            "pipeline.sentiment.fixtures.gazetteer_2027 for the #26 launch gate."
        ),
    )
    parser.add_argument(
        "--threshold",
        type=float,
        default=DEFAULT_F1_THRESHOLD,
        help="F1 threshold; non-zero exit when result falls below.",
    )
    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    path = _select_csv_path(args.csv)
    if path is None:
        logger.error(
            "No labelled headline CSV available (looked in %s and %s).",
            DEFAULT_CSV,
            SMOKE_CSV,
        )
        return 2
    try:
        headlines = load_csv(path)
    except (FileNotFoundError, ValueError) as exc:
        logger.error("Failed to load CSV: %s", exc)
        return 2

    resolver = _build_default_resolver(args.gazetteer_module)
    report = score(resolver, headlines)
    logger.info(
        "validate_entity_resolver: n=%d tp=%d fp=%d fn=%d "
        "precision=%.3f recall=%.3f f1=%.3f (gate=%.2f)",
        report.n_headlines,
        report.true_positives,
        report.false_positives,
        report.false_negatives,
        report.precision,
        report.recall,
        report.f1,
        args.threshold,
    )
    return 0 if report.passed(args.threshold) else 1


if __name__ == "__main__":
    sys.exit(main())
