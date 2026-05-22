package store

import (
	"context"
	"database/sql"
	"errors"

	"github.com/jlcp89/polityk/internal/handlers"
)

// ForecastReader is the database/sql-backed implementation of
// handlers.ForecastReader. It returns the JSONB `payload` bytes plus the
// metadata fields described in the issue-#9 query exactly.
type ForecastReader struct {
	DB *sql.DB
}

// LatestPublishedPresidential runs the issue-#9 query verbatim and returns
// the row, or (nil, nil) when no published presidential forecast exists yet
// (the calibration gate in #36 may not have flipped is_published for any run).
func (r *ForecastReader) LatestPublishedPresidential(ctx context.Context) (*handlers.PresidentialForecast, error) {
	const q = `
		SELECT payload, run_id::text, model_version, generated_at
		FROM forecasts
		WHERE race_type = 'presidential' AND is_published = TRUE
		ORDER BY generated_at DESC
		LIMIT 1
	`
	var f handlers.PresidentialForecast
	err := r.DB.QueryRowContext(ctx, q).Scan(&f.Payload, &f.RunID, &f.ModelVersion, &f.GeneratedAt)
	if errors.Is(err, sql.ErrNoRows) {
		return nil, nil
	}
	if err != nil {
		return nil, err
	}
	return &f, nil
}
