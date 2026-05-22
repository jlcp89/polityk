-- 0025_approval_ratings.sql
-- Issue #31: `approval_ratings` — sitting-government approval readings used
-- to derive the Feature 2 "party-of-government performance penalty" in the
-- fundamentals model. One row per (party, cycle, measured_at, pollster);
-- the model picks the most recent pre-election reading for the cycle's
-- incumbent (resolved via party_of_government from 0023).
--
-- Schema notes
--   * approval_share is a fraction in [0,1] (not a percent). The penalty
--     transformation is `1 - approval_share` applied in Python.
--   * disapproval_share is OPTIONAL because not every survey publishes it;
--     when present the model could also use it (currently it does not, but
--     storing keeps follow-up modelling work cheap).
--   * sample_size and source_url are NULLABLE so historical readings whose
--     archives survive only as press-clip text can still be ingested with
--     provenance recorded in source_url when available.
--   * UNIQUE(party_id, cycle, measured_at, pollster) prevents accidental
--     duplicate ingests; pollster is NOT NULL by default so the unique key
--     is meaningful (NULL would let dupes slip through under NULLS DISTINCT
--     semantics).
--
-- Seeding policy: this migration creates the schema but seeds NO rows. The
-- backtest historical approval numbers for 2003-2023 incumbents are best
-- sourced from CID Gallup / ProDatos / Encuesta Libre archival reports
-- under maintainer review (see #31 follow-up). The fundamentals model
-- tolerates a missing approval reading by falling back to the cohort mean
-- (0.5) with a widened prior; the calibration gate (#36) is the safety net.

-- +goose Up
CREATE TABLE approval_ratings (
    approval_id BIGSERIAL PRIMARY KEY,
    party_id BIGINT NOT NULL REFERENCES parties (party_id),
    cycle SMALLINT NOT NULL,
    measured_at DATE NOT NULL,
    approval_share NUMERIC NOT NULL CHECK (approval_share >= 0 AND approval_share <= 1),
    disapproval_share NUMERIC CHECK (disapproval_share IS NULL OR (disapproval_share >= 0 AND disapproval_share <= 1)),
    pollster TEXT NOT NULL,
    sample_size INTEGER CHECK (sample_size IS NULL OR sample_size > 0),
    source_url TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (party_id, cycle, measured_at, pollster)
);

CREATE INDEX approval_ratings_cycle_idx ON approval_ratings (cycle);
CREATE INDEX approval_ratings_latest_idx
    ON approval_ratings (party_id, cycle, measured_at DESC);

COMMENT ON TABLE approval_ratings IS
    'Sitting-government approval readings per pollster. Consumed by the '
    'fundamentals model (#31) Feature 2 (party-of-government performance '
    'penalty = 1 - approval_share). Historical seed populated by a follow-up '
    'data-curation task; the model tolerates missing rows.';

-- +goose Down
DROP TABLE IF EXISTS approval_ratings;
