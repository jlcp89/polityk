-- 0004_polls.sql
-- Issue #4: polls schema (polls, poll_responses, poll_errors) per ADR-008
-- and ADR-017, plus a seed of the four launch pollsters with the ADR-017
-- diffuse default bias prior (mean=0, sd=0.05).

-- +goose Up
CREATE TABLE polls (
    poll_id BIGSERIAL PRIMARY KEY,
    pollster_id BIGINT NOT NULL REFERENCES pollsters (pollster_id),
    field_start DATE NOT NULL,
    field_end DATE NOT NULL,
    sample_size INTEGER CHECK (sample_size IS NULL OR sample_size > 0),
    methodology TEXT,
    source_url TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    CHECK (field_end >= field_start),
    UNIQUE (pollster_id, field_end, source_url)
);

CREATE INDEX polls_pollster_idx ON polls (pollster_id);
CREATE INDEX polls_field_end_idx ON polls (field_end);

CREATE TABLE poll_responses (
    poll_id BIGINT NOT NULL REFERENCES polls (poll_id) ON DELETE CASCADE,
    candidate_id BIGINT NOT NULL REFERENCES candidates (candidate_id),
    share NUMERIC NOT NULL CHECK (share >= 0 AND share <= 1),
    margin_of_error NUMERIC CHECK (margin_of_error IS NULL OR margin_of_error >= 0),
    PRIMARY KEY (poll_id, candidate_id)
);

CREATE INDEX poll_responses_candidate_idx ON poll_responses (candidate_id);

CREATE TABLE poll_errors (
    pollster_id BIGINT NOT NULL REFERENCES pollsters (pollster_id),
    cycle SMALLINT NOT NULL,
    candidate_id BIGINT NOT NULL REFERENCES candidates (candidate_id),
    poll_prediction NUMERIC NOT NULL,
    actual_result NUMERIC NOT NULL,
    error NUMERIC GENERATED ALWAYS AS (poll_prediction - actual_result) STORED,
    PRIMARY KEY (pollster_id, cycle, candidate_id)
);

CREATE INDEX poll_errors_cycle_idx ON poll_errors (cycle);
CREATE INDEX poll_errors_candidate_idx ON poll_errors (candidate_id);

-- Seed the four launch pollsters per ADR-017. ON CONFLICT keeps the seed
-- idempotent and preserves any historical_bias_* values written back by the
-- #29 estimator without clobbering them on re-run.
INSERT INTO pollsters (name, country_code, methodology, historical_bias_mean, historical_bias_sd, sample_count_used) VALUES
    ('CID Gallup', 'GT', 'Multi-stage stratified national sample', 0, 0.05, 0),
    ('ProDatos', 'GT', 'Encuesta Libre / Prensa Libre national sample', 0, 0.05, 0),
    ('Borge y Asociados', 'GT', 'National face-to-face sample', 0, 0.05, 0),
    ('Fundación Libertad y Desarrollo', 'GT', 'National telephone/face-to-face sample', 0, 0.05, 0)
ON CONFLICT (name) DO NOTHING;

-- +goose Down
DROP TABLE IF EXISTS poll_errors;
DROP TABLE IF EXISTS poll_responses;
DROP TABLE IF EXISTS polls;
-- The seeded pollsters are kept on `goose down 1` because dropping rows
-- that other migrations may reference (poll_errors, sentiment_scores) is
-- riskier than leaving them: the 0002 migration's `DROP TABLE pollsters`
-- on its own Down covers full teardown. The seeded values are also
-- idempotent under the Up section above.
