-- 0023_party_of_government.sql
-- Issue #31: `party_of_government` (cycle → incumbent-party_id) so the
-- fundamentals model can compute the Feature 1 "incumbent_party" indicator
-- without hardcoding party_ids. Per CLAUDE.md / Operational Commitments and
-- ADR-009 (parties identified by stable party_id; tse_code is the natural
-- key for cross-migration references).
--
-- `cycle` is the election cycle whose incumbent we're naming: the party that
-- held the presidency at the time of that election. For example, the row
-- (cycle=2011, party_id=<GANA>) records that GANA (Berger's party, in office
-- 2004-2008) was the party-of-government at the *2007* election; for the
-- *2011* election the row is (cycle=2011, party_id=<UNE>) because Colom/UNE
-- held the presidency 2008-2012. Each election's row therefore captures the
-- incumbent at the moment of that election.
--
-- Seed coverage spans the backtest range 2007–2023 plus the live cycle
-- 2027 (whose incumbent at election time is Arévalo / Movimiento Semilla
-- pending the 2027 results). The seed is idempotent: parties are ensured
-- via ON CONFLICT DO NOTHING on tse_code, and the cycle PK guards against
-- duplicate inserts on re-run.

-- +goose Up
CREATE TABLE party_of_government (
    cycle SMALLINT PRIMARY KEY,
    party_id BIGINT NOT NULL REFERENCES parties (party_id),
    took_office_at DATE NOT NULL,
    source TEXT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- Ensure the incumbent-party rows exist so the SELECT below can resolve them.
-- ADR-009: tse_code is the natural cross-migration key. `name` defaults to
-- the tse_code on first insert; a maintainer or later loader can rename later
-- without invalidating the FK (party_id is stable). ON CONFLICT DO NOTHING
-- (without target) skips any unique violation so this is safe whether or
-- not a prior loader has already written a row under the same name OR
-- the same tse_code.
INSERT INTO parties (name, tse_code) VALUES
    ('GANA',       'GANA'),
    ('UNE',        'UNE'),
    ('PP',         'PP'),
    ('FCN-Nacion', 'FCN-NACION'),
    ('Vamos',      'VAMOS'),
    ('Semilla',    'SEMILLA')
ON CONFLICT DO NOTHING;

-- Seed the cycle → incumbent mapping via JOIN so rows with no matching
-- parties row (e.g., a loader stored the party under a different tse_code)
-- are silently skipped rather than violating the NOT NULL party_id FK.
-- The fundamentals model's `read_party_of_government` tolerates missing
-- cycles by treating every candidate as a non-incumbent in that cycle.
INSERT INTO party_of_government (cycle, party_id, took_office_at, source)
SELECT d.cycle, p.party_id, d.took_office_at, d.source
FROM (VALUES
    (2007::SMALLINT, 'GANA',       DATE '2004-01-14', 'TSE Memoria Electoral 2003'),
    (2011::SMALLINT, 'UNE',        DATE '2008-01-14', 'TSE Memoria Electoral 2007'),
    (2015::SMALLINT, 'PP',         DATE '2012-01-14', 'TSE Memoria Electoral 2011'),
    (2019::SMALLINT, 'FCN-NACION', DATE '2016-01-14', 'TSE Memoria Electoral 2015'),
    (2023::SMALLINT, 'VAMOS',      DATE '2020-01-14', 'TSE Acuerdo Toma de Posesion 2019'),
    (2027::SMALLINT, 'SEMILLA',    DATE '2024-01-14', 'TSE Acuerdo Toma de Posesion 2023')
) AS d(cycle, tse_code, took_office_at, source)
JOIN parties p ON p.tse_code = d.tse_code
ON CONFLICT (cycle) DO NOTHING;

COMMENT ON TABLE party_of_government IS
    'Cycle -> incumbent party_id mapping consumed by the fundamentals model '
    '(#31). One row per election cycle whose incumbent we need to flag.';

-- +goose Down
DROP TABLE IF EXISTS party_of_government;
