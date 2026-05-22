package store

import (
	"context"
	"database/sql"

	"github.com/jlcp89/polityk/internal/handlers"
)

// PollsterBiasReader is the database/sql-backed implementation of
// handlers.PollsterBiasReader used by /v1/methodology. The query projects
// only the four columns ADR-014 documents on the response; ORDER BY name
// keeps the response deterministic for client caching + Android UI tests.
type PollsterBiasReader struct {
	DB *sql.DB
}

// PollsterBiasPriors returns one row per `pollsters` table entry. ADR-017
// guarantees the four launch pollsters are seeded with diffuse priors;
// re-runs of the bias estimator in #29 will write back real means/sds
// which surface here without code changes.
func (r *PollsterBiasReader) PollsterBiasPriors(ctx context.Context) ([]handlers.PollsterBiasPrior, error) {
	const q = `
		SELECT name, historical_bias_mean, historical_bias_sd, sample_count_used
		FROM pollsters
		ORDER BY name
	`
	rows, err := r.DB.QueryContext(ctx, q)
	if err != nil {
		return nil, err
	}
	defer func() { _ = rows.Close() }()

	priors := []handlers.PollsterBiasPrior{}
	for rows.Next() {
		var p handlers.PollsterBiasPrior
		if err := rows.Scan(&p.Pollster, &p.HistoricalBiasMean, &p.HistoricalBiasSD, &p.SampleCountUsed); err != nil {
			return nil, err
		}
		priors = append(priors, p)
	}
	if err := rows.Err(); err != nil {
		return nil, err
	}
	return priors, nil
}
