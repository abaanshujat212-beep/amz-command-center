"use client"

import Link from "next/link"
import { isManualInventoryLocationType, MANUAL_INVENTORY_LOCATION_TYPES } from "@/lib/inventory-location-types"
import { useRouter } from "next/navigation"
import { useEffect, useRef, useState, type FormEvent } from "react"

const quantities = [
	["availableQty", "Available now"], ["onHandQty", "On hand"],
	["reservedQty", "Reserved"], ["committedQty", "Committed"],
	["inboundQty", "Inbound"], ["inTransitQty", "In transit"], ["unsellableQty", "Unsellable"],
] as const

type Location = { locationCode: string; locationName: string }

function text(data: FormData, key: string) {
	const value = data.get(key)
	return typeof value === "string" ? value.trim() : ""
}
function utc(value: string, label: string, optional = false) {
	if (!value && optional) return null
	if (!/^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}$/.test(value)) throw new Error(`${label} must include a valid date and time.`)
	const date = new Date(`${value}:00Z`)
	if (!Number.isFinite(date.getTime()) || date.toISOString().slice(0, 16) !== value) throw new Error(`${label} must include a valid date and time.`)
	return date.toISOString()
}

/** Preserve unknown versus zero quantities and the same count identity on retries. */
export function manualInventoryPayload(data: FormData, locations: Location[], now = Date.now()) {
	const locationCode = text(data, "locationCode")
	const locationName = text(data, "locationName")
	const locationType = text(data, "locationType") || "own_warehouse"
	if (!isManualInventoryLocationType(locationType)) throw new Error("Choose a supported local location type.")
	const sku = text(data, "sku")
	const sourceReference = text(data, "sourceReference")
	if (!locationCode || locationCode.length > 100) throw new Error("Enter a location code of at most 100 characters.")
	if (!sku || sku.length > 100) throw new Error("Enter a SKU of at most 100 characters.")
	if (!sourceReference || sourceReference.length > 200) throw new Error("Enter a count reference of at most 200 characters.")
	const knownLocation = locations.some(location => location.locationCode === locationCode)
	if (locationName.length > 200) throw new Error("Location name must be at most 200 characters.")
	const observedAt = utc(text(data, "observedAt"), "Observation time")!
	if (new Date(observedAt).getTime() > now) throw new Error("Observation time cannot be in the future.")
	const freshness = text(data, "freshness") || "current"
	if (!["current", "partial", "unknown"].includes(freshness)) throw new Error("Choose a valid count quality.")
	const values = Object.fromEntries(quantities.map(([key, label]) => {
		const raw = text(data, key)
		if (!raw) return [key, null]
		if (!/^(?:\d+(?:\.\d{1,4})?|\.\d{1,4})$/.test(raw) || !Number.isFinite(Number(raw)) || Number(raw) > 999999999999.9999) {
			throw new Error(`${label} must be a non-negative number with at most four decimal places.`)
		}
		return [key, Number(raw)]
	}))
	return {
		locationCode, ...(!knownLocation && locationName ? { locationName, locationType } : {}), sku, sourceReference, observedAt, freshness,
		...values, expectedAvailableAt: utc(text(data, "expectedAvailableAt"), "Expected availability", true),
	}
}

function countReference() { return `stock-${crypto.randomUUID()}` }
function utcMinute() { return new Date().toISOString().slice(0, 16) }
const field = "w-full rounded border border-slate-300 bg-white px-3 py-2 text-sm disabled:bg-slate-100"

export function ManualInventoryForm({ locations, initialObservedAt }: { locations: Location[]; initialObservedAt: string }) {
	const router = useRouter()
	const form = useRef<HTMLFormElement>(null)
	const submitting = useRef(false)
	const [locationCode, setLocationCode] = useState("")
	const knownLocation = locations.some(location => location.locationCode === locationCode.trim())
	const [reference, setReference] = useState("")
	const [observedAt, setObservedAt] = useState(initialObservedAt.slice(0, 16))
	const [busy, setBusy] = useState(false)
	const [error, setError] = useState("")
	const [success, setSuccess] = useState("")
	const [savedSku, setSavedSku] = useState("")
	useEffect(() => { setReference(countReference()) }, [])

	async function submit(event: FormEvent<HTMLFormElement>) {
		event.preventDefault()
		if (submitting.current || success) return
		submitting.current = true
		setBusy(true)
		setError("")
		try {
			const payload = manualInventoryPayload(new FormData(event.currentTarget), locations)
			const response = await fetch("/api/inventory", { method: "POST", credentials: "same-origin", headers: { "content-type": "application/json" }, body: JSON.stringify(payload) })
			const result = await response.json().catch(() => null)
			if (!response.ok) throw new Error(result?.error || "The count could not be saved. Your entries are unchanged; try again.")
			if (typeof result?.snapshot?.snapshotId !== "string" || typeof result?.snapshot?.inserted !== "boolean") throw new Error("The save could not be confirmed. Retry with the same count reference.")
			setSavedSku(payload.sku)
			setSuccess(result.snapshot.inserted ? "Stock count saved." : "This count was already saved. No duplicate was added.")
			router.refresh()
		} catch (cause) {
			setError(cause instanceof Error ? cause.message : "The count could not be saved. Your entries are unchanged; try again.")
		} finally {
			submitting.current = false
			setBusy(false)
		}
	}
	function startAnother() {
		form.current?.reset()
		setLocationCode("")
		setReference(countReference())
		setObservedAt(utcMinute())
		setError("")
		setSuccess("")
		setSavedSku("")
	}

	return <details className="rounded-lg border bg-white p-4">
		<summary className="cursor-pointer font-semibold">Record a stock count</summary>
		<p className="mt-2 text-sm text-slate-600">Add a manual stock observation. Leave a quantity blank when it is unknown; enter 0 only when you have confirmed there is none.</p>
		<form ref={form} onSubmit={submit} className="mt-4 space-y-4" aria-busy={busy}>
			<fieldset disabled={busy || Boolean(success)} className="space-y-4 disabled:opacity-70"><legend className="sr-only">Stock count details</legend>
			<div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
				<label className="grid gap-1 text-sm">Location code<input className={field} name="locationCode" value={locationCode} onChange={event => setLocationCode(event.target.value)} required maxLength={100} list="inventory-location-codes" autoComplete="off" placeholder="e.g. MAIN-WAREHOUSE" /></label>
				<datalist id="inventory-location-codes">{locations.map(location => <option key={location.locationCode} value={location.locationCode}>{location.locationName}</option>)}</datalist>
				<label className="grid gap-1 text-sm">New location name<input className={field} name="locationName" maxLength={200} placeholder="Required for a new location" aria-describedby="location-name-help" /></label>
				<label className="grid gap-1 text-sm">New location type<select className={field} name="locationType" defaultValue="own_warehouse" disabled={knownLocation} aria-describedby="location-name-help">{MANUAL_INVENTORY_LOCATION_TYPES.map(option => <option key={option.value} value={option.value}>{option.label}</option>)}</select></label>
				<label className="grid gap-1 text-sm">SKU<input className={field} name="sku" required maxLength={100} autoComplete="off" /></label>
			</div>
			<p id="location-name-help" className="text-xs text-slate-500">Name and type apply only when adding a new named location. Existing location codes keep their current name and type. Amazon FBA and AWD locations cannot be created here.</p>
			<div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
				<label className="grid gap-1 text-sm">Count reference<input className={field} name="sourceReference" required maxLength={200} value={reference} onChange={event => setReference(event.target.value)} aria-describedby="count-reference-help" /></label>
				<label className="grid gap-1 text-sm">Observed at (UTC)<input className={field} name="observedAt" type="datetime-local" required value={observedAt} onChange={event => setObservedAt(event.target.value)} /></label>
				<label className="grid gap-1 text-sm">Count quality<select className={field} name="freshness" defaultValue="current"><option value="current">Confirmed observation</option><option value="partial">Partial observation</option><option value="unknown">Unverified observation</option></select></label>
			</div>
			<p id="count-reference-help" className="text-xs text-slate-500">Keep the same reference and observation time when retrying this count. Start another count for a new observation.</p>
			<div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">{quantities.map(([key, label]) => <label key={key} className="grid gap-1 text-sm">{label}<input className={field} name={key} type="number" min="0" max="999999999999.9999" step="0.0001" placeholder="Unknown" /></label>)}
			<label className="grid gap-1 text-sm">Expected availability (UTC)<input className={field} name="expectedAvailableAt" type="datetime-local" /></label></div>
			<p className="text-xs text-slate-500">Inbound and in-transit units do not increase stock available now. Expected availability is a future estimate, not a receipt.</p>
			</fieldset>
			{error && <p role="alert" className="rounded bg-red-50 p-3 text-sm text-red-800">{error}</p>}
			{success && <div role="status" className="rounded bg-green-50 p-3 text-sm text-green-800"><p>{success}</p><Link href={`/inventory?sku=${encodeURIComponent(savedSku)}`} className="mt-1 inline-block underline">View this SKU</Link></div>}
			<div className="flex flex-wrap items-center gap-3"><button type="submit" disabled={busy || Boolean(success) || !reference} className="rounded bg-slate-900 px-4 py-2 text-sm text-white disabled:opacity-50">{busy ? "Saving…" : "Save stock count"}</button>{success && <button type="button" onClick={startAnother} className="rounded border px-4 py-2 text-sm">Start another count</button>}</div>
		</form>
	</details>
}
