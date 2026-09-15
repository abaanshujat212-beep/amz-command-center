import io
import zipfile

import pytest

from services.reports.render import MAX_REPORT_ROWS, render_dataset

ROWS = [
    {"sku": "A-1", "sales": 12.5, "active": True},
    {"sku": "A-2", "sales": None, "active": False},
]
COLUMNS = ("sku", "sales", "active")


@pytest.mark.parametrize(
    ("output_format", "signature"),
    [("csv", b"sku,sales,active"), ("xlsx", b"PK"), ("pdf", b"%PDF-1.4")],
)
def test_render_contracts_are_deterministic(output_format, signature):
    first = render_dataset(output_format, COLUMNS, ROWS)
    second = render_dataset(output_format, COLUMNS, ROWS)
    assert first.data.startswith(signature)
    assert first.data == second.data
    assert first.content_sha256 == second.content_sha256
    assert first.source_data_sha256 == second.source_data_sha256
    assert first.row_count == 2
    assert first.reconciliation["column_count"] == 3


def test_xlsx_contract_is_a_valid_deterministic_package():
    artifact = render_dataset("xlsx", COLUMNS, ROWS)
    with zipfile.ZipFile(io.BytesIO(artifact.data)) as workbook:
        assert "xl/workbook.xml" in workbook.namelist()
        sheet = workbook.read("xl/worksheets/sheet1.xml")
        assert b"A-1" in sheet and b"12.5" in sheet


def test_render_contracts_fail_closed():
    with pytest.raises(ValueError, match="unsupported report format"):
        render_dataset("html", COLUMNS, ROWS)
    with pytest.raises(ValueError, match="contract version"):
        render_dataset("csv", COLUMNS, ROWS, contract_version=2)
    with pytest.raises(ValueError, match="unique"):
        render_dataset("csv", ("sku", "sku"), ROWS)


def test_large_results_are_bounded():
    rows = ({"value": index} for index in range(MAX_REPORT_ROWS + 1))
    with pytest.raises(ValueError, match="row limit"):
        render_dataset("csv", ("value",), rows)
