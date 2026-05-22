package rss

import (
	"context"
	"net/http"
	"net/http/httptest"
	"net/url"
	"strings"
	"testing"
	"time"
)

func TestEvenSample(t *testing.T) {
	t.Parallel()
	tests := []struct {
		name string
		in   []string
		n    int
		want []string
	}{
		{name: "empty in", in: nil, n: 3, want: nil},
		{name: "zero n", in: []string{"a", "b"}, n: 0, want: nil},
		{name: "in shorter than n", in: []string{"a", "b"}, n: 5, want: []string{"a", "b"}},
		{
			name: "evenly spaced",
			in:   []string{"a", "b", "c", "d", "e", "f", "g", "h", "i", "j"},
			n:    5,
			// step = 10/5 = 2.0; idx = 0, 2, 4, 6, 8 → "a","c","e","g","i"
			want: []string{"a", "c", "e", "g", "i"},
		},
		{
			name: "single sample",
			in:   []string{"a", "b", "c"},
			n:    1,
			want: []string{"a"},
		},
	}
	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			t.Parallel()
			got := evenSample(tt.in, tt.n)
			if len(got) != len(tt.want) {
				t.Fatalf("len: got %d, want %d (got=%v want=%v)", len(got), len(tt.want), got, tt.want)
			}
			for i := range got {
				if got[i] != tt.want[i] {
					t.Errorf("idx %d: got %q want %q", i, got[i], tt.want[i])
				}
			}
		})
	}
}

func TestArchiveClient_QueryCDX_ParsesJSON(t *testing.T) {
	t.Parallel()
	body := `[["timestamp"],
["20230301075305"],
["20230301183734"],
["20230302021700"]]`
	srv := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		if !strings.Contains(r.URL.RawQuery, "from=20230301") {
			t.Errorf("CDX query missing from param: %s", r.URL.RawQuery)
		}
		w.Header().Set("Content-Type", "application/json")
		_, _ = w.Write([]byte(body))
	}))
	t.Cleanup(srv.Close)

	c := &ArchiveClient{
		HTTPClient: srv.Client(),
		UserAgent:  "test/1",
		CDXBase:    srv.URL,
	}
	stamps, err := c.queryCDX(context.Background(), "https://example.com/feed/",
		time.Date(2023, 3, 1, 0, 0, 0, 0, time.UTC),
		time.Date(2023, 3, 10, 0, 0, 0, 0, time.UTC))
	if err != nil {
		t.Fatalf("queryCDX: %v", err)
	}
	want := []string{"20230301075305", "20230301183734", "20230302021700"}
	if len(stamps) != len(want) {
		t.Fatalf("got %d stamps, want %d (got=%v)", len(stamps), len(want), stamps)
	}
	for i, s := range stamps {
		if s != want[i] {
			t.Errorf("idx %d: got %q want %q", i, s, want[i])
		}
	}
}

func TestArchiveClient_FetchArchivedFeed_ParsesItems(t *testing.T) {
	t.Parallel()
	feed := `<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0"><channel><title>x</title><link>x</link><description>x</description>
<item>
  <title>Arévalo gana la elección</title>
  <link>https://example.com/articulo-1</link>
  <description>Resumen de la jornada.</description>
  <pubDate>Sun, 20 Aug 2023 23:00:00 +0000</pubDate>
</item>
<item>
  <title>Torres concede</title>
  <link>https://example.com/articulo-2</link>
  <description>Reacción tras el conteo.</description>
</item>
</channel></rss>`
	srv := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		w.Header().Set("Content-Type", "application/rss+xml")
		_, _ = w.Write([]byte(feed))
	}))
	t.Cleanup(srv.Close)

	c := &ArchiveClient{
		HTTPClient:  srv.Client(),
		UserAgent:   "test/1",
		WaybackBase: srv.URL + "/",
	}
	// fetchArchivedFeed builds <base><timestamp>id_/<feedURL>; the test
	// server ignores the path and returns the fixture, so any timestamp +
	// feedURL works.
	items, err := c.fetchArchivedFeed(context.Background(), "20230301000000",
		"https://example.com/feed/")
	if err != nil {
		t.Fatalf("fetchArchivedFeed: %v", err)
	}
	if len(items) != 2 {
		t.Fatalf("got %d items, want 2", len(items))
	}
	if items[0].Title != "Arévalo gana la elección" {
		t.Errorf("item[0].Title = %q", items[0].Title)
	}
	if items[0].URL != "https://example.com/articulo-1" {
		t.Errorf("item[0].URL = %q", items[0].URL)
	}
	if items[0].PublishedAt == nil {
		t.Errorf("item[0].PublishedAt is nil")
	}
	if items[1].Body == "" {
		t.Errorf("item[1].Body unexpectedly empty")
	}
}

func TestDefaultArchiveOutlets_NonEmpty(t *testing.T) {
	t.Parallel()
	if len(DefaultArchiveOutlets()) == 0 {
		t.Fatal("DefaultArchiveOutlets returned empty list")
	}
	for _, o := range DefaultArchiveOutlets() {
		if o.Name == "" || o.FeedURL == "" {
			t.Errorf("bad archive outlet: %+v", o)
		}
		if _, err := url.Parse(o.FeedURL); err != nil {
			t.Errorf("invalid FeedURL %q: %v", o.FeedURL, err)
		}
	}
}

func TestDefaultArchiveWindows_NonEmpty(t *testing.T) {
	t.Parallel()
	for _, w := range DefaultArchiveWindows() {
		if !w.From.Before(w.To) {
			t.Errorf("window From >= To: %+v", w)
		}
		if w.Samples <= 0 {
			t.Errorf("window samples <= 0: %+v", w)
		}
	}
}
