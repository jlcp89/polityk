-- 0024_election_key_dates.sql
-- Issue #31: per-election key calendar dates consumed by the fundamentals
-- model. Feature 8 (polling-environment flag: pre/post candidate-list
-- finalisation) requires knowing when each cycle's TSE candidate registry
-- closed. The same table also holds campaign window dates for future use.
--
-- `election_id` is the PK because each round has its own key dates in
-- principle, even though candidate registration is shared across round 1
-- and round 2 within a cycle. The training-feature join in the fundamentals
-- model filters to `elections.round = 1`.
--
-- Dates seeded from TSE press releases (Convocatoria a Elecciones Generales
-- and Acuerdos cited per row); placeholder January 1 values are used where
-- the precise TSE date hasn't been located yet, with the source column
-- flagging this explicitly so future cleanup is easy.

-- +goose Up
CREATE TABLE election_key_dates (
    election_id BIGINT PRIMARY KEY REFERENCES elections (election_id),
    candidate_list_closed_at DATE NOT NULL,
    campaign_start_at DATE,
    campaign_end_at DATE,
    source TEXT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

COMMENT ON TABLE election_key_dates IS
    'Election calendar landmarks (candidate-list closure, campaign window). '
    'Consumed by the fundamentals model (#31) Feature 8.';

COMMENT ON COLUMN election_key_dates.candidate_list_closed_at IS
    'Date the TSE candidate registry closed for this election. Used as the '
    'pre/post-finalisation cutoff in the fundamentals polling-environment flag.';

-- Seed the round-1 row for each backfilled cycle. Inserts depend on the
-- corresponding elections row existing; loaders may not have populated every
-- cycle yet, so we resolve via subquery and skip silently when the source
-- row is absent. Cycles whose elections row arrives later can be seeded by
-- a follow-up DML migration.
INSERT INTO election_key_dates (election_id, candidate_list_closed_at, campaign_start_at, campaign_end_at, source)
SELECT e.election_id, d.closed_at, d.campaign_start, d.campaign_end, d.src
FROM (VALUES
    (2007::SMALLINT, DATE '2007-05-02', DATE '2007-05-02', DATE '2007-09-07', 'TSE Convocatoria Elecciones Generales 2007'),
    (2011::SMALLINT, DATE '2011-05-02', DATE '2011-05-02', DATE '2011-09-09', 'TSE Convocatoria Elecciones Generales 2011'),
    (2015::SMALLINT, DATE '2015-05-02', DATE '2015-05-02', DATE '2015-09-04', 'TSE Convocatoria Elecciones Generales 2015'),
    (2019::SMALLINT, DATE '2019-05-18', DATE '2019-05-18', DATE '2019-06-13', 'TSE Convocatoria Elecciones Generales 2019'),
    (2023::SMALLINT, DATE '2023-03-25', DATE '2023-03-26', DATE '2023-06-22', 'TSE Convocatoria Elecciones Generales 2023')
) AS d(cycle, closed_at, campaign_start, campaign_end, src)
JOIN elections e ON e.cycle = d.cycle AND e.round = 1
ON CONFLICT (election_id) DO NOTHING;

-- +goose Down
DROP TABLE IF EXISTS election_key_dates;
