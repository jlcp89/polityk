---
paths:
  - "src/**"
  - "lib/**"
  - "app/**"
  - "pkg/**"
  - "internal/**"
  - "cmd/**"
  - "pipeline/**"
  - "android/**"
  - "**/*.go"
  - "**/*.py"
  - "**/*.kt"
  - "**/*.kts"
---

# Toolchain Quick Reference

Single lookup table for all project commands. No searching across files.

## Go API

| Concern | Command | Notes |
|---------|---------|-------|
| Type check | `go vet ./...` | Run after every code change |
| Lint | `golangci-lint run` | Install: `go install github.com/golangci/golangci-lint/cmd/golangci-lint@latest` |
| Test | `go test -race ./...` | Race detector required |
| Build | `go build -o bin/api ./cmd/api` | Outputs `bin/api` |
| Format | `gofmt -w .` and `goimports -w .` | Pre-commit |
| Dev server | `go run ./cmd/api` | Listens on 127.0.0.1:8080 by default |

## Python pipeline

| Concern | Command | Notes |
|---------|---------|-------|
| Env setup | `uv sync` | Creates `.venv`, installs from `uv.lock` |
| Type check | `uv run mypy pipeline/` | Type hints required on all signatures |
| Lint | `uv run ruff check pipeline/` | Includes import-order, complexity |
| Test (fast) | `uv run pytest pipeline/tests/ -v -k "not slow"` | Skip MCMC tests |
| Test (full) | `uv run pytest pipeline/tests/ -v` | Includes MCMC smoke tests |
| Format | `uv run ruff format pipeline/` | Pre-commit |
| Train models | `uv run python pipeline/scripts/train.py` | CPU-only — budget ~15–30 min per model |
| Predict | `uv run python pipeline/scripts/predict.py` | Writes `data/posteriors/posterior_<ts>_<sha>.parquet` |

## Android client

| Concern | Command | Notes |
|---------|---------|-------|
| Type check | `./gradlew :app:compileDebugKotlin` | Run after every Kotlin change |
| Lint | `./gradlew detekt ktlintCheck` | Both detekt and ktlint must pass |
| Test (unit) | `./gradlew test` | All modules |
| Test (instrumented) | `./gradlew connectedAndroidTest` | Needs device/emulator |
| Build (debug) | `./gradlew assembleDebug` | Outputs `app/build/outputs/apk/debug/app-debug.apk` |
| Build (release) | `./gradlew bundleRelease` | Signed bundle for Play Store — CI only |
| Clean | `./gradlew clean` | When in doubt |

## Cross-cutting

| Concern | Command |
|---------|---------|
| Secret scan | `bash .claude/hooks/scan-secrets.sh` (pre-commit hook) |
| Knowledge graph | `graphify . --update` (requires `c2/graphify` Python tool) |

## Stack Summary

| Aspect | Value |
|--------|-------|
| Languages | Go 1.22+, Python 3.11+, Kotlin 2.0 |
| Frameworks | net/http · PyMC 5 · Jetpack Compose 1.7 |
| Test runners | `testing` (Go) · `pytest` (Python) · JUnit 5 (Kotlin) |
| Formatters | `gofmt` + `goimports` · `ruff format` · `ktlint` |
| Linters | `golangci-lint` · `ruff check` · `detekt` |
| Databases | SQLite (`modernc.org/sqlite`) + DuckDB |

## Config Files (created as the project develops)

| File | Purpose |
|------|---------|
| `go.mod` / `go.sum` | Go module + checksums |
| `golangci.yml` | golangci-lint config |
| `pyproject.toml` / `uv.lock` | Python project + lockfile |
| `ruff.toml` or `[tool.ruff]` in pyproject | Lint/format config |
| `android/build.gradle.kts` | Root Gradle config |
| `android/app/build.gradle.kts` | App module config |
| `android/gradle/libs.versions.toml` | Version catalog |
| `infra/systemd/*.service` `*.timer` | Host deployment units (when introduced) |
| `infra/cloudflared/config.yml` | Cloudflare Tunnel ingress (when introduced) |
