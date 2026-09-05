import type { Metadata } from "next"
import Link from "next/link"
import "./globals.css"
import { withTenant } from "@/lib/db"
import { automationState, dataFreshness, tenantIdentity } from "@/lib/queries"
import { currentTenantId } from "@/lib/session"
import { AccountMenu } from "@/components/account-menu"

export const metadata: Metadata = {
	title: "AXATY Command Center",
	description: "Amazon PPC and product analytics",
}

// Never cache: these pages exist to show the current state of a live account.
export const dynamic = "force-dynamic"

async function StatusBar() {
	let armed = false
	let dryRun = true
	let stalest: { dataset: string; hours: number } | null = null
	let tenant: Awaited<ReturnType<typeof tenantIdentity>> = null

	try {
		const tenantId = await currentTenantId()
		const result = await withTenant(tenantId, async (c) => ({
			settings: await automationState(c),
			freshness: await dataFreshness(c),
			tenant: await tenantIdentity(c),
		}))
		const { settings, freshness } = result
		tenant = result.tenant
		armed = settings?.automation_enabled ?? false
		dryRun = settings?.dry_run ?? true
		for (const f of freshness) {
			if (f.hours_old === null) continue
			if (stalest === null || f.hours_old > stalest.hours) {
				stalest = { dataset: f.dataset, hours: f.hours_old }
			}
		}
	} catch {
		// The status bar must not take the whole page down with it.
		return (
			<span className="text-slate-400">status unavailable</span>
		)
	}

	const stale = stalest !== null && stalest.hours > 48

	return (
		<div className="flex items-center gap-4 text-xs">
			{tenant && (
				<div className="hidden text-right sm:block">
					<div className="font-medium text-slate-800">{tenant.name}</div>
					<div className="text-slate-500">
						{tenant.profile_id
							? `${tenant.country_code ?? "Amazon"} profile ${tenant.profile_id}`
							: "Amazon profile pending"}
					</div>
				</div>
			)}
			<span
				className={
					armed && !dryRun
						? "rounded bg-bad px-2 py-1 font-medium text-white"
						: "rounded bg-slate-200 px-2 py-1 text-slate-700"
				}
			>
				{armed && !dryRun ? "automation ARMED" : "dry run"}
			</span>
			{stalest !== null && (
				<span className={stale ? "tone-bad" : "text-slate-500"}>
					data {stalest.hours}h old ({stalest.dataset})
				</span>
			)}
			<AccountMenu />
		</div>
	)
}

export default function RootLayout({
	children,
}: {
	children: React.ReactNode
}) {
	return (
		<html lang="en">
			<body>
				<header className="border-b border-slate-200 bg-white">
					<div className="mx-auto flex max-w-7xl items-center justify-between px-6 py-3">
						<nav className="flex items-center gap-6 text-sm">
							<span className="font-semibold">AXATY</span>
							<Link href="/" className="hover:underline">
								Command Center
							</Link>
							<Link href="/search-terms" className="hover:underline">
								Search terms
							</Link>
							<Link href="/opportunities" className="hover:underline">Products</Link>
							<Link href="/sqp" className="hover:underline">SQP</Link>
							<Link href="/economics" className="hover:underline">Economics</Link>
							<Link href="/approvals" className="hover:underline">
								Approvals
							</Link>
							<Link href="/history" className="hover:underline">
								History
							</Link>
							<Link href="/settings/members" className="hover:underline">Team</Link>
							<Link href="/settings/client" className="hover:underline">Settings</Link>
						</nav>
						<StatusBar />
					</div>
				</header>
				<main className="mx-auto max-w-7xl px-6 py-8">{children}</main>
			</body>
		</html>
	)
}
