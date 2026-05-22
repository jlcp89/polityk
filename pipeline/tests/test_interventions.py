"""Tests for ``pipeline.models.interventions`` (issue #35, ADR-019).

Three tiers, matching the rest of the suite:

1. Pure-logic unit tests (always run) — the sample-matrix transformer's mass
   invariants, the (kind × target_kind) resolution matrix, expired-row
   skipping, and the payload-shaped ``interventions_applied`` builder.
2. Fake-conn tests for :func:`load_active_interventions` and end-to-end for
   :func:`apply_interventions` on a hand-built :class:`PresidentialPosterior`.
3. End-to-end Postgres test gated by ``POLITYK_TEST_DATABASE_URL`` —
   inserts a candidate + a disqualifying intervention, calls
   ``predict.produce_forecast`` with ``interventions=None`` so the loader
   reads the DB, and asserts the posterior column for the target is all
   zeros in ``posterior_archives.sample_array``.
"""

from __future__ import annotations

import os
import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest

from pipeline.models import interventions as itv_mod
from pipeline.models import presidential as pres

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _candidate_inputs(
    cand_ids: list[int],
    party_ids: list[int | None] | None = None,
) -> list[pres.CandidateInput]:
    if party_ids is None:
        party_ids = [None] * len(cand_ids)
    return [
        pres.CandidateInput(
            candidate_id=cid,
            name=f"Cand {cid}",
            party_id=pid,
            party_name=f"Party {pid}" if pid is not None else None,
            wikidata_qid=None,
            feature_vector=None,
        )
        for cid, pid in zip(cand_ids, party_ids, strict=True)
    ]


def _itv(
    *,
    intervention_id: int = 1,
    target_kind: str = "candidate",
    target_id: int = 10,
    kind: str = "disqualified",
    effective_at: datetime | None = None,
    expires_at: datetime | None = None,
    override_probability: float | None = None,
    reason: str = "test reason",
    operator: str = "tester",
    target_name: str | None = None,
) -> itv_mod.Intervention:
    return itv_mod.Intervention(
        intervention_id=intervention_id,
        target_kind=target_kind,
        target_id=target_id,
        kind=kind,
        effective_at=effective_at or datetime(2027, 4, 15, tzinfo=UTC),
        expires_at=expires_at,
        override_probability=override_probability,
        reason=reason,
        operator=operator,
        target_name=target_name,
    )


def _synth_samples(
    rows: list[list[float]],
) -> Any:
    import numpy as np

    return np.array(rows, dtype=float)


# ---------------------------------------------------------------------------
# Sample-matrix math invariants
# ---------------------------------------------------------------------------


def test_no_interventions_returns_renormalised_pass_through() -> None:
    """Empty intervention list: samples normalised row-wise to sum-to-1.

    The applier always emits clean probability distributions even on the
    no-intervention path; this is the contract that lets the per-kind
    transformations rely on a stable starting point.
    """
    import numpy as np

    samples = _synth_samples(
        [
            [0.30, 0.25, 0.10, 0.05],  # sum = 0.70
            [0.40, 0.20, 0.15, 0.10],  # sum = 0.85
        ]
    )
    cand_inputs = _candidate_inputs([10, 20, 30, 40])
    out = itv_mod.apply_interventions_to_samples(samples, cand_inputs, [])
    np.testing.assert_allclose(out.sum(axis=1), [1.0, 1.0], atol=1e-9)


def test_disqualified_zeroes_target_and_preserves_unit_mass() -> None:
    """zero-out + renormalise: mass = 1.0 ± 1e-9 (acceptance criterion)."""
    import numpy as np

    samples = _synth_samples(
        [
            [0.30, 0.25, 0.10, 0.05],
            [0.40, 0.20, 0.15, 0.10],
            [0.10, 0.10, 0.10, 0.10],
        ]
    )
    cand_inputs = _candidate_inputs([10, 20, 30, 40])
    intervention = _itv(target_id=30, kind="disqualified")
    out = itv_mod.apply_interventions_to_samples(
        samples, cand_inputs, [intervention]
    )
    np.testing.assert_allclose(out[:, 2], 0.0, atol=1e-12)
    np.testing.assert_allclose(out.sum(axis=1), [1.0, 1.0, 1.0], atol=1e-9)
    # Surviving shares preserved their relative proportions: rows that started
    # with 0.30 : 0.25 : 0.05 → 0.30/0.60 : 0.25/0.60 : 0.05/0.60.
    np.testing.assert_allclose(
        out[0, [0, 1, 3]],
        [0.30 / 0.60, 0.25 / 0.60, 0.05 / 0.60],
        atol=1e-9,
    )


def test_withdrew_same_math_as_disqualified() -> None:
    """``withdrew`` shares the same transformation as ``disqualified``."""
    import numpy as np

    samples = _synth_samples([[0.5, 0.3, 0.2], [0.4, 0.4, 0.2]])
    cand_inputs = _candidate_inputs([1, 2, 3])
    out_a = itv_mod.apply_interventions_to_samples(
        samples, cand_inputs, [_itv(target_id=2, kind="withdrew")]
    )
    out_b = itv_mod.apply_interventions_to_samples(
        samples, cand_inputs, [_itv(target_id=2, kind="disqualified")]
    )
    np.testing.assert_allclose(out_a, out_b)


def test_party_cancelled_zeros_every_party_candidate_column() -> None:
    """``party_cancelled`` zeros every column with the matching party_id."""
    import numpy as np

    samples = _synth_samples([[0.3, 0.2, 0.1, 0.4]])
    # Candidates 10, 20 belong to party 100; 30, 40 to party 200.
    cand_inputs = _candidate_inputs([10, 20, 30, 40], party_ids=[100, 100, 200, 200])
    intervention = _itv(target_kind="party", target_id=100, kind="party_cancelled")
    out = itv_mod.apply_interventions_to_samples(
        samples, cand_inputs, [intervention]
    )
    np.testing.assert_allclose(out[:, 0:2], 0.0, atol=1e-12)
    np.testing.assert_allclose(out.sum(axis=1), [1.0], atol=1e-9)


def test_manual_probability_sets_target_and_renorms_siblings() -> None:
    """delta-replace + sibling-renorm: mass = 1.0 ± 1e-9 (acceptance criterion)."""
    import numpy as np

    samples = _synth_samples(
        [
            [0.30, 0.25, 0.10, 0.05],
            [0.40, 0.20, 0.15, 0.10],
        ]
    )
    cand_inputs = _candidate_inputs([10, 20, 30, 40])
    intervention = _itv(
        target_id=20, kind="manual_probability", override_probability=0.5
    )
    out = itv_mod.apply_interventions_to_samples(
        samples, cand_inputs, [intervention]
    )
    np.testing.assert_allclose(out[:, 1], 0.5, atol=1e-12)
    np.testing.assert_allclose(out.sum(axis=1), [1.0, 1.0], atol=1e-9)
    # Sibling proportions preserved within each row.
    # Row 0 siblings originally [0.30, 0.10, 0.05] → renormalised to sum 0.5.
    np.testing.assert_allclose(
        out[0, [0, 2, 3]],
        np.array([0.30, 0.10, 0.05]) * 0.5 / 0.45,
        atol=1e-9,
    )


def test_manual_probability_override_one_zeros_siblings() -> None:
    """override=1.0 collapses every other candidate to zero."""
    import numpy as np

    samples = _synth_samples([[0.3, 0.3, 0.4]])
    cand_inputs = _candidate_inputs([1, 2, 3])
    intervention = _itv(
        target_id=1, kind="manual_probability", override_probability=1.0
    )
    out = itv_mod.apply_interventions_to_samples(
        samples, cand_inputs, [intervention]
    )
    np.testing.assert_allclose(out, [[1.0, 0.0, 0.0]], atol=1e-9)


def test_manual_probability_override_zero_zeros_target() -> None:
    """override=0.0 zeros the target and renormalises siblings to sum to 1."""
    import numpy as np

    samples = _synth_samples([[0.3, 0.3, 0.4]])
    cand_inputs = _candidate_inputs([1, 2, 3])
    intervention = _itv(
        target_id=1, kind="manual_probability", override_probability=0.0
    )
    out = itv_mod.apply_interventions_to_samples(
        samples, cand_inputs, [intervention]
    )
    np.testing.assert_allclose(out[0, 0], 0.0, atol=1e-12)
    np.testing.assert_allclose(out.sum(axis=1), [1.0], atol=1e-9)


def test_multiple_disqualifications_stack_deterministically() -> None:
    """Two disqualifications: both targets zero, mass = 1.0."""
    import numpy as np

    samples = _synth_samples([[0.30, 0.25, 0.10, 0.05]])
    cand_inputs = _candidate_inputs([10, 20, 30, 40])
    out = itv_mod.apply_interventions_to_samples(
        samples,
        cand_inputs,
        [
            _itv(intervention_id=1, target_id=20, kind="disqualified"),
            _itv(intervention_id=2, target_id=40, kind="withdrew"),
        ],
    )
    np.testing.assert_allclose(out[:, [1, 3]], 0.0, atol=1e-12)
    np.testing.assert_allclose(out.sum(axis=1), [1.0], atol=1e-9)


def test_unmatched_target_id_is_ignored() -> None:
    """A target_id that no candidate matches is a no-op (still renormalised)."""
    import numpy as np

    samples = _synth_samples([[0.4, 0.3, 0.3]])
    cand_inputs = _candidate_inputs([1, 2, 3])
    intervention = _itv(target_id=999, kind="disqualified")
    out = itv_mod.apply_interventions_to_samples(
        samples, cand_inputs, [intervention]
    )
    # Original sum was 1.0; after normalisation unchanged.
    np.testing.assert_allclose(out, samples, atol=1e-9)


def test_race_kind_target_is_a_noop_for_samples() -> None:
    """``target_kind='race'`` does not touch the per-candidate matrix."""
    import numpy as np

    samples = _synth_samples([[0.4, 0.3, 0.3]])
    cand_inputs = _candidate_inputs([1, 2, 3])
    intervention = _itv(
        target_kind="race", target_id=1, kind="disqualified"
    )
    out = itv_mod.apply_interventions_to_samples(
        samples, cand_inputs, [intervention]
    )
    np.testing.assert_allclose(out, samples, atol=1e-9)


def test_apply_to_samples_rejects_non_2d() -> None:
    import numpy as np

    samples = np.array([0.5, 0.5], dtype=float)
    cand_inputs = _candidate_inputs([1, 2])
    with pytest.raises(ValueError, match="2-D"):
        itv_mod.apply_interventions_to_samples(samples, cand_inputs, [])


def test_apply_to_samples_rejects_manual_without_override() -> None:
    samples = _synth_samples([[0.5, 0.5]])
    cand_inputs = _candidate_inputs([1, 2])
    bad = _itv(target_id=1, kind="manual_probability", override_probability=None)
    with pytest.raises(ValueError, match="override_probability"):
        itv_mod.apply_interventions_to_samples(samples, cand_inputs, [bad])


def test_apply_to_samples_rejects_unknown_kind() -> None:
    samples = _synth_samples([[0.5, 0.5]])
    cand_inputs = _candidate_inputs([1, 2])
    bad = _itv(target_id=1, kind="exploded")
    with pytest.raises(ValueError, match="unknown kind"):
        itv_mod.apply_interventions_to_samples(samples, cand_inputs, [bad])


# ---------------------------------------------------------------------------
# Posterior-level applier
# ---------------------------------------------------------------------------


def _synthetic_posterior(
    *,
    cand_ids: list[int] | None = None,
    party_ids: list[int | None] | None = None,
    n_mc: int = 100,
    seed: int = 17,
) -> pres.PresidentialPosterior:
    """Build a hand-rolled PresidentialPosterior for applier tests.

    Mirrors ``test_predict._synthetic_posterior`` but exposes party_id so the
    party-targeted intervention tests can find columns by party.
    """
    pytest.importorskip("numpy")
    import numpy as np

    if cand_ids is None:
        cand_ids = [10, 20, 30, 40]
    if party_ids is None:
        party_ids = [None] * len(cand_ids)

    rng = np.random.default_rng(seed)
    means = [0.32, 0.22, 0.15, 0.10][: len(cand_ids)]
    samples = np.zeros((n_mc, len(cand_ids)), dtype=float)
    for j, m in enumerate(means):
        samples[:, j] = np.clip(rng.normal(m, 0.04, n_mc), 0.01, 0.99)

    cand_inputs = _candidate_inputs(cand_ids, party_ids)

    order = np.argsort(samples, axis=1)
    top1_idx = order[:, -1]
    top2_idx = order[:, -2]
    win_a_prob = np.full(n_mc, 0.55, dtype=float)

    candidates = pres._per_candidate_summary(
        candidate_inputs=cand_inputs,
        first_round_samples=samples,
        top1_idx=top1_idx,
        top2_idx=top2_idx,
    )
    runoff_matrix = pres._build_runoff_matrix(
        candidate_inputs=cand_inputs,
        top1_idx=top1_idx,
        top2_idx=top2_idx,
        win_a_prob=win_a_prob,
    )
    return pres.PresidentialPosterior(
        candidates=candidates,
        runoff_matrix=runoff_matrix,
        first_round_samples=samples,
        n_monte_carlo=n_mc,
        max_r_hat=1.001,
        min_bulk_ess=900.0,
    )


def test_apply_interventions_no_active_passes_through() -> None:
    """Empty intervention list returns the original posterior object."""
    posterior = _synthetic_posterior()
    new_posterior, applied = itv_mod.apply_interventions(posterior, [])
    assert new_posterior is posterior
    assert applied == []


def test_apply_interventions_zeros_target_candidate_column() -> None:
    """Per acceptance: posterior column for disqualified target is zero."""
    import numpy as np

    posterior = _synthetic_posterior()
    intervention = _itv(target_id=20, kind="disqualified")
    new_posterior, applied = itv_mod.apply_interventions(
        posterior, [intervention]
    )
    # Column 1 = candidate_id 20.
    np.testing.assert_allclose(
        new_posterior.first_round_samples[:, 1], 0.0, atol=1e-12
    )
    # Rows still sum to 1.0.
    np.testing.assert_allclose(
        new_posterior.first_round_samples.sum(axis=1),
        np.ones(new_posterior.n_monte_carlo),
        atol=1e-9,
    )
    # Candidate 20's marginal collapsed: win prob = 0, qualifies = 0.
    cand_20 = next(c for c in new_posterior.candidates if c.candidate_id == 20)
    assert cand_20.win_probability_round1 == 0.0
    assert cand_20.qualifies_for_runoff_probability == 0.0
    # Runoff matrix must not surface the disqualified candidate as a finalist.
    for entry in new_posterior.runoff_matrix:
        assert entry.a_candidate_id != 20
        assert entry.b_candidate_id != 20
    # ADR-013 C5 invariant: pair probabilities sum to 1.0 ± 1e-6.
    pair_sum = sum(e.pair_probability for e in new_posterior.runoff_matrix)
    assert abs(pair_sum - 1.0) < 1e-6
    # Audit list carries the row in the documented payload shape.
    assert len(applied) == 1
    assert applied[0]["kind"] == "disqualified"
    assert applied[0]["target_kind"] == "candidate"
    assert applied[0]["target_id"] == 20


def test_apply_interventions_manual_probability_sets_marginal() -> None:
    """``manual_probability`` puts the target at exactly ``override_probability``."""
    import numpy as np

    posterior = _synthetic_posterior()
    intervention = _itv(
        target_id=30, kind="manual_probability", override_probability=0.4
    )
    new_posterior, _ = itv_mod.apply_interventions(posterior, [intervention])
    np.testing.assert_allclose(
        new_posterior.first_round_samples[:, 2], 0.4, atol=1e-9
    )
    np.testing.assert_allclose(
        new_posterior.first_round_samples.sum(axis=1),
        np.ones(new_posterior.n_monte_carlo),
        atol=1e-9,
    )


def test_apply_interventions_preserves_runoff_pair_probability_sum() -> None:
    """ADR-013 C5 holds after multiple interventions."""
    posterior = _synthetic_posterior()
    new_posterior, _ = itv_mod.apply_interventions(
        posterior,
        [
            _itv(intervention_id=1, target_id=10, kind="disqualified"),
            _itv(intervention_id=2, target_id=40, kind="withdrew"),
        ],
    )
    pair_sum = sum(e.pair_probability for e in new_posterior.runoff_matrix)
    assert abs(pair_sum - 1.0) < 1e-6


def test_apply_interventions_party_target_zeros_party_candidates() -> None:
    """Party-targeted disqualification zeros every party candidate column."""
    import numpy as np

    posterior = _synthetic_posterior(
        cand_ids=[10, 20, 30, 40], party_ids=[100, 100, 200, 200]
    )
    intervention = _itv(
        target_kind="party", target_id=100, kind="party_cancelled"
    )
    new_posterior, _ = itv_mod.apply_interventions(posterior, [intervention])
    np.testing.assert_allclose(
        new_posterior.first_round_samples[:, 0:2], 0.0, atol=1e-12
    )


# ---------------------------------------------------------------------------
# Payload-shaped metadata
# ---------------------------------------------------------------------------


def test_serialize_interventions_applied_matches_documented_keys() -> None:
    """Acceptance: payload's interventions_applied matches the active rows."""
    interventions = [
        _itv(
            intervention_id=1,
            target_kind="candidate",
            target_id=42,
            kind="disqualified",
            effective_at=datetime(2027, 4, 15, 12, 0, tzinfo=UTC),
            reason="TSE Acuerdo NNN",
            target_name="Bernardo Arévalo",
        ),
        _itv(
            intervention_id=2,
            target_kind="party",
            target_id=17,
            kind="party_cancelled",
            effective_at=datetime(2027, 5, 1, 18, 0, tzinfo=UTC),
            reason="Registro de Ciudadanos cancelled party",
            target_name="Movimiento Semilla",
        ),
    ]
    applied = itv_mod.serialize_interventions_applied(interventions)
    assert applied == [
        {
            "kind": "disqualified",
            "target_kind": "candidate",
            "target_id": 42,
            "target_name": "Bernardo Arévalo",
            "reason": "TSE Acuerdo NNN",
            "effective_at": "2027-04-15T12:00:00+00:00",
        },
        {
            "kind": "party_cancelled",
            "target_kind": "party",
            "target_id": 17,
            "target_name": "Movimiento Semilla",
            "reason": "Registro de Ciudadanos cancelled party",
            "effective_at": "2027-05-01T18:00:00+00:00",
        },
    ]


def test_serialize_interventions_applied_empty_list() -> None:
    assert itv_mod.serialize_interventions_applied([]) == []


def test_serialize_interventions_applied_normalises_to_utc() -> None:
    """Non-UTC effective_at values are normalised to UTC offset in the payload."""
    from datetime import timezone

    gt = timezone(timedelta(hours=-6))  # America/Guatemala (no DST)
    interventions = [
        _itv(
            intervention_id=1,
            effective_at=datetime(2027, 4, 15, 6, 0, tzinfo=gt),
        )
    ]
    applied = itv_mod.serialize_interventions_applied(interventions)
    # 06:00-06:00 = 12:00 UTC.
    assert applied[0]["effective_at"] == "2027-04-15T12:00:00+00:00"


# ---------------------------------------------------------------------------
# Fake-conn loader tests
# ---------------------------------------------------------------------------


class _FakeCursor:
    def __init__(self, rows: list[tuple[Any, ...]]) -> None:
        self.executed: list[tuple[str, tuple[Any, ...]]] = []
        self._rows = rows

    def execute(self, sql: str, params: tuple[Any, ...] = ()) -> None:
        self.executed.append((sql, params))

    def fetchall(self) -> list[tuple[Any, ...]]:
        return self._rows

    def __enter__(self) -> _FakeCursor:
        return self

    def __exit__(self, *args: object) -> None:
        return None


class _FakeConn:
    def __init__(self, rows: list[tuple[Any, ...]] | None = None) -> None:
        self.cur = _FakeCursor(rows or [])

    def cursor(self) -> _FakeCursor:
        return self.cur


def test_load_active_interventions_passes_at_to_both_predicates() -> None:
    """The ``at`` parameter is bound to both the effective and expires checks."""
    when = datetime(2027, 4, 15, 12, 0, tzinfo=UTC)
    conn = _FakeConn(rows=[])
    itv_mod.load_active_interventions(conn, at=when)
    assert len(conn.cur.executed) == 1
    sql, params = conn.cur.executed[0]
    assert "i.effective_at <= %s" in sql
    assert "i.expires_at IS NULL OR i.expires_at > %s" in sql
    assert params == (when, when)


def test_load_active_interventions_rejects_naive_at() -> None:
    conn = _FakeConn(rows=[])
    with pytest.raises(ValueError, match="timezone-aware"):
        itv_mod.load_active_interventions(conn, at=datetime(2027, 4, 15))


def test_load_active_interventions_maps_columns_to_dataclass() -> None:
    rows = [
        (
            42,
            "candidate",
            10,
            "disqualified",
            datetime(2027, 4, 15, tzinfo=UTC),
            None,
            None,
            "TSE Acuerdo",
            "ops",
            "Bernardo Arévalo",
        )
    ]
    conn = _FakeConn(rows=rows)
    out = itv_mod.load_active_interventions(
        conn, at=datetime(2027, 5, 1, tzinfo=UTC)
    )
    assert len(out) == 1
    only = out[0]
    assert only.intervention_id == 42
    assert only.target_kind == "candidate"
    assert only.target_id == 10
    assert only.kind == "disqualified"
    assert only.effective_at == datetime(2027, 4, 15, tzinfo=UTC)
    assert only.expires_at is None
    assert only.override_probability is None
    assert only.reason == "TSE Acuerdo"
    assert only.operator == "ops"
    assert only.target_name == "Bernardo Arévalo"


# ---------------------------------------------------------------------------
# End-to-end Postgres
# ---------------------------------------------------------------------------


_TEST_DSN = os.environ.get("POLITYK_TEST_DATABASE_URL")


def _truncate_intervention_world(conn: Any) -> None:
    """Wipe forecasts + posterior_archives + interventions + candidates.

    candidates are CASCADE-deleted from the catch-all truncate but stay in
    their own statement because they are not FK-referenced by forecasts."""
    with conn.cursor() as cur:
        cur.execute(
            "TRUNCATE TABLE posterior_archives, calibration_failures, "
            "calibration_overrides, forecasts CASCADE"
        )
        cur.execute("TRUNCATE TABLE interventions RESTART IDENTITY")
        cur.execute(
            "DELETE FROM candidate_aliases WHERE candidate_id IN ("
            "SELECT candidate_id FROM candidates WHERE full_name LIKE 'Test %')"
        )
        cur.execute("DELETE FROM candidates WHERE full_name LIKE 'Test %'")
    conn.commit()


@pytest.mark.skipif(_TEST_DSN is None, reason="POLITYK_TEST_DATABASE_URL not set")
def test_expired_interventions_are_skipped_by_loader() -> None:
    """Acceptance: expired interventions are ignored at load time."""
    import psycopg

    assert _TEST_DSN is not None
    now = datetime.now(UTC)
    active_eff = now - timedelta(hours=1)
    expired_eff = now - timedelta(days=10)
    expired_at = now - timedelta(hours=1)

    with psycopg.connect(_TEST_DSN) as conn:
        _truncate_intervention_world(conn)
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO interventions
                    (target_kind, target_id, kind, effective_at, expires_at,
                     reason, operator)
                VALUES
                    ('candidate', 1, 'disqualified', %s, NULL,
                     'active row', 'tester'),
                    ('candidate', 2, 'disqualified', %s, %s,
                     'expired row', 'tester')
                """,
                (active_eff, expired_eff, expired_at),
            )
            conn.commit()

        loaded = itv_mod.load_active_interventions(conn, at=now)

    target_ids = [i.target_id for i in loaded]
    assert 1 in target_ids
    assert 2 not in target_ids


@pytest.mark.skipif(_TEST_DSN is None, reason="POLITYK_TEST_DATABASE_URL not set")
def test_produce_forecast_applies_active_disqualification() -> None:
    """Acceptance: insert intervention, run #33, target column is zero in
    posterior_archives.sample_array."""
    import psycopg

    from pipeline.scripts import predict

    assert _TEST_DSN is not None
    rid = uuid.uuid4()

    with psycopg.connect(_TEST_DSN) as conn:
        _truncate_intervention_world(conn)
        # Insert a candidate row so the loader can resolve target_name.
        with conn.cursor() as cur:
            cur.execute(
                "INSERT INTO candidates (full_name) VALUES (%s) "
                "RETURNING candidate_id",
                ("Test DisqualifiedCand",),
            )
            row = cur.fetchone()
            assert row is not None
            target_cand_id = int(row[0])
            cur.execute(
                "INSERT INTO candidates (full_name) VALUES (%s) "
                "RETURNING candidate_id",
                ("Test SurvivorCand",),
            )
            row = cur.fetchone()
            assert row is not None
            survivor_cand_id = int(row[0])
            cur.execute(
                "INSERT INTO candidates (full_name) VALUES (%s) "
                "RETURNING candidate_id",
                ("Test SurvivorCand2",),
            )
            row = cur.fetchone()
            assert row is not None
            other_cand_id = int(row[0])

            cur.execute(
                """
                INSERT INTO interventions
                    (target_kind, target_id, kind, effective_at,
                     reason, operator)
                VALUES (%s, %s, %s, %s, %s, %s)
                """,
                (
                    "candidate",
                    target_cand_id,
                    "disqualified",
                    datetime(2027, 4, 15, tzinfo=UTC),
                    "TSE disqualified",
                    "afk-test",
                ),
            )
            conn.commit()

        posterior = _synthetic_posterior(
            cand_ids=[target_cand_id, survivor_cand_id, other_cand_id],
            n_mc=50,
            seed=11,
        )

        predict.produce_forecast(
            conn,
            posterior=posterior,
            run_id=rid,
            generated_at=datetime(2027, 6, 1, tzinfo=UTC),
            interventions=None,  # load from DB
        )
        conn.commit()

        with conn.cursor() as cur:
            cur.execute(
                "SELECT sample_array FROM posterior_archives "
                "WHERE run_id = %s",
                (str(rid),),
            )
            row = cur.fetchone()
        assert row is not None
        sample_array = row[0]
        # Target candidate is at column 0 (first in cand_ids); every row's
        # target-column value must be zero after the applier ran.
        target_col = [float(r[0]) for r in sample_array]
        assert all(v == 0.0 for v in target_col), (
            f"non-zero target column entries: {[v for v in target_col if v != 0.0]}"
        )

        # And the payload's interventions_applied carries the audit row.
        with conn.cursor() as cur:
            cur.execute(
                "SELECT payload FROM forecasts WHERE run_id = %s",
                (str(rid),),
            )
            row = cur.fetchone()
        assert row is not None
        payload = row[0]
        applied = payload["interventions_applied"]
        assert len(applied) == 1
        assert applied[0]["kind"] == "disqualified"
        assert applied[0]["target_kind"] == "candidate"
        assert applied[0]["target_id"] == target_cand_id
        assert applied[0]["target_name"] == "Test DisqualifiedCand"
        assert applied[0]["reason"] == "TSE disqualified"
