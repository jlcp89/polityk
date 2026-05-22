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

// NewHealth returns the /v1/health handler. If checker is nil the handler
// reports only the static `{"status":"ok"}` payload — useful for boot before
// the DB connection is wired in, and for tests that don't need a database.
func NewHealth(checker DimensionsChecker) http.HandlerFunc {
	return func(w http.ResponseWriter, r *http.Request) {
		body := map[string]any{"status": "ok"}
		if checker != nil {
			seeded, err := checker.DimensionsSeeded(r.Context())
			if err != nil {
				slog.Warn("health_dimensions_check_failed", "err", err)
				body["db_dimensions_seeded"] = false
			} else {
				body["db_dimensions_seeded"] = seeded
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
	NewHealth(nil).ServeHTTP(w, r)
}
