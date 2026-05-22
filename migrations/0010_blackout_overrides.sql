-- 0010_blackout_overrides.sql
-- Issue #46: audit table for manual blackout flips per ADR-003.
--
-- The systemd timer is the primary mechanism for flipping BLACKOUT_ENABLED
-- on Fri 18:00 / off Sun 18:00. This table backs the manual-override CLI
-- (`cmd/blackout`) that operators use as a backup when the timer misfires
-- (DST, clock skew, false alarms). Every manual flip MUST land here so the
-- log is defensible: who flipped it, when, why.
--
-- Schema notes:
--   * action is a TEXT + CHECK constraint rather than CREATE TYPE so a future
--     fourth state (e.g. 'forced_off_emergency') is a one-line CHECK
--     amendment rather than a TYPE migration. Matches the run_kind pattern
--     used in 0006_operational.sql.
--   * reason / operator are NOT NULL + length > 0 CHECK so the audit row
--     can never be a meaningless empty string. The CLI defends `--reason`
--     non-empty at the boundary; the CHECK is the last line of defence.
--   * created_at defaults to now() so a row inserted from the CLI without
--     an explicit timestamp still records when the flip happened.
--   * The default index on the BIGSERIAL PK is enough for `ORDER BY
--     override_id DESC LIMIT 5` ('status' subcommand). No secondary
--     indices needed at this scale (<= O(thousand) rows in a cycle).

-- +goose Up
CREATE TABLE blackout_overrides (
    override_id BIGSERIAL PRIMARY KEY,
    action TEXT NOT NULL CHECK (action IN ('enabled', 'disabled')),
    reason TEXT NOT NULL CHECK (length(reason) > 0),
    operator TEXT NOT NULL CHECK (length(operator) > 0),
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- +goose Down
DROP TABLE IF EXISTS blackout_overrides;
