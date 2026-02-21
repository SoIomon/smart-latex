"""Generic front-matter builder — simple title/author/date cover page."""

from __future__ import annotations

from docx import Document
from docx.enum.text import WD_PARAGRAPH_ALIGNMENT
from docx.shared import Pt

from app.core.compiler.word_preprocessor import WordExportMetadata
from app.core.compiler.word_postprocessor import (
    _make_paragraph as make_paragraph,
    _make_page_break as make_page_break,
)
from . import FrontmatterBuilder


class GenericFrontmatter(FrontmatterBuilder):
    """Builds a simple cover page with title, author, and date."""

    def build(self, doc: Document, metadata: WordExportMetadata) -> None:
        if not metadata.title:
            return

        body = doc.element.body
        first_element = body[0] if len(body) > 0 else None

        elements = []

        # Spacer
        elements.append(make_paragraph(""))
        elements.append(make_paragraph(""))
        elements.append(make_paragraph(""))

        # Title
        if metadata.title:
            elements.append(make_paragraph(
                metadata.title,
                font_name="Heiti SC",
                font_size=Pt(22),
                bold=True,
                alignment=WD_PARAGRAPH_ALIGNMENT.CENTER,
            ))
            elements.append(make_paragraph(""))

        # Author
        if metadata.author:
            elements.append(make_paragraph(
                metadata.author,
                font_name="STSong",
                font_size=Pt(16),
                alignment=WD_PARAGRAPH_ALIGNMENT.CENTER,
            ))

        # Institute
        if metadata.institute:
            elements.append(make_paragraph(
                metadata.institute,
                font_name="STSong",
                font_size=Pt(14),
                alignment=WD_PARAGRAPH_ALIGNMENT.CENTER,
            ))

        # Date
        if metadata.date or metadata.report_date:
            date_text = metadata.date or metadata.report_date
            elements.append(make_paragraph(
                date_text,
                font_name="STSong",
                font_size=Pt(14),
                alignment=WD_PARAGRAPH_ALIGNMENT.CENTER,
            ))

        elements.append(make_page_break())

        # Insert at beginning
        if first_element is not None:
            insert_idx = body.index(first_element)
            for elem in elements:
                body.insert(insert_idx, elem)
                insert_idx += 1
        else:
            for elem in elements:
                body.append(elem)

    def should_handle_command(self, cmd: str) -> bool:
        return cmd in ("maketitle",)
