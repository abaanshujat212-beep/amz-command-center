const assert = require('node:assert/strict')
const fs = require('node:fs')
const Module = require('node:module')
const path = require('node:path')
const root = path.resolve(__dirname, '..')
const requireWeb = Module.createRequire(path.join(root, 'package.json'))
const ts = requireWeb('typescript')
const React = requireWeb('react')
const { renderToStaticMarkup } = requireWeb('react-dom/server')
const filename = path.join(root, 'app/verification/page.tsx')
const pageModule = new Module(filename)
pageModule.filename = filename
pageModule.paths = Module._nodeModulePaths(root)
const native = pageModule.require.bind(pageModule)
const snapshots = [{
  horizon_days: 7,
  status: 'COMPLETE',
  outcome: 'improved',
  confounding_status: 'CONFOUNDED',
  confounder_count: 1,
  evidence_truncated: false,
  confounders: [{ source: 'manual', window: 'after', change_kind: 'bid', source_ref: 'ticket-1', changed_at: '2026-10-01T12:00:00Z', action_id: null, signal_id: 'signal-1' }],
}]
pageModule.require = name => {
  if (name === '@/lib/action-value') return { isMoneyAction: () => false, shown: value => String(value ?? '') }
  if (name === '@/lib/db') return { withTenant: async (_tenant, callback) => callback({}) }
  if (name === '@/lib/format') return { money: value => String(value ?? '—'), percent: value => String(value ?? '—'), stamp: value => String(value ?? '—') }
  if (name === '@/lib/queries-verification') return { verificationScorecards: async () => [{
    id: 'action-1', entity_type: 'keyword', entity_id: 'K-1', action_type: 'set_bid', status: 'verified', outcome: 'improved',
    applied_at: '2026-09-24T00:00:00Z', verified_at: '2026-10-01T00:00:00Z', before_value: { value: 1 }, after_value: { value: 1.1 },
    impact_jsonb: {}, snapshots, reason_text: null, rule_code: 'RULE', rule_name: 'Rule',
  }] }
  if (name === '@/lib/session') return { currentTenantId: async () => 'tenant-1' }
  return native(name)
}
pageModule._compile(ts.transpileModule(fs.readFileSync(filename, 'utf8'), { compilerOptions: { module: ts.ModuleKind.CommonJS, jsx: ts.JsxEmit.ReactJSX } }).outputText, filename)

async function main() {
  const html = renderToStaticMarkup(await pageModule.exports.default())
  assert.match(html, /CONFOUNDED/)
  assert.match(html, /T\+7 observed movement: improved\. It is not attributed to this action\./)
  assert.match(html, /Manual/)
  assert.match(html, /ticket-1/)
  assert.match(html, /parent-entity and unrecorded changes may be missing/)
  console.log('Verification confounding UI: horizon override, observed-but-not-attributed outcome and recorded same-entity evidence passed.')
}

main().catch(error => { console.error(error); process.exitCode = 1 })
