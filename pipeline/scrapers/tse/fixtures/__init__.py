"""Committed test fixtures for TSE loaders.

`tse_2019_presidential.xlsx` is a long-format normalisation of the TSE
2019 "Datos abiertos: Excel" export — synthetic small-sample data
(3 municipalities × 5 candidates round-1, × 2 candidates round-2) sized
to exercise the loader end-to-end without bloating the repo. Real TSE
totals plug into the loader by passing `expected_round{1,2}_total` to
`pipeline.scrapers.tse.load_2019_excel.load`.
"""
