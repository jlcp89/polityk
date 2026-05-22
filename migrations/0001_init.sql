-- 0001_init.sql
-- Issue #1: bootstrap the goose harness. No DDL — schema work starts in #2.
-- A SELECT 1 keeps the migration non-empty so goose records a real statement
-- in goose_db_version, not a parse-time noop.

-- +goose Up
SELECT 1;

-- +goose Down
SELECT 1;
