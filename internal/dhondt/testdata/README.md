# dhondt testdata

`2019_results.csv` is the regression fixture for the Guatemalan 2019 congressional
seat allocations — 23 distritales + the 32-seat national list + the 20-seat
PARLACEN list. 25 races, one row per (race, party).

## Provenance

Vote counts in `2019_inputs.csv` approximate published 2019 TSE totals from
`resultados2019.tse.org.gt` and from the parties' nationally aggregated
shares. Seat counts per district match the electoral law in force for the
2019 election (see `docs/requirement.md` Section A and ADR-008/ADR-016).

`2019_results.csv` is materialised from `2019_inputs.csv` by running the
production `Allocate` function (see `gen.go`). The committed CSV serves as
the regression baseline: any future change to the allocator that perturbs an
allocation here fails CI.

When **issue #19** lands the authoritative `resultados2019.tse.org.gt`
Excel loader, replace `2019_inputs.csv` with the official per-district
vote counts and re-run:

```
go run ./internal/dhondt/testdata/gen.go
```

The diff on `2019_results.csv` is the answer to "did our D'Hondt match TSE's
published seat counts exactly?"

## Files

| File | Owner | Purpose |
|------|-------|---------|
| `2019_inputs.csv` | hand-curated | (race, seats, party_id, party_name, votes) source data |
| `gen.go` | tool (`//go:build ignore`) | regenerates `2019_results.csv` |
| `2019_results.csv` | generated | fixture used by `TestAllocate_2019Fixtures` |
