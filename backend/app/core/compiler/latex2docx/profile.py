"""DocxProfile — data-driven configuration for LaTeX→DOCX conversion.

All template-specific behaviour (fonts, labels, numbering, styles, headers,
frontmatter layout) is driven by a ``DocxProfile`` instance loaded from the
template's ``meta.json["docx_profile"]`` field.  Every field has a sensible
default that reproduces the current (ucas_thesis / Chinese academic) hardcoded
behaviour, so existing templates work without any ``docx_profile`` at all.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field as dc_field
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Sub-configuration dataclasses
# ---------------------------------------------------------------------------

@dataclass
class LabelsConfig:
    """UI labels for abstract, TOC, captions, etc."""
    abstract: str = "摘要"
    toc: str = "目  录"
    figure_prefix: str = "图"
    table_prefix: str = "表"
    references: str = "参考文献"
    toc_update_hint: str = "请右键点击此处，选择\u201c更新域\u201d以生成目录"


@dataclass
class NumberingConfig:
    """Heading numbering formats and unnumbered heading list."""
    chapter_format: str = "第 {n} 章  {title}"
    section_format: str = "{chapter}.{section}  {title}"
    subsection_format: str = "{chapter}.{section}.{subsection}  {title}"
    subsubsection_format: str = (
        "{chapter}.{section}.{subsection}.{subsubsection}  {title}"
    )
    unnumbered_headings: list[str] = dc_field(default_factory=lambda: [
        "摘要", "abstract", "Abstract", "ABSTRACT", "致谢",
        "参考文献", "附录", "目录", "目  录", "References",
    ])


@dataclass
class FontsConfig:
    """Font assignments for body, headings, captions, monospace, and CJK."""
    body_latin: str = "Times New Roman"
    body_east_asian: str | None = "STSong"
    heading_latin: str = "Times New Roman"
    heading_east_asian: str | None = "Heiti SC"
    caption_east_asian: str | None = "Heiti SC"
    monospace: str = "Courier New"
    cjk_font_commands: dict[str, str] = dc_field(default_factory=lambda: {
        "heiti": "Heiti SC",
        "songti": "STSong",
        "kaiti": "Kaiti SC",
        "fangsong": "STFangsong",
    })


@dataclass
class HeadingStyleConfig:
    """Style spec for a single heading level."""
    level: int = 1
    font_size_pt: float = 15
    bold: bool = True


@dataclass
class NormalStyleConfig:
    """Style spec for normal body text."""
    font_size_pt: float = 12
    first_line_indent_pt: float = 24  # 2em CJK indent


@dataclass
class CaptionStyleConfig:
    """Style spec for captions."""
    font_size_pt: float = 10.5


@dataclass
class StylesConfig:
    """Aggregated style settings."""
    normal: NormalStyleConfig = dc_field(default_factory=NormalStyleConfig)
    headings: list[HeadingStyleConfig] = dc_field(default_factory=lambda: [
        HeadingStyleConfig(level=1, font_size_pt=15, bold=True),
        HeadingStyleConfig(level=2, font_size_pt=15, bold=True),
        HeadingStyleConfig(level=3, font_size_pt=14, bold=True),
        HeadingStyleConfig(level=4, font_size_pt=12, bold=True),
        HeadingStyleConfig(level=5, font_size_pt=12, bold=True),
        HeadingStyleConfig(level=6, font_size_pt=12, bold=False),
    ])
    caption: CaptionStyleConfig = dc_field(default_factory=CaptionStyleConfig)


@dataclass
class PageHeadersConfig:
    """Page header configuration.

    All assignments are content-driven — no fixed section indices.

    ``content_headers``: maps a content keyword/pattern to the header text
    to display.  E.g. ``{"摘要": "摘  要"}`` means a section whose content
    contains "摘要" gets header "摘  要".
    ``no_header_markers``: content markers that indicate a section should
    have no header and no page numbers (frontmatter, covers, declarations).
    ``chapter_pattern``: regex that matches numbered chapter headings;
    sections containing this get a STYLEREF dynamic header.
    ``odd_even``: enable different headers for odd/even pages (twoside).
    ``even_page_content``: text for even-page header; ``{title}`` is
    replaced with the document title at runtime.
    ``frontmatter_page_format``: page number format for front matter
    sections (``"upperRoman"``, ``"lowerRoman"``, ``"decimal"``).
    ``body_page_format``: page number format for body sections.
    """
    enable_styleref: bool = True
    header_font: str = "STSong"
    header_font_size_pt: float = 10.5
    header_rule_pt: float = 0.8
    chapter_pattern: str = r"第\s*\d+\s*章"
    content_headers: dict[str, str] = dc_field(default_factory=lambda: {
        "摘要": "摘  要",
        "Abstract": "Abstract",
        "目.*录": "目  录",
    })
    no_header_markers: list[str] = dc_field(default_factory=lambda: [
        "学位论文", "thesis submitted", "原创性声明", "授权使用声明",
    ])
    odd_even: bool = True
    even_page_content: str = "{title}"
    frontmatter_page_format: str = "upperRoman"
    body_page_format: str = "decimal"
    # Legacy fields kept for backward compat
    static_headers: dict[str, str] = dc_field(default_factory=dict)
    no_header_sections: list[int] = dc_field(default_factory=list)
    styleref_start_section: int = 6


# -- Frontmatter element / section configs --

@dataclass
class FrontmatterElementConfig:
    """A single element in a frontmatter section (text, spacer, logo, etc.)."""
    type: str = "text"               # text | spacer | logo | info_table |
                                     # boilerplate | signature_block | approval_table
    content: str = ""                # text content (may include {field} placeholders)
    field: str = ""                  # metadata field name to use as content
    source: str = ""                 # e.g. "school_logo" for logo element
    font: str = "STSong"
    size_pt: float = 12
    bold: bool = False
    align: str = "left"              # left | center | right
    lines: int = 1                   # for spacer: number of blank lines
    rows: list[list[str]] = dc_field(default_factory=list)  # for info_table / boilerplate
    space_before_pt: float | None = None
    condition: str = ""              # metadata field that must be truthy


@dataclass
class FrontmatterSectionConfig:
    """A logical section in frontmatter (e.g. cn_cover, en_cover, declaration)."""
    id: str = ""
    elements: list[FrontmatterElementConfig] = dc_field(default_factory=list)
    break_after: str = ""            # oddPage | evenPage | nextPage | "" (none)
    condition: str = ""              # metadata field that must be truthy


@dataclass
class BodySectionBreakConfig:
    """Rule for inserting a section break before a matching heading."""
    before_heading_text: str = ""      # exact match
    before_heading_pattern: str = ""   # regex match
    break_type: str = "oddPage"
    first_only: bool = False


@dataclass
class AutoTocConfig:
    """Auto TOC insertion configuration."""
    insert_before_first_chapter: bool = True
    heading_text: str = "目  录"
    heading_font: str = "Heiti SC"


@dataclass
class FrontmatterConfig:
    """Top-level frontmatter configuration."""
    sections: list[FrontmatterSectionConfig] = dc_field(default_factory=list)
    body_section_breaks: list[BodySectionBreakConfig] = dc_field(default_factory=list)
    auto_toc: AutoTocConfig | None = None


# ---------------------------------------------------------------------------
# DocxProfile — the main configuration object
# ---------------------------------------------------------------------------

@dataclass
class DocxProfile:
    """Complete DOCX export profile for a template.

    All fields have defaults that reproduce the current hardcoded behaviour
    for Chinese academic documents.
    """
    language: str = "zh-CN"
    labels: LabelsConfig = dc_field(default_factory=LabelsConfig)
    numbering: NumberingConfig = dc_field(default_factory=NumberingConfig)
    fonts: FontsConfig = dc_field(default_factory=FontsConfig)
    styles: StylesConfig = dc_field(default_factory=StylesConfig)
    page_headers: PageHeadersConfig = dc_field(default_factory=PageHeadersConfig)
    frontmatter: FrontmatterConfig = dc_field(default_factory=FrontmatterConfig)
    reference_docx: str | None = None
    doc_class_type: str = "report"
    template_dir: Path | None = None

    # -- Convenience methods ---------------------------------------------------

    def format_chapter(self, n: int, title: str) -> str:
        """Format a chapter heading using ``numbering.chapter_format``."""
        if title in self.numbering.unnumbered_headings:
            return title
        return self.numbering.chapter_format.format(n=n, title=title)

    def format_section(self, level: int, title: str,
                       chapter: int = 0, section: int = 0,
                       subsection: int = 0, subsubsection: int = 0) -> str:
        """Format a section/subsection/subsubsection heading."""
        if title in self.numbering.unnumbered_headings:
            return title
        fmt_map = {
            2: self.numbering.section_format,
            3: self.numbering.subsection_format,
            4: self.numbering.subsubsection_format,
        }
        fmt = fmt_map.get(level)
        if fmt is None:
            return title
        return fmt.format(
            chapter=chapter, section=section,
            subsection=subsection, subsubsection=subsubsection,
            title=title,
        )

    def get_cjk_font(self, cmd_name: str) -> str | None:
        """Look up the real font name for a CJK font command."""
        return self.fonts.cjk_font_commands.get(cmd_name)

    def is_cjk(self) -> bool:
        """Return True if this profile targets a CJK language."""
        return self.language.startswith(("zh", "ja", "ko"))

    def get_heading_style(self, level: int) -> HeadingStyleConfig | None:
        """Return the heading style config for a given level."""
        for hs in self.styles.headings:
            if hs.level == level:
                return hs
        return None


# ---------------------------------------------------------------------------
# Loading helpers
# ---------------------------------------------------------------------------

def _merge_dict(base: dict, override: dict) -> dict:
    """Shallow merge *override* into *base*, returning a new dict."""
    result = dict(base)
    result.update(override)
    return result


def _build_labels(data: dict) -> LabelsConfig:
    defaults = LabelsConfig()
    return LabelsConfig(
        abstract=data.get("abstract", defaults.abstract),
        toc=data.get("toc", defaults.toc),
        figure_prefix=data.get("figure_prefix", defaults.figure_prefix),
        table_prefix=data.get("table_prefix", defaults.table_prefix),
        references=data.get("references", defaults.references),
        toc_update_hint=data.get("toc_update_hint", defaults.toc_update_hint),
    )


def _build_numbering(data: dict) -> NumberingConfig:
    defaults = NumberingConfig()
    return NumberingConfig(
        chapter_format=data.get("chapter_format", defaults.chapter_format),
        section_format=data.get("section_format", defaults.section_format),
        subsection_format=data.get("subsection_format", defaults.subsection_format),
        subsubsection_format=data.get("subsubsection_format", defaults.subsubsection_format),
        unnumbered_headings=data.get("unnumbered_headings", defaults.unnumbered_headings),
    )


def _build_fonts(data: dict) -> FontsConfig:
    defaults = FontsConfig()
    return FontsConfig(
        body_latin=data.get("body_latin", defaults.body_latin),
        body_east_asian=data.get("body_east_asian", defaults.body_east_asian),
        heading_latin=data.get("heading_latin", defaults.heading_latin),
        heading_east_asian=data.get("heading_east_asian", defaults.heading_east_asian),
        caption_east_asian=data.get("caption_east_asian", defaults.caption_east_asian),
        monospace=data.get("monospace", defaults.monospace),
        cjk_font_commands=data.get("cjk_font_commands", defaults.cjk_font_commands),
    )


def _build_styles(data: dict) -> StylesConfig:
    defaults = StylesConfig()
    normal_data = data.get("normal", {})
    normal = NormalStyleConfig(
        font_size_pt=normal_data.get("font_size_pt", defaults.normal.font_size_pt),
        first_line_indent_pt=normal_data.get("first_line_indent_pt", defaults.normal.first_line_indent_pt),
    )
    headings_data = data.get("headings", None)
    if headings_data is not None:
        headings = [
            HeadingStyleConfig(
                level=h.get("level", i + 1),
                font_size_pt=h.get("font_size_pt", 12),
                bold=h.get("bold", True),
            )
            for i, h in enumerate(headings_data)
        ]
    else:
        headings = defaults.headings

    caption_data = data.get("caption", {})
    caption = CaptionStyleConfig(
        font_size_pt=caption_data.get("font_size_pt", defaults.caption.font_size_pt),
    )

    return StylesConfig(normal=normal, headings=headings, caption=caption)


def _build_page_headers(data: dict) -> PageHeadersConfig:
    defaults = PageHeadersConfig()
    return PageHeadersConfig(
        enable_styleref=data.get("enable_styleref", defaults.enable_styleref),
        header_font=data.get("header_font", defaults.header_font),
        header_font_size_pt=data.get("header_font_size_pt", defaults.header_font_size_pt),
        header_rule_pt=data.get("header_rule_pt", defaults.header_rule_pt),
        chapter_pattern=data.get("chapter_pattern", defaults.chapter_pattern),
        content_headers=data.get("content_headers", defaults.content_headers),
        no_header_markers=data.get("no_header_markers", defaults.no_header_markers),
        odd_even=data.get("odd_even", defaults.odd_even),
        even_page_content=data.get("even_page_content", defaults.even_page_content),
        frontmatter_page_format=data.get("frontmatter_page_format", defaults.frontmatter_page_format),
        body_page_format=data.get("body_page_format", defaults.body_page_format),
        # Legacy compat
        static_headers=data.get("static_headers", {}),
        no_header_sections=data.get("no_header_sections", []),
        styleref_start_section=data.get("styleref_start_section", 6),
    )


def _build_frontmatter_element(data: dict) -> FrontmatterElementConfig:
    return FrontmatterElementConfig(
        type=data.get("type", "text"),
        content=data.get("content", ""),
        field=data.get("field", ""),
        source=data.get("source", ""),
        font=data.get("font", "STSong"),
        size_pt=data.get("size_pt", 12),
        bold=data.get("bold", False),
        align=data.get("align", "left"),
        lines=data.get("lines", 1),
        rows=data.get("rows", []),
        space_before_pt=data.get("space_before_pt"),
        condition=data.get("condition", ""),
    )


def _build_frontmatter_section(data: dict) -> FrontmatterSectionConfig:
    elements = [_build_frontmatter_element(e) for e in data.get("elements", [])]
    return FrontmatterSectionConfig(
        id=data.get("id", ""),
        elements=elements,
        break_after=data.get("break_after", ""),
        condition=data.get("condition", ""),
    )


def _build_body_section_break(data: dict) -> BodySectionBreakConfig:
    return BodySectionBreakConfig(
        before_heading_text=data.get("before_heading_text", ""),
        before_heading_pattern=data.get("before_heading_pattern", ""),
        break_type=data.get("break_type", "oddPage"),
        first_only=data.get("first_only", False),
    )


def _build_auto_toc(data: dict) -> AutoTocConfig:
    defaults = AutoTocConfig()
    return AutoTocConfig(
        insert_before_first_chapter=data.get("insert_before_first_chapter", defaults.insert_before_first_chapter),
        heading_text=data.get("heading_text", defaults.heading_text),
        heading_font=data.get("heading_font", defaults.heading_font),
    )


def _build_frontmatter(data: dict) -> FrontmatterConfig:
    sections = [_build_frontmatter_section(s) for s in data.get("sections", [])]
    breaks = [_build_body_section_break(b) for b in data.get("body_section_breaks", [])]
    auto_toc_data = data.get("auto_toc")
    auto_toc = _build_auto_toc(auto_toc_data) if auto_toc_data else None
    return FrontmatterConfig(
        sections=sections,
        body_section_breaks=breaks,
        auto_toc=auto_toc,
    )


def _build_profile_from_dict(data: dict, doc_class_type: str = "report",
                              template_dir: Path | None = None) -> DocxProfile:
    """Build a DocxProfile from a raw dict (the ``docx_profile`` JSON value)."""
    return DocxProfile(
        language=data.get("language", "zh-CN"),
        labels=_build_labels(data.get("labels", {})),
        numbering=_build_numbering(data.get("numbering", {})),
        fonts=_build_fonts(data.get("fonts", {})),
        styles=_build_styles(data.get("styles", {})),
        page_headers=_build_page_headers(data.get("page_headers", {})),
        frontmatter=_build_frontmatter(data.get("frontmatter", {})),
        reference_docx=data.get("reference_docx"),
        doc_class_type=doc_class_type,
        template_dir=template_dir,
    )


def load_profile(template_id: str) -> DocxProfile:
    """Load a DocxProfile from a template's ``meta.json``.

    If the template has no ``docx_profile`` field, returns a default profile
    whose values reproduce the current hardcoded behaviour.
    """
    from app.core.templates.registry import get_template, get_template_dir

    profile_data: dict[str, Any] = {}
    doc_class_type = "report"
    template_dir: Path | None = None

    if template_id:
        tmpl = get_template(template_id)
        if tmpl:
            profile_data = tmpl.get("docx_profile", {}) or {}
            dct = tmpl.get("doc_class_type", "")
            if dct in ("book", "report"):
                doc_class_type = "report"
            elif dct == "article":
                doc_class_type = "article"
            template_dir = get_template_dir(template_id)

    return _build_profile_from_dict(profile_data, doc_class_type, template_dir)
