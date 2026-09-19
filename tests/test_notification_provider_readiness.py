import datetime as dt

from services.notifications.provider_readiness import load_provider_ready


class ReadinessConnection:
    def __init__(self, row):
        self.row = row
        self.parameters = None

    def execute(self, _sql, parameters):
        self.parameters = parameters
        return self

    def fetchone(self):
        return self.row


def test_missing_provider_state_fails_closed():
    assert load_provider_ready(ReadinessConnection(None), "tenant-1", "email") is False


def test_ready_requires_non_expired_explicit_evidence():
    future = dt.datetime.now(dt.timezone.utc) + dt.timedelta(minutes=5)
    past = dt.datetime.now(dt.timezone.utc) - dt.timedelta(minutes=5)
    assert load_provider_ready(
        ReadinessConnection({"readiness_state": "READY", "evidence_expires_at": future}),
        "tenant-1", "email",
    ) is True
    assert load_provider_ready(
        ReadinessConnection({"readiness_state": "READY", "evidence_expires_at": past}),
        "tenant-1", "email",
    ) is False


def test_credentials_or_config_refs_do_not_make_state_ready():
    assert load_provider_ready(
        ReadinessConnection({"readiness_state": "BLOCKED_CONFIGURATION", "evidence_expires_at": None}),
        "tenant-1", "email",
    ) is False


def test_unknown_channel_fails_closed_without_database_access():
    conn = ReadinessConnection({"readiness_state": "READY", "evidence_expires_at": None})
    assert load_provider_ready(conn, "tenant-1", "fax") is False
    assert conn.parameters is None
