package store

import (
	"context"
	"database/sql"
	"errors"
	"fmt"
	"strings"
	"time"
)

// HealthInfo is the database/sql-backed implementation of
// handlers.HealthInfoReader for issue #14. Three queries, one per field on the
// `/v1/health` body:
//
//   - Ping: db.PingContext — gates the 503 short-circuit.
//   - LastPublishedForecastAt: MAX(generated_at) over published forecasts.
//   - LastScrapeBySource: scrape_runs lookup for a known set of source keys.
//
// Each query is intentionally narrow; the handler degrades a per-field error
// to a null in the JSON response rather than tripping the 503.
type HealthInfo struct {
	DB *sql.DB
}

// Ping is a thin pass-through to db.PingContext. Health uses it as the
// single source of truth for the `db_connected` field, so any wrapping
// here would obscure the real connectivity state.
func (h *HealthInfo) Ping(ctx context.Context) error {
	if h == nil || h.DB == nil {
		return errors.New("health: nil db")
	}
	return h.DB.PingContext(ctx)
}

// LastPublishedForecastAt returns MAX(generated_at) over forecasts with
// is_published=TRUE, or (nil, nil) when no published row exists. A missing
// `forecasts` table (migration 0006 not applied) surfaces as an error so the
// handler can degrade to `null`.
func (h *HealthInfo) LastPublishedForecastAt(ctx context.Context) (*time.Time, error) {
	if h == nil || h.DB == nil {
		return nil, errors.New("health: nil db")
	}
	const q = `SELECT MAX(generated_at) FROM forecasts WHERE is_published = TRUE`
	var ts sql.NullTime
	if err := h.DB.QueryRowContext(ctx, q).Scan(&ts); err != nil {
		return nil, fmt.Errorf("query last_published_forecast_at: %w", err)
	}
	if !ts.Valid {
		return nil, nil
	}
	t := ts.Time
	return &t, nil
}

// LastScrapeBySource looks up scrape_runs.last_run_at for every source in
// `sources` in a single round-trip. Sources absent from the table are simply
// missing from the returned map (the handler fills them with nil). A missing
// `scrape_runs` table surfaces as an error.
func (h *HealthInfo) LastScrapeBySource(ctx context.Context, sources []string) (map[string]*time.Time, error) {
	if h == nil || h.DB == nil {
		return nil, errors.New("health: nil db")
	}
	out := make(map[string]*time.Time, len(sources))
	if len(sources) == 0 {
		return out, nil
	}
	// Manual placeholder expansion keeps us off pq.Array / pgtype helpers;
	// the source list is small (3 entries today) so the query stays tiny.
	placeholders := make([]string, 0, len(sources))
	args := make([]any, 0, len(sources))
	for i, s := range sources {
		placeholders = append(placeholders, fmt.Sprintf("$%d", i+1))
		args = append(args, s)
	}
	q := fmt.Sprintf(
		`SELECT source, last_run_at FROM scrape_runs WHERE source IN (%s)`,
		strings.Join(placeholders, ","),
	)
	rows, err := h.DB.QueryContext(ctx, q, args...)
	if err != nil {
		return nil, fmt.Errorf("query scrape_runs: %w", err)
	}
	defer func() { _ = rows.Close() }()
	for rows.Next() {
		var source string
		var lastRunAt time.Time
		if err := rows.Scan(&source, &lastRunAt); err != nil {
			return nil, fmt.Errorf("scan scrape_runs row: %w", err)
		}
		t := lastRunAt
		out[source] = &t
	}
	if err := rows.Err(); err != nil {
		return nil, fmt.Errorf("iterate scrape_runs rows: %w", err)
	}
	return out, nil
}
