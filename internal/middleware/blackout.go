// Package middleware contains HTTP middleware for the polityk API.
package middleware

import (
	"log/slog"
	"net/http"
	"os"
	"strconv"
)

// blackoutEnvVar is the env var read on every request to decide whether the
// legal-blackout short-circuit is active. Read fresh per request so that a
// systemd-timer flip (or the manual override CLI in #46) takes effect on the
// very next request — never cached in process memory.
const blackoutEnvVar = "BLACKOUT_ENABLED"

// blackoutBody is the canonical 503 response body shipped to clients during
// the Tribunal Supremo Electoral's mandated silencio electoral.
// The Spanish wording is the source of truth for downstream consumers
// (Android splash falls back to in-app strings — see #43 — but the API still
// returns this for any non-app caller).
const blackoutBody = `{"error":"blackout","message":"Las previsiones están suspendidas por mandato del Tribunal Supremo Electoral durante el silencio electoral (36 h antes de cada vuelta). Vuelva después del cierre de votación."}`

// Blackout wraps next so that whenever BLACKOUT_ENABLED is truthy the
// request short-circuits to HTTP 503 with a Spanish-language body.
//
// Per ADR-003, polityk must suppress forecast output during the
// constitutionally-mandated 36 h pre-vote silence (expediente 1699-2018).
// Mount this middleware only on `/v1/forecast/*`; `/v1/health` and
// `/v1/methodology` MUST stay reachable during a blackout so monitoring and
// methodology disclosure are unaffected.
func Blackout(next http.Handler) http.Handler {
	return http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		if blackoutActive() {
			writeBlackoutResponse(w)
			return
		}
		next.ServeHTTP(w, r)
	})
}

// blackoutActive returns true when BLACKOUT_ENABLED parses as a truthy bool.
// strconv.ParseBool accepts 1/t/T/TRUE/true/True; anything else (including
// unset, empty, or garbage) is treated as off — fail-open on the env, since
// a stuck-on blackout would silently break the public-facing API.
// The on-state is reachable only via an explicit truthy value.
func blackoutActive() bool {
	v, err := strconv.ParseBool(os.Getenv(blackoutEnvVar))
	if err != nil {
		return false
	}
	return v
}

func writeBlackoutResponse(w http.ResponseWriter) {
	w.Header().Set("Content-Type", "application/json; charset=utf-8")
	w.WriteHeader(http.StatusServiceUnavailable)
	if _, err := w.Write([]byte(blackoutBody)); err != nil {
		slog.Error("blackout_write_failed", "err", err)
	}
}
