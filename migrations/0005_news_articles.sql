-- 0005_news_articles.sql
-- Issue #16: introduce `news_articles` lazily — it is the first table the
-- RSS aggregator scraper needs and #5 (the planned operational schema for
-- news + social + sentiment) has not yet landed. Follows the precedent set
-- by #19, which introduced `scrape_runs` lazily for the same reason.
--
-- Shape per #16 acceptance criteria + ADR-015:
--   - one row per (outlet, url); url is globally unique to keep dedup simple
--   - body_text is NOT NULL and length > 0; the scraper skips articles whose
--     body extraction fails so we never persist an empty article
--   - published_at is TIMESTAMPTZ NULL because some feeds omit pubDate
--   - fetched_at is the moment the scraper successfully stored the row
--
-- When #5 lands it must either be a no-op on this table (preserve the
-- columns + UNIQUE + CHECK) or it must add columns/indexes only. Any rename
-- of `news_articles` should be coordinated with the RSS scraper at the same
-- commit.

-- +goose Up
CREATE TABLE news_articles (
    article_id BIGSERIAL PRIMARY KEY,
    outlet TEXT NOT NULL,
    url TEXT NOT NULL UNIQUE,
    title TEXT NOT NULL,
    body_text TEXT NOT NULL CHECK (length(body_text) > 0),
    published_at TIMESTAMPTZ,
    fetched_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX news_articles_outlet_idx ON news_articles (outlet);
CREATE INDEX news_articles_published_at_idx ON news_articles (published_at);

-- +goose Down
DROP TABLE IF EXISTS news_articles;
