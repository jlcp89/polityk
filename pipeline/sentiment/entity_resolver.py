"""Resolve free-text spans to `(candidate_id | party_id, confidence)` mentions.

Per ADR-011 + ADR-015: sentiment grain is per-sentence × per-entity. This
module takes a Spanish text fragment (typically a single sentence) and
returns every span that resolves to a known Guatemalan candidate or
political party, plus a confidence score.

Resolution pipeline
-------------------
1. Accent-strip + lowercase the input (`unicodedata.normalize('NFKD', …)`).
2. Scan for verbatim gazetteer hits — canonical `candidates.full_name`,
   `candidate_aliases.alias_name`, `parties.name`, `party_aliases.alias_name`.
   Longest entries win to prefer "Bernardo Arévalo" over "Arévalo" when both
   appear in the same span.
3. "<trigger> de <party>" patterns ("el candidato de Semilla", "la
   aspirante por la UNE") map back to the party's current-cycle candidate
   via the `cycle_candidate_for_party` table. This lets the resolver
   recover the issue-spec'd "el candidato de Semilla → same candidate_id"
   case without needing spaCy NER.
4. spaCy `es_core_news_sm` (PER + ORG) catches names the gazetteer missed
   literally — typos, partial matches, novel forms. Each NER span is
   matched against the gazetteer with a Levenshtein threshold so a typo
   like "Sandar Torres" still resolves to Sandra Torres' candidate_id.
   The spaCy model is loaded lazily on first call; if it isn't installed
   the resolver still runs (gazetteer + trigger phrases only). Whether
   sentiment ships as a *modelled* input is gated on the validation
   harness in `validate_entity_resolver.py` hitting ≥95% F1 against the
   #26 labelled headline set (see ADR-011).
"""

from __future__ import annotations

import logging
import re
import unicodedata
from collections.abc import Iterable, Iterator
from dataclasses import dataclass, field
from typing import Any

logger = logging.getLogger(__name__)


_CANDIDATE_TRIGGER_RE = re.compile(
    r"\b(?:candidat[oa]s?|aspirante|presidenciable|abanderad[oa])"
    r"\s+(?:de(?:l)?|por|para)\s+(?:la\s+|el\s+)?",
    re.IGNORECASE,
)


@dataclass(frozen=True)
class GazetteerEntry:
    """One canonical or alias surface for a candidate or party."""

    surface: str
    subject_kind: str  # 'candidate' | 'party'
    subject_id: int
    normalized: str = field(init=False, compare=False)

    def __post_init__(self) -> None:
        if self.subject_kind not in {"candidate", "party"}:
            raise ValueError(f"subject_kind must be candidate|party, got {self.subject_kind!r}")
        object.__setattr__(self, "normalized", normalize(self.surface))
        if not self.normalized.strip():
            raise ValueError(f"empty normalized surface for entry {self.surface!r}")


@dataclass(frozen=True)
class Mention:
    span: str
    start: int
    end: int
    subject_kind: str
    subject_id: int
    confidence: float


def normalize(text: str) -> str:
    """NFKD-decompose, strip combining marks, lowercase. Preserve whitespace shape."""
    decomposed = unicodedata.normalize("NFKD", text)
    stripped = "".join(c for c in decomposed if not unicodedata.combining(c))
    return stripped.lower()


def levenshtein(a: str, b: str) -> int:
    """Pure-python edit distance. Sufficient for short proper-noun spans."""
    if a == b:
        return 0
    if len(a) < len(b):
        a, b = b, a
    if not b:
        return len(a)
    prev = list(range(len(b) + 1))
    for i, ca in enumerate(a, 1):
        curr = [i]
        for j, cb in enumerate(b, 1):
            curr.append(
                min(
                    prev[j] + 1,
                    curr[j - 1] + 1,
                    prev[j - 1] + (0 if ca == cb else 1),
                )
            )
        prev = curr
    return prev[-1]


def _is_word_boundary(text: str, idx: int) -> bool:
    if idx < 0 or idx >= len(text):
        return True
    ch = text[idx]
    return not (ch.isalnum() or ch == "_")


def _find_all_bounded(haystack: str, needle: str) -> Iterator[tuple[int, int]]:
    """Yield (start, end) offsets where `needle` appears bounded by non-word chars."""
    if not needle:
        return
    pos = 0
    nlen = len(needle)
    while True:
        idx = haystack.find(needle, pos)
        if idx == -1:
            return
        left_ok = _is_word_boundary(haystack, idx - 1)
        right_ok = _is_word_boundary(haystack, idx + nlen)
        if left_ok and right_ok:
            yield idx, idx + nlen
        pos = idx + 1


# Lazy spaCy holder. None means "haven't tried yet"; False means "tried, not installed".
_NLP: Any | None = None
_NLP_LOAD_ATTEMPTED = False


def _get_nlp() -> Any | None:
    global _NLP, _NLP_LOAD_ATTEMPTED
    if _NLP_LOAD_ATTEMPTED:
        return _NLP
    _NLP_LOAD_ATTEMPTED = True
    try:
        import spacy
    except ImportError:
        logger.info("spacy not installed; entity_resolver falling back to gazetteer-only")
        _NLP = None
        return None
    try:
        _NLP = spacy.load("es_core_news_sm", disable=["parser", "lemmatizer"])
    except OSError:
        logger.warning(
            "spacy model es_core_news_sm not installed; entity_resolver "
            "falling back to gazetteer-only. Install with: "
            "python -m spacy download es_core_news_sm"
        )
        _NLP = None
    return _NLP


def _reset_nlp_for_tests() -> None:
    """Reset the lazy spaCy cache. Test-only hook."""
    global _NLP, _NLP_LOAD_ATTEMPTED
    _NLP = None
    _NLP_LOAD_ATTEMPTED = False


class EntityResolver:
    """Gazetteer- (and optionally spaCy-) backed entity resolver.

    Parameters
    ----------
    gazetteer
        Every canonical name and alias for in-system candidates and parties.
        Build from `candidates.full_name` ∪ `candidate_aliases.alias_name` ∪
        `parties.name` ∪ `party_aliases.alias_name`.
    cycle_candidate_for_party
        Optional mapping party_id → candidate_id for the *current* election
        cycle. Lets "el candidato de Semilla" resolve to the same candidate
        as "Bernardo Arévalo" without requiring named-entity recognition.
    max_edit_distance
        Levenshtein budget for fuzzy matches against spaCy NER spans. Set
        conservatively — false-positive matches inflate the labelled-set
        precision penalty more than missed mentions inflate recall.
    min_token_len_for_fuzzy
        Don't attempt fuzzy match on tokens shorter than this. "ana" against
        gazetteer "ene" is one edit but obviously wrong.
    """

    def __init__(
        self,
        gazetteer: Iterable[GazetteerEntry],
        cycle_candidate_for_party: dict[int, int] | None = None,
        *,
        max_edit_distance: int = 1,
        min_token_len_for_fuzzy: int = 5,
    ) -> None:
        entries = list(gazetteer)
        self._entries: list[GazetteerEntry] = sorted(
            entries, key=lambda e: len(e.normalized), reverse=True
        )
        self._cycle_candidate_for_party = dict(cycle_candidate_for_party or {})
        self._max_edit_distance = max_edit_distance
        self._min_token_len_for_fuzzy = min_token_len_for_fuzzy

    @classmethod
    def from_db_rows(
        cls,
        candidates: Iterable[tuple[int, str]],
        candidate_aliases: Iterable[tuple[int, str]],
        parties: Iterable[tuple[int, str]],
        party_aliases: Iterable[tuple[int, str]],
        cycle_candidate_for_party: dict[int, int] | None = None,
    ) -> EntityResolver:
        gaz: list[GazetteerEntry] = []
        for cid, full_name in candidates:
            gaz.append(GazetteerEntry(full_name, "candidate", cid))
        for cid, alias in candidate_aliases:
            gaz.append(GazetteerEntry(alias, "candidate", cid))
        for pid, name in parties:
            gaz.append(GazetteerEntry(name, "party", pid))
        for pid, alias in party_aliases:
            gaz.append(GazetteerEntry(alias, "party", pid))
        return cls(gaz, cycle_candidate_for_party)

    def resolve(self, text: str) -> list[Mention]:
        if not text:
            return []
        normalized = normalize(text)
        mentions: list[Mention] = []
        consumed = [False] * len(normalized)

        self._gazetteer_pass(text, normalized, mentions, consumed)
        self._trigger_phrase_pass(text, mentions)

        nlp = _get_nlp()
        if nlp is not None:
            self._ner_pass(text, nlp, mentions, consumed)

        return self._dedupe(mentions)

    def _gazetteer_pass(
        self,
        text: str,
        normalized: str,
        mentions: list[Mention],
        consumed: list[bool],
    ) -> None:
        for entry in self._entries:
            for start, end in _find_all_bounded(normalized, entry.normalized):
                if any(consumed[start:end]):
                    continue
                mentions.append(
                    Mention(
                        span=text[start:end],
                        start=start,
                        end=end,
                        subject_kind=entry.subject_kind,
                        subject_id=entry.subject_id,
                        confidence=1.0,
                    )
                )
                for i in range(start, end):
                    consumed[i] = True

    def _trigger_phrase_pass(self, text: str, mentions: list[Mention]) -> None:
        if not self._cycle_candidate_for_party:
            return
        normalized = normalize(text)
        for match in _CANDIDATE_TRIGGER_RE.finditer(text):
            tail_start = match.end()
            tail_normalized = normalized[tail_start:]
            for entry in self._entries:
                if entry.subject_kind != "party":
                    continue
                if not tail_normalized.startswith(entry.normalized):
                    continue
                right_idx = tail_start + len(entry.normalized)
                if not _is_word_boundary(normalized, right_idx):
                    continue
                cand_id = self._cycle_candidate_for_party.get(entry.subject_id)
                if cand_id is None:
                    break
                start = match.start()
                end = right_idx
                already = any(
                    m.subject_kind == "candidate"
                    and m.subject_id == cand_id
                    and m.start <= start < m.end
                    for m in mentions
                )
                if not already:
                    mentions.append(
                        Mention(
                            span=text[start:end],
                            start=start,
                            end=end,
                            subject_kind="candidate",
                            subject_id=cand_id,
                            confidence=0.8,
                        )
                    )
                break

    def _ner_pass(
        self,
        text: str,
        nlp: Any,
        mentions: list[Mention],
        consumed: list[bool],
    ) -> None:
        doc = nlp(text)
        for ent in doc.ents:
            if ent.label_ not in {"PER", "ORG"}:
                continue
            start, end = ent.start_char, ent.end_char
            if any(consumed[start:end]):
                continue
            span_normalized = normalize(ent.text)
            if len(span_normalized) < self._min_token_len_for_fuzzy:
                continue
            kind_hint = "candidate" if ent.label_ == "PER" else "party"
            best: tuple[int, GazetteerEntry] | None = None
            for entry in self._entries:
                if entry.subject_kind != kind_hint:
                    continue
                if abs(len(entry.normalized) - len(span_normalized)) > self._max_edit_distance:
                    continue
                dist = levenshtein(span_normalized, entry.normalized)
                if dist > self._max_edit_distance:
                    continue
                if best is None or dist < best[0]:
                    best = (dist, entry)
                if dist == 0:
                    break
            if best is None:
                continue
            dist, entry = best
            confidence = 0.95 if dist == 0 else max(0.6, 0.95 - 0.15 * dist)
            mentions.append(
                Mention(
                    span=text[start:end],
                    start=start,
                    end=end,
                    subject_kind=entry.subject_kind,
                    subject_id=entry.subject_id,
                    confidence=confidence,
                )
            )
            for i in range(start, end):
                consumed[i] = True

    @staticmethod
    def _dedupe(mentions: list[Mention]) -> list[Mention]:
        seen: dict[tuple[int, int, str, int], Mention] = {}
        for m in mentions:
            key = (m.start, m.end, m.subject_kind, m.subject_id)
            prev = seen.get(key)
            if prev is None or m.confidence > prev.confidence:
                seen[key] = m
        return sorted(seen.values(), key=lambda m: (m.start, m.end))


def resolve(
    text: str,
    resolver: EntityResolver,
) -> list[Mention]:
    """Module-level convenience wrapper around `EntityResolver.resolve`."""
    return resolver.resolve(text)
