"""Turn a report document (the same structure the PDF renderer uses) into Excel or CSV files."""
import csv
import io
import re

from openpyxl import Workbook
from openpyxl.styles import Alignment, Font, PatternFill
from openpyxl.utils import get_column_letter

_BAD = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f]")


def _v(v):
    """Values that begin with =,+,-,@ are prefixed so a spreadsheet never runs them as a formula."""
    if v is None:
        return ""
    if isinstance(v, bool):
        return "Yes" if v else "No"
    if isinstance(v, (int, float)):
        return v
    s = _BAD.sub("", str(v))
    if s[:1] in ("=", "+", "@") or (s[:1] == "-" and not re.fullmatch(r"-?\d+(\.\d+)?", s)):
        return "'" + s
    return s


def _sheet_name(title: str, used: set) -> str:
    base = re.sub(r"[\[\]\:\*\?\/\\]", " ", title or "Sheet").strip()[:28] or "Sheet"
    name, n = base, 2
    while name.lower() in used:
        name = f"{base[:25]} {n}"
        n += 1
    used.add(name.lower())
    return name


def doc_to_xlsx(doc: dict) -> bytes:
    wb = Workbook()
    wb.remove(wb.active)
    used: set = set()
    head_fill = PatternFill("solid", fgColor="14274E")
    summary = wb.create_sheet(_sheet_name("Summary", used))
    summary.append([doc["school"]["name"]])
    summary["A1"].font = Font(bold=True, size=14, color="14274E")
    summary.append([doc["title"]])
    summary["A2"].font = Font(bold=True, size=12)
    if doc.get("subtitle"):
        summary.append([doc["subtitle"]])
    summary.append([f"Generated {doc['generated_at']} by {doc['generated_by']}"])
    summary.append([])
    for b in doc["blocks"]:
        if b["type"] == "kv":
            if b.get("title"):
                summary.append([b["title"]]); summary.cell(summary.max_row, 1).font = Font(bold=True)
            for lab, val in b["items"]:
                summary.append([lab, _v(val)])
            summary.append([])
        elif b["type"] == "stats":
            if b.get("title"):
                summary.append([b["title"]]); summary.cell(summary.max_row, 1).font = Font(bold=True)
            for it in b["items"]:
                summary.append([it["label"], _v(it["value"])])
            summary.append([])
        elif b["type"] == "text":
            if b.get("title"):
                summary.append([b["title"]]); summary.cell(summary.max_row, 1).font = Font(bold=True)
            summary.append([_v(b["text"])])
            summary.append([])
    summary.column_dimensions["A"].width = 34
    summary.column_dimensions["B"].width = 40
    for b in doc["blocks"]:
        if b["type"] != "table":
            continue
        ws = wb.create_sheet(_sheet_name(b.get("title") or "Data", used))
        cols = b["columns"]
        ws.append([c["label"] for c in cols])
        for i in range(1, len(cols) + 1):
            c = ws.cell(1, i)
            c.font, c.fill = Font(bold=True, color="FFFFFF"), head_fill
            c.alignment = Alignment(horizontal="center", vertical="center", wrap_text=True)
        for r in b["rows"]:
            ws.append([_v(r.get(c["key"])) for c in cols])
        for i, c in enumerate(cols, start=1):
            width = max([len(str(c["label"]))] + [len(str(r.get(c["key"]) if r.get(c["key"]) is not None else "")) for r in b["rows"][:200]])
            ws.column_dimensions[get_column_letter(i)].width = min(max(width + 2, 8), 40)
        ws.freeze_panes = "A2"
    if len(wb.sheetnames) > 1 and summary.max_row <= 6:
        wb.remove(summary)
    out = io.BytesIO()
    wb.save(out)
    return out.getvalue()


def doc_to_csv(doc: dict) -> bytes:
    out = io.StringIO()
    w = csv.writer(out)
    first = True
    for b in doc["blocks"]:
        if b["type"] != "table":
            continue
        if not first:
            w.writerow([])
        first = False
        if b.get("title"):
            w.writerow([b["title"]])
        w.writerow([c["label"] for c in b["columns"]])
        for r in b["rows"]:
            w.writerow([_v(r.get(c["key"])) for c in b["columns"]])
    return ("﻿" + out.getvalue()).encode("utf-8")
