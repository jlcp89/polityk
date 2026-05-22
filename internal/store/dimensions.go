// Package store provides thin DB-backed implementations of the small
// query interfaces consumed by handlers. Per ADR-005 the project uses a
// single Postgres datastore via database/sql + jackc/pgx/v5/stdlib.
package store

import (
	"context"
	"database/sql"
)

// DimensionsChecker reports whether the dimension tables have been seeded.
// "Seeded" is defined as `geographies` having at least one row, per the
// issue-#2 acceptance criterion.
type DimensionsChecker struct {
	DB *sql.DB
}

// DimensionsSeeded returns true iff `SELECT COUNT(*) FROM geographies > 0`.
// A missing table — i.e. before the 0002 migration has been applied —
// surfaces as an error so /v1/health can report `false` cleanly.
func (c *DimensionsChecker) DimensionsSeeded(ctx context.Context) (bool, error) {
	var count int
	if err := c.DB.QueryRowContext(ctx, "SELECT COUNT(*) FROM geographies").Scan(&count); err != nil {
		return false, err
	}
	return count > 0, nil
}
