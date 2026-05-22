# PRD: v1 Presidential Forecast Platform

*Status: draft · Author: maintainer + Claude Opus 4.7 (1M context) · Date: 2026-05-21 · Branch: `prd/v1-presidential-platform`*

This PRD synthesises the architecture and scope decisions ratified during the 2026-05-21 `/grill` session (ADRs 001–019 + Operational Commitments in `CONTEXT.md`). It defines what ships at v1 and what is deliberately deferred to v1.5 (congressional) and v2 (municipal).

## Problem Statement

A Guatemalan voter checking polls a month before the 2027 first-round election has no neutral, calibrated, probabilistic forecast in Spanish from a credible source. They can read individual polls in the press — but each poll's methodology, sample, and house-effect history is opaque, and a single CID Gallup or ProDatos number is presented as point-estimate fact even though Guatemalan polling missed Arévalo by ~12.6 percentage points in 2023. They have no single place to see the *posterior distribution* of likely outcomes with honest uncertainty bounds, no way to compare candidate trajectories across pollsters, and no way to understand how late-cycle disqualifications shift the picture. The information asymmetry favours partisan media and well-resourced campaigns.

Journalists and analysts face the same gap from the producer side: they want to cite *something* with calibration evidence, but there is no Guatemalan equivalent of FiveThirtyEight or The Economist's election model.

The Constitutional Court ruling on expediente 1699-2018 bans publishing forecasts in the 36 hours before each round — meaning whatever solution exists must be both *accurate enough to be useful when it's online* and *operationally trustworthy enough to go dark on schedule, every time, no exceptions*.

## Solution

A free, public-facing Android app backed by a Go JSON API that publishes a calibrated probabilistic forecast for the 2027 Guatemalan presidential race. Updated weekly through January 2027, daily through May, and hourly during election month. The forecast is produced by a Bayesian hierarchical model (poll aggregator + fundamentals + sentiment-trend) implemented in PyMC, calibrated against 2019 and 2023 holdouts before any run is published, and gated by an automated coverage check that prevents publication when calibration regresses. A separate `interventions` table lets a maintainer ratchet a disqualified candidate's posterior to zero between scheduled runs.

Users see honest uncertainty: 80% and 95% credible-interval ranges per candidate, win probabilities for both rounds, a runoff-matchup matrix, freshness stamps, and — when stale — graduated banners that warn them the data is old without locking them out. During the legal blackout the API short-circuits all forecast routes to `503` and the app renders a Spanish-language blackout splash; cached forecasts are never shown during blackout.

The system is designed to extend to congressional (v1.5) and municipal (v2) forecasts without schema migration churn — dimension tables, scrapers, and historical backfill scope all three race layers from day one, even though only presidential is published in v1.

## User Stories

1. As a Guatemalan voter, I want to see each presidential candidate's vote-share distribution as a density/violin plot, so I can grasp uncertainty rather than a single number.
2. As a Guatemalan voter, I want 80% and 95% credible intervals on every candidate's projected vote share, so I can tell the difference between "likely" and "merely possible."
3. As a Guatemalan voter, I want each candidate's probability of qualifying for the runoff, so I understand which matchups are realistic.
4. As a Guatemalan voter, I want a matrix of plausible runoff pairings with each side's conditional win probability, so I can reason about second-round dynamics.
5. As a Guatemalan voter, I want a "last updated" timestamp on every forecast view, so I know how fresh the data is.
6. As a Guatemalan voter using the app offline, I want to see my last cached forecast with a graduated freshness banner (green/yellow/red), so I can still get value during network gaps without being misled.
7. As a Guatemalan voter opening the app during the legal blackout window, I want a clear Spanish-language explanation that forecasts are paused by law, so I am not confused or shown stale data.
8. As a Guatemalan voter on a low-end Android phone (8.0+), I want the app to install and load fast, so I am not excluded for hardware reasons.
9. As a journalist citing the forecast, I want a stable URL contract (`/v1/forecast/presidential`) and an unambiguous JSON shape, so my tooling does not break across publication cycles.
10. As a journalist citing the forecast, I want a methodology page linked from every payload, so I can attribute the model and disclose its assumptions.
11. As a journalist, I want every published run to carry a `model_version` and `run_id`, so I can pin a citation to an exact snapshot.
12. As a political analyst, I want pollster house-effects estimated from historical performance, so polls that have systematically missed (e.g., ProDatos in 2023) are appropriately down-weighted.
13. As a political analyst, I want each pollster's bias prior surfaced on the methodology page, so I can audit the aggregator's weights.
14. As a political analyst, I want a record of every intervention (disqualification, withdrawal, manual override) attached to the forecast that applied it, so I can reconstruct *why* a posterior shifted.
15. As a political analyst, I want full posterior samples archived (not just summary quantiles), so I can run downstream analyses.
16. As the maintainer publishing the forecast, I want the calibration gate to automatically refuse to publish a forecast whose 2019/2023 holdout coverage falls below threshold, so my credibility is protected by code, not memory.
17. As the maintainer, I want a force-publish escape hatch that requires a `--reason` and writes an audit row, so genuine emergencies can ship while remaining defensible.
18. As the maintainer, I want a CLI to insert an `interventions` row (with required `--reason` and `--operator`), so applying a disqualification is a deliberate, audited act.
19. As the maintainer, I want a separate `run_kind = 'whatif'` flag, so I can sanity-check the model without affecting published output.
20. As the maintainer, I want the API to enforce the blackout flag server-side rather than relying on the client clock, so I cannot accidentally publish during the silencio electoral.
21. As the maintainer, I want a manual blackout override script with logged usage, so DST or clock-skew emergencies have a documented escape.
22. As the maintainer, I want every forecast publication audit-logged (`run_id`, `model_version`, `generated_at`, who/what flipped `is_published`), so any future legal complaint is answerable.
23. As the ETL author, I want the historical backfill to start with 2019 (clean Excel exports) and iterate the schema against that ground truth before tackling Memoria PDFs, so the schema is hardened before the heaviest extraction.
24. As the ETL author, I want each scraper rate-limited and User-Agent-identified per ADR-004, so we respect each source's `robots.txt` and don't trigger 403s.
25. As the ETL author, I want PDF extraction to fail loudly with a typed error when a table layout changes mid-document, so I notice schema drift early.
26. As the ETL author, I want news ingestion to capture full article body text, so sentence-level sentiment scoring per ADR-015 has the material it needs.
27. As the modeller, I want a Linzer/Kremp state-space poll-aggregator whose pollster-bias priors are fed from `pollsters.historical_bias_mean/sd`, so the model uses the bias estimates instead of ignoring them.
28. As the modeller, I want a fundamentals-layer regression on incumbency, GDP growth, inflation, remittances, security, and sentiment-trend, so the model has a non-poll backbone for sparse-polling periods.
29. As the modeller, I want the presidential combiner to produce a posterior over first-round vote shares, then Monte Carlo simulate 10k+ first rounds and conditionally simulate runoffs using a learned second-round swing matrix, so the runoff matrix is empirically grounded.
30. As the modeller, I want every model run to write its full posterior to `posterior_archives` alongside the summary in `forecasts.payload`, so I can replay calibration checks later.
31. As the modeller, I want PyMC NUTS configured with NumPyro backend, 4 chains, 2000 warmup + 4000 samples, `target_accept=0.95`, and `r_hat < 1.01` / `bulk_ess > 400` diagnostics enforced via the calibration gate, so divergent runs cannot publish.
32. As the modeller, I want intervention rows to be applied as posterior-level transformations (zero-out + renormalise, or replace-marginal-with-delta + renormalise siblings), so the math stays principled rather than ad-hoc.
33. As the modeller, I want sentiment to be optional in the published model — included only if the "with vs without sentiment" backtest shows it doesn't worsen coverage — so an unvalidated input never silently degrades the forecast.
34. As the sentiment-pipeline author, I want per-sentence × per-entity scoring (not article-level), so an article that praises one candidate and criticises another generates distinct features for each.
35. As the sentiment-pipeline author, I want a Spanish NER tokeniser (spaCy `es_core_news_sm`) plus a gazetteer of canonical names + aliases, so entity resolution handles "Arévalo", "Bernardo Arévalo", and "el candidato de Semilla" consistently.
36. As the sentiment-pipeline author, I want a labelled validation set of ~500 Guatemalan political headlines, so accuracy is measurable before sentiment becomes a published-forecast input.
37. As the API consumer (Android), I want a single GET to `/v1/forecast/presidential` to return everything needed to render the screen, so I don't chain requests.
38. As the API consumer, I want `ETag` + `Cache-Control` headers, so Cloudflare and OkHttp cache responses correctly.
39. As the API consumer, I want a `cache_invalid_until` field, so I can be told to forcibly drop the local cache at the start of a blackout window.
40. As the API consumer, I want `404` for race types not yet live (per ADR-007 staging), so I can hide congress/municipal screens until v1.5 / v2 ship.
41. As the API consumer, I want `503` to mean "blackout — show the splash", with the splash content living in the app (not in the response body), so a malicious upstream cannot inject content.
42. As the operator, I want `pgbackrest` / `wal-g` continuous backups shipped to Cloudflare R2, so a laptop failure does not lose a year of scraped data.
43. As the operator, I want systemd timers driving each scraper, the forecast worker, the calibration job, and the blackout flag flips, so the system has no always-on Python daemon and RAM is reclaimed between runs.
44. As the operator, I want a `/v1/health` endpoint reporting DB connectivity, last successful forecast timestamp, last scrape timestamps per source, and current blackout flag state, so an external uptime checker has a single fact.
45. As the operator, I want ERROR-level logs tailed and pushed to a Discord/Telegram webhook, so failures during the election week are seen immediately.

## Implementation Decisions

### Architectural anchors

- Three-stack project: Go API + Python ML pipeline + Kotlin Android client. Every decision below traces to an ADR in `CONTEXT.md` (001–019).
- Storage: single PostgreSQL instance on the IdeaPad (Ryzen 7000 / 16 GB) per ADR-005. No SQLite, no DuckDB.
- Forecast coupling: cron-driven Python writes a `forecasts` row, then `NOTIFY forecast_ready`; Go API `LISTEN`s and invalidates a 5-minute LRU per ADR-006.
- Scraping split: Go owns HTTP/JSON/HTML/RSS sources; Python owns PDFs, `pytrends`, `telethon`, Bluesky per ADR-004.
- Public client is Android-only in v1 per ADR-002.
- Blackout enforced server-side via `BLACKOUT_ENABLED` env-var middleware per ADR-003.
- Stdlib-first across all three stacks per ADR-001.

### Module sketch (deep, testable, paths intentionally omitted)

These are the major modules. Each encapsulates one concern behind an interface that rarely changes; each is built to be unit-tested in isolation.

1. **Schema (DDL only)** — All Postgres tables managed by `goose` migrations per ADR-010. Dimensions: `elections`, `parties`, `party_aliases`, `party_eligibility`, `candidates`, `candidate_aliases`, `candidate_party`, `geographies`, `pollsters`. Facts: `presidential_results`, `congress_results` (with `chamber` discriminator per ADR-016), `municipal_results`, `polls`, `poll_responses`, `poll_errors`, `news_articles`, `social_posts`, `sentiment_scores`. Operational: `forecasts`, `posterior_archives`, `calibration_failures`, `calibration_overrides`, `interventions`. One migration per PR; both `up` and `down` SQL.

2. **D'Hondt allocator** — Pure Go function. Inputs: a vote-count map and a seat count. Output: a seat-count map, deterministic, ties broken by party order. The single allocation primitive in the codebase. Used at fit time by the congressional model in v1.5 — still implemented in v1 so the `congress_results.seats` column is correctly populated during historical backfill.

3. **Go scrapers** — One package per source. Common interface: `Run(ctx) error` writing into the canonical schema. Rate-limited, User-Agent-identified, idempotent on URL uniqueness. Sources in scope for v1: TSE HTML (party lists, padrón), RSS aggregator (10 outlets), Wikidata SPARQL, INE/SEGEPLAN/MINFIN open-data portals, Reddit JSON, YouTube Data API v3, Wikipedia API.

4. **Python scrapers** — Same interface contract as Go scrapers. Sources: Memoria Electoral PDF extractor (`pdfplumber` + `camelot`), CID Gallup PDF parser, Google Trends (`pytrends`), Telegram (`telethon`), Bluesky firehose.

5. **Entity resolver** — Python module mapping mention strings to `candidate_id` / `party_id` via gazetteer + `party_aliases` + `candidate_aliases` with accent-normalised fuzzy matching. Used by the sentiment pipeline. Validated against the 500-headline labelled set before launch.

6. **Sentiment scorer** — Python module wrapping spaCy `es_core_news_sm` (sentence split + NER) and `pysentimiento` BETO. Writes per-(`source_kind`, `source_id`, `sentence_index`, `subject_id`) rows to `sentiment_scores`. A materialised view aggregates to per-source × per-subject for model consumption.

7. **Pollster bias estimator** — Periodic PyMC script that fits `error_ij ~ Normal(bias_i, sigma_i)` per pollster across historical `(candidate, cycle)` pairs and writes posterior mean/sd back to `pollsters`. Runs once per cycle as truth lands.

8. **Modelling layer** — PyMC under `pipeline/models/`:
   - **Poll aggregator**: Linzer/Kremp state-space; accepts pollster bias priors from `pollsters`.
   - **Fundamentals**: regression on incumbency, GDP growth, inflation, remittances, security, sentiment-trend.
   - **Presidential combiner**: weighted combination of (1) and (2); Monte Carlo simulates 10k+ first rounds and conditionally simulates runoffs via a learned second-round swing matrix from 2007/2011/2015/2019/2023.
   - Congressional and municipal model stubs exist per ADR-007 but are not exercised in v1.

9. **Intervention applier** — Python module that reads active interventions from the DB and applies posterior-level transformations (zero-out + renormalise, or delta-replace + renormalise siblings). Called by the modelling layer before payload generation.

10. **Forecast writer** — Python module that takes the modelling layer's posterior, computes quantile summaries per the API contract, writes `forecasts` + `posterior_archives` rows, and emits `NOTIFY forecast_ready`.

11. **Calibration gate** — Python script per ADR-013. Re-runs the model against 2019 and 2023 holdouts, computes the C1–C6 coverage checks, flips `is_published = TRUE` on pass, writes `calibration_failures` rows on fail.

12. **Go API** — `cmd/api/` + `internal/handlers/`. Endpoints per ADR-014: `/v1/forecast/presidential`, `/v1/forecast/congress` (404 in v1), `/v1/forecast/municipal/{id}` (404 in v1), `/v1/methodology`, `/v1/health`. Blackout middleware per ADR-003. 5-minute LRU cache invalidated via a `LISTEN forecast_ready` goroutine with reconnect-on-drop.

13. **Android app** — Kotlin / Compose / Hilt / Retrofit / Room. Presidential screen + methodology screen + blackout splash + freshness banners per ADR-018. Congress and municipal tabs are scaffolded but feature-flagged off (API returns 404, app hides tab).

14. **Operations** — Systemd timers (one per scraper, one for the forecast worker, one for the calibration job, one for the blackout flag flips), `pgbackrest`/`wal-g` to R2, ERROR-tailing webhook to Discord/Telegram.

### API, schema, and runtime contracts

- All DDL lives under `migrations/` and is managed by `goose` per ADR-010.
- API contract: versioned `/v1/forecast/*` with quantile payload per ADR-014. The JSON response body is stored directly in `forecasts.payload` (JSONB) so `SELECT payload FROM forecasts WHERE …` is literally the API body.
- Payload always carries `run_id`, `model_version`, `generated_at`, `interventions_applied`, and `methodology_url`.
- Posterior archives store full sample arrays in `posterior_archives` for retrospective work — never served via the public API.
- Standard headers: `ETag` on every response; `Cache-Control: public, max-age=300` outside election week, `max-age=60` during; `Content-Type: application/json; charset=utf-8`.
- Standard error codes: `503` for blackout, `404` for race types not yet live, `429` if rate-limit triggers.

### Hard constraints

- Server-side blackout (ADR-003): every `/forecast/*` route returns `503` when the flag is on; client never trusts device clock.
- TSE scrapers (Go) spoof a real-browser User-Agent or get 403'd.
- No Twitter/X scraping; no Facebook page-content scraping. Sentiment input set is fixed per ADR-015.
- Mesa-level results are *not* backfilled via the 122k-acta crawl per ADR-012.
- Movimiento Semilla 2027 eligibility is a runtime flag in `party_eligibility`.
- Sentiment-as-modelled-input is calibration-gated per ADR-011 — if it worsens holdout coverage, schema and pipeline still ship but modelling weight is zero at launch.

## Testing Decisions

### What "good" looks like

Tests verify *external behaviour* — what a module promises a caller — and are indifferent to whether the implementation changes. For our modelling and ETL code that means: black-box tests against fixture inputs with asserted outputs; integration tests that hit a real Postgres (not mocks); golden-file tests for stable JSON contracts; property-based tests where invariants are clear (D'Hondt monotonicity, posterior renormalisation summing to 1).

Tests must not assert on private function call counts, on intermediate logging, or on JSON key order. A test that breaks on refactor without a behaviour change is anti-signal.

### Modules with required test coverage at v1

1. **D'Hondt allocator** — table-driven Go unit tests against the 2019 and 2023 actual seat allocations for every district + the national list. The allocator must reproduce real-world seat counts exactly. Failure = schema or allocator is wrong; do not ship.

2. **Schema migrations** — `goose up`, `goose down`, `goose up` round-trip against a disposable Postgres in CI. Every PR touching `migrations/` runs this gate.

3. **PDF extractors** — Python tests per Memoria Electoral cycle, asserting extracted table totals match known cycle totals (e.g., 2019 first-round national vote total). Fail loudly when table layout drifts.

4. **Entity resolver** — Python tests over the 500-headline labelled validation set. Threshold: ≥95% correct entity attribution before sentiment can become a *modelled* input per ADR-011.

5. **Pollster bias estimator** — PyMC backtest: re-fit on 2007–2019 polls, predict 2023, assert that estimated biases would have correctly down-weighted ProDatos. Result documented on the methodology page.

6. **Presidential model** — Backtest harness implementing the C1–C5 checks of ADR-013 against 2019 and 2023 holdouts. The same harness is reused live by the calibration gate.

7. **Intervention applier** — Python unit tests with hand-built posteriors: assert that zero-out + renormalise sums to 1; assert that delta-replace + sibling-renormalise preserves total mass. Invariants, not specific numbers.

8. **Go API handlers** — `httptest` tests for blackout 503, race-type 404, valid forecast payload shape, ETag stability. A chaos test (`pkill postgres`) verifies the LISTEN/NOTIFY reconnect loop per ADR-006.

9. **Calibration gate** — End-to-end test: synthetic forecast with deliberately bad coverage → gate refuses to flip `is_published`; synthetic good coverage → gate flips. Both cases assert audit rows.

10. **Android UI** — Compose UI tests for the freshness-banner state machine (≤6 h / 6–24 h / 24–72 h / >72 h) per ADR-018. A separate test asserts a `503` renders the blackout splash and that cache reads never bypass it.

### Modules without required test coverage at v1

Scrapers and operational scripts ship with smoke tests only (a single happy-path run against a fixture HTML/RSS/PDF). Full coverage doesn't pay back — when a scraper breaks in production, the fix is a one-line selector update plus a fixture update, not a test rewrite.

### Prior art / inspiration

- The Linzer/Kremp poll-aggregation model has a PyMC reference at `github.com/fonnesbeck/election_pycast`; we can borrow its calibration-check structure for our backtests.
- `pressly/goose` ships canonical migration round-trip examples.
- `pysentimiento` publishes validation accuracy benchmarks we can match against our labelled-headline set.

There is no Guatemala-specific prior art for any of the modelling. Calibration baselines are established by our own backtests.

## Out of Scope

- **Congressional and municipal forecasts.** Per ADR-007, v1 publishes presidential only. Schema, scrapers, and historical backfill cover all three layers (so v1.5 and v2 don't need migrations), but no congress or municipal route ships in v1.
- **Mesa-level results backfill.** Per ADR-012, the 122k-acta TREP crawl is dropped. Mesa data is ingested only opportunistically from existing Excel/CSV/open-data exports.
- **Twitter/X and Facebook page content.** Per ADR-015, neither is scraped.
- **Web frontend.** Per ADR-002, Android is the only client in v1. Web access is via the JSON API directly.
- **iOS app.** Not in v1. Reconsider post-election if audience justifies it.
- **PARLACEN forecasts.** Results ingested via the `chamber` discriminator (ADR-016) but never modelled or surfaced in v1.
- **Authentication / user accounts.** API is public, read-only. No login, no per-user rate-limiting (Cloudflare absorbs traffic).
- **Push notifications.** Out of scope for v1.
- **Multi-language support.** v1 is Spanish-only.
- **Postgres failover replica.** Single-node Postgres on the IdeaPad. Backups to R2 are the recovery path.

## Further Notes

- **Calibration is the launch gate.** ADR-013's C1–C5 thresholds are the literal go/no-go. If 2019/2023 holdout coverage fails, the launch slips — there is no soft option. This protects credibility per `docs/requirement.md` recommendation #8.
- **The 2023 Memoria Electoral remains unpublished as of 2026-05.** v1 must handle a world where 2023 truth is provisional (TREP aggregates + Acuerdo 1659-2023 / 1361-2023). Schema and ETL treat 2023 as provisional and re-ingest the Memoria when it lands.
- **TREP's replacement system is unknown.** Monitor `tse.org.gt` quarterly. The Phase 5 results-tracking module is empty until the new system is announced (probably late 2026 or Q1 2027). Contingency: scrape TSE's preliminary HTML or partner with Mirador Electoral / Plaza Pública.
- **Movimiento Semilla eligibility is a runtime flag** in `party_eligibility`. Flipping the flag does not re-fit the model — the model reads it at fit time, so the next scheduled run incorporates the change.
- **Sentiment-as-modelled-input is calibration-gated.** Per ADR-011, sentiment must not worsen presidential holdout coverage. If it does, schema and pipeline still ship; modelling weight is zero at launch and sentiment becomes a *displayed* trend feature on the methodology page only.
- **Phase 1 backfill ordering** (2019 Excel → 2007/2011/2015 Memoria PDFs → 2023 provisional) is locked in the `CONTEXT.md` "Operational Commitments" section and gives the team time to harden the schema and PDF parsers before tackling the heaviest extraction.
- **Cross-references for future PRDs**: v1.5 (congressional) and v2 (municipal) will get their own PRDs that re-use the dimension tables, scrapers, and operational machinery established here.

## ADR References

| ADR | Decision |
|---|---|
| ADR-001 | Stdlib-first across all three stacks |
| ADR-002 | Public client is Kotlin Android, not Astro web |
| ADR-003 | Blackout enforced server-side, never by the client |
| ADR-004 | Hybrid scraping: Go for HTTP/HTML/RSS, Python for PDFs/Trends/Sentiment |
| ADR-005 | PostgreSQL is the single datastore — no SQLite, no DuckDB |
| ADR-006 | Forecast IPC = cron + `forecasts` snapshot table + `LISTEN/NOTIFY` |
| ADR-007 | Models ship staged — president → congress → municipal |
| ADR-008 | Three race-specific fact tables, shared dimensions |
| ADR-009 | Single `party_id` per political identity; status + aliases |
| ADR-010 | `goose` owns all schema migrations |
| ADR-011 | Sentiment pipeline ships with presidential v1, not deferred |
| ADR-012 | Backfill at municipality grain; mesa-level only opportunistic |
| ADR-013 | Automated calibration gate flips `is_published` |
| ADR-014 | API is `/v1/forecast/*` with quantile-based JSONB payload |
| ADR-015 | Sentiment grain is per-sentence × per-entity; 5 input streams |
| ADR-016 | PARLACEN via `chamber` discriminator; not modelled in v1 |
| ADR-017 | Pollster house-effects estimated from historical performance |
| ADR-018 | Android offline-cache: ≤72 h with escalating banners; blackout always wins |
| ADR-019 | `interventions` table allows posterior ratcheting on disqualification |
