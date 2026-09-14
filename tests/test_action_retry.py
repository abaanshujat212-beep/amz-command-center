import datetime as dt

import pytest

from services.actions.audit import EventType
from services.actions.retry import release_due_retries, replay_dead_letter


class Result:
    def __init__(self, rows=None):
        self.rows = rows or []

    def fetchall(self):
        return self.rows

    def fetchone(self):
        return self.rows[0] if self.rows else None


class FakeConn:
    def __init__(self, rows=None):
        self.rows = rows or []
        self.calls = []

    def execute(self, sql, params):
        self.calls.append((sql, params))
        if "select id,tenant_id" in sql:
            return Result(self.rows)
        return Result()


def row():
    return {
        "id": "a1",
        "tenant_id": "t1",
        "entity_type": "keyword",
        "entity_id": "k1",
        "idempotency_key": "idem-1",
        "retry_count": 2,
        "failure_classification": "transient",
    }


def test_release_due_retry_is_claimed_and_audited(monkeypatch):
    events = []
    monkeypatch.setattr("services.actions.retry.append_event", lambda _conn, event: events.append(event))
    releases = release_due_retries(
        FakeConn([row()]),
        "t1",
        now=dt.datetime.now(dt.timezone.utc),
        correlation_key="release-1",
    )
    assert releases[0].attempt == 2
    assert events[0].event_type is EventType.RETRY_ATTEMPTED
    assert events[0].previous_state == "failed"
    assert events[0].new_state == "pending"


def test_dead_letter_replay_requires_authorized_role():
    with pytest.raises(PermissionError):
        replay_dead_letter(
            FakeConn([row()]),
            tenant_id="t1",
            action_id="a1",
            actor_id="u1",
            actor_role="viewer",
        )


def test_dead_letter_replay_is_explicit_and_audited(monkeypatch):
    events = []
    monkeypatch.setattr("services.actions.retry.append_event", lambda _conn, event: events.append(event))
    replay = replay_dead_letter(
        FakeConn([row()]),
        tenant_id="t1",
        action_id="a1",
        actor_id="u1",
        actor_role="owner",
        correlation_key="replay-1",
    )
    assert replay.action_id == "a1"
    assert events[0].event_type is EventType.RETRY_SCHEDULED
    assert events[0].actor_type == "user"
