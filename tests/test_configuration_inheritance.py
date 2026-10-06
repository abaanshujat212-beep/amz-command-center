import datetime as dt

import pytest

from services.config.inheritance import diff_configuration, resolve_effective_configuration


class Result:
    def __init__(self, rows):
        self.rows = rows

    def fetchall(self):
        return self.rows


class Connection:
    def __init__(self, *results):
        self.results = iter(results)

    def execute(self, _query, _params):
        return Result(next(self.results))


def definition(key, value, *, version=1, hard=False):
    return {
        "key": key,
        "version": version,
        "default_value": value,
        "hard_guard": hard,
    }


def override(scope, scope_id, version, values, operation="apply"):
    return {
        "id": f"{scope}-{version}",
        "scope_type": scope,
        "scope_id": scope_id,
        "version": version,
        "operation": operation,
        "values": values,
    }


def test_precedence_detach_hard_caps_and_trace_are_deterministic():
    definitions = [
        definition("max_bid", 5),
        definition("absolute_max_bid", 50, hard=True),
        definition("dry_run", True),
    ]
    overrides = [
        override("tenant", "t", 2, {"max_bid": 8, "dry_run": False}),
        override("marketplace", "uk", 1, {"max_bid": 12}),
        override("entity", "campaign:c1", 3, {}, operation="detach"),
    ]
    result = resolve_effective_configuration(
        Connection(definitions, overrides),
        tenant_id="t",
        scopes={"tenant": "t", "marketplace": "uk", "entity": "campaign:c1"},
        at=dt.datetime(2026, 10, 6, tzinfo=dt.timezone.utc),
    )
    assert result.values["max_bid"] == 12
    assert result.sources["max_bid"].level == "marketplace"
    assert result.values["dry_run"] is False
    assert result.sources["dry_run"].level == "tenant"

    changes = diff_configuration(result, {"max_bid": 12, "dry_run": True})
    assert set(changes) == {"dry_run"}
    assert changes["dry_run"]["source"].level == "tenant"


def test_system_hard_cap_overrides_higher_local_number():
    result = resolve_effective_configuration(
        Connection(
            [definition("max_bid", 5), definition("absolute_max_bid", 50, hard=True)],
            [override("entity", "keyword:k1", 1, {"max_bid": 75})],
        ),
        tenant_id="t",
        scopes={"tenant": "t", "entity": "keyword:k1"},
    )
    assert result.values["max_bid"] == 50
    assert result.sources["max_bid"].level == "system"
    assert result.sources["max_bid"].hard_guard is True


@pytest.mark.parametrize(
    ("scopes", "message"),
    [
        ({"tenant": "wrong"}, "tenant scope must equal tenant_id"),
        ({"tenant": "t", "entity": ""}, "scope ids cannot be blank"),
        ({"tenant": "t", "portfolio": "p"}, "unsupported configuration scope"),
    ],
)
def test_invalid_context_fails_closed(scopes, message):
    with pytest.raises(ValueError, match=message):
        resolve_effective_configuration(Connection([], []), tenant_id="t", scopes=scopes)


def test_invalid_stored_hard_guard_override_fails_closed():
    with pytest.raises(RuntimeError, match="hard guard"):
        resolve_effective_configuration(
            Connection(
                [definition("allow_direct_amazon_mutation", False, hard=True)],
                [override("tenant", "t", 1, {"allow_direct_amazon_mutation": True})],
            ),
            tenant_id="t",
            scopes={"tenant": "t"},
        )
