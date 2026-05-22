//go:build ignore

// gen.go materialises 2019_results.csv from 2019_inputs.csv by running the
// D'Hondt allocator. Run from the repo root:
//
//	go run ./internal/dhondt/testdata/gen.go
//
// The generated file is the test fixture committed alongside this tool; the
// tests assert that the production Allocate exactly reproduces it. When TSE
// official results land via issue #19, replace 2019_inputs.csv with the
// authoritative vote counts and re-run gen.go.
package main

import (
	"encoding/csv"
	"fmt"
	"os"
	"sort"
	"strconv"

	"github.com/jlcp89/polityk/internal/dhondt"
)

type row struct {
	race      string
	seats     int
	partyID   dhondt.PartyID
	partyName string
	votes     int
}

func main() {
	in, err := os.Open("internal/dhondt/testdata/2019_inputs.csv")
	if err != nil {
		fmt.Fprintln(os.Stderr, "open inputs:", err)
		os.Exit(1)
	}
	defer in.Close()

	r := csv.NewReader(in)
	r.FieldsPerRecord = 5
	records, err := r.ReadAll()
	if err != nil {
		fmt.Fprintln(os.Stderr, "read inputs:", err)
		os.Exit(1)
	}
	if len(records) < 2 {
		fmt.Fprintln(os.Stderr, "inputs csv is empty")
		os.Exit(1)
	}

	rows := make([]row, 0, len(records)-1)
	for i, rec := range records[1:] {
		seats, err1 := strconv.Atoi(rec[1])
		pid, err2 := strconv.Atoi(rec[2])
		votes, err3 := strconv.Atoi(rec[4])
		if err1 != nil || err2 != nil || err3 != nil {
			fmt.Fprintf(os.Stderr, "row %d parse error\n", i+2)
			os.Exit(1)
		}
		rows = append(rows, row{
			race:      rec[0],
			seats:     seats,
			partyID:   dhondt.PartyID(pid),
			partyName: rec[3],
			votes:     votes,
		})
	}

	// Group by race, preserve first-seen order.
	type group struct {
		seats int
		rows  []row
	}
	groups := make(map[string]*group)
	order := []string{}
	for _, r := range rows {
		g, ok := groups[r.race]
		if !ok {
			g = &group{seats: r.seats}
			groups[r.race] = g
			order = append(order, r.race)
		}
		if g.seats != r.seats {
			fmt.Fprintf(os.Stderr, "race %s: seat count varies across rows\n", r.race)
			os.Exit(1)
		}
		g.rows = append(g.rows, r)
	}

	out, err := os.Create("internal/dhondt/testdata/2019_results.csv")
	if err != nil {
		fmt.Fprintln(os.Stderr, "create outputs:", err)
		os.Exit(1)
	}
	defer out.Close()

	w := csv.NewWriter(out)
	defer w.Flush()
	if err := w.Write([]string{"race", "seats", "party_id", "party_name", "votes", "expected_seats"}); err != nil {
		fmt.Fprintln(os.Stderr, "write header:", err)
		os.Exit(1)
	}

	for _, race := range order {
		g := groups[race]
		votes := make(map[dhondt.PartyID]int, len(g.rows))
		for _, r := range g.rows {
			votes[r.partyID] = r.votes
		}
		alloc := dhondt.Allocate(votes, g.seats)

		// Sanity: total seats == g.seats (positive-vote parties should saturate).
		total := 0
		for _, s := range alloc {
			total += s
		}
		if total != g.seats {
			fmt.Fprintf(os.Stderr, "race %s: allocated %d seats but expected %d\n", race, total, g.seats)
			os.Exit(1)
		}

		// Sort by party_id ascending for stable CSV output.
		sort.Slice(g.rows, func(i, j int) bool { return g.rows[i].partyID < g.rows[j].partyID })
		for _, r := range g.rows {
			rec := []string{
				r.race,
				strconv.Itoa(g.seats),
				strconv.Itoa(int(r.partyID)),
				r.partyName,
				strconv.Itoa(r.votes),
				strconv.Itoa(alloc[r.partyID]),
			}
			if err := w.Write(rec); err != nil {
				fmt.Fprintln(os.Stderr, "write row:", err)
				os.Exit(1)
			}
		}
	}

	fmt.Println("wrote internal/dhondt/testdata/2019_results.csv")
}
