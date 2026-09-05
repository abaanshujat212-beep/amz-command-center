import { currentContext } from "@/lib/session"
import { SettingsCard, SettingsHeading } from "@/components/settings-ui"

export default async function ProfileSettingsPage() {
	const actor = await currentContext()
	return <div><SettingsHeading title="My profile" description="Your account identity and access for this tenant."/><SettingsCard title="Personal details"><dl className="grid gap-5 sm:grid-cols-2"><div><dt className="text-xs font-medium uppercase tracking-wide text-slate-400">Name</dt><dd className="mt-1 text-sm font-medium">{actor.user.name}</dd></div><div><dt className="text-xs font-medium uppercase tracking-wide text-slate-400">Email</dt><dd className="mt-1 text-sm font-medium">{actor.user.email}</dd></div><div><dt className="text-xs font-medium uppercase tracking-wide text-slate-400">Tenant role</dt><dd className="mt-1 text-sm capitalize">{actor.role}</dd></div><div><dt className="text-xs font-medium uppercase tracking-wide text-slate-400">User ID</dt><dd className="mt-1 break-all font-mono text-xs text-slate-500">{actor.userId}</dd></div></dl><p className="mt-6 border-t pt-4 text-xs text-slate-500">Profile editing and password changes will use the authentication provider when account self-service is enabled.</p></SettingsCard></div>
}
