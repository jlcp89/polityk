// Package dhondt allocates parliamentary seats via the D'Hondt
// highest-averages method. Used for Guatemala's congressional districts
// (23 distritales of 2–19 seats), the 32-seat national list, and the
// 20-seat PARLACEN list (ADR-008, ADR-016).
//
// The allocator is pure: no I/O, no global state, no goroutines. Ties on
// the same quotient are broken by ascending PartyID (project convention,
// CONTEXT.md domain glossary).
package dhondt

import "sort"

// PartyID identifies a party in the allocation. The model layer maps it
// to parties.party_id (ADR-008); the dhondt package keeps it abstract so
// the allocator can be reused for non-party allocations (e.g., slate
// councilmember seats in a municipality).
type PartyID int

// Allocate distributes `seats` among parties by D'Hondt highest-averages.
//
//   - votes: map from PartyID to vote count. Non-positive vote counts are
//     ignored (the party is eligible only when votes > 0).
//   - seats: number of seats to allocate. Zero or negative returns an
//     empty map.
//
// The returned map has one entry per input PartyID (zero for parties
// that won no seats). When fewer parties have positive votes than there
// are seats, the algorithm stops and unallocated seats are simply not
// assigned — the caller can detect this via sum-of-values < seats.
//
// Determinism: ties on `votes / (seats_so_far + 1)` are broken by the
// lower PartyID winning the seat. With identical inputs, Allocate
// returns identical outputs (no randomness, no map-iteration leakage).
func Allocate(votes map[PartyID]int, seats int) map[PartyID]int {
	result := make(map[PartyID]int, len(votes))
	for id := range votes {
		result[id] = 0
	}
	if seats <= 0 || len(votes) == 0 {
		return result
	}

	ids := make([]PartyID, 0, len(votes))
	for id, v := range votes {
		if v > 0 {
			ids = append(ids, id)
		}
	}
	sort.Slice(ids, func(i, j int) bool { return ids[i] < ids[j] })
	if len(ids) == 0 {
		return result
	}

	for s := 0; s < seats; s++ {
		// Find the party whose next quotient is largest. Iterating ids in
		// ascending order with a strict-greater comparison guarantees the
		// lower PartyID wins on ties.
		bestIdx := 0
		bestID := ids[0]
		for k := 1; k < len(ids); k++ {
			id := ids[k]
			// votes[id] / (result[id]+1)  >  votes[bestID] / (result[bestID]+1)
			// rearranged to avoid float / division:
			lhs := int64(votes[id]) * int64(result[bestID]+1)
			rhs := int64(votes[bestID]) * int64(result[id]+1)
			if lhs > rhs {
				bestIdx = k
				bestID = id
			}
		}
		result[ids[bestIdx]]++
	}

	return result
}
