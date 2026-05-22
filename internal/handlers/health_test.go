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

type fakeDimsChecker struct {
	seeded bool
	err    error
}

func (f fakeDimsChecker) DimensionsSeeded(_ context.Context) (bool, error) {
	return f.seeded, f.err
}

type fakeFactsChecker struct {
	ready bool
	err   error
}

func (f fakeFactsChecker) FactsReady(_ context.Context) (bool, error) {
	return f.ready, f.err
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
	if _, present := body["db_facts_ready"]; present {
		t.Fatalf("db_facts_ready should be omitted when no checker is wired; body=%v", body)
	}
}

func TestHealth_WithDimensionsChecker(t *testing.T) {
	t.Parallel()

	tests := []struct {
		name       string
		checker    DimensionsChecker
		wantSeeded bool
	}{
		{name: "seeded", checker: fakeDimsChecker{seeded: true}, wantSeeded: true},
		{name: "unseeded", checker: fakeDimsChecker{seeded: false}, wantSeeded: false},
		{name: "checker_error_reports_false", checker: fakeDimsChecker{err: errors.New("db down")}, wantSeeded: false},
	}

	for _, tt := range tests {
		tt := tt
		t.Run(tt.name, func(t *testing.T) {
			t.Parallel()
			req := httptest.NewRequest(http.MethodGet, "/v1/health", nil)
			rec := httptest.NewRecorder()

			NewHealth(tt.checker, nil).ServeHTTP(rec, req)

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
			if _, present := body["db_facts_ready"]; present {
				t.Fatalf("db_facts_ready should be omitted when no facts checker is wired; body=%v", body)
			}
		})
	}
}

func TestHealth_WithFactsChecker(t *testing.T) {
	t.Parallel()

	tests := []struct {
		name      string
		checker   FactsChecker
		wantReady bool
	}{
		{name: "ready", checker: fakeFactsChecker{ready: true}, wantReady: true},
		{name: "not_ready", checker: fakeFactsChecker{ready: false}, wantReady: false},
		{name: "checker_error_reports_false", checker: fakeFactsChecker{err: errors.New("missing table")}, wantReady: false},
	}

	for _, tt := range tests {
		tt := tt
		t.Run(tt.name, func(t *testing.T) {
			t.Parallel()
			req := httptest.NewRequest(http.MethodGet, "/v1/health", nil)
			rec := httptest.NewRecorder()

			NewHealth(nil, tt.checker).ServeHTTP(rec, req)

			if got, want := rec.Code, http.StatusOK; got != want {
				t.Fatalf("status: got %d want %d", got, want)
			}
			var body map[string]any
			if err := json.Unmarshal(rec.Body.Bytes(), &body); err != nil {
				t.Fatalf("decode body: %v (raw=%q)", err, rec.Body.String())
			}
			got, ok := body["db_facts_ready"].(bool)
			if !ok {
				t.Fatalf("db_facts_ready missing or not a bool; body=%v", body)
			}
			if got != tt.wantReady {
				t.Fatalf("db_facts_ready: got %v want %v", got, tt.wantReady)
			}
		})
	}
}

func TestHealth_WithBothCheckers(t *testing.T) {
	t.Parallel()

	req := httptest.NewRequest(http.MethodGet, "/v1/health", nil)
	rec := httptest.NewRecorder()

	NewHealth(fakeDimsChecker{seeded: true}, fakeFactsChecker{ready: true}).ServeHTTP(rec, req)

	if got, want := rec.Code, http.StatusOK; got != want {
		t.Fatalf("status: got %d want %d", got, want)
	}
	var body map[string]any
	if err := json.Unmarshal(rec.Body.Bytes(), &body); err != nil {
		t.Fatalf("decode body: %v (raw=%q)", err, rec.Body.String())
	}
	if body["db_dimensions_seeded"] != true {
		t.Fatalf("db_dimensions_seeded: got %v want true", body["db_dimensions_seeded"])
	}
	if body["db_facts_ready"] != true {
		t.Fatalf("db_facts_ready: got %v want true", body["db_facts_ready"])
	}
}
