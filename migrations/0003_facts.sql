-- 0003_facts.sql
-- Issue #3: race-specific fact tables (presidential_results, congress_results,
-- municipal_results) per ADR-008, with the `chamber` discriminator from
-- ADR-016 on congress_results.

-- +goose Up
-- +goose StatementBegin
CREATE TYPE congress_chamber AS ENUM (
    'congress_distrital',
    'congress_nacional',
    'parlacen'
);
-- +goose StatementEnd

CREATE TABLE presidential_results (
    election_id BIGINT NOT NULL REFERENCES elections (election_id),
    candidate_id BIGINT NOT NULL REFERENCES candidates (candidate_id),
    geography_id BIGINT NOT NULL REFERENCES geographies (geography_id),
    votes BIGINT NOT NULL CHECK (votes >= 0),
    PRIMARY KEY (election_id, candidate_id, geography_id)
);

CREATE INDEX presidential_results_geography_idx
    ON presidential_results (geography_id);
CREATE INDEX presidential_results_candidate_idx
    ON presidential_results (candidate_id);

CREATE TABLE congress_results (
    election_id BIGINT NOT NULL REFERENCES elections (election_id),
    district_id BIGINT NOT NULL REFERENCES geographies (geography_id),
    party_id BIGINT NOT NULL REFERENCES parties (party_id),
    chamber congress_chamber NOT NULL DEFAULT 'congress_distrital',
    votes BIGINT NOT NULL CHECK (votes >= 0),
    seats SMALLINT NOT NULL DEFAULT 0 CHECK (seats >= 0),
    PRIMARY KEY (election_id, district_id, party_id, chamber)
);

CREATE INDEX congress_results_party_idx ON congress_results (party_id);
CREATE INDEX congress_results_chamber_idx ON congress_results (chamber);

CREATE TABLE municipal_results (
    election_id BIGINT NOT NULL REFERENCES elections (election_id),
    municipality_id BIGINT NOT NULL REFERENCES geographies (geography_id),
    party_id BIGINT NOT NULL REFERENCES parties (party_id),
    alcalde_votes BIGINT NOT NULL DEFAULT 0 CHECK (alcalde_votes >= 0),
    alcalde_won BOOLEAN NOT NULL DEFAULT FALSE,
    concejales_seats SMALLINT NOT NULL DEFAULT 0 CHECK (concejales_seats >= 0),
    sindicos_seats SMALLINT NOT NULL DEFAULT 0 CHECK (sindicos_seats >= 0),
    PRIMARY KEY (election_id, municipality_id, party_id)
);

CREATE INDEX municipal_results_party_idx ON municipal_results (party_id);

-- +goose Down
DROP TABLE IF EXISTS municipal_results;
DROP TABLE IF EXISTS congress_results;
DROP TABLE IF EXISTS presidential_results;
DROP TYPE IF EXISTS congress_chamber;
