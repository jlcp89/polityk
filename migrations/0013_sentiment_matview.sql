-- 0009_sentiment_matview.sql
-- Issue #28: ensure the `sentiment_per_source_subject` materialized view
-- (mean_score + dominant_label per (source_kind, source_id, subject_kind,
-- subject_id)) exists with the canonical shape that #28's scorer refreshes
-- at the end of each batch and that the fundamentals layer (#31) joins
-- against. ADR-015 fixes the per-sentence × per-entity grain on
-- `sentiment_scores`; this migration owns the aggregation view + the
-- unique index needed for `REFRESH MATERIALIZED VIEW CONCURRENTLY`.
--
-- Design notes
--   * dominant_label is the modal label; ties broken POS > NEG > NEU so
--     the view is deterministic across refreshes.
--   * The unique index keys on (source_kind, source_id, subject_kind,
--     subject_id) with NULLS NOT DISTINCT so subject_id IS NULL ("overall"
--     rows written when no entity resolves -- ADR-015) collapse to a
--     single row per source.
--   * Up: DROP MATERIALIZED VIEW IF EXISTS then CREATE. This keeps the
--     migration round-trip clean whether or not an earlier migration
--     already defined the view -- recreating is safe because the matview
--     stores no irreplaceable data (it is a pure aggregate over
--     `sentiment_scores`, refreshed by the scorer).
--   * Down: DROP MATERIALIZED VIEW IF EXISTS. The unique index lives
--     inside the matview namespace so dropping the matview drops the
--     index too.

-- +goose Up
DROP MATERIALIZED VIEW IF EXISTS sentiment_per_source_subject;

-- +goose StatementBegin
CREATE MATERIALIZED VIEW sentiment_per_source_subject AS
SELECT
    source_kind,
    source_id,
    subject_kind,
    subject_id,
    AVG(score)::NUMERIC AS mean_score,
    COUNT(*)::BIGINT AS sentence_count,
    (
        SELECT s2.label
        FROM sentiment_scores s2
        WHERE s2.source_kind = s.source_kind
          AND s2.source_id = s.source_id
          AND s2.subject_kind = s.subject_kind
          AND s2.subject_id IS NOT DISTINCT FROM s.subject_id
        GROUP BY s2.label
        ORDER BY COUNT(*) DESC,
                 CASE s2.label
                     WHEN 'POS' THEN 0
                     WHEN 'NEG' THEN 1
                     WHEN 'NEU' THEN 2
                 END
        LIMIT 1
    ) AS dominant_label
FROM sentiment_scores s
GROUP BY source_kind, source_id, subject_kind, subject_id;
-- +goose StatementEnd

CREATE UNIQUE INDEX sentiment_per_source_subject_pk
    ON sentiment_per_source_subject (source_kind, source_id, subject_kind, subject_id)
    NULLS NOT DISTINCT;

-- +goose Down
DROP MATERIALIZED VIEW IF EXISTS sentiment_per_source_subject;
