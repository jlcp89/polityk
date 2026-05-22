-- 0003_scrape_runs.sql
-- Issue #15: scrape audit table. Every scraper (TSE party list, RSS,
-- Memoria PDFs, macro indicators, ...) stamps a row keyed by a stable
-- source identifier (e.g. 'tse_party_list', 'rss_aggregator') on every
-- run, success or failure. Powers /v1/health (#14) and operational
-- visibility into stale ingest paths.
--
-- The table is intentionally tiny and rewritten in-place per source via
-- UPSERT — a full per-run history is not the point; the latest status is.
-- A separate scrape_run_history can be added later if forensic depth
-- is needed.

-- +goose Up
CREATE TABLE scrape_runs (
    source TEXT PRIMARY KEY,
    last_run_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    success BOOLEAN NOT NULL,
    error_message TEXT
);

-- +goose Down
DROP TABLE IF EXISTS scrape_runs;
