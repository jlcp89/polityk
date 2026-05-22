-- 0012_sentiment_schema.sql
-- Originally issue #5: news_articles + social_posts + sentiment_scores +
-- materialized view per ADR-015.
--
-- Scope after duplicate-migration resolution (2026-05-22):
--   * news_articles is owned by 0005_news_articles.sql (the canonical
--     RSS-aggregator shape with `outlet` column). Removed here.
--   * sentiment_per_source_subject materialized view is owned by
--     0013_sentiment_matview.sql (issue #28, idempotent DROP+CREATE).
--     Removed here.
--   * This migration retains: the four ENUM types, social_posts,
--     sentiment_scores. They are referenced by 0013 and by the scorer
--     in pipeline/sentiment/scorer.py.

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

-- +goose Down
DROP TABLE IF EXISTS sentiment_scores;
DROP TABLE IF EXISTS social_posts;
DROP TYPE IF EXISTS sentiment_label;
DROP TYPE IF EXISTS sentiment_subject_kind;
DROP TYPE IF EXISTS sentiment_source_kind;
DROP TYPE IF EXISTS social_platform;
