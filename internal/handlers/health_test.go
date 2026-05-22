package handlers

import (
	"context"
	"encoding/json"
	"errors"
	"net/http"
	"net/http/httptest"
	"strings"
	"testing"
)

type fakeChecker struct {
	seeded bool
	err    error
}

func (f fakeChecker) DimensionsSeeded(_ context.Context) (bool, error) {
	return f.seeded, f.err
}

func TestHealth_StaticFallback_ReturnsOK(t *testing.T) {
	t.Parallel()

	req := httptest.NewRequest(http.MethodGet, "/v1/health", nil)
	rec := httptest.NewRecorder()

	Health(rec, req)

	if got, want := rec.Code, http.StatusOK; got != want {
		t.Fatalf("status: got %d want %d", got, want)
	}
	ct := rec.Header().Get("Content-Type")
	if !strings.HasPrefix(ct, "application/json") {
		t.Fatalf("content-type: got %q want application/json prefix", ct)
	}

	var body map[string]any
	if err := json.Unmarshal(rec.Body.Bytes(), &body); err != nil {
		t.Fatalf("decode body: %v (raw=%q)", err, rec.Body.String())
	}
	if got, want := body["status"], "ok"; got != want {
		t.Fatalf("status field: got %v want %q", got, want)
	}
	if _, present := body["db_dimensions_seeded"]; present {
		t.Fatalf("db_dimensions_seeded should be omitted when no checker is wired; body=%v", body)
	}
}

func TestHealth_WithChecker(t *testing.T) {
	t.Parallel()

	tests := []struct {
		name        string
		checker     DimensionsChecker
		wantSeeded  bool
	}{
		{name: "seeded", checker: fakeChecker{seeded: true}, wantSeeded: true},
		{name: "unseeded", checker: fakeChecker{seeded: false}, wantSeeded: false},
		{name: "checker_error_reports_false", checker: fakeChecker{err: errors.New("db down")}, wantSeeded: false},
	}

	for _, tt := range tests {
		tt := tt
		t.Run(tt.name, func(t *testing.T) {
			t.Parallel()
			req := httptest.NewRequest(http.MethodGet, "/v1/health", nil)
			rec := httptest.NewRecorder()

			NewHealth(tt.checker).ServeHTTP(rec, req)

			if got, want := rec.Code, http.StatusOK; got != want {
				t.Fatalf("status: got %d want %d", got, want)
			}
			var body map[string]any
			if err := json.Unmarshal(rec.Body.Bytes(), &body); err != nil {
				t.Fatalf("decode body: %v (raw=%q)", err, rec.Body.String())
			}
			if got, want := body["status"], "ok"; got != want {
				t.Fatalf("status: got %v want %q", got, want)
			}
			got, ok := body["db_dimensions_seeded"].(bool)
			if !ok {
				t.Fatalf("db_dimensions_seeded missing or not a bool; body=%v", body)
			}
			if got != tt.wantSeeded {
				t.Fatalf("db_dimensions_seeded: got %v want %v", got, tt.wantSeeded)
			}
		})
	}
}
