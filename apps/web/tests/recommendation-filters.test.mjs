import assert from 'node:assert/strict'
import test from 'node:test'
import {
  parseRecommendationFilters, recommendationPage, recommendationPageHref, confidenceLabel,
} from '../lib/recommendation-filters.ts'

const parse = (text='') => parseRecommendationFilters(new URLSearchParams(text))

test('optional filters parse empty confidence as unspecified, not zero', () => {
  assert.equal(parse('minConfidence=&confidence=').minConfidence, undefined)
  assert.equal(parse('minConfidence=&confidence=').confidence, undefined)
  assert.equal(parse('confidence=0').confidence, 0)
  assert.throws(() => parse('minConfidence=1.1'), /between/)
  assert.equal(confidenceLabel(null), 'Confidence not available')
  assert.equal(confidenceLabel(0), '0% confidence')
})

test('only real dates and ordered ranges are accepted', () => {
  assert.equal(parse('from=2024-02-29&to=2024-02-29').to, '2024-02-29')
  for (const bad of ['from=2025-02-29','from=2026-04-31','from=0000-01-01','to=2026/11/23']) {
    assert.throws(() => parse(bad), /calendar/)
  }
  assert.throws(() => parse('from=2026-11-23&to=2026-11-22'), /start date/)
})

test('lookahead distinguishes a full last page from a page with more results', () => {
  const middle = parse('limit=2&offset=2')
  const seen = recommendationPage(['c','d','e'], middle)
  assert.deepEqual(seen.recommendations,['c','d'])
  assert.deepEqual(seen.pagination,{limit:2,offset:2,count:2,previousOffset:0,nextOffset:4})
  assert.equal(recommendationPage(['c','d'],middle).pagination.nextOffset,null)
  assert.equal(recommendationPage([],middle).pagination.previousOffset,0)
  assert.throws(() => parse('offset=9007199254740993'), /pagination/)
})

test('paging preserves selected filters and handles encoded entity IDs', () => {
  const params = new URLSearchParams('type=bid_adjustment&from=2026-11-01&limit=2&entityId=x%26y&offset=2')
  const target = new URL(recommendationPageHref(params,4),'https://example.test')
  assert.equal(target.searchParams.get('entityId'),'x&y')
  assert.equal(target.searchParams.get('offset'),'4')
  assert.equal(target.searchParams.get('type'),'bid_adjustment')
  assert.equal(target.searchParams.get('from'),'2026-11-01')
  assert.equal(target.searchParams.get('limit'),'2')
  assert.ok(!recommendationPageHref(params,0).includes('offset'))
})
