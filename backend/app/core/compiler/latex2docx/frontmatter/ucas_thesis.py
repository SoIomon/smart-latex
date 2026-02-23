"""UCAS thesis front-matter builder.

Generates: Chinese cover → English cover → Declarations → TOC + page headers.
Ported from word_postprocessor.py's ucas-specific functions.
"""

from __future__ import annotations

from docx import Document
from docx.enum.text import WD_PARAGRAPH_ALIGNMENT
from docx.shared import Pt

from app.core.compiler.word_preprocessor import WordExportMetadata
from app.core.compiler.word_postprocessor import (
    _make_paragraph as make_paragraph,
    _make_section_break as make_section_break,
    _make_logo_paragraph as make_logo_paragraph,
    _make_info_table as make_info_table,
    _make_toc_field_paragraph as make_toc_field_paragraph,
    _set_static_header as set_static_header,
    _set_styleref_header as set_styleref_header,
    _add_page_numbers as add_page_numbers,
)
from . import FrontmatterBuilder, register_builder


@register_builder("ucas_thesis")
class UcasThesisFrontmatter(FrontmatterBuilder):
    """Builds ucas_thesis front-matter: covers, declarations, TOC."""

    def build(self, doc: Document, metadata: WordExportMetadata) -> None:
        self._build_frontmatter(doc, metadata)
        self._build_body_pagebreaks(doc)
        self._build_page_headers(doc)

    def should_handle_command(self, cmd: str) -> bool:
        return cmd in ("maketitle", "MAKETITLE", "makedeclaration",
                       "tableofcontents", "frontmatter", "mainmatter")

    def _build_frontmatter(self, doc: Document, metadata: WordExportMetadata):
        """Insert all front-matter at the beginning."""
        body = doc.element.body
        first_element = body[0] if len(body) > 0 else None

        elements = []

        # 1. Chinese cover
        logo_elem = make_logo_paragraph(doc, metadata)
        if logo_elem is not None:
            elements.append(logo_elem)
            elements.append(make_paragraph(""))

        degree_word = metadata.degree or "硕士"
        elements.append(make_paragraph(
            f"{degree_word}学位论文",
            font_name="Heiti SC", font_size=Pt(28), bold=True,
            alignment=WD_PARAGRAPH_ALIGNMENT.CENTER,
        ))
        elements.append(make_paragraph(""))
        elements.append(make_paragraph(""))

        if metadata.title:
            elements.append(make_paragraph(
                metadata.title,
                font_name="Heiti SC", font_size=Pt(16), bold=True,
                alignment=WD_PARAGRAPH_ALIGNMENT.CENTER,
            ))
        elements.append(make_paragraph(""))
        elements.append(make_paragraph(""))

        info_rows = [
            ("作者姓名", metadata.author),
            ("指导教师", metadata.advisor),
            ("学位类别", f"{metadata.degreetype}{metadata.degree}" if metadata.degreetype else metadata.degree),
            ("学科专业", metadata.major),
            ("培养单位", metadata.institute),
        ]
        elements.append(make_info_table(info_rows))
        elements.append(make_paragraph(""))

        if metadata.date:
            elements.append(make_paragraph(
                metadata.date,
                font_name="STSong", font_size=Pt(12),
                alignment=WD_PARAGRAPH_ALIGNMENT.CENTER,
            ))

        elements.append(make_section_break("oddPage"))

        # 2. English cover
        if metadata.title_en:
            elements.append(make_paragraph(
                metadata.title_en,
                font_name="Times New Roman", font_size=Pt(16), bold=True,
                alignment=WD_PARAGRAPH_ALIGNMENT.CENTER,
                space_before=Pt(80),
            ))

        boilerplate = [
            "A thesis submitted to",
            "University of Chinese Academy of Sciences",
            "in partial fulfillment of the requirement for the degree of",
            f"{metadata.degree_en} of {metadata.degreetype_en}" if metadata.degree_en else "",
        ]
        first_bp = True
        for line in boilerplate:
            if line:
                elements.append(make_paragraph(
                    line, font_name="Times New Roman", font_size=Pt(12),
                    alignment=WD_PARAGRAPH_ALIGNMENT.CENTER,
                    space_before=Pt(100) if first_bp else None,
                ))
                first_bp = False

        if metadata.author_en:
            elements.append(make_paragraph(
                f"By {metadata.author_en}",
                font_name="Times New Roman", font_size=Pt(12),
                alignment=WD_PARAGRAPH_ALIGNMENT.CENTER,
                space_before=Pt(80),
            ))
        if metadata.advisor_en:
            prefix = (
                self.profile.labels.advisor_en_prefix
                if self.profile else "Supervisor: "
            )
            advisor_text = metadata.advisor_en
            if prefix and not advisor_text.lower().startswith(prefix.strip().lower()):
                advisor_text = f"{prefix}{advisor_text}"
            elements.append(make_paragraph(
                advisor_text,
                font_name="Times New Roman", font_size=Pt(12),
                alignment=WD_PARAGRAPH_ALIGNMENT.CENTER,
            ))
        if metadata.institute_en:
            elements.append(make_paragraph(
                metadata.institute_en,
                font_name="Times New Roman", font_size=Pt(12),
                alignment=WD_PARAGRAPH_ALIGNMENT.CENTER,
                space_before=Pt(80),
            ))
        if metadata.date_en:
            elements.append(make_paragraph(
                metadata.date_en,
                font_name="Times New Roman", font_size=Pt(12),
                alignment=WD_PARAGRAPH_ALIGNMENT.CENTER,
                space_before=Pt(40),
            ))

        elements.append(make_section_break("oddPage"))

        # 3. Originality declaration
        elements.append(make_paragraph(
            "中国科学院大学",
            font_name="Heiti SC", font_size=Pt(14), bold=True,
            alignment=WD_PARAGRAPH_ALIGNMENT.CENTER,
        ))
        elements.append(make_paragraph(
            "学位论文原创性声明",
            font_name="Heiti SC", font_size=Pt(14), bold=True,
            alignment=WD_PARAGRAPH_ALIGNMENT.CENTER,
        ))
        elements.append(make_paragraph(""))
        elements.append(make_paragraph(
            "本人郑重声明：所呈交的学位论文是本人在导师的指导下独立进行研究工作所取得的成果。"
            "尽我所知，除文中已经注明引用的内容外，本论文不包含任何其他个人或集体已经发表或撰写过的研究成果。"
            "对论文所涉及的研究工作做出贡献的其他个人和集体，均已在文中以明确方式标明或致谢。",
            font_name="STSong", font_size=Pt(10.5),
        ))
        elements.append(make_paragraph(""))
        elements.append(make_paragraph(
            "作者签名：____________    日    期：____________",
            font_name="STSong", font_size=Pt(10.5),
            alignment=WD_PARAGRAPH_ALIGNMENT.CENTER,
        ))
        elements.append(make_paragraph(""))
        elements.append(make_paragraph(""))
        elements.append(make_paragraph(""))

        # 4. Authorization declaration
        elements.append(make_paragraph(
            "中国科学院大学",
            font_name="Heiti SC", font_size=Pt(14), bold=True,
            alignment=WD_PARAGRAPH_ALIGNMENT.CENTER,
        ))
        elements.append(make_paragraph(
            "学位论文授权使用声明",
            font_name="Heiti SC", font_size=Pt(14), bold=True,
            alignment=WD_PARAGRAPH_ALIGNMENT.CENTER,
        ))
        elements.append(make_paragraph(""))
        elements.append(make_paragraph(
            "本人完全了解并同意遵守中国科学院有关保存和使用学位论文的规定，即中国科学院有权保留送交学位论文的副本，"
            "允许该论文被查阅，可以按照学术研究公开原则和保护知识产权的原则公布该论文的全部或部分内容，"
            "可以采用影印、缩印或其他复制手段保存、汇编本学位论文。",
            font_name="STSong", font_size=Pt(10.5),
        ))
        elements.append(make_paragraph(""))
        elements.append(make_paragraph(
            "涉密及延迟公开的学位论文在解密或延迟期后适用本声明。",
            font_name="STSong", font_size=Pt(10.5),
        ))
        elements.append(make_paragraph(""))
        elements.append(make_paragraph(
            "作者签名：__________    导师签名：__________",
            font_name="STSong", font_size=Pt(10.5),
            alignment=WD_PARAGRAPH_ALIGNMENT.CENTER,
        ))
        elements.append(make_paragraph(
            "日    期：__________    日    期：__________",
            font_name="STSong", font_size=Pt(10.5),
            alignment=WD_PARAGRAPH_ALIGNMENT.CENTER,
        ))
        elements.append(make_section_break("oddPage"))

        # Insert at beginning
        if first_element is not None:
            insert_idx = body.index(first_element)
            for elem in elements:
                body.insert(insert_idx, elem)
                insert_idx += 1
        else:
            for elem in elements:
                body.append(elem)

    def _build_body_pagebreaks(self, doc: Document):
        """Insert section breaks between 摘要, Abstract, TOC, and body.

        Expected result: each of 摘要 / Abstract / 目录 / body gets its
        own section so headers and page numbering can differ per section.
        """
        import re as _re
        body = doc.element.body

        abstract_en_elem = None
        toc_elem = None
        first_chapter_elem = None

        for para in doc.paragraphs:
            text = para.text.strip()
            is_heading1 = para.style and para.style.style_id == "Heading1"

            if text.lower() == "abstract" and abstract_en_elem is None:
                abstract_en_elem = para._element
            elif ("目" in text and "录" in text) and toc_elem is None:
                toc_elem = para._element
            elif is_heading1 and _re.match(r"第\s*\d+\s*章", text) and first_chapter_elem is None:
                first_chapter_elem = para._element

        # Helper: insert section break before an element (safe)
        def _insert_break_before(elem):
            try:
                idx = list(body).index(elem)
                body.insert(idx, make_section_break("oddPage"))
            except ValueError:
                pass

        # Section break before Abstract (separates 摘要 from Abstract)
        if abstract_en_elem is not None:
            _insert_break_before(abstract_en_elem)

        # Section break before 目录 (separates Abstract from TOC)
        if toc_elem is not None:
            _insert_break_before(toc_elem)
            # Also add section break before first chapter (after TOC)
            if first_chapter_elem is not None:
                _insert_break_before(first_chapter_elem)
        elif first_chapter_elem is not None:
            # No TOC exists — insert TOC + section breaks before body
            try:
                idx = list(body).index(first_chapter_elem)
                toc_elems = [
                    make_section_break("oddPage"),
                    make_paragraph(
                        "目  录",
                        font_name="Heiti SC", font_size=Pt(16), bold=True,
                        alignment=WD_PARAGRAPH_ALIGNMENT.CENTER,
                    ),
                    make_paragraph(""),
                    make_toc_field_paragraph(),
                    make_section_break("oddPage"),
                ]
                for i, elem in enumerate(toc_elems):
                    body.insert(idx + i, elem)
            except ValueError:
                pass

    def _build_page_headers(self, doc: Document):
        """Add section-specific headers."""
        sections = list(doc.sections)
        header_map = {
            3: "摘  要",
            4: "Abstract",
            5: "目  录",
        }

        for i, section in enumerate(sections):
            if i < 3:
                header = section.header
                header.is_linked_to_previous = False
                for p in header.paragraphs:
                    p.clear()
                continue

            if i in header_map:
                set_static_header(section, header_map[i])
            elif i >= 6:
                set_styleref_header(section)
