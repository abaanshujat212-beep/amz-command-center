"""Persistence contract for immutable/versioned COGS calculations."""

from __future__ import annotations

from services.economics.batch_cogs import Calculation, Method, Receipt, Sale, calculate


def calculate_and_persist(conn, *, tenant_id: str, marketplace_id: str, sku: str, policy_id: str, method: Method, period_start, period_end, version: int, receipts: list[Receipt], sales: list[Sale], currency: str = "GBP", supersedes_run_id: str | None = None) -> str:
    result: Calculation = calculate(method, receipts, sales)
    run = conn.execute(
        """insert into cogs_calculation_run
           (tenant_id,marketplace_id,sku,policy_id,method,period_start,period_end,version,
            supersedes_run_id,input_hash,status,incomplete_reason)
           values(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s) returning id""",
        (tenant_id, marketplace_id, sku, policy_id, method, period_start, period_end, version,
         supersedes_run_id, result.input_hash, "complete" if result.complete else "incomplete", result.incomplete_reason),
    ).fetchone()[0]
    sale_times = {sale.ref: sale.sold_at for sale in sales}
    for item in result.allocations:
        conn.execute(
            """insert into cogs_allocation
               (tenant_id,run_id,sale_ref,sold_at,batch_id,quantity,unit_cost,allocated_cost,currency,sequence)
               values(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)""",
            (tenant_id, run, item.sale_ref, sale_times[item.sale_ref], item.batch_id, item.quantity,
             item.unit_cost, item.allocated_cost, currency, item.sequence),
        )
    return str(run)
