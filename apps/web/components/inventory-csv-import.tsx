"use client"

import { useRouter } from "next/navigation"
import { useEffect, useRef, useState } from "react"

export const INVENTORY_CSV_TEMPLATE = "locationCode,locationName,sku,sourceReference,observedAt,freshness,currency,availableQty,onHandQty,reservedQty,committedQty,inboundQty,inTransitQty,unsellableQty,expectedAvailableAt\n"
export const MAX_INVENTORY_CSV_BYTES = 128 * 1024

type PreviewRow = { rowNumber: number; valid: boolean; errors: string[]; values: Record<string, unknown> | null }
type Preview = { valid: boolean; totalRows: number; validRows: number; errorRows: number; rows: PreviewRow[] }
type RowError = { rowNumber: number; errors: string[] }
function record(value: unknown): value is Record<string, unknown> { return value !== null && typeof value === "object" && !Array.isArray(value) }
function count(value: unknown): value is number { return typeof value === "number" && Number.isSafeInteger(value) && value >= 0 }
export function inventoryCsvText(csv: string) {
	if (!csv.trim()) throw new Error("Choose a CSV file or paste your stock counts first.")
	if (new TextEncoder().encode(csv).byteLength > MAX_INVENTORY_CSV_BYTES) throw new Error("CSV must be at most 128 KiB. Split larger files into smaller batches.")
	return csv
}
export function inventoryCsvPreview(value: unknown, mode = "preview"): Preview {
	if (!record(value) || value.mode !== mode || typeof value.valid !== "boolean" || !count(value.totalRows) || value.totalRows < 1 || value.totalRows > 100 || !count(value.validRows) || !count(value.errorRows) || !Array.isArray(value.rows) || value.rows.length !== value.totalRows) throw new Error("The preview could not be verified. Please preview the CSV again.")
	const rows = value.rows.map(row => {
		if (!record(row) || !count(row.rowNumber) || row.rowNumber < 2 || typeof row.valid !== "boolean" || !Array.isArray(row.errors) || !row.errors.every(error => typeof error === "string") || (row.values !== null && !record(row.values))) throw new Error("The preview could not be verified. Please preview the CSV again.")
		const values = record(row.values) ? row.values : null
		if (!row.valid && row.errors.length === 0) throw new Error("The preview contains an unexplained row error. Please preview the CSV again.")
		if (row.valid && (row.errors.length || !values || !["locationCode", "sku", "sourceReference", "observedAt"].every(key => typeof values[key] === "string" && String(values[key]).trim()))) throw new Error("The preview contains incomplete rows. Please preview the CSV again.")
		return row as PreviewRow
	})
	const validRows = rows.filter(row => row.valid).length
	if (new Set(rows.map(row => row.rowNumber)).size !== rows.length || validRows !== value.validRows || rows.length - validRows !== value.errorRows || value.valid !== (validRows === rows.length)) throw new Error("The preview counts do not match its rows. Please preview the CSV again.")
	return { valid: value.valid, totalRows: value.totalRows, validRows, errorRows: value.errorRows, rows }
}
export function inventoryCsvCommitCounts(value: unknown, expected: number) {
	if (!record(value) || value.mode !== "commit" || value.totalRows !== expected || !count(value.inserted) || !count(value.unchanged) || value.inserted + value.unchanged !== expected) throw new Error("The import result could not be confirmed. Retry the same CSV to check which counts were saved.")
	return { totalRows: expected, inserted: value.inserted, unchanged: value.unchanged }
}
function serverRowErrors(value: unknown): RowError[] {
	if (!record(value) || !Array.isArray(value.rowErrors)) return []
	return value.rowErrors.filter((row): row is RowError => record(row) && count(row.rowNumber) && Array.isArray(row.errors) && row.errors.every(error => typeof error === "string"))
}
function quantity(value: unknown) { return typeof value === "number" && Number.isFinite(value) ? value.toLocaleString("en-GB", { maximumFractionDigits: 4 }) : "Unknown" }
function text(value: unknown) { return typeof value === "string" && value ? value : "Unknown" }

export function InventoryCsvImport() {
	const router = useRouter()
	const [csv, setCsv] = useState("")
	const [filename, setFilename] = useState("")
	const [preview, setPreview] = useState<Preview | null>(null)
	const [previewedCsv, setPreviewedCsv] = useState<string | null>(null)
	const [confirmed, setConfirmed] = useState(false)
	const [busy, setBusy] = useState<"file" | "preview" | "commit" | null>(null)
	const [error, setError] = useState("")
	const [rowErrors, setRowErrors] = useState<RowError[]>([])
	const [success, setSuccess] = useState("")
	const pending = useRef(false)
	const generation = useRef(0)
	const mounted = useRef(true)
	useEffect(() => { mounted.current = true; return () => { mounted.current = false; generation.current += 1 } }, [])
	const exactPreview = preview?.valid === true && previewedCsv === csv
	const canCommit = exactPreview && confirmed && !busy && !success

	function invalidate() {
		generation.current += 1
		setPreview(null); setPreviewedCsv(null); setConfirmed(false); setError(""); setRowErrors([]); setSuccess("")
	}
	function edit(value: string) { invalidate(); setCsv(value); setFilename("") }
	async function readFile(file?: File) {
		if (!file || pending.current) return
		invalidate()
		const version = generation.current
		pending.current = true; setBusy("file")
		try {
			if (file.size > MAX_INVENTORY_CSV_BYTES) throw new Error("CSV must be at most 128 KiB. Existing text has not changed.")
			const value = new TextDecoder("utf-8", { fatal: true, ignoreBOM: true }).decode(await file.arrayBuffer())
			if (!mounted.current || generation.current !== version) return
			inventoryCsvText(value)
			setCsv(value); setFilename(file.name)
		} catch (cause) {
			if (mounted.current && generation.current === version) setError(cause instanceof TypeError ? "Choose a valid UTF-8 CSV file. Existing text has not changed." : cause instanceof Error ? cause.message : "The file could not be read. Existing text has not changed.")
		} finally { if (mounted.current) { pending.current = false; setBusy(null) } }
	}
	async function request(mode: "preview" | "commit") {
		if (pending.current || (mode === "commit" && !canCommit)) return
		pending.current = true; setBusy(mode); setError(""); setRowErrors([]); setSuccess("")
		if (mode === "preview") { setPreview(null); setPreviewedCsv(null); setConfirmed(false) }
		const version = ++generation.current
		const exactCsv = csv
		try {
			inventoryCsvText(exactCsv)
			const response = await fetch("/api/inventory/import", { method: "POST", credentials: "same-origin", headers: { "content-type": "application/json" }, body: JSON.stringify({ mode, csv: exactCsv }) })
			const result: unknown = await response.json().catch(() => null)
			if (!mounted.current || generation.current !== version) return
			if (!response.ok) {
				setRowErrors(serverRowErrors(result))
				if (mode === "commit" && record(result) && result.valid === false) { setPreview(inventoryCsvPreview(result, "commit")); setPreviewedCsv(exactCsv) }
				throw new Error(record(result) && typeof result.error === "string" ? result.error : "The import could not be completed. Your CSV is unchanged; try again.")
			}
			if (mode === "preview") { setPreview(inventoryCsvPreview(result)); setPreviewedCsv(exactCsv) }
			else {
				const counts = inventoryCsvCommitCounts(result, preview!.totalRows)
				setSuccess(`${counts.inserted} new counts saved; ${counts.unchanged} already recorded; ${counts.totalRows} total.`)
				setConfirmed(false)
				router.refresh()
			}
		} catch (cause) {
			if (mounted.current && generation.current === version) { setConfirmed(false); setError(cause instanceof Error ? cause.message : "The request failed. Your CSV is unchanged; try again.") }
		} finally { if (mounted.current) { pending.current = false; setBusy(null) } }
	}

	return <details className="rounded-lg border bg-white p-4">
		<summary className="cursor-pointer font-semibold">Import stock counts from CSV</summary>
		<p className="mt-2 text-sm text-slate-600">Choose a UTF-8 file or paste up to 100 stock counts (128 KiB maximum). Preview the rows, then confirm before any counts are saved.</p>
		<a href={`data:text/csv;charset=utf-8,${encodeURIComponent(INVENTORY_CSV_TEMPLATE)}`} download="inventory-stock-counts-template.csv" className="mt-2 inline-block text-sm text-blue-700 underline">Download CSV headers</a>
		<p id="inventory-csv-columns" className="mt-2 text-xs text-slate-500">Required columns: locationCode, sku, sourceReference, observedAt. Supply each count reference and observation time explicitly, including a timezone. Use locationName for a new warehouse. Leave unknown quantities blank; enter 0 only for confirmed zero. The template lists every optional column.</p>
		<form onSubmit={event => { event.preventDefault(); void request("preview") }} className="mt-4 space-y-4" aria-busy={Boolean(busy)}>
			<label className="grid gap-1 text-sm">CSV file<input type="file" accept=".csv,text/csv,text/plain" disabled={Boolean(busy)} onClick={event => { event.currentTarget.value = "" }} onChange={event => { void readFile(event.target.files?.[0]) }} className="max-w-full text-sm file:mr-3 file:rounded file:border file:bg-white file:px-3 file:py-2" /></label>
			{filename && <p className="break-all text-xs text-slate-500">Loaded file: {filename}</p>}
			<label className="grid gap-1 text-sm">CSV contents<textarea name="csv" value={csv} onChange={event => edit(event.target.value)} disabled={Boolean(busy)} rows={7} spellCheck={false} aria-describedby="inventory-csv-columns inventory-csv-size" className="w-full rounded border px-3 py-2 font-mono text-xs disabled:bg-slate-100" /></label>
			<p id="inventory-csv-size" className="text-xs text-slate-500">{new TextEncoder().encode(csv).byteLength.toLocaleString("en-GB")} / 131,072 bytes. Editing the CSV clears its previous preview and confirmation.</p>
			<button type="submit" disabled={Boolean(busy) || !csv.trim()} className="rounded border bg-white px-4 py-2 text-sm disabled:opacity-50">{busy === "file" ? "Reading file…" : busy === "preview" ? "Checking rows…" : "Preview rows"}</button>
			{error && <div role="alert" className="rounded bg-red-50 p-3 text-sm text-red-800"><p>{error}</p>{rowErrors.length > 0 && <ul className="mt-2 list-inside list-disc">{rowErrors.map(row => <li key={row.rowNumber}>Row {row.rowNumber}: {row.errors.join("; ")}</li>)}</ul>}</div>}
			{preview && previewedCsv === csv && <section aria-label="CSV preview" className="space-y-3">
				<p role="status" className={`rounded p-3 text-sm ${preview.valid ? "bg-blue-50 text-blue-900" : "bg-amber-50 text-amber-900"}`}>{preview.totalRows} rows · {preview.validRows} valid · {preview.errorRows} with errors.{!preview.valid && " Fix every row error and preview again before importing."}</p>
				{!preview.valid && <ul aria-label="CSV row errors" className="list-inside list-disc rounded bg-amber-50 p-3 text-sm text-amber-900">{preview.rows.filter(row => !row.valid).map(row => <li key={row.rowNumber}>Row {row.rowNumber}: {row.errors.join("; ")}</li>)}</ul>}
				<p className="text-xs text-slate-500 sm:hidden">Scroll the preview sideways to review every field.</p>
				<div className="overflow-x-auto rounded border"><table className="w-full text-left text-xs"><caption className="sr-only">Stock counts to import and row validation results</caption><thead className="border-b bg-slate-50"><tr>{["Row", "Location / SKU", "Count reference / observed", "Available / on hand", "Reserved / committed", "Inbound / in transit", "Result"].map(title => <th key={title} scope="col" className="p-3 font-medium">{title}</th>)}</tr></thead><tbody>{preview.rows.map(row => <tr key={row.rowNumber} className="border-b last:border-0"><th scope="row" className="p-3 align-top">{row.rowNumber}</th><td className="p-3 align-top"><div>{text(row.values?.locationCode)}</div><div>{text(row.values?.sku)}</div>{typeof row.values?.locationName === "string" && <div className="mt-1 text-slate-500">Warehouse: {row.values.locationName}</div>}</td><td className="max-w-xs break-words p-3 align-top"><div>{text(row.values?.sourceReference)}</div><div>{text(row.values?.observedAt)}</div></td><td className="p-3 align-top"><div>Available: {quantity(row.values?.availableQty)}</div><div>On hand: {quantity(row.values?.onHandQty)}</div><div>Unsellable: {quantity(row.values?.unsellableQty)}</div></td><td className="p-3 align-top"><div>Reserved: {quantity(row.values?.reservedQty)}</div><div>Committed: {quantity(row.values?.committedQty)}</div></td><td className="p-3 align-top"><div>Inbound: {quantity(row.values?.inboundQty)}</div><div>In transit: {quantity(row.values?.inTransitQty)}</div><div>Expected: {text(row.values?.expectedAvailableAt)}</div></td><td className={`p-3 align-top ${row.valid ? "text-slate-600" : "text-red-800"}`}>{row.valid ? "Valid" : <ul className="space-y-1">{row.errors.map((message, index) => <li key={index}>{message}</li>)}</ul>}{row.values && <div className="mt-1 text-slate-500">Quality: {text(row.values.freshness)}{typeof row.values.currency === "string" && <div>Currency: {row.values.currency}</div>}</div>}</td></tr>)}</tbody></table></div>
				<p className="text-xs text-slate-500">All rows are saved together. A changed location or reused count reference may still stop the import; any errors are shown before you retry.</p>
				{exactPreview && !success && <label className="flex items-start gap-2 text-sm"><input type="checkbox" checked={confirmed} onChange={event => setConfirmed(event.target.checked)} disabled={Boolean(busy)} className="mt-1" /><span>I have reviewed all {preview.totalRows} rows and want to save these stock counts.</span></label>}
				<button type="button" onClick={() => { void request("commit") }} disabled={!canCommit} className="rounded bg-slate-900 px-4 py-2 text-sm text-white disabled:opacity-50">{busy === "commit" ? "Importing…" : "Confirm import"}</button>
			</section>}
			{success && <p role="status" className="rounded bg-green-50 p-3 text-sm text-green-800">{success}</p>}
		</form>
	</details>
}
