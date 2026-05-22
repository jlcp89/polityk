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

// FactsChecker reports whether the three race-specific fact tables introduced
// by migration 0003 exist. "Exist" — not "populated" — because the truth
// loaders in #19–#22 land later; /v1/health just needs to confirm the schema
// is in place.
type FactsChecker struct {
	DB *sql.DB
}

// FactsReady returns true iff `presidential_results`, `congress_results`, and
// `municipal_results` are all present in the current database.
func (c *FactsChecker) FactsReady(ctx context.Context) (bool, error) {
	const q = `
		SELECT COUNT(*)
		FROM information_schema.tables
		WHERE table_schema = current_schema()
		  AND table_name IN ('presidential_results', 'congress_results', 'municipal_results')
	`
	var count int
	if err := c.DB.QueryRowContext(ctx, q).Scan(&count); err != nil {
		return false, err
	}
	return count == 3, nil
}
