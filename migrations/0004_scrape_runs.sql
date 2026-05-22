-- 0004_scrape_runs.sql
-- Issue #19: introduce `scrape_runs` audit table, needed by every scraper /
-- loader (#15, #16, #17, #18, #19-#25). Lives here because #19 is the first
-- end-to-end ETL pass that lands and must stamp it. Per #14's note, the
-- table is introduced lazily by the first scraper/loader to land.
--
-- Shape per #15:
--   scrape_runs (source TEXT PK, last_run_at TIMESTAMPTZ, success BOOLEAN,
--                error_message TEXT NULL)

-- +goose Up
CREATE TABLE scrape_runs (
    source TEXT PRIMARY KEY,
    last_run_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    success BOOLEAN NOT NULL,
    error_message TEXT
);

-- +goose Down
DROP TABLE IF EXISTS scrape_runs;
