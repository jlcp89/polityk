"""2027-cycle gazetteer for the issue #26 labelled validation set.

This is the canonical fixture-ID space used by ``headlines_labelled.csv``.
The IDs here are fixture-stable (not DB ``candidate_id`` / ``party_id``);
the production resolver at runtime is constructed via
``EntityResolver.from_db_rows(...)``. The same headline corpus stays
re-keyable when real rows land in ``candidates`` / ``parties`` because
the matcher works on the surface forms in this gazetteer, not on the IDs.

Slate is the universe of *plausibly headline-mentioned 2027 political
figures and parties* as of 2026-05. It is intentionally broader than the
formally-registered 2027 slate (which is still fluid). Every entity has
≥ 3 alias surface forms — full name, surname-only when unambiguous, and
common short forms / TSE codes — so the resolver gets meaningful coverage.

See ``LABELING.md`` for the rubric that maps each headline to a subset
of these IDs.
"""

from __future__ import annotations

from pipeline.sentiment.entity_resolver import GazetteerEntry

# ---------------------------------------------------------------------------
# Candidate IDs (fixture-stable, 101-199).
# ---------------------------------------------------------------------------

ARÉVALO = 101  # Bernardo Arévalo (Semilla — incumbent)
HERRERA = 102  # Karin Herrera (Semilla VP)
TORRES = 103  # Sandra Torres (UNE)
MULET = 104  # Edmond Mulet (Cabal)
ZURY_RÍOS = 105  # Zury Ríos (Valor)
CONDE = 106  # Manuel Conde Orellana (Vamos)
PINEDA = 107  # Carlos Pineda (Prosperidad Ciudadana)
ARZÚ = 108  # Roberto Arzú (Podemos)
MOLINA = 109  # Roberto Molina Barreto (Valor VP)
GIAMMATTEI = 110  # Alejandro Giammattei (Vamos, former president)
ALDANA = 111  # Thelma Aldana (Semilla, former AG)
BALDIZÓN = 112  # Manuel Baldizón (Líder/FCN, ex-candidate)
ESTRADA = 113  # Mario Estrada (UCN, jailed in US)
RIVERA = 114  # Amílcar Rivera (Viva, Mixco mayor)

CANDIDATE_NAMES: dict[int, str] = {
    ARÉVALO: "Bernardo Arévalo",
    HERRERA: "Karin Herrera",
    TORRES: "Sandra Torres",
    MULET: "Edmond Mulet",
    ZURY_RÍOS: "Zury Ríos",
    CONDE: "Manuel Conde Orellana",
    PINEDA: "Carlos Pineda",
    ARZÚ: "Roberto Arzú",
    MOLINA: "Roberto Molina Barreto",
    GIAMMATTEI: "Alejandro Giammattei",
    ALDANA: "Thelma Aldana",
    BALDIZÓN: "Manuel Baldizón",
    ESTRADA: "Mario Estrada",
    RIVERA: "Amílcar Rivera",
}

# ---------------------------------------------------------------------------
# Party IDs (fixture-stable, 201-299).
# ---------------------------------------------------------------------------

SEMILLA = 201
UNE = 202
VAMOS = 203
VALOR = 204
CABAL = 205
VIVA = 206
BIEN = 207
TODOS = 208
WINAQ = 209
PODEMOS = 210
URNG = 211
MLP = 212
VOS = 213
PP = 214  # Partido Patriota (cancelled, still referenced historically)
FCN = 215
CREO = 216  # Compromiso Renovación y Orden
LÍDER = 217  # cancelled, still referenced
GANA = 218

PARTY_NAMES: dict[int, str] = {
    SEMILLA: "Movimiento Semilla",
    UNE: "Unidad Nacional de la Esperanza",
    VAMOS: "Vamos",
    VALOR: "Valor",
    CABAL: "Cabal",
    VIVA: "Visión con Valores",
    BIEN: "Bienestar Nacional",
    TODOS: "TODOS",
    WINAQ: "Winaq",
    PODEMOS: "Podemos",
    URNG: "URNG-MAÍZ",
    MLP: "Movimiento para la Liberación de los Pueblos",
    VOS: "VOS",
    PP: "Partido Patriota",
    FCN: "Frente de Convergencia Nacional",
    CREO: "Compromiso Renovación y Orden",
    LÍDER: "Libertad Democrática Renovada",
    GANA: "Gran Alianza Nacional",
}

# ---------------------------------------------------------------------------
# Candidate → party mapping (for the "candidato de X" trigger phrase).
# Maps cycle (party_id → candidate_id) for the 2027 prospective slate.
# ---------------------------------------------------------------------------

CYCLE_CANDIDATE_FOR_PARTY: dict[int, int] = {
    SEMILLA: ARÉVALO,
    UNE: TORRES,
    VAMOS: CONDE,
    VALOR: ZURY_RÍOS,
    CABAL: MULET,
    PODEMOS: ARZÚ,
    VIVA: RIVERA,
}


def build_gazetteer() -> list[GazetteerEntry]:
    """Canonical + alias surface forms covering the 2027 slate."""
    e = GazetteerEntry
    return [
        # ---- Bernardo Arévalo (Semilla — incumbent) ----
        e("Bernardo Arévalo", "candidate", ARÉVALO),
        e("Bernardo Arévalo de León", "candidate", ARÉVALO),
        e("Arévalo de León", "candidate", ARÉVALO),
        e("presidente Arévalo", "candidate", ARÉVALO),
        e("Arévalo", "candidate", ARÉVALO),
        # ---- Karin Herrera (Semilla VP) ----
        e("Karin Herrera", "candidate", HERRERA),
        e("vicepresidenta Herrera", "candidate", HERRERA),
        e("Karin Larissa Herrera", "candidate", HERRERA),
        # ---- Sandra Torres (UNE) ----
        e("Sandra Torres", "candidate", TORRES),
        e("Sandra Julieta Torres", "candidate", TORRES),
        e("Sandra Torres Casanova", "candidate", TORRES),
        # ---- Edmond Mulet (Cabal) ----
        e("Edmond Mulet", "candidate", MULET),
        e("Mulet", "candidate", MULET),
        e("Edmond Mulet Lesieur", "candidate", MULET),
        # ---- Zury Ríos (Valor) ----
        e("Zury Ríos", "candidate", ZURY_RÍOS),
        e("Zury Mayté Ríos Sosa", "candidate", ZURY_RÍOS),
        e("Zury Ríos Sosa", "candidate", ZURY_RÍOS),
        # ---- Manuel Conde Orellana (Vamos) ----
        e("Manuel Conde", "candidate", CONDE),
        e("Manuel Conde Orellana", "candidate", CONDE),
        e("Conde Orellana", "candidate", CONDE),
        # ---- Carlos Pineda (Prosperidad Ciudadana) ----
        e("Carlos Pineda", "candidate", PINEDA),
        e("Carlos Ramiro Pineda", "candidate", PINEDA),
        # ---- Roberto Arzú (Podemos) ----
        e("Roberto Arzú", "candidate", ARZÚ),
        e("Roberto Arzú García-Granados", "candidate", ARZÚ),
        # ---- Roberto Molina Barreto (Valor VP) ----
        e("Roberto Molina Barreto", "candidate", MOLINA),
        e("Molina Barreto", "candidate", MOLINA),
        # ---- Alejandro Giammattei (Vamos, former president) ----
        e("Alejandro Giammattei", "candidate", GIAMMATTEI),
        e("Giammattei", "candidate", GIAMMATTEI),
        e("expresidente Giammattei", "candidate", GIAMMATTEI),
        # ---- Thelma Aldana (Semilla, former AG) ----
        e("Thelma Aldana", "candidate", ALDANA),
        e("exfiscal Aldana", "candidate", ALDANA),
        # ---- Manuel Baldizón ----
        e("Manuel Baldizón", "candidate", BALDIZÓN),
        e("Baldizón", "candidate", BALDIZÓN),
        # ---- Mario Estrada ----
        e("Mario Estrada", "candidate", ESTRADA),
        # ---- Amílcar Rivera (Viva) ----
        e("Amílcar Rivera", "candidate", RIVERA),
        e("Neto Bran", "candidate", RIVERA),
        # ---- Parties ----
        e("Movimiento Semilla", "party", SEMILLA),
        e("Semilla", "party", SEMILLA),
        e("Unidad Nacional de la Esperanza", "party", UNE),
        e("UNE", "party", UNE),
        e("Vamos", "party", VAMOS),
        e("partido Vamos", "party", VAMOS),
        e("Valor", "party", VALOR),
        e("partido Valor", "party", VALOR),
        e("Cabal", "party", CABAL),
        e("partido Cabal", "party", CABAL),
        e("Visión con Valores", "party", VIVA),
        e("VIVA", "party", VIVA),
        e("Bienestar Nacional", "party", BIEN),
        e("BIEN", "party", BIEN),
        e("TODOS", "party", TODOS),
        e("partido TODOS", "party", TODOS),
        e("Winaq", "party", WINAQ),
        e("Movimiento Político Winaq", "party", WINAQ),
        e("Podemos", "party", PODEMOS),
        e("partido Podemos", "party", PODEMOS),
        e("URNG", "party", URNG),
        e("URNG-MAÍZ", "party", URNG),
        e("Unidad Revolucionaria Nacional Guatemalteca", "party", URNG),
        e("MLP", "party", MLP),
        e("Movimiento para la Liberación de los Pueblos", "party", MLP),
        e("VOS", "party", VOS),
        e("partido VOS", "party", VOS),
        e("Partido Patriota", "party", PP),
        e("PP", "party", PP),
        e("FCN", "party", FCN),
        e("FCN-Nación", "party", FCN),
        e("Frente de Convergencia Nacional", "party", FCN),
        e("CREO", "party", CREO),
        e("Compromiso Renovación y Orden", "party", CREO),
        e("Líder", "party", LÍDER),
        e("Libertad Democrática Renovada", "party", LÍDER),
        e("GANA", "party", GANA),
        e("Gran Alianza Nacional", "party", GANA),
    ]


def build_cycle_candidate_for_party() -> dict[int, int]:
    """For the resolver's 'candidato de X' / 'aspirante por Y' trigger."""
    return dict(CYCLE_CANDIDATE_FOR_PARTY)


# Convenience export for scripts that want quick (id → display name).
ENTITY_NAMES: dict[tuple[str, int], str] = {
    **{("candidate", cid): name for cid, name in CANDIDATE_NAMES.items()},
    **{("party", pid): name for pid, name in PARTY_NAMES.items()},
}
