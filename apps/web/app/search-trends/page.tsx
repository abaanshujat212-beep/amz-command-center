import { SearchIntelligenceNav } from "@/components/search-intelligence-nav"

export default function SearchTrends() {
	return <div className="space-y-6">
		<SearchIntelligenceNav active="/search-trends" />
		<div><h1 className="text-lg font-semibold">Market search trends</h1><p className="text-sm text-slate-600">Market-wide demand estimates are kept separate from your Amazon account observations.</p></div>
		<section className="rounded-lg border border-amber-200 bg-amber-50 p-5">
			<div className="text-sm font-semibold text-amber-950">External market source not configured</div>
			<p className="mt-2 max-w-3xl text-sm text-amber-900">No approved market-trend provider is connected for this tenant, so there are no market volume, growth or seasonality estimates to show. Ads Search Terms and SQP remain available in their own views and are never relabelled as market trends.</p>
		</section>
		<div className="grid gap-3 text-sm sm:grid-cols-3">
			<div className="rounded-lg border bg-white p-4"><b>Required source</b><p className="mt-1 text-slate-600">An approved market-data provider with tenant entitlement.</p></div>
			<div className="rounded-lg border bg-white p-4"><b>Required evidence</b><p className="mt-1 text-slate-600">Provider, geography, time window, grain, capture time and freshness.</p></div>
			<div className="rounded-lg border bg-white p-4"><b>Safety boundary</b><p className="mt-1 text-slate-600">Unsupported estimates stay unavailable; this page does not infer them from PPC or SQP.</p></div>
		</div>
	</div>
}
