"""Layer 1: LaTeX preprocessor for Word export.

Strips/replaces commands that Pandoc cannot handle, extracts cover-page
metadata so it can be rebuilt later by the post-processor.
"""

import re
from dataclasses import dataclass, field


@dataclass
class WordExportMetadata:
    """Metadata extracted from LaTeX during preprocessing."""

    # Cover page fields
    title: str = ""
    author: str = ""
    institute: str = ""
    report_date: str = ""
    doc_number: str = ""
    phase_mark: str = ""
    classification: str = ""
    page_count: str = ""
    writer: str = ""
    write_date: str = ""
    proofreader: str = ""
    proofread_date: str = ""
    reviewer: str = ""
    review_date: str = ""
    standard_reviewer: str = ""
    standard_review_date: str = ""
    approver: str = ""
    approve_date: str = ""

    # ucas_thesis fields
    school_logo: str = ""       # \schoollogo{ucas_logo} — image basename
    school_logo_scale: float = 0.0  # \schoollogo[scale=0.095] — scale factor
    advisor: str = ""
    degree: str = ""
    degreetype: str = ""
    major: str = ""
    date: str = ""
    title_en: str = ""
    author_en: str = ""
    advisor_en: str = ""
    degree_en: str = ""
    degreetype_en: str = ""
    major_en: str = ""
    institute_en: str = ""
    date_en: str = ""

    # Revision records
    revision_records: list[dict] = field(default_factory=list)

    # Page layout
    geometry: dict = field(default_factory=dict)

    # Footer text
    footer_text: str = ""

    # Whether a cover page was found and extracted
    has_cover: bool = False

    # Template info
    template_id: str = ""

    # Page numbering (auto-detected from LaTeX)
    frontmatter_page_format: str | None = None   # "upperRoman" / "lowerRoman" / "decimal"
    body_page_format: str | None = None           # "decimal" etc.
    twoside: bool = False                         # from \documentclass[twoside]


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def preprocess_latex_for_word(
    content: str, template_id: str = ""
) -> tuple[str, WordExportMetadata]:
    """Preprocess LaTeX content for Pandoc Word conversion.

    Returns ``(cleaned_content, metadata)``.
    """
    metadata = WordExportMetadata(template_id=template_id)

    # Split into preamble and body at the *real* \begin{document}
    # (not one inside a LaTeX % comment)
    doc_match = re.search(r"^[^%\n]*\\begin\{document\}", content, re.MULTILINE)
    if not doc_match:
        return content, metadata

    # The match includes any prefix before \begin{document} on that line;
    # find the exact start of \begin{document} within the match.
    bd_offset = doc_match.group().index("\\begin{document}")
    split_pos = doc_match.start() + bd_offset
    preamble = content[:split_pos]
    body = content[split_pos:]

    # ── Extract metadata from preamble ──────────────────────────────────
    _extract_geometry(preamble, metadata)
    _extract_preamble_metadata(preamble, metadata)

    # ── Process preamble ────────────────────────────────────────────────
    preamble = _normalize_documentclass(preamble)
    preamble = _clean_preamble(preamble)

    # ── Process body ────────────────────────────────────────────────────
    body = _process_body(body, metadata)

    # Clean up excessive blank lines
    result = preamble + body
    result = re.sub(r"\n{3,}", "\n\n", result)
    return result, metadata


# ---------------------------------------------------------------------------
# Preamble processing
# ---------------------------------------------------------------------------

def _extract_preamble_metadata(preamble: str, metadata: WordExportMetadata) -> None:
    """Extract title/author/date from standard LaTeX preamble commands."""
    m = re.search(r"(?<!%)\\title\{(.*?)\}%?", preamble, re.DOTALL)
    if m:
        metadata.title = re.sub(r"[{}]", "", m.group(1)).strip()
    m = re.search(r"(?<!%)\\author\{(.*?)\}%?", preamble, re.DOTALL)
    if m:
        metadata.author = re.sub(r"[{}]", "", m.group(1)).strip()

    # ucas_thesis-specific fields
    _UCAS_FIELDS = [
        ("advisor", "advisor"), ("degree", "degree"), ("degreetype", "degreetype"),
        ("major", "major"), ("institute", "institute"), ("date", "date"),
        ("title_en", "TITLE"), ("author_en", "AUTHOR"), ("advisor_en", "ADVISOR"),
        ("degree_en", "DEGREE"), ("degreetype_en", "DEGREETYPE"),
        ("major_en", "MAJOR"), ("institute_en", "INSTITUTE"), ("date_en", "DATE"),
    ]
    for attr, cmd in _UCAS_FIELDS:
        m = re.search(rf"\\{cmd}\{{([^}}]*)\}}", preamble)
        if m:
            setattr(metadata, attr, m.group(1).replace("~", " ").strip())

    # schoollogo: \schoollogo[scale=0.095]{ucas_logo}
    m = re.search(r"\\schoollogo(?:\[([^\]]*)\])?\{([^}]*)\}", preamble)
    if m:
        opts = m.group(1) or ""
        metadata.school_logo = m.group(2).strip()
        scale_m = re.search(r"scale\s*=\s*([\d.]+)", opts)
        if scale_m:
            metadata.school_logo_scale = float(scale_m.group(1))

    # Detect twoside from \documentclass options
    dc_match = re.search(r"\\documentclass\[([^\]]*)\]", preamble)
    if dc_match:
        opts = dc_match.group(1)
        if re.search(r"\btwoside\b", opts):
            metadata.twoside = True

    if metadata.template_id == "ucas_thesis" and metadata.title:
        metadata.has_cover = True


def _normalize_documentclass(preamble: str) -> str:
    """Replace custom documentclass with a standard one Pandoc can handle."""
    # Map custom classes to standard equivalents
    _CUSTOM_CLASSES = {
        "Style/ucasthesis": "ctexrep",
        "ucasthesis": "ctexrep",
    }
    m = re.search(r"\\documentclass(?:\[([^\]]*)\])?\{([^}]+)\}", preamble)
    if not m:
        return preamble
    doc_class = m.group(2)
    replacement = _CUSTOM_CLASSES.get(doc_class)
    if replacement:
        preamble = preamble[: m.start()] + f"\\documentclass[12pt,a4paper]{{{replacement}}}" + preamble[m.end() :]
    return preamble


def _clean_preamble(preamble: str) -> str:
    """Remove preamble commands that Pandoc cannot handle."""

    # Remove custom Style/ packages (ucas_thesis, etc.)
    preamble = re.sub(r"\\usepackage(?:\[[^\]]*\])?\{Style/[^}]+\}[^\n]*\n?", "", preamble)

    # Packages to remove entirely
    _REMOVE_PACKAGES = {
        "fontspec", "fancyhdr", "titlesec", "titletoc", "lastpage",
        "bookmark", "setspace", "geometry",
    }
    for pkg in _REMOVE_PACKAGES:
        preamble = re.sub(
            rf"\\usepackage(?:\[[^\]]*\])?\{{{pkg}\}}[^\n]*\n?", "", preamble
        )

    # ucas_thesis custom preamble commands (with brace arguments)
    _PREAMBLE_CMDS_WITH_ARG = [
        "confidential", "schoollogo", "advisor", "degree", "degreetype",
        "major", "institute",
        "TITLE", "AUTHOR", "ADVISOR", "DEGREE", "DEGREETYPE", "MAJOR",
        "INSTITUTE", "DATE",
    ]
    for cmd in _PREAMBLE_CMDS_WITH_ARG:
        preamble = re.sub(rf"\\{cmd}(?:\[[^\]]*\])?\{{[^}}]*\}}[^\n]*\n?", "", preamble)

    # CJK font declarations
    preamble = re.sub(r"\\newCJKfontfamily(?:\[[^\]]*\])?\\?\w+\{[^}]*\}(?:\[[^\]]*\])?", "", preamble)
    preamble = re.sub(r"\\setCJK(?:main|sans|mono)font(?:\[[^\]]*\])?\{[^}]*\}", "", preamble)
    preamble = re.sub(r"\\setmainfont(?:\[[^\]]*\])?\{[^}]*\}", "", preamble)

    # titlesec / titletoc — these span multiple lines with nested braces
    # Pattern matches one level of brace nesting: {text{inner}text}
    _BG = r"\{(?:[^{}]|\{[^{}]*\})*\}"
    preamble = re.sub(
        rf"\\titleformat\*?\s*{_BG}(?:\s*\[[^\]]*\])?\s*(?:{_BG}\s*)*",
        "", preamble, flags=re.DOTALL,
    )
    preamble = re.sub(
        rf"\\titlespacing\*?\s*{_BG}\s*(?:{_BG}\s*)*",
        "", preamble, flags=re.DOTALL,
    )
    preamble = re.sub(
        rf"\\titlecontents\s*{_BG}(?:\s*\[[^\]]*\])?\s*(?:{_BG}\s*)*",
        "", preamble, flags=re.DOTALL,
    )

    # fancyhdr commands
    preamble = re.sub(r"\\pagestyle\{[^}]*\}", "", preamble)
    preamble = re.sub(r"\\fancyhf\{[^}]*\}", "", preamble)
    preamble = re.sub(r"\\fancyhead(?:\[[^\]]*\])?\{[^}]*\}", "", preamble)
    preamble = re.sub(r"\\fancyfoot(?:\[[^\]]*\])?\{[^}]*\}", "", preamble)
    preamble = re.sub(r"\\renewcommand\{\\headrulewidth\}\{[^}]*\}", "", preamble)
    preamble = re.sub(r"\\renewcommand\{\\footrulewidth\}\{[^}]*\}", "", preamble)
    # Remove fancypagestyle blocks (use brace-depth counting)
    preamble = _remove_fancypagestyle_blocks(preamble)

    # hypersetup
    preamble = re.sub(r"\\hypersetup\s*\{[^}]*\}", "", preamble, flags=re.DOTALL)

    # caption setup
    preamble = re.sub(r"\\DeclareCaptionFont\{[^}]*\}\{[^}]*\}", "", preamble)
    preamble = re.sub(r"\\captionsetup(?:\[[^\]]*\])?\{[^}]*\}", "", preamble, flags=re.DOTALL)
    preamble = re.sub(r"\\renewcommand\{\\figurename\}\{[^}]*\}", "", preamble)
    preamble = re.sub(r"\\renewcommand\{\\tablename\}\{[^}]*\}", "", preamble)

    # geometry
    preamble = re.sub(r"\\geometry\s*\{[^}]*\}", "", preamble, flags=re.DOTALL)

    # spacing commands
    preamble = re.sub(r"\\onehalfspacing", "", preamble)
    preamble = re.sub(r"\\doublespacing", "", preamble)
    preamble = re.sub(r"\\singlespacing", "", preamble)
    preamble = re.sub(r"\\setlength\{\\parindent\}\{[^}]*\}", "", preamble)
    preamble = re.sub(r"\\setlength\{\\parskip\}\{[^}]*\}", "", preamble)
    preamble = re.sub(r"\\renewcommand\{\\arraystretch\}\{[^}]*\}", "", preamble)

    # Section counter and numbering format commands
    preamble = re.sub(r"\\setcounter\{(?:secnumdepth|tocdepth)\}\{[^}]*\}", "", preamble)
    preamble = re.sub(
        r"\\renewcommand\{\\the(?:chapter|section|subsection|subsubsection|paragraph|subparagraph)\}.*",
        "", preamble,
    )
    preamble = re.sub(r"\\renewcommand\{\\contentsname\}\{[^}]*\}", "", preamble)

    # Custom command definitions (\newcommand{\mainpagegeometry}{...})
    preamble = _remove_balanced_command(preamble, r"\\newcommand\{\\mainpagegeometry\}")

    # Remove title/author/date to prevent Pandoc from generating a title block
    preamble = re.sub(r"(?<!%)\\title\{.*?\}%?[^\n]*\n?", "", preamble, flags=re.DOTALL)
    preamble = re.sub(r"(?<!%)\\author\{.*?\}%?[^\n]*\n?", "", preamble, flags=re.DOTALL)
    preamble = re.sub(r"(?<!%)\\date\{.*?\}%?[^\n]*\n?", "", preamble, flags=re.DOTALL)

    return preamble


def _remove_fancypagestyle_blocks(text: str) -> str:
    """Remove \\fancypagestyle{name}{...} blocks handling nested braces."""
    result = []
    i = 0
    pattern = re.compile(r"\\fancypagestyle\{")
    while i < len(text):
        m = pattern.search(text, i)
        if not m:
            result.append(text[i:])
            break
        result.append(text[i : m.start()])
        # Skip past the opening \fancypagestyle{name}
        j = m.end()
        # Skip the name and closing brace
        while j < len(text) and text[j] != "}":
            j += 1
        j += 1  # past the }
        # Now skip the body {..}
        j = _skip_balanced_braces(text, j)
        i = j
    return "".join(result)


def _remove_balanced_command(text: str, cmd_pattern: str) -> str:
    """Remove a command followed by a balanced brace group."""
    pattern = re.compile(cmd_pattern)
    result = []
    i = 0
    while i < len(text):
        m = pattern.search(text, i)
        if not m:
            result.append(text[i:])
            break
        result.append(text[i : m.start()])
        j = _skip_balanced_braces(text, m.end())
        i = j
    return "".join(result)


def _skip_balanced_braces(text: str, start: int) -> int:
    """Skip from *start* past the next balanced ``{...}`` group."""
    # Find opening brace
    i = start
    while i < len(text) and text[i] != "{":
        i += 1
    if i >= len(text):
        return i
    depth = 0
    while i < len(text):
        if text[i] == "{":
            depth += 1
        elif text[i] == "}":
            depth -= 1
            if depth == 0:
                return i + 1
        i += 1
    return i


# ---------------------------------------------------------------------------
# Page numbering extraction
# ---------------------------------------------------------------------------

_PAGENUMBERING_MAP = {
    "roman": "lowerRoman",
    "Roman": "upperRoman",
    "arabic": "decimal",
    "alph": "lowerLetter",
    "Alph": "upperLetter",
}


def _extract_page_numbering(body: str, metadata: WordExportMetadata) -> None:
    r"""Extract page numbering formats from ``\pagenumbering{...}`` commands.

    Must be called *before* ``_strip_thesis_frontmatter`` removes ``\mainmatter``.
    """
    # Collect all \pagenumbering{X} in order
    numberings = re.findall(r"\\pagenumbering\{(\w+)\}", body)
    has_mainmatter = bool(re.search(r"\\mainmatter\b", body))

    if not numberings:
        return

    # First \pagenumbering → frontmatter format
    mapped = _PAGENUMBERING_MAP.get(numberings[0])
    if mapped:
        metadata.frontmatter_page_format = mapped

    # Second \pagenumbering → body format
    if len(numberings) >= 2:
        mapped2 = _PAGENUMBERING_MAP.get(numberings[1])
        if mapped2:
            metadata.body_page_format = mapped2
    elif has_mainmatter:
        # \mainmatter implies \pagenumbering{arabic}
        metadata.body_page_format = "decimal"


# ---------------------------------------------------------------------------
# Body processing
# ---------------------------------------------------------------------------

def _process_body(body: str, metadata: WordExportMetadata) -> str:
    """Clean the document body for Pandoc."""

    # ── Extract cover page (comm_research_report) ───────────────────────
    body = _extract_cover_page(body, metadata)

    # ── Extract revision records ────────────────────────────────────────
    body = _extract_revision_records(body, metadata)

    # ── Extract page numbering (before strip removes \mainmatter) ──────
    _extract_page_numbering(body, metadata)

    # ── Remove thesis front-matter commands (ucas_thesis etc.) ──────────
    body = _strip_thesis_frontmatter(body)

    # ── Replace font commands ───────────────────────────────────────────
    body = _replace_font_commands(body)

    # ── Remove body-level formatting commands ───────────────────────────
    body = re.sub(r"\\(?:this)?pagestyle\{[^}]*\}", "", body)
    body = re.sub(r"\\pagenumbering\{[^}]*\}", "", body)
    body = re.sub(r"\\mainpagegeometry\b", "", body)
    body = re.sub(r"\\newgeometry\s*\{[^}]*\}", "", body, flags=re.DOTALL)
    body = re.sub(r"\\vfill\b", "", body)
    body = re.sub(r"\\setcounter\{[^}]*\}\{[^}]*\}", "", body)
    body = re.sub(r"\\linespread\{[^}]*\}", "", body)

    return body


def _strip_thesis_frontmatter(body: str) -> str:
    """Remove thesis-specific front-matter commands (ucas_thesis etc.)."""
    # Standalone commands (no arguments)
    for cmd in ("frontmatter", "mainmatter", "backmatter",
                "maketitle", "MAKETITLE", "makedeclaration",
                "listoffigures", "listoftables", "tableofcontents"):
        body = re.sub(rf"\\{cmd}\b[^\n]*\n?", "", body)

    # \intobmk\chapter*{...} → \chapter*{...}  (strip prefix, keep \chapter)
    # \intobmk*{\cleardoublepage}{\contentsname} → remove entire line
    body = re.sub(r"\\intobmk\*?(?:\{[^}]*\})+[^\n]*\n?", "", body)
    # \intobmk before \chapter (no brace group) → just remove prefix
    body = re.sub(r"\\intobmk\s*(?=\\chapter)", "", body)

    # \keywords{...} / \KEYWORDS{...} → bold line
    body = re.sub(r"\\keywords\{([^}]*)\}", r"\\textbf{关键词：}\1", body)
    body = re.sub(r"\\KEYWORDS\{([^}]*)\}", r"\\textbf{Keywords: }\1", body)

    # \cleardoublepage inside groups
    body = re.sub(r"\\cleardoublepage\b", r"\\clearpage", body)

    # \contentsname / \listfigurename / \listtablename standalone refs
    body = re.sub(r"\{\\contentsname\}", "{目录}", body)
    body = re.sub(r"\{\\listfigurename\}", "{图目录}", body)
    body = re.sub(r"\{\\listtablename\}", "{表目录}", body)

    return body


def _extract_cover_page(body: str, metadata: WordExportMetadata) -> str:
    """Extract complex cover page content and save metadata."""
    # Only extract if this looks like a comm_research_report-style cover
    if "\\begingroup" not in body:
        return body

    # Find the cover region: \begingroup ... \endgroup
    bg_match = re.search(r"\\begingroup", body)
    eg_match = re.search(r"\\endgroup", body)
    if not bg_match or not eg_match:
        return body

    cover_text = body[bg_match.start() : eg_match.end()]

    # Check it looks like a cover page (has approval table markers)
    if "编写" not in cover_text and "批准" not in cover_text:
        return body

    _parse_cover_metadata(cover_text, metadata)
    metadata.has_cover = True

    # Remove the cover block from body
    body = body[: bg_match.start()] + body[eg_match.end() :]
    # Also remove any \thispagestyle{coverpage} and \vspace before it
    body = re.sub(r"\\thispagestyle\{coverpage\}", "", body)

    return body


def _parse_cover_metadata(cover_text: str, metadata: WordExportMetadata) -> None:
    """Extract structured data from cover-page LaTeX."""

    def _clean(text: str) -> str:
        text = re.sub(r"\\(?:heiti|songti|fangsong|kaiti|bfseries|normalfont|selectfont|centering)\b", "", text)
        text = re.sub(r"\\fontsize\{[^}]*\}\{[^}]*\}", "", text)
        text = re.sub(r"\\(?:textbf|textit)\{([^}]*)\}", r"\1", text)
        text = re.sub(r"\\quad\s*", " ", text)
        text = re.sub(r"[{}]", "", text)
        return text.strip()

    # Field-value pairs in metadata table
    field_map = {
        "文件编号": "doc_number",
        "阶段标志": "phase_mark",
    }
    for label, attr in field_map.items():
        m = re.search(rf"{label}\s*&\s*(.*?)\\\\", cover_text)
        if m:
            setattr(metadata, attr, _clean(m.group(1)))

    # Fields with \quad
    m = re.search(r"密\s*\\quad\s*级\s*&\s*(.*?)\\\\", cover_text)
    if m:
        metadata.classification = _clean(m.group(1))
    m = re.search(r"页\s*\\quad\s*数\s*&\s*(.*?)\\\\", cover_text)
    if m:
        metadata.page_count = _clean(m.group(1))

    # Title — extract cell content between & and \\
    m = re.search(r"名\s*\\quad\s*称\s*&\s*(.*?)\\\\", cover_text, re.DOTALL)
    if m:
        metadata.title = _clean(m.group(1))

    # Approval table
    approval_fields = [
        ("编写", "writer", "write_date"),
        ("校对", "proofreader", "proofread_date"),
        ("审核", "reviewer", "review_date"),
        ("标审", "standard_reviewer", "standard_review_date"),
        ("批准", "approver", "approve_date"),
    ]
    for label, name_attr, date_attr in approval_fields:
        m = re.search(
            rf"{label}\s*&\s*\\centering\s*(.*?)\s*&\s*(.*?)\s*\\tabularnewline",
            cover_text,
        )
        if m:
            setattr(metadata, name_attr, _clean(m.group(1)))
            setattr(metadata, date_attr, _clean(m.group(2)))

    # Institute (large font near bottom)
    m = re.search(r"\\fontsize\{18bp\}[^}]*\}\\selectfont\\heiti\\bfseries\s+(.*?)(?:\}|\\\\)", cover_text, re.DOTALL)
    if m:
        metadata.institute = _clean(m.group(1))

    # Date (second large font near bottom)
    vfill_pos = cover_text.rfind("\\vfill")
    if vfill_pos != -1:
        tail = cover_text[vfill_pos:]
        m = re.search(r"\\fontsize\{16bp\}[^}]*\}\\selectfont\\heiti\\bfseries\s+(.*?)(?:\}|\\\\)", tail, re.DOTALL)
        if m:
            metadata.report_date = _clean(m.group(1))


def _extract_revision_records(body: str, metadata: WordExportMetadata) -> str:
    """Extract revision records table and replace with Pandoc-friendly markup."""
    marker = re.search(r"文档修改记录", body)
    if not marker:
        return body

    # Find the tabularx environment after the marker
    search_region = body[marker.start() :]
    tabularx_match = re.search(
        r"(\\begin\{tabularx\}.*?\\end\{tabularx\})", search_region, re.DOTALL
    )
    if not tabularx_match:
        return body

    table_text = tabularx_match.group(1)

    # Parse rows by splitting on \tabularnewline then splitting cells by &
    raw_rows = re.split(r"\\tabularnewline", table_text)
    records = []
    for raw_row in raw_rows:
        # Skip header / empty / structural lines
        if "\\heiti" in raw_row or "\\begin{" in raw_row or "\\end{" in raw_row:
            continue
        cells = raw_row.split("&")
        if len(cells) < 5:
            continue
        version = re.sub(r"\\[a-zA-Z]+\b", "", cells[0]).strip()
        if not version:
            continue
        records.append({
            "version": version,
            "date": cells[1].strip(),
            "change_summary": cells[2].strip(),
            "modified_sections": cells[3].strip(),
            "remarks": cells[4].replace("\\hline", "").strip(),
        })
    metadata.revision_records = records

    # Find the entire section (center block + tabularx) to replace
    # Look backwards from marker for \begin{center}
    center_start = body.rfind("\\begin{center}", 0, marker.start())
    if center_start == -1:
        center_start = marker.start()
    table_abs_end = marker.start() + tabularx_match.end()

    # Build simple replacement
    replacement = "\n\\section*{文档修改记录}\n\n"
    if records:
        cols = "|l|l|p{5cm}|l|l|"
        replacement += f"\\begin{{tabular}}{{{cols}}}\n\\hline\n"
        replacement += "\\textbf{版本} & \\textbf{日期} & \\textbf{更改摘要} & \\textbf{修改章节} & \\textbf{备注} \\\\\n\\hline\n"
        for rec in records:
            replacement += (
                f"{rec['version']} & {rec['date']} & {rec['change_summary']} "
                f"& {rec['modified_sections']} & {rec['remarks']} \\\\\n\\hline\n"
            )
        replacement += "\\end{tabular}\n"
    replacement += "\n\\clearpage\n"

    body = body[:center_start] + replacement + body[table_abs_end:]
    return body


def _replace_font_commands(text: str) -> str:
    """Replace CJK font commands with semantic equivalents."""
    # {\heiti text} → {\textbf{text}}  (keep outer braces for command arguments)
    text = re.sub(r"\{\\heiti\b\s*(.*?)\}", r"{\\textbf{\1}}", text)
    text = re.sub(r"\\heiti\{(.*?)\}", r"\\textbf{\1}", text)

    # {\songti text} → {text}
    text = re.sub(r"\{\\songti\b\s*(.*?)\}", r"{\1}", text)
    text = re.sub(r"\\songti\{(.*?)\}", r"{\1}", text)

    # {\fangsong text} → {text}
    text = re.sub(r"\{\\fangsong\b\s*(.*?)\}", r"{\1}", text)
    text = re.sub(r"\\fangsong\{(.*?)\}", r"{\1}", text)

    # {\kaiti text} → {\textit{text}}
    text = re.sub(r"\{\\kaiti\b\s*(.*?)\}", r"{\\textit{\1}}", text)
    text = re.sub(r"\\kaiti\{(.*?)\}", r"\\textit{\1}", text)

    # Standalone font switches (e.g. \heiti used as toggle)
    text = re.sub(r"\\(?:heiti|songti|fangsong|kaiti)\b(?!\{)", "", text)

    # \fontsize{...}{...}\selectfont
    text = re.sub(r"\\fontsize\{[^}]*\}\{[^}]*\}\\selectfont", "", text)

    return text


# ---------------------------------------------------------------------------
# Geometry extraction
# ---------------------------------------------------------------------------

def _extract_geometry(preamble: str, metadata: WordExportMetadata) -> None:
    """Extract \\geometry{...} values into metadata."""
    # Collect all geometry blocks; prefer the *last* one (main body layout)
    for m in re.finditer(r"\\(?:new)?geometry\s*\{([^}]*)\}", preamble, re.DOTALL):
        geo_str = m.group(1)
        for param_match in re.finditer(r"(\w+)\s*=\s*([\d.]+\s*(?:cm|mm|in|pt|bp))", geo_str):
            metadata.geometry[param_match.group(1)] = param_match.group(2)
