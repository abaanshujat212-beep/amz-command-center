export type ListingValidationIssue = { code:string; field:string; severity:"warning"|"error"; message:string }
export type ListingValidationInput = { title:string; bullets:string[]; description:string; backendTerms:string[]; citedFactIds:string[]; availableFactIds:string[]; keywordBank:string[]; productType:string|null; ptdContractVerified:boolean; restrictionsStatus:string }

const prohibited: Array<[string, RegExp]> = [
	["guarantee", /\b(?:guaranteed?|100% guaranteed)\b/i],
	["unverified_superlative", /(?:\b#\s*1\b|\bbest\b|\bnumber one\b)/i],
	["medical_claim", /\b(?:cures?|treats?|prevents?)\s+(?:a|an|the)?\s*(?:disease|illness|condition|infection)\b/i],
]

export function validateListingDraft(input: ListingValidationInput) {
	const issues: ListingValidationIssue[] = []
	if (!input.citedFactIds.length) issues.push({code:"ungrounded_draft",field:"sources",severity:"error",message:"At least one tenant product fact must support the draft."})
	if (input.citedFactIds.some(id => !input.availableFactIds.includes(id))) issues.push({code:"unknown_source",field:"sources",severity:"error",message:"The draft cites an unavailable product fact."})
	if (!input.productType || !input.ptdContractVerified) issues.push({code:"ptd_unverified",field:"product_type",severity:"error",message:"A verified Amazon product-type contract is required before review."})
	if (input.restrictionsStatus !== "clear") issues.push({code:"restrictions_not_clear",field:"restrictions",severity:"error",message:"Amazon restrictions must be verified clear before review."})
	const fields: Array<[string,string]> = [["title",input.title],["description",input.description],...input.bullets.map((value,index):[string,string] => [`bullet_${index+1}`,value])]
	for (const [field,value] of fields) for (const [code,pattern] of prohibited) if (pattern.test(value)) issues.push({code,field,severity:"error",message:"Remove prohibited or unverifiable claims."})
	if (input.title.length > 200) issues.push({code:"title_too_long",field:"title",severity:"error",message:"Title exceeds the conservative 200-character limit."})
	if (input.bullets.length > 5) issues.push({code:"too_many_bullets",field:"bullets",severity:"error",message:"Use no more than five bullets."})
	input.bullets.forEach((value,index) => { if (value.length > 500) issues.push({code:"bullet_too_long",field:`bullet_${index+1}`,severity:"error",message:"Bullet exceeds 500 characters."}) })
	if (new TextEncoder().encode(input.backendTerms.join(" ")).length > 249) issues.push({code:"backend_terms_too_long",field:"backend_terms",severity:"error",message:"Backend terms exceed 249 UTF-8 bytes."})
	const allowed = new Set(input.keywordBank.map(v => v.trim().toLocaleLowerCase()).filter(Boolean))
	if (input.backendTerms.some(v => !allowed.has(v.trim().toLocaleLowerCase()))) issues.push({code:"keyword_not_approved",field:"backend_terms",severity:"error",message:"Backend terms must come from the approved keyword bank."})
	return { passed: !issues.some(issue => issue.severity === "error"), issues }
}
