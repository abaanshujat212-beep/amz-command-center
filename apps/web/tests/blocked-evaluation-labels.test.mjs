import assert from 'node:assert/strict'
import test from 'node:test'
import { blockedEvaluationReason, blockedEvaluationType } from '../lib/blocked-evaluation-labels.ts'

test('native conflict has a separate approval step and not an action', () => {
  const result = blockedEvaluationReason('NATIVE_OPTIMIZATION_CONFLICT')
  assert.equal(result.code, 'NATIVE_OPTIMIZATION_CONFLICT')
  assert.match(result.title, /conflict/)
  assert.match(result.nextStep, /keep Amazon.+separate.+approved/i)
})

test('missing, stale, invalid and unsupported evidence remain distinct', () => {
  const codes = ['NATIVE_CONTROL_EVIDENCE_MISSING','NATIVE_CONTROL_EVIDENCE_STALE',
    'NATIVE_CONTROL_EVIDENCE_INVALID','NATIVE_CONTROL_UNSUPPORTED']
  assert.equal(new Set(codes.map(code => blockedEvaluationReason(code).title)).size, 4)
})

test('unknown or inherited values never echo stored arbitrary text', () => {
  for (const input of ['untrusted arbitrary payload','constructor','__proto__',null]) {
    const result = blockedEvaluationReason(input)
    assert.equal(result.code,null)
    assert.equal(result.title,'Other guardrail block')
    assert.doesNotMatch(result.nextStep,/payload|constructor|__proto__/)
  }
})

test('only approved proposal categories become display labels', () => {
  assert.equal(blockedEvaluationType('bid_adjustment'), 'Bid adjustment')
  assert.equal(blockedEvaluationType('raw advertiser data'), null)
  assert.equal(blockedEvaluationType('constructor'), null)
})
