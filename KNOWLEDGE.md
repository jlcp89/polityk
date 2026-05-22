# KNOWLEDGE.md — Project Insights

Ticket-agnostic engineering knowledge. Per-ticket session lines live in
`SESSIONS.md`. Append (newest at bottom). Written by `/wrap`, read by
`/recover`.

## Entries

### 2026-05-22 — Cross-migration dimension-table seeds must be conflict-tolerant on every unique constraint

**Context**: New migrations frequently need to seed reference rows that
parties / candidates / etc. *might* already contain — earlier loaders
(`load_*.py`) or hand-written DML may have inserted the same logical
entity under a different surface form. `parties` has two unique
constraints (`name`, `tse_code`); writes from loaders use the source
data's casing/spelling, while seeds in migrations pick a canonical form.

**Problem**: The first draft of `0023_party_of_government.sql` used
`ON CONFLICT (tse_code) DO NOTHING` to seed parties and then resolved
the cycle → party_id mapping with a per-row scalar subquery
(`SELECT party_id FROM parties WHERE tse_code = 'VAMOS'`). Two failure
modes lurk:

1. If a prior loader inserted `parties(name='Vamos', tse_code='Vamos')`,
   my insert `parties(name='Vamos', tse_code='VAMOS')` hits the
   `UNIQUE(name)` constraint — `ON CONFLICT (tse_code)` only catches
   tse_code collisions, so the migration errors out.
2. If the `tse_code` casing differs, the scalar subquery returns NULL
   → `party_of_government.party_id` is NULL → the NOT NULL FK fails.

**Solution**:
- Seed dimension rows with `ON CONFLICT DO NOTHING` *without a target*
  so the insert skips on any unique violation, regardless of which
  column collided.
- Resolve FK dependencies via `INSERT … SELECT … FROM (VALUES …) JOIN
  parents ON parents.natural_key = d.natural_key` — unmatched rows are
  silently dropped instead of producing a NULL FK that violates NOT NULL.
- Make the Python reader tolerate missing dim rows (e.g.,
  `read_party_of_government` returns a `{cycle: party_id}` map that
  simply omits unmapped cycles; the model treats them as non-incumbent).

**Prevention**: Any future migration that seeds rows referencing
`parties`, `candidates`, `pollsters`, `geographies` should follow the
same two-step pattern: (a) ON CONFLICT DO NOTHING for the parent seed,
(b) JOIN-based INSERT for dependents, (c) the Python reader handles a
missing dim row as a no-op rather than raising. The single test that
catches this is the integration round-trip against a real DB — the
fake-conn unit tests can't reproduce the constraint interaction.
