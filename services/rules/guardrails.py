"""Guardrails: the layer that stops a correct rule from doing real damage.

Every proposed action passes through check() twice:
  1. at proposal time (so the UI shows what was blocked or clamped)
  2. again at apply time (data may have moved, the kill switch may have flipped)

Nothing is ever silently suppressed. A blocked proposal is stored with the name
of the guardrail that blocked it, because invisible automation is untrustworthy
automation.

TWO CLASSES OF PROPOSAL (issue #28)
A change and a diagnosis are not the same thing and must not be guarded the
same way. Guardrails exist to limit DAMAGE, and a diagnosis cannot cause any:
it changes nothing at Amazon. Running the mutation guardrails over diagnostics
silences them exactly when they matter most:

  * kill switch     -- automation_enabled is false by default, so a brand-new
                       tenant would see zero findings. That is the state where
                       findings are the entire product.
  * blast radius    -- "30% of your keywords have terrible CTR" is a real
                       finding, not a runaway rule. Halting it hides the truth.
  * cooldown        -- a diagnosis does not need to settle; nothing was done.
  * daily change    -- diagnostics consume no change budget.
  * clamp / bounds  -- there is no number to clamp.

Data-quality guardrails still apply in full, because a diagnosis drawn from
stale, unsettled or thin data is simply wrong, and a confidently wrong
recommendation costs trust faster than no recommendation at all.
"""

from __future__ import annotations

import datetime as dt
from dataclasses import dataclass, field
from enum import Enum

# Action types that only ever report a finding. They never reach the Amazon
# APIs; 0006_diagnostic_actions.sql enforces that in the database too.
DIAGNOSTIC_ACTIONS: frozenset[str] = frozenset({"flag"})


def is_diagnostic(action_type: str) -> bool:
    """True for recommend-only action types."""
    return action_type in DIAGNOSTIC_ACTIONS


class Guard(str, Enum):
    KILL_SWITCH = "kill_switch"
    DRY_RUN = "dry_run"
    STALE_DATA = "stale_data"
    UNSETTLED_DATA = "unsettled_data"
    THIN_DATA = "thin_data"
    COOLDOWN = "cooldown"
    DAILY_CHANGE_LIMIT = "daily_change_limit"
    DAILY_BUDGET_LIMIT = "daily_budget_limit"
    BLAST_RADIUS = "blast_radius"
    BOUNDS = "bounds"
    ECONOMICS_INCOMPLETE = "economics_incomplete"


@dataclass(frozen=True)
class TenantGuardConfig:
    """Mirrors tenant_settings. Defaults are deliberately conservative."""

    automation_enabled: bool = False
    dry_run: bool = True
    max_change_pct: float = 0.25          # +/-25% per single change
    cooldown_days: int = 3
    max_changes_per_day: int = 50
    max_budget_increase_per_day: float = 50.00
    blast_radius_pct: float = 0.30        # >30% of entities matched = halt
    min_bid: float = 0.02
    max_bid: float = 5.00
    max_daily_budget: float = 100.00
    max_data_age_hours: int = 48
    settlement_lag_days: int = 3


@dataclass(frozen=True)
class Proposal:
    entity_type: str
    entity_id: str
    action_type: str                       # 'set_bid' | 'set_budget' | 'flag' | ...
    before_value: float | None
    after_value: float | None
    clicks: int = 0
    impressions: int = 0
    break_even_acos: float | None = None

    @property
    def is_diagnostic(self) -> bool:
        return is_diagnostic(self.action_type)


@dataclass
class Decision:
    allowed: bool
    value: float | None = None
    clamped: bool = False
    notes: list[str] = field(default_factory=list)
    blocked_by: Guard | None = None

    def block(self, guard: Guard, note: str) -> "Decision":
        self.allowed = False
        self.blocked_by = guard
        self.notes.append(note)
        return self


@dataclass(frozen=True)
class RunContext:
    now: dt.datetime
    data_through: dt.date            # newest settled report date available
    data_loaded_at: dt.datetime      # when the newest data landed
    changes_applied_today: int = 0
    budget_increase_today: float = 0.0
    entities_evaluated: int = 0
    entities_matched: int = 0
    last_applied_at: dt.datetime | None = None   # for this entity


def clamp_change(
    before: float, after: float, cfg: TenantGuardConfig
) -> tuple[float, bool, str | None]:
    """Limit a single change to +/-max_change_pct of the current value."""
    if before is None or before <= 0:
        return after, False, None
    limit = abs(before) * cfg.max_change_pct
    lo, hi = before - limit, before + limit
    if after > hi:
        return hi, True, f"clamped from {after:.4f} to +{cfg.max_change_pct:.0%} ({hi:.4f})"
    if after < lo:
        return lo, True, f"clamped from {after:.4f} to -{cfg.max_change_pct:.0%} ({lo:.4f})"
    return after, False, None


def apply_bounds(
    action_type: str, value: float, cfg: TenantGuardConfig
) -> tuple[float, bool, str | None]:
    """Absolute floors and ceilings, applied after percentage clamping."""
    if action_type == "set_bid":
        if value < cfg.min_bid:
            return cfg.min_bid, True, f"raised to min_bid {cfg.min_bid}"
        if value > cfg.max_bid:
            return cfg.max_bid, True, f"lowered to max_bid {cfg.max_bid}"
    if action_type == "set_budget" and value > cfg.max_daily_budget:
        return cfg.max_daily_budget, True, f"lowered to max_daily_budget {cfg.max_daily_budget}"
    return value, False, None


def _data_quality(
    d: Decision,
    proposal: Proposal,
    cfg: TenantGuardConfig,
    ctx: RunContext,
    min_clicks: int,
    min_impressions: int,
) -> Decision | None:
    """Guardrails about whether the DATA can support any conclusion.

    Applied to changes and diagnostics alike. Returns a blocked Decision, or
    None when the data is good enough to proceed.
    """
    # Acting on stale data is worse than not acting.
    age_h = (ctx.now - ctx.data_loaded_at).total_seconds() / 3600
    if age_h > cfg.max_data_age_hours:
        return d.block(Guard.STALE_DATA, f"newest data is {age_h:.0f}h old")

    # Settlement lag: Amazon restates attributed sales for days.
    latest_settled = (ctx.now.date() - dt.timedelta(days=cfg.settlement_lag_days))
    if ctx.data_through > latest_settled:
        return d.block(
            Guard.UNSETTLED_DATA,
            f"data_through {ctx.data_through} is newer than the settled cutoff {latest_settled}",
        )

    # Thin data: no decisions on noise.
    if proposal.clicks < min_clicks and proposal.impressions < min_impressions:
        return d.block(
            Guard.THIN_DATA,
            f"only {proposal.clicks} clicks / {proposal.impressions} impressions",
        )

    return None


def check(
    proposal: Proposal,
    cfg: TenantGuardConfig,
    ctx: RunContext,
    min_clicks: int = 15,
    min_impressions: int = 500,
) -> Decision:
    """Run every guardrail. Order matters: cheapest and most absolute first."""
    d = Decision(allowed=True, value=proposal.after_value)

    # 0. Diagnostics: data quality only. See the module docstring for why the
    #    mutation guardrails are skipped rather than "passed" -- skipping is a
    #    decision, and it is recorded in the notes so the UI can show it.
    if proposal.is_diagnostic:
        blocked = _data_quality(d, proposal, cfg, ctx, min_clicks, min_impressions)
        if blocked is not None:
            return blocked
        d.value = None
        d.notes.append("diagnostic: reports a finding, never sent to Amazon")
        return d

    # 1. Kill switch beats everything, including mid-run.
    if not cfg.automation_enabled:
        return d.block(Guard.KILL_SWITCH, "automation_enabled is false for this tenant")

    # 2. Dry-run still produces a proposal, but it is never applied.
    if cfg.dry_run:
        d.notes.append("dry_run: recorded as WOULD_DO, not sent to Amazon")

    # 3-5. Data freshness, settlement lag, thin data.
    blocked = _data_quality(d, proposal, cfg, ctx, min_clicks, min_impressions)
    if blocked is not None:
        return blocked

    # 6. Cooldown: let the previous change settle before judging it again.
    if ctx.last_applied_at is not None:
        days = (ctx.now - ctx.last_applied_at).days
        if days < cfg.cooldown_days:
            return d.block(
                Guard.COOLDOWN,
                f"changed {days}d ago, cooldown is {cfg.cooldown_days}d",
            )

    # 7. Blast radius: a rule matching most of the account is a bug, not a win.
    if ctx.entities_evaluated >= 20:
        ratio = ctx.entities_matched / ctx.entities_evaluated
        if ratio > cfg.blast_radius_pct:
            return d.block(
                Guard.BLAST_RADIUS,
                f"{ratio:.0%} of entities matched (limit {cfg.blast_radius_pct:.0%}); halting for review",
            )

    # 8. Daily change budget.
    if ctx.changes_applied_today >= cfg.max_changes_per_day:
        return d.block(
            Guard.DAILY_CHANGE_LIMIT,
            f"{ctx.changes_applied_today} changes already applied today",
        )

    # 9. Clamp magnitude, then apply absolute bounds.
    if proposal.action_type in ("set_bid", "set_budget") and proposal.after_value is not None:
        value = proposal.after_value
        if proposal.before_value is not None:
            value, clamped, note = clamp_change(proposal.before_value, value, cfg)
            if clamped:
                d.clamped = True
                if note:
                    d.notes.append(note)
        value, bounded, note = apply_bounds(proposal.action_type, value, cfg)
        if bounded:
            d.clamped = True
            if note:
                d.notes.append(note)
        d.value = round(value, 2)

        # 10. Daily budget increase cap (after clamping, using the real delta).
        if proposal.action_type == "set_budget" and proposal.before_value is not None:
            delta = d.value - proposal.before_value
            if delta > 0 and ctx.budget_increase_today + delta > cfg.max_budget_increase_per_day:
                return d.block(
                    Guard.DAILY_BUDGET_LIMIT,
                    f"budget increase {delta:.2f} would exceed the daily cap "
                    f"({cfg.max_budget_increase_per_day:.2f})",
                )

    return d
