package dhondt

import (
	"encoding/csv"
	"math/rand"
	"os"
	"path/filepath"
	"sort"
	"strconv"
	"testing"
)

// --- First-principles cases ---------------------------------------------------
//
// These are hand-verifiable D'Hondt allocations from the textbook
// (https://en.wikipedia.org/wiki/D%27Hondt_method#Allocation). They prove the
// algorithm — independent of any election fixture.

func TestAllocate_TextbookExample(t *testing.T) {
	// Classic Wikipedia D'Hondt example: 8 seats, 4 parties.
	// Quotients ranked: 100,80,50,40,33.3(A),30(C),26.6(B),25(A) → A=4 B=3 C=1 D=0.
	got := Allocate(map[PartyID]int{1: 100, 2: 80, 3: 30, 4: 20}, 8)
	want := map[PartyID]int{1: 4, 2: 3, 3: 1, 4: 0}
	assertMapEqual(t, want, got)
}

func TestAllocate_TieBrokenByLowerPartyID(t *testing.T) {
	// Two parties with identical votes and a single seat: lower party_id wins.
	got := Allocate(map[PartyID]int{7: 1000, 3: 1000}, 1)
	assertMapEqual(t, map[PartyID]int{3: 1, 7: 0}, got)

	// Three-way tie, two seats: ids 2 and 4 win, not 9.
	got = Allocate(map[PartyID]int{9: 500, 2: 500, 4: 500}, 2)
	assertMapEqual(t, map[PartyID]int{2: 1, 4: 1, 9: 0}, got)
}

func TestAllocate_DegenerateInputs(t *testing.T) {
	// Zero seats → all zero, no panic.
	got := Allocate(map[PartyID]int{1: 100, 2: 50}, 0)
	assertMapEqual(t, map[PartyID]int{1: 0, 2: 0}, got)

	// Negative seats treated as zero.
	got = Allocate(map[PartyID]int{1: 100}, -3)
	assertMapEqual(t, map[PartyID]int{1: 0}, got)

	// Empty votes → empty result.
	got = Allocate(map[PartyID]int{}, 5)
	if len(got) != 0 {
		t.Fatalf("expected empty result, got %v", got)
	}

	// Parties with zero or negative votes are ineligible; one positive-vote
	// party gets all seats up to its quotient series.
	got = Allocate(map[PartyID]int{1: 0, 2: 50, 3: -10}, 3)
	assertMapEqual(t, map[PartyID]int{1: 0, 2: 3, 3: 0}, got)

	// More seats than positive-vote parties can absorb still terminates: the
	// one party simply collects every seat (D'Hondt has no minimum-quotient
	// rule in our implementation).
	got = Allocate(map[PartyID]int{1: 100, 2: 0}, 5)
	assertMapEqual(t, map[PartyID]int{1: 5, 2: 0}, got)

	// All-zero votes → no seats allocated (no positive quotient exists).
	got = Allocate(map[PartyID]int{1: 0, 2: 0}, 3)
	assertMapEqual(t, map[PartyID]int{1: 0, 2: 0}, got)
}

// --- 2019 fixture sweep -------------------------------------------------------
//
// Table-driven test that asserts Allocate exactly reproduces the seat
// allocation recorded in testdata/2019_results.csv for every Guatemalan
// 2019 congressional race — 23 distritales + the 32-seat nacional + the
// 20-seat PARLACEN. 25 cases total.
//
// Provenance: see testdata/README.md. Vote counts approximate published 2019
// TSE totals; the fixture is the regression baseline until issue #19 lands
// the authoritative resultados2019.tse.org.gt Excel loader, at which point
// testdata/gen.go rebuilds 2019_results.csv from official numbers.

type fixtureRow struct {
	race          string
	seats         int
	partyID       PartyID
	partyName     string
	votes         int
	expectedSeats int
}

func TestAllocate_2019Fixtures(t *testing.T) {
	races, order := loadFixture(t)
	if len(races) != 25 {
		t.Fatalf("fixture must cover 25 races (23 distritales + nacional + parlacen), got %d", len(races))
	}

	for _, race := range order {
		rows := races[race]
		t.Run(race, func(t *testing.T) {
			seats := rows[0].seats
			votes := make(map[PartyID]int, len(rows))
			expected := make(map[PartyID]int, len(rows))
			for _, r := range rows {
				votes[r.partyID] = r.votes
				expected[r.partyID] = r.expectedSeats
			}

			got := Allocate(votes, seats)
			assertMapEqual(t, expected, got)

			// Defence-in-depth: the fixture's expected_seats column must sum
			// to the declared seat count. Catches drift if 2019_results.csv
			// is hand-edited without re-running gen.go.
			sum := 0
			for _, s := range expected {
				sum += s
			}
			if sum != seats {
				t.Fatalf("fixture expected_seats sum to %d, declared seats=%d", sum, seats)
			}
		})
	}
}

// --- Property tests -----------------------------------------------------------

func TestAllocate_TotalSeatsInvariant(t *testing.T) {
	// For every seeded distribution with at least one positive-vote party and
	// seats ≤ a reasonable bound, sum(seats) == seats parameter.
	rng := rand.New(rand.NewSource(1))
	for trial := 0; trial < 200; trial++ {
		nParties := 2 + rng.Intn(9) // 2..10 parties
		seats := 1 + rng.Intn(40)   // 1..40 seats

		votes := make(map[PartyID]int, nParties)
		hasPositive := false
		for i := 0; i < nParties; i++ {
			v := rng.Intn(100000)
			if v > 0 {
				hasPositive = true
			}
			votes[PartyID(i+1)] = v
		}
		if !hasPositive {
			votes[1] = 1 // ensure progress
		}

		got := Allocate(votes, seats)
		sum := 0
		for _, s := range got {
			sum += s
		}
		if sum != seats {
			t.Fatalf("trial %d: total seats=%d, want %d (votes=%v)", trial, sum, seats, votes)
		}
	}
}

func TestAllocate_Monotonicity(t *testing.T) {
	// If party A's votes increase while no other party's votes change, A's
	// seat count must not decrease. (Property guaranteed by D'Hondt.)
	rng := rand.New(rand.NewSource(42))
	for trial := 0; trial < 200; trial++ {
		nParties := 3 + rng.Intn(7)
		seats := 2 + rng.Intn(30)

		base := make(map[PartyID]int, nParties)
		for i := 0; i < nParties; i++ {
			base[PartyID(i+1)] = 1000 + rng.Intn(50000)
		}
		target := PartyID(1 + rng.Intn(nParties))

		alloc1 := Allocate(base, seats)

		boosted := make(map[PartyID]int, nParties)
		for id, v := range base {
			boosted[id] = v
		}
		boosted[target] += 1 + rng.Intn(20000)

		alloc2 := Allocate(boosted, seats)

		if alloc2[target] < alloc1[target] {
			t.Fatalf("trial %d: monotonicity violated for party %d (%d → %d). base=%v boosted=%v",
				trial, target, alloc1[target], alloc2[target], base, boosted)
		}
	}
}

func TestAllocate_Determinism(t *testing.T) {
	// Identical inputs produce bit-identical outputs across repeated calls,
	// regardless of map-iteration ordering.
	votes := map[PartyID]int{
		5: 100, 1: 100, 9: 100, 3: 100, 7: 100, // five-way tie
		2: 50, 4: 50, 6: 50, 8: 50,
	}
	first := Allocate(votes, 7)
	for i := 0; i < 100; i++ {
		got := Allocate(votes, 7)
		assertMapEqual(t, first, got)
	}
}

// --- helpers ------------------------------------------------------------------

func assertMapEqual(t *testing.T, want, got map[PartyID]int) {
	t.Helper()
	if len(want) != len(got) {
		t.Fatalf("map length mismatch: want %v, got %v", want, got)
	}
	keys := make([]PartyID, 0, len(want))
	for k := range want {
		keys = append(keys, k)
	}
	sort.Slice(keys, func(i, j int) bool { return keys[i] < keys[j] })
	for _, k := range keys {
		if want[k] != got[k] {
			t.Fatalf("party %d: want %d seats, got %d (full want=%v got=%v)", k, want[k], got[k], want, got)
		}
	}
}

func loadFixture(t *testing.T) (map[string][]fixtureRow, []string) {
	t.Helper()
	path := filepath.Join("testdata", "2019_results.csv")
	f, err := os.Open(path)
	if err != nil {
		t.Fatalf("open fixture %s: %v", path, err)
	}
	t.Cleanup(func() { _ = f.Close() })

	r := csv.NewReader(f)
	r.FieldsPerRecord = 6
	records, err := r.ReadAll()
	if err != nil {
		t.Fatalf("parse fixture: %v", err)
	}
	if len(records) < 2 {
		t.Fatalf("fixture is empty")
	}

	races := make(map[string][]fixtureRow)
	order := []string{}
	for i, rec := range records[1:] {
		seats, err1 := strconv.Atoi(rec[1])
		pid, err2 := strconv.Atoi(rec[2])
		votes, err3 := strconv.Atoi(rec[4])
		exp, err4 := strconv.Atoi(rec[5])
		if err1 != nil || err2 != nil || err3 != nil || err4 != nil {
			t.Fatalf("fixture row %d parse error: %v / %v / %v / %v", i+2, err1, err2, err3, err4)
		}
		row := fixtureRow{
			race:          rec[0],
			seats:         seats,
			partyID:       PartyID(pid),
			partyName:     rec[3],
			votes:         votes,
			expectedSeats: exp,
		}
		if _, seen := races[row.race]; !seen {
			order = append(order, row.race)
		}
		races[row.race] = append(races[row.race], row)
	}
	return races, order
}
