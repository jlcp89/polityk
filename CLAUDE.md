# CLAUDE.md

## Project Overview

> **polityk** — Public platform forecasting Guatemala's 2027 General Elections. Ingests TSE, news RSS, polls, INE, and Google Trends into PostgreSQL; runs PyMC Bayesian hierarchical models (presidential two-round, 160-seat congressional D'Hondt, 340-municipality partial-pooling) and serves results through a Go JSON API consumed by a native Android app. Designed to run on a 2024 IdeaPad (Ryzen 7000-series, 16 GB RAM) behind a Cloudflare Tunnel.

| Attribute | Value |
|-----------|-------|
| **Type** | Fullstack (Go API + Python ML pipeline + Android client) |
| **Status** | Greenfield — planning + scaffolding phase (May 2026) |
| **Languages** | Go 1.22+ · Python 3.11+ · Kotlin 2.0 |
| **Election dates** | 1st round ~late June 2027 · runoff ~Aug 2027 |

## Repository Layout (planned)

```
polityk/
├── cmd/api/               # Go entry point — JSON HTTP API behind Cloudflare Tunnel
├── internal/              # Go private packages: scrapers/, dhondt/, store/, handlers/
├── pipeline/              # Python — scraping + ML pipeline
│   ├── scrapers/          # TSE, RSS, INE, Google Trends, polls
│   ├── parsers/           # pdfplumber/camelot extractors for Memoria Electoral PDFs
│   ├── models/            # PyMC: poll-aggregator, fundamentals, presidential, congress, municipal
│   └── scripts/           # train.py, evaluate.py, predict.py
├── android/               # Kotlin Android app — public consumer of /forecast endpoints
│   └── app/src/main/      # Jetpack Compose UI, Hilt DI, Retrofit, Room cache
├── data/                  # local PostgreSQL data dir + scrape cache (gitignored)
└── docs/requirement.md    # Architecture & implementation plan (read first)
```

## Tech Stack

### Go API (`cmd/api`, `internal/`)
| Layer | Choice |
|-------|--------|
| Language | Go 1.22+ |
| HTTP | `net/http` (stdlib first — third-party only with clear justification) |
| Database | PostgreSQL via `database/sql` + `jackc/pgx/v5/stdlib` (single datastore — see ADR-005) |
| Logging | `log/slog` (stdlib) |
| Config | Env vars via `os.Getenv` / `flag` |
| Tests | `testing` + `httptest` |

### Python ML Pipeline (`pipeline/`)
| Layer | Choice |
|-------|--------|
| Python | 3.11 |
| ML | PyMC 5 (Bayesian hierarchical) with NumPyro backend; NUTS, 4 chains parallel on Ryzen 7000 |
| Scraping | `pdfplumber` / `camelot-py` (PDFs) + `pytrends` (Trends) + `telethon` (Telegram) — see ADR-004 for the Python/Go split |
| Database driver | `psycopg[binary]` (PostgreSQL — see ADR-005) |
| Sentiment | `pysentimiento` (BETO) — full FP32 fits comfortably in 16 GB; INT8 only if throughput becomes the bottleneck |
| Compute | **CPU only** (integrated Radeon iGPU not used — ROCm setup not worth maintenance) |
| Package mgr | `uv` |
| Tests | `pytest` |

### Android Client (`android/`)
| Layer | Choice |
|-------|--------|
| Language | Kotlin 2.0 |
| Min SDK | 26 (Android 8.0) · Target SDK 35 (Android 15) |
| UI | Jetpack Compose 1.7 + Material 3 |
| DI | Hilt |
| Networking | Retrofit 2.11 + OkHttp + Moshi |
| Local cache | Room 2.6 (for offline-first behaviour during the legal blackout) |
| Build | Gradle 8.7 (Kotlin DSL) |
| Tests | JUnit 5 + MockK + Turbine + Compose UI tests |

## Essential Commands

### Go API
```bash
go run ./cmd/api                    # Run the JSON API locally
go test ./...                       # All Go tests
go test -race ./...                 # With race detector
go vet ./...                        # Static analysis
golangci-lint run                   # Linter
go build -o bin/api ./cmd/api       # Build binary
```

### Python pipeline
```bash
uv sync                                       # Install deps (creates .venv)
uv run python pipeline/scripts/scrape.py      # Run a scraper
uv run python pipeline/scripts/train.py       # Fit Bayesian models
uv run python pipeline/scripts/predict.py     # Generate /forecast JSON
uv run pytest pipeline/tests/ -v              # All tests
uv run pytest pipeline/tests/ -v -k "not slow"  # Skip slow MCMC tests
uv run ruff check pipeline/                   # Lint
uv run ruff format pipeline/                  # Format
```

### Android app
```bash
cd android
./gradlew assembleDebug             # Build debug APK
./gradlew test                      # All unit tests
./gradlew :app:testDebugUnitTest    # App-module unit tests
./gradlew connectedAndroidTest      # Instrumented tests (requires device/emulator)
./gradlew lint
./gradlew detekt                    # Static analysis
./gradlew ktlintCheck               # Formatting check
./gradlew clean
```

## Conventions

| Concern | Go | Python | Kotlin |
|---------|-----|--------|--------|
| Naming | PascalCase exported, camelCase unexported, snake_case files | snake_case files+funcs, PascalCase classes | PascalCase files+classes, camelCase funcs |
| Errors | Wrap with `fmt.Errorf("%w", err)`; check immediately | Typed exceptions; never silent `except: pass` | `Result<T>` sealed classes for domain errors; suspend funcs throw for I/O |
| Imports | `goimports` order: stdlib → third-party → internal | stdlib → third-party → local; no wildcard | Default order; trailing commas in multiline |
| Structure | `cmd/`, `internal/`, package-by-domain (not layer) | `pipeline/{scrapers,parsers,models,scripts}/` | Standard Android: `app/src/main/{kotlin,res}/` |
| Tests | `*_test.go` co-located; table-driven; `t.Helper()` | `test_*.py` under `tests/`; `pytest` fixtures + `parametrize` | `*Test.kt` mirroring `src/main/kotlin/`; MockK + Turbine |

## Critical Domain Rules

These are non-negotiable — see `CONTEXT.md` for full reasoning.

1. **Legal blackout (36 hours)** — Per the Constitutional Court ruling on expediente 1699-2018 (23 April 2019), forecasts must be unavailable from ~18:00 local Friday to ~18:00 local Sunday for both election rounds. A `BLACKOUT_ENABLED` runtime flag in the Go API must return `503` on `/forecast/*` and the Android app must display a blackout splash when the API returns it. **The flag is the hard switch — never bypass even in tests against production data.**
2. **TSE returns 403 to bare scrapers** — every scraper hitting `tse.org.gt` must spoof a real browser User-Agent (Chrome/Safari latest). Plan retries with exponential backoff.
3. **Twitter/X is forbidden** — free API is gone and scraping violates ToS. Do not add it. Sentiment input comes from RSS + Reddit + Bluesky + YouTube comments only.
4. **Movimiento Semilla cancellation is "vigente" but under appeal** — treat its 2027 eligibility as a runtime flag in the congressional model. Eleven other 2023 parties are confirmed cancelled (see `docs/requirement.md`).
5. **`pytrends` rate limit** — 60s sleep between requests once throttled; minimum 3–5s between requests always. Build robust backoff before deploying.
6. **No bulk-downloading TREP per-mesa actas** — ~122,000 PDFs, no bulk endpoint, will be retired for 2027 anyway. Use 2023 results only for backfill, scraped from `resultados2019.tse.org.gt` "Datos abiertos: Excel" buttons where possible.

## Proof Cycle

Think before editing (SAIV — `.claude/rules/thinking-protocol.md`). After EVERY code change, run the proof cycle for the area you touched: type check → lint → test → build. Completion claims require evidence — see `.claude/rules/verification.md`.

| Area | Type check | Lint | Test | Build |
|------|-----------|------|------|-------|
| Go | `go vet ./...` | `golangci-lint run` | `go test ./...` | `go build ./...` |
| Python | `uv run mypy pipeline/` | `uv run ruff check pipeline/` | `uv run pytest pipeline/tests/` | n/a |
| Android | `./gradlew :app:compileDebugKotlin` | `./gradlew detekt ktlintCheck` | `./gradlew test` | `./gradlew assembleDebug` |

## Hooks

Active hooks live in `.claude/settings.json`. If a hook blocks you, read the error — don't bypass. `.claude/hooks/` contains the scripts.

## Project State

- **`CONTEXT.md`**: stable project context — mission, ADRs, glossary, constraints. Read at session start.
- **GitHub Issues**: running work and decisions. Repo is `jlcp89/polityk`. Issues tagged `ready-for-agent` are pickable by the AFK loop; `needs-human` or unlabeled wait for the maintainer.
- **AFK automation**: `.claude/automation/` contains the autonomous loop (`run-loop.sh`, `run-parallel.sh`) and per-stage sandcastle prompts. See `.claude/automation/loop-prompt.md`.

Persist long-running context with `/wrap`; recover at session start with `/recover`.

## Autonomous Mode

When running with `--dangerously-skip-permissions` (the AFK loop):
- Hooks are your safety net — don't bypass.
- Commit early and often — small atomic commits, reversible changes.
- After each milestone, run `/wrap` to persist decisions to `CONTEXT.md` (ADRs).
- Stay conservative — do exactly what was asked, no opportunistic refactors.
- Verify harder — full proof cycle after every change.
- **NEVER touch the blackout flag logic without a `needs-human` tag** — legal risk.

<!-- Generated by c2 v0.9.0 on 2026-05-21 -->
