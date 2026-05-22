-- 0007_macro_indicators.sql
-- Issue #18: macro-indicator fact table consumed by the fundamentals layer
-- (#31, ADR-011). One row per (source, code, observed_at). Sources are
-- locked to the four institutions named in ADR-004 -- adding a new source
-- requires a follow-up migration so a scraper typo cannot silently land
-- under a misspelled string.
--
-- Schema notes
--   * source is TEXT with a CHECK constraint rather than CREATE TYPE ENUM
--     to match the 0006 pattern (which avoids per-source DDL on extension).
--   * value is NUMERIC (no precision/scale) so banguat's 4-decimal GDP YoY
--     and ine's integer-counted homicide rate coexist without rounding loss.
--   * unit is NOT NULL with an empty-string default rather than nullable
--     to keep downstream JOINs free of NULL handling -- the fundamentals
--     model treats "" as "dimensionless ratio" per ADR-011.
--   * UNIQUE(source, code, observed_at) is the idempotency key the four
--     macro scrapers UPSERT against; the partial index on observed_at DESC
--     supports the "latest reading per (source, code)" lookups the
--     fundamentals model issues.

-- +goose Up
CREATE TABLE macro_indicators (
    indicator_id BIGSERIAL PRIMARY KEY,
    source TEXT NOT NULL
        CHECK (source IN ('banguat', 'ine', 'segeplan', 'minfin')),
    code TEXT NOT NULL CHECK (length(code) > 0),
    observed_at DATE NOT NULL,
    value NUMERIC NOT NULL,
    unit TEXT NOT NULL DEFAULT '',
    UNIQUE (source, code, observed_at)
);

CREATE INDEX macro_indicators_latest_idx
    ON macro_indicators (source, code, observed_at DESC);

-- +goose Down
DROP TABLE IF EXISTS macro_indicators;
