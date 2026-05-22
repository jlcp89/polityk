"""Tests for `pipeline.scripts.intervene` (issue #34, ADR-019).

The pure-logic tests run unconditionally and cover the CLI's argument
validation contract:

* missing `--reason` is rejected
* empty `--reason` is rejected
* missing `--operator` AND empty `$USER` is rejected
* `--override-probability` outside [0, 1] is rejected with a clean
  message before any DB round-trip
* `--whatif` causes the CLI to print ``run_kind=whatif``

The end-to-end Postgres tests run only when
``POLITYK_TEST_DATABASE_URL`` is set (mirroring
``test_load_2019_excel.py``). They wrap each insert in a transaction
and ROLLBACK so the test leaves no state behind, as required by the
acceptance criterion "Integration test inserts a row, asserts fields,
then rolls back".
"""

from __future__ import annotations

import os
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest

from pipeline.scripts import intervene

# ---- Pure-logic: argument validation --------------------------------------


def test_rejects_missing_reason(capsys: pytest.CaptureFixture[str]) -> None:
    with pytest.raises(SystemExit) as exc:
        intervene.main(
            [
                "--target-kind",
                "candidate",
                "--target-id",
                "1",
                "--kind",
                "disqualified",
                "--effective-at",
                "2027-04-15T12:00:00-06:00",
                # no --reason
            ]
        )
    # argparse exits with code 2 on missing required argument.
    assert exc.value.code == 2
    err = capsys.readouterr().err
    assert "--reason" in err


def test_rejects_empty_reason(capsys: pytest.CaptureFixture[str]) -> None:
    with pytest.raises(SystemExit) as exc:
        intervene.main(
            [
                "--target-kind",
                "candidate",
                "--target-id",
                "1",
                "--kind",
                "disqualified",
                "--effective-at",
                "2027-04-15T12:00:00-06:00",
                "--reason",
                "",
            ]
        )
    assert exc.value.code == 2
    assert "must be non-empty" in capsys.readouterr().err


def test_rejects_whitespace_only_reason(
    capsys: pytest.CaptureFixture[str],
) -> None:
    with pytest.raises(SystemExit) as exc:
        intervene.main(
            [
                "--target-kind",
                "candidate",
                "--target-id",
                "1",
                "--kind",
                "disqualified",
                "--effective-at",
                "2027-04-15T12:00:00-06:00",
                "--reason",
                "   ",
            ]
        )
    assert exc.value.code == 2
    assert "must be non-empty" in capsys.readouterr().err


def test_rejects_missing_operator_when_user_empty(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """`--operator` defaults to $USER; if both are empty the CLI errors."""
    monkeypatch.delenv("USER", raising=False)
    # DATABASE_URL set so we don't bail at the DSN check first.
    monkeypatch.setenv("DATABASE_URL", "postgres://fake/fake")
    with pytest.raises(SystemExit) as exc:
        intervene.main(
            [
                "--target-kind",
                "candidate",
                "--target-id",
                "1",
                "--kind",
                "disqualified",
                "--effective-at",
                "2027-04-15T12:00:00-06:00",
                "--reason",
                "TSE disqualified",
            ]
        )
    msg = exc.value.code if isinstance(exc.value.code, int) else str(exc.value)
    # SystemExit raised via `raise SystemExit("intervene: --operator ...")`
    # carries the message as `code` (per CPython semantics).
    assert "operator" in str(msg).lower()


def test_rejects_explicit_empty_operator(
    capsys: pytest.CaptureFixture[str],
) -> None:
    with pytest.raises(SystemExit) as exc:
        intervene.main(
            [
                "--target-kind",
                "candidate",
                "--target-id",
                "1",
                "--kind",
                "disqualified",
                "--effective-at",
                "2027-04-15T12:00:00-06:00",
                "--reason",
                "TSE disqualified",
                "--operator",
                "",
            ]
        )
    assert exc.value.code == 2
    assert "must be non-empty" in capsys.readouterr().err


def test_rejects_override_probability_above_one(
    capsys: pytest.CaptureFixture[str],
) -> None:
    with pytest.raises(SystemExit) as exc:
        intervene.main(
            [
                "--target-kind",
                "candidate",
                "--target-id",
                "1",
                "--kind",
                "manual_probability",
                "--effective-at",
                "2027-04-15T12:00:00-06:00",
                "--reason",
                "manual override",
                "--override-probability",
                "1.5",
            ]
        )
    assert exc.value.code == 2
    err = capsys.readouterr().err
    assert "must be in [0, 1]" in err


def test_rejects_override_probability_negative(
    capsys: pytest.CaptureFixture[str],
) -> None:
    with pytest.raises(SystemExit) as exc:
        intervene.main(
            [
                "--target-kind",
                "candidate",
                "--target-id",
                "1",
                "--kind",
                "manual_probability",
                "--effective-at",
                "2027-04-15T12:00:00-06:00",
                "--reason",
                "manual override",
                "--override-probability",
                "-0.01",
            ]
        )
    assert exc.value.code == 2
    err = capsys.readouterr().err
    assert "must be in [0, 1]" in err


def test_rejects_unknown_target_kind(
    capsys: pytest.CaptureFixture[str],
) -> None:
    """argparse choices rejects values outside the DB enum."""
    with pytest.raises(SystemExit) as exc:
        intervene.main(
            [
                "--target-kind",
                "ufo",  # not in TARGET_KINDS
                "--target-id",
                "1",
                "--kind",
                "disqualified",
                "--effective-at",
                "2027-04-15T12:00:00-06:00",
                "--reason",
                "noop",
            ]
        )
    assert exc.value.code == 2
    err = capsys.readouterr().err
    assert "ufo" in err or "invalid choice" in err


def test_rejects_unknown_intervention_kind(
    capsys: pytest.CaptureFixture[str],
) -> None:
    with pytest.raises(SystemExit) as exc:
        intervene.main(
            [
                "--target-kind",
                "candidate",
                "--target-id",
                "1",
                "--kind",
                "exploded",  # not in INTERVENTION_KINDS
                "--effective-at",
                "2027-04-15T12:00:00-06:00",
                "--reason",
                "noop",
            ]
        )
    assert exc.value.code == 2
    err = capsys.readouterr().err
    assert "exploded" in err or "invalid choice" in err


def test_rejects_invalid_effective_at(
    capsys: pytest.CaptureFixture[str],
) -> None:
    with pytest.raises(SystemExit) as exc:
        intervene.main(
            [
                "--target-kind",
                "candidate",
                "--target-id",
                "1",
                "--kind",
                "disqualified",
                "--effective-at",
                "not-a-timestamp",
                "--reason",
                "noop",
            ]
        )
    assert exc.value.code == 2
    err = capsys.readouterr().err
    assert "ISO-8601" in err


def test_rejects_missing_database_url(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """If DATABASE_URL is unset the CLI exits 2 before any DB work."""
    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.setenv("USER", "tester")
    rc = intervene.main(
        [
            "--target-kind",
            "candidate",
            "--target-id",
            "1",
            "--kind",
            "disqualified",
            "--effective-at",
            "2027-04-15T12:00:00-06:00",
            "--reason",
            "TSE disqualified",
        ]
    )
    assert rc == 2


def test_constants_match_db_enums() -> None:
    """Pin the CLI's choice lists to the DB enums in migration 0006."""
    assert intervene.TARGET_KINDS == ("candidate", "party", "race")
    assert intervene.INTERVENTION_KINDS == (
        "disqualified",
        "withdrew",
        "party_cancelled",
        "manual_probability",
    )


def test_resolve_operator_prefers_cli_arg(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("USER", "shell-user")
    assert intervene._resolve_operator("cli-user") == "cli-user"


def test_resolve_operator_falls_back_to_user(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("USER", "shell-user")
    assert intervene._resolve_operator(None) == "shell-user"


def test_resolve_operator_rejects_empty_user(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("USER", "")
    with pytest.raises(SystemExit):
        intervene._resolve_operator(None)


# ---- Pure-logic: insert_intervention via fake conn -------------------------


class _FakeCursor:
    def __init__(self, returning_id: int) -> None:
        self.executed: list[tuple[str, tuple[Any, ...]]] = []
        self._returning_id = returning_id

    def execute(self, sql: str, params: tuple[Any, ...] = ()) -> None:
        self.executed.append((sql, params))

    def fetchone(self) -> tuple[int]:
        return (self._returning_id,)

    def __enter__(self) -> _FakeCursor:
        return self

    def __exit__(self, *args: object) -> None:
        return None


class _FakeConn:
    def __init__(self, returning_id: int = 99) -> None:
        self.cur = _FakeCursor(returning_id)
        self.committed = False

    def cursor(self) -> _FakeCursor:
        return self.cur

    def commit(self) -> None:
        self.committed = True


def test_insert_intervention_binds_all_columns() -> None:
    conn = _FakeConn(returning_id=42)
    intervention_id = intervene.insert_intervention(
        conn,
        target_kind="candidate",
        target_id=7,
        kind="manual_probability",
        effective_at=datetime(2027, 4, 15, 12, 0, tzinfo=UTC),
        expires_at=datetime(2027, 5, 1, 12, 0, tzinfo=UTC),
        override_probability=0.25,
        reason="manual override for testing",
        operator="tester",
    )
    assert intervention_id == 42
    assert len(conn.cur.executed) == 1
    sql, params = conn.cur.executed[0]
    assert "INSERT INTO interventions" in sql
    assert "RETURNING intervention_id" in sql
    assert params == (
        "candidate",
        7,
        "manual_probability",
        datetime(2027, 4, 15, 12, 0, tzinfo=UTC),
        datetime(2027, 5, 1, 12, 0, tzinfo=UTC),
        0.25,
        "manual override for testing",
        "tester",
    )


def test_insert_intervention_does_not_commit() -> None:
    """The library function leaves commit to the caller."""
    conn = _FakeConn()
    intervene.insert_intervention(
        conn,
        target_kind="candidate",
        target_id=1,
        kind="disqualified",
        effective_at=datetime(2027, 4, 15, tzinfo=UTC),
        reason="TSE disqualified",
        operator="op",
    )
    assert conn.committed is False


# ---- End-to-end Postgres ---------------------------------------------------

_TEST_DSN = os.environ.get("POLITYK_TEST_DATABASE_URL")


@pytest.mark.skipif(_TEST_DSN is None, reason="POLITYK_TEST_DATABASE_URL not set")
def test_insert_visible_within_transaction_then_rolled_back() -> None:
    """Acceptance: insert row, assert fields, then rollback."""
    import psycopg

    assert _TEST_DSN is not None
    effective = datetime(2027, 4, 15, 12, 0, tzinfo=UTC)
    expires = effective + timedelta(days=10)

    with psycopg.connect(_TEST_DSN) as conn:
        # Manual transaction control: don't commit; rollback at end.
        intervention_id = intervene.insert_intervention(
            conn,
            target_kind="candidate",
            target_id=12345,
            kind="manual_probability",
            effective_at=effective,
            expires_at=expires,
            override_probability=0.42,
            reason="TSE Acuerdo NNNN-2027 test override",
            operator="afk-test",
        )
        assert intervention_id > 0

        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT target_kind::text, target_id, kind::text, effective_at,
                       expires_at, override_probability, reason, operator
                FROM interventions
                WHERE intervention_id = %s
                """,
                (intervention_id,),
            )
            row = cur.fetchone()
        assert row is not None
        assert row[0] == "candidate"
        assert row[1] == 12345
        assert row[2] == "manual_probability"
        # Postgres returns offset-aware TIMESTAMPTZ; compare instants.
        assert row[3] == effective
        assert row[4] == expires
        assert float(row[5]) == pytest.approx(0.42)
        assert row[6] == "TSE Acuerdo NNNN-2027 test override"
        assert row[7] == "afk-test"

        conn.rollback()

    # Fresh connection: row must not be visible after rollback.
    with psycopg.connect(_TEST_DSN) as conn:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT 1 FROM interventions WHERE intervention_id = %s",
                (intervention_id,),
            )
            assert cur.fetchone() is None


@pytest.mark.skipif(_TEST_DSN is None, reason="POLITYK_TEST_DATABASE_URL not set")
def test_db_rejects_override_probability_on_non_manual_kind() -> None:
    """The DB CHECK ties override_probability to kind='manual_probability'."""
    import psycopg

    assert _TEST_DSN is not None
    with psycopg.connect(_TEST_DSN) as conn:
        with pytest.raises(psycopg.errors.CheckViolation):
            intervene.insert_intervention(
                conn,
                target_kind="candidate",
                target_id=1,
                kind="disqualified",
                effective_at=datetime(2027, 4, 15, tzinfo=UTC),
                override_probability=0.5,  # disallowed for non-manual
                reason="should fail",
                operator="afk-test",
            )
        conn.rollback()


@pytest.mark.skipif(_TEST_DSN is None, reason="POLITYK_TEST_DATABASE_URL not set")
def test_db_rejects_manual_kind_without_override_probability() -> None:
    """manual_probability requires override_probability NOT NULL."""
    import psycopg

    assert _TEST_DSN is not None
    with psycopg.connect(_TEST_DSN) as conn:
        with pytest.raises(psycopg.errors.CheckViolation):
            intervene.insert_intervention(
                conn,
                target_kind="candidate",
                target_id=1,
                kind="manual_probability",
                effective_at=datetime(2027, 4, 15, tzinfo=UTC),
                override_probability=None,  # missing for manual_probability
                reason="should fail",
                operator="afk-test",
            )
        conn.rollback()


@pytest.mark.skipif(_TEST_DSN is None, reason="POLITYK_TEST_DATABASE_URL not set")
def test_main_emits_run_kind_whatif_when_whatif_flag_set(
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """`--whatif` makes the CLI print `run_kind=whatif` to stdout.

    Downstream forecast trigger (#33) reads this marker to write the
    next forecast as run_kind='whatif' (excluded from is_published).
    """
    assert _TEST_DSN is not None
    monkeypatch.setenv("DATABASE_URL", _TEST_DSN)
    monkeypatch.setenv("USER", "afk-test")

    rc = intervene.main(
        [
            "--target-kind",
            "candidate",
            "--target-id",
            "999999",
            "--kind",
            "disqualified",
            "--effective-at",
            "2027-04-15T12:00:00+00:00",
            "--reason",
            "whatif scenario test",
            "--whatif",
        ]
    )
    assert rc == 0
    out = capsys.readouterr().out
    assert "intervention_id=" in out
    assert "run_kind=whatif" in out

    # Cleanup the inserted row (main() commits — no rollback path here).
    import psycopg

    # Extract the printed intervention_id and delete the row directly.
    intervention_id_line = next(
        line for line in out.splitlines() if line.startswith("intervention_id=")
    )
    inserted_id = int(intervention_id_line.split("=", 1)[1])
    with psycopg.connect(_TEST_DSN) as conn:
        with conn.cursor() as cur:
            cur.execute(
                "DELETE FROM interventions WHERE intervention_id = %s",
                (inserted_id,),
            )
        conn.commit()


@pytest.mark.skipif(_TEST_DSN is None, reason="POLITYK_TEST_DATABASE_URL not set")
def test_main_omits_run_kind_whatif_when_flag_absent(
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Without `--whatif`, the CLI does NOT print run_kind=whatif."""
    assert _TEST_DSN is not None
    monkeypatch.setenv("DATABASE_URL", _TEST_DSN)
    monkeypatch.setenv("USER", "afk-test")

    rc = intervene.main(
        [
            "--target-kind",
            "candidate",
            "--target-id",
            "999998",
            "--kind",
            "disqualified",
            "--effective-at",
            "2027-04-15T12:00:00+00:00",
            "--reason",
            "scheduled scenario test",
        ]
    )
    assert rc == 0
    out = capsys.readouterr().out
    assert "intervention_id=" in out
    assert "run_kind=whatif" not in out

    import psycopg

    intervention_id_line = next(
        line for line in out.splitlines() if line.startswith("intervention_id=")
    )
    inserted_id = int(intervention_id_line.split("=", 1)[1])
    with psycopg.connect(_TEST_DSN) as conn:
        with conn.cursor() as cur:
            cur.execute(
                "DELETE FROM interventions WHERE intervention_id = %s",
                (inserted_id,),
            )
        conn.commit()
