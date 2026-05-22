// Package middleware contains HTTP middleware for the polityk API.
package middleware

import (
	"bytes"
	"errors"
	"io/fs"
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

// blackoutFlagFileEnv names a filesystem path the middleware additionally
// consults on each request. The manual-override CLI (#46) writes the
// canonical boolean to this file so a single `blackout enable` is visible
// to the running API process within one request — without restarting the
// service or mutating its environment. When the env var is unset, the
// middleware falls back to the env-var-only path used by the systemd timer.
const blackoutFlagFileEnv = "BLACKOUT_FLAG_FILE"

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

// blackoutActive returns true when BLACKOUT_ENABLED (or the file at
// BLACKOUT_FLAG_FILE, when set) parses as a truthy bool.
//
// Source precedence:
//  1. If BLACKOUT_FLAG_FILE points at a readable file, its trimmed contents
//     are parsed as the boolean. A present-but-unparseable value is treated
//     as off (fail-open — a stuck-on blackout would silently break the
//     public-facing API and we'd rather take a known false-negative than an
//     unknown false-positive). The CLI guarantees the file contents are
//     always "true" or "false" with a trailing newline.
//  2. Otherwise the BLACKOUT_ENABLED env var is read directly. strconv.ParseBool
//     accepts 1/t/T/TRUE/true/True; anything else (including unset, empty, or
//     garbage) is treated as off.
//
// File presence — not file-contents truthiness — controls precedence. A file
// containing "false" still wins over an env var set to "true", because the
// CLI is the explicit override path and the env var is the systemd-timer
// fallback.
func blackoutActive() bool {
	if v, ok := blackoutFromFile(); ok {
		return v
	}
	v, err := strconv.ParseBool(os.Getenv(blackoutEnvVar))
	if err != nil {
		return false
	}
	return v
}

// blackoutFromFile returns (value, true) when BLACKOUT_FLAG_FILE is set and
// the file is readable. It returns (false, false) when the env var is unset
// or the file is missing (ENOENT) — both of which trigger the env-var
// fallback. A read error other than ENOENT is logged once per request and
// also returns (false, false) so the env-var fallback can still rescue a
// scheduled blackout.
func blackoutFromFile() (bool, bool) {
	path := os.Getenv(blackoutFlagFileEnv)
	if path == "" {
		return false, false
	}
	raw, err := os.ReadFile(path)
	if err != nil {
		if !errors.Is(err, fs.ErrNotExist) {
			slog.Warn("blackout_flag_file_read_failed", "path", path, "err", err)
		}
		return false, false
	}
	trimmed := string(bytes.TrimSpace(raw))
	if trimmed == "" {
		return false, true
	}
	parsed, err := strconv.ParseBool(trimmed)
	if err != nil {
		slog.Warn("blackout_flag_file_unparseable", "path", path, "value", trimmed)
		return false, true
	}
	return parsed, true
}

func writeBlackoutResponse(w http.ResponseWriter) {
	w.Header().Set("Content-Type", "application/json; charset=utf-8")
	w.WriteHeader(http.StatusServiceUnavailable)
	if _, err := w.Write([]byte(blackoutBody)); err != nil {
		slog.Error("blackout_write_failed", "err", err)
	}
}
