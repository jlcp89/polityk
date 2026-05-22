-- 0008_trends.sql
-- Issue #24: Google Trends fact table populated by `pytrends_scraper.py`
-- (ADR-004 Python-side scraping). One row per (query, observed_at, geo).
--
-- Schema notes
--   * query is TEXT (no length cap) -- candidate full names + alias forms
--     up to ~80 chars. Stored verbatim as sent to pytrends so a re-scrape
--     hits the same idempotency key without normalisation drift.
--   * observed_at is DATE -- pytrends daily-interval responses carry one
--     row per UTC date.
--   * geo defaults to 'GT' (Guatemala, the only geography we currently
--     query). Kept on the row + in the UNIQUE key so a later cross-country
--     comparison (e.g. 'GT-AV' department-level) does not collide.
--   * interest is SMALLINT in 0..100 (pytrends' normalised search-interest
--     index). CHECK enforces the range so a parser bug surfaces at write
--     time, not at fit time in #31.
--   * UNIQUE(query, observed_at, geo) is the idempotency key the scraper
--     UPSERTs against via ON CONFLICT DO NOTHING.

-- +goose Up
CREATE TABLE trends (
    trend_id BIGSERIAL PRIMARY KEY,
    query TEXT NOT NULL CHECK (length(query) > 0),
    observed_at DATE NOT NULL,
    geo TEXT NOT NULL DEFAULT 'GT' CHECK (length(geo) > 0),
    interest SMALLINT NOT NULL CHECK (interest >= 0 AND interest <= 100),
    UNIQUE (query, observed_at, geo)
);

CREATE INDEX trends_query_observed_idx
    ON trends (query, geo, observed_at DESC);

-- +goose Down
DROP TABLE IF EXISTS trends;
