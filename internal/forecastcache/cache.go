// Package forecastcache holds the in-process LRU mandated by ADR-006: the
// Go API serves /v1/forecast/* from the latest is_published=TRUE row per
// race_type, fronted by a 5-minute TTL cache that is invalidated on each
// `forecast_ready` LISTEN/NOTIFY arrival (see internal/listener).
//
// The "LRU" naming follows the ADR. The actual eviction policy is purely
// time-based: with three race_types (presidential, congress, municipal)
// there is no contention for slots, so a size cap would be ceremony.
// The same Cache satisfies handlers.ForecastReader, so it slots in between
// store.ForecastReader and the HTTP handler without touching either.
package forecastcache

import (
	"context"
	"sync"
	"time"

	"github.com/jlcp89/polityk/internal/handlers"
)

// DefaultTTL is the 5-minute window mandated by ADR-006. Entries that age
// past this without a LISTEN/NOTIFY-driven invalidation are refreshed on
// the next request.
const DefaultTTL = 5 * time.Minute

// RaceTypePresidential is the cache key the presidential reader uses.
// Exported so the listener (#10) can target a specific race_type when it
// learns to parse run_id → race_type from notifications. Until then the
// listener clears the whole cache via Clear().
const RaceTypePresidential = "presidential"

// Cache wraps a handlers.ForecastReader with a per-race_type TTL cache and
// satisfies the same interface so it drops into the handler wiring with no
// other change. Concurrent reads are served from the in-memory map; misses
// fall through to the upstream reader and the resulting (forecast, error)
// pair is stored only on a clean read — errors are not cached.
type Cache struct {
	upstream handlers.ForecastReader
	ttl      time.Duration
	now      func() time.Time

	mu    sync.Mutex
	items map[string]entry
}

type entry struct {
	forecast  *handlers.PresidentialForecast
	expiresAt time.Time
}

// New returns a Cache that delegates to upstream on miss. Pass 0 for ttl to
// use DefaultTTL.
func New(upstream handlers.ForecastReader, ttl time.Duration) *Cache {
	if ttl <= 0 {
		ttl = DefaultTTL
	}
	return &Cache{
		upstream: upstream,
		ttl:      ttl,
		now:      time.Now,
		items:    make(map[string]entry),
	}
}

// LatestPublishedPresidential serves the cached payload when fresh; on miss
// or expiry it fetches from upstream and caches (including the nil
// "no published row" case so unpublished states do not hammer the DB).
func (c *Cache) LatestPublishedPresidential(ctx context.Context) (*handlers.PresidentialForecast, error) {
	if f, ok := c.get(RaceTypePresidential); ok {
		return f, nil
	}
	f, err := c.upstream.LatestPublishedPresidential(ctx)
	if err != nil {
		return nil, err
	}
	c.set(RaceTypePresidential, f)
	return f, nil
}

// Invalidate removes the entry for the given race_type. The next read for
// that race_type bypasses the cache.
func (c *Cache) Invalidate(raceType string) {
	c.mu.Lock()
	delete(c.items, raceType)
	c.mu.Unlock()
}

// Clear removes every entry. Called by the LISTEN/NOTIFY goroutine on each
// forecast_ready notification: until the listener carries enough metadata to
// target a specific race_type, the safe move is to drop the lot — a fresh
// fetch is cheap and reads are already O(1) on the published row.
func (c *Cache) Clear() {
	c.mu.Lock()
	c.items = make(map[string]entry)
	c.mu.Unlock()
}

// Len reports how many entries are currently cached. Exported for tests
// asserting that Clear / Invalidate / TTL expiry are doing what they claim.
func (c *Cache) Len() int {
	c.mu.Lock()
	defer c.mu.Unlock()
	return len(c.items)
}

// SetClock overrides the time source used for TTL math. For tests.
func (c *Cache) SetClock(now func() time.Time) {
	c.mu.Lock()
	c.now = now
	c.mu.Unlock()
}

func (c *Cache) get(key string) (*handlers.PresidentialForecast, bool) {
	c.mu.Lock()
	defer c.mu.Unlock()
	e, ok := c.items[key]
	if !ok {
		return nil, false
	}
	if !c.now().Before(e.expiresAt) {
		delete(c.items, key)
		return nil, false
	}
	return e.forecast, true
}

func (c *Cache) set(key string, f *handlers.PresidentialForecast) {
	c.mu.Lock()
	c.items[key] = entry{forecast: f, expiresAt: c.now().Add(c.ttl)}
	c.mu.Unlock()
}
