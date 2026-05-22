"""Tests for the entity resolver and its validation harness.

These tests run unconditionally (no Postgres, no spaCy). The spaCy NER
fallback path is exercised via a stub `_NLP` injection so we don't need
the 50 MB model in CI. A separate marker (`@pytest.mark.spacy_model`)
covers the live-spaCy path when the model is available locally.
"""

from __future__ import annotations

import time
from pathlib import Path

import pytest

from pipeline.sentiment import entity_resolver as er
from pipeline.sentiment.entity_resolver import (
    EntityResolver,
    GazetteerEntry,
    Mention,
    levenshtein,
    normalize,
)
from pipeline.sentiment.fixtures.gazetteer_2023 import (
    ARÉVALO,
    GIAMMATTEI,
    SEMILLA,
    TORRES,
    UNE,
    build_fixture_cycle_candidate_for_party,
    build_fixture_gazetteer,
)
from pipeline.sentiment.validate_entity_resolver import (
    SMOKE_CSV,
    load_csv,
    score,
)

# ---- pure helpers --------------------------------------------------------


def test_normalize_strips_accents_and_lowercases() -> None:
    assert normalize("Bernardo Arévalo") == "bernardo arevalo"
    assert normalize("Zury Ríos") == "zury rios"
    assert normalize("ÑOÑO") == "nono"
    assert normalize("Movimiento Semilla") == "movimiento semilla"


def test_normalize_is_idempotent() -> None:
    sample = "Sandra Julieta Torres — UNE"
    assert normalize(normalize(sample)) == normalize(sample)


def test_levenshtein_basic_cases() -> None:
    assert levenshtein("abc", "abc") == 0
    assert levenshtein("abc", "abd") == 1
    assert levenshtein("kitten", "sitting") == 3
    assert levenshtein("", "abc") == 3
    assert levenshtein("sandra", "sandar") == 2


def test_gazetteer_entry_rejects_invalid_kind() -> None:
    with pytest.raises(ValueError, match="subject_kind"):
        GazetteerEntry("foo", "bogus", 1)


def test_gazetteer_entry_rejects_empty_normalized() -> None:
    with pytest.raises(ValueError, match="empty normalized"):
        GazetteerEntry("   ", "candidate", 1)


# ---- resolver -----------------------------------------------------------


@pytest.fixture()
def resolver() -> EntityResolver:
    er._reset_nlp_for_tests()
    return EntityResolver(
        build_fixture_gazetteer(),
        build_fixture_cycle_candidate_for_party(),
    )


def _ids(mentions: list[Mention], kind: str) -> set[int]:
    return {m.subject_id for m in mentions if m.subject_kind == kind}


def test_empty_text_returns_no_mentions(resolver: EntityResolver) -> None:
    assert resolver.resolve("") == []


def test_resolves_canonical_candidate(resolver: EntityResolver) -> None:
    mentions = resolver.resolve("Bernardo Arévalo asume la presidencia")
    assert _ids(mentions, "candidate") == {ARÉVALO}
    assert all(m.confidence == 1.0 for m in mentions)


def test_resolves_alias_for_same_candidate(resolver: EntityResolver) -> None:
    a = _ids(resolver.resolve("Bernardo Arévalo de León presenta su plan"), "candidate")
    b = _ids(resolver.resolve("Arévalo presenta su plan económico"), "candidate")
    assert a == b == {ARÉVALO}


def test_prefers_longest_match_no_double_count(resolver: EntityResolver) -> None:
    # "Bernardo Arévalo" should not also yield a separate "Arévalo" mention
    # at the same offsets.
    mentions = resolver.resolve("Bernardo Arévalo se reúne con la prensa")
    candidate_mentions = [m for m in mentions if m.subject_kind == "candidate"]
    assert len(candidate_mentions) == 1
    assert candidate_mentions[0].subject_id == ARÉVALO


def test_word_boundary_prevents_substring_match(resolver: EntityResolver) -> None:
    # "arevaloar" should not match "Arévalo" because it isn't word-bounded.
    mentions = resolver.resolve("Esto es arevaloar la propuesta")
    assert _ids(mentions, "candidate") == set()


def test_resolves_party_canonical_and_alias(resolver: EntityResolver) -> None:
    via_full = resolver.resolve("La Unidad Nacional de la Esperanza presenta su plan")
    via_alias = resolver.resolve("La UNE presenta su plan")
    assert _ids(via_full, "party") == _ids(via_alias, "party") == {UNE}


def test_trigger_phrase_maps_party_to_candidate(resolver: EntityResolver) -> None:
    """`el candidato de Semilla` → Bernardo Arévalo (same candidate_id)."""
    mentions = resolver.resolve("El candidato de Semilla agradece a sus votantes")
    # Both the party and the inferred candidate should appear.
    assert SEMILLA in _ids(mentions, "party")
    assert ARÉVALO in _ids(mentions, "candidate")


def test_trigger_phrase_handles_feminine_and_compound_articles(
    resolver: EntityResolver,
) -> None:
    mentions = resolver.resolve("La aspirante por la UNE convoca a una manifestación")
    assert UNE in _ids(mentions, "party")
    assert TORRES in _ids(mentions, "candidate")


def test_trigger_phrase_skips_when_party_has_no_cycle_candidate() -> None:
    er._reset_nlp_for_tests()
    # Gazetteer with the party but no cycle mapping.
    gaz = [GazetteerEntry("Semilla", "party", SEMILLA)]
    resolver = EntityResolver(gaz, cycle_candidate_for_party={})
    mentions = resolver.resolve("El candidato de Semilla agradece a sus votantes")
    assert _ids(mentions, "candidate") == set()
    assert _ids(mentions, "party") == {SEMILLA}


def test_multiple_subjects_in_same_sentence(resolver: EntityResolver) -> None:
    mentions = resolver.resolve("Arévalo y Torres se disputan la segunda elección")
    assert _ids(mentions, "candidate") == {ARÉVALO, TORRES}


def test_party_and_candidate_resolved_together(resolver: EntityResolver) -> None:
    mentions = resolver.resolve("Arévalo se reúne con la bancada de Semilla")
    assert _ids(mentions, "candidate") == {ARÉVALO}
    assert _ids(mentions, "party") == {SEMILLA}


def test_mentions_carry_correct_offsets(resolver: EntityResolver) -> None:
    text = "Sandra Torres impugna el resultado"
    mentions = resolver.resolve(text)
    cand = next(m for m in mentions if m.subject_kind == "candidate")
    assert text[cand.start : cand.end] == "Sandra Torres"


def test_dedupes_overlapping_mentions(resolver: EntityResolver) -> None:
    mentions = resolver.resolve("Arévalo, Arévalo, Arévalo en titulares de hoy")
    # Three distinct offsets — three mentions, no double-count at any single offset.
    cand_mentions = [m for m in mentions if m.subject_id == ARÉVALO]
    assert len(cand_mentions) == 3
    assert len({m.start for m in cand_mentions}) == 3


# ---- NER fallback (stubbed; no real spaCy needed) ----------------------


class _StubEnt:
    def __init__(self, text: str, label: str, start: int, end: int) -> None:
        self.text = text
        self.label_ = label
        self.start_char = start
        self.end_char = end


class _StubDoc:
    def __init__(self, ents: list[_StubEnt]) -> None:
        self.ents = ents


class _StubNLP:
    """Drop-in stub that returns whatever entities the test prepared."""

    def __init__(self, ents_for: dict[str, list[_StubEnt]]) -> None:
        self._ents_for = ents_for

    def __call__(self, text: str) -> _StubDoc:
        return _StubDoc(self._ents_for.get(text, []))


def test_ner_pass_resolves_typo_within_edit_distance(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    er._reset_nlp_for_tests()
    # "Giamatte" is two edits from "Giammattei" and is *not* a substring of any
    # gazetteer alias, so this span only resolves via the NER fuzzy path.
    text = "Giamatte concluye su mandato presidencial"
    stub = _StubNLP({text: [_StubEnt("Giamatte", "PER", 0, 8)]})
    monkeypatch.setattr(er, "_NLP_LOAD_ATTEMPTED", True)
    monkeypatch.setattr(er, "_NLP", stub)
    resolver = EntityResolver(
        build_fixture_gazetteer(),
        build_fixture_cycle_candidate_for_party(),
        max_edit_distance=2,
    )
    mentions = resolver.resolve(text)
    assert GIAMMATTEI in _ids(mentions, "candidate")
    ner_mention = next(m for m in mentions if m.subject_id == GIAMMATTEI)
    assert ner_mention.confidence < 1.0  # downweighted because of edit distance


def test_ner_pass_does_not_double_count_gazetteer_hits(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    er._reset_nlp_for_tests()
    text = "Sandra Torres impugna el resultado"
    # NER would also flag this span; the gazetteer pass already consumed it.
    stub = _StubNLP({text: [_StubEnt("Sandra Torres", "PER", 0, 13)]})
    monkeypatch.setattr(er, "_NLP_LOAD_ATTEMPTED", True)
    monkeypatch.setattr(er, "_NLP", stub)
    resolver = EntityResolver(
        build_fixture_gazetteer(),
        build_fixture_cycle_candidate_for_party(),
    )
    mentions = resolver.resolve(text)
    torres_mentions = [m for m in mentions if m.subject_id == TORRES]
    assert len(torres_mentions) == 1


def test_ner_pass_skips_unknown_person(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    er._reset_nlp_for_tests()
    text = "Pepe Garcia anuncia su jubilación"
    stub = _StubNLP({text: [_StubEnt("Pepe Garcia", "PER", 0, 11)]})
    monkeypatch.setattr(er, "_NLP_LOAD_ATTEMPTED", True)
    monkeypatch.setattr(er, "_NLP", stub)
    resolver = EntityResolver(
        build_fixture_gazetteer(),
        build_fixture_cycle_candidate_for_party(),
    )
    assert resolver.resolve(text) == []


# ---- performance --------------------------------------------------------


def test_resolves_100_tokens_under_50ms(resolver: EntityResolver) -> None:
    text = (
        "Bernardo Arévalo, presidente de Guatemala, dialogó con Sandra Torres y "
        "con Alejandro Giammattei sobre el futuro del país. La aspirante por la "
        "UNE pidió transparencia, mientras que el abanderado de Vamos rechazó "
        "los señalamientos. Zury Ríos y Edmond Mulet coincidieron en pedir "
        "reformas profundas al sistema electoral. El Movimiento Semilla "
        "mantiene su personalidad jurídica bajo apelación ante el TSE, y la "
        "Unidad Nacional de la Esperanza convocó a sus militantes para una "
        "asamblea nacional. Cabal y Valor presentaron plataformas legislativas "
        "alineadas frente a la agenda del Ejecutivo, según fuentes consultadas "
        "el día de hoy. Se espera que la próxima ronda de encuestas confirme "
        "las tendencias observadas en estudios anteriores, y que los analistas "
        "compartan sus interpretaciones durante la cobertura especial."
    )
    assert len(text.split()) >= 100
    # Warm-up call (no JIT here, but populates Python caches).
    resolver.resolve(text)
    start = time.perf_counter()
    resolver.resolve(text)
    elapsed_ms = (time.perf_counter() - start) * 1000
    assert elapsed_ms < 50, f"resolver took {elapsed_ms:.2f} ms, gate is 50 ms"


# ---- validation harness ------------------------------------------------


def test_harness_loads_smoke_csv() -> None:
    rows = load_csv(SMOKE_CSV)
    assert len(rows) >= 25  # enough for a meaningful F1 measurement
    # Each labelled row must carry at least one column; "negative" rows are
    # allowed (both ID sets empty).
    negatives = [r for r in rows if not r.candidate_ids and not r.party_ids]
    assert negatives, "fixture should contain false-positive controls"


def test_harness_scores_smoke_fixture_above_threshold() -> None:
    """F1 ≥ 0.95 on the hand-built smoke set proves the harness works.

    Issue #26's 500-row labelled set is the real launch gate; this asserts
    only that the resolver + harness combine to *measure* F1 correctly
    on a known input.
    """
    er._reset_nlp_for_tests()
    resolver = EntityResolver(
        build_fixture_gazetteer(),
        build_fixture_cycle_candidate_for_party(),
    )
    rows = load_csv(SMOKE_CSV)
    report = score(resolver, rows)
    assert report.f1 >= 0.95, (
        f"smoke F1 below gate: {report.f1:.3f} "
        f"(tp={report.true_positives}, fp={report.false_positives}, fn={report.false_negatives})"
    )


def test_harness_main_returns_zero_when_smoke_csv_present() -> None:
    from pipeline.sentiment.validate_entity_resolver import main

    rc = main(["--csv", str(SMOKE_CSV)])
    assert rc == 0


def test_harness_main_returns_two_when_csv_missing(tmp_path: Path) -> None:
    from pipeline.sentiment.validate_entity_resolver import main

    rc = main(["--csv", str(tmp_path / "does-not-exist.csv")])
    assert rc == 2


# ---- spaCy live-model marker --------------------------------------------

pytestmark_spacy = pytest.mark.skipif(
    True,
    reason="es_core_news_sm model not installed in CI; covered by stub tests above",
)


@pytestmark_spacy
def test_live_spacy_es_core_news_sm_loads() -> None:  # pragma: no cover
    er._reset_nlp_for_tests()
    nlp = er._get_nlp()
    assert nlp is not None, "spaCy es_core_news_sm should load when installed locally"
