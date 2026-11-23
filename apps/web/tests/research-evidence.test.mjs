import { strict as assert } from "node:assert"
import { test } from "node:test"
import { presentResearchEvidence } from "../lib/research-evidence.ts"

const now=Date.parse("2026-01-02T12:00Z")
const base={completeness:"complete",numeric_value:"0",text_value:null,unit:"USD",
  observed_at:"2026-01-02T11:00Z",provider:"Recorded provider",method:"provider_api",
  evidence_ref:"report:123",evidence_scope:{marketplace:"US",grain:"weekly",token:"test-not-displayed"}}

test("keeps exact zero and arbitrary decimal precision, preserving source and scope",()=>{
  const shown=presentResearchEvidence(base,now)
  assert.equal(shown.value,"0")
  assert.equal(shown.source,"report:123")
  assert.equal(shown.unit,"USD")
  assert.deepEqual(shown.dimensions,[{key:"marketplace",value:"US"},{key:"grain",value:"weekly"}])
  const precise="12345678901234567890.1234567890"
  assert.equal(presentResearchEvidence({...base,numeric_value:precise},now).value,precise)
})
test("suppresses values from partial, blocked, unverified and invalid records",()=>{
  for(const fields of [{completeness:"partial"},{completeness:"blocked"},{completeness:"unexpected"},
    {observed_at:"not a date"},{observed_at:"2026-01-02T13:00Z"},{provider:" "},{method:" "},{evidence_ref:""},
    {evidence_scope:{token:"not scope"}},{numeric_value:"NaN"},{numeric_value:"Infinity"},
    {text_value:"should not have two values"}]){
    assert.equal(presentResearchEvidence({...base,...fields},now).value,null)
  }
})
test("does not expose URL credentials or treat references as links",()=>{
  const shown=presentResearchEvidence({...base,evidence_ref:"https://user:pass@example.invalid/private/path?token=secret#fragment"},now)
  assert.equal(shown.source,"https://example.invalid")
  assert.equal(presentResearchEvidence({...base,evidence_ref:"Bearer secret"},now).value,null)
})
