"""Parse TeX .aux files to extract structure data (TOC, labels, floats).

Provides ``parse_aux_file()`` which returns a ``TexStructure`` containing
all numbered headings, figure/table entries, and cross-reference labels
as computed by TeX during compilation.
"""

import logging
import re
from dataclasses import dataclass, field
from pathlib import Path

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------

@dataclass
class TocEntry:
    """A single TOC entry parsed from the .aux file."""
    level: str          # "chapter" | "section" | "subsection" | "subsubsection"
    number: str         # "第 1 章" | "1.1" | "1.1.1"
    title: str          # "绪论"
    page: int           # 4

    @property
    def full_title(self) -> str:
        """Combine number and title into the display string."""
        if not self.number:
            return self.title
        return f"{self.number} {self.title}"


@dataclass
class FloatEntry:
    """A figure or table entry parsed from the .aux file."""
    kind: str           # "figure" | "table"
    number: str         # "1" | "2.1"
    caption: str        # "系统架构图"
    page: int           # 5


@dataclass
class LabelInfo:
    """A cross-reference label parsed from the .aux file."""
    key: str            # "fig:arch"
    display: str        # "2.1"
    page: int           # 5


@dataclass
class TexStructure:
    """Structured data extracted from a TeX .aux file."""
    toc_entries: list[TocEntry] = field(default_factory=list)
    lof_entries: list[FloatEntry] = field(default_factory=list)
    lot_entries: list[FloatEntry] = field(default_factory=list)
    labels: dict[str, LabelInfo] = field(default_factory=dict)
    citation_order: list[str] = field(default_factory=list)

    # Internal cursor for sequential heading matching
    _toc_cursor: int = field(default=0, repr=False)

    def find_heading(self, title_text: str, level: str) -> TocEntry | None:
        """Find the next TOC entry matching *title_text* and *level*.

        Uses sequential scanning (cursor-based) so that headings are
        matched in document order.
        """
        norm_title = _normalize_for_match(title_text)
        for i in range(self._toc_cursor, len(self.toc_entries)):
            entry = self.toc_entries[i]
            if entry.level != level:
                continue
            if _titles_match(norm_title, _normalize_for_match(entry.title)):
                self._toc_cursor = i + 1
                return entry
        return None

    def find_figure(self, index: int) -> FloatEntry | None:
        """Return the *index*-th figure entry (1-based)."""
        if 1 <= index <= len(self.lof_entries):
            return self.lof_entries[index - 1]
        return None

    def find_table(self, index: int) -> FloatEntry | None:
        """Return the *index*-th table entry (1-based)."""
        if 1 <= index <= len(self.lot_entries):
            return self.lot_entries[index - 1]
        return None

    def resolve_ref(self, key: str) -> str | None:
        r"""Resolve a ``\ref{key}`` or ``\cite{key}`` to its display string."""
        label = self.labels.get(key)
        return label.display if label else None

    def resolve_citation_keys(self, keys: list[str]) -> list[str]:
        """Resolve citation keys in order, preserving unknown keys as-is."""
        resolved: list[str] = []
        for key in keys:
            display = self.resolve_ref(key)
            resolved.append(display if display else key)
        return resolved


# ---------------------------------------------------------------------------
# Text normalization helpers
# ---------------------------------------------------------------------------

def _clean_latex_text(text: str) -> str:
    """Strip LaTeX commands from *text*, keeping readable content."""
    text = text.replace("\\ignorespaces", "")
    text = text.replace("\\nobreakspace{}", " ")
    text = text.replace("\\protect", "")
    text = text.replace("\\relax", "")
    text = text.replace("\\protected@file@percent", "")
    text = text.replace("~", " ")
    # \hspace{...} / \hspace  {.3em} / \vspace*{...} → space
    # (allow arbitrary whitespace and optional * between command and {)
    text = re.sub(r"\\[hv]space\s*\*?\s*\{[^}]*\}", " ", text)
    # Remove \penalty, \@M etc.
    text = re.sub(r"\\penalty[^{}\s]*", "", text)
    text = re.sub(r"\\@M\b", "", text)
    # $...$ → keep inner content (without dollars)
    text = re.sub(r"\$([^$]*)\$", r"\1", text)
    # Single-char TeX spacing commands: \, \; \! \: → space
    text = re.sub(r"\\[,;!>:]", " ", text)
    # Remove remaining \command sequences (keep any following text)
    text = re.sub(r"\\[a-zA-Z@]+\s*", "", text)
    # Remove stray braces
    text = text.replace("{", "").replace("}", "")
    return text.strip()


def _normalize_for_match(text: str) -> str:
    """Normalize *text* for fuzzy title matching."""
    text = _clean_latex_text(text)
    # Collapse all whitespace
    text = re.sub(r"\s+", "", text)
    return text.lower()


def _titles_match(a: str, b: str) -> bool:
    """Return True if normalised titles *a* and *b* are equivalent."""
    if not a or not b:
        return False
    return a == b or a in b or b in a


# ---------------------------------------------------------------------------
# Brace-balanced extraction
# ---------------------------------------------------------------------------

def _extract_brace_content(text: str, start: int) -> tuple[str, int]:
    """Extract the content of the first balanced ``{...}`` starting at *start*.

    Returns ``(content, end_position)`` where *end_position* is the index
    immediately after the closing ``}``.
    """
    if start >= len(text) or text[start] != "{":
        return ("", start)
    depth = 1
    i = start + 1
    while i < len(text) and depth > 0:
        if text[i] == "{":
            depth += 1
        elif text[i] == "}":
            depth -= 1
        i += 1
    return (text[start + 1 : i - 1], i)


def _extract_all_brace_groups(text: str, start: int = 0) -> list[str]:
    """Extract all top-level ``{...}`` groups from *text*."""
    groups: list[str] = []
    i = start
    while i < len(text):
        if text[i] == "{":
            content, i = _extract_brace_content(text, i)
            groups.append(content)
        else:
            i += 1
    return groups


# ---------------------------------------------------------------------------
# Line parsers
# ---------------------------------------------------------------------------

def _parse_numberline(text: str) -> tuple[str, str]:
    r"""Parse ``\numberline{NUM}TITLE`` and return ``(number, title)``."""
    m = re.match(r"\\numberline\s*", text)
    if not m:
        return ("", _clean_latex_text(text))
    pos = m.end()
    # Skip whitespace before '{'
    while pos < len(text) and text[pos] == " ":
        pos += 1
    if pos < len(text) and text[pos] == "{":
        num_content, end_pos = _extract_brace_content(text, pos)
        number = _clean_latex_text(num_content)
        title = _clean_latex_text(text[end_pos:])
    else:
        number = ""
        title = _clean_latex_text(text[pos:])
    return (number, title)


def _parse_toc_line(line: str) -> TocEntry | None:
    r"""Parse ``\@writefile{toc}{\contentsline{TYPE}{...}{PAGE}{...}}``."""
    m = re.match(r"\\@writefile\{toc\}", line)
    if not m:
        return None
    rest = line[m.end():]
    idx = rest.find("{")
    if idx < 0:
        return None
    content, _ = _extract_brace_content(rest, idx)
    if not content:
        return None

    cm = re.match(r"\\contentsline\s*\{(\w+)\}", content)
    if not cm:
        return None
    level = cm.group(1)
    if level not in ("chapter", "section", "subsection", "subsubsection"):
        return None

    groups = _extract_all_brace_groups(content, cm.end())
    if len(groups) < 2:
        return None

    number, title = _parse_numberline(groups[0])
    try:
        page = int(groups[1].strip())
    except ValueError:
        page = 0

    return TocEntry(level=level, number=number, title=title, page=page)


def _parse_float_line(line: str, kind: str) -> FloatEntry | None:
    r"""Parse ``\@writefile{lof/lot}{\contentsline{figure/table}{...}{PAGE}{...}}``."""
    tag = "lof" if kind == "figure" else "lot"
    m = re.match(rf"\\@writefile\{{{tag}\}}", line)
    if not m:
        return None
    rest = line[m.end():]
    idx = rest.find("{")
    if idx < 0:
        return None
    content, _ = _extract_brace_content(rest, idx)
    if not content:
        return None

    cm = re.match(rf"\\contentsline\s*\{{{kind}\}}", content)
    if not cm:
        return None

    groups = _extract_all_brace_groups(content, cm.end())
    if len(groups) < 2:
        return None

    number, caption = _parse_numberline(groups[0])
    try:
        page = int(groups[1].strip())
    except ValueError:
        page = 0

    return FloatEntry(kind=kind, number=number, caption=caption, page=page)


def _parse_label_line(line: str) -> LabelInfo | None:
    r"""Parse ``\newlabel{KEY}{{DISPLAY}{PAGE}{...}{...}{...}}``."""
    m = re.match(r"\\newlabel\{([^}]+)\}", line)
    if not m:
        return None
    key = m.group(1)
    rest = line[m.end():]

    idx = rest.find("{")
    if idx < 0:
        return None
    outer_content, _ = _extract_brace_content(rest, idx)
    if not outer_content:
        return None

    inner_groups = _extract_all_brace_groups(outer_content)
    if len(inner_groups) < 2:
        return None

    display = _clean_latex_text(inner_groups[0])
    try:
        page = int(inner_groups[1].strip())
    except ValueError:
        page = 0

    return LabelInfo(key=key, display=display, page=page)


def _parse_bibcite_line(line: str) -> LabelInfo | None:
    r"""Parse ``\bibcite{KEY}{DISPLAY}``."""
    m = re.match(r"\\bibcite\{([^}]+)\}\{([^}]+)\}", line)
    if not m:
        return None
    return LabelInfo(key=m.group(1), display=m.group(2), page=0)


def _parse_abx_aux_cite_key(line: str) -> str | None:
    r"""Parse biblatex aux cite lines and return cite key if present.

    Supports common forms:
    - ``\abx@aux@cite{<key>}``
    - ``\abx@aux@cite{<segment>}{<key>}``
    - ``\abx@aux@segm{...}{...}{<key>}``
    """
    m = re.match(r"\\abx@aux@cite\{([^}]+)\}(?:\{([^}]+)\})?", line)
    if m:
        # Two-arg form stores key in group 2; one-arg form uses group 1.
        return m.group(2) or m.group(1)
    m = re.match(r"\\abx@aux@segm\{[^}]*\}\{[^}]*\}\{([^}]+)\}", line)
    if m:
        return m.group(1)
    return None


def _parse_bbl_entries(bbl_path: Path) -> list[str]:
    r"""Parse ``.bbl`` and return bibliography key order from ``\entry{key}{...}``."""
    try:
        content = bbl_path.read_text(encoding="utf-8", errors="replace")
    except (OSError, IOError) as e:
        logger.warning("Failed to read bbl file %s: %s", bbl_path, e)
        return []

    # biblatex .bbl entry form
    keys = re.findall(r"\\entry\{([^}]+)\}\{", content)
    if keys:
        return keys

    # bibtex/natbib numeric styles
    keys = re.findall(r"\\bibitem(?:\[[^\]]*\])?\{([^}]+)\}", content)
    if keys:
        return keys

    return []


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def parse_aux_file(aux_path: Path, bbl_path: Path | None = None) -> TexStructure | None:
    """Parse a ``.aux`` file and return a :class:`TexStructure`.

    Returns ``None`` if the file cannot be read.
    """
    try:
        content = aux_path.read_text(encoding="utf-8", errors="replace")
    except (OSError, IOError) as e:
        logger.warning("Failed to read aux file %s: %s", aux_path, e)
        return None

    structure = TexStructure()
    seen_abx_keys: set[str] = set()

    for line in content.splitlines():
        line = line.strip()
        if not line:
            continue

        # TOC entries
        if line.startswith("\\@writefile{toc}"):
            entry = _parse_toc_line(line)
            if entry:
                structure.toc_entries.append(entry)
            continue

        # Figure entries (lof)
        if line.startswith("\\@writefile{lof}"):
            entry = _parse_float_line(line, "figure")
            if entry:
                structure.lof_entries.append(entry)
            continue

        # Table entries (lot)
        if line.startswith("\\@writefile{lot}"):
            entry = _parse_float_line(line, "table")
            if entry:
                structure.lot_entries.append(entry)
            continue

        # Cross-reference labels
        if line.startswith("\\newlabel{"):
            info = _parse_label_line(line)
            if info:
                structure.labels[info.key] = info
            continue

        # Bibliography citations
        if line.startswith("\\bibcite{"):
            info = _parse_bibcite_line(line)
            if info:
                structure.labels[info.key] = info
            continue

        # biblatex citation tracking (for later .bbl mapping)
        if line.startswith("\\abx@aux@cite") or line.startswith("\\abx@aux@segm"):
            key = _parse_abx_aux_cite_key(line)
            if key and key not in seen_abx_keys:
                seen_abx_keys.add(key)
                structure.citation_order.append(key)
            continue

    # If we have biblatex cite keys, prefer .bbl entry order for final numbering.
    if bbl_path and bbl_path.exists():
        bbl_order = _parse_bbl_entries(bbl_path)
        if bbl_order:
            for i, key in enumerate(bbl_order, start=1):
                if key not in structure.labels:
                    structure.labels[key] = LabelInfo(key=key, display=str(i), page=0)
        else:
            # Fallback: use aux citation encounter order when .bbl parsing yields no entries.
            for i, key in enumerate(structure.citation_order, start=1):
                if key not in structure.labels:
                    structure.labels[key] = LabelInfo(key=key, display=str(i), page=0)
    elif structure.citation_order:
        for i, key in enumerate(structure.citation_order, start=1):
            if key not in structure.labels:
                structure.labels[key] = LabelInfo(key=key, display=str(i), page=0)

    logger.info(
        "Parsed .aux: %d toc, %d figures, %d tables, %d labels, %d cites",
        len(structure.toc_entries),
        len(structure.lof_entries),
        len(structure.lot_entries),
        len(structure.labels),
        len(structure.citation_order),
    )
    return structure
