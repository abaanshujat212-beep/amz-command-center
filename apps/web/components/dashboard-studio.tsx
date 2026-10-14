"use client"

import Link from "next/link"
import { useRouter } from "next/navigation"
import { useMemo, useState } from "react"
import type { DashboardDefinition, DashboardFilter, DashboardRow, DashboardWidget } from "@/lib/dashboard-studio"
import type { DecisionOverlay, StudioData, WidgetData } from "@/lib/dashboard-studio-view"
import { count, money, percent, stamp } from "@/lib/format"

type Template = { template_key: string; name: string; description: string | null; current_version: number; definition: DashboardDefinition }
type Props = { dashboards: DashboardRow[]; templates: Template[]; selected: DashboardRow | null; data: StudioData | null; compareData: StudioData | null; actorRole: string }
type WidgetSpec = { type: DashboardWidget["type"]; query: string; title: string; description: string; width: number; height: number }

const CATALOG: WidgetSpec[] = [
	{ type: "scorecard", query: "dashboard.summary", title: "Account summary", description: "Spend, sales, ACOS and orders.", width: 12, height: 3 },
	{ type: "table", query: "campaign.performance", title: "Campaign performance", description: "Settled campaign metrics only.", width: 7, height: 6 },
	{ type: "table", query: "search_terms.performance", title: "Search terms", description: "Search-query efficiency and outcomes.", width: 5, height: 6 },
	{ type: "bar", query: "product.economics", title: "Product profit", description: "Economics-backed sales and contribution.", width: 6, height: 6 },
	{ type: "table", query: "sqp.opportunities", title: "SQP opportunities", description: "Ranked query opportunities and suggested action.", width: 6, height: 6 },
	{ type: "timeseries", query: "pipeline.health", title: "Pipeline health", description: "Recent ingest and transformation evidence.", width: 12, height: 5 },
]

const STARTERS: Template[] = [
	{ template_key: "executive", name: "Executive", description: "Account pulse, product profit and pipeline evidence.", current_version: 1, definition: { schemaVersion: 1, widgets: [widget(CATALOG[0], "summary", 0, 0), widget(CATALOG[3], "profit", 0, 3), widget(CATALOG[5], "health", 6, 3)], globalFilters: dateFilter(30) } },
	{ template_key: "ppc", name: "PPC", description: "Campaign, search-term and SQP performance.", current_version: 1, definition: { schemaVersion: 1, widgets: [widget(CATALOG[0], "summary", 0, 0), widget(CATALOG[1], "campaigns", 0, 3), widget(CATALOG[2], "terms", 7, 3), widget(CATALOG[4], "sqp", 0, 9)], globalFilters: dateFilter(30) } },
	{ template_key: "profit", name: "Profit", description: "Product economics with account context.", current_version: 1, definition: { schemaVersion: 1, widgets: [widget(CATALOG[0], "summary", 0, 0), widget(CATALOG[3], "profit", 0, 3)], globalFilters: dateFilter(30) } },
	{ template_key: "inventory", name: "Inventory readiness", description: "Pipeline evidence and product rows; unavailable inventory remains explicit.", current_version: 1, definition: { schemaVersion: 1, widgets: [widget(CATALOG[5], "inventory_health", 0, 0), widget(CATALOG[3], "inventory_products", 0, 5)], globalFilters: dateFilter(30) } },
]
const WIDTH_CLASS: Record<number, string> = { 1: "md:col-span-1", 2: "md:col-span-2", 3: "md:col-span-3", 4: "md:col-span-4", 5: "md:col-span-5", 6: "md:col-span-6", 7: "md:col-span-7", 8: "md:col-span-8", 9: "md:col-span-9", 10: "md:col-span-10", 11: "md:col-span-11", 12: "md:col-span-12" }

function dateFilter(days: number): DashboardFilter[] { return [{ field: "dateRange", operator: "between", value: [`P${days}D`, "P0D"] }] }
function widget(spec: WidgetSpec, id: string, x: number, y: number): DashboardWidget { return { id, type: spec.type, query: spec.query, title: spec.title, layout: { x, y, w: spec.width, h: spec.height } } }
function rows(payload: WidgetData | undefined): Record<string, unknown>[] { return Array.isArray(payload?.rows) ? payload.rows as Record<string, unknown>[] : [] }
function number(value: unknown): number | null { const n = Number(value); return value !== null && value !== "" && Number.isFinite(n) ? n : null }
function label(value: string) { return value.replaceAll("_", " ").replace(/\b\w/g, part => part.toUpperCase()) }
function display(key: string, value: unknown) {
	if (value === null || value === undefined) return "—"
	if (["cost", "sales", "ad_spend", "ad_sales", "total_sales", "gross_profit_est", "cpc"].includes(key)) return money(number(value))
	if (["acos", "roas", "ctr", "cvr", "tacos", "break_even_acos", "contribution_margin_pct", "sqp_opportunity_score"].includes(key)) return percent(number(value))
	if (typeof value === "number") return count(value)
	if (typeof value === "boolean") return value ? "Yes" : "No"
	return String(value)
}

function Empty({ children }: { children: React.ReactNode }) { return <div className="grid min-h-36 place-items-center rounded-lg border border-dashed border-slate-300 bg-slate-50 p-6 text-center text-sm text-slate-500">{children}</div> }

function DecisionLinks({ decisions, entityIds }: { decisions: DecisionOverlay[]; entityIds: string[] }) {
	const matches = decisions.filter(decision => entityIds.length === 0 || entityIds.includes(decision.entity_id)).slice(0, 3)
	if (!matches.length) return null
	return <div className="mt-3 border-t border-slate-100 pt-3"><p className="text-[11px] font-semibold uppercase tracking-wide text-slate-400">Decision evidence</p><div className="mt-2 flex flex-wrap gap-2">{matches.map(decision => <Link key={decision.id} href={`/copilot?action=${encodeURIComponent(decision.id)}`} className="rounded-full border border-blue-200 bg-blue-50 px-2 py-1 text-xs text-blue-700 hover:bg-blue-100">{decision.action_type} · {decision.status}</Link>)}</div></div>
}

function Scorecards({ payload, compare }: { payload?: WidgetData; compare?: WidgetData }) {
	const total = payload?.total as Record<string, unknown> | null | undefined
	const other = compare?.total as Record<string, unknown> | null | undefined
	if (!total) return <Empty>No settled account totals in this window.</Empty>
	const metrics: [string, string, (value: number | null) => string][] = [["cost", "Ad spend", money], ["sales", "Ad sales", money], ["acos", "ACOS", percent], ["orders", "Orders", value => count(value)]]
	return <div className="grid grid-cols-2 gap-3 lg:grid-cols-4">{metrics.map(([key, title, formatter]) => { const current = number(total[key]), previous = number(other?.[key]); const delta = current !== null && previous !== null ? current - previous : null; return <div key={key} className="rounded-lg bg-slate-50 p-3"><div className="text-xs text-slate-500">{title}</div><div className="mt-1 text-xl font-semibold tabular-nums">{formatter(current)}</div>{other && <div className={`mt-1 text-xs tabular-nums ${delta !== null && delta > 0 ? "text-blue-700" : "text-slate-500"}`}>{delta === null ? "No comparison" : `${delta > 0 ? "+" : ""}${formatter(delta)} vs compare`}</div>}</div> })}</div>
}

function DataTable({ queryKey, payload, compare }: { queryKey: string; payload?: WidgetData; compare?: WidgetData }) {
	const data = rows(payload)
	if (!data.length) return <Empty>No persisted rows match this widget and its filters.</Empty>
	const priorities: Record<string, string[]> = {
		"campaign.performance": ["campaign_name", "campaign_status", "cost", "sales", "acos", "orders"],
		"search_terms.performance": ["search_term", "cost", "sales", "acos", "orders", "exists_as_exact"],
		"product.economics": ["asin", "sku", "total_sales", "ad_spend", "tacos", "gross_profit_est"],
		"sqp.opportunities": ["search_query", "asin", "query_volume_30d", "query_ctr", "query_cvr", "suggested_action"],
		"pipeline.health": ["dataset", "status", "started_at", "rows_loaded", "error"],
	}
	const columns = (priorities[queryKey] ?? Object.keys(data[0])).filter(key => key in data[0]).slice(0, 6)
	const compareCount = rows(compare).length
	return <div className="overflow-x-auto"><table className="w-full min-w-[560px] text-sm"><caption className="sr-only">{label(queryKey)} data</caption><thead><tr className="border-b text-left text-[11px] uppercase tracking-wide text-slate-400">{columns.map(column => <th scope="col" className="px-2 py-2" key={column}>{label(column)}</th>)}</tr></thead><tbody>{data.slice(0, 8).map((row, index) => <tr className="border-b border-slate-100" key={`${String(row.id ?? row.asin ?? row.campaign_id ?? row.search_term ?? row.dataset)}:${index}`}>{columns.map(column => <td className="max-w-52 truncate px-2 py-2 tabular-nums" title={String(row[column] ?? "")} key={column}>{display(column, row[column])}</td>)}</tr>)}</tbody></table>{compare && <p className="mt-2 text-xs text-slate-500">Comparison window contains {compareCount} matching row{compareCount === 1 ? "" : "s"}; current window contains {data.length}.</p>}</div>
}

function Bars({ payload }: { payload?: WidgetData }) {
	const data = rows(payload).slice(0, 8)
	if (!data.length) return <Empty>No persisted product economics rows match this widget.</Empty>
	const maximum = Math.max(...data.map(row => number(row.total_sales ?? row.sales ?? row.query_volume_30d) ?? 0), 1)
	return <ul className="space-y-3" aria-label="Ranked product values">{data.map((row, index) => { const raw = number(row.total_sales ?? row.sales ?? row.query_volume_30d) ?? 0; return <li key={`${String(row.asin ?? row.search_query)}:${index}`}><div className="mb-1 flex justify-between gap-3 text-xs"><span className="truncate">{String(row.sku ?? row.asin ?? row.search_query ?? "Unknown")}</span><span className="tabular-nums">{money(raw)}</span></div><div className="h-2 rounded bg-slate-100"><div className="h-2 rounded bg-blue-600" style={{ width: `${Math.max(2, raw / maximum * 100)}%` }}/></div></li> })}</ul>
}

function WidgetView({ widget, data, compareData }: { widget: DashboardWidget; data: StudioData; compareData: StudioData | null }) {
	const payload = data.widgets[widget.query], compare = compareData?.widgets[widget.query]
	if (widget.type === "scorecard") return <Scorecards payload={payload} compare={compare}/>
	if (widget.type === "bar") return <Bars payload={payload}/>
	return <DataTable queryKey={widget.query} payload={payload} compare={compare}/>
}

export function DashboardStudio({ dashboards, templates, selected, data, compareData, actorRole }: Props) {
	const router = useRouter()
	const [definition, setDefinition] = useState<DashboardDefinition | null>(selected?.definition ?? null)
	const [editing, setEditing] = useState(false)
	const [busy, setBusy] = useState(false)
	const [message, setMessage] = useState("")
	const [newName, setNewName] = useState("")
	const [starterKey, setStarterKey] = useState("executive")
	const [filterField, setFilterField] = useState("campaignId")
	const [filterValue, setFilterValue] = useState("")
	const allTemplates = useMemo(() => [...STARTERS, ...templates.filter(template => !STARTERS.some(item => item.template_key === template.template_key))], [templates])
	const canEdit = actorRole !== "viewer"

	async function request(url: string, init: RequestInit) {
		setBusy(true); setMessage("")
		try { const response = await fetch(url, { ...init, headers: { "content-type": "application/json", ...(init.headers ?? {}) } }); const body = await response.json(); if (!response.ok) throw new Error(body.error ?? "Request failed"); return body }
		catch (error) { setMessage(error instanceof Error ? error.message : "Request failed"); throw error }
		finally { setBusy(false) }
	}

	async function create() {
		const template = allTemplates.find(item => item.template_key === starterKey) ?? STARTERS[0]
		if (!newName.trim()) { setMessage("Give the dashboard a name."); return }
		try { const body = await request("/api/dashboards", { method: "POST", body: JSON.stringify({ name: newName, visibility: "private", definition: template.definition }) }); router.push(`/dashboard-studio?dashboard=${body.dashboard.id}`); router.refresh() } catch {}
	}
	async function save() {
		if (!selected || !definition) return
		try { await request(`/api/dashboards/${selected.id}`, { method: "PATCH", body: JSON.stringify({ definition, changeSummary: "Updated in Dashboard Studio" }) }); setEditing(false); setMessage("Dashboard layout saved as a new version."); router.refresh() } catch {}
	}
	function changeWidget(id: string, operation: "left" | "right" | "up" | "down" | "wider" | "narrower" | "taller" | "shorter") {
		if (!definition) return
		setDefinition({ ...definition, widgets: definition.widgets.map(item => { if (item.id !== id) return item; const l = item.layout; const next = { ...l }; if (operation === "left") next.x = Math.max(0, l.x - 1); if (operation === "right") next.x = Math.min(12 - l.w, l.x + 1); if (operation === "up") next.y = Math.max(0, l.y - 1); if (operation === "down") next.y = l.y + 1; if (operation === "wider") next.w = Math.min(12 - l.x, l.w + 1); if (operation === "narrower") next.w = Math.max(1, l.w - 1); if (operation === "taller") next.h = Math.min(20, l.h + 1); if (operation === "shorter") next.h = Math.max(1, l.h - 1); return { ...item, layout: next } }) })
	}
	function addWidget(spec: WidgetSpec) { if (!definition) return; const id = `${spec.query.split(".")[0]}_${Date.now()}`; const bottom = definition.widgets.reduce((max, item) => Math.max(max, item.layout.y + item.layout.h), 0); setDefinition({ ...definition, widgets: [...definition.widgets, widget(spec, id, 0, bottom)] }) }
	function setDays(days: number) { if (!definition) return; setDefinition({ ...definition, globalFilters: [...(definition.globalFilters ?? []).filter(item => item.field !== "dateRange"), ...dateFilter(days)] }) }
	function addFilter() { if (!definition || !filterValue.trim()) return; const next = (definition.globalFilters ?? []).filter(item => item.field !== filterField); setDefinition({ ...definition, globalFilters: [...next, { field: filterField, operator: "eq", value: filterValue.trim() }] }); setFilterValue("") }

	if (!selected || !definition || !data) return <div className="space-y-6"><header><h1 className="text-xl font-semibold">Dashboard Studio</h1><p className="mt-1 text-sm text-slate-600">Build a safe dashboard from approved widget contracts. Calculations remain in governed queries.</p></header><section className="rounded-xl border bg-white p-6"><h2 className="font-semibold">Create your first dashboard</h2><p className="mt-1 text-sm text-slate-500">Choose an operator-focused starting point. You can rearrange it after creation.</p><CreateControls templates={allTemplates} name={newName} setName={setNewName} templateKey={starterKey} setTemplateKey={setStarterKey} create={create} busy={busy}/>{message && <p role="alert" className="mt-3 text-sm text-bad">{message}</p>}</section></div>

	const ordered = [...definition.widgets].sort((a, b) => a.layout.y - b.layout.y || a.layout.x - b.layout.x)
	return <div className="space-y-5">
		<header className="flex flex-wrap items-start justify-between gap-4"><div><div className="flex flex-wrap items-center gap-2"><h1 className="text-xl font-semibold">Dashboard Studio</h1><span className="rounded bg-emerald-50 px-2 py-1 text-xs font-medium text-emerald-700">safe queries only</span></div><p className="mt-1 text-sm text-slate-600">Responsive analytics canvas backed by saved, versioned definitions.</p></div><div className="flex flex-wrap gap-2">{canEdit && <button type="button" onClick={() => setEditing(value => !value)} className="rounded-lg border bg-white px-3 py-2 text-sm hover:bg-slate-50">{editing ? "Close editor" : "Edit layout"}</button>}{editing && <button type="button" disabled={busy} onClick={save} className="rounded-lg bg-slate-900 px-3 py-2 text-sm text-white disabled:opacity-50">Save version</button>}</div></header>
		<div className="grid gap-3 rounded-xl border bg-white p-4 lg:grid-cols-[1fr_auto_auto]"><label className="text-sm"><span className="mb-1 block text-xs font-medium text-slate-500">Saved dashboard</span><select value={selected.id} onChange={event => router.push(`/dashboard-studio?dashboard=${event.target.value}`)} className="w-full rounded-lg border px-3 py-2">{dashboards.map(item => <option key={item.id} value={item.id}>{item.name}{item.is_default ? " · default" : ""}</option>)}</select></label><label className="text-sm"><span className="mb-1 block text-xs font-medium text-slate-500">Current window</span><select value={data.days} disabled={!editing} onChange={event => setDays(Number(event.target.value))} className="w-full rounded-lg border px-3 py-2 disabled:bg-slate-50">{[7,14,30,60,90].map(days => <option value={days} key={days}>Last {days} days</option>)}</select></label><label className="text-sm"><span className="mb-1 block text-xs font-medium text-slate-500">Compare mode</span><select value={compareData?.days ?? ""} onChange={event => router.push(`/dashboard-studio?dashboard=${selected.id}${event.target.value ? `&compare=${event.target.value}` : ""}`)} className="w-full rounded-lg border px-3 py-2"><option value="">Off</option>{[7,14,30,60,90].filter(days => days !== data.days).map(days => <option value={days} key={days}>Compare last {days} days</option>)}</select></label></div>
		{compareData && <div className="rounded-lg border border-blue-200 bg-blue-50 px-4 py-3 text-sm text-blue-900">Compare mode shows the same governed widgets for trailing {data.days}-day and {compareData.days}-day windows. It does not imply causation.</div>}
		{editing && <aside className="space-y-5 rounded-xl border border-slate-200 bg-white p-4"><div><h2 className="font-semibold">Widget catalog</h2><p className="text-xs text-slate-500">Only allowlisted data contracts can be added. Use keyboard-accessible controls on each widget to move or resize it.</p><div className="mt-3 grid gap-2 sm:grid-cols-2 lg:grid-cols-3">{CATALOG.map(spec => <button type="button" key={spec.query} onClick={() => addWidget(spec)} className="rounded-lg border p-3 text-left hover:border-blue-300 hover:bg-blue-50"><span className="block text-sm font-medium">+ {spec.title}</span><span className="text-xs text-slate-500">{spec.description}</span></button>)}</div></div><div className="border-t pt-4"><h2 className="font-semibold">Validated filters</h2><p className="text-xs text-slate-500">Filters are stored only through the server allowlist; free-form SQL is never accepted.</p><div className="mt-3 grid gap-2 sm:grid-cols-[180px_1fr_auto]"><select aria-label="Filter field" value={filterField} onChange={event => setFilterField(event.target.value)} className="rounded-lg border px-3 py-2 text-sm">{["campaignId", "asin", "sku", "status"].map(field => <option key={field} value={field}>{label(field)}</option>)}</select><input aria-label="Filter value" value={filterValue} onChange={event => setFilterValue(event.target.value)} className="rounded-lg border px-3 py-2 text-sm" placeholder="Exact value"/><button type="button" onClick={addFilter} className="rounded-lg border px-3 py-2 text-sm">Add filter</button></div><div className="mt-3 flex flex-wrap gap-2">{(definition.globalFilters ?? []).filter(item => item.field !== "dateRange").map(item => <button type="button" key={item.field} onClick={() => setDefinition({ ...definition, globalFilters: (definition.globalFilters ?? []).filter(filter => filter !== item) })} className="rounded-full bg-slate-100 px-3 py-1 text-xs text-slate-700" aria-label={`Remove ${item.field} filter`}>{label(item.field)} = {String(item.value)} ×</button>)}</div></div></aside>}
		<div className="grid grid-cols-1 gap-4 md:grid-cols-12" aria-label={`${selected.name} dashboard canvas`}>{ordered.length === 0 ? <div className="md:col-span-12"><Empty>This layout has no widgets. Open the editor and add one from the safe catalog.</Empty></div> : ordered.map(item => { const entityIds = rows(data.widgets[item.query]).flatMap(row => [row.entity_id, row.campaign_id, row.asin, row.search_term]).filter((value): value is string => typeof value === "string"); return <section key={item.id} style={{ minHeight: `${Math.max(12, item.layout.h * 3)}rem` }} className={`${WIDTH_CLASS[item.layout.w] ?? "md:col-span-12"} min-w-0 rounded-xl border border-slate-200 bg-white p-4 shadow-sm`}><div className="mb-4 flex flex-wrap items-start justify-between gap-2"><div><h2 className="font-semibold">{item.title ?? label(item.query)}</h2><p className="text-xs text-slate-500">{item.query} · {data.days} days</p></div>{editing && <WidgetControls widget={item} change={changeWidget} remove={() => setDefinition({ ...definition, widgets: definition.widgets.filter(widget => widget.id !== item.id) })}/>}</div><WidgetView widget={item} data={data} compareData={compareData}/><DecisionLinks decisions={data.decisions} entityIds={entityIds}/></section> })}</div>
		{editing && <section className="rounded-xl border bg-white p-4"><h2 className="font-semibold">Create another layout</h2><CreateControls templates={allTemplates} name={newName} setName={setNewName} templateKey={starterKey} setTemplateKey={setStarterKey} create={create} busy={busy}/></section>}
		<div aria-live="polite" className={`text-sm ${message.includes("saved") ? "text-emerald-700" : "text-bad"}`}>{message}</div>
	</div>
}

function WidgetControls({ widget, change, remove }: { widget: DashboardWidget; change: (id: string, operation: "left" | "right" | "up" | "down" | "wider" | "narrower" | "taller" | "shorter") => void; remove: () => void }) {
	return <div className="flex flex-wrap justify-end gap-1" role="group" aria-label={`Arrange ${widget.title ?? widget.query}`}><button className="rounded border px-2 py-1 text-xs" onClick={() => change(widget.id, "left")} aria-label="Move left">←</button><button className="rounded border px-2 py-1 text-xs" onClick={() => change(widget.id, "right")} aria-label="Move right">→</button><button className="rounded border px-2 py-1 text-xs" onClick={() => change(widget.id, "up")} aria-label="Move up">↑</button><button className="rounded border px-2 py-1 text-xs" onClick={() => change(widget.id, "down")} aria-label="Move down">↓</button><button className="rounded border px-2 py-1 text-xs" onClick={() => change(widget.id, "narrower")} aria-label="Make narrower">− width</button><button className="rounded border px-2 py-1 text-xs" onClick={() => change(widget.id, "wider")} aria-label="Make wider">+ width</button><button className="rounded border px-2 py-1 text-xs" onClick={() => change(widget.id, "shorter")} aria-label="Make shorter">− height</button><button className="rounded border px-2 py-1 text-xs" onClick={() => change(widget.id, "taller")} aria-label="Make taller">+ height</button><button className="rounded border border-red-200 px-2 py-1 text-xs text-red-700" onClick={remove}>Remove</button></div>
}

function CreateControls({ templates, name, setName, templateKey, setTemplateKey, create, busy }: { templates: Template[]; name: string; setName: (value: string) => void; templateKey: string; setTemplateKey: (value: string) => void; create: () => void; busy: boolean }) {
	return <div className="mt-4 grid gap-3 md:grid-cols-[1fr_1fr_auto]"><label className="text-sm"><span className="sr-only">Dashboard name</span><input value={name} maxLength={120} onChange={event => setName(event.target.value)} placeholder="Dashboard name" className="w-full rounded-lg border px-3 py-2"/></label><label className="text-sm"><span className="sr-only">Starter template</span><select value={templateKey} onChange={event => setTemplateKey(event.target.value)} className="w-full rounded-lg border px-3 py-2">{templates.map(template => <option key={`${template.template_key}:${template.current_version}`} value={template.template_key}>{template.name} — {template.description}</option>)}</select></label><button type="button" disabled={busy} onClick={create} className="rounded-lg bg-blue-600 px-4 py-2 text-sm font-medium text-white disabled:opacity-50">Create dashboard</button></div>
}
