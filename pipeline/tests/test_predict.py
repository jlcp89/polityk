"""Tests for ``pipeline.scripts.predict`` (issue #33, ADR-006, ADR-014).

Three tiers, matching the rest of the suite:

1. Pure-logic tests (always run) — payload schema conformance against the
   ADR-014 contract, idempotence on a fixed-seed synthetic posterior,
   ``posterior_sample_array`` shape and dtype, ``run_kind`` validation.
2. Fake-conn DB writer tests — assert the two INSERT statements + the
   ``pg_notify`` call fire with the right parameters and the right
   ordering.
3. End-to-end Postgres test gated by ``POLITYK_TEST_DATABASE_URL`` —
   inserts via the production code path against a real DB, asserts the
   ``forecasts`` and ``posterior_archives`` rows materialize, the NOTIFY
   round-trips on a listening session, and a re-run with the same
   posterior produces a byte-identical payload (modulo ``run_id`` +
   ``generated_at``).
"""

from __future__ import annotations

import json
import os
import uuid
from datetime import UTC, datetime
from typing import Any

import pytest

from pipeline.models import presidential as pres
from pipeline.scripts import predict

# ---------------------------------------------------------------------------
# Hand-built synthetic PresidentialPosterior
# ---------------------------------------------------------------------------


def _synthetic_posterior(
    *,
    n_mc: int = 200,
    seed: int = 17,
) -> pres.PresidentialPosterior:
    """Build a deterministic PresidentialPosterior for payload tests.

    No PyMC required — we synthesise the share matrix directly with
    numpy's seeded generator and run the same top-two summary the combiner
    would. That keeps the tests fast and independent of the runoff fit.
    """
    pytest.importorskip("numpy")
    import numpy as np

    rng = np.random.default_rng(seed)
    cand_ids = [10, 20, 30, 40]
    means = [0.32, 0.22, 0.15, 0.10]
    samples = np.zeros((n_mc, len(cand_ids)), dtype=float)
    for j, m in enumerate(means):
        samples[:, j] = np.clip(rng.normal(m, 0.04, n_mc), 0.01, 0.99)

    candidate_inputs = [
        pres.CandidateInput(
            candidate_id=cid,
            name=f"Cand {cid}",
            party_id=cid + 1000,
            party_name=f"Party {cid}",
            wikidata_qid=f"Q{cid}",
            feature_vector=None,
        )
        for cid in cand_ids
    ]

    # Top-two indices.
    order = np.argsort(samples, axis=1)
    top1_idx = order[:, -1]
    top2_idx = order[:, -2]
    # Synthetic per-MC P(a wins runoff): deterministic 0.55.
    win_a_prob = np.full(n_mc, 0.55, dtype=float)

    candidates = pres._per_candidate_summary(
        candidate_inputs=candidate_inputs,
        first_round_samples=samples,
        top1_idx=top1_idx,
        top2_idx=top2_idx,
    )
    runoff_matrix = pres._build_runoff_matrix(
        candidate_inputs=candidate_inputs,
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


# ---------------------------------------------------------------------------
# ADR-014 payload schema validator (no jsonschema dep)
# ---------------------------------------------------------------------------


_EXPECTED_QUANTILE_KEYS = ("p05", "p10", "p25", "p50", "p75", "p90", "p95")


def _assert_adr014_presidential_payload(payload: dict[str, Any]) -> None:
    """Structural validator for the ADR-014 presidential payload contract."""
    required = {
        "run_id",
        "model_version",
        "generated_at",
        "race",
        "candidates",
        "runoff_matrix",
        "interventions_applied",
        "methodology_url",
    }
    missing = required - set(payload)
    assert not missing, f"missing top-level keys: {missing}"

    # run_id parses as UUID
    uuid.UUID(payload["run_id"])
    assert isinstance(payload["model_version"], str) and payload["model_version"]

    # generated_at parses as ISO-8601 with offset
    gen = datetime.fromisoformat(payload["generated_at"])
    assert gen.tzinfo is not None, "generated_at must carry a timezone offset"

    race = payload["race"]
    assert race["type"] == "presidential"
    assert isinstance(race["cycle"], int)
    assert race["round"] in (1, 2)

    cands = payload["candidates"]
    assert isinstance(cands, list) and len(cands) >= 1
    for c in cands:
        assert isinstance(c["candidate_id"], int)
        assert isinstance(c["name"], str)
        # party_id / party_name / wikidata_qid may be None.
        for opt_key in ("party_id", "party_name", "wikidata_qid"):
            assert opt_key in c
        vs = c["vote_share"]
        assert set(vs.keys()) == set(_EXPECTED_QUANTILE_KEYS), (
            f"vote_share keys mismatch: {set(vs.keys())}"
        )
        # Quantiles monotone non-decreasing.
        for prev_k, next_k in zip(
            _EXPECTED_QUANTILE_KEYS, _EXPECTED_QUANTILE_KEYS[1:], strict=False
        ):
            assert vs[prev_k] <= vs[next_k], (
                f"non-monotonic quantiles on {c['candidate_id']}: {vs}"
            )
        # Probabilities in [0, 1].
        assert 0.0 <= c["win_probability_round1"] <= 1.0
        assert 0.0 <= c["qualifies_for_runoff_probability"] <= 1.0

    rm = payload["runoff_matrix"]
    assert isinstance(rm, list)
    pair_sum = 0.0
    for e in rm:
        assert isinstance(e["candidate_a_id"], int)
        assert isinstance(e["candidate_b_id"], int)
        assert 0.0 <= e["pair_probability"] <= 1.0
        assert 0.0 <= e["winner_a_probability"] <= 1.0
        pair_sum += float(e["pair_probability"])
    # ADR-013 C5: pair probabilities sum to 1.0 ± 1e-6.
    assert abs(pair_sum - 1.0) < 1e-6, f"pair_probability sum = {pair_sum}"

    assert payload["interventions_applied"] == []
    assert isinstance(payload["methodology_url"], str)
    assert payload["methodology_url"].startswith("http")


# ---------------------------------------------------------------------------
# Pure-logic: payload construction
# ---------------------------------------------------------------------------


def test_quantile_keys_match_adr014() -> None:
    """ADR-014 example uses p05/p10/p25/p50/p75/p90/p95 in that order."""
    assert predict.QUANTILE_KEYS == _EXPECTED_QUANTILE_KEYS


def test_build_payload_conforms_to_adr014_contract() -> None:
    posterior = _synthetic_posterior()
    rid = uuid.UUID("12345678-1234-5678-1234-567812345678")
    gen_at = datetime(2027, 6, 1, 18, 0, tzinfo=UTC)
    payload = predict.build_presidential_payload(
        posterior, run_id=rid, generated_at=gen_at
    )
    _assert_adr014_presidential_payload(payload)
    # Specific identity assertions.
    assert payload["run_id"] == str(rid)
    assert payload["generated_at"] == "2027-06-01T18:00:00+00:00"
    assert payload["model_version"] == predict.MODEL_VERSION
    assert payload["methodology_url"] == predict.METHODOLOGY_URL


def test_build_payload_is_idempotent_on_fixed_seed() -> None:
    """Same posterior → byte-identical payload after factoring out run_id + generated_at.

    The issue-#33 acceptance criterion: "Idempotent on fixed seed: same
    input → same payload (excluding run_id and generated_at)".
    """
    posterior = _synthetic_posterior(seed=17)
    rid = uuid.UUID("00000000-0000-0000-0000-000000000001")
    gen_at = datetime(2027, 6, 1, tzinfo=UTC)

    p1 = predict.build_presidential_payload(
        posterior, run_id=rid, generated_at=gen_at
    )
    # Re-build twice; the two payloads must be equal.
    p2 = predict.build_presidential_payload(
        posterior, run_id=rid, generated_at=gen_at
    )
    assert json.dumps(p1, sort_keys=True) == json.dumps(p2, sort_keys=True)

    # Now re-synthesise the posterior under the same seed; the same
    # candidates section must still match (run_id + generated_at swapped
    # out so we can compare around them).
    posterior2 = _synthetic_posterior(seed=17)
    p3 = predict.build_presidential_payload(
        posterior2,
        run_id=uuid.UUID("00000000-0000-0000-0000-000000000002"),
        generated_at=datetime(2030, 1, 1, tzinfo=UTC),
    )
    # Strip run_id / generated_at; everything else must be byte-identical.
    for k in ("run_id", "generated_at"):
        p1.pop(k)
        p3.pop(k)
    assert json.dumps(p1, sort_keys=True) == json.dumps(p3, sort_keys=True)


def test_build_payload_rejects_invalid_round() -> None:
    posterior = _synthetic_posterior()
    with pytest.raises(ValueError, match="round_"):
        predict.build_presidential_payload(
            posterior,
            run_id=uuid.uuid4(),
            generated_at=datetime.now(UTC),
            round_=3,
        )


def test_build_payload_rejects_naive_generated_at() -> None:
    posterior = _synthetic_posterior()
    with pytest.raises(ValueError, match="timezone-aware"):
        predict.build_presidential_payload(
            posterior,
            run_id=uuid.uuid4(),
            generated_at=datetime(2027, 1, 1),  # naive
        )


def test_build_payload_honours_cycle_and_round_kwargs() -> None:
    posterior = _synthetic_posterior()
    payload = predict.build_presidential_payload(
        posterior,
        run_id=uuid.uuid4(),
        generated_at=datetime.now(UTC),
        cycle=2031,
        round_=2,
    )
    assert payload["race"] == {"type": "presidential", "cycle": 2031, "round": 2}


# ---------------------------------------------------------------------------
# Pure-logic: posterior_sample_array
# ---------------------------------------------------------------------------


def test_posterior_sample_array_round_trips_shape() -> None:
    posterior = _synthetic_posterior(n_mc=50)
    arr = predict.posterior_sample_array(posterior)
    assert len(arr) == 50
    assert all(len(row) == 4 for row in arr)
    assert all(isinstance(x, float) for row in arr for x in row)


def test_posterior_sample_array_rejects_non_2d() -> None:
    import numpy as np

    posterior = pres.PresidentialPosterior(
        candidates=(),
        runoff_matrix=(),
        first_round_samples=np.zeros((5,), dtype=float),  # 1-D
        n_monte_carlo=5,
        max_r_hat=1.0,
        min_bulk_ess=900.0,
    )
    with pytest.raises(ValueError, match="2-D"):
        predict.posterior_sample_array(posterior)


# ---------------------------------------------------------------------------
# Fake-conn DB writer tests
# ---------------------------------------------------------------------------


class _FakeCursor:
    def __init__(self) -> None:
        self.executed: list[tuple[str, tuple[Any, ...]]] = []

    def execute(self, sql: str, params: tuple[Any, ...] = ()) -> None:
        self.executed.append((sql, params))

    def __enter__(self) -> _FakeCursor:
        return self

    def __exit__(self, *args: object) -> None:
        return None


class _FakeConn:
    def __init__(self) -> None:
        self.cur = _FakeCursor()

    def cursor(self) -> _FakeCursor:
        return self.cur


def test_write_forecast_emits_two_inserts_and_pg_notify() -> None:
    conn = _FakeConn()
    rid = uuid.UUID("11111111-1111-1111-1111-111111111111")
    gen_at = datetime(2027, 6, 1, 18, 0, tzinfo=UTC)
    posterior = _synthetic_posterior(n_mc=20)
    payload = predict.build_presidential_payload(
        posterior, run_id=rid, generated_at=gen_at
    )
    sample_array = predict.posterior_sample_array(posterior)

    predict.write_forecast(
        conn,
        run_id=rid,
        model_version="0.1.0",
        generated_at=gen_at,
        payload=payload,
        sample_array=sample_array,
    )

    statements = [sql for sql, _ in conn.cur.executed]
    assert len(statements) == 3, statements

    # Statement 1 = forecasts INSERT.
    sql_f, params_f = conn.cur.executed[0]
    assert "INSERT INTO forecasts" in sql_f
    assert params_f[0] == str(rid)
    assert params_f[1] == "0.1.0"
    assert params_f[2] == gen_at
    assert params_f[3] == "presidential"
    assert params_f[4] == "scheduled"
    # payload comes in as a JSON string + ::jsonb cast.
    assert isinstance(params_f[5], str)
    json.loads(params_f[5])  # parses

    # Statement 2 = posterior_archives INSERT.
    sql_p, params_p = conn.cur.executed[1]
    assert "INSERT INTO posterior_archives" in sql_p
    assert params_p == (str(rid), "presidential", sample_array)

    # Statement 3 = pg_notify on the documented channel.
    sql_n, params_n = conn.cur.executed[2]
    assert "pg_notify" in sql_n
    assert params_n == (predict.NOTIFY_CHANNEL, str(rid))


def test_write_forecast_rejects_unknown_run_kind() -> None:
    conn = _FakeConn()
    posterior = _synthetic_posterior(n_mc=5)
    rid = uuid.uuid4()
    gen_at = datetime.now(UTC)
    with pytest.raises(ValueError, match="run_kind"):
        predict.write_forecast(
            conn,
            run_id=rid,
            model_version="0.1.0",
            generated_at=gen_at,
            payload=predict.build_presidential_payload(
                posterior, run_id=rid, generated_at=gen_at
            ),
            sample_array=predict.posterior_sample_array(posterior),
            run_kind="bogus",
        )


def test_produce_forecast_returns_run_id_and_payload() -> None:
    conn = _FakeConn()
    posterior = _synthetic_posterior(n_mc=10)
    result = predict.produce_forecast(
        conn,
        posterior=posterior,
        run_id=uuid.UUID("22222222-2222-2222-2222-222222222222"),
        generated_at=datetime(2027, 7, 1, tzinfo=UTC),
    )
    assert result.run_id == uuid.UUID("22222222-2222-2222-2222-222222222222")
    assert result.payload["run_id"] == "22222222-2222-2222-2222-222222222222"
    _assert_adr014_presidential_payload(result.payload)


def test_produce_forecast_generates_uuid_v4_when_unset() -> None:
    conn = _FakeConn()
    posterior = _synthetic_posterior(n_mc=10)
    result = predict.produce_forecast(conn, posterior=posterior)
    # UUIDv4 → version field is 4.
    assert result.run_id.version == 4


def test_produce_forecast_writes_whatif_kind() -> None:
    """run_kind='whatif' lands on the INSERT; the row is excluded from
    is_published per ADR-006 + the partial index in migration 0006."""
    conn = _FakeConn()
    posterior = _synthetic_posterior(n_mc=10)
    predict.produce_forecast(conn, posterior=posterior, run_kind="whatif")
    sql_f, params_f = conn.cur.executed[0]
    assert "INSERT INTO forecasts" in sql_f
    assert params_f[4] == "whatif"


def test_main_returns_two_when_database_url_missing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """CLI exits 2 when DATABASE_URL isn't set — before any DB / fit work."""
    monkeypatch.delenv("DATABASE_URL", raising=False)
    rc = predict.main([])
    assert rc == 2


# ---------------------------------------------------------------------------
# End-to-end Postgres
# ---------------------------------------------------------------------------


_TEST_DSN = os.environ.get("POLITYK_TEST_DATABASE_URL")


def _truncate_forecasts(conn: Any) -> None:
    """Wipe forecasts + posterior_archives between tests. CASCADE handles
    the FK from posterior_archives.run_id."""
    with conn.cursor() as cur:
        cur.execute(
            "TRUNCATE TABLE posterior_archives, "
            "calibration_failures, calibration_overrides, "
            "forecasts CASCADE"
        )
    conn.commit()


@pytest.mark.skipif(_TEST_DSN is None, reason="POLITYK_TEST_DATABASE_URL not set")
def test_produce_forecast_writes_exactly_one_row_per_table() -> None:
    """Acceptance: running produce_forecast writes exactly one row to
    forecasts and one to posterior_archives."""
    import psycopg

    assert _TEST_DSN is not None
    posterior = _synthetic_posterior(n_mc=30, seed=17)
    rid = uuid.uuid4()

    with psycopg.connect(_TEST_DSN) as conn:
        _truncate_forecasts(conn)
        result = predict.produce_forecast(
            conn,
            posterior=posterior,
            run_id=rid,
            generated_at=datetime(2027, 6, 1, 18, 0, tzinfo=UTC),
        )
        conn.commit()
        assert result.run_id == rid

        with conn.cursor() as cur:
            cur.execute("SELECT COUNT(*) FROM forecasts WHERE run_id = %s", (str(rid),))
            row = cur.fetchone()
            assert row is not None
            assert row[0] == 1
            cur.execute(
                "SELECT COUNT(*) FROM posterior_archives WHERE run_id = %s",
                (str(rid),),
            )
            row = cur.fetchone()
            assert row is not None
            assert row[0] == 1


@pytest.mark.skipif(_TEST_DSN is None, reason="POLITYK_TEST_DATABASE_URL not set")
def test_produce_forecast_is_published_defaults_false() -> None:
    """ADR-006: is_published defaults to FALSE until #36 flips it."""
    import psycopg

    assert _TEST_DSN is not None
    posterior = _synthetic_posterior(n_mc=20)
    rid = uuid.uuid4()

    with psycopg.connect(_TEST_DSN) as conn:
        _truncate_forecasts(conn)
        predict.produce_forecast(
            conn,
            posterior=posterior,
            run_id=rid,
            generated_at=datetime.now(UTC),
        )
        conn.commit()

        with conn.cursor() as cur:
            cur.execute(
                "SELECT is_published, run_kind, race_type, model_version "
                "FROM forecasts WHERE run_id = %s",
                (str(rid),),
            )
            row = cur.fetchone()
        assert row is not None
        assert row[0] is False
        assert row[1] == "scheduled"
        assert row[2] == "presidential"
        assert row[3] == predict.MODEL_VERSION


@pytest.mark.skipif(_TEST_DSN is None, reason="POLITYK_TEST_DATABASE_URL not set")
def test_produce_forecast_payload_round_trips_through_jsonb() -> None:
    """The payload stored in JSONB matches the ADR-014 contract on read-back."""
    import psycopg

    assert _TEST_DSN is not None
    posterior = _synthetic_posterior(n_mc=40)
    rid = uuid.uuid4()

    with psycopg.connect(_TEST_DSN) as conn:
        _truncate_forecasts(conn)
        predict.produce_forecast(
            conn,
            posterior=posterior,
            run_id=rid,
            generated_at=datetime(2027, 6, 1, tzinfo=UTC),
        )
        conn.commit()

        with conn.cursor() as cur:
            cur.execute(
                "SELECT payload FROM forecasts WHERE run_id = %s",
                (str(rid),),
            )
            row = cur.fetchone()
        assert row is not None
        payload = row[0]
    _assert_adr014_presidential_payload(payload)


@pytest.mark.skipif(_TEST_DSN is None, reason="POLITYK_TEST_DATABASE_URL not set")
def test_produce_forecast_writes_sample_array_two_dimensional() -> None:
    """posterior_archives.sample_array stores the full (n_mc, n_cand) matrix."""
    import psycopg

    assert _TEST_DSN is not None
    posterior = _synthetic_posterior(n_mc=25)
    rid = uuid.uuid4()

    with psycopg.connect(_TEST_DSN) as conn:
        _truncate_forecasts(conn)
        predict.produce_forecast(
            conn,
            posterior=posterior,
            run_id=rid,
            generated_at=datetime.now(UTC),
        )
        conn.commit()

        with conn.cursor() as cur:
            cur.execute(
                "SELECT array_length(sample_array, 1), array_length(sample_array, 2) "
                "FROM posterior_archives WHERE run_id = %s",
                (str(rid),),
            )
            row = cur.fetchone()
        assert row is not None
        assert row[0] == 25
        assert row[1] == 4


@pytest.mark.skipif(_TEST_DSN is None, reason="POLITYK_TEST_DATABASE_URL not set")
def test_notify_forecast_ready_fires_with_run_id() -> None:
    """The Go listener (#10) reads pg_notify on `forecast_ready` carrying
    `<run_id>` as the payload. Open a LISTEN session on a separate
    connection, run produce_forecast, assert the notification arrives."""
    import psycopg

    assert _TEST_DSN is not None
    posterior = _synthetic_posterior(n_mc=15)
    rid = uuid.uuid4()

    # Listener session: must be autocommit so LISTEN takes effect immediately.
    with psycopg.connect(_TEST_DSN, autocommit=True) as listener_conn:
        with listener_conn.cursor() as cur:
            cur.execute(f"LISTEN {predict.NOTIFY_CHANNEL}")

        # Writer session: produce_forecast + commit fires the queued NOTIFY.
        with psycopg.connect(_TEST_DSN) as writer_conn:
            _truncate_forecasts(writer_conn)
            predict.produce_forecast(
                writer_conn,
                posterior=posterior,
                run_id=rid,
                generated_at=datetime.now(UTC),
            )
            writer_conn.commit()

        # Drain notifications with a short timeout. psycopg's
        # `notifies()` returns a generator that keeps a long-lived hold
        # on the connection's socket-reader state; if we don't close it
        # before the connection's __exit__, the close blocks waiting
        # for the generator to be GC'd. ``stop_after`` ends the
        # iteration when we get one notification, and ``gen.close()``
        # releases the socket lock so the outer ``with`` can return.
        gen = listener_conn.notifies(timeout=3.0, stop_after=1)
        seen: list[tuple[str, str]] = []
        try:
            for notify in gen:
                seen.append((notify.channel, notify.payload))
                if notify.payload == str(rid):
                    break
        finally:
            gen.close()

    payloads = [p for _, p in seen]
    channels = {c for c, _ in seen}
    assert str(rid) in payloads, f"run_id {rid} not in {payloads}"
    assert predict.NOTIFY_CHANNEL in channels


@pytest.mark.skipif(_TEST_DSN is None, reason="POLITYK_TEST_DATABASE_URL not set")
def test_produce_forecast_idempotent_payload_across_runs() -> None:
    """Same synthetic posterior → identical payload bytes across runs,
    ignoring run_id + generated_at."""
    import psycopg

    assert _TEST_DSN is not None
    rid_a = uuid.uuid4()
    rid_b = uuid.uuid4()

    with psycopg.connect(_TEST_DSN) as conn:
        _truncate_forecasts(conn)

        posterior_a = _synthetic_posterior(n_mc=30, seed=17)
        predict.produce_forecast(
            conn,
            posterior=posterior_a,
            run_id=rid_a,
            generated_at=datetime(2027, 6, 1, tzinfo=UTC),
        )

        posterior_b = _synthetic_posterior(n_mc=30, seed=17)
        predict.produce_forecast(
            conn,
            posterior=posterior_b,
            run_id=rid_b,
            generated_at=datetime(2030, 6, 1, tzinfo=UTC),
        )
        conn.commit()

        with conn.cursor() as cur:
            cur.execute(
                "SELECT run_id::text, payload FROM forecasts "
                "WHERE run_id IN (%s, %s) ORDER BY generated_at",
                (str(rid_a), str(rid_b)),
            )
            rows = cur.fetchall()
    assert len(rows) == 2
    pa = rows[0][1]
    pb = rows[1][1]
    for k in ("run_id", "generated_at"):
        pa.pop(k)
        pb.pop(k)
    assert json.dumps(pa, sort_keys=True) == json.dumps(pb, sort_keys=True)
