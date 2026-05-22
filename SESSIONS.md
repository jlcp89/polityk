# SESSIONS.md — Per-Ticket Session Log

One distilled line per `/wrap`, prepended so newest is on top. Each line is tied to a ticket/issue number. Capped at 100 entries via 120→100 rotation: when the file reaches 120 entries, the oldest 20 are dropped. Coexists with KNOWLEDGE.md (ticket-agnostic project insights).

Written by `/wrap`. Read by `/recover`.

## Format

`DATE | TICKET | BRANCH | SHA | problem: … | fix: … | ref: …`

- DATE: `YYYY-MM-DD`
- TICKET: `ticket-N`, `#N`, `TKT-N`, `issue-N`, or `ticket-none`
- BRANCH: current git branch (`detached` if HEAD is detached)
- SHA: short SHA from `git log -1 --format=%h`
- problem / fix / ref: each ≤ 120 chars; whole line ≤ 500 chars; `none` when empty

## Entries

<!-- newest first; do not edit by hand — managed by /wrap -->
2026-05-22 | #31 | main | fbfa94d | problem: fundamentals layer missing; 4 of 8 features lacked schema (incumbent map, approval, candidate-list dates) | fix: 3 migrations (party_of_government, election_key_dates, approval_ratings) + logit-Normal PyMC regression + LOO backtest; coverage gate passes | ref: pipeline/models/fundamentals.py, ADR-020
