"""State machine tests: nothing reaches a client's live account by accident."""

import datetime as dt

import pytest

from services.actions.state_machine import (
    Action,
    Status,
    TransitionError,
    apply,
    approve,
    expire,
    reject,
    retry,
    rollback,
    verify,
)

NOW = dt.datetime(2026, 8, 20, 12, 0, tzinfo=dt.timezone.utc)


def make(status: Status = Status.PENDING, **kw) -> Action:
    base = dict(
        id="a-1",
        tenant_id="t-1",
        entity_type="keyword",
        entity_id="kw-1",
        action_type="set_bid",
        before_value={"bid": 1.00},
        after_value={"bid": 1.10},
        status=status,
        requested_by="u-analyst",
        requested_at=NOW - dt.timedelta(hours=2),
    )
    base.update(kw)
    return Action(**base)


# ------------------------------------------------------------- happy path
def test_full_lifecycle():
    a = make()
    approve(a, approver_id="u-owner", approver_role="owner", now=NOW)
    assert a.status is Status.APPROVED

    apply(a, now=NOW, live_before_value={"bid": 1.00}, api_ok=True)
    assert a.status is Status.APPLIED and a.applied_at == NOW

    later = NOW + dt.timedelta(days=8)
    verify(a, now=later, outcome="improved", impact={"acos_delta": -0.04})
    assert a.status is Status.VERIFIED and a.outcome == "improved"


# --------------------------------------------------------- illegal moves
def test_cannot_skip_approval():
    a = make()
    with pytest.raises(TransitionError):
        apply(a, now=NOW, live_before_value={"bid": 1.00}, api_ok=True)


def test_verified_is_terminal():
    a = make(status=Status.VERIFIED, applied_at=NOW - dt.timedelta(days=9))
    with pytest.raises(TransitionError):
        rollback(a, now=NOW)


def test_cannot_rollback_a_pending_action():
    with pytest.raises(TransitionError):
        rollback(make(), now=NOW)


# -------------------------------------------------------------- approval
def test_analyst_cannot_approve():
    with pytest.raises(TransitionError, match="cannot approve"):
        approve(make(), approver_id="u-analyst", approver_role="analyst", now=NOW)


def test_viewer_cannot_approve():
    with pytest.raises(TransitionError):
        approve(make(), approver_id="u-v", approver_role="viewer", now=NOW)


def test_self_approval_blocked_by_default():
    a = make(requested_by="u-owner")
    with pytest.raises(TransitionError, match="self-approval"):
        approve(a, approver_id="u-owner", approver_role="owner", now=NOW)


def test_self_approval_allowed_when_tenant_opts_in():
    a = make(requested_by="u-owner")
    approve(
        a,
        approver_id="u-owner",
        approver_role="owner",
        now=NOW,
        allow_self_approval=True,
    )
    assert a.status is Status.APPROVED


# ---------------------------------------------------------------- expiry
def test_stale_proposal_cannot_be_approved():
    a = make(requested_at=NOW - dt.timedelta(hours=60))
    with pytest.raises(TransitionError, match="expired"):
        approve(a, approver_id="u-owner", approver_role="owner", now=NOW)


def test_expire_only_after_ttl():
    a = make()
    with pytest.raises(TransitionError, match="not yet expired"):
        expire(a, now=NOW)
    expire(a, now=NOW + dt.timedelta(hours=47))
    assert a.status is Status.EXPIRED


# ----------------------------------------------------------------- drift
def test_manual_change_in_seller_central_blocks_apply():
    """Somebody edited the bid by hand. We must not overwrite their intent."""
    a = make()
    approve(a, approver_id="u-owner", approver_role="owner", now=NOW)
    apply(a, now=NOW, live_before_value={"bid": 1.75}, api_ok=True)
    assert a.status is Status.FAILED
    assert "drift" in a.error


def test_api_failure_is_recorded_not_swallowed():
    a = make()
    approve(a, approver_id="u-owner", approver_role="owner", now=NOW)
    apply(a, now=NOW, live_before_value={"bid": 1.00}, api_ok=False, error="429 throttled")
    assert a.status is Status.FAILED and a.error == "429 throttled"


def test_failed_action_can_be_retried():
    a = make(status=Status.FAILED, error="429 throttled")
    retry(a)
    assert a.status is Status.PENDING and a.error is None


# ---------------------------------------------------------- verification
def test_cannot_verify_before_seven_days():
    a = make(status=Status.APPLIED, applied_at=NOW - dt.timedelta(days=3))
    with pytest.raises(TransitionError, match="too early"):
        verify(a, now=NOW, outcome="improved")


def test_unknown_outcome_rejected():
    a = make(status=Status.APPLIED, applied_at=NOW - dt.timedelta(days=9))
    with pytest.raises(TransitionError, match="unknown outcome"):
        verify(a, now=NOW, outcome="great success")


def test_rollback_requires_before_value():
    a = make(status=Status.APPLIED, applied_at=NOW, before_value=None)
    with pytest.raises(TransitionError, match="before_value"):
        rollback(a, now=NOW)


def test_rollback_from_applied_succeeds():
    a = make(status=Status.APPLIED, applied_at=NOW)
    rollback(a, now=NOW + dt.timedelta(days=1))
    assert a.status is Status.ROLLED_BACK and a.rolled_back_at is not None


def test_reject_from_pending():
    a = make()
    reject(a, actor_id="u-owner", now=NOW, reason="seasonal push, ignore ACOS")
    assert a.status is Status.REJECTED and "seasonal" in a.error
