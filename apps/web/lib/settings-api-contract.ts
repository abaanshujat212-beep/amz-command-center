import { createHash } from "node:crypto"

export class SettingsApiError extends Error {
  readonly status:number
  constructor(message:string, status:number) { super(message); this.status=status }
}
export type CompanySettings = {name:string;timezone:string}
export function settingsRevision(value:CompanySettings) {
  return `"${createHash("sha256").update(JSON.stringify([value.name,value.timezone])).digest("hex")}"`
}
export function validateCompanySettings(raw:unknown):CompanySettings {
  if (!raw || typeof raw!=="object" || Array.isArray(raw)) throw new SettingsApiError("Expected settings object",400)
  const value=raw as Record<string,unknown>
  if(Object.keys(value).some(k=>k!=="name"&&k!=="timezone")) throw new SettingsApiError("Only name and timezone can be changed",400)
  if(typeof value.name!=="string"||value.name.trim().length<2||value.name.trim().length>100) throw new SettingsApiError("Name must be 2–100 characters",400)
  if(typeof value.timezone!=="string"||value.timezone.length>80) throw new SettingsApiError("Invalid timezone",400)
  try {new Intl.DateTimeFormat("en",{timeZone:value.timezone}).format()} catch {throw new SettingsApiError("Invalid timezone",400)}
  return {name:value.name.trim(),timezone:value.timezone}
}
