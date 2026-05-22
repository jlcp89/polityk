"""Tests for `pipeline.scripts.prodatos_2023_backtest` (issue #29, ADR-017).

The pure-logic tests (CLI, fixture shape, assertion helper) run
unconditionally. The end-to-end PyMC fit is gated by
``pytest.importorskip("pymc")``.
"""

from __future__ import annotations

import pytest

from pipeline.scripts import prodatos_2023_backtest as bt

# ---------------------------------------------------------------------------
# Pure-logic: synthetic fixtures cover the documented failure mode
# ---------------------------------------------------------------------------


def test_synthetic_pre_2023_has_three_pollsters_and_four_cycles() -> None:
    rows = bt.synthetic_2007_to_2019(seed=17)
    cycles = {r.cycle for r in rows}
    pollster_names = {r.pollster_name for r in rows}
    assert cycles == {2007, 2011, 2015, 2019}
    assert pollster_names == {"CID Gallup", "ProDatos", "Borge y Asociados"}
    # 4 cycles x 3 pollsters x 5 candidates = 60 rows
    assert len(rows) == 60


def test_synthetic_2023_contains_prodatos_arevalo_undercall() -> None:
    """The 2023 slice must encode the ~12.6pp ProDatos miss on Arévalo."""
    rows = bt.synthetic_2023(seed=17)
    prodatos = [r for r in rows if r.pollster_name == "ProDatos"]
    assert prodatos, "ProDatos rows missing from 2023 fixture"
    worst = min(r.error for r in prodatos)
    # The headline error ProDatos posted on Arévalo in 2023.
    assert worst <= -0.12
    assert worst >= -0.13


def test_assert_prodatos_widens_passes_on_post_above_floor() -> None:
    result = bt.BacktestResult(
        pre_2023_mean=0.0,
        pre_2023_sd=0.02,
        pre_2023_samples=20,
        post_2023_mean=-0.03,
        post_2023_sd=0.05,
        post_2023_samples=25,
    )
    # Should not raise; ratio = 0.05 / 0.02 = 2.5 >= 2.0 and post sd >= 0.045.
    bt.assert_prodatos_widens(result)


def test_assert_prodatos_widens_fails_when_post_sd_too_small() -> None:
    result = bt.BacktestResult(
        pre_2023_mean=0.0,
        pre_2023_sd=0.015,
        pre_2023_samples=20,
        post_2023_mean=-0.03,
        post_2023_sd=0.04,  # below 0.045 floor
        post_2023_samples=25,
    )
    with pytest.raises(AssertionError, match="did not widen"):
        bt.assert_prodatos_widens(result)


def test_assert_prodatos_widens_fails_when_ratio_too_small() -> None:
    """A post sd above the floor but only ~1.2x the pre sd must still fail."""
    result = bt.BacktestResult(
        pre_2023_mean=0.0,
        pre_2023_sd=0.05,
        pre_2023_samples=20,
        post_2023_mean=-0.03,
        post_2023_sd=0.07,  # only 1.4x — below 2.0 ratio floor
        post_2023_samples=25,
    )
    with pytest.raises(AssertionError, match="did not meaningfully widen"):
        bt.assert_prodatos_widens(result)


def test_backtest_result_widening_ratio_handles_zero_pre() -> None:
    result = bt.BacktestResult(
        pre_2023_mean=0.0,
        pre_2023_sd=0.0,
        pre_2023_samples=0,
        post_2023_mean=0.0,
        post_2023_sd=0.1,
        post_2023_samples=5,
    )
    assert result.widening_ratio == float("inf")


def test_cli_use_database_without_dsn_returns_2(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("DATABASE_URL", raising=False)
    rc = bt.main(["--use-database"])
    assert rc == 2


# ---------------------------------------------------------------------------
# PyMC end-to-end backtest — gated by pymc availability
# ---------------------------------------------------------------------------


@pytest.mark.slow
def test_prodatos_backtest_widens_sd_end_to_end() -> None:
    """ADR-017 acceptance: ProDatos sd widens after 2023 evidence."""
    pytest.importorskip("pymc")

    pre_rows = bt.synthetic_2007_to_2019(seed=17)
    post_rows = bt.synthetic_2023(seed=17)
    # Larger tune + slightly relaxed rhat for the post-2023 fit: the
    # ~12.6pp ProDatos outlier creates a sharp posterior for tau_bias /
    # sigma[ProDatos] that needs more warmup than the production default.
    result = bt.run_backtest(
        pre_rows,
        post_rows,
        draws=2000,
        tune=2500,
        chains=4,
        seed=17,
        rhat_threshold=1.05,
        ess_threshold=100.0,
    )
    # Sample-count flips visibly after the 2023 slice is added.
    assert result.post_2023_samples > result.pre_2023_samples
    # The actual ADR-017 gate.
    bt.assert_prodatos_widens(result)
