"""Unit tests for the issue #26 labelling toolchain.

Covers:
  * `label_headlines._label_row` rubric application
  * `coverage_report.main` quota gate
  * `gazetteer_2027` integrity (every id has ≥ 1 surface form)
"""

from __future__ import annotations

import csv
from collections import defaultdict
from pathlib import Path

import pytest

from pipeline.sentiment.fixtures.gazetteer_2027 import (
    ARÉVALO,
    CANDIDATE_NAMES,
    GIAMMATTEI,
    PARTY_NAMES,
    TORRES,
    UNE,
    VAMOS,
    build_cycle_candidate_for_party,
    build_gazetteer,
)
from pipeline.sentiment.scripts.coverage_report import main as coverage_main
from pipeline.sentiment.scripts.label_headlines import AliasHit, _label_row, _normalize


@pytest.fixture(scope="module")
def aliases_and_sorted_norms() -> tuple[dict[str, list[AliasHit]], list[str]]:
    aliases_by_norm: dict[str, list[AliasHit]] = defaultdict(list)
    for entry in build_gazetteer():
        norm = _normalize(entry.surface)
        aliases_by_norm[norm].append(
            AliasHit(
                surface_norm=norm,
                subject_kind=entry.subject_kind,
                subject_id=entry.subject_id,
                full_phrase=" " in norm,
            )
        )
    sorted_norms = sorted(aliases_by_norm.keys(), key=len, reverse=True)
    return aliases_by_norm, sorted_norms


def test_gazetteer_integrity() -> None:
    """Every CANDIDATE_NAMES / PARTY_NAMES id appears in at least one surface."""
    gaz = build_gazetteer()
    seen_candidate_ids = {e.subject_id for e in gaz if e.subject_kind == "candidate"}
    seen_party_ids = {e.subject_id for e in gaz if e.subject_kind == "party"}
    missing_cands = set(CANDIDATE_NAMES) - seen_candidate_ids
    missing_parties = set(PARTY_NAMES) - seen_party_ids
    assert not missing_cands, f"candidates without surfaces: {missing_cands}"
    assert not missing_parties, f"parties without surfaces: {missing_parties}"


def test_cycle_map_targets_known_entities() -> None:
    """Every (party, candidate) edge points to slots in *_NAMES."""
    cycle = build_cycle_candidate_for_party()
    for pid, cid in cycle.items():
        assert pid in PARTY_NAMES, f"unknown party {pid} in cycle map"
        assert cid in CANDIDATE_NAMES, f"unknown candidate {cid} in cycle map"


def test_label_full_phrase_match(
    aliases_and_sorted_norms: tuple[dict[str, list[AliasHit]], list[str]],
) -> None:
    aliases, norms = aliases_and_sorted_norms
    cands, parties = _label_row(
        "Bernardo Arévalo anuncia gabinete junto a Karin Herrera",
        aliases,
        norms,
    )
    assert ARÉVALO in cands
    assert parties == []


def test_label_disambiguation_arevalo_alone(
    aliases_and_sorted_norms: tuple[dict[str, list[AliasHit]], list[str]],
) -> None:
    """Surname-only 'Arévalo' resolves (allowed by the rubric)."""
    aliases, norms = aliases_and_sorted_norms
    cands, parties = _label_row(
        "Arévalo viaja a Costa Rica para asistir a toma de posesión",
        aliases,
        norms,
    )
    assert cands == [ARÉVALO]


def test_label_drops_ambiguous_surname(
    aliases_and_sorted_norms: tuple[dict[str, list[AliasHit]], list[str]],
) -> None:
    """Bare 'Torres' with no first name is dropped under rule 3."""
    aliases, norms = aliases_and_sorted_norms
    cands, parties = _label_row(
        "Torres anuncia denuncia ante el Ministerio Público",
        aliases,
        norms,
    )
    assert cands == []


def test_label_keeps_torres_with_first_name(
    aliases_and_sorted_norms: tuple[dict[str, list[AliasHit]], list[str]],
) -> None:
    aliases, norms = aliases_and_sorted_norms
    cands, _ = _label_row(
        "Sandra Torres impugna resultado",
        aliases,
        norms,
    )
    assert TORRES in cands


def test_label_drops_common_word_party_alone(
    aliases_and_sorted_norms: tuple[dict[str, list[AliasHit]], list[str]],
) -> None:
    """'Vamos al grano' should NOT label Vamos under rule 2 anti-rule."""
    aliases, norms = aliases_and_sorted_norms
    cands, parties = _label_row(
        "Vamos al grano: una columna sobre transporte",
        aliases,
        norms,
    )
    assert VAMOS not in parties


def test_label_keeps_party_with_qualifier(
    aliases_and_sorted_norms: tuple[dict[str, list[AliasHit]], list[str]],
) -> None:
    aliases, norms = aliases_and_sorted_norms
    cands, parties = _label_row(
        "Bancada del partido Vamos propone reforma",
        aliases,
        norms,
    )
    assert VAMOS in parties


def test_label_multi_entity(
    aliases_and_sorted_norms: tuple[dict[str, list[AliasHit]], list[str]],
) -> None:
    aliases, norms = aliases_and_sorted_norms
    cands, parties = _label_row(
        "Bernardo Arévalo denuncia a Alejandro Giammattei por corrupción",
        aliases,
        norms,
    )
    assert ARÉVALO in cands and GIAMMATTEI in cands
    assert parties == []


def test_label_party_abbrev_acronym_always_ok(
    aliases_and_sorted_norms: tuple[dict[str, list[AliasHit]], list[str]],
) -> None:
    """UNE is unambiguous when it appears as an acronym."""
    aliases, norms = aliases_and_sorted_norms
    cands, parties = _label_row(
        "La UNE convoca a su asamblea departamental",
        aliases,
        norms,
    )
    assert UNE in parties


def test_label_unrelated_headline_returns_empty(
    aliases_and_sorted_norms: tuple[dict[str, list[AliasHit]], list[str]],
) -> None:
    aliases, norms = aliases_and_sorted_norms
    cands, parties = _label_row(
        "Pronóstico del clima: lluvias en el Pacífico durante el fin de semana",
        aliases,
        norms,
    )
    assert cands == [] and parties == []


def test_coverage_report_passes(tmp_path: Path) -> None:
    """A synthetic CSV satisfying the quotas exits zero."""
    fixture = tmp_path / "labelled.csv"
    rows: list[list[str]] = []
    # 3 hits per candidate, 3 per party (matches the relaxed per-entity-min).
    headline_id = 1
    for cid in CANDIDATE_NAMES:
        for _ in range(3):
            rows.append([str(headline_id), f"about {cid}", str(cid), "", "2026-05-22", "test"])
            headline_id += 1
    for pid in PARTY_NAMES:
        for _ in range(3):
            rows.append([str(headline_id), f"about p{pid}", "", str(pid), "2026-05-22", "test"])
            headline_id += 1
    # 50 negatives.
    for _ in range(50):
        rows.append([str(headline_id), "weather", "", "", "2026-05-22", "test"])
        headline_id += 1
    # pad to ≥ 500.
    while len(rows) < 500:
        rows.append([str(headline_id), "filler", "", "", "2026-05-22", "test"])
        headline_id += 1
    header = [
        "headline_id",
        "headline_text",
        "candidate_ids",
        "party_ids",
        "labeled_at",
        "labeled_by",
    ]
    with fixture.open("w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(header)
        writer.writerows(rows)
    rc = coverage_main(["--fixture", str(fixture)])
    assert rc == 0, "coverage gate should pass when quotas are met"


def test_coverage_report_fails_on_low_negatives(tmp_path: Path) -> None:
    fixture = tmp_path / "labelled.csv"
    header = [
        "headline_id",
        "headline_text",
        "candidate_ids",
        "party_ids",
        "labeled_at",
        "labeled_by",
    ]
    with fixture.open("w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(header)
        # Hit per-entity quotas but only 3 negatives.
        hid = 1
        for cid in CANDIDATE_NAMES:
            for _ in range(3):
                writer.writerow([hid, "x", cid, "", "2026-05-22", "t"])
                hid += 1
        for pid in PARTY_NAMES:
            for _ in range(3):
                writer.writerow([hid, "x", "", pid, "2026-05-22", "t"])
                hid += 1
        for _ in range(3):
            writer.writerow([hid, "weather", "", "", "2026-05-22", "t"])
            hid += 1
        while hid <= 500:
            writer.writerow([hid, "x", "101", "", "2026-05-22", "t"])
            hid += 1
    rc = coverage_main(["--fixture", str(fixture)])
    assert rc == 1, "coverage gate should fail on negatives < 50"
