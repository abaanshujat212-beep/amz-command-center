import { SettingsNav } from "@/components/settings-nav"

export default function SettingsLayout({ children }: { children: React.ReactNode }) {
	return <div className="grid gap-6 lg:grid-cols-[220px_minmax(0,1fr)]"><aside><div className="rounded-xl border border-slate-200 bg-white p-3"><h1 className="px-3 pb-3 pt-1 text-base font-semibold">Settings</h1><SettingsNav /></div></aside><section className="min-w-0">{children}</section></div>
}
