import { SettingsCard, SettingsHeading, StatusPill } from "@/components/settings-ui"
import { query, withTenant } from "@/lib/db"
import { stamp } from "@/lib/format"
import { currentContext } from "@/lib/session"

type Connection = {
	provider: string
	region: string
	status: string
	authorized_at: string | null
	last_refresh_at: string | null
	last_error: string | null
}

type Run = {
	dataset: string
	status: string
	started_at: string
	finished_at: string | null
	rows_loaded: number | null
	error: string | null
}

const providers = ["sp_api", "ads_api"] as const

function providerTitle(provider: string): string {
	return provider === "sp_api" ? "Selling Partner API" : "Amazon Ads API"
}

function providerCopy(provider: string): string {
	return provider === "sp_api"
		? "Orders, Sales & Traffic, catalog and sandbox report testing."
		: "Advertising profiles, reports and approval-gated actions. Ads access is pending until Amazon approves it."
}

function expectedMode(provider: string, item: Connection | undefined): string {
	if (!item) return provider === "ads_api" ? "Pending Amazon approval" : "Not configured"
	if (provider === "sp_api" && item.status === "active") return "Ready for sandbox/live read smoke"
	if (provider === "ads_api" && item.status !== "active") return "Waiting for Ads API approval"
	return item.status
}

function RunList({ runs }: { runs: Run[] }) {
	if (runs.length === 0) return <p className="text-xs text-slate-500">No related pipeline runs yet.</p>
	return <div className="space-y-2">{runs.map((run, i) => <div key={`${run.dataset}-${run.started_at}-${i}`} className="rounded border border-slate-100 bg-slate-50 p-2 text-xs"><div className="flex justify-between gap-2"><span className="font-medium text-slate-700">{run.dataset}</span><span className={run.status === "success" ? "tone-good" : run.status === "failed" || run.status === "partial" ? "tone-bad" : "tone-warn"}>{run.status}</span></div><div className="text-slate-500">{stamp(run.started_at)}{run.finished_at ? ` → ${stamp(run.finished_at)}` : ""} · {run.rows_loaded ?? 0} rows</div>{run.error && <div className="tone-bad">{run.error}</div>}</div>)}</div>
}

export default async function AmazonSettingsPage() {
	const actor = await currentContext()
	const { rows, runs } = await withTenant(actor.tenantId, async c => ({
		rows: await query<Connection>(c, "select provider,region,status,authorized_at::text,last_refresh_at::text,last_error from amazon_connection where tenant_id=$1 order by provider", [actor.tenantId]),
		runs: await query<Run>(c, "select dataset,status,started_at::text,finished_at::text,rows_loaded,error from pipeline_run where dataset in ('sales_traffic_asin_daily','action_worker','ads_sp_campaigns','ads_sp_ad_groups','ads_sp_targeting','ads_sp_search_terms') order by started_at desc limit 8"),
	}))
	return <div className="space-y-6"><SettingsHeading title="Amazon integrations" description="SP-API sandbox/live read status, Ads API approval status and recent backend run evidence."/><div className="grid gap-4 md:grid-cols-2">{providers.map(provider => { const item = rows.find(row => row.provider === provider); const ready = item?.status === "active"; const relatedRuns = runs.filter(run => provider === "sp_api" ? run.dataset === "sales_traffic_asin_daily" : run.dataset.startsWith("ads_") || run.dataset === "action_worker"); return <SettingsCard key={provider} title={providerTitle(provider)} aside={<StatusPill ready={ready}>{item?.status ?? "Not connected"}</StatusPill>}><p className="text-sm text-slate-600">{providerCopy(provider)}</p><div className="mt-3 rounded-lg bg-slate-50 p-3 text-xs text-slate-600"><b>Current mode:</b> {expectedMode(provider, item)}</div><dl className="mt-4 space-y-2 text-xs text-slate-500"><div>Region: <b className="text-slate-700">{item?.region ?? "EU / UK default"}</b></div><div>Authorized: <b className="text-slate-700">{item?.authorized_at ? stamp(item.authorized_at) : "Not recorded"}</b></div><div>Last token refresh: <b className="text-slate-700">{item?.last_refresh_at ? stamp(item.last_refresh_at) : "Never"}</b></div>{item?.last_error ? <div className="tone-bad">{item.last_error}</div> : null}</dl><div className="mt-4 border-t pt-4"><h4 className="mb-2 text-xs font-semibold uppercase tracking-wide text-slate-500">Recent backend evidence</h4><RunList runs={relatedRuns} /></div><p className="mt-4 border-t pt-4 text-xs text-slate-500">Credentials are loaded from the server environment; refresh tokens are persisted through the encrypted token vault. No secret is exposed in the browser.</p></SettingsCard>})}</div><SettingsCard title="Next operating sequence"><ol className="list-decimal space-y-2 pl-5 text-sm text-slate-600"><li>Use SP-API sandbox first: seed one local tenant, run Sales &amp; Traffic sandbox smoke, then run dbt.</li><li>Keep Ads API marked pending until Amazon approval arrives in roughly 72 hours.</li><li>After Ads approval, test Ads report/profile reads before enabling any live action write-back.</li><li>Action worker remains dry-run unless the explicit live Ads command is used.</li></ol></SettingsCard></div>
}
