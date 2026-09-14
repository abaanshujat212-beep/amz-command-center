from pathlib import Path

state = Path("services/actions/state_machine.py")
text = state.read_text()
text = text.replace(
    "    error: str | None = None\n",
    "    error: str | None = None\n    idempotency_key: str | None = None\n",
)
state.write_text(text)

worker = Path("services/actions/worker.py")
text = worker.read_text()
text = text.replace(
    "from services.actions import state_machine as sm\n",
    "from services.actions import state_machine as sm\nfrom services.actions.audit import EventType, append_event, event_for, sanitize\n",
)
text = text.replace(
    "        applied_at=row[\"applied_at\"],\n",
    "        applied_at=row[\"applied_at\"],\n        idempotency_key=row[\"idempotency_key\"],\n",
    1,
)
text = text.replace(
    "               after_value, status, approved_by, approved_at, applied_at\n",
    "               after_value, status, approved_by, approved_at, applied_at, idempotency_key\n",
)
marker = "\ndef persist_apply_result(conn, action: sm.Action, api_response: dict | None = None) -> None:\n"
insert = '''

def record_apply_start(conn, action: sm.Action, *, correlation_key: str, attempt: int = 1) -> None:
    for kind, suffix in (
        (EventType.APPLY_REQUESTED, "requested"),
        (EventType.APPLY_STARTED, "started"),
    ):
        append_event(
            conn,
            event_for(
                action,
                kind,
                correlation_key=correlation_key,
                dedupe_key=f"apply:{attempt}:{correlation_key}:{suffix}",
                retry_attempt=attempt,
                actor_id="action-worker",
                previous_state=action.status.value,
                new_state=action.status.value,
            ),
        )
'''
if marker not in text:
    raise SystemExit("persist_apply_result marker missing")
text = text.replace(marker, insert + marker)
old = '''def persist_apply_result(conn, action: sm.Action, api_response: dict | None = None) -> None:
    conn.execute(
        """
        update action
           set status = %s, before_value = %s, applied_at = %s,
               error = %s, api_response = %s
         where tenant_id = %s and id = %s
        """,
        (
            action.status.value,
            psycopg.types.json.Jsonb(action.before_value),
            action.applied_at,
            action.error,
            psycopg.types.json.Jsonb(api_response or {}),
            action.tenant_id,
            action.id,
        ),
    )
'''
new = '''def persist_apply_result(
    conn,
    action: sm.Action,
    api_response: dict | None = None,
    *,
    correlation_key: str | None = None,
    attempt: int = 1,
) -> None:
    conn.execute(
        """
        update action
           set status = %s, before_value = %s, applied_at = %s,
               error = %s, api_response = %s
         where tenant_id = %s and id = %s
        """,
        (
            action.status.value,
            psycopg.types.json.Jsonb(action.before_value),
            action.applied_at,
            action.error,
            psycopg.types.json.Jsonb(sanitize(api_response or {})),
            action.tenant_id,
            action.id,
        ),
    )
    if correlation_key is None:
        return
    drift = action.status == sm.Status.FAILED and bool(action.error and action.error.startswith("drift:"))
    if drift:
        kind = EventType.DRIFT_BLOCKED
        classification = "drift_blocked"
    elif action.status == sm.Status.APPLIED:
        kind = EventType.APPLY_SUCCEEDED
        classification = "success"
    else:
        kind = EventType.APPLY_FAILED
        classification = "failed"
    append_event(
        conn,
        event_for(
            action,
            kind,
            correlation_key=correlation_key,
            dedupe_key=f"apply:{attempt}:{correlation_key}:result",
            retry_attempt=attempt,
            actor_id="action-worker",
            previous_state=sm.Status.APPROVED.value,
            new_state=action.status.value,
            applied_value=api_response if action.status == sm.Status.APPLIED else None,
            provider_result_classification=classification,
            metadata={"error": action.error} if action.error else {},
        ),
    )
'''
if old not in text:
    raise SystemExit("persist_apply_result body missing")
text = text.replace(old, new)
text = text.replace(
    "                updated, response = apply_action(action, client, now=now)\n                persist_apply_result(conn, updated, response)\n",
    "                correlation_key = str(run_id)\n                if live_ads:\n                    record_apply_start(conn, action, correlation_key=correlation_key)\n                updated, response = apply_action(action, client, now=now)\n                persist_apply_result(\n                    conn,\n                    updated,\n                    response,\n                    correlation_key=correlation_key if live_ads else None,\n                )\n",
)
old_except = '''        except Exception as exc:
            finish_worker_run(conn, run_id, result, error=str(exc))
            conn.commit()
            raise
'''
new_except = '''        except Exception:
            conn.rollback()
            raise
'''
if old_except not in text:
    raise SystemExit("worker exception block missing")
worker.write_text(text.replace(old_except, new_except))

verification = Path("services/actions/verification.py")
text = verification.read_text()
text = text.replace(
    "from services.actions import state_machine as sm\n",
    "from services.actions import state_machine as sm\nfrom services.actions.audit import EventType, append_event, event_for\n",
)
text = text.replace(
    "        applied_at=row[\"applied_at\"],\n",
    "        applied_at=row[\"applied_at\"],\n        idempotency_key=row[\"idempotency_key\"],\n",
    1,
)
text = text.replace(
    "               after_value, status, applied_at\n",
    "               after_value, status, applied_at, idempotency_key\n",
)
needle = '''def verify_action(conn, action: sm.Action, *, now: dt.datetime) -> sm.Action:
    assert action.applied_at is not None
    applied_date = action.applied_at.date()
'''
replacement = '''def verify_action(conn, action: sm.Action, *, now: dt.datetime) -> sm.Action:
    assert action.applied_at is not None
    correlation_key = f"verification:{action.id}:{action.applied_at.isoformat()}"
    append_event(
        conn,
        event_for(
            action,
            EventType.VERIFICATION_SCHEDULED,
            correlation_key=correlation_key,
            dedupe_key="verification:scheduled",
            actor_type="system",
            actor_id="verification-worker",
            previous_state=action.status.value,
            new_state=action.status.value,
        ),
    )
    applied_date = action.applied_at.date()
'''
if needle not in text:
    raise SystemExit("verification start missing")
text = text.replace(needle, replacement)
text = text.replace(
    "    after = performance_window(\n",
    '''    append_event(
        conn,
        event_for(
            action,
            EventType.VERIFICATION_CHECKPOINT,
            correlation_key=correlation_key,
            dedupe_key="verification:before-window",
            actor_type="system",
            actor_id="verification-worker",
            verification_checkpoint="before_window_loaded",
            metadata={"window": before.__dict__},
        ),
    )
    after = performance_window(
''',
    1,
)
text = text.replace(
    "    outcome, impact = judge(before, after)\n",
    '''    append_event(
        conn,
        event_for(
            action,
            EventType.VERIFICATION_CHECKPOINT,
            correlation_key=correlation_key,
            dedupe_key="verification:after-window",
            actor_type="system",
            actor_id="verification-worker",
            verification_checkpoint="after_window_loaded",
            metadata={"window": after.__dict__},
        ),
    )
    outcome, impact = judge(before, after)
''',
    1,
)
return_needle = "    return updated\n\n\ndef run_once"
return_replacement = '''    for kind, suffix in (
        (EventType.VERIFICATION_RESULT, "result"),
        (EventType.VERIFICATION_TERMINAL, "terminal"),
    ):
        append_event(
            conn,
            event_for(
                updated,
                kind,
                correlation_key=correlation_key,
                dedupe_key=f"verification:{suffix}",
                actor_type="system",
                actor_id="verification-worker",
                previous_state=sm.Status.APPLIED.value,
                new_state=updated.status.value,
                provider_result_classification=outcome,
                verification_checkpoint=outcome,
                metadata={"impact": impact},
            ),
        )
    return updated


def run_once'''
if return_needle not in text:
    raise SystemExit("verification return missing")
verification.write_text(text.replace(return_needle, return_replacement, 1))
