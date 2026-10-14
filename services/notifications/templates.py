"""Fail-closed approved-template selection for external notification routes."""

from __future__ import annotations


def load_approved_template(conn, tenant_id: str, event_type: str, channel: str):
    if channel not in {"email", "whatsapp", "sms"}:
        return None
    return conn.execute(
        """select id::text,event_type,channel,locale,subject_template,body_template,
                  variable_allowlist
             from notification_template
            where tenant_id=%s and channel=%s and event_type in (%s,'*')
              and status='APPROVED'
            order by case when event_type=%s then 0 else 1 end,updated_at desc
            limit 1""",
        (tenant_id, channel, event_type, event_type),
    ).fetchone()
