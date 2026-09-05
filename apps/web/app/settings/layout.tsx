import { SettingsNav } from "@/components/settings-nav"

export default function SettingsLayout({ children }: { children: React.ReactNode }) {
	return <div className="grid gap-6 lg:grid-cols-[240px_minmax(0,1fr)]"><aside className="lg:sticky lg:top-24 lg:self-start"><div className="rounded-xl border border-slate-200 bg-white p-3 shadow-sm"><h1 className="px-3 pb-3 pt-1 text-base font-semibold">Workspace settings</h1><SettingsNav /></div></aside><section className="min-w-0 pb-10">{children}</section></div>
}
