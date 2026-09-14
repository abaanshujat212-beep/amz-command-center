from pathlib import Path

approval = Path("apps/web/lib/approval-decision.ts")
text = approval.read_text()
old = """\t\tif (isApproval) {
\t\t\tconst candidate = await query<{ entity_type: string; action_type: string }>(c, \"select entity_type, action_type from action where id = $1 and status = 'pending'\", [input.actionId])
\t\t\tif (candidate.length > 0) { const support = liveActionSupport(candidate[0].entity_type, candidate[0].action_type); if (!support.supported) throw new ApprovalDecisionError(support.message, 409) }
\t\t}
"""
new = """\t\tif (isApproval) {
\t\t\tconst candidate = await query<{ entity_type: string; action_type: string }>(c, \"select entity_type, action_type from action where id = $1 and status = 'pending'\", [input.actionId])
\t\t\tif (candidate.length > 0) {
\t\t\t\tconst readiness = await query<{ readiness_state: string; verification_level: string | null }>(c, \"select readiness_state, metadata->>'verification_level' as verification_level from external_dependency_state where module_key = 'ppc' and dependency_key = 'amazon_ads' order by updated_at desc limit 1\")
\t\t\t\tconst state = readiness[0]
\t\t\t\tconst support = liveActionSupport(candidate[0].entity_type, candidate[0].action_type, state?.readiness_state, state?.verification_level ?? undefined)
\t\t\t\tif (!support.supported) throw new ApprovalDecisionError(support.message, 409)
\t\t\t}
\t\t}
"""
if old not in text:
    raise SystemExit("approval insertion point not found")
approval.write_text(text.replace(old, new))

worker = Path("services/actions/worker.py")
text = worker.read_text()
text = text.replace(
    "from services.actions import state_machine as sm\n",
    "from packages.shared.action_capabilities import assert_worker_capability\nfrom services.actions import state_machine as sm\n",
)
text = text.replace(
    "    def __init__(self, ads: AdsClient) -> None:\n        self.ads = ads\n",
    "    def __init__(self, ads: AdsClient, readiness_state: str | None, verification_level: str | None) -> None:\n        self.ads = ads\n        self.readiness_state = readiness_state\n        self.verification_level = verification_level\n\n    def _require(self, action: sm.Action, phase: str) -> None:\n        assert_worker_capability(\n            action.entity_type,\n            action.action_type,\n            phase=phase,\n            readiness_state=self.readiness_state,\n            verification_level=self.verification_level,\n        )\n",
)
text = text.replace(
    "    def read_before_value(self, action: sm.Action) -> dict | None:\n        if action.action_type == \"set_bid\"",
    "    def read_before_value(self, action: sm.Action) -> dict | None:\n        self._require(action, \"baseline\")\n        if action.action_type == \"set_bid\"",
)
text = text.replace(
    "    def apply(self, action: sm.Action) -> dict:\n        value = action.after_value.get(\"value\")",
    "    def apply(self, action: sm.Action) -> dict:\n        self._require(action, \"apply\")\n        value = action.after_value.get(\"value\")",
)
text = text.replace(
    "    def rollback(self, action: sm.Action) -> dict:\n        if action.before_value is None:",
    "    def rollback(self, action: sm.Action) -> dict:\n        self._require(action, \"rollback\")\n        if action.before_value is None:",
)
insert = """

def load_action_readiness(conn, tenant_id: str) -> tuple[str | None, str | None]:
    row = conn.execute(
        """
        select readiness_state, metadata->>'verification_level' as verification_level
          from external_dependency_state
         where tenant_id = %s and module_key = 'ppc' and dependency_key = 'amazon_ads'
         order by updated_at desc
         limit 1
        """,
        (tenant_id,),
    ).fetchone()
    if row is None:
        return None, None
    return row["readiness_state"], row["verification_level"]
"""
marker = "\ndef persist_rotated_refresh_token(conn, ads: AdsClient) -> None:\n"
if marker not in text:
    raise SystemExit("worker readiness insertion point not found")
text = text.replace(marker, insert + marker)
text = text.replace(
    "                    client = AdsActionClient(ads_client)\n",
    "                    readiness_state, verification_level = load_action_readiness(conn, tenant_id)\n                    client = AdsActionClient(ads_client, readiness_state, verification_level)\n",
)
worker.write_text(text)
