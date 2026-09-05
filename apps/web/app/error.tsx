"use client"

import Link from "next/link"
import { useEffect } from "react"

export default function DashboardError({ error, reset }: { error: Error & { digest?: string }; reset: () => void }) {
	useEffect(() => { console.error(error) }, [error])
	return <div className="rounded-lg border border-amber-200 bg-white p-8"><h1 className="text-lg font-semibold">Dashboard data is temporarily unavailable</h1><p className="mt-2 max-w-2xl text-sm text-slate-600">The account setup or analytics pipeline may not have finished yet. No Amazon action was attempted.</p><div className="mt-4 flex gap-3"><button onClick={reset} className="rounded bg-slate-900 px-3 py-2 text-sm text-white">Try again</button><Link href="/history" className="rounded border px-3 py-2 text-sm">Check pipeline history</Link></div>{error.digest && <p className="mt-4 text-xs text-slate-400">Reference: {error.digest}</p>}</div>
}
