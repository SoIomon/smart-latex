"""Generate the generic reference.docx for Pandoc Word export.

Run once:  python scripts/generate_reference_docx.py

Output: backend/app/core/templates/reference.docx
"""

from pathlib import Path

from docx import Document
from docx.enum.style import WD_STYLE_TYPE
from docx.enum.text import WD_PARAGRAPH_ALIGNMENT
from docx.oxml import OxmlElement
from docx.oxml.ns import qn
from docx.shared import Pt, Cm, RGBColor


def _set_east_asian_font(style, font_name: str) -> None:
    """Set the East Asian font for a style via OxmlElement."""
    rPr = style.element.get_or_add_rPr()
    rFonts = rPr.find(qn("w:rFonts"))
    if rFonts is None:
        rFonts = OxmlElement("w:rFonts")
        rPr.insert(0, rFonts)
    rFonts.set(qn("w:eastAsia"), font_name)


def _ensure_style(doc: Document, name: str, style_type=WD_STYLE_TYPE.PARAGRAPH):
    """Get existing style or create it."""
    try:
        return doc.styles[name]
    except KeyError:
        return doc.styles.add_style(name, style_type)


def generate_reference_docx(output_path: Path) -> None:
    doc = Document()

    # ── Normal ──────────────────────────────────────────────────────────
    normal = doc.styles["Normal"]
    normal.font.name = "Times New Roman"
    normal.font.size = Pt(12)
    normal.font.color.rgb = RGBColor(0, 0, 0)
    _set_east_asian_font(normal, "STSong")
    normal.paragraph_format.line_spacing = 1.5
    normal.paragraph_format.first_line_indent = Pt(24)  # ~2em at 12pt
    normal.paragraph_format.space_before = Pt(0)
    normal.paragraph_format.space_after = Pt(0)

    # ── Headings ────────────────────────────────────────────────────────
    heading_specs = [
        # (level, font_size_pt, bold, east_asian_font)
        (1, 15, True, "Heiti SC"),
        (2, 15, True, "Heiti SC"),
        (3, 14, True, "Heiti SC"),
        (4, 12, True, "Heiti SC"),
        (5, 12, True, "Heiti SC"),
        (6, 12, False, "Heiti SC"),
    ]

    for level, size, bold, ea_font in heading_specs:
        style_name = f"Heading {level}"
        style = _ensure_style(doc, style_name)
        style.font.name = "Times New Roman"
        style.font.size = Pt(size)
        style.font.bold = bold
        style.font.color.rgb = RGBColor(0, 0, 0)
        _set_east_asian_font(style, ea_font)
        style.paragraph_format.space_before = Pt(6)
        style.paragraph_format.space_after = Pt(6)
        style.paragraph_format.first_line_indent = None
        style.paragraph_format.line_spacing = 1.2

    # ── Caption ─────────────────────────────────────────────────────────
    caption = _ensure_style(doc, "Caption")
    caption.font.name = "Times New Roman"
    caption.font.size = Pt(10.5)
    caption.font.bold = False
    caption.font.color.rgb = RGBColor(0, 0, 0)
    _set_east_asian_font(caption, "Heiti SC")
    caption.paragraph_format.alignment = WD_PARAGRAPH_ALIGNMENT.CENTER
    caption.paragraph_format.space_before = Pt(6)
    caption.paragraph_format.space_after = Pt(6)

    # ── TOC Heading ─────────────────────────────────────────────────────
    toc = _ensure_style(doc, "TOC Heading")
    toc.font.name = "Times New Roman"
    toc.font.size = Pt(15)
    toc.font.bold = True
    _set_east_asian_font(toc, "Heiti SC")
    toc.paragraph_format.alignment = WD_PARAGRAPH_ALIGNMENT.CENTER

    # ── TOC 1-3 ─────────────────────────────────────────────────────────
    for lvl in range(1, 4):
        toc_style = _ensure_style(doc, f"TOC {lvl}")
        toc_style.font.name = "Times New Roman"
        toc_style.font.size = Pt(12)
        toc_style.font.bold = lvl == 1
        _set_east_asian_font(toc_style, "Heiti SC" if lvl == 1 else "STSong")

    # ── Default page layout (A4) ────────────────────────────────────────
    section = doc.sections[0]
    section.page_width = Cm(21.0)
    section.page_height = Cm(29.7)
    section.top_margin = Cm(2.54)
    section.bottom_margin = Cm(2.54)
    section.left_margin = Cm(3.17)
    section.right_margin = Cm(3.17)

    # ── Add a dummy paragraph so styles are preserved ───────────────────
    doc.add_paragraph("", style="Normal")

    output_path.parent.mkdir(parents=True, exist_ok=True)
    doc.save(str(output_path))
    print(f"Generated: {output_path}")


if __name__ == "__main__":
    out = Path(__file__).resolve().parent.parent / "backend" / "app" / "core" / "templates" / "reference.docx"
    generate_reference_docx(out)
