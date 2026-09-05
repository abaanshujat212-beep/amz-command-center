import type { ReactNode } from "react"

export function SettingsHeading({ title, description }: { title: string; description: string }) {
	return <div className="mb-6"><h2 className="text-xl font-semibold tracking-tight">{title}</h2><p className="mt-1 text-sm text-slate-500">{description}</p></div>
}

export function SettingsCard({ title, children, aside }: { title: string; children: ReactNode; aside?: ReactNode }) {
	return <div className="rounded-xl border border-slate-200 bg-white p-5 shadow-sm"><div className="mb-4 flex items-start justify-between gap-4"><h3 className="font-semibold">{title}</h3>{aside}</div>{children}</div>
}

export function StatusPill({ ready, children }: { ready: boolean; children: ReactNode }) {
	return <span className={`rounded-full px-2.5 py-1 text-xs font-medium ${ready ? "bg-emerald-50 text-emerald-700" : "bg-slate-100 text-slate-500"}`}>{children}</span>
}
