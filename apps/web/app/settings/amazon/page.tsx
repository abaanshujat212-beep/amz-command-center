import { query, withTenant } from "@/lib/db"
import { currentContext } from "@/lib/session"
import { SettingsCard, SettingsHeading, StatusPill } from "@/components/settings-ui"

type Connection = { provider:string; region:string; status:string; authorized_at:string|null; last_refresh_at:string|null; last_error:string|null }
export default async function AmazonSettingsPage() {
	const actor = await currentContext()
	const rows = await withTenant(actor.tenantId, c => query<Connection>(c,"select provider,region,status,authorized_at::text,last_refresh_at::text,last_error from amazon_connection where tenant_id=$1 order by provider",[actor.tenantId]))
	return <div><SettingsHeading title="Amazon integrations" description="SP-API and Amazon Ads authorization status for this company."/><div className="grid gap-4 md:grid-cols-2">{(["sp_api","ads_api"] as const).map(provider => { const item=rows.find(row=>row.provider===provider); const ready=item?.status==="active"; return <SettingsCard key={provider} title={provider==="sp_api"?"Selling Partner API":"Amazon Ads API"} aside={<StatusPill ready={ready}>{item?.status ?? "Not connected"}</StatusPill>}><p className="text-sm text-slate-600">{provider==="sp_api"?"Orders, Sales & Traffic and catalog reporting.":"Advertising profiles, reports and approval-gated actions."}</p><dl className="mt-4 space-y-2 text-xs text-slate-500"><div>Region: <b className="text-slate-700">{item?.region ?? "EU / UK default"}</b></div><div>Last token refresh: <b className="text-slate-700">{item?.last_refresh_at ?? "Never"}</b></div>{item?.last_error ? <div className="tone-bad">{item.last_error}</div>:null}</dl><p className="mt-4 border-t pt-4 text-xs text-slate-500">Credentials are loaded from the server environment; refresh tokens are persisted through the encrypted token vault.</p></SettingsCard>})}</div></div>
}
