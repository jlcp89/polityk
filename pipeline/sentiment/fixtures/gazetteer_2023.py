"""Tiny gazetteer + headline fixture for entity-resolver tests.

This is *not* the validation set from issue #26 — that ships ≥500 hand-
labelled headlines under `headlines_labelled.csv` once a human curates them.
This module holds a much smaller, hand-built fixture for unit tests and the
validation-harness smoke test. Subject IDs are fictitious (1..99) and do
*not* correspond to any production `candidates.candidate_id` /
`parties.party_id`.
"""

from __future__ import annotations

from pipeline.sentiment.entity_resolver import GazetteerEntry

# Candidates (fictitious IDs; only used by tests + the harness smoke test).
ARÉVALO = 11
TORRES = 12
GIAMMATTEI = 13
ZURY_RÍOS = 14
MULET = 15

# Parties.
SEMILLA = 21
UNE = 22
VAMOS = 23
VALOR = 24
CABAL = 25


def build_fixture_gazetteer() -> list[GazetteerEntry]:
    """Canonical + alias surfaces covering the headline fixture below."""
    return [
        # Bernardo Arévalo (Semilla).
        GazetteerEntry("Bernardo Arévalo", "candidate", ARÉVALO),
        GazetteerEntry("Arévalo", "candidate", ARÉVALO),
        GazetteerEntry("Bernardo Arévalo de León", "candidate", ARÉVALO),
        # Sandra Torres (UNE).
        GazetteerEntry("Sandra Torres", "candidate", TORRES),
        GazetteerEntry("Torres", "candidate", TORRES),
        GazetteerEntry("Sandra Julieta Torres", "candidate", TORRES),
        # Alejandro Giammattei (Vamos).
        GazetteerEntry("Alejandro Giammattei", "candidate", GIAMMATTEI),
        GazetteerEntry("Giammattei", "candidate", GIAMMATTEI),
        # Zury Ríos (Valor).
        GazetteerEntry("Zury Ríos", "candidate", ZURY_RÍOS),
        GazetteerEntry("Zury Mayté Ríos Sosa", "candidate", ZURY_RÍOS),
        # Manuel Conde Orellana → fictitious; not used in fixture headlines.
        # Edmond Mulet (Cabal).
        GazetteerEntry("Edmond Mulet", "candidate", MULET),
        GazetteerEntry("Mulet", "candidate", MULET),
        # Parties.
        GazetteerEntry("Movimiento Semilla", "party", SEMILLA),
        GazetteerEntry("Semilla", "party", SEMILLA),
        GazetteerEntry("UNE", "party", UNE),
        GazetteerEntry("Unidad Nacional de la Esperanza", "party", UNE),
        GazetteerEntry("Vamos", "party", VAMOS),
        GazetteerEntry("Valor", "party", VALOR),
        GazetteerEntry("Cabal", "party", CABAL),
    ]


def build_fixture_cycle_candidate_for_party() -> dict[int, int]:
    """Per-cycle linker so "el candidato de Semilla" → Arévalo."""
    return {
        SEMILLA: ARÉVALO,
        UNE: TORRES,
        VAMOS: GIAMMATTEI,
        VALOR: ZURY_RÍOS,
        CABAL: MULET,
    }
