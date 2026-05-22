-- 0005_scrape_runs.sql
-- Issue #17: shared per-source scrape audit table consumed by all scrapers
-- (Wikipedia polls now; TSE party list #15, RSS aggregator #16, macro
-- indicators #18, Memoria PDF loaders #20-22, etc.) and read by /v1/health
-- (#14). Carries one row per `source` string; UPSERT on every run.

-- +goose Up
CREATE TABLE scrape_runs (
    source TEXT PRIMARY KEY,
    last_run_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    success BOOLEAN NOT NULL,
    error_message TEXT
);

-- +goose Down
DROP TABLE IF EXISTS scrape_runs;
