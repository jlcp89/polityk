package middleware

import (
	"encoding/json"
	"net/http"
	"net/http/httptest"
	"strings"
	"testing"
)

const expectedBlackoutMessage = "Las previsiones están suspendidas por mandato del Tribunal Supremo Electoral durante el silencio electoral (36 h antes de cada vuelta). Vuelva después del cierre de votación."

func okHandler(w http.ResponseWriter, _ *http.Request) {
	w.Header().Set("Content-Type", "application/json; charset=utf-8")
	w.WriteHeader(http.StatusOK)
	_, _ = w.Write([]byte(`{"data":"ok"}`))
}

// TestBlackout_FlagStates table-drives every BLACKOUT_ENABLED value the
// middleware will see in production. t.Parallel is intentionally absent
// because t.Setenv mutates process-wide state.
func TestBlackout_FlagStates(t *testing.T) {
	tests := []struct {
		name       string
		envValue   string
		wantStatus int
	}{
		{"unset (empty) → pass through", "", http.StatusOK},
		{"false → pass through", "false", http.StatusOK},
		{"garbage → pass through (fail-open)", "maybe", http.StatusOK},
		{"true → 503", "true", http.StatusServiceUnavailable},
		{"TRUE → 503", "TRUE", http.StatusServiceUnavailable},
		{"1 → 503", "1", http.StatusServiceUnavailable},
	}
	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			t.Setenv("BLACKOUT_ENABLED", tt.envValue)
			req := httptest.NewRequest(http.MethodGet, "/v1/forecast/presidential", nil)
			rec := httptest.NewRecorder()
			Blackout(http.HandlerFunc(okHandler)).ServeHTTP(rec, req)
			if got := rec.Code; got != tt.wantStatus {
				t.Fatalf("status: got %d want %d (body=%q)", got, tt.wantStatus, rec.Body.String())
			}
		})
	}
}

// TestBlackout_503Body asserts the exact JSON contract the Android app
// relies on (#43). Any drift here is a breaking change for the client.
func TestBlackout_503Body(t *testing.T) {
	t.Setenv("BLACKOUT_ENABLED", "true")
	req := httptest.NewRequest(http.MethodGet, "/v1/forecast/presidential", nil)
	rec := httptest.NewRecorder()
	Blackout(http.HandlerFunc(okHandler)).ServeHTTP(rec, req)

	if got, want := rec.Code, http.StatusServiceUnavailable; got != want {
		t.Fatalf("status: got %d want %d", got, want)
	}
	ct := rec.Header().Get("Content-Type")
	if !strings.HasPrefix(ct, "application/json") {
		t.Fatalf("content-type: got %q want application/json prefix", ct)
	}

	var body map[string]string
	if err := json.Unmarshal(rec.Body.Bytes(), &body); err != nil {
		t.Fatalf("decode body: %v (raw=%q)", err, rec.Body.String())
	}
	if got, want := body["error"], "blackout"; got != want {
		t.Fatalf("error field: got %q want %q", got, want)
	}
	if got, want := body["message"], expectedBlackoutMessage; got != want {
		t.Fatalf("message field:\n got %q\nwant %q", got, want)
	}
}

// TestBlackout_DoesNotInvokeNextWhenActive guards against accidental fall
// through that would let a forecast payload leak during the blackout.
func TestBlackout_DoesNotInvokeNextWhenActive(t *testing.T) {
	t.Setenv("BLACKOUT_ENABLED", "true")
	called := false
	next := http.HandlerFunc(func(_ http.ResponseWriter, _ *http.Request) {
		called = true
	})
	req := httptest.NewRequest(http.MethodGet, "/v1/forecast/presidential", nil)
	rec := httptest.NewRecorder()
	Blackout(next).ServeHTTP(rec, req)
	if called {
		t.Fatalf("next handler must not be invoked while blackout is active")
	}
	if got := rec.Code; got != http.StatusServiceUnavailable {
		t.Fatalf("status: got %d want %d", got, http.StatusServiceUnavailable)
	}
}

func TestBlackout_InvokesNextWhenInactive(t *testing.T) {
	t.Setenv("BLACKOUT_ENABLED", "false")
	called := false
	next := http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		called = true
		okHandler(w, r)
	})
	req := httptest.NewRequest(http.MethodGet, "/v1/forecast/presidential", nil)
	rec := httptest.NewRecorder()
	Blackout(next).ServeHTTP(rec, req)
	if !called {
		t.Fatalf("next handler should be invoked when blackout is inactive")
	}
	if got := rec.Code; got != http.StatusOK {
		t.Fatalf("status: got %d want %d", got, http.StatusOK)
	}
}

// TestBlackout_FlagFlipMidTest proves the no-cache contract: flipping the
// env var changes the very next request's behaviour. This is what makes
// the systemd-timer model in ADR-003 safe — the API picks up the flip
// without restart.
func TestBlackout_FlagFlipMidTest(t *testing.T) {
	handler := Blackout(http.HandlerFunc(okHandler))
	doRequest := func() int {
		req := httptest.NewRequest(http.MethodGet, "/v1/forecast/presidential", nil)
		rec := httptest.NewRecorder()
		handler.ServeHTTP(rec, req)
		return rec.Code
	}

	t.Setenv("BLACKOUT_ENABLED", "false")
	if got := doRequest(); got != http.StatusOK {
		t.Fatalf("flag=false: got %d want %d", got, http.StatusOK)
	}

	t.Setenv("BLACKOUT_ENABLED", "true")
	if got := doRequest(); got != http.StatusServiceUnavailable {
		t.Fatalf("flag flipped to true: got %d want %d", got, http.StatusServiceUnavailable)
	}

	t.Setenv("BLACKOUT_ENABLED", "false")
	if got := doRequest(); got != http.StatusOK {
		t.Fatalf("flag flipped back to false: got %d want %d", got, http.StatusOK)
	}
}

// TestBlackout_MuxWiring mirrors the production wiring exactly: the
// middleware mounts on `/v1/forecast/` only, leaving `/v1/health` and
// `/v1/methodology` reachable regardless of the flag state.
func TestBlackout_MuxWiring(t *testing.T) {
	forecastMux := http.NewServeMux()
	forecastMux.HandleFunc("GET /v1/forecast/presidential", okHandler)
	forecastMux.HandleFunc("GET /v1/forecast/congress", okHandler)

	root := http.NewServeMux()
	root.HandleFunc("GET /v1/health", okHandler)
	root.HandleFunc("GET /v1/methodology", okHandler)
	root.Handle("/v1/forecast/", Blackout(forecastMux))

	tests := []struct {
		name     string
		flag     string
		path     string
		wantCode int
	}{
		{"off + health → 200", "false", "/v1/health", http.StatusOK},
		{"off + methodology → 200", "false", "/v1/methodology", http.StatusOK},
		{"off + presidential → 200", "false", "/v1/forecast/presidential", http.StatusOK},
		{"off + congress → 200", "false", "/v1/forecast/congress", http.StatusOK},
		{"on + health → 200", "true", "/v1/health", http.StatusOK},
		{"on + methodology → 200", "true", "/v1/methodology", http.StatusOK},
		{"on + presidential → 503", "true", "/v1/forecast/presidential", http.StatusServiceUnavailable},
		{"on + congress → 503", "true", "/v1/forecast/congress", http.StatusServiceUnavailable},
		{"on + unknown forecast subpath → 503", "true", "/v1/forecast/municipal/42", http.StatusServiceUnavailable},
	}
	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			t.Setenv("BLACKOUT_ENABLED", tt.flag)
			req := httptest.NewRequest(http.MethodGet, tt.path, nil)
			rec := httptest.NewRecorder()
			root.ServeHTTP(rec, req)
			if got := rec.Code; got != tt.wantCode {
				t.Fatalf("path=%s flag=%s: got %d want %d (body=%q)", tt.path, tt.flag, got, tt.wantCode, rec.Body.String())
			}
		})
	}
}
