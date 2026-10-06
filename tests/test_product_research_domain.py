import datetime as dt

import pytest

from services.research.domain import (
    add_candidate,
    add_observation,
    compare_candidates,
    create_project,
    set_disposition,
)


class NoDatabase:
    def execute(self, *_args, **_kwargs):
        raise AssertionError("invalid input must fail before database access")


def test_viewers_cannot_mutate_research():
    with pytest.raises(PermissionError):
        create_project(
            NoDatabase(), tenant_id="tenant", actor_user_id="user", actor_role="viewer", name="A"
        )
    with pytest.raises(PermissionError):
        set_disposition(
            NoDatabase(),
            tenant_id="tenant",
            candidate_id="candidate",
            actor_role="analyst",
            status="shortlisted",
        )


def test_own_catalog_identity_is_required_but_market_candidate_can_start_unmatched():
    with pytest.raises(ValueError, match="ASIN or SKU"):
        add_candidate(
            NoDatabase(),
            tenant_id="tenant",
            project_id="project",
            actor_user_id="user",
            actor_role="analyst",
            candidate_kind="own_catalog",
            title="Known product",
        )


@pytest.mark.parametrize("completeness", ["complete", "partial", "blocked"])
def test_observation_requires_attributed_single_value(completeness):
    with pytest.raises(ValueError, match="exactly one"):
        add_observation(
            NoDatabase(),
            tenant_id="tenant",
            candidate_id="candidate",
            actor_role="analyst",
            metric="price",
            provider="licensed",
            observed_at=dt.datetime(2026, 10, 6, tzinfo=dt.timezone.utc),
            method="provider_api",
            evidence_scope={"marketplace": "UK"},
            completeness=completeness,
            evidence_ref="report:1",
        )


def test_observation_rejects_naive_time_and_unknown_completeness():
    base = dict(
        conn=NoDatabase(),
        tenant_id="tenant",
        candidate_id="candidate",
        actor_role="analyst",
        metric="price",
        provider="licensed",
        method="provider_api",
        evidence_scope={"marketplace": "UK"},
        evidence_ref="report:1",
        numeric_value=12.5,
    )
    with pytest.raises(ValueError, match="timezone-aware"):
        add_observation(**base, observed_at=dt.datetime(2026, 10, 6), completeness="complete")
    with pytest.raises(ValueError, match="completeness"):
        add_observation(
            **base,
            observed_at=dt.datetime(2026, 10, 6, tzinfo=dt.timezone.utc),
            completeness="invented",
        )


@pytest.mark.parametrize("ids", [[], ["one"], ["same", "same"], [str(i) for i in range(11)]])
def test_compare_requires_two_to_ten_unique_candidates(ids):
    with pytest.raises(ValueError, match="2 to 10"):
        compare_candidates(NoDatabase(), tenant_id="tenant", candidate_ids=ids)
