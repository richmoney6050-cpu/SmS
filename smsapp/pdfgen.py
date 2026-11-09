"""Render a structured report document to PDF (ReportLab). The same document drives the on-screen view."""
from __future__ import annotations

import io
from pathlib import Path
from xml.sax.saxutils import escape

from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER, TA_LEFT, TA_RIGHT
from reportlab.lib.pagesizes import A4, landscape
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import mm
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import Image, KeepTogether, PageBreak, Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

FONT_DIR = Path(__file__).parent / "fonts"
NAVY = colors.HexColor("#14274e")
BLUE = colors.HexColor("#2f6fdb")
LIGHT = colors.HexColor("#eef2f9")
GRID = colors.HexColor("#cfd8e6")
MUTED = colors.HexColor("#5b6b85")

_fonts_ready = False
BASE, BOLD = "Helvetica", "Helvetica-Bold"


def _fonts():
    global _fonts_ready, BASE, BOLD
    if _fonts_ready:
        return
    try:
        pdfmetrics.registerFont(TTFont("SMS-Sans", str(FONT_DIR / "DejaVuSans.ttf")))
        pdfmetrics.registerFont(TTFont("SMS-Sans-Bold", str(FONT_DIR / "DejaVuSans-Bold.ttf")))
        pdfmetrics.registerFontFamily("SMS-Sans", normal="SMS-Sans", bold="SMS-Sans-Bold", italic="SMS-Sans", boldItalic="SMS-Sans-Bold")
        BASE, BOLD = "SMS-Sans", "SMS-Sans-Bold"
    except Exception:  # pragma: no cover - falls back to the built-in font
        pass
    _fonts_ready = True


def _s(name, **kw):
    return ParagraphStyle(name, fontName=kw.pop("fontName", BASE), **kw)


def _cell(v) -> str:
    if v is None or v == "":
        return "-"
    if isinstance(v, float):
        return f"{v:g}"
    return str(v)


def render_pdf(doc, logo_path: str | None = None) -> bytes:
    """One document, or a list of documents each starting on a new page (class report cards)."""
    docs = doc if isinstance(doc, list) else [doc]
    doc = docs[0]
    _fonts()
    wide = any(len(b.get("columns", [])) > 7 for d_ in docs for b in d_["blocks"] if b["type"] == "table")
    page = landscape(A4) if wide else A4
    buf = io.BytesIO()
    margin = 14 * mm
    pdf = SimpleDocTemplate(buf, pagesize=page, leftMargin=margin, rightMargin=margin, topMargin=12 * mm, bottomMargin=16 * mm,
                            title=doc["title"], author=doc["school"]["name"])
    width = page[0] - 2 * margin
    body = _s("body", fontSize=9, leading=12.5, textColor=colors.HexColor("#1b2740"))
    small = _s("small", fontSize=8, leading=10.5, textColor=MUTED)
    h1 = _s("h1", fontName=BOLD, fontSize=15, leading=19, textColor=NAVY, spaceAfter=1)
    h2 = _s("h2", fontName=BOLD, fontSize=10.5, leading=14, textColor=NAVY, spaceBefore=9, spaceAfter=4)
    cell = _s("cell", fontSize=8.2, leading=10.4)
    cell_b = _s("cellb", fontName=BOLD, fontSize=8.2, leading=10.4, textColor=colors.white)
    story = []
    for di, doc in enumerate(docs):
        if di:
            story.append(PageBreak())
        school = doc["school"]
        # ---- letterhead
        left = []
        if logo_path and Path(logo_path).exists():
            try:
                img = Image(logo_path)
                ratio = img.imageWidth / img.imageHeight
                h = 17 * mm
                img.drawHeight, img.drawWidth = h, h * ratio
                left = [img]
            except Exception:
                left = []
        name_block = [Paragraph(escape(school["name"]), _s("sn", fontName=BOLD, fontSize=16, leading=20, textColor=NAVY))]
        if school.get("motto"):
            name_block.append(Paragraph(f"<i>{escape(school['motto'])}</i>", small))
        contact = " | ".join(x for x in (school.get("address"), school.get("phone"), school.get("email")) if x)
        if contact:
            name_block.append(Paragraph(escape(contact), small))
        head = Table([[left or "", name_block]], colWidths=[24 * mm if left else 0.1, width - (24 * mm if left else 0.1)])
        head.setStyle(TableStyle([("VALIGN", (0, 0), (-1, -1), "MIDDLE"), ("LEFTPADDING", (0, 0), (-1, -1), 0), ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
                                  ("LINEBELOW", (0, 0), (-1, 0), 1.6, BLUE)]))
        story += [head, Spacer(1, 6), Paragraph(escape(doc["title"]), h1)]
        if doc.get("subtitle"):
            story.append(Paragraph(escape(doc["subtitle"]), _s("sub", fontSize=9.5, leading=13, textColor=MUTED)))
        story.append(Spacer(1, 4))

        for b in doc["blocks"]:
            parts = []
            if b.get("title"):
                parts.append(Paragraph(escape(b["title"]), h2))
            if b["type"] == "kv":
                items = b["items"]
                cols = 2 if width < 200 * mm else 3
                rows_ = []
                for i in range(0, len(items), cols):
                    r = []
                    for lab, val in items[i:i + cols]:
                        r.append(Paragraph(f"<font color='#5b6b85' size='7.5'>{escape(str(lab)).upper()}</font><br/>{escape(_cell(val))}", body))
                    while len(r) < cols:
                        r.append("")
                    rows_.append(r)
                t = Table(rows_, colWidths=[width / cols] * cols)
                t.setStyle(TableStyle([("VALIGN", (0, 0), (-1, -1), "TOP"), ("BOX", (0, 0), (-1, -1), 0.5, GRID), ("INNERGRID", (0, 0), (-1, -1), 0.25, GRID),
                                       ("BACKGROUND", (0, 0), (-1, -1), LIGHT), ("TOPPADDING", (0, 0), (-1, -1), 4), ("BOTTOMPADDING", (0, 0), (-1, -1), 4)]))
                parts.append(t)
            elif b["type"] == "stats":
                items = b["items"]
                n = min(len(items), 6) or 1
                rows_ = []
                for i in range(0, len(items), n):
                    chunk = items[i:i + n]
                    r = [Paragraph(f"<font size='15' color='#14274e'><b>{escape(_cell(x['value']))}</b></font><br/><font size='7.5' color='#5b6b85'>{escape(x['label'])}</font>",
                                   _s("st", alignment=TA_CENTER, leading=17)) for x in chunk]
                    r += [""] * (n - len(r))
                    rows_.append(r)
                t = Table(rows_, colWidths=[width / n] * n)
                t.setStyle(TableStyle([("BOX", (0, 0), (-1, -1), 0.5, GRID), ("INNERGRID", (0, 0), (-1, -1), 0.25, GRID), ("BACKGROUND", (0, 0), (-1, -1), LIGHT),
                                       ("TOPPADDING", (0, 0), (-1, -1), 6), ("BOTTOMPADDING", (0, 0), (-1, -1), 6), ("VALIGN", (0, 0), (-1, -1), "MIDDLE")]))
                parts.append(t)
            elif b["type"] == "table":
                cols = b["columns"]
                if not b["rows"]:
                    parts.append(Paragraph(escape(b.get("empty") or "No records."), small))
                else:
                    data = [[Paragraph(escape(c["label"]), cell_b) for c in cols]]
                    for r in b["rows"]:
                        data.append([Paragraph(escape(_cell(r.get(c["key"]))), _s("c", fontSize=8.2, leading=10.4, alignment=TA_RIGHT if c.get("align") == "right" else (TA_CENTER if c.get("align") == "center" else TA_LEFT))) for c in cols])
                    weights = [c.get("w", 1) for c in cols]
                    tw = sum(weights)
                    t = Table(data, colWidths=[width * w / tw for w in weights], repeatRows=1)
                    style = [("BACKGROUND", (0, 0), (-1, 0), NAVY), ("VALIGN", (0, 0), (-1, -1), "MIDDLE"), ("GRID", (0, 0), (-1, -1), 0.25, GRID),
                             ("TOPPADDING", (0, 0), (-1, -1), 3), ("BOTTOMPADDING", (0, 0), (-1, -1), 3), ("LEFTPADDING", (0, 0), (-1, -1), 4), ("RIGHTPADDING", (0, 0), (-1, -1), 4)]
                    for i in range(2, len(data), 2):
                        style.append(("BACKGROUND", (0, i), (-1, i), LIGHT))
                    t.setStyle(TableStyle(style))
                    parts.append(t)
                if b.get("note"):
                    parts.append(Paragraph(escape(b["note"]), small))
            elif b["type"] == "text":
                parts.append(Paragraph(escape(b["text"]).replace("\n", "<br/>"), body))
            if b["type"] == "table" and len(b.get("rows", [])) > 14:
                story += parts
            else:
                story.append(KeepTogether(parts))


    def footer(canvas, d):
        canvas.saveState()
        canvas.setFont(BASE, 7.5)
        canvas.setFillColor(MUTED)
        canvas.drawString(margin, 9 * mm, f"{doc.get('footer') or ''}"[:120])
        canvas.drawRightString(page[0] - margin, 9 * mm, f"Generated {doc['generated_at']} by {doc['generated_by']}  |  Page {d.page}")
        canvas.restoreState()

    pdf.build(story, onFirstPage=footer, onLaterPages=footer)
    return buf.getvalue()
