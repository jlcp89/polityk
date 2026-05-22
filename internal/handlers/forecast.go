package handlers

import (
	"context"
	"log/slog"
	"net/http"
	"time"
)

// PresidentialForecast is the row read from `forecasts` for the most recent
// is_published=TRUE presidential run. Payload is the raw JSONB bytes that the
// handler returns verbatim per ADR-006; the metadata fields are reserved for
// the ETag / Cache-Control middleware in #11 and for observability.
type PresidentialForecast struct {
	Payload      []byte
	RunID        string
	ModelVersion string
	GeneratedAt  time.Time
}

// ForecastReader fetches the latest published forecast row. A nil result with
// nil error means "no published row yet" — the handler maps that to a 404 per
// the issue-#9 contract (`{"error":"no_forecast_available"}`).
type ForecastReader interface {
	LatestPublishedPresidential(ctx context.Context) (*PresidentialForecast, error)
}

const (
	noForecastBody    = `{"error":"no_forecast_available"}`
	dbUnavailableBody = `{"error":"db_unavailable"}`
	internalErrorBody = `{"error":"internal"}`

	// Per ADR-007, congress and municipal forecasts are not live in v1.
	// The Android client (issue #44) reads these 404 bodies to hide the
	// corresponding tabs. The `available_in` field is intentionally a
	// fixed semver-ish version string, not a date, so the client can
	// surface "coming in v1.5" without depending on calendar dates.
	congressUnavailableBody  = `{"error":"race_type_not_available","race_type":"congress","available_in":"v1.5"}`
	municipalUnavailableBody = `{"error":"race_type_not_available","race_type":"municipal","available_in":"v2"}`
)

// NewPresidentialForecast returns the `GET /v1/forecast/presidential` handler.
//
// Per ADR-006 and ADR-014, the handler is read-only: it returns the JSONB
// `payload` byte-for-byte so the writer (#33) controls the response contract
// and the LISTEN/NOTIFY watcher (#10) can clear caches without parsing.
//
// nil reader (DATABASE_URL unset at boot) → 503 with `db_unavailable`. Real
// errors → 500. Missing row → 404. Happy path → 200 with the seeded payload.
func NewPresidentialForecast(r ForecastReader) http.HandlerFunc {
	return func(w http.ResponseWriter, req *http.Request) {
		w.Header().Set("Content-Type", "application/json; charset=utf-8")
		if r == nil {
			w.WriteHeader(http.StatusServiceUnavailable)
			_, _ = w.Write([]byte(dbUnavailableBody))
			return
		}
		forecast, err := r.LatestPublishedPresidential(req.Context())
		if err != nil {
			slog.Error("forecast_read_failed", "race_type", "presidential", "err", err)
			w.WriteHeader(http.StatusInternalServerError)
			_, _ = w.Write([]byte(internalErrorBody))
			return
		}
		if forecast == nil {
			slog.Info("forecast_not_available", "race_type", "presidential")
			w.WriteHeader(http.StatusNotFound)
			_, _ = w.Write([]byte(noForecastBody))
			return
		}
		w.WriteHeader(http.StatusOK)
		if _, err := w.Write(forecast.Payload); err != nil {
			slog.Error("forecast_write_failed", "err", err, "run_id", forecast.RunID)
		}
	}
}

// NewCongressForecast returns the `GET /v1/forecast/congress` handler.
//
// Per ADR-007 the congressional model is staged for v1.5 — until then this
// route returns 404 with a body the Android client (#44) keys on to hide
// the congress tab. Blackout middleware still wins: when BLACKOUT_ENABLED
// is on, the request short-circuits with 503 before reaching this handler.
func NewCongressForecast() http.HandlerFunc {
	return func(w http.ResponseWriter, _ *http.Request) {
		w.Header().Set("Content-Type", "application/json; charset=utf-8")
		w.WriteHeader(http.StatusNotFound)
		if _, err := w.Write([]byte(congressUnavailableBody)); err != nil {
			slog.Error("forecast_write_failed", "race_type", "congress", "err", err)
		}
	}
}

// NewMunicipalForecast returns the `GET /v1/forecast/municipal/{municipality_id}`
// handler.
//
// Per ADR-007 the municipal model is staged for v2 — the `{municipality_id}`
// path segment is captured by the router but ignored: every value yields the
// same 404. Blackout middleware still wins as with the congress route.
func NewMunicipalForecast() http.HandlerFunc {
	return func(w http.ResponseWriter, _ *http.Request) {
		w.Header().Set("Content-Type", "application/json; charset=utf-8")
		w.WriteHeader(http.StatusNotFound)
		if _, err := w.Write([]byte(municipalUnavailableBody)); err != nil {
			slog.Error("forecast_write_failed", "race_type", "municipal", "err", err)
		}
	}
}
