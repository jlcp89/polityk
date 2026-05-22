-- 0001_init.up.sql
-- Issue #1: bootstrap the goose harness. No DDL — schema work starts in #2.
-- A SELECT 1 keeps the file non-empty so the migration is recorded in
-- goose_db_version with a real statement, not a parse-time noop.
SELECT 1;
