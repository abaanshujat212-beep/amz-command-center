/**
 * Postgres -> JavaScript type parsing.
 *
 * Import this before any query runs. lib/db.ts does exactly that, which is why
 * this module has no exports worth using: it exists for the side effect.
 *
 * By default node-postgres hands back numeric (oid 1700) and int8 (oid 20) as
 * strings, on the grounds that neither fits in a double in the general case.
 * That is correct and it is also a trap: JavaScript will happily concatenate
 * two of those strings, compare them lexically, and never complain.
 *
 *   "9.5" > "10.2"   is true
 *   "12.50" + "3.20" is "12.503.20"
 *
 * Ad spend, clicks and impressions are far inside the safe integer range, so
 * converting to Number loses nothing real. Anything that must be exact to the
 * penny -- invoices, the cost ledger -- should be selected as text and handled
 * deliberately, not left to this default.
 */

import { types } from "pg"

const NUMERIC = 1700
const INT8 = 20

types.setTypeParser(NUMERIC, (v: string) => (v === null ? null : Number(v)))
types.setTypeParser(INT8, (v: string) => (v === null ? null : Number(v)))

export const PG_TYPES_CONFIGURED = true
