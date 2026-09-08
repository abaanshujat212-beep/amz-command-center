import { SettingsCard, SettingsHeading, StatusPill } from "@/components/settings-ui"

const inbound = [
	"Define tenant-safe auth for any external MCP server before tools can touch account data.",
	"Keep write tools disabled unless they use the same approval/idempotency/audit contract as the app.",
	"Never pass Amazon refresh tokens, provider secrets or raw audit payloads to an external server.",
]
const outbound = [
	"Expose read-only account health, campaign KPIs, opportunities, approvals and verification status.",
	"Use platform API keys with read scopes by default; approval/write scopes must be explicitly enabled.",
	"Return tenant-scoped data only; no cross-tenant system map or secret access.",
]
const sensitive = ["approval decisions", "future write tools", "budget/bid mutations", "negative keyword changes", "external MCP tool execution"]

export default function McpSettingsPage() {
	return <div className="space-y-6"><SettingsHeading title="MCP readiness" description="Platform follow-up for connecting external MCP servers and exposing AXATY as a read-first MCP source."/><div className="rounded border border-red-200 bg-red-50 p-4 text-sm text-red-800"><b>Sensitive write scopes must be deliberately enabled.</b> Default MCP/API behavior remains read-only. Any approval/write scope needs owner/admin RBAC, warning UI, idempotency and audit logging.</div><div className="grid gap-4 lg:grid-cols-2"><SettingsCard title="Connect external MCP servers" aside={<StatusPill ready={false}>Deferred</StatusPill>}><p className="text-sm text-slate-600">External MCP tools are not required for the Amazon Command Center MVP. Before enabling them, each server needs tenant-safe auth, explicit tool permissions and a no-secrets contract.</p><ul className="mt-4 list-disc space-y-2 pl-5 text-sm text-slate-600">{inbound.map(item => <li key={item}>{item}</li>)}</ul></SettingsCard><SettingsCard title="Expose AXATY MCP" aside={<StatusPill ready={false}>Planned</StatusPill>}><p className="text-sm text-slate-600">The safe first version exposes the same read model as the API boundary. Approval/write tools should only appear when sensitive scopes are intentionally enabled.</p><ul className="mt-4 list-disc space-y-2 pl-5 text-sm text-slate-600">{outbound.map(item => <li key={item}>{item}</li>)}</ul></SettingsCard></div><SettingsCard title="Sensitive capabilities"><ul className="list-disc space-y-2 pl-5 text-sm text-slate-600">{sensitive.map(item => <li key={item}>{item}</li>)}</ul></SettingsCard><SettingsCard title="Recommended sequence"><ol className="list-decimal space-y-2 pl-5 text-sm text-slate-600"><li>Keep API/MCP clients read-only by default.</li><li>Enable approval scope only for trusted owner/admin clients.</li><li>Require warning UI before any write scope is created.</li><li>Add write-capable MCP tools only after route-level tests exist.</li><li>Keep direct Amazon mutation out of MCP; route through approvals and worker safety checks.</li></ol></SettingsCard></div>
}
