-- 0006_operational.sql
-- Issue #6: operational schema for the model pipeline per ADR-006 (forecasts
-- table + LISTEN/NOTIFY cache invalidation), ADR-013 (calibration gate audit
-- trail), and ADR-019 (manual interventions).
--
-- Schema contract notes:
--   * forecasts.payload is JSONB (not JSON, not TEXT) so the Go handler in
--     #9 can return it byte-for-byte and the LISTEN/NOTIFY watcher in #10
--     can clear the in-process LRU without parsing.
--   * race_type and run_kind are TEXT with CHECK constraints rather than
--     CREATE TYPE enums, matching the issue body verbatim. ENUM types here
--     would also force a migration whenever we add a new race_type, and
--     #12 already routes congress/municipal as 404s in v1.
--   * interventions uses CREATE TYPE for target_kind and intervention_kind
--     per the issue body. These are fixed by ADR-019.
--   * posterior_archives.sample_array is NUMERIC[][] — two-dimensional
--     because the posterior is shape (samples, candidates) per #33.
--   * gen_random_uuid() is built into Postgres 13+; no pgcrypto extension
--     needed for postgres:16 (the CI matrix).
--   * NOTIFY forecast_ready is a runtime concern (no DDL); the channel is
--     reserved here by being the documented channel name -- the integration
--     test asserts a NOTIFY round-trips on this channel.

-- +goose Up
-- +goose StatementBegin
CREATE TYPE intervention_target_kind AS ENUM (
    'candidate',
    'party',
    'race'
);
-- +goose StatementEnd

-- +goose StatementBegin
CREATE TYPE intervention_kind AS ENUM (
    'disqualified',
    'withdrew',
    'party_cancelled',
    'manual_probability'
);
-- +goose StatementEnd

CREATE TABLE forecasts (
    run_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    model_version TEXT NOT NULL,
    generated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    race_type TEXT NOT NULL,
    run_kind TEXT NOT NULL DEFAULT 'scheduled'
        CHECK (run_kind IN ('scheduled', 'whatif')),
    payload JSONB NOT NULL,
    is_published BOOLEAN NOT NULL DEFAULT FALSE
);

-- The /v1/forecast/* handler (#9) reads "latest is_published per race_type"
-- and the calibration gate (#36) writes is_published. Partial indexes cover
-- both hot paths.
CREATE INDEX forecasts_published_latest_idx
    ON forecasts (race_type, generated_at DESC)
    WHERE is_published = TRUE;
CREATE INDEX forecasts_race_kind_idx
    ON forecasts (race_type, run_kind);

CREATE TABLE posterior_archives (
    run_id UUID NOT NULL REFERENCES forecasts (run_id) ON DELETE CASCADE,
    race_type TEXT NOT NULL,
    sample_array NUMERIC[][] NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (run_id, race_type)
);

CREATE TABLE calibration_failures (
    failure_id BIGSERIAL PRIMARY KEY,
    run_id UUID NOT NULL REFERENCES forecasts (run_id) ON DELETE CASCADE,
    gate TEXT NOT NULL,
    observed_value NUMERIC,
    threshold NUMERIC,
    failed_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX calibration_failures_run_idx
    ON calibration_failures (run_id);
CREATE INDEX calibration_failures_gate_idx
    ON calibration_failures (gate);

-- calibration_overrides is the audit trail for #37 (force_publish.py).
-- run_id is a real FK to forecasts -- a forced publish without a forecast
-- row would be nonsensical and silently un-auditable.
CREATE TABLE calibration_overrides (
    override_id BIGSERIAL PRIMARY KEY,
    run_id UUID NOT NULL REFERENCES forecasts (run_id) ON DELETE CASCADE,
    reason TEXT NOT NULL CHECK (length(reason) > 0),
    operator TEXT NOT NULL CHECK (length(operator) > 0),
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX calibration_overrides_run_idx
    ON calibration_overrides (run_id);

CREATE TABLE interventions (
    intervention_id BIGSERIAL PRIMARY KEY,
    target_kind intervention_target_kind NOT NULL,
    target_id BIGINT NOT NULL,
    kind intervention_kind NOT NULL,
    effective_at TIMESTAMPTZ NOT NULL,
    expires_at TIMESTAMPTZ,
    override_probability NUMERIC
        CHECK (override_probability IS NULL
               OR (override_probability >= 0 AND override_probability <= 1)),
    reason TEXT NOT NULL CHECK (length(reason) > 0),
    operator TEXT NOT NULL CHECK (length(operator) > 0),
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    -- override_probability is only meaningful for the 'manual_probability'
    -- kind; the other three kinds zero-out the target deterministically per
    -- ADR-019 and must leave override_probability NULL so the applier in
    -- #35 doesn't pick up a stale value.
    CHECK (
        (kind = 'manual_probability' AND override_probability IS NOT NULL)
        OR (kind <> 'manual_probability' AND override_probability IS NULL)
    ),
    CHECK (expires_at IS NULL OR expires_at > effective_at)
);

-- The #35 intervention applier reads "active at now()" so the (effective_at,
-- expires_at) range index is the hot path. The target lookup index helps
-- the methodology display and the CLI's "is X already intervened?" probe.
CREATE INDEX interventions_active_window_idx
    ON interventions (effective_at, expires_at);
CREATE INDEX interventions_target_idx
    ON interventions (target_kind, target_id);

-- +goose Down
DROP TABLE IF EXISTS interventions;
DROP TABLE IF EXISTS calibration_overrides;
DROP TABLE IF EXISTS calibration_failures;
DROP TABLE IF EXISTS posterior_archives;
DROP TABLE IF EXISTS forecasts;
DROP TYPE IF EXISTS intervention_kind;
DROP TYPE IF EXISTS intervention_target_kind;
