import { SettingsCard, SettingsHeading, StatusPill } from "@/components/settings-ui"

const inbound = [
	"Define tenant-safe auth for any external MCP server before tools can touch account data.",
	"Keep write tools disabled unless they use the same approval/idempotency/audit contract as the app.",
	"Never pass Amazon refresh tokens, provider secrets or raw audit payloads to an external server.",
]
const outbound = [
	"Expose read-only account health, campaign KPIs, opportunities, approvals and verification status.",
	"Use platform API keys with read scopes only until mutating API contracts are proven.",
	"Return tenant-scoped data only; no cross-tenant system map or secret access.",
]

export default function McpSettingsPage() {
	return <div className="space-y-6"><SettingsHeading title="MCP readiness" description="Platform follow-up for connecting external MCP servers and exposing AXATY as a read-only MCP source."/><div className="grid gap-4 lg:grid-cols-2"><SettingsCard title="Connect external MCP servers" aside={<StatusPill ready={false}>Deferred</StatusPill>}><p className="text-sm text-slate-600">External MCP tools are not required for the Amazon Command Center MVP. Before enabling them, each server needs tenant-safe auth, explicit tool permissions and a no-secrets contract.</p><ul className="mt-4 list-disc space-y-2 pl-5 text-sm text-slate-600">{inbound.map(item => <li key={item}>{item}</li>)}</ul></SettingsCard><SettingsCard title="Expose AXATY read-only MCP" aside={<StatusPill ready={false}>Planned</StatusPill>}><p className="text-sm text-slate-600">The safe first version should expose the same read model as the API boundary: KPIs, alerts, opportunities and verification — not write-back.</p><ul className="mt-4 list-disc space-y-2 pl-5 text-sm text-slate-600">{outbound.map(item => <li key={item}>{item}</li>)}</ul></SettingsCard></div><SettingsCard title="Recommended sequence"><ol className="list-decimal space-y-2 pl-5 text-sm text-slate-600"><li>Finish read API boundary and platform read keys.</li><li>Define MCP tool permission scopes and tenant auth.</li><li>Expose read-only MCP server first.</li><li>Add external MCP connections only after a security review.</li><li>Keep mutating tools out until approvals/write-back have explicit tests.</li></ol></SettingsCard></div>
}
