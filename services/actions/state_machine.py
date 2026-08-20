"""Action state machine.

    pending ---approve---> approved ---apply---> applied ---verify---> verified
       |                      |                    |
       |--reject--> rejected  |--reject--> rejected|--rollback--> rolled_back
       |--expire--> expired                        
       |                      |--fail----> failed

Rules enforced here, not scattered across callers:
  * no state skipping (pending can never jump straight to applied)
  * only owner/admin may approve; nobody may approve their own proposal
    unless the tenant explicitly allows it
  * proposals expire after 48h -- an old recommendation is based on old data
  * only an applied action can be rolled back, and only to its before_value
  * every transition is journalled to audit_log by the caller
"""

from __future__ import annotations

import datetime as dt
from dataclasses import dataclass
from enum import Enum


class Status(str, Enum):
    PENDING = "pending"
    APPROVED = "approved"
    APPLIED = "applied"
    VERIFIED = "verified"
    REJECTED = "rejected"
    EXPIRED = "expired"
    FAILED = "failed"
    ROLLED_BACK = "rolled_back"


TERMINAL = {Status.VERIFIED, Status.REJECTED, Status.EXPIRED, Status.ROLLED_BACK}

ALLOWED: dict[Status, set[Status]] = {
    Status.PENDING: {Status.APPROVED, Status.REJECTED, Status.EXPIRED},
    Status.APPROVED: {Status.APPLIED, Status.FAILED, Status.REJECTED, Status.EXPIRED},
    Status.APPLIED: {Status.VERIFIED, Status.ROLLED_BACK},
    Status.FAILED: {Status.PENDING},          # retry re-enters the queue
    Status.VERIFIED: set(),
    Status.REJECTED: set(),
    Status.EXPIRED: set(),
    Status.ROLLED_BACK: set(),
}

APPROVER_ROLES = {"owner", "admin"}
PROPOSAL_TTL = dt.timedelta(hours=48)
VERIFY_AFTER = dt.timedelta(days=7)


class TransitionError(Exception):
    """Raised on an illegal or unauthorised transition."""


@dataclass
class Action:
    id: str
    tenant_id: str
    entity_type: str
    entity_id: str
    action_type: str
    before_value: dict | None
    after_value: dict
    status: Status = Status.PENDING
    requested_by: str | None = None
    requested_at: dt.datetime | None = None
    approved_by: str | None = None
    approved_at: dt.datetime | None = None
    applied_at: dt.datetime | None = None
    verified_at: dt.datetime | None = None
    rolled_back_at: dt.datetime | None = None
    outcome: str | None = None
    error: str | None = None

    @property
    def expires_at(self) -> dt.datetime:
        assert self.requested_at is not None
        return self.requested_at + PROPOSAL_TTL


def _assert(action: Action, target: Status) -> None:
    if target not in ALLOWED[action.status]:
        raise TransitionError(f"cannot move {action.status.value} -> {target.value}")


def approve(
    action: Action,
    *,
    approver_id: str,
    approver_role: str,
    now: dt.datetime,
    allow_self_approval: bool = False,
) -> Action:
    _assert(action, Status.APPROVED)
    if approver_role not in APPROVER_ROLES:
        raise TransitionError(f"role '{approver_role}' cannot approve actions")
    if now > action.expires_at:
        raise TransitionError("proposal expired; re-evaluate against fresh data")
    if (
        not allow_self_approval
        and action.requested_by is not None
        and action.requested_by == approver_id
    ):
        raise TransitionError("self-approval is disabled for this tenant")

    action.status = Status.APPROVED
    action.approved_by = approver_id
    action.approved_at = now
    return action


def reject(action: Action, *, actor_id: str, now: dt.datetime, reason: str = "") -> Action:
    _assert(action, Status.REJECTED)
    action.status = Status.REJECTED
    action.approved_by = actor_id
    action.approved_at = now
    action.error = reason or None
    return action


def expire(action: Action, *, now: dt.datetime) -> Action:
    _assert(action, Status.EXPIRED)
    if now <= action.expires_at:
        raise TransitionError("not yet expired")
    action.status = Status.EXPIRED
    return action


def apply(
    action: Action,
    *,
    now: dt.datetime,
    live_before_value: dict | None,
    api_ok: bool,
    error: str | None = None,
) -> Action:
    """Commit the change.

    `live_before_value` is read from Amazon immediately before writing, not
    taken from our marts. If somebody changed the bid by hand in Seller Central
    since the proposal, we must not silently overwrite their intent.
    """
    _assert(action, Status.APPLIED if api_ok else Status.FAILED)

    if api_ok and live_before_value is not None and action.before_value is not None:
        if live_before_value != action.before_value:
            action.status = Status.FAILED
            action.error = (
                "drift: live value "
                f"{live_before_value} no longer matches the proposed baseline "
                f"{action.before_value}; requires re-evaluation"
            )
            return action

    if not api_ok:
        action.status = Status.FAILED
        action.error = error or "amazon api call failed"
        return action

    action.before_value = live_before_value or action.before_value
    action.status = Status.APPLIED
    action.applied_at = now
    return action


def verify(
    action: Action,
    *,
    now: dt.datetime,
    outcome: str,
    impact: dict | None = None,
) -> Action:
    """Judge the result no earlier than T+7 days."""
    _assert(action, Status.VERIFIED)
    assert action.applied_at is not None
    if now - action.applied_at < VERIFY_AFTER:
        raise TransitionError("too early to verify; wait for the 7-day window")
    if outcome not in {"improved", "worsened", "neutral", "inconclusive", "drifted"}:
        raise TransitionError(f"unknown outcome '{outcome}'")
    action.status = Status.VERIFIED
    action.verified_at = now
    action.outcome = outcome
    return action


def rollback(action: Action, *, now: dt.datetime, api_ok: bool = True) -> Action:
    """Restore before_value. Only possible for an applied action."""
    _assert(action, Status.ROLLED_BACK)
    if action.before_value is None:
        raise TransitionError("no before_value captured; cannot roll back safely")
    if not api_ok:
        action.error = "rollback api call failed"
        return action
    action.status = Status.ROLLED_BACK
    action.rolled_back_at = now
    return action


def retry(action: Action) -> Action:
    """Send a failed action back to the queue for a fresh evaluation."""
    _assert(action, Status.PENDING)
    action.status = Status.PENDING
    action.error = None
    action.approved_by = None
    action.approved_at = None
    return action
