package handlers_test

import (
	"bytes"
	"context"
	"encoding/json"
	"errors"
	"net/http"
	"net/http/httptest"
	"strings"
	"testing"
	"time"

	"github.com/jlcp89/polityk/internal/handlers"
	"github.com/jlcp89/polityk/internal/middleware"
)

type fakeForecastReader struct {
	forecast *handlers.PresidentialForecast
	err      error
}

func (f fakeForecastReader) LatestPublishedPresidential(_ context.Context) (*handlers.PresidentialForecast, error) {
	return f.forecast, f.err
}

// canonicalPayload mirrors the ADR-014 contract: the writer (#33) is
// responsible for putting run_id, model_version and generated_at at the top
// level. The handler returns payload bytes verbatim — the test asserts
// byte-for-byte equality.
const canonicalPayload = `{"run_id":"3f4e7c0a-1234-5678-9abc-def012345678","model_version":"0.1.0","generated_at":"2027-06-01T12:00:00-06:00","race":{"type":"presidential"},"candidates":[{"candidate_id":1,"name":"Alfa","vote_share_quantiles":{"p05":0.18,"p10":0.20,"p25":0.23,"p50":0.27,"p75":0.31,"p90":0.34,"p95":0.36}}],"runoff_matrix":[],"interventions_applied":[],"methodology_url":"https://polityk.gt/v1/methodology"}`

func TestPresidentialForecast_HappyPath_ReturnsPayloadByteForByte(t *testing.T) {
	t.Parallel()

	reader := fakeForecastReader{forecast: &handlers.PresidentialForecast{
		Payload:      []byte(canonicalPayload),
		RunID:        "3f4e7c0a-1234-5678-9abc-def012345678",
		ModelVersion: "0.1.0",
		GeneratedAt:  time.Date(2027, 6, 1, 18, 0, 0, 0, time.UTC),
	}}

	req := httptest.NewRequest(http.MethodGet, "/v1/forecast/presidential", nil)
	rec := httptest.NewRecorder()
	handlers.NewPresidentialForecast(reader).ServeHTTP(rec, req)

	if got, want := rec.Code, http.StatusOK; got != want {
		t.Fatalf("status: got %d want %d (body=%q)", got, want, rec.Body.String())
	}
	if got := rec.Body.Bytes(); !bytes.Equal(got, []byte(canonicalPayload)) {
		t.Fatalf("payload not byte-for-byte:\n got %q\nwant %q", got, canonicalPayload)
	}
	ct := rec.Header().Get("Content-Type")
	if !strings.HasPrefix(ct, "application/json") {
		t.Fatalf("content-type: got %q want application/json prefix", ct)
	}

	// ADR-014 contract: the payload itself carries run_id, model_version
	// and generated_at at top level. Asserting these proves the test
	// fixture matches the contract that the writer (#33) must honour.
	var body map[string]any
	if err := json.Unmarshal(rec.Body.Bytes(), &body); err != nil {
		t.Fatalf("decode payload: %v", err)
	}
	for _, field := range []string{"run_id", "model_version", "generated_at"} {
		if _, ok := body[field]; !ok {
			t.Errorf("payload missing top-level field %q", field)
		}
	}
}

func TestPresidentialForecast_NoPublishedRow_Returns404(t *testing.T) {
	t.Parallel()

	reader := fakeForecastReader{forecast: nil, err: nil}

	req := httptest.NewRequest(http.MethodGet, "/v1/forecast/presidential", nil)
	rec := httptest.NewRecorder()
	handlers.NewPresidentialForecast(reader).ServeHTTP(rec, req)

	if got, want := rec.Code, http.StatusNotFound; got != want {
		t.Fatalf("status: got %d want %d (body=%q)", got, want, rec.Body.String())
	}
	ct := rec.Header().Get("Content-Type")
	if !strings.HasPrefix(ct, "application/json") {
		t.Fatalf("content-type: got %q want application/json prefix", ct)
	}
	var body map[string]string
	if err := json.Unmarshal(rec.Body.Bytes(), &body); err != nil {
		t.Fatalf("decode body: %v (raw=%q)", err, rec.Body.String())
	}
	if got, want := body["error"], "no_forecast_available"; got != want {
		t.Fatalf("error field: got %q want %q", got, want)
	}
}

func TestPresidentialForecast_ReaderError_Returns500(t *testing.T) {
	t.Parallel()

	reader := fakeForecastReader{err: errors.New("connection refused")}

	req := httptest.NewRequest(http.MethodGet, "/v1/forecast/presidential", nil)
	rec := httptest.NewRecorder()
	handlers.NewPresidentialForecast(reader).ServeHTTP(rec, req)

	if got, want := rec.Code, http.StatusInternalServerError; got != want {
		t.Fatalf("status: got %d want %d (body=%q)", got, want, rec.Body.String())
	}
}

func TestPresidentialForecast_NilReader_Returns503(t *testing.T) {
	t.Parallel()

	req := httptest.NewRequest(http.MethodGet, "/v1/forecast/presidential", nil)
	rec := httptest.NewRecorder()
	handlers.NewPresidentialForecast(nil).ServeHTTP(rec, req)

	if got, want := rec.Code, http.StatusServiceUnavailable; got != want {
		t.Fatalf("status: got %d want %d (body=%q)", got, want, rec.Body.String())
	}
	var body map[string]string
	if err := json.Unmarshal(rec.Body.Bytes(), &body); err != nil {
		t.Fatalf("decode body: %v", err)
	}
	if body["error"] != "db_unavailable" {
		t.Fatalf("error field: got %q want %q", body["error"], "db_unavailable")
	}
}

// TestPresidentialForecast_BlackoutMiddlewareWins mirrors the production wiring
// (cmd/api/main.go) so the issue-#9 acceptance criterion "BLACKOUT_ENABLED=true
// overrides and returns 503 (middleware wins)" is verified end-to-end.
func TestPresidentialForecast_BlackoutMiddlewareWins(t *testing.T) {
	// No t.Parallel(): t.Setenv mutates process-wide state.
	reader := fakeForecastReader{forecast: &handlers.PresidentialForecast{
		Payload: []byte(canonicalPayload),
	}}
	forecastMux := http.NewServeMux()
	forecastMux.HandleFunc("GET /v1/forecast/presidential", handlers.NewPresidentialForecast(reader))
	root := http.NewServeMux()
	root.Handle("/v1/forecast/", middleware.Blackout(forecastMux))

	t.Run("blackout_off_returns_payload", func(t *testing.T) {
		t.Setenv("BLACKOUT_ENABLED", "false")
		req := httptest.NewRequest(http.MethodGet, "/v1/forecast/presidential", nil)
		rec := httptest.NewRecorder()
		root.ServeHTTP(rec, req)
		if got, want := rec.Code, http.StatusOK; got != want {
			t.Fatalf("status: got %d want %d (body=%q)", got, want, rec.Body.String())
		}
		if !bytes.Equal(rec.Body.Bytes(), []byte(canonicalPayload)) {
			t.Fatalf("payload: got %q want %q", rec.Body.String(), canonicalPayload)
		}
	})

	t.Run("blackout_on_returns_503", func(t *testing.T) {
		t.Setenv("BLACKOUT_ENABLED", "true")
		req := httptest.NewRequest(http.MethodGet, "/v1/forecast/presidential", nil)
		rec := httptest.NewRecorder()
		root.ServeHTTP(rec, req)
		if got, want := rec.Code, http.StatusServiceUnavailable; got != want {
			t.Fatalf("status: got %d want %d (body=%q)", got, want, rec.Body.String())
		}
		var body map[string]string
		if err := json.Unmarshal(rec.Body.Bytes(), &body); err != nil {
			t.Fatalf("decode body: %v", err)
		}
		if body["error"] != "blackout" {
			t.Fatalf("error field: got %q want %q", body["error"], "blackout")
		}
		// Payload must NEVER leak during blackout, even when the
		// reader is wired and would happily return data.
		if bytes.Contains(rec.Body.Bytes(), []byte("vote_share_quantiles")) {
			t.Fatalf("blackout response leaked payload bytes: %q", rec.Body.String())
		}
	})
}
