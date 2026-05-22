// Package macro contains the four macro-indicator scrapers (Banguat, INE,
// SEGEPLAN, MINFIN) that feed the fundamentals layer (#31) per ADR-004 +
// ADR-011. Each scraper fetches a published CSV feed from its institution,
// parses it into Indicator rows, UPSERTs them into macro_indicators
// (migration 0007), and stamps scrape_runs with the source's canonical tag.
//
// Production endpoints are configurable on each scraper Client so the
// production wiring can point at the real banguat.gob.gt / ine.gob.gt /
// segeplan.gob.gt / minfin.gob.gt feeds while tests inject an httptest URL.
// The fixture-driven smoke tests in *_test.go cover the per-source happy
// path -- the integration test in macro_integration_test.go round-trips
// migration 0007 + a real Postgres write against a live DB.
package macro

import (
	"context"
	"database/sql"
	"errors"
	"fmt"
	"net/http"
	"time"
)

// Canonical scrape_runs.source identifiers + CHECK values for macro_indicators.source.
const (
	SourceBanguat  = "banguat"
	SourceINE      = "ine"
	SourceSEGEPLAN = "segeplan"
	SourceMINFIN   = "minfin"
)

// DefaultUserAgent identifies the polityk scraper to upstream macro feeds
// per docs/requirement.md's "Operational guardrails" section. Mirrors the
// form used by the RSS aggregator (#16) and TSE party-list scraper (#15).
const DefaultUserAgent = "PolitykForecastBot/0.1 (+https://github.com/jlcp89/polityk; macro-indicators)"

const (
	defaultHTTPTimeout = 30 * time.Second
)

// Indicator is one row destined for macro_indicators. Source is filled in
// by the scraper that owns it; the per-source parsers only set the other
// fields.
type Indicator struct {
	Source     string
	Code       string
	ObservedAt time.Time
	Value      float64
	Unit       string
}

// Validate enforces the schema's NOT NULL + CHECK contract before the DB
// round-trip so a malformed parser fails loudly in the scraper rather than
// surfacing as a constraint error 200ms later.
func (i Indicator) Validate() error {
	switch i.Source {
	case SourceBanguat, SourceINE, SourceSEGEPLAN, SourceMINFIN:
	default:
		return fmt.Errorf("invalid source %q", i.Source)
	}
	if i.Code == "" {
		return errors.New("empty code")
	}
	if i.ObservedAt.IsZero() {
		return errors.New("zero observed_at")
	}
	return nil
}

// Upsert writes the indicator rows idempotently. Duplicates on
// (source, code, observed_at) are rejected silently per the migration's
// UNIQUE constraint -- ON CONFLICT DO NOTHING gives us upsert semantics
// without re-running the value check. Returns (inserted, total) where
// total counts every row supplied (so callers can log "5 ingested, 2 new").
func Upsert(ctx context.Context, db *sql.DB, rows []Indicator) (inserted int, err error) {
	if db == nil {
		return 0, nil
	}
	const stmt = `
        INSERT INTO macro_indicators (source, code, observed_at, value, unit)
        VALUES ($1, $2, $3, $4, $5)
        ON CONFLICT (source, code, observed_at) DO NOTHING
        RETURNING indicator_id
    `
	for _, r := range rows {
		if err := r.Validate(); err != nil {
			return inserted, fmt.Errorf("validate %s/%s: %w", r.Source, r.Code, err)
		}
		var id int64
		scanErr := db.QueryRowContext(ctx, stmt,
			r.Source, r.Code, r.ObservedAt, r.Value, r.Unit,
		).Scan(&id)
		if errors.Is(scanErr, sql.ErrNoRows) {
			continue // duplicate -- ON CONFLICT DO NOTHING
		}
		if scanErr != nil {
			return inserted, fmt.Errorf("insert %s/%s/%s: %w",
				r.Source, r.Code, r.ObservedAt.Format("2006-01-02"), scanErr)
		}
		inserted++
	}
	return inserted, nil
}

// StampScrapeRun UPSERTs scrape_runs for source. Mirrors the helper in
// internal/scrapers/{tse,rss}/ -- duplicated so each scraper subpackage
// stays independently testable.
func StampScrapeRun(ctx context.Context, db *sql.DB, source string, success bool, errMsg string) error {
	if db == nil {
		return nil
	}
	const stmt = `
        INSERT INTO scrape_runs (source, last_run_at, success, error_message)
        VALUES ($1, now(), $2, NULLIF($3, ''))
        ON CONFLICT (source) DO UPDATE
        SET last_run_at = excluded.last_run_at,
            success = excluded.success,
            error_message = excluded.error_message
    `
	if _, err := db.ExecContext(ctx, stmt, source, success, errMsg); err != nil {
		return fmt.Errorf("stamp scrape_runs: %w", err)
	}
	return nil
}

// newHTTPClient returns the shared default HTTP client. Callers may override
// per-source for testing.
func newHTTPClient() *http.Client {
	return &http.Client{Timeout: defaultHTTPTimeout}
}
