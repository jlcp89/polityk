-- 0002_dimensions.sql
-- Issue #2: dimension tables (elections, parties, candidates, geographies,
-- pollsters and their satellite alias/eligibility tables) per ADR-008,
-- ADR-009, ADR-016, ADR-017.

-- +goose Up
-- +goose StatementBegin
CREATE TYPE party_status AS ENUM (
    'active',
    'cancelled',
    'cancelled_under_appeal',
    'dissolved'
);
-- +goose StatementEnd

-- +goose StatementBegin
CREATE TYPE geography_level AS ENUM (
    'country',
    'department',
    'district',
    'municipality',
    'mesa'
);
-- +goose StatementEnd

CREATE TABLE elections (
    election_id BIGSERIAL PRIMARY KEY,
    cycle SMALLINT NOT NULL,
    round SMALLINT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (cycle, round)
);

CREATE TABLE parties (
    party_id BIGSERIAL PRIMARY KEY,
    name TEXT NOT NULL UNIQUE,
    tse_code TEXT UNIQUE,
    status party_status NOT NULL DEFAULT 'active',
    cancelled_at TIMESTAMPTZ,
    predecessor_party_id BIGINT REFERENCES parties (party_id),
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE party_aliases (
    alias_id BIGSERIAL PRIMARY KEY,
    party_id BIGINT NOT NULL REFERENCES parties (party_id) ON DELETE CASCADE,
    alias_name TEXT NOT NULL,
    valid_from DATE,
    valid_to DATE,
    UNIQUE (party_id, alias_name)
);

CREATE TABLE party_eligibility (
    party_id BIGINT NOT NULL REFERENCES parties (party_id) ON DELETE CASCADE,
    cycle SMALLINT NOT NULL,
    is_eligible BOOLEAN NOT NULL,
    source TEXT,
    PRIMARY KEY (party_id, cycle)
);

CREATE TABLE candidates (
    candidate_id BIGSERIAL PRIMARY KEY,
    full_name TEXT NOT NULL,
    sex CHAR(1) CHECK (sex IN ('M', 'F', 'X')),
    wikidata_qid TEXT UNIQUE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE candidate_aliases (
    alias_id BIGSERIAL PRIMARY KEY,
    candidate_id BIGINT NOT NULL REFERENCES candidates (candidate_id) ON DELETE CASCADE,
    alias_name TEXT NOT NULL,
    UNIQUE (candidate_id, alias_name)
);

CREATE TABLE candidate_party (
    candidate_id BIGINT NOT NULL REFERENCES candidates (candidate_id) ON DELETE CASCADE,
    party_id BIGINT NOT NULL REFERENCES parties (party_id) ON DELETE CASCADE,
    cycle SMALLINT NOT NULL,
    PRIMARY KEY (candidate_id, party_id, cycle)
);

CREATE TABLE geographies (
    geography_id BIGSERIAL PRIMARY KEY,
    level geography_level NOT NULL,
    code TEXT NOT NULL,
    name TEXT NOT NULL,
    parent_id BIGINT REFERENCES geographies (geography_id),
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (level, code)
);

CREATE INDEX geographies_parent_idx ON geographies (parent_id);
CREATE INDEX geographies_level_idx ON geographies (level);

CREATE TABLE pollsters (
    pollster_id BIGSERIAL PRIMARY KEY,
    name TEXT NOT NULL UNIQUE,
    country_code TEXT NOT NULL DEFAULT 'GT',
    est_year SMALLINT,
    methodology TEXT,
    historical_bias_mean NUMERIC NOT NULL DEFAULT 0,
    historical_bias_sd NUMERIC NOT NULL DEFAULT 0.05,
    sample_count_used SMALLINT NOT NULL DEFAULT 0,
    bias_last_estimated_at TIMESTAMPTZ
);

-- +goose Down
DROP TABLE IF EXISTS pollsters;
DROP TABLE IF EXISTS candidate_party;
DROP TABLE IF EXISTS candidate_aliases;
DROP TABLE IF EXISTS candidates;
DROP TABLE IF EXISTS party_eligibility;
DROP TABLE IF EXISTS party_aliases;
DROP TABLE IF EXISTS parties;
DROP TABLE IF EXISTS geographies;
DROP TABLE IF EXISTS elections;
DROP TYPE IF EXISTS geography_level;
DROP TYPE IF EXISTS party_status;
