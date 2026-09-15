"""Deterministic render contracts for governed report datasets."""

from __future__ import annotations

import csv
import datetime as dt
import hashlib
import io
import json
import math
import zipfile
from dataclasses import dataclass
from decimal import Decimal
from typing import Any, Iterable, Mapping
from xml.sax.saxutils import escape

MAX_REPORT_ROWS = 100_000
MAX_REPORT_CELLS = 1_000_000
FIXED_ZIP_TIME = (2000, 1, 1, 0, 0, 0)


@dataclass(frozen=True)
class RenderedArtifact:
    data: bytes
    output_format: str
    media_type: str
    file_extension: str
    contract_version: int
    content_sha256: str
    source_data_sha256: str
    row_count: int
    reconciliation: dict[str, Any]


CONTRACTS = {
    "csv": ("text/csv; charset=utf-8", "csv"),
    "xlsx": ("application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", "xlsx"),
    "pdf": ("application/pdf", "pdf"),
}


def _cell(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (dt.date, dt.datetime)):
        return value.isoformat()
    if isinstance(value, Decimal):
        return format(value, "f")
    if isinstance(value, float):
        if not math.isfinite(value):
            raise ValueError("report cells cannot contain non-finite numbers")
        return format(value, ".15g")
    if isinstance(value, (dict, list, tuple)):
        return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return str(value)


def _canonical_rows(
    columns: tuple[str, ...], rows: Iterable[Mapping[str, Any]]
) -> tuple[tuple[str, ...], ...]:
    if not columns or any(not column for column in columns):
        raise ValueError("report columns must be non-empty")
    if len(columns) != len(set(columns)):
        raise ValueError("report columns must be unique")
    materialized: list[tuple[str, ...]] = []
    for row in rows:
        if len(materialized) >= MAX_REPORT_ROWS:
            raise ValueError("report row limit exceeded")
        materialized.append(tuple(_cell(row.get(column)) for column in columns))
    if len(materialized) * len(columns) > MAX_REPORT_CELLS:
        raise ValueError("report cell limit exceeded")
    return tuple(materialized)


def _source_bytes(columns: tuple[str, ...], rows: tuple[tuple[str, ...], ...]) -> bytes:
    return json.dumps(
        {"columns": columns, "rows": rows},
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    ).encode()


def _csv_bytes(columns: tuple[str, ...], rows: tuple[tuple[str, ...], ...]) -> bytes:
    output = io.StringIO(newline="")
    writer = csv.writer(output, lineterminator="\n")
    writer.writerow(columns)
    writer.writerows(rows)
    return output.getvalue().encode()


def _column_name(index: int) -> str:
    name = ""
    while index:
        index, remainder = divmod(index - 1, 26)
        name = chr(65 + remainder) + name
    return name


def _xlsx_cell(reference: str, value: str) -> str:
    preserve = ' xml:space="preserve"' if value != value.strip() else ""
    return f'<c r="{reference}" t="inlineStr"><is><t{preserve}>{escape(value)}</t></is></c>'


def _xlsx_bytes(columns: tuple[str, ...], rows: tuple[tuple[str, ...], ...]) -> bytes:
    sheet_rows = []
    for row_number, values in enumerate((columns, *rows), start=1):
        cells = "".join(
            _xlsx_cell(f"{_column_name(column_number)}{row_number}", value)
            for column_number, value in enumerate(values, start=1)
        )
        sheet_rows.append(f'<row r="{row_number}">{cells}</row>')
    files = {
        "[Content_Types].xml": """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types"><Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/><Default Extension="xml" ContentType="application/xml"/><Override PartName="/xl/workbook.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml"/><Override PartName="/xl/worksheets/sheet1.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"/><Override PartName="/docProps/core.xml" ContentType="application/vnd.openxmlformats-package.core-properties+xml"/></Types>""",
        "_rels/.rels": """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships"><Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="xl/workbook.xml"/><Relationship Id="rId2" Type="http://schemas.openxmlformats.org/package/2006/relationships/metadata/core-properties" Target="docProps/core.xml"/></Relationships>""",
        "docProps/core.xml": """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<cp:coreProperties xmlns:cp="http://schemas.openxmlformats.org/package/2006/metadata/core-properties" xmlns:dc="http://purl.org/dc/elements/1.1/" xmlns:dcterms="http://purl.org/dc/terms/" xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance"><dc:creator>AXATY</dc:creator><dcterms:created xsi:type="dcterms:W3CDTF">2000-01-01T00:00:00Z</dcterms:created></cp:coreProperties>""",
        "xl/_rels/workbook.xml.rels": """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships"><Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet" Target="worksheets/sheet1.xml"/></Relationships>""",
        "xl/workbook.xml": """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships"><sheets><sheet name="Report" sheetId="1" r:id="rId1"/></sheets></workbook>""",
        "xl/worksheets/sheet1.xml": """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main"><sheetData>"""
        + "".join(sheet_rows)
        + "</sheetData></worksheet>",
    }
    output = io.BytesIO()
    with zipfile.ZipFile(output, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=9) as archive:
        for name in sorted(files):
            info = zipfile.ZipInfo(name, FIXED_ZIP_TIME)
            info.compress_type = zipfile.ZIP_DEFLATED
            info.external_attr = 0o600 << 16
            archive.writestr(info, files[name].encode())
    return output.getvalue()


def _pdf_escape(value: str) -> str:
    return value.encode("latin-1", "replace").decode("latin-1").replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")


def _pdf_bytes(columns: tuple[str, ...], rows: tuple[tuple[str, ...], ...]) -> bytes:
    lines = [" | ".join(columns), *(" | ".join(row) for row in rows)]
    pages = [lines[index : index + 48] for index in range(0, len(lines), 48)] or [[]]
    font_id = 3 + 2 * len(pages)
    objects: list[bytes] = [b"", b""]
    page_ids = []
    for page_index, page_lines in enumerate(pages):
        page_id = 3 + page_index * 2
        content_id = page_id + 1
        page_ids.append(page_id)
        commands = ["BT", "/F1 8 Tf", "36 806 Td", "10 TL"]
        for line in page_lines:
            commands.extend((f"({_pdf_escape(line[:160])}) Tj", "T*"))
        commands.append("ET")
        stream = "\n".join(commands).encode("latin-1")
        objects.append(
            f"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 595 842] /Resources << /Font << /F1 {font_id} 0 R >> >> /Contents {content_id} 0 R >>".encode()
        )
        objects.append(b"<< /Length " + str(len(stream)).encode() + b" >>\nstream\n" + stream + b"\nendstream")
    objects[0] = b"<< /Type /Catalog /Pages 2 0 R >>"
    kids = " ".join(f"{page_id} 0 R" for page_id in page_ids)
    objects[1] = f"<< /Type /Pages /Kids [{kids}] /Count {len(page_ids)} >>".encode()
    objects.append(b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>")
    output = bytearray(b"%PDF-1.4\n%\xe2\xe3\xcf\xd3\n")
    offsets = [0]
    for object_id, body in enumerate(objects, start=1):
        offsets.append(len(output))
        output.extend(f"{object_id} 0 obj\n".encode() + body + b"\nendobj\n")
    xref = len(output)
    output.extend(f"xref\n0 {len(objects) + 1}\n".encode())
    output.extend(b"0000000000 65535 f \n")
    for offset in offsets[1:]:
        output.extend(f"{offset:010d} 00000 n \n".encode())
    output.extend(
        f"trailer\n<< /Size {len(objects) + 1} /Root 1 0 R >>\nstartxref\n{xref}\n%%EOF\n".encode()
    )
    return bytes(output)


def render_dataset(
    output_format: str,
    columns: Iterable[str],
    rows: Iterable[Mapping[str, Any]],
    *,
    contract_version: int = 1,
) -> RenderedArtifact:
    """Render deterministic bytes and reconciliation metadata from ordered data."""
    output_format = output_format.lower()
    if output_format not in CONTRACTS:
        raise ValueError(f"unsupported report format: {output_format}")
    if contract_version != 1:
        raise ValueError(f"unsupported render contract version: {contract_version}")
    ordered_columns = tuple(columns)
    ordered_rows = _canonical_rows(ordered_columns, rows)
    source = _source_bytes(ordered_columns, ordered_rows)
    renderer = {"csv": _csv_bytes, "xlsx": _xlsx_bytes, "pdf": _pdf_bytes}[output_format]
    data = renderer(ordered_columns, ordered_rows)
    content_hash = hashlib.sha256(data).hexdigest()
    source_hash = hashlib.sha256(source).hexdigest()
    media_type, extension = CONTRACTS[output_format]
    reconciliation = {
        "column_count": len(ordered_columns),
        "columns": list(ordered_columns),
        "row_count": len(ordered_rows),
        "source_data_sha256": source_hash,
    }
    return RenderedArtifact(
        data=data,
        output_format=output_format,
        media_type=media_type,
        file_extension=extension,
        contract_version=contract_version,
        content_sha256=content_hash,
        source_data_sha256=source_hash,
        row_count=len(ordered_rows),
        reconciliation=reconciliation,
    )
