-- 0005_news_sentiment.sql
-- Issue #5: news_articles, social_posts, sentiment_scores and the
-- sentiment_per_source_subject materialized view, per ADR-015.
--
-- The grain is per-sentence × per-entity so the fundamentals layer (#31)
-- can use differential sentiment (POS_A - POS_B) rather than overall valence.
-- An "overall" subject_kind row is written when no entity resolves; its
-- subject_id is NULL, so the UNIQUE constraint uses NULLS NOT DISTINCT
-- (Postgres 15+) to keep "one row per (source, sentence, overall)" enforced.

-- +goose Up
-- +goose StatementBegin
CREATE TYPE social_platform AS ENUM (
    'reddit',
    'youtube_comment',
    'telegram',
    'bluesky'
);
-- +goose StatementEnd

-- +goose StatementBegin
CREATE TYPE sentiment_source_kind AS ENUM (
    'article',
    'post'
);
-- +goose StatementEnd

-- +goose StatementBegin
CREATE TYPE sentiment_subject_kind AS ENUM (
    'candidate',
    'party',
    'overall'
);
-- +goose StatementEnd

-- +goose StatementBegin
CREATE TYPE sentiment_label AS ENUM (
    'POS',
    'NEG',
    'NEU'
);
-- +goose StatementEnd

CREATE TABLE news_articles (
    article_id BIGSERIAL PRIMARY KEY,
    source TEXT NOT NULL,
    url TEXT NOT NULL UNIQUE,
    published_at TIMESTAMPTZ,
    title TEXT,
    body_text TEXT,
    lang TEXT NOT NULL DEFAULT 'es',
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX news_articles_published_idx ON news_articles (published_at);
CREATE INDEX news_articles_source_idx ON news_articles (source);

CREATE TABLE social_posts (
    post_id BIGSERIAL PRIMARY KEY,
    platform social_platform NOT NULL,
    source_handle TEXT,
    url TEXT NOT NULL UNIQUE,
    published_at TIMESTAMPTZ,
    body_text TEXT,
    parent_post_id BIGINT REFERENCES social_posts (post_id) ON DELETE SET NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX social_posts_published_idx ON social_posts (published_at);
CREATE INDEX social_posts_platform_idx ON social_posts (platform);
CREATE INDEX social_posts_parent_idx ON social_posts (parent_post_id);

CREATE TABLE sentiment_scores (
    score_id BIGSERIAL PRIMARY KEY,
    source_kind sentiment_source_kind NOT NULL,
    source_id BIGINT NOT NULL,
    sentence_index SMALLINT NOT NULL CHECK (sentence_index >= 0),
    subject_kind sentiment_subject_kind NOT NULL,
    subject_id BIGINT,
    score NUMERIC NOT NULL,
    label sentiment_label NOT NULL,
    model_version TEXT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    CHECK (
        (subject_kind = 'overall' AND subject_id IS NULL)
        OR (subject_kind IN ('candidate', 'party') AND subject_id IS NOT NULL)
    ),
    UNIQUE NULLS NOT DISTINCT (source_kind, source_id, sentence_index, subject_kind, subject_id)
);

CREATE INDEX sentiment_scores_source_idx
    ON sentiment_scores (source_kind, source_id);
CREATE INDEX sentiment_scores_subject_idx
    ON sentiment_scores (subject_kind, subject_id);

-- The materialized view shape mirrors what #28's scorer refreshes at the end
-- of each batch and what the fundamentals layer (#31) joins against.
-- dominant_label is the modal label; ties are broken POS > NEG > NEU so the
-- view is deterministic across refreshes.
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

CREATE UNIQUE INDEX sentiment_per_source_subject_pk
    ON sentiment_per_source_subject (source_kind, source_id, subject_kind, subject_id)
    NULLS NOT DISTINCT;

-- +goose Down
DROP MATERIALIZED VIEW IF EXISTS sentiment_per_source_subject;
DROP TABLE IF EXISTS sentiment_scores;
DROP TABLE IF EXISTS social_posts;
DROP TABLE IF EXISTS news_articles;
DROP TYPE IF EXISTS sentiment_label;
DROP TYPE IF EXISTS sentiment_subject_kind;
DROP TYPE IF EXISTS sentiment_source_kind;
DROP TYPE IF EXISTS social_platform;
