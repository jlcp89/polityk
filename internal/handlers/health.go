// Package handlers contains the HTTP handlers for the polityk API.
package handlers

import (
	"context"
	"encoding/json"
	"log/slog"
	"net/http"
)

// DimensionsChecker reports whether the dimension tables have been seeded.
// Issue #14 will widen this into a fuller `HealthChecker` (DB connectivity,
// last forecast, last scrape per source); for issue #2 we only need to know
// if `geographies` has rows.
type DimensionsChecker interface {
	DimensionsSeeded(ctx context.Context) (bool, error)
}

// FactsChecker reports whether the race-specific fact tables exist (i.e. the
// 0003 migration has been applied). Issue #3 surfaces this on /v1/health as
// `db_facts_ready` so contributors and the Android tab logic in #44 can
// distinguish a pre-migration DB from a post-migration one.
type FactsChecker interface {
	FactsReady(ctx context.Context) (bool, error)
}

// NewHealth returns the /v1/health handler. Both checkers are optional;
// passing nil for either omits the corresponding field — useful for boot
// before the DB connection is wired in, and for tests that don't need a
// database.
func NewHealth(dims DimensionsChecker, facts FactsChecker) http.HandlerFunc {
	return func(w http.ResponseWriter, r *http.Request) {
		body := map[string]any{"status": "ok"}
		if dims != nil {
			seeded, err := dims.DimensionsSeeded(r.Context())
			if err != nil {
				slog.Warn("health_dimensions_check_failed", "err", err)
				body["db_dimensions_seeded"] = false
			} else {
				body["db_dimensions_seeded"] = seeded
			}
		}
		if facts != nil {
			ready, err := facts.FactsReady(r.Context())
			if err != nil {
				slog.Warn("health_facts_check_failed", "err", err)
				body["db_facts_ready"] = false
			} else {
				body["db_facts_ready"] = ready
			}
		}
		w.Header().Set("Content-Type", "application/json; charset=utf-8")
		w.WriteHeader(http.StatusOK)
		if err := json.NewEncoder(w).Encode(body); err != nil {
			slog.Error("health_encode_failed", "err", err)
		}
	}
}

// Health is the static fallback handler used when no DB checker is wired.
// Kept exported for callers that still reference it directly.
func Health(w http.ResponseWriter, r *http.Request) {
	NewHealth(nil, nil).ServeHTTP(w, r)
}
