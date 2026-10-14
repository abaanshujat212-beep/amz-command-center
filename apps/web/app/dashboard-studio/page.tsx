import { DashboardStudio } from "@/components/dashboard-studio"
import { listDashboards, listDashboardTemplates, type DashboardRow } from "@/lib/dashboard-studio"
import { loadStudioData } from "@/lib/dashboard-studio-view"
import { withTenantActor } from "@/lib/db"
import { currentContext } from "@/lib/session"

export const dynamic = "force-dynamic"

export default async function DashboardStudioPage({ searchParams }: { searchParams: Promise<{ dashboard?: string; compare?: string }> }) {
	const params = await searchParams
	const actor = await currentContext()
	const result = await withTenantActor(actor.tenantId, actor.userId, actor.role, async client => {
		const dashboards = await listDashboards(client, actor.userId) as DashboardRow[]
		const templates = await listDashboardTemplates(client)
		const selected = dashboards.find(row => row.id === params.dashboard) ?? dashboards[0] ?? null
		const compare = params.compare ? Number(params.compare) : null
		return {
			dashboards,
			templates,
			selected,
			data: selected ? await loadStudioData(client, selected.definition, 30) : null,
			compareData: selected && [7, 14, 30, 60, 90].includes(compare ?? 0) ? await loadStudioData(client, { ...selected.definition, globalFilters: [{ field: "dateRange", operator: "between", value: [`P${compare}D`, "P0D"] }] }, compare!) : null,
		}
	})
	return <DashboardStudio {...result} actorRole={actor.role}/>
}
