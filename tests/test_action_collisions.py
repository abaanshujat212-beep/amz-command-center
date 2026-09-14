import datetime as dt

import pytest

from services.actions.collisions import CollisionKind, detect, record_source_signal


class FakeCursor:
    def __init__(self, row=None):
        self.row = row
        self.calls = []

    def execute(self, sql, params):
        self.calls.append((sql, params))
        return self

    def fetchone(self):
        return self.row


def test_detect_maps_canonical_collision_row():
    cur = FakeCursor({
        "collision_kind": "manual_change",
        "conflicting_action_id": None,
        "change_signal_id": "signal-1",
        "evidence": {"source": "manual"},
    })
    collision = detect(cur, tenant_id="tenant-1", entity_type="keyword", entity_id="K1")
    assert collision is not None
    assert collision.kind is CollisionKind.MANUAL_CHANGE
    assert collision.change_signal_id == "signal-1"
    assert collision.evidence == {"source": "manual"}


def test_record_signal_redacts_secret_shaped_evidence():
    now = dt.datetime.now(dt.timezone.utc)
    cur = FakeCursor(("signal-1",))
    signal_id = record_source_signal(
        cur,
        tenant_id="t",
        entity_type="keyword",
        entity_id="k",
        source="manual",
        change_kind="bid",
        observed_at=now,
        expires_at=now + dt.timedelta(hours=1),
        source_ref="x",
        evidence={"authorization": "secret", "safe": "value"},
    )
    assert signal_id == "signal-1"
    payload = cur.calls[0][1][-1]
    assert '"authorization": "[REDACTED]"' in payload
    assert '"safe": "value"' in payload
    assert "secret" not in payload


def test_record_signal_rejects_unknown_source_and_invalid_window():
    now = dt.datetime.now(dt.timezone.utc)
    cur = FakeCursor()
    with pytest.raises(ValueError, match="source"):
        record_source_signal(cur, tenant_id="t", entity_type="keyword", entity_id="k", source="fixture", change_kind="bid", observed_at=now, expires_at=now + dt.timedelta(hours=1), source_ref="x")
    with pytest.raises(ValueError, match="expires_at"):
        record_source_signal(cur, tenant_id="t", entity_type="keyword", entity_id="k", source="manual", change_kind="bid", observed_at=now, expires_at=now, source_ref="x")
