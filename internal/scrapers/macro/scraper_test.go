package macro

import (
	"context"
	"net/http"
	"net/http/httptest"
	"strings"
	"sync/atomic"
	"testing"
)

// newFixtureServer returns an httptest server that serves the named fixture
// file from testdata/ for every GET. It also exposes a counter so tests can
// assert how many requests reached the upstream feed.
func newFixtureServer(t *testing.T, fixture string) (*httptest.Server, *atomic.Int32, *atomic.Value) {
	t.Helper()
	calls := &atomic.Int32{}
	gotUA := &atomic.Value{}
	srv := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		calls.Add(1)
		gotUA.Store(r.Header.Get("User-Agent"))
		w.Header().Set("Content-Type", "text/csv")
		_, _ = w.Write([]byte(readTestdata(t, fixture)))
	}))
	t.Cleanup(srv.Close)
	return srv, calls, gotUA
}

func TestClient_RunFetchesFixture_NilDB(t *testing.T) {
	t.Parallel()
	cases := []struct {
		ctor    func() *Client
		fixture string
		source  string
		// minRows is a lower bound on parsed rows. Exact counts can drift if
		// fixtures gain rows; the test asserts the contract not the volume.
		minRows int
	}{
		{NewBanguatClient, "banguat.csv", SourceBanguat, 5},
		{NewINEClient, "ine.csv", SourceINE, 5},
		{NewSEGEPLANClient, "segeplan.csv", SourceSEGEPLAN, 3},
		{NewMINFINClient, "minfin.csv", SourceMINFIN, 3},
	}
	for _, tc := range cases {
		t.Run(tc.source, func(t *testing.T) {
			t.Parallel()
			srv, calls, gotUA := newFixtureServer(t, tc.fixture)

			c := tc.ctor()
			c.FeedURL = srv.URL
			c.HTTPClient = srv.Client()

			stats, err := c.Run(context.Background(), nil) // nil DB: upsert + stamp are no-ops
			if err != nil {
				t.Fatalf("Run: %v", err)
			}
			if stats.Source != tc.source {
				t.Errorf("Source: got %q want %q", stats.Source, tc.source)
			}
			if stats.Fetched < tc.minRows {
				t.Errorf("Fetched: got %d want >=%d", stats.Fetched, tc.minRows)
			}
			if calls.Load() != 1 {
				t.Errorf("HTTP calls: got %d want 1", calls.Load())
			}
			ua, _ := gotUA.Load().(string)
			if !strings.Contains(ua, "PolitykForecastBot") {
				t.Errorf("UA: got %q want substring %q", ua, "PolitykForecastBot")
			}
		})
	}
}

func TestClient_Run_NonOKStatusReturnsError(t *testing.T) {
	t.Parallel()
	srv := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		w.WriteHeader(http.StatusServiceUnavailable)
	}))
	t.Cleanup(srv.Close)

	c := NewBanguatClient()
	c.FeedURL = srv.URL
	c.HTTPClient = srv.Client()

	_, err := c.Run(context.Background(), nil)
	if err == nil {
		t.Fatal("expected error for 503, got nil")
	}
	if !strings.Contains(err.Error(), "503") {
		t.Errorf("error message: got %q want substring %q", err.Error(), "503")
	}
}

func TestClient_Run_EmptyFeedURLFails(t *testing.T) {
	t.Parallel()
	c := &Client{Source: SourceBanguat}
	if _, err := c.Run(context.Background(), nil); err == nil {
		t.Fatal("expected error for empty FeedURL, got nil")
	}
}

func TestConstructors_HaveExpectedSources(t *testing.T) {
	t.Parallel()
	checks := []struct {
		name   string
		client *Client
		want   string
	}{
		{"banguat", NewBanguatClient(), SourceBanguat},
		{"ine", NewINEClient(), SourceINE},
		{"segeplan", NewSEGEPLANClient(), SourceSEGEPLAN},
		{"minfin", NewMINFINClient(), SourceMINFIN},
	}
	for _, c := range checks {
		if c.client.Source != c.want {
			t.Errorf("%s: Source got %q want %q", c.name, c.client.Source, c.want)
		}
		if c.client.FeedURL == "" {
			t.Errorf("%s: FeedURL empty", c.name)
		}
		if c.client.UserAgent == "" {
			t.Errorf("%s: UserAgent empty", c.name)
		}
	}
}
