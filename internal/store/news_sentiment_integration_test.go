package store_test

import (
	"context"
	"database/sql"
	"os"
	"testing"

	_ "github.com/jackc/pgx/v5/stdlib"
)

// newsTestDB mirrors pollsTestDB: gated on POLITYK_TEST_DATABASE_URL so the
// unit-only `go test ./...` workflow keeps working without Postgres. Tests
// run inside a transaction that is always rolled back.
func newsTestDB(t *testing.T) *sql.DB {
	t.Helper()
	dsn := os.Getenv("POLITYK_TEST_DATABASE_URL")
	if dsn == "" {
		t.Skip("POLITYK_TEST_DATABASE_URL not set; skipping news/sentiment integration test")
	}
	db, err := sql.Open("pgx", dsn)
	if err != nil {
		t.Fatalf("sql.Open: %v", err)
	}
	t.Cleanup(func() {
		if cerr := db.Close(); cerr != nil {
			t.Logf("db close: %v", cerr)
		}
	})
	if err := db.PingContext(context.Background()); err != nil {
		t.Fatalf("ping: %v", err)
	}
	return db
}

func TestNewsArticles_URLUniquePreventsDuplicateScrape(t *testing.T) {
	db := newsTestDB(t)
	ctx := context.Background()

	tx, err := db.BeginTx(ctx, nil)
	if err != nil {
		t.Fatalf("begin tx: %v", err)
	}
	t.Cleanup(func() { _ = tx.Rollback() })

	const url = "https://example.com/itest/news/dup-1"
	if _, err := tx.ExecContext(ctx, `
		INSERT INTO news_articles (source, url, published_at, title, body_text)
		VALUES ('prensa_libre', $1, '2027-04-10T12:00:00Z', 'Headline', 'Body.')
	`, url); err != nil {
		t.Fatalf("first insert: %v", err)
	}
	if _, err := tx.ExecContext(ctx, `SAVEPOINT dup_url`); err != nil {
		t.Fatalf("savepoint dup_url: %v", err)
	}
	if _, err := tx.ExecContext(ctx, `
		INSERT INTO news_articles (source, url, title) VALUES ('soy502', $1, 'Other')
	`, url); err == nil {
		t.Fatalf("expected UNIQUE violation on duplicate url, got nil")
	}
	if _, err := tx.ExecContext(ctx, `ROLLBACK TO SAVEPOINT dup_url`); err != nil {
		t.Fatalf("rollback dup_url: %v", err)
	}
}

func TestNewsArticles_LangDefaultsToEs(t *testing.T) {
	db := newsTestDB(t)
	ctx := context.Background()

	tx, err := db.BeginTx(ctx, nil)
	if err != nil {
		t.Fatalf("begin tx: %v", err)
	}
	t.Cleanup(func() { _ = tx.Rollback() })

	var lang string
	if err := tx.QueryRowContext(ctx, `
		INSERT INTO news_articles (source, url, title)
		VALUES ('agn', 'https://example.com/itest/news/lang-1', 'T')
		RETURNING lang
	`).Scan(&lang); err != nil {
		t.Fatalf("insert: %v", err)
	}
	if lang != "es" {
		t.Errorf("lang default: got %q want \"es\"", lang)
	}
}

func TestSocialPosts_PlatformEnumRejectsUnknown(t *testing.T) {
	db := newsTestDB(t)
	ctx := context.Background()

	tx, err := db.BeginTx(ctx, nil)
	if err != nil {
		t.Fatalf("begin tx: %v", err)
	}
	t.Cleanup(func() { _ = tx.Rollback() })

	// Wrap the expected-failure insert in a savepoint so the outer tx survives.
	if _, err := tx.ExecContext(ctx, `SAVEPOINT bad_platform`); err != nil {
		t.Fatalf("savepoint: %v", err)
	}
	if _, err := tx.ExecContext(ctx, `
		INSERT INTO social_posts (platform, url) VALUES ('twitter', 'https://x.com/itest/1')
	`); err == nil {
		t.Fatalf("expected ENUM violation for platform='twitter', got nil")
	}
	if _, err := tx.ExecContext(ctx, `ROLLBACK TO SAVEPOINT bad_platform`); err != nil {
		t.Fatalf("rollback to savepoint: %v", err)
	}
	for _, p := range []string{"reddit", "youtube_comment", "telegram", "bluesky"} {
		if _, err := tx.ExecContext(ctx, `
			INSERT INTO social_posts (platform, url) VALUES ($1::social_platform, $2)
		`, p, "https://example.com/itest/social/"+p); err != nil {
			t.Errorf("platform %q should be accepted: %v", p, err)
		}
	}
}

func TestSentimentScores_UniqueOnSourceSentenceSubject(t *testing.T) {
	db := newsTestDB(t)
	ctx := context.Background()

	tx, err := db.BeginTx(ctx, nil)
	if err != nil {
		t.Fatalf("begin tx: %v", err)
	}
	t.Cleanup(func() { _ = tx.Rollback() })

	var articleID int64
	if err := tx.QueryRowContext(ctx, `
		INSERT INTO news_articles (source, url, title)
		VALUES ('prensa_libre', 'https://example.com/itest/sentiment/unique-1', 'T')
		RETURNING article_id
	`).Scan(&articleID); err != nil {
		t.Fatalf("insert article: %v", err)
	}
	var candidateID int64
	if err := tx.QueryRowContext(ctx, `
		INSERT INTO candidates (full_name) VALUES ('Sentiment Unique Candidate')
		RETURNING candidate_id
	`).Scan(&candidateID); err != nil {
		t.Fatalf("insert candidate: %v", err)
	}

	if _, err := tx.ExecContext(ctx, `
		INSERT INTO sentiment_scores
			(source_kind, source_id, sentence_index, subject_kind, subject_id,
			 score, label, model_version)
		VALUES ('article', $1, 0, 'candidate', $2, 0.85, 'POS', 'pysentimiento-0.7.6')
	`, articleID, candidateID); err != nil {
		t.Fatalf("first sentiment insert: %v", err)
	}
	if _, err := tx.ExecContext(ctx, `SAVEPOINT dup_subject`); err != nil {
		t.Fatalf("savepoint: %v", err)
	}
	if _, err := tx.ExecContext(ctx, `
		INSERT INTO sentiment_scores
			(source_kind, source_id, sentence_index, subject_kind, subject_id,
			 score, label, model_version)
		VALUES ('article', $1, 0, 'candidate', $2, 0.10, 'NEU', 'pysentimiento-0.7.6')
	`, articleID, candidateID); err == nil {
		t.Fatalf("expected UNIQUE violation on duplicate (source, sentence, subject), got nil")
	}
	if _, err := tx.ExecContext(ctx, `ROLLBACK TO SAVEPOINT dup_subject`); err != nil {
		t.Fatalf("rollback to savepoint dup_subject: %v", err)
	}

	// "overall" rows use subject_id=NULL; NULLS NOT DISTINCT keeps the unique
	// constraint effective so re-scoring an article can't double-write.
	if _, err := tx.ExecContext(ctx, `
		INSERT INTO sentiment_scores
			(source_kind, source_id, sentence_index, subject_kind, subject_id,
			 score, label, model_version)
		VALUES ('article', $1, 1, 'overall', NULL, 0.0, 'NEU', 'pysentimiento-0.7.6')
	`, articleID); err != nil {
		t.Fatalf("overall null insert: %v", err)
	}
	if _, err := tx.ExecContext(ctx, `SAVEPOINT dup_overall`); err != nil {
		t.Fatalf("savepoint dup_overall: %v", err)
	}
	if _, err := tx.ExecContext(ctx, `
		INSERT INTO sentiment_scores
			(source_kind, source_id, sentence_index, subject_kind, subject_id,
			 score, label, model_version)
		VALUES ('article', $1, 1, 'overall', NULL, 0.0, 'NEU', 'pysentimiento-0.7.6')
	`, articleID); err == nil {
		t.Fatalf("expected UNIQUE violation on duplicate overall row (NULLS NOT DISTINCT)")
	}
	if _, err := tx.ExecContext(ctx, `ROLLBACK TO SAVEPOINT dup_overall`); err != nil {
		t.Fatalf("rollback to savepoint dup_overall: %v", err)
	}
}

func TestSentimentScores_OverallRequiresNullSubjectID(t *testing.T) {
	db := newsTestDB(t)
	ctx := context.Background()

	tx, err := db.BeginTx(ctx, nil)
	if err != nil {
		t.Fatalf("begin tx: %v", err)
	}
	t.Cleanup(func() { _ = tx.Rollback() })

	var articleID int64
	if err := tx.QueryRowContext(ctx, `
		INSERT INTO news_articles (source, url, title)
		VALUES ('soy502', 'https://example.com/itest/sentiment/overall-check', 'T')
		RETURNING article_id
	`).Scan(&articleID); err != nil {
		t.Fatalf("insert article: %v", err)
	}

	if _, err := tx.ExecContext(ctx, `SAVEPOINT bad_overall`); err != nil {
		t.Fatalf("savepoint bad_overall: %v", err)
	}
	if _, err := tx.ExecContext(ctx, `
		INSERT INTO sentiment_scores
			(source_kind, source_id, sentence_index, subject_kind, subject_id,
			 score, label, model_version)
		VALUES ('article', $1, 0, 'overall', 42, 0.0, 'NEU', 'pysentimiento-0.7.6')
	`, articleID); err == nil {
		t.Fatalf("expected CHECK violation: overall row must have NULL subject_id")
	}
	if _, err := tx.ExecContext(ctx, `ROLLBACK TO SAVEPOINT bad_overall`); err != nil {
		t.Fatalf("rollback bad_overall: %v", err)
	}
	if _, err := tx.ExecContext(ctx, `SAVEPOINT bad_candidate`); err != nil {
		t.Fatalf("savepoint bad_candidate: %v", err)
	}
	if _, err := tx.ExecContext(ctx, `
		INSERT INTO sentiment_scores
			(source_kind, source_id, sentence_index, subject_kind, subject_id,
			 score, label, model_version)
		VALUES ('article', $1, 0, 'candidate', NULL, 0.0, 'NEU', 'pysentimiento-0.7.6')
	`, articleID); err == nil {
		t.Fatalf("expected CHECK violation: candidate row must have non-NULL subject_id")
	}
	if _, err := tx.ExecContext(ctx, `ROLLBACK TO SAVEPOINT bad_candidate`); err != nil {
		t.Fatalf("rollback bad_candidate: %v", err)
	}
}

// TestSentimentScores_MatViewAggregatesArticleAndFiveSentences walks the
// happy path described in the issue's last acceptance criterion: an article
// plus 5 sentence-level rows aggregate cleanly through the materialized view.
func TestSentimentScores_MatViewAggregatesArticleAndFiveSentences(t *testing.T) {
	db := newsTestDB(t)
	ctx := context.Background()

	// The materialized view is global state, so this test cannot run inside a
	// rolled-back transaction (REFRESH cannot run inside a tx). Clean up by
	// deleting the seeded rows.
	var articleID, candidateAID, candidateBID int64
	cleanup := []string{}
	t.Cleanup(func() {
		for i := len(cleanup) - 1; i >= 0; i-- {
			if _, err := db.ExecContext(ctx, cleanup[i]); err != nil {
				t.Logf("cleanup %d: %v", i, err)
			}
		}
		if _, err := db.ExecContext(ctx,
			`REFRESH MATERIALIZED VIEW sentiment_per_source_subject`); err != nil {
			t.Logf("final refresh: %v", err)
		}
	})

	if err := db.QueryRowContext(ctx, `
		INSERT INTO news_articles (source, url, title)
		VALUES ('plaza_publica', 'https://example.com/itest/sentiment/matview-1', 'Title')
		RETURNING article_id
	`).Scan(&articleID); err != nil {
		t.Fatalf("insert article: %v", err)
	}
	cleanup = append(cleanup, `DELETE FROM news_articles WHERE article_id = `+itoa(articleID))

	if err := db.QueryRowContext(ctx, `
		INSERT INTO candidates (full_name) VALUES ('Matview Candidate A') RETURNING candidate_id
	`).Scan(&candidateAID); err != nil {
		t.Fatalf("insert candidate A: %v", err)
	}
	cleanup = append(cleanup, `DELETE FROM candidates WHERE candidate_id = `+itoa(candidateAID))

	if err := db.QueryRowContext(ctx, `
		INSERT INTO candidates (full_name) VALUES ('Matview Candidate B') RETURNING candidate_id
	`).Scan(&candidateBID); err != nil {
		t.Fatalf("insert candidate B: %v", err)
	}
	cleanup = append(cleanup, `DELETE FROM candidates WHERE candidate_id = `+itoa(candidateBID))

	cleanup = append(cleanup,
		`DELETE FROM sentiment_scores WHERE source_kind = 'article' AND source_id = `+itoa(articleID))

	// Five sentence-level rows: two about A (POS+POS), two about B (NEG+NEU),
	// one "overall" sentence with no resolved entity (NEU).
	inserts := []struct {
		sentence    int
		subjectKind string
		subjectArg  any
		score       float64
		label       string
	}{
		{0, "candidate", candidateAID, 0.90, "POS"},
		{1, "candidate", candidateAID, 0.70, "POS"},
		{2, "candidate", candidateBID, -0.80, "NEG"},
		{3, "candidate", candidateBID, 0.05, "NEU"},
		{4, "overall", nil, 0.00, "NEU"},
	}
	for _, row := range inserts {
		if _, err := db.ExecContext(ctx, `
			INSERT INTO sentiment_scores
				(source_kind, source_id, sentence_index, subject_kind, subject_id,
				 score, label, model_version)
			VALUES ('article', $1, $2, $3::sentiment_subject_kind, $4, $5, $6::sentiment_label,
				    'pysentimiento-0.7.6')
		`, articleID, row.sentence, row.subjectKind, row.subjectArg, row.score, row.label); err != nil {
			t.Fatalf("insert sentiment row %d: %v", row.sentence, err)
		}
	}

	if _, err := db.ExecContext(ctx,
		`REFRESH MATERIALIZED VIEW sentiment_per_source_subject`); err != nil {
		t.Fatalf("refresh matview: %v", err)
	}

	type aggRow struct {
		subjectKind   string
		subjectID     sql.NullInt64
		meanScore     float64
		sentenceCount int64
		dominantLabel string
	}
	rows, err := db.QueryContext(ctx, `
		SELECT subject_kind::text, subject_id, mean_score, sentence_count, dominant_label::text
		FROM sentiment_per_source_subject
		WHERE source_kind = 'article' AND source_id = $1
		ORDER BY subject_kind, subject_id NULLS LAST
	`, articleID)
	if err != nil {
		t.Fatalf("query matview: %v", err)
	}
	defer rows.Close()

	var got []aggRow
	for rows.Next() {
		var r aggRow
		if err := rows.Scan(&r.subjectKind, &r.subjectID, &r.meanScore, &r.sentenceCount, &r.dominantLabel); err != nil {
			t.Fatalf("scan: %v", err)
		}
		got = append(got, r)
	}
	if err := rows.Err(); err != nil {
		t.Fatalf("rows.Err: %v", err)
	}
	if len(got) != 3 {
		t.Fatalf("matview row count: got %d want 3 (A, B, overall)", len(got))
	}

	byKey := map[string]aggRow{}
	for _, r := range got {
		key := r.subjectKind
		if r.subjectID.Valid {
			key += ":" + itoa(r.subjectID.Int64)
		}
		byKey[key] = r
	}
	rowA, ok := byKey["candidate:"+itoa(candidateAID)]
	if !ok {
		t.Fatalf("missing candidate A row in matview")
	}
	if rowA.sentenceCount != 2 {
		t.Errorf("A sentence_count: got %d want 2", rowA.sentenceCount)
	}
	if round4(rowA.meanScore) != 0.80 {
		t.Errorf("A mean_score: got %v want 0.80", round4(rowA.meanScore))
	}
	if rowA.dominantLabel != "POS" {
		t.Errorf("A dominant_label: got %q want POS", rowA.dominantLabel)
	}

	rowB, ok := byKey["candidate:"+itoa(candidateBID)]
	if !ok {
		t.Fatalf("missing candidate B row in matview")
	}
	if rowB.sentenceCount != 2 {
		t.Errorf("B sentence_count: got %d want 2", rowB.sentenceCount)
	}
	// (-0.80 + 0.05) / 2 = -0.375
	if round4(rowB.meanScore) != -0.375 {
		t.Errorf("B mean_score: got %v want -0.375", round4(rowB.meanScore))
	}
	// Tie between NEG and NEU (1 each) — tie-breaker prefers NEG over NEU
	// per the dominant_label ordering encoded in the view.
	if rowB.dominantLabel != "NEG" {
		t.Errorf("B dominant_label tie-break: got %q want NEG", rowB.dominantLabel)
	}

	rowOverall, ok := byKey["overall"]
	if !ok {
		t.Fatalf("missing overall row in matview")
	}
	if rowOverall.subjectID.Valid {
		t.Errorf("overall subject_id should be NULL, got %d", rowOverall.subjectID.Int64)
	}
	if rowOverall.sentenceCount != 1 {
		t.Errorf("overall sentence_count: got %d want 1", rowOverall.sentenceCount)
	}
	if rowOverall.dominantLabel != "NEU" {
		t.Errorf("overall dominant_label: got %q want NEU", rowOverall.dominantLabel)
	}
}

// itoa avoids strconv import bloat in the SQL-string builders above; the
// values are trusted server-side IDs we just inserted, never user input.
func itoa(i int64) string {
	const digits = "0123456789"
	if i == 0 {
		return "0"
	}
	neg := i < 0
	if neg {
		i = -i
	}
	var buf [20]byte
	pos := len(buf)
	for i > 0 {
		pos--
		buf[pos] = digits[i%10]
		i /= 10
	}
	if neg {
		pos--
		buf[pos] = '-'
	}
	return string(buf[pos:])
}
