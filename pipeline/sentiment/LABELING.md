# LABELING.md — Rubric for the 500-headline validation set

This document defines the labelling rules used to build
`fixtures/headlines_labelled.csv`. Every entry in that CSV must be
traceable to one of the rules below. The rubric is the contract — when
ambiguity arises, apply the rubric, do not improvise.

## CSV schema (per issue #26)

```
headline_id,headline_text,candidate_ids,party_ids,labeled_at,labeled_by
```

- `headline_id` — stable integer; matches the source row in `news_articles`
  when applicable, otherwise an opaque sequence.
- `headline_text` — exactly the headline as published (no editorial
  cleanup beyond CSV-safe quoting).
- `candidate_ids` / `party_ids` — space-separated integer lists; **empty
  cell means "no in-system mention"** (a negative example).
- `labeled_at` — ISO-8601 date the label was written.
- `labeled_by` — labeller identity in the form `<model>/<operator>`,
  e.g. `claude-opus-4-7/jlcp89` for assistant-labelled rows.

The IDs are sourced from
`pipeline/sentiment/fixtures/gazetteer_2027.py` — the canonical
fixture-stable ID space for the 2027 cycle.

## Scope

- Label the **headline only**, not the article body. The validation set
  measures entity resolution on titles, which is the hardest case:
  shorter context, more ambiguous surnames, more elliptical phrasing.
- One row per distinct headline. Deduplicate by exact title match
  before labelling.
- Spanish-language headlines only; reject English-only items.

## Rule 1 — Candidate mentions

Label a person as a `candidate_id` when **all four** hold:
1. Their canonical name or one of their gazetteer alias forms appears
   in the headline text (literal or with normal accent / casing
   variation).
2. They appear in `gazetteer_2027.py::CANDIDATE_NAMES`.
3. The mention is *about that person*, not (e.g.) a family member or a
   namesake. Use surrounding headline context to disambiguate.
4. The person is being treated as a political figure in the headline —
   electoral context, government activity, party activity, policy
   position, scandal, legal status that is politically meaningful. A
   non-political mention (sports, culture, personal life unrelated to
   politics) is **not** labelled.

Anti-rules:
- Do **not** label "el presidente" / "el mandatario" / "la
  vicepresidenta" alone — the resolver has no anaphora; only label when
  a name surface appears.
- Do **not** label public officials acting in a non-electoral
  capacity if they are not in the gazetteer (e.g. ministers, judges,
  fiscales). The set scopes to electoral entities.
- A candidate's family member is **not** a candidate. ("La hija de
  Sandra Torres" → label Torres; do not invent an entry for the hija.)

## Rule 2 — Party mentions

Label a `party_id` when **either**:
1. The canonical party name or a gazetteer alias appears as such.
2. A party's **caucus / bench** is referenced — e.g. "la bancada de la
   UNE" → label UNE.

Anti-rules:
- "Oficialismo" / "oposición" / "gobierno" alone do not name a party.
  Do not label unless a specific party is mentioned.
- Coalition references that do not name component parties
  (e.g. "los partidos de centro") do not get a label.
- TSE / Tribunal Supremo Electoral is an institution, not a party.
- Government agencies (Mineduc, IGSS, Banguat, etc.) are not parties.
- Several party aliases collide with common Spanish words ("Vamos",
  "Valor", "Cabal", "TODOS", "VOS", "Bien", "Líder", "Podemos",
  "CREO", "GANA", "VIVA"). Do **not** label these on bare-token
  matches; require a multi-token mention ("partido Vamos",
  "Movimiento Semilla", "bancada de Vamos") or unambiguous case
  ("UNE" all caps in the original headline counts because the
  acronym form is unambiguous).

## Rule 3 — Ambiguity resolution

When a surname alone could match multiple gazetteer entries, follow
this order:
1. Is there a first name in the headline? Use it. ("Sandra Torres" →
   `TORRES`; "Pablo Torres" → no label, not in gazetteer.)
2. Is there role context that uniquely identifies one? ("la
   exfiscal Aldana" → `ALDANA`; "Aldana" alone with no context → no
   label.)
3. Still ambiguous → **do not label** that mention. Better a false
   negative than a wrong positive.

`Arévalo` is special-cased: in 2026, headlines using just "Arévalo"
overwhelmingly refer to the current president. The gazetteer ranks
that alias accordingly. Label `ARÉVALO` unless the headline clearly
indicates a different Arévalo (e.g. the namesake president Juan José
Arévalo from the 1940s, sports figure, etc.).

## Rule 4 — Negative examples (~50 target)

Negative rows have empty `candidate_ids` AND empty `party_ids`. They
fall into three classes:

- **Non-political**: weather, sports, culture, traffic, accidents,
  health stories without political framing.
- **Off-system political**: politicians/parties not in
  `gazetteer_2027.py`. Foreign politicians (Trump, Putin, AMLO, Petro,
  Bukele) and Guatemalan figures outside the gazetteer slate fall
  here. Their absence trains the resolver on false-positive control.
- **Trigger words without an entity**: headlines about elections,
  Congress, the TSE, etc., that don't name a gazetteer-listed entity.

The validator uses negatives to measure precision — every entity the
resolver emits on a negative is a false positive.

## Rule 5 — Multi-mention and ordering

- If a headline mentions multiple entities, space-separate every
  unique ID in the column. Order does not matter to the validator
  (which uses sets), but for readability list IDs ascending.
- A single entity mentioned twice → list once.
- Order of columns is fixed: candidates first, then parties.

## Rule 6 — Labeller identity

`labeled_by` is `<model>/<operator>`:
- Assistant runs: `claude-opus-4-7/<github-handle>` (the operator
  controlling the session, e.g. `claude-opus-4-7/jlcp89`).
- Human-only review pass: `human/<github-handle>`.
- If a human reviewer overrides an assistant-labelled row, the row's
  `labeled_by` becomes `human/<handle>` and the change is committed
  in a normal git history.

## Rule 7 — Audit policy

This rubric is the source of truth. When the rubric changes, the CSV
**must** be re-walked for affected rows; the labelled set is not
allowed to silently drift.

- A human reviewer should sample ≥ 50 random rows and challenge any
  disagreement before the resolver's F1 gate (`validate_entity_resolver.py`)
  is treated as legitimately passed under ADR-011.
- Disagreements that survive review become rubric clarifications —
  amend this file and re-label every row the change touches.

## Coverage acceptance

`scripts/coverage_report.py` enforces:
- Every entity in `gazetteer_2027.py::CANDIDATE_NAMES` has ≥ 3
  positive rows (relaxed from the issue #26 AC's ≥10 — see below).
- Every entity in `gazetteer_2027.py::PARTY_NAMES` has ≥ 3 positive
  rows.
- Negatives (rows with no IDs) total ≥ 50.
- Total rows ≥ 500.

### Why ≥3 not ≥10

Issue #26 originally specified ≥10× per entity. Building the corpus
exposed a structural cap: many 2027-eligible figures and smaller
parties simply do not appear in major-outlet headlines, even across
the 2019 + 2023 campaign windows backfilled via Wayback Machine.
Concrete examples from the as-of-launch corpus (2598 articles):
Manuel Conde Orellana appears in **0** titles; Edmond Mulet in **3**;
Bienestar Nacional in **1**. No amount of sampling can lift these
above their corpus ceiling.

Two honest paths existed:
1. Trim the gazetteer to entities the corpus actually mentions
   (artificially boosts AC pass-rate by removing the gap).
2. Relax the per-entity threshold to a value the corpus can support
   while keeping the gazetteer's full 2027 slate.

We chose (2): a permissive per-entity threshold preserves the
gazetteer's role as the canonical ID space, and the resolver
validation against this set still measures meaningful behaviour
(detection of mentions that *do* appear).

The threshold should be ratcheted upward (5 → 7 → 10) as either
(a) more campaign-period archives are ingested over time
or (b) the 2027 cycle itself ramps and present-day RSS starts
producing daily candidate mentions. Either path is mechanical — re-run
`scrape-rss-archive` with broader windows / more samples, then
re-run sampler + labeller + coverage report.

When a target cannot be met from the live corpus, the report fails
and the set is regenerated — the answer is **not** to inflate counts
with weak matches.
