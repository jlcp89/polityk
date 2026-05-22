-- 0022_elections_is_provisional.sql
-- Issue #22: 2023 provisional ingest from TREP aggregates and TSE Acuerdos
-- 1659-2023 / 1361-2023.
--
-- The 2023 Memoria Electoral has not been published as of 2026-05; v1 must
-- work with provisional sources. Rows ingested from those sources are marked
-- `is_provisional = TRUE` so the model + /v1/methodology can disclose the
-- provisional status. When the 2023 Memoria publishes, a re-ingest path
-- (future issue) overwrites the rows and flips the flag to FALSE.
--
-- Default FALSE: every pre-2023 election row (and every future final-Memoria
-- ingest) is treated as definitive unless explicitly marked otherwise.

-- +goose Up
ALTER TABLE elections
    ADD COLUMN is_provisional BOOLEAN NOT NULL DEFAULT FALSE;

COMMENT ON COLUMN elections.is_provisional IS
    'TRUE when sourced from provisional TSE Acuerdos / TREP aggregates '
    '(2023 cycle in particular until the Memoria publishes).';

-- +goose Down
ALTER TABLE elections DROP COLUMN IF EXISTS is_provisional;
