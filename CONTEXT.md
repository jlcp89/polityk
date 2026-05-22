# Project Context: polityk

*Last updated: 2026-05-21. Updated by `/wrap` when project-level context changes (architecture decisions, conventions, domain language). Day-to-day work lives in GitHub Issues (`gh issue list`), not here.*

## Mission

Build a free, public-facing platform that forecasts Guatemala's 2027 General Elections — president (two-round), 160-seat Congress (128 distritales + 32 lista nacional, D'Hondt), and 340 municipal races — using Bayesian hierarchical models in PyMC. Backend is a Go JSON API served through a Cloudflare Tunnel from a 2024 IdeaPad (Ryzen 7000-series, 16 GB RAM). Public client is a native Kotlin Android app. Goal: a credible, probabilistic, publication-quality forecast that respects Guatemalan electoral law (especially the 36-hour pre-election blackout).

The original architecture in `docs/requirement.md` specified an Astro static site on Cloudflare Pages as the public client; that decision was superseded on 2026-05-21 — see ADR-002 below.

## Stakeholders

- **Primary users**: Guatemalan voters, journalists, and political analysts seeking probabilistic election forecasts on mobile devices.
- **Maintainer**: [@jlcp89](https://github.com/jlcp89).
- **Legal**: forecasts must comply with the Constitutional Court ruling on expediente 1699-2018 (23 April 2019) — 36-hour blackout before each election round.

## Domain Language

<!-- Maintained by /grill. Skip generic programming concepts. -->

**D'Hondt**: Highest-averages seat allocation method. Applied independently in each of Guatemala's 23 multi-member congressional districts (varying 2–19 seats) and once to the 32-seat national list. Deterministic given vote counts; ties broken by party order (project convention).

**Memoria Electoral**: TSE's post-election retrospective publication (PDF only, multi-hundred pages). 2014, 2015, 2017, 2018, 2019 published; **2023 not yet published as of 2026-05** despite TSE statements in October 2023.

**TREP**: Transmisión de Resultados Electorales Preliminares — TSE's 2023 preliminary-results system. **Will not be reused in 2027**; TSE has announced an in-house replacement. Monitor `tse.org.gt` quarterly for the new system.

**Padrón electoral**: Registered-voters list. 2023 total: 9,361,068. Published in HTML reports aggregated by department, municipality, age, sex — no CSV.

**Personalidad jurídica vigente**: A political party's active legal status. As of early 2026, 28 parties hold active status per TSE (Canal Antigua, 9 Feb 2026); 11 of 2023's parties were cancelled. **Movimiento Semilla's cancellation is vigente but under appeal** — treat 2027 eligibility as a runtime flag.

**Blackout (silencio electoral)**: Legal prohibition on publishing polls/forecasts in the 36 hours before each election round. Our `BLACKOUT_ENABLED` env var on the Go API is the enforcement mechanism.

_Avoid_: do not call the runoff a "segunda vuelta" in code — TSE official terminology uses "segunda elección". Internal naming: `presidential_round_1` / `presidential_round_2`.

## Architecture Decisions

<!-- ADR-style entries — only for decisions that are hard to reverse, surprising without context, AND the result of a real trade-off. Most decisions don't qualify. Maintained by /grill or /wrap. -->

### ADR-001: Stdlib-first across all three stacks
- **Status**: accepted (2026-05-21)
- **Context**: Three-stack project (Go, Python, Kotlin/Android) running on a 4–8 GB Celeron. Each third-party dependency adds maintenance cost, audit surface, and potential supply-chain risk. `docs/requirement.md` is explicit about preferring the Go standard library.
- **Decision**: For each stack, prefer stdlib / platform-provided libraries before reaching for third-party. Go: `net/http`, `database/sql`, `log/slog`. Python: `httpx` for scraping (not `requests`+wrappers), `pdfplumber` for PDFs (one focused dep), no Pandas in model files. Android: Compose + Material 3, Hilt, Retrofit, Room — boring, well-maintained, no exotic libraries.
- **Consequences**: Slower initial scaffolding (writing routing patterns by hand), but smaller bundle, smaller attack surface, less version-bump churn. Re-litigate per dep with an ADR if a real ergonomic wall appears.

### ADR-002: Public client is a Kotlin Android app, not an Astro web frontend
- **Status**: accepted (2026-05-21) — supersedes the Astro-on-Cloudflare-Pages design in `docs/requirement.md`
- **Context**: `docs/requirement.md` originally specified a static Astro site on Cloudflare Pages backed by the Go API. The maintainer chose to ship a native Android app instead — Guatemalan smartphone penetration is high, and a native app gives finer control over the blackout UX, offline caching, and accessibility on low-end devices.
- **Decision**: The public client is an Android app written in Kotlin 2.0 with Jetpack Compose, distributed via the Google Play Store. The Go API contract is unchanged; the Android app is a consumer of the same `/forecast/*` endpoints originally designed for Astro.
- **Consequences**: No public web frontend in v1. Web access is via the API directly (curl, journalists' tools), not a styled site. Cloudflare Pages is no longer in the deployment path. The Cloudflare Tunnel remains, fronting the Go API for the mobile app. Re-evaluate post-election whether a web client is worth adding for archival access.

### ADR-003: Legal blackout enforced by the server, never by the client
- **Status**: accepted (2026-05-21)
- **Context**: The 36-hour blackout (expediente 1699-2018) is a legal control. Enforcing it client-side based on device clock is unsafe — clocks on low-end devices drift, can be set manually, and timezone confusion (DST, traveller's clock) creates legal risk.
- **Decision**: A `BLACKOUT_ENABLED` env var on the Go API gates all `/forecast/*` routes via `internal/middleware/blackout.go`. When true, the API returns `503` with a Spanish-language explanation body. The Android app trusts the server: a `503` response renders the blackout splash. The flag is flipped by systemd timers on the host (Fri 18:00 → on, Sun 18:00 → off, both rounds), with a manual-override script as backup.
- **Consequences**: Server is the legal source of truth. Single point to audit. Any change to `internal/middleware/blackout.go` requires a `needs-human` label on the issue. Manual override exists for clock-skew or DST emergencies; every flip is logged.

### ADR-019: Intervention mechanism — `interventions` table lets the model ratchet candidate/party probabilities on disqualification
- **Status**: accepted (2026-05-21) — implements the `docs/requirement.md` caveat ("Build a manual intervention mechanism that lets you ratchet a candidate's probability to zero overnight if disqualified")
- **Context**: The 2023 cycle saw multiple late-stage candidate disqualifications and party cancellations that no statistical model could anticipate. Without an intervention path, the published forecast lags reality by hours-to-days during the period when accuracy matters most — and "the model still has X at 10%" after X has been disqualified is exactly the kind of failure that destroys credibility.
- **Decision**: Auditable, side-effect-only intervention rows.
  - Schema: `interventions (intervention_id PK, target_kind ENUM('candidate','party','race'), target_id, kind ENUM('disqualified','withdrew','party_cancelled','manual_probability'), effective_at TIMESTAMPTZ, expires_at TIMESTAMPTZ NULL, override_probability NUMERIC NULL CHECK (override_probability BETWEEN 0 AND 1), reason TEXT NOT NULL, operator TEXT NOT NULL, created_at TIMESTAMPTZ DEFAULT now())`.
  - The Python ML worker reads all interventions with `effective_at <= now() AND (expires_at IS NULL OR expires_at > now())` before fitting. For each active intervention:
    - `disqualified` / `withdrew` / `party_cancelled` → zero the target's posterior column after sampling and renormalise across remaining options.
    - `manual_probability` → replace the target's marginal with a delta at `override_probability` and renormalise siblings proportionally.
  - The `/v1/forecast/*` payload includes an `interventions_applied: [{kind, target, reason, effective_at}]` array for transparency.
  - Inserts to `interventions` are gated to a maintainer-only script (`pipeline/scripts/intervene.py`) that requires `--reason` and writes `operator = $USER`.
- **Consequences**: A disqualification at noon becomes a published-forecast change at the next scheduled run (worst case: the next hourly run during election week). The audit table makes overrides defensible — `reason` and `operator` are `NOT NULL`. What-if scenarios use a separate `forecasts.run_kind = 'whatif'` row that is excluded from `is_published`.

### ADR-018: Android offline-cache freshness — last good response cached ≤72h with escalating banners; blackout always wins
- **Status**: accepted (2026-05-21)
- **Context**: The Android client operates under three regimes: (1) normal — network OK, fresh forecast available; (2) flaky network — last cached forecast still relevant; (3) legal blackout — must show the blackout splash regardless of cache. Showing stale data without a freshness signal is dishonest; refusing to show *any* cached data during a coverage gap is user-hostile.
- **Decision**: Room cache keyed by endpoint URL, gated by `generated_at` (in payload) and `cache_invalid_until` (server-sent override).
  - **0–6 h stale**: render normally with "Actualizado hace X horas" stamp.
  - **6–24 h stale**: render with a yellow "Datos posiblemente desactualizados" banner.
  - **24–72 h stale**: render with a red "Datos antiguos" banner and a prominent retry button.
  - **>72 h stale**: do not render the cached forecast; show "Sin conexión reciente" empty state with retry.
  - **Blackout**: when the API returns `503` (per ADR-003), the blackout splash takes precedence — cached data is *never* shown during blackout. The Go API may include `cache_invalid_until: <ISO-8601>` in any success response; the client honours it as a forced expiry (used at the start of each blackout window so a user with the app open pre-blackout sees the splash without a network refresh).
- **Consequences**: Room schema needs `generated_at` and `cache_invalid_until` columns alongside the JSON blob. The blackout-splash branch in the UI bypasses cache reads entirely. Tested via `adb` time-warp and airplane-mode flows before launch.

### ADR-017: Pollster house-effects estimated from historical performance and carried as `pollsters` dim columns
- **Status**: accepted (2026-05-21)
- **Context**: ProDatos missed Arévalo by ~12.6 percentage points in 2023 (predicted 2.9%, actual ~15.5%); other Guatemalan pollsters have similar (smaller) history-dependent biases. Treating every pollster identically discards that information. The Linzer/Kremp poll-aggregation pattern in `docs/requirement.md` Section C step 1 accommodates pollster-specific bias priors directly — but only if we *estimate* and *store* them.
- **Decision**:
  - Schema:
    - `pollsters (pollster_id PK, name, country_code, est_year NULL, methodology TEXT, historical_bias_mean NUMERIC DEFAULT 0, historical_bias_sd NUMERIC DEFAULT 0.05, sample_count_used SMALLINT DEFAULT 0, bias_last_estimated_at TIMESTAMPTZ NULL)`.
    - `poll_errors (pollster_id FK, cycle, candidate_id FK, poll_prediction NUMERIC, actual_result NUMERIC, error NUMERIC GENERATED ALWAYS AS (poll_prediction - actual_result) STORED)`.
  - `pipeline/scripts/estimate_pollster_bias.py` runs after each cycle's true results land. It fits a hierarchical normal model `error_ij ~ Normal(bias_i, sigma_i)` per pollster across all `(candidate, cycle)` pairs that pollster covered, then writes the posterior mean/sd back to `pollsters.historical_bias_mean` / `historical_bias_sd`.
  - At forecast time, the model treats each new poll as `observed_share_ij ~ Normal(true_share_j + bias_i, poll_se_ij + sigma_i)` using the stored pollster row.
  - New pollsters with `sample_count_used = 0` keep the diffuse default `(0, 0.05)`.
- **Consequences**: After the 2023 fit lands, ProDatos' bias prior widens (likely `historical_bias_sd ≈ 0.10–0.15`), correctly down-weighting its 2027 polls in the aggregator. Re-estimation is cyclical: once per election cycle as truth lands. Adds two tables and one small PyMC script to the v1 critical path — minor effort, large accuracy payoff against precisely the failure mode that hurt 2023 forecasters.

### ADR-016: PARLACEN ingested via a `chamber` discriminator on `congress_results`; not modeled in v1
- **Status**: accepted (2026-05-21)
- **Context**: 20 PARLACEN seats are elected on the same ballot via closed national-list D'Hondt — structurally identical to the 32-seat congressional national list. `docs/requirement.md` puts PARLACEN modelling out of scope for v1 but asks the scraper to ingest the results "for completeness." A separate `parlacen_results` table duplicates ADR-008's congress schema; a `chamber` column on `congress_results` reuses everything.
- **Decision**: Extend ADR-008's `congress_results` with `chamber ENUM('congress_distrital','congress_nacional','parlacen') NOT NULL DEFAULT 'congress_distrital'`. PARLACEN rows reference a synthetic `geographies` row `level='country', code='GT-PARLACEN', name='Nacional (PARLACEN)'`. No `/v1/forecast/parlacen` route in v1 — scraping yes, modelling no.
- **Consequences**: Future PARLACEN modelling is a model-side change with no schema migration. Congressional-model backtests can optionally include PARLACEN as a 33-seat allocation sanity check (its seat-share should track congress_nacional's seat-share closely).

### ADR-015: Sentiment grain is per-sentence × per-entity; inputs span news + Reddit + YouTube + Telegram + Bluesky
- **Status**: accepted (2026-05-21) — refines and extends ADR-011
- **Context**: Article-level POS/NEG/NEU sentiment loses signal when one article discusses multiple candidates with different valences ("Arévalo defendió X, pero Torres criticó Y"). For accuracy-as-feature, scoring must be per-mention, then aggregated. Likewise, news articles alone miss live political discourse — `docs/requirement.md` Section B explicitly enumerates Reddit, YouTube comments, Telegram and Bluesky as legal-and-stable alternatives to Twitter/X and Facebook content.
- **Decision**:
  - **Tokenisation + NER**: spaCy `es_core_news_sm` (≈50 MB) for sentence splitting and `PER` / `ORG` recognition. Entity resolution to `candidate_id` / `party_id` via the gazetteer in ADR-011 plus `party_aliases` and a new `candidate_aliases` table.
  - **Scoring**: `pysentimiento` (BETO base) scored per `(source_kind, source_id, sentence_index, subject_id)` tuple. Sentences with no resolved entity are still scored as `subject_kind = 'overall'`.
  - **Schema**:
    - `news_articles (article_id PK, source, url UNIQUE, published_at TIMESTAMPTZ, title, body_text, lang DEFAULT 'es')`.
    - `social_posts (post_id PK, platform ENUM('reddit','youtube_comment','telegram','bluesky'), source_handle, url, published_at TIMESTAMPTZ, body_text, parent_post_id NULL)`.
    - `sentiment_scores (score_id PK, source_kind ENUM('article','post'), source_id, sentence_index SMALLINT, subject_kind ENUM('candidate','party','overall'), subject_id NULL, score NUMERIC, label ENUM('POS','NEG','NEU'), model_version TEXT)` with a unique index on `(source_kind, source_id, sentence_index, subject_kind, subject_id)`.
    - Materialized view `sentiment_per_source_subject` aggregates to mean score + dominant label per `(source, subject)`.
  - **Sources**:
    - News RSS: the 10 outlets in `docs/requirement.md` Section B + `dca.gob.gt` scrape.
    - Reddit: `reddit.com/r/Guatemala/.json` polled hourly, top-level posts + comments.
    - YouTube: Data API v3 comments on candidate channels (10k quota units/day).
    - Telegram: `telethon` public-channel scraping; channels list at `pipeline/scrapers/telegram/channels.yaml`.
    - Bluesky: AT-Proto firehose filtered by Spanish + Guatemalan-handle list.
  - **Excluded**: Twitter/X, Facebook page content.
- **Consequences**: Storage grows ~10× over article-level scoring (each article has ~10–20 sentences). Postgres handles this trivially at our volumes (~100 articles/day × 20 sentences × 12 cycle-months ≈ 720k rows). Per-mention scoring lets the fundamentals layer use *differential* sentiment (Arévalo POS rate – Torres POS rate over rolling window) instead of overall valence, which is more predictive. Five-platform ingestion fans out the scraper count; rate-limiter discipline becomes non-optional.

### ADR-014: API contract — `/v1/forecast/*` from day one, quantile-based JSONB payload
- **Status**: accepted (2026-05-21)
- **Context**: The Android app, the methodology page, and any future external consumer (journalists, civic tech) all need a stable contract. URL-prefix versioning is the universally-understood, cheapest implementation. Shipping raw posterior samples is wasteful (~5 candidates × 4096 floats × 8 bytes ≈ 160 KB per response); pre-computed quantiles support every UI element this project needs.
- **Decision**: Versioned routes from launch.
  - Endpoints: `/v1/forecast/presidential`, `/v1/forecast/congress`, `/v1/forecast/municipal/{municipality_id}`, `/v1/methodology`, `/v1/health`. Breaking changes bump to `/v2/`; `/v1/` and `/v2/` may coexist for one election cycle then `/v1/` retires.
  - **Presidential payload (canonical)**:
    ```json
    {
      "run_id": "<uuid>",
      "model_version": "0.1.0",
      "generated_at": "<ISO-8601>",
      "race": {"type": "presidential", "cycle": 2027, "round": 1},
      "candidates": [
        {
          "candidate_id": 42,
          "name": "Bernardo Arévalo",
          "wikidata_qid": "Q123",
          "party_id": 17,
          "party_name": "Movimiento Semilla",
          "vote_share": {"p05": 0.12, "p10": 0.14, "p25": 0.18, "p50": 0.23, "p75": 0.28, "p90": 0.32, "p95": 0.34},
          "win_probability_round1": 0.04,
          "qualifies_for_runoff_probability": 0.62
        }
      ],
      "runoff_matrix": [
        {"candidate_a_id": 42, "candidate_b_id": 11, "pair_probability": 0.31, "winner_a_probability": 0.61}
      ],
      "interventions_applied": [],
      "methodology_url": "https://polityk.gt/methodology#presidential-0.1.0"
    }
    ```
  - **Congress payload**: per-district seat-distribution quantiles per party + a national-roll-up.
  - **Municipal payload**: per-municipality alcalde win probability + concejales seat-distribution quantiles.
  - **Headers**: `Cache-Control: public, max-age=300` outside election week; `max-age=60` during. `ETag` on every response. `Content-Type: application/json; charset=utf-8`.
  - **Errors**: `503` for blackout (ADR-003), `404` for race types not yet live (ADR-007), `429` if rate-limit triggers.
- **Consequences**: Stable Android contract from day one; the JSONB column in `forecasts.payload` stores the response shape directly so `SELECT payload FROM forecasts WHERE …` is literally the API body. Storing quantiles loses the ability to recompute custom intervals at the API layer; the model run *also* writes the full posterior to `posterior_archives (run_id FK, race_type, sample_array NUMERIC[][])` for retrospective analysis — separate from the served payload, queried only by maintainers.

### ADR-013: Calibration auto-gate — a Python job evaluates each forecast against holdout coverage and flips `is_published`
- **Status**: accepted (2026-05-21) — resolves the open quality-gate question in ADR-006
- **Context**: ADR-006 left `is_published` as a manual flip, deferring the gate decision. For a forecast that updates weekly → daily → hourly, manual gating drifts: someone forgets, or rationalises a marginal failure under deadline pressure. Recommendation #8 in `docs/requirement.md` ("≥95% credible intervals cover truth ≥95% of the time on holdouts") is exact enough to mechanise.
- **Decision**: A `pipeline/scripts/calibrate.py` job runs immediately after each successful forecast `NOTIFY`. It re-runs the model against the 2019 and 2023 holdouts using the *same configuration*, computes coverage statistics, and sets `is_published = TRUE` only if all the following pass:
  - **C1**: 80% credible interval covers truth in ≥80% of `(holdout_cycle × candidate)` pairs.
  - **C2**: 95% credible interval covers truth in ≥95% of pairs.
  - **C3**: Median absolute error on top-3 candidates ≤ 5 pp (presidential), ≤ 3 pp on congressional seat counts, ≤ 7 pp on municipal vote shares.
  - **C4**: No NaN, no Inf, no all-zero quantile vectors in `payload`.
  - **C5** (presidential): runoff-matrix probabilities sum to 1.0 ± 1e-6 and every entry ∈ [0, 1].
  - Failures emit a `calibration_failures (run_id FK, gate, observed_value, threshold, failed_at)` row; the forecast stays unpublished.
  - A manual override script `pipeline/scripts/force_publish.py --run-id X --reason "..."` exists for ops emergencies (e.g., intervention applied, want to publish before the next gate cycle). Every override writes `calibration_overrides (run_id FK, reason TEXT NOT NULL, operator TEXT NOT NULL, created_at TIMESTAMPTZ)`.
- **Consequences**: Forecast cadence becomes fully automated — the API serves the latest auto-gated run with no human in the loop on routine days. Calibration becomes a first-class build step that fails loudly. The `force_publish` path is intentionally separate and audited because publishing a forecast is implicit legal endorsement by the maintainer; that endorsement must remain explicit.

### ADR-012: Result grain — municipality is the common backfill grain; mesa-level is opportunistic only
- **Status**: accepted (2026-05-21) — refines `docs/requirement.md` recommendation #6
- **Context**: Finer-grained training data tightens hierarchical priors (more variance estimates, better partial pooling). The cleanest signal is mesa-level (~122k actas in 2023). But bulk-downloading TREP per-mesa actas is operationally prohibitive: no bulk endpoint, ~1 MB per PDF, ~122k requests at rate-limit-respecting cadence (~1 req/sec + 5 s jitter) ≈ 2–3 weeks of solid scraping plus ~120 GB of PDF storage. TREP is being retired for 2027 anyway. Meanwhile, `resultados2019.tse.org.gt` exposes municipality-level data via "Datos abiertos: Excel" — clean, fast, consistent.
- **Decision**: Schema admits mesa-level (`geographies.level='mesa'`), but **backfill targets municipality** (and department / district where the source data lives there). Mesa-level rows load *only* when the data is bulk-extractable from an existing Excel/CSV/open-data dataset — never via per-PDF scraping at scale. The presidential model fits at the lowest *consistently available* grain across cycles, which is municipality. Honest uncertainty from looser data → wider posteriors → *better-calibrated* coverage, which is itself an accuracy win at the calibration gate (ADR-013).
- **Consequences**: ETL writers default to municipality grain. The Phase 1 TREP-per-mesa task in `docs/requirement.md` is dropped. Future mesa-rich datasets (e.g., TSE's 2027 replacement system if it ships machine-readable mesa data) can be ingested with no schema change.

### ADR-011: Sentiment pipeline ships with presidential v1, not deferred
- **Status**: accepted (2026-05-21) — chosen over the deferral recommendation
- **Context**: `docs/requirement.md` treats sentiment as "a feature into the fundamentals layer, not as a primary signal" — useful for trend detection late-cycle. Argued for deferral to v1.5 alongside congressional: presidential model functions on poll aggregator + fundamentals alone, and an unvalidated sentiment pipeline that swings the published forecast is a calibration risk (recommendation #8). Counter-decision: ship sentiment with v1 anyway. Reasons accepted: late-cycle trend signal value is highest *in* the final 2–3 months pre-election, which is exactly when presidential v1 is live; building the pipeline once and using it across all three race layers later is cheaper than rebuilding for v1.5.
- **Decision**: Full sentiment pipeline is a v1 launch dependency.
  - **News ingestion** (Go): RSS scrapers for the ~10 outlets in `docs/requirement.md` Section B (Prensa Libre, La Hora, Soy502, Plaza Pública, Publinews, Emisoras Unidas, República, AGN, Guatemala.com; plus Diario de Centro América via scrape). Writes `news_articles (article_id, source, url UNIQUE, published_at, title, body_text)`.
  - **Sentiment inference** (Python): `pysentimiento` (BETO base) on a systemd timer; FP32 first (16 GB allows it), INT8 quantization only if throughput becomes the bottleneck. Writes `sentiment_scores (article_id, subject_kind ENUM('candidate','party','overall'), subject_id NULL, score NUMERIC, label ENUM('POS','NEG','NEU'), model_version)`.
  - **Entity resolution** (Python): name-to-`candidate_id` and name-to-`party_id` linker. Initial implementation: gazetteer of canonical names + aliases from `party_aliases` and a `candidate_aliases` analogue; fuzzy match with accent normalization (`unicodedata.normalize('NFKD', …)`). Validated against a hand-labeled set of ~500 Guatemalan political headlines before v1 launch.
  - **Calibration gate**: sentiment is included in the fundamentals layer *only* if backtests on 2019 + 2023 show its inclusion does not worsen presidential coverage. If it does, schema and pipeline still ship, but the modelling weight goes to zero at launch.
- **Consequences**: Adds entity-resolution work and a 500-headline labeling task to the v1 critical path. Adds the `news_articles` + `sentiment_scores` tables and `candidate_aliases` table to the schema. Sentiment becomes a published-forecast input from day one — calibration tests must include "with vs without sentiment" coverage comparisons before flipping `is_published`. If the calibration gate fails, sentiment ships as a *displayed* trend feature on the methodology page without being a *modelled* input.

### ADR-010: `goose` owns all schema migrations; one source of truth
- **Status**: accepted (2026-05-21)
- **Context**: Both Go and Python read/write the same Postgres database. Two migration tools (Go's `goose`, Python's `alembic`) would create drift risk, double-tracking of sequence numbers, and ambiguous ownership of shared tables. The Python pipeline does not use SQLAlchemy (per ADR-001 stdlib-first inclinations — raw `psycopg` is the planned driver), so `alembic`'s ORM-aware migration generation has no upside here.
- **Decision**: All DDL lives in `migrations/` at the repo root and is managed by `pressly/goose`. Plain SQL `up`/`down` files. Both Go and Python apply the same schema; only Go (or anyone editing a migration file) creates new ones. Go's `cmd/api` runs `goose up` on startup against the configured `DATABASE_URL`. Python applies migrations via the same `goose` binary in CI / setup scripts — no Python-side migration code.
- **Consequences**: Python-driven schema needs route through a SQL migration file (no need to round-trip through a Go contributor — anyone can write the SQL). Schema versions align 1:1 with the migration sequence number. CI gate: every PR that touches `migrations/` must include both `up` and `down` files. The `down` rollback is for emergencies only; we don't enforce reversibility at code-review time beyond "it exists."

### ADR-009: Party identity is single `party_id` per political identity; status + aliases carry the timeline
- **Status**: accepted (2026-05-21)
- **Context**: Guatemalan parties cancel, rename, re-register, and (rarely) reuse names. Eleven 2023 parties were cancelled by the Registro de Ciudadanos; Movimiento Semilla's cancellation is `vigente bajo apelación`. Two modeling viewpoints conflict: TSE's *legal* view treats each registration episode as a distinct legal person; the *modelling* view treats Semilla as Semilla across registrations. The schema has to satisfy modelers without losing the legal facts.
- **Decision**: One stable `party_id` per political identity. Renames are alias rows. Cancellation is metadata on the same row. Per-cycle eligibility is its own table.
  - `parties (party_id PK, name, tse_code, status, cancelled_at NULL, predecessor_party_id NULL)` — `status ∈ {active, cancelled, cancelled_under_appeal, dissolved}`.
  - `party_aliases (party_id FK, alias_name, valid_from, valid_to)` — handles renames and historical labels without changing identity.
  - `party_eligibility (party_id, cycle, is_eligible BOOLEAN, source TEXT)` — captures Semilla's 2027 flag cleanly and generalizes to future cancellations.
  - When a *new* legal entity adopts an old name (rare; would be e.g. an unrelated future "Partido Republicano"), it gets a new `party_id` with `predecessor_party_id` set for analyst clarity.
- **Consequences**: Modeling queries can `JOIN parties ON party_id` without lineage UNIONs. Movimiento Semilla's flip-flop is a single row update in `party_eligibility`. The legal-view consumer can still reconstruct registration episodes from `status` + `cancelled_at` + audit logs. The trade-off accepted: we lose 1-to-1 alignment with TSE's `personalidad jurídica` numbering — by design.

### ADR-008: Three fact tables for historical results, shared dimensions
- **Status**: accepted (2026-05-21) — refines the single-`results`-table sketch in `docs/requirement.md` recommendation #1
- **Context**: A single `results` table forces nullable FKs (`candidate_id` is meaningless for congressional rows, `seats` is meaningless for presidential rows, `slate_votes` is meaningless everywhere except municipal) and runtime discriminators on every query. The three race types have genuinely different keys: presidential is candidate-centric, congressional is party-centric over districts, municipal is party-centric over municipalities with separate alcalde/concejales/síndicos counts.
- **Decision**: Three race-specific fact tables, shared dimensions.
  - **Dims**: `elections (election_id PK, cycle, round)`, `parties (party_id PK, name, tse_code, status, cancelled_at NULL)`, `party_aliases (party_id FK, alias_name, valid_from, valid_to)`, `candidates (candidate_id PK, full_name, sex, wikidata_qid NULL)`, `candidate_party (candidate_id FK, party_id FK, cycle)`, `geographies (geography_id PK, level ENUM('country','department','district','municipality','mesa'), code, name, parent_id NULL)`.
  - **Facts**:
    - `presidential_results (election_id, candidate_id, geography_id, votes) PK(all 3)`
    - `congress_results (election_id, district_id, party_id, votes, seats) PK(election_id, district_id, party_id)`
    - `municipal_results (election_id, municipality_id, party_id, alcalde_votes, alcalde_won, concejales_seats, sindicos_seats) PK(election_id, municipality_id, party_id)`
- **Consequences**: Cross-race-type queries (e.g., "all parties' national vote-share trend") need a `UNION`-based view. Acceptable — those reads are not hot. The strong typing pays off in ETL: each PDF parser writes to exactly one fact table, and a wrong column type fails fast at load time instead of producing silently malformed JOIN keys.

### ADR-007: Models ship staged — president → congress → municipal — never big-bang
- **Status**: accepted (2026-05-21) — refines the `docs/requirement.md` Phase 3 milestone
- **Context**: `docs/requirement.md` Phase 3 says "first public-facing forecast published, ~5 months before election day," implying all three layers (presidential, congressional, 340 municipals) launch together. Recommendation #8 in the same document is non-negotiable: "Don't publicize the forecast until backtesting shows ≥95% credible intervals actually cover the truth ≥95% of the time on the 2019 and 2023 holdouts." These two constraints conflict — calibration difficulty is wildly uneven across the three layers. Presidential has 5 historical cycles and abundant polls. Municipal has thin per-unit history across 340 races and almost no per-race polling. If we gate launch on the slowest-to-calibrate model, launch slips into the legal-risk zone or the calibration bar quietly slips instead.
- **Decision**: Stage the public launch by race layer.
  - **v1 (target Jan–Feb 2027)**: presidential only — two-round simulator, violin plot of first-round posterior. Launch when 2019 + 2023 holdout coverage ≥95%.
  - **v1.5 (target Mar–Apr 2027)**: add congressional layer (23 districts + Nacional, hierarchical multinomial + Go D'Hondt). Launch when congressional holdout coverage ≥95%.
  - **v2 (target May 2027 or post-election)**: add municipal partial-pooling layer. If municipal won't calibrate by mid-May 2027, ship a deterministic "2023 baseline + incumbency tilt" placeholder on the municipal pages with an explicit "no probabilistic forecast — see methodology" banner, and publish full posteriors after the post-mortem.
- **Consequences**: The schema must still handle all three layers from Phase 1 onward (historical backfill is for all levels regardless). The UI ships in three releases. The methodology page is updated each release with what's now covered. The Android app needs feature flags for the not-yet-launched layers — the API returns `404` for race types that aren't live yet, and the app gracefully hides those screens. Acceptable cost; the alternative (delaying launch until municipal calibrates) is worse — it courts both legal risk (publishing closer to the blackout) and reputational risk (recommendation #8).

### ADR-006: Forecast IPC is cron + `forecasts` snapshot table + `LISTEN/NOTIFY`
- **Status**: accepted (2026-05-21) — supersedes the SQLite "predict_request" jobs queue in `docs/requirement.md`
- **Context**: `docs/requirement.md` proposed a SQLite jobs table where Go writes `predict_request` rows and Python polls every 30s. Forecasting in this project is scheduled work, not request/response — the cadence is weekly during quiet phases, daily as polls intensify, hourly on election night. A jobs queue adds a polling loop and a job protocol with no business benefit. Postgres provides `LISTEN/NOTIFY` for free, which is a real pub/sub primitive — fitting for "fresh forecast available, invalidate caches."
- **Decision**:
  - **Schema**: `forecasts (run_id UUID PK, model_version TEXT, generated_at TIMESTAMPTZ, race_type TEXT, payload JSONB, is_published BOOLEAN DEFAULT FALSE)`.
  - **Producer**: Python ML worker is a systemd timer one-shot. Each run computes posteriors, inserts a row, then `NOTIFY forecast_ready, '<run_id>'`, and exits. RAM is fully reclaimed between runs.
  - **Consumer**: Go API serves `/forecast/*` from the latest `is_published = TRUE` row per `race_type`, behind a 5-minute in-process LRU. A background goroutine holds an idle Postgres connection on `LISTEN forecast_ready` and clears the cache on notification.
  - **Quality gate**: `is_published` defaults to `FALSE`. A human (or a calibration job — to be decided in a later ADR) flips it after coverage checks pass. Recommendation #8 in `docs/requirement.md` ("don't publicize until ≥95% credible intervals cover truth ≥95% of the time on holdouts") is the criterion.
- **Consequences**: No always-on Python process. No on-demand `/forecast` recompute (use `systemctl start polityk-forecast.service` from the CLI if you need an ad-hoc run after a manual intervention). The LISTEN/NOTIFY goroutine needs a reconnect-on-drop loop — write it once, test it with a `pkill postgres` chaos test.

### ADR-005: PostgreSQL is the single datastore — no SQLite, no DuckDB
- **Status**: accepted (2026-05-21) — supersedes the SQLite + DuckDB split in `docs/requirement.md`
- **Context**: `docs/requirement.md` Section D argued against Postgres because it assumed a Celeron / 4 GB host where Postgres' ~250 MB resident overhead was prohibitive. The actual host is a 2024 IdeaPad with Ryzen 7000 and 16 GB RAM, which the original document itself flagged as a benchmark threshold ("If RAM upgrades to 16 GB+ → consider PostgreSQL primary"). The memory argument no longer applies.
- **Decision**: Single PostgreSQL instance on the IdeaPad handles both OLTP (scrapes, polls, news, results) and analytical workloads (model-feature joins, backtests). DuckDB is dropped — Postgres' window functions, CTEs and parallel sequential scans cover the analytical queries this project actually runs (340 municipios × ~28 parties × 6 cycles is not a "big data" workload). Driver: `database/sql` + `jackc/pgx/v5/stdlib` from Go; `psycopg[binary]` from Python.
- **Consequences**: One backup story (`pgbackrest` or `wal-g` shipping to Cloudflare R2), one connection pool, one migration system (`goose` — see ADR-010). The "Why NOT PostgreSQL" paragraph and the SQLite/DuckDB rows in `docs/requirement.md` are now stale; treat `CONTEXT.md` as authoritative. If a future analytical workload truly needs columnar performance (e.g., millions of acta rows), revisit DuckDB-as-embedded-library at that time — don't pre-optimize.

### ADR-004: Hybrid scraping — Go for HTTP/HTML/RSS, Python for PDFs/Trends/Sentiment
- **Status**: accepted (2026-05-21) — supersedes the Go-only scraping plan in `docs/requirement.md`
- **Context**: `docs/requirement.md` originally proposed Go-only scraping (Colly v2 + chromedp + gofeed). `CLAUDE.md`'s pipeline conventions list all scraping libraries under Python (`requests`, `pdfplumber`, `camelot-py`, `feedparser`, `pytrends`). PDF parsing, Google Trends and Telegram are Python-only ecosystems; HTML/JSON/RSS scraping is equally well-served by Go's Colly + `mmcdole/gofeed` and avoids running a Python interpreter just to fetch a feed.
- **Decision**: Split scrapers by source type.
  - **Go (`internal/scrapers/`)**: HTTP/JSON APIs, HTML pages, RSS feeds — TSE HTML, padrón pages, Prensa Libre/La Hora/Soy502 RSS, Wikidata SPARQL, INE/SEGEPLAN/MINFIN open data, Reddit JSON, YouTube Data API, Wikipedia API.
  - **Python (`pipeline/scrapers/`)**: PDFs (Memorias Electorales, CID Gallup poll reports), `pytrends` (Google Trends), `telethon` (Telegram public channels), Bluesky firehose if added.
  - Both write to the same PostgreSQL database (see ADR-005).
- **Consequences**: Two scraping codebases means two rate-limiter implementations, two User-Agent policies, two cookie jars — accepted cost because each language owns the libraries it does best. The rule for new scrapers: if the source needs a Python-only library, it goes in `pipeline/scrapers/`; otherwise it goes in `internal/scrapers/`. Don't fork further.

## Constraints & Non-Negotiables

- **Hardware**: IdeaPad (2024 model), **AMD Ryzen 7000-series, 16 GB RAM**. CPU-only inference (integrated Radeon iGPU not used; ROCm setup is brittle and not worth the maintenance). Model wall-clock budgets still documented per-model in docstrings — the Ryzen is fast enough that wall-clock is the limit, not RAM.
- **Legal**: 36-hour blackout enforced server-side. See ADR-003.
- **Data sources**: TSE returns 403 to bare scrapers — every scraper sends a real-browser User-Agent. 2023 Memoria Electoral not yet published. TREP will be replaced for 2027 (system unknown).
- **Social media**: No Twitter/X scraping (ToS forbidden, free API gone). Sentiment inputs: RSS + Reddit + Bluesky + YouTube comments only.
- **Rate limits**: `pytrends` requires 60s sleep when throttled, 3–5s minimum between requests always.
- **Party state**: 28 active parties (early 2026 TSE data). 11 of 2023's parties cancelled. Movimiento Semilla's cancellation is "vigente" but under appeal — runtime flag.
- **Stdlib-first** per ADR-001.

## Operational Commitments

Concrete decisions made during the 2026-05-21 `/grill` session that aren't architectural enough to warrant a standalone ADR but lock in *how* the system behaves. Promote any of these to an ADR if a real challenge later requires explicit justification.

### Backfill ordering (Phase 1, Jun–Aug 2026)
1. **2019 end-to-end first** — use `resultados2019.tse.org.gt` "Datos abiertos: Excel" exports. Cleanest source; lets the schema, ETL, and Go D'Hondt simulator iterate against known ground truth.
2. **2007, 2011, 2015** — Memoria Electoral PDFs via `pdfplumber` + `camelot`. Heavy lift; each cycle a milestone.
3. **2023 (provisional)** — TREP aggregates + TSE press-release totals (Acuerdos 1659-2023 / 1361-2023). Re-ingest the 2023 Memoria when published.

### PyMC sampling configuration (all model layers per ADR-007)
- **Sampler**: NUTS with the NumPyro backend.
- **Chains**: 4 in parallel (Ryzen 7000 has the cores).
- **Samples**: 2000 warmup + 4000 post-warmup per chain → 16k total per forecast.
- **`target_accept`**: 0.95 (tighter than the default 0.8). Election-share posteriors are well-behaved enough that the cost is small and divergence risk drops.
- **Diagnostics gate**: every monitored quantity must satisfy `r_hat < 1.01` and `bulk_ess > 400`. Failure trips a C6 check in the ADR-013 calibration gate and the run stays unpublished.

### Polls scope
- **In-scope pollsters**: CID Gallup, ProDatos (Encuesta Libre via Prensa Libre), Borge y Asociados, Fundación Libertad y Desarrollo. Each gets a row in `pollsters` with the ADR-017 bias prior.
- **Aggregator cross-check**: Wikipedia opinion-polling page for 2027, via the Wikipedia API (not scraped) once it appears.
- **New mid-cycle pollsters**: ingested with the diffuse default prior `(0, 0.05)`; bias only updates after they accrue a fitted history.

### Fundamentals-layer features (presidential v1)
- Incumbent-party indicator (binary).
- Party-of-government performance penalty (continuous; derived from approval-rating proxies).
- Real GDP growth YoY (Banguat).
- Inflation YoY (Banguat / INE).
- Remittance-inflow growth YoY (Banguat).
- Security indicator: homicide-rate change YoY (INE).
- Sentiment trend: rolling 30-day differential POS-NEG share per candidate from the ADR-015 materialised view.
- Polling-environment flag: pre/post candidate-list finalisation.

### Forecast update cadence
- **Through Jan 2027**: weekly run, Sunday 18:00 local. Calibration backtests run weekly.
- **Feb–May 2027**: daily run, 06:00 local.
- **Jun 2027 (election month, outside blackout)**: hourly.
- **Election day after polls close (outside blackout)**: switch the API into "results-tracking" mode — a separate code path showing live TSE results overlaid against the most recent published forecast. Not a "forecast" — explicitly labelled as results-tracking in the methodology page.
- **Blackout windows**: no forecast runs at all; the `BLACKOUT_ENABLED` flag (ADR-003) short-circuits the API and the scheduler is paused via the same systemd timer that flips the flag.

## ADR Archive

<!-- Superseded ADRs compressed to one-line summaries.
     Format: ADR-NNN: {title} — superseded by ADR-NNN ({date}) -->
