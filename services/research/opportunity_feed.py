"""Schedule evidence-grounded Product Research feeds and optional digests."""

from __future__ import annotations

import datetime as dt

from services.notifications.router import InternalEvent, publish_in_app
from services.reports.scheduled_delivery import ScheduleSpec, next_run

MANAGER_ROLES = frozenset({"owner", "admin"})


def create_schedule(
    conn,
    *,
    tenant_id: str,
    project_id: str,
    actor_user_id: str,
    actor_role: str,
    spec: ScheduleSpec,
    digest_enabled: bool = False,
    recipient_user_id: str | None = None,
    now: dt.datetime | None = None,
) -> str:
    if actor_role not in MANAGER_ROLES:
        raise PermissionError("only owners or admins may schedule opportunity feeds")
    if spec.cadence not in {"weekly", "monthly"}:
        raise ValueError("opportunity feeds support weekly or monthly cadence")
    if digest_enabled and not recipient_user_id:
        raise ValueError("digest delivery requires a recipient")
    if (
        recipient_user_id
        and conn.execute(
            "select 1 from tenant_member where tenant_id=%s and user_id=%s",
            (tenant_id, recipient_user_id),
        ).fetchone()
        is None
    ):
        raise ValueError("recipient must be a tenant member")
    due = next_run(spec, now or dt.datetime.now(dt.timezone.utc))
    row = conn.execute(
        """insert into opportunity_feed_schedule(
               tenant_id,project_id,cadence,run_time,weekday,month_day,timezone,
               digest_enabled,recipient_user_id,next_run_at,created_by)
           values(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s) returning id""",
        (
            tenant_id,
            project_id,
            spec.cadence,
            spec.run_time,
            spec.weekday,
            spec.month_day,
            spec.timezone,
            digest_enabled,
            recipient_user_id,
            due,
            actor_user_id,
        ),
    ).fetchone()
    return str(row["id"])


def run_due(conn, *, tenant_id: str, now: dt.datetime, limit: int = 25) -> int:
    """Materialize ranked feeds only from complete, attributed score evidence."""
    schedules = conn.execute(
        """select * from opportunity_feed_schedule where tenant_id=%s and enabled
             and next_run_at<=%s order by next_run_at for update skip locked limit %s""",
        (tenant_id, now, limit),
    ).fetchall()
    completed = 0
    for schedule in schedules:
        scheduled_for = schedule["next_run_at"]
        inserted = conn.execute(
            """insert into opportunity_feed_run(tenant_id,schedule_id,scheduled_for,status)
               values(%s,%s,%s,'blocked_readiness')
               on conflict(tenant_id,schedule_id,scheduled_for) do nothing returning id""",
            (tenant_id, schedule["id"], scheduled_for),
        ).fetchone()
        following = next_run(
            ScheduleSpec(
                schedule["cadence"],
                schedule["run_time"],
                schedule["timezone"],
                schedule["weekday"],
                schedule["month_day"],
            ),
            scheduled_for,
        )
        conn.execute(
            "update opportunity_feed_schedule set next_run_at=%s,updated_at=now() where tenant_id=%s and id=%s",
            (following, tenant_id, schedule["id"]),
        )
        if inserted is None:
            continue
        run_id = inserted["id"]
        scores = conn.execute(
            """select distinct on(c.id) c.id,o.id as observation_id,o.numeric_value as score
                 from research_candidate c join research_observation o
                   on o.tenant_id=c.tenant_id and o.candidate_id=c.id
                where c.tenant_id=%s and c.project_id=%s and c.status<>'rejected'
                  and o.metric='opportunity_score' and o.completeness='complete'
                  and o.numeric_value is not null
                order by c.id,o.observed_at desc""",
            (tenant_id, schedule["project_id"]),
        ).fetchall()
        if not scores:
            conn.execute(
                "update opportunity_feed_run set reason='No complete provider-attributed opportunity_score evidence' where tenant_id=%s and id=%s",
                (tenant_id, run_id),
            )
            continue
        scores.sort(key=lambda row: (-float(row["score"]), str(row["id"])))
        for rank, score in enumerate(scores, 1):
            conn.execute(
                """insert into opportunity_feed_item(
                       tenant_id,run_id,candidate_id,score_observation_id,rank,score)
                   values(%s,%s,%s,%s,%s,%s)""",
                (tenant_id, run_id, score["id"], score["observation_id"], rank, score["score"]),
            )
        event_id = None
        if schedule["digest_enabled"]:
            member = conn.execute(
                "select 1 from tenant_member where tenant_id=%s and user_id=%s",
                (tenant_id, schedule["recipient_user_id"]),
            ).fetchone()
            if member is None:
                conn.execute(
                    "update opportunity_feed_run set status='blocked_recipient',reason='Recipient is not a tenant member' where tenant_id=%s and id=%s",
                    (tenant_id, run_id),
                )
                continue
            event = publish_in_app(
                conn,
                InternalEvent(
                    tenant_id=tenant_id,
                    event_type="product_opportunity_digest",
                    source="internal",
                    source_ref=str(run_id),
                    dedupe_key=f"opportunity-feed:{run_id}",
                    severity="info",
                    title=f"Product opportunity feed: {len(scores)} ranked candidates",
                    payload={"run_id": str(run_id), "candidate_count": len(scores)},
                    occurred_at=now,
                    recipient_ref=str(schedule["recipient_user_id"]),
                ),
            )
            event_id = event.event_id
        conn.execute(
            "update opportunity_feed_run set status='succeeded',reason=null,notification_event_id=%s where tenant_id=%s and id=%s",
            (event_id, tenant_id, run_id),
        )
        completed += 1
    return completed
