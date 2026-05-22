package rss

import (
	"context"
	"database/sql"
	"errors"
	"io"
	"log/slog"
	"net/http"
	"net/http/httptest"
	"net/url"
	"os"
	"path/filepath"
	"strings"
	"sync"
	"sync/atomic"
	"testing"
	"time"

	_ "github.com/jackc/pgx/v5/stdlib"
)

func mustRead(t *testing.T, name string) []byte {
	t.Helper()
	b, err := os.ReadFile(filepath.Join("testdata", name))
	if err != nil {
		t.Fatalf("read fixture %s: %v", name, err)
	}
	return b
}

func discardLogger() *slog.Logger {
	return slog.New(slog.NewTextHandler(io.Discard, nil))
}

// rssFixtureForOutlet returns the fixture file each outlet's FeedURL maps
// to in the in-process httptest server. Used to exercise every outlet's
// parse path without leaving testdata/ desynced from sources.go.
func rssFixtureForOutlet(name string) []string {
	switch name {
	case "Prensa Libre":
		return []string{"prensa_libre.xml", "prensa_libre_politica.xml"}
	case "La Hora":
		return []string{"la_hora.xml"}
	case "Soy502":
		return []string{"soy502.xml"}
	case "Plaza Pública":
		return []string{"plaza_publica.xml"}
	case "Publinews":
		return []string{"publinews.xml"}
	case "Emisoras Unidas":
		return []string{"emisoras_unidas.xml"}
	case "República":
		return []string{"republica.xml"}
	case "Agencia Guatemalteca de Noticias":
		return []string{"agn.xml"}
	case "Guatemala.com":
		return []string{"guatemala_com.xml"}
	}
	return nil
}

// fixtureRouter serves the per-outlet RSS fixtures + a single generic
// article body for any article URL fetch + the DCA homepage. The set of
// URLs is computed from outlets so we never have to keep parallel lists.
type fixtureRouter struct {
	t           *testing.T
	mu          sync.Mutex
	hits        map[string]int
	hitOrder    []time.Time
	requestLog  []string
	clock       func() time.Time
	dcaHomepage []byte
	articleHTML []byte
}

func newFixtureRouter(t *testing.T) *fixtureRouter {
	return &fixtureRouter{
		t:           t,
		hits:        map[string]int{},
		clock:       time.Now,
		dcaHomepage: mustRead(t, "dca_homepage.html"),
		articleHTML: mustRead(t, "article_sample.html"),
	}
}

func (r *fixtureRouter) ServeHTTP(w http.ResponseWriter, req *http.Request) {
	func() {
		r.mu.Lock()
		defer r.mu.Unlock()
		if r.hits == nil {
			r.hits = map[string]int{}
		}
		r.hits[req.URL.Path]++
		clock := r.clock
		if clock == nil {
			clock = time.Now
		}
		r.hitOrder = append(r.hitOrder, clock())
		r.requestLog = append(r.requestLog, req.URL.Path)
	}()

	host := req.Host
	path := req.URL.Path

	// DCA homepage and articles are served distinctly because the homepage
	// is HTML-with-links, while DCA articles share the generic article body.
	if strings.Contains(host, "dca.gob.gt") {
		if strings.HasSuffix(path, "/noticias-guatemala-diario-centro-america/") || path == "/" {
			w.Header().Set("Content-Type", "text/html; charset=utf-8")
			_, _ = w.Write(r.dcaHomepage)
			return
		}
		w.Header().Set("Content-Type", "text/html; charset=utf-8")
		_, _ = w.Write(r.articleHTML)
		return
	}

	// RSS feed paths: dispatch by host first, then by /feed-style suffix
	// for the two Prensa Libre feeds.
	switch {
	case strings.Contains(host, "prensalibre.com"):
		// Check feed paths first; some article URLs contain "politica" too.
		switch {
		case strings.HasSuffix(path, "/politica/feed/") || strings.HasSuffix(path, "politica/feed"):
			r.writeFixture(w, "prensa_libre_politica.xml")
		case strings.HasSuffix(path, "/feed/") || strings.HasSuffix(path, "/feed"):
			r.writeFixture(w, "prensa_libre.xml")
		default:
			r.writeFixture(w, "article_sample.html")
		}
		return
	case strings.Contains(host, "lahora.gt"):
		if strings.HasSuffix(path, "/feed/") {
			r.writeFixture(w, "la_hora.xml")
		} else {
			r.writeFixture(w, "article_sample.html")
		}
		return
	case strings.Contains(host, "soy502.com"):
		if strings.HasSuffix(path, "/rss.xml") {
			r.writeFixture(w, "soy502.xml")
		} else {
			r.writeFixture(w, "article_sample.html")
		}
		return
	case strings.Contains(host, "plazapublica.com.gt"):
		if strings.HasSuffix(path, "/feed/") {
			r.writeFixture(w, "plaza_publica.xml")
		} else {
			r.writeFixture(w, "article_sample.html")
		}
		return
	case strings.Contains(host, "publinews.gt"):
		if strings.HasSuffix(path, "/rss/") {
			r.writeFixture(w, "publinews.xml")
		} else {
			r.writeFixture(w, "article_sample.html")
		}
		return
	case strings.Contains(host, "emisorasunidas.com"):
		if strings.HasSuffix(path, "/feed/") {
			r.writeFixture(w, "emisoras_unidas.xml")
		} else {
			r.writeFixture(w, "article_sample.html")
		}
		return
	case strings.Contains(host, "republica.gt"):
		if strings.HasSuffix(path, "/feed/") {
			r.writeFixture(w, "republica.xml")
		} else {
			r.writeFixture(w, "article_sample.html")
		}
		return
	case strings.Contains(host, "agn.gt"):
		if strings.HasSuffix(path, "/feed/") {
			r.writeFixture(w, "agn.xml")
		} else {
			r.writeFixture(w, "article_sample.html")
		}
		return
	case strings.Contains(host, "guatemala.com") || strings.Contains(host, "aprende.guatemala.com"):
		if strings.HasSuffix(path, "/feed/") {
			r.writeFixture(w, "guatemala_com.xml")
		} else {
			r.writeFixture(w, "article_sample.html")
		}
		return
	}

	// Default: serve the generic article HTML so unrelated URLs still
	// produce valid bodies during integration tests.
	r.writeFixture(w, "article_sample.html")
}

func (r *fixtureRouter) writeFixture(w http.ResponseWriter, name string) {
	w.Header().Set("Content-Type", contentTypeFor(name))
	_, _ = w.Write(mustRead(r.t, name))
}

func contentTypeFor(name string) string {
	if strings.HasSuffix(name, ".xml") {
		return "application/rss+xml; charset=utf-8"
	}
	return "text/html; charset=utf-8"
}

// hostRedirectTransport rewrites every outbound request's URL host to the
// httptest server so the gofeed parser + the article fetcher both reach
// the fixture handler. Host header is preserved so the router can
// distinguish outlets.
type hostRedirectTransport struct {
	base       http.RoundTripper
	serverHost string
	hits       atomic.Int64
	requestLog *sync.Map // map[string]int
}

func (t *hostRedirectTransport) RoundTrip(req *http.Request) (*http.Response, error) {
	t.hits.Add(1)
	if t.requestLog != nil {
		existing, _ := t.requestLog.LoadOrStore(req.URL.Host+req.URL.Path, new(atomic.Int64))
		existing.(*atomic.Int64).Add(1)
	}
	cloned := req.Clone(req.Context())
	cloned.URL.Scheme = "http"
	originalHost := cloned.URL.Host
	cloned.URL.Host = t.serverHost
	if cloned.Host == "" {
		cloned.Host = originalHost
	}
	return t.base.RoundTrip(cloned)
}

func newFixtureClient(t *testing.T, srv *httptest.Server, outlets []Outlet, minDelay time.Duration) (*Client, *hostRedirectTransport) {
	t.Helper()
	parsed, err := url.Parse(srv.URL)
	if err != nil {
		t.Fatalf("parse srv URL: %v", err)
	}
	transport := &hostRedirectTransport{
		base:       srv.Client().Transport,
		serverHost: parsed.Host,
		requestLog: &sync.Map{},
	}
	hc := &http.Client{Transport: transport, Timeout: 5 * time.Second}
	return &Client{
		HTTPClient:   hc,
		UserAgent:    "test-bot/0.1",
		Outlets:      outlets,
		MinDelay:     minDelay,
		MaxBodyBytes: defaultMaxBodyBytes,
		Logger:       discardLogger(),
		Clock:        time.Now,
	}, transport
}

// --- Pure / fast tests below. ---

func TestSources_ActiveOutletsAndDCADirect(t *testing.T) {
	t.Parallel()
	outlets := Sources()
	// 6 working RSS outlets + 1 Direct (DCA) = 7. Soy502, Publinews, AGN
	// were removed in 2026-05 after their RSS endpoints stopped serving
	// XML; see sources.go for the rationale.
	if got, want := len(outlets), 7; got != want {
		t.Fatalf("Sources(): got %d outlets, want %d", got, want)
	}
	directCount := 0
	feedCount := 0
	for _, o := range outlets {
		if o.Name == "" {
			t.Errorf("outlet has empty Name")
		}
		switch {
		case o.Direct != nil:
			directCount++
			if len(o.FeedURLs) != 0 {
				t.Errorf("outlet %q has both Direct and FeedURLs", o.Name)
			}
		default:
			feedCount++
			if len(o.FeedURLs) == 0 {
				t.Errorf("outlet %q has neither Direct nor FeedURLs", o.Name)
			}
		}
	}
	if directCount != 1 {
		t.Errorf("expected exactly one Direct outlet (DCA), got %d", directCount)
	}
	if feedCount != 6 {
		t.Errorf("expected 6 RSS outlets, got %d", feedCount)
	}
	// Spot-check: DCA must be the Direct outlet.
	for _, o := range outlets {
		if o.Direct != nil && !strings.Contains(strings.ToLower(o.Name), "diario") {
			t.Errorf("Direct outlet is %q, expected Diario de Centro América", o.Name)
		}
	}
}

func TestExtractArticle_RealWorldShape(t *testing.T) {
	t.Parallel()
	body, title := extractArticle(mustRead(t, "article_sample.html"))
	if !strings.Contains(title, "Pleno del Congreso") {
		t.Errorf("title: got %q", title)
	}
	if body == "" {
		t.Fatalf("body is empty")
	}
	if !strings.Contains(body, "reforma electoral") {
		t.Errorf("body missing expected text: %q", body)
	}
	// Noise nodes must not survive.
	if strings.Contains(body, "Publicidad descartada") {
		t.Errorf("ad text leaked into body: %q", body)
	}
	if strings.Contains(body, "Compartir") {
		t.Errorf("share widget text leaked into body: %q", body)
	}
	if strings.Contains(body, "Relacionado 1") {
		t.Errorf("related-article link text leaked into body: %q", body)
	}
}

func TestExtractArticle_BrokenInputReturnsEmpty(t *testing.T) {
	t.Parallel()
	body, _ := extractArticle([]byte("<html><body><div>nothing</div></body></html>"))
	if body != "" {
		t.Errorf("expected empty body for noise-only input, got %q", body)
	}
}

func TestDCAIsArticleHref(t *testing.T) {
	t.Parallel()
	cases := []struct {
		href string
		want bool
	}{
		{"/dca-articulo-uno/", true},
		{"https://dca.gob.gt/dca-articulo-dos/", true},
		{"/category/politica/", false},
		{"/tag/elecciones/", false},
		{"/author/john/", false},
		{"/feed/", false},
		{"mailto:editor@dca.gob.gt", false},
		{"#top", false},
		{"https://otro-medio.gt/articulo", false},
		{"", false},
	}
	for _, c := range cases {
		c := c
		t.Run(c.href, func(t *testing.T) {
			t.Parallel()
			if got := dcaIsArticleHref(c.href); got != c.want {
				t.Errorf("dcaIsArticleHref(%q) = %v, want %v", c.href, got, c.want)
			}
		})
	}
}

func TestParseDirectHomepage_DCA(t *testing.T) {
	t.Parallel()
	cfg := &DirectConfig{
		LinkSelector:  "article a, h2 a, h3 a",
		URLAttr:       "href",
		IsArticleHref: dcaIsArticleHref,
		NormalizeHref: dcaNormalizeHref,
	}
	items, err := parseDirectHomepage(mustRead(t, "dca_homepage.html"), cfg)
	if err != nil {
		t.Fatalf("parseDirectHomepage: %v", err)
	}
	// dca_homepage.html has 4 candidate links; 2 are real articles, the
	// section link and external link are filtered.
	if len(items) != 2 {
		t.Fatalf("expected 2 articles, got %d: %+v", len(items), items)
	}
	got := map[string]bool{items[0].URL: true, items[1].URL: true}
	want := []string{
		"https://dca.gob.gt/dca-articulo-uno/",
		"https://dca.gob.gt/dca-articulo-dos/",
	}
	for _, w := range want {
		if !got[w] {
			t.Errorf("missing expected article %q in %+v", w, items)
		}
	}
}

// TestFeedFixture_EachOutletParsesWithoutPanic exercises every outlet's
// fixture through gofeed end-to-end via the in-process httptest server.
// This is the explicit "Fixture-driven test parses each outlet's sample
// feed without panic" acceptance criterion.
func TestFeedFixture_EachOutletParsesWithoutPanic(t *testing.T) {
	t.Parallel()
	router := newFixtureRouter(t)
	srv := httptest.NewServer(router)
	t.Cleanup(srv.Close)

	for _, outlet := range Sources() {
		outlet := outlet
		if outlet.Direct != nil {
			continue // DCA is exercised separately.
		}
		t.Run(outlet.Name, func(t *testing.T) {
			t.Parallel()
			fixtures := rssFixtureForOutlet(outlet.Name)
			if len(fixtures) == 0 {
				t.Fatalf("no fixture mapping for outlet %q", outlet.Name)
			}
			client, _ := newFixtureClient(t, srv, []Outlet{outlet}, 0)
			items, err := client.fetchAndParseFeeds(context.Background(), outlet)
			if err != nil {
				t.Fatalf("fetchAndParseFeeds: %v", err)
			}
			if len(items) == 0 {
				t.Fatalf("no items parsed for outlet %q", outlet.Name)
			}
			for _, it := range items {
				if it.URL == "" {
					t.Errorf("item with empty URL in outlet %q: %+v", outlet.Name, it)
				}
				if it.Title == "" {
					t.Errorf("item with empty Title in outlet %q: %+v", outlet.Name, it)
				}
			}
		})
	}
}

func TestPrensaLibre_DedupesAcrossTwoFeeds(t *testing.T) {
	t.Parallel()
	router := newFixtureRouter(t)
	srv := httptest.NewServer(router)
	t.Cleanup(srv.Close)

	outlet := Outlet{
		Name: "Prensa Libre",
		FeedURLs: []string{
			"https://www.prensalibre.com/feed/",
			"https://www.prensalibre.com/guatemala/politica/feed/",
		},
	}
	client, _ := newFixtureClient(t, srv, []Outlet{outlet}, 0)
	items, err := client.fetchAndParseFeeds(context.Background(), outlet)
	if err != nil {
		t.Fatalf("fetchAndParseFeeds: %v", err)
	}
	// Fixtures: feed1 has articles 1+2, feed2 has 2+3. After dedup we
	// expect 3 distinct URLs total.
	if len(items) != 3 {
		t.Fatalf("expected 3 unique items after dedup, got %d: %+v", len(items), items)
	}
	seen := map[string]int{}
	for _, it := range items {
		seen[it.URL]++
	}
	for url, n := range seen {
		if n != 1 {
			t.Errorf("url %q appeared %d times, expected 1", url, n)
		}
	}
}

// TestRunOutlet_SkipsArticleOnExtractionFailure proves the
// "body_text is non-empty for every inserted row (skip on extraction
// failure)" criterion at the in-memory layer (no DB).
func TestIngestArticles_SkipsEmptyBody(t *testing.T) {
	t.Parallel()

	router := &fixtureRouter{
		t:    t,
		hits: map[string]int{},
		// All article-body fetches return a body with no extractable text
		// (no <article>, no .entry-content, no <p>) so extractArticle
		// returns "" → row is skipped.
		articleHTML: []byte(`<html><body><div>nothing</div></body></html>`),
	}
	srv := httptest.NewServer(router)
	t.Cleanup(srv.Close)

	outlet := Outlet{
		Name:     "Test Outlet",
		FeedURLs: []string{"https://example.gt/feed/"},
	}
	client, _ := newFixtureClient(t, srv, []Outlet{outlet}, 0)

	items := []fetchedItem{
		{URL: "https://example.gt/articulo-1/", Title: "Title"},
		{URL: "https://example.gt/articulo-2/", Title: "Title"},
	}
	inserted, err := client.ingestArticles(context.Background(), nil, outlet, items)
	if err != nil {
		t.Fatalf("ingestArticles: %v", err)
	}
	if inserted != 0 {
		t.Errorf("expected 0 inserts when all bodies extract empty, got %d", inserted)
	}
}

// TestIngestArticles_RateLimitedAtLeast1ReqPerSec validates the
// "Rate-limited to 1 req/sec per outlet" acceptance criterion by measuring
// the wall-clock between consecutive article fetches within a single
// outlet run.
func TestIngestArticles_RateLimitedAtLeast1ReqPerSec(t *testing.T) {
	if testing.Short() {
		t.Skip("skipping wall-clock rate-limit test in -short")
	}
	t.Parallel()
	router := newFixtureRouter(t)
	srv := httptest.NewServer(router)
	t.Cleanup(srv.Close)

	outlet := Outlet{
		Name:     "Test Outlet",
		FeedURLs: []string{"https://example.gt/feed/"},
	}
	// Shorten the delay so the test finishes quickly while still proving
	// the gap is enforced.
	const delay = 120 * time.Millisecond
	client, _ := newFixtureClient(t, srv, []Outlet{outlet}, delay)

	items := []fetchedItem{
		{URL: "https://example.gt/a/", Title: "T"},
		{URL: "https://example.gt/b/", Title: "T"},
		{URL: "https://example.gt/c/", Title: "T"},
	}
	start := time.Now()
	if _, err := client.ingestArticles(context.Background(), nil, outlet, items); err != nil {
		t.Fatalf("ingestArticles: %v", err)
	}
	elapsed := time.Since(start)
	// 2 sleeps between 3 articles = at least 2 * delay.
	want := 2*delay - 5*time.Millisecond
	if elapsed < want {
		t.Errorf("rate limit not enforced: elapsed=%v want >= %v", elapsed, want)
	}
	// Cap: shouldn't be obscenely slow either.
	if elapsed > 2*time.Second {
		t.Errorf("rate limit too slow: elapsed=%v", elapsed)
	}
}

func TestRun_NoOutletsConfigured(t *testing.T) {
	t.Parallel()
	c := &Client{
		HTTPClient: &http.Client{Timeout: time.Second},
		UserAgent:  "test",
		Outlets:    nil,
		Logger:     discardLogger(),
	}
	err := c.Run(context.Background(), nil)
	if err == nil || !strings.Contains(err.Error(), "no outlets") {
		t.Fatalf("expected 'no outlets' error, got %v", err)
	}
}

func TestStampScrapeRun_NilDBIsNoop(t *testing.T) {
	t.Parallel()
	if err := stampScrapeRun(context.Background(), nil, SourceRSSAggregator, true, ""); err != nil {
		t.Errorf("nil DB stamp returned error: %v", err)
	}
}

// --- DB-gated integration tests below. Skip when
// POLITYK_TEST_DATABASE_URL is unset. ---

func openTestDB(t *testing.T) (*sql.DB, bool) {
	t.Helper()
	dsn := os.Getenv("POLITYK_TEST_DATABASE_URL")
	if dsn == "" {
		t.Skip("POLITYK_TEST_DATABASE_URL not set")
		return nil, false
	}
	db, err := sql.Open("pgx", dsn)
	if err != nil {
		t.Fatalf("sql.Open: %v", err)
	}
	if err := db.PingContext(context.Background()); err != nil {
		_ = db.Close()
		t.Skipf("DB not reachable: %v", err)
		return nil, false
	}
	return db, true
}

func truncateNewsArticles(t *testing.T, db *sql.DB) {
	t.Helper()
	ctx := context.Background()
	for _, stmt := range []string{
		"TRUNCATE TABLE news_articles RESTART IDENTITY",
		"DELETE FROM scrape_runs WHERE source = 'rss_aggregator'",
	} {
		if _, err := db.ExecContext(ctx, stmt); err != nil {
			t.Fatalf("truncate (%s): %v", stmt, err)
		}
	}
}

func TestRun_HappyPath_Integration(t *testing.T) {
	db, ok := openTestDB(t)
	if !ok {
		return
	}
	t.Cleanup(func() { _ = db.Close() })
	truncateNewsArticles(t, db)

	router := newFixtureRouter(t)
	srv := httptest.NewServer(router)
	t.Cleanup(srv.Close)

	client, _ := newFixtureClient(t, srv, Sources(), 0)
	if err := client.Run(context.Background(), db); err != nil {
		t.Fatalf("Run: %v", err)
	}

	var total int
	if err := db.QueryRowContext(context.Background(),
		"SELECT COUNT(*) FROM news_articles").Scan(&total); err != nil {
		t.Fatalf("count: %v", err)
	}
	if total == 0 {
		t.Fatalf("no articles inserted")
	}

	// Per-outlet smoke: at least one row from each RSS outlet + DCA.
	for _, outlet := range Sources() {
		var n int
		err := db.QueryRowContext(context.Background(),
			`SELECT COUNT(*) FROM news_articles WHERE outlet = $1`, outlet.Name).Scan(&n)
		if err != nil {
			t.Fatalf("count outlet %s: %v", outlet.Name, err)
		}
		if n == 0 {
			t.Errorf("outlet %s: expected >= 1 row, got 0", outlet.Name)
		}
	}

	// scrape_runs stamped.
	var success bool
	if err := db.QueryRowContext(context.Background(),
		`SELECT success FROM scrape_runs WHERE source = 'rss_aggregator'`).Scan(&success); err != nil {
		t.Fatalf("read scrape_runs: %v", err)
	}
	if !success {
		t.Errorf("scrape_runs.success false; expected true")
	}

	// Idempotency: a second run yields the same total.
	if err := client.Run(context.Background(), db); err != nil {
		t.Fatalf("Run (second): %v", err)
	}
	var totalAfter int
	if err := db.QueryRowContext(context.Background(),
		"SELECT COUNT(*) FROM news_articles").Scan(&totalAfter); err != nil {
		t.Fatalf("count after: %v", err)
	}
	if totalAfter != total {
		t.Errorf("idempotency: total changed from %d to %d on second run", total, totalAfter)
	}
}

func TestInsertArticle_EmptyBodyRejectedByCheckConstraint_Integration(t *testing.T) {
	db, ok := openTestDB(t)
	if !ok {
		return
	}
	t.Cleanup(func() { _ = db.Close() })
	truncateNewsArticles(t, db)

	_, err := db.ExecContext(context.Background(),
		`INSERT INTO news_articles (outlet, url, title, body_text) VALUES ($1,$2,$3,$4)`,
		"X", "https://example.gt/x/", "T", "")
	if err == nil {
		t.Fatal("expected CHECK constraint violation for empty body_text")
	}
}

func TestRun_AllOutletsFail_StampsFailure_Integration(t *testing.T) {
	db, ok := openTestDB(t)
	if !ok {
		return
	}
	t.Cleanup(func() { _ = db.Close() })
	truncateNewsArticles(t, db)

	// httptest server that 500s every request → all outlets fail their
	// feed parse → aggregated failure.
	srv := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, _ *http.Request) {
		http.Error(w, "boom", http.StatusInternalServerError)
	}))
	t.Cleanup(srv.Close)

	parsed, err := url.Parse(srv.URL)
	if err != nil {
		t.Fatalf("parse srv URL: %v", err)
	}
	transport := &hostRedirectTransport{base: srv.Client().Transport, serverHost: parsed.Host}
	hc := &http.Client{Transport: transport, Timeout: 2 * time.Second}
	client := &Client{
		HTTPClient:   hc,
		UserAgent:    "test-bot/0.1",
		Outlets:      Sources(),
		MinDelay:     0,
		MaxBodyBytes: defaultMaxBodyBytes,
		Logger:       discardLogger(),
	}
	err = client.Run(context.Background(), db)
	if err == nil {
		t.Fatal("expected error when every outlet fails")
	}

	var success bool
	var errMsg sql.NullString
	if err := db.QueryRowContext(context.Background(),
		`SELECT success, error_message FROM scrape_runs WHERE source = 'rss_aggregator'`).Scan(&success, &errMsg); err != nil {
		t.Fatalf("read scrape_runs: %v", err)
	}
	if success {
		t.Errorf("scrape_runs.success true; expected false")
	}
	if !errMsg.Valid || !strings.Contains(errMsg.String, "all outlets failed") {
		t.Errorf("expected aggregated failure message, got %q", errMsg.String)
	}
}

// Compile-time assertion that the package's helper transport satisfies the
// RoundTripper contract — guards against accidental signature drift.
var _ http.RoundTripper = (*hostRedirectTransport)(nil)
var _ http.RoundTripper = (*rateLimitCounter)(nil)

// Silence the "imported and not used" check for unused stdlib symbols
// reached only in skipped DB paths.
var _ = errors.New
