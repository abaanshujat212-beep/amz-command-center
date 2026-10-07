import datetime as dt

from services.rules.protections import active_protection


class Result:
    def __init__(self, row):
        self.row = row

    def fetchone(self):
        return self.row


class Connection:
    def __init__(self, row=None):
        self.row = row
        self.params = None

    def execute(self, _query, params):
        self.params = params
        return Result(self.row)


def test_protect_and_allow_block_destructive_automation():
    for policy in ("protect", "allow"):
        decision = active_protection(
            Connection(
                {
                    "id": "p1",
                    "policy": policy,
                    "reason": "human correction",
                    "duration": "persistent",
                    "expires_at": None,
                    "latest_event": "created",
                }
            ),
            tenant_id="t",
            entity_type="search_term",
            entity_value="womens shoes",
            product_scope="mens-shoes",
            action_type="add_negative_exact",
            now=dt.datetime(2026, 10, 7, tzinfo=dt.timezone.utc),
        )
        assert decision.blocked is True
        assert decision.protection_id == "p1"


def test_deny_permits_negative_and_release_or_expiry_returns_control():
    base = {
        "id": "p1",
        "policy": "deny",
        "reason": "irrelevant query",
        "duration": "persistent",
        "expires_at": None,
        "latest_event": "created",
    }
    assert not active_protection(
        Connection(base),
        tenant_id="t",
        entity_type="search_term",
        entity_value="womens shoes",
        action_type="add_negative_phrase",
    ).blocked
    assert not active_protection(
        Connection({**base, "policy": "protect", "latest_event": "released"}),
        tenant_id="t",
        entity_type="search_term",
        entity_value="womens shoes",
        action_type="add_negative_phrase",
    ).blocked


def test_non_destructive_action_does_not_query_or_block():
    conn = Connection({"unexpected": True})
    assert not active_protection(
        conn,
        tenant_id="t",
        entity_type="keyword",
        entity_value="brand",
        action_type="set_bid",
    ).blocked
    assert conn.params is None
