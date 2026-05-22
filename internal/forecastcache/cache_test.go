package forecastcache_test

import (
	"context"
	"errors"
	"sync"
	"sync/atomic"
	"testing"
	"time"

	"github.com/jlcp89/polityk/internal/forecastcache"
	"github.com/jlcp89/polityk/internal/handlers"
)

type fakeReader struct {
	calls    atomic.Int64
	forecast *handlers.PresidentialForecast
	err      error
}

func (f *fakeReader) LatestPublishedPresidential(_ context.Context) (*handlers.PresidentialForecast, error) {
	f.calls.Add(1)
	return f.forecast, f.err
}

func TestCache_FirstReadHitsUpstream(t *testing.T) {
	t.Parallel()
	want := &handlers.PresidentialForecast{Payload: []byte(`{"v":1}`), RunID: "run-1"}
	r := &fakeReader{forecast: want}
	c := forecastcache.New(r, time.Minute)

	got, err := c.LatestPublishedPresidential(context.Background())
	if err != nil {
		t.Fatalf("first read: %v", err)
	}
	if got != want {
		t.Fatalf("got %+v, want %+v", got, want)
	}
	if r.calls.Load() != 1 {
		t.Fatalf("upstream calls: got %d want 1", r.calls.Load())
	}
}

func TestCache_SecondReadHitsCache(t *testing.T) {
	t.Parallel()
	want := &handlers.PresidentialForecast{Payload: []byte(`{"v":2}`)}
	r := &fakeReader{forecast: want}
	c := forecastcache.New(r, time.Minute)

	if _, err := c.LatestPublishedPresidential(context.Background()); err != nil {
		t.Fatalf("first: %v", err)
	}
	if _, err := c.LatestPublishedPresidential(context.Background()); err != nil {
		t.Fatalf("second: %v", err)
	}
	if got := r.calls.Load(); got != 1 {
		t.Fatalf("upstream calls: got %d want 1 (second read should hit cache)", got)
	}
}

func TestCache_CachesNilForecast(t *testing.T) {
	t.Parallel()
	r := &fakeReader{forecast: nil}
	c := forecastcache.New(r, time.Minute)

	got, err := c.LatestPublishedPresidential(context.Background())
	if err != nil {
		t.Fatalf("first: %v", err)
	}
	if got != nil {
		t.Fatalf("expected nil forecast, got %+v", got)
	}
	if _, err := c.LatestPublishedPresidential(context.Background()); err != nil {
		t.Fatalf("second: %v", err)
	}
	if r.calls.Load() != 1 {
		t.Fatalf("upstream calls: got %d want 1 (nil forecast must be cached)", r.calls.Load())
	}
}

func TestCache_DoesNotCacheErrors(t *testing.T) {
	t.Parallel()
	r := &fakeReader{err: errors.New("connection refused")}
	c := forecastcache.New(r, time.Minute)

	if _, err := c.LatestPublishedPresidential(context.Background()); err == nil {
		t.Fatalf("first: expected error, got nil")
	}
	if _, err := c.LatestPublishedPresidential(context.Background()); err == nil {
		t.Fatalf("second: expected error, got nil")
	}
	if got := r.calls.Load(); got != 2 {
		t.Fatalf("upstream calls: got %d want 2 (errors must NOT be cached)", got)
	}
}

func TestCache_ExpiresAfterTTL(t *testing.T) {
	t.Parallel()
	want := &handlers.PresidentialForecast{Payload: []byte(`{}`)}
	r := &fakeReader{forecast: want}
	c := forecastcache.New(r, 5*time.Minute)

	now := time.Unix(0, 0)
	c.SetClock(func() time.Time { return now })

	if _, err := c.LatestPublishedPresidential(context.Background()); err != nil {
		t.Fatalf("first: %v", err)
	}
	now = now.Add(4 * time.Minute)
	if _, err := c.LatestPublishedPresidential(context.Background()); err != nil {
		t.Fatalf("second within TTL: %v", err)
	}
	if got := r.calls.Load(); got != 1 {
		t.Fatalf("calls within TTL: got %d want 1", got)
	}
	now = now.Add(2 * time.Minute) // total = 6 min, past 5-min TTL
	if _, err := c.LatestPublishedPresidential(context.Background()); err != nil {
		t.Fatalf("third after TTL: %v", err)
	}
	if got := r.calls.Load(); got != 2 {
		t.Fatalf("calls after TTL: got %d want 2", got)
	}
}

func TestCache_InvalidateClearsEntry(t *testing.T) {
	t.Parallel()
	r := &fakeReader{forecast: &handlers.PresidentialForecast{}}
	c := forecastcache.New(r, time.Minute)
	if _, err := c.LatestPublishedPresidential(context.Background()); err != nil {
		t.Fatalf("populate: %v", err)
	}
	if got := c.Len(); got != 1 {
		t.Fatalf("Len after populate: got %d want 1", got)
	}
	c.Invalidate(forecastcache.RaceTypePresidential)
	if got := c.Len(); got != 0 {
		t.Fatalf("Len after Invalidate: got %d want 0", got)
	}
	if _, err := c.LatestPublishedPresidential(context.Background()); err != nil {
		t.Fatalf("post-invalidate read: %v", err)
	}
	if got := r.calls.Load(); got != 2 {
		t.Fatalf("upstream calls: got %d want 2 (invalidate must force a refetch)", got)
	}
}

func TestCache_ClearWipesEverything(t *testing.T) {
	t.Parallel()
	r := &fakeReader{forecast: &handlers.PresidentialForecast{}}
	c := forecastcache.New(r, time.Minute)
	if _, err := c.LatestPublishedPresidential(context.Background()); err != nil {
		t.Fatalf("populate: %v", err)
	}
	c.Clear()
	if got := c.Len(); got != 0 {
		t.Fatalf("Len after Clear: got %d want 0", got)
	}
}

func TestCache_DefaultTTLAppliedOnZero(t *testing.T) {
	t.Parallel()
	r := &fakeReader{forecast: &handlers.PresidentialForecast{}}
	c := forecastcache.New(r, 0)
	now := time.Unix(0, 0)
	c.SetClock(func() time.Time { return now })

	if _, err := c.LatestPublishedPresidential(context.Background()); err != nil {
		t.Fatalf("populate: %v", err)
	}
	now = now.Add(4 * time.Minute) // inside 5-min default
	if _, err := c.LatestPublishedPresidential(context.Background()); err != nil {
		t.Fatalf("second: %v", err)
	}
	if got := r.calls.Load(); got != 1 {
		t.Fatalf("calls within default TTL: got %d want 1", got)
	}
	now = now.Add(2 * time.Minute) // past 5-min default
	if _, err := c.LatestPublishedPresidential(context.Background()); err != nil {
		t.Fatalf("third: %v", err)
	}
	if got := r.calls.Load(); got != 2 {
		t.Fatalf("calls past default TTL: got %d want 2", got)
	}
}

// TestCache_ConcurrentReadsAndInvalidate exercises the mutex under the race
// detector: a steady stream of reads and a clear in a separate goroutine
// must never panic or trip -race. The exact ratio of cache vs upstream
// hits is not asserted (it depends on scheduler), but every read must
// return successfully and the upstream must have been called at least once.
func TestCache_ConcurrentReadsAndInvalidate(t *testing.T) {
	t.Parallel()
	r := &fakeReader{forecast: &handlers.PresidentialForecast{Payload: []byte(`{}`)}}
	c := forecastcache.New(r, time.Minute)

	var wg sync.WaitGroup
	const readers = 8
	const reads = 200
	for i := 0; i < readers; i++ {
		wg.Add(1)
		go func() {
			defer wg.Done()
			for j := 0; j < reads; j++ {
				if _, err := c.LatestPublishedPresidential(context.Background()); err != nil {
					t.Errorf("concurrent read: %v", err)
					return
				}
			}
		}()
	}
	wg.Add(1)
	go func() {
		defer wg.Done()
		for j := 0; j < 50; j++ {
			c.Clear()
			time.Sleep(time.Microsecond)
		}
	}()
	wg.Wait()
	if r.calls.Load() < 1 {
		t.Fatalf("upstream never called")
	}
}
