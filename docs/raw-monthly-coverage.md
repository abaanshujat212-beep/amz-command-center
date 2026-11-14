# Monthly raw data coverage report

`make raw-monthly-coverage` writes a CSV row for each tenant, month, and report-grained raw source. Months with no rows are included with `row_count=0`, so missing history is visible alongside populated months. The report includes row counts and the latest source report date, not customer or campaign data.

The script is read-only, uses the fixed source allowlist in `infra/scripts/report_raw_monthly_coverage.py`, requires `DATABASE_URL`, and caps the query at five minutes. The database connection must be a restricted operator role with cross-tenant read access and `BYPASSRLS`; the command verifies this before reading data. Do not use the app role. It creates a new output directory with mode `0700` and each report with mode `0600`. Store generated reports as sensitive operational metadata; do not commit them or publish tenant identifiers.

Run it monthly from the trusted deployment scheduler with `REPORT_DIR` on private storage. Alert on a failed run and review zero-count or unexpectedly declining months against pipeline history. This report detects row-count gaps; it does not prove that the source report itself was complete or reconcile business totals.
