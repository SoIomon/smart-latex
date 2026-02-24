"""Document tools for the chat agent.

Provides tools that let the LLM inspect and modify a LaTeX document
without ever seeing the full text in its context window.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

MAX_RESULT_CHARS = 4000

# ---------------------------------------------------------------------------
# Chinese reference → LaTeX environment mapping
# ---------------------------------------------------------------------------

# Maps Chinese reference prefixes to LaTeX patterns to search for
_REFERENCE_LATEX_PATTERNS: dict[str, list[str]] = {
    "表": [r"\\begin\{table", r"\\caption\{"],
    "图": [r"\\begin\{figure", r"\\includegraphics"],
    "公式": [r"\\begin\{equation", r"\\begin\{align"],
    "方程": [r"\\begin\{equation", r"\\begin\{align"],
    "定理": [r"\\begin\{theorem"],
    "定义": [r"\\begin\{definition"],
    "引理": [r"\\begin\{lemma"],
    "推论": [r"\\begin\{corollary"],
    "算法": [r"\\begin\{algorithm"],
    "代码": [r"\\begin\{lstlisting", r"\\begin\{minted"],
    "列表": [r"\\begin\{enumerate", r"\\begin\{itemize"],
}

# Matches patterns like "表2.1", "图 3", "公式1.2", "表 2-1", "方程（1）" etc.
_REFERENCE_RE = re.compile(
    r"^(" + "|".join(_REFERENCE_LATEX_PATTERNS.keys()) + r")\s*[\d\.\-\(\)（）]*$"
)


@dataclass
class DocumentState:
    """In-memory line-based representation of a LaTeX document."""

    lines: list[str] = field(default_factory=list)
    modified: bool = False

    @classmethod
    def from_latex(cls, latex: str) -> "DocumentState":
        return cls(lines=latex.splitlines(keepends=True))

    def to_latex(self) -> str:
        return "".join(self.lines)

    @property
    def total_lines(self) -> int:
        return len(self.lines)


# ---------------------------------------------------------------------------
# Tool definitions (OpenAI function-calling schema)
# ---------------------------------------------------------------------------

TOOL_DEFINITIONS: list[dict] = [
    {
        "type": "function",
        "function": {
            "name": "get_document_outline",
            "description": (
                "返回文档的章节大纲（\\chapter, \\section, \\subsection 等），"
                "每行包含行号和标题，帮助你快速了解文档结构。"
            ),
            "parameters": {
                "type": "object",
                "properties": {},
                "required": [],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "search_text",
            "description": (
                "在文档中搜索文本（支持正则表达式），返回匹配行及上下文。"
                "最多返回 20 条匹配结果。"
                "支持自动识别\u201c表2.1\u201d\u201c图3.1\u201d等编号引用并搜索对应 LaTeX 环境。"
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": "搜索关键词或正则表达式",
                    },
                    "context_lines": {
                        "type": "integer",
                        "description": "每条匹配前后显示的上下文行数，默认 2",
                        "default": 2,
                    },
                },
                "required": ["query"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "read_lines",
            "description": (
                "读取文档指定行范围的内容（行号从 1 开始）。"
                "单次最多读取 200 行。"
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "start_line": {
                        "type": "integer",
                        "description": "起始行号（1-based，含）",
                    },
                    "end_line": {
                        "type": "integer",
                        "description": "结束行号（1-based，含）",
                    },
                },
                "required": ["start_line", "end_line"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "replace_lines",
            "description": (
                "替换文档指定行范围的内容。行号从 1 开始。"
                "用 new_content 替换 start_line 到 end_line（含）之间的所有行。"
                "替换前请先用 read_lines 确认要替换的内容。"
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "start_line": {
                        "type": "integer",
                        "description": "起始行号（1-based，含）",
                    },
                    "end_line": {
                        "type": "integer",
                        "description": "结束行号（1-based，含）",
                    },
                    "new_content": {
                        "type": "string",
                        "description": "替换后的新内容（可以是多行文本）",
                    },
                },
                "required": ["start_line", "end_line", "new_content"],
            },
        },
    },
]

# Heading patterns ordered by depth
_HEADING_PATTERNS = [
    (r"\\chapter\*?\{(.+?)\}", "chapter"),
    (r"\\section\*?\{(.+?)\}", "section"),
    (r"\\subsection\*?\{(.+?)\}", "subsection"),
    (r"\\subsubsection\*?\{(.+?)\}", "subsubsection"),
    (r"\\begin\{abstract\}", "abstract"),
    (r"\\begin\{appendix\}", "appendix"),
]


def _truncate(text: str) -> str:
    if len(text) <= MAX_RESULT_CHARS:
        return text
    return text[: MAX_RESULT_CHARS - 40] + "\n...[结果已截断，请缩小范围重试]"


# ---------------------------------------------------------------------------
# Tool implementations
# ---------------------------------------------------------------------------


def get_document_outline(doc: DocumentState) -> str:
    results: list[str] = []
    for idx, line in enumerate(doc.lines, 1):
        stripped = line.strip()
        for pattern, level in _HEADING_PATTERNS:
            m = re.search(pattern, stripped)
            if m:
                title = m.group(1) if m.lastindex else level
                indent = {"chapter": "", "section": "  ", "subsection": "    ",
                          "subsubsection": "      "}.get(level, "")
                results.append(f"L{idx}: {indent}{level}: {title}")
                break
    if not results:
        return "未找到章节标题。文档可能没有使用标准 LaTeX 章节命令。"
    return "\n".join(results)


def _find_matches(
    doc: DocumentState, pattern: re.Pattern, context_lines: int, limit: int = 20
) -> list[str]:
    """Core search: return formatted match blocks for *pattern*."""
    matches: list[str] = []
    total = doc.total_lines
    for idx, line in enumerate(doc.lines):
        if pattern.search(line):
            start = max(0, idx - context_lines)
            end = min(total, idx + context_lines + 1)
            block = []
            for i in range(start, end):
                marker = ">>>" if i == idx else "   "
                block.append(f"{marker} L{i + 1}: {doc.lines[i].rstrip()}")
            matches.append("\n".join(block))
            if len(matches) >= limit:
                break
    return matches


def _try_reference_fallback(
    doc: DocumentState, query: str, context_lines: int
) -> str | None:
    """If *query* looks like a Chinese numbered reference (e.g. '表2.1'),
    search for the corresponding LaTeX environments instead.
    Returns a formatted result string, or None if the query doesn't match."""
    m = _REFERENCE_RE.match(query.strip())
    if not m:
        return None

    prefix = m.group(1)
    latex_patterns = _REFERENCE_LATEX_PATTERNS.get(prefix)
    if not latex_patterns:
        return None

    # Combine all LaTeX patterns with OR
    combined = "|".join(latex_patterns)
    try:
        pat = re.compile(combined, re.IGNORECASE)
    except re.error:
        return None

    matches = _find_matches(doc, pat, context_lines)
    if not matches:
        return (
            f"未找到匹配 '{query}' 的内容。\n"
            f"提示：\u201c{prefix}X.X\u201d的编号是 LaTeX 编译时自动生成的，源码中不存在。"
            f"已自动搜索 {combined} 等环境，也未找到。"
            f"你可以尝试搜索该{prefix}格 caption 中的关键词来定位。"
        )

    header = (
        f"注意：\u201c{query}\u201d的编号是 LaTeX 编译时自动生成的，源码中不存在。"
        f"已自动搜索对应的 LaTeX 环境（{combined}），找到 {len(matches)} 处：\n"
    )
    return _truncate(header + "\n---\n".join(matches))


def search_text(doc: DocumentState, query: str, context_lines: int = 2) -> str:
    try:
        pattern = re.compile(query, re.IGNORECASE)
    except re.error:
        pattern = re.compile(re.escape(query), re.IGNORECASE)

    matches = _find_matches(doc, pattern, context_lines)

    if matches:
        header = f"找到 {len(matches)} 处匹配：\n"
        return _truncate(header + "\n---\n".join(matches))

    # Fallback: try to detect Chinese numbered references
    fallback = _try_reference_fallback(doc, query, context_lines)
    if fallback:
        return fallback

    return (
        f"未找到匹配 '{query}' 的内容。"
        f"提示：如果你在搜索编号（如\u201c表X.X\u201d\u201c图X.X\u201d），这些编号是编译时生成的，"
        f"请尝试搜索 caption 中的关键词或对应的 LaTeX 环境名（如 \\\\begin{{table}}）。"
    )


def read_lines(doc: DocumentState, start_line: int, end_line: int) -> str:
    total = doc.total_lines
    start_line = max(1, start_line)
    end_line = min(total, end_line)

    if end_line - start_line + 1 > 200:
        end_line = start_line + 199

    result_lines: list[str] = []
    for i in range(start_line - 1, end_line):
        result_lines.append(f"L{i + 1}: {doc.lines[i].rstrip()}")

    header = f"[行 {start_line}-{end_line}，共 {total} 行]\n"
    return _truncate(header + "\n".join(result_lines))


def replace_lines(doc: DocumentState, start_line: int, end_line: int, new_content: str) -> str:
    total = doc.total_lines
    start_line = max(1, start_line)
    end_line = min(total, end_line)

    # Ensure new_content lines end with newline
    new_lines = new_content.splitlines(keepends=True)
    if new_lines and not new_lines[-1].endswith("\n"):
        new_lines[-1] += "\n"

    old_count = end_line - start_line + 1
    doc.lines[start_line - 1 : end_line] = new_lines
    doc.modified = True

    new_total = doc.total_lines
    return (
        f"已替换行 {start_line}-{end_line}（原 {old_count} 行 → 新 {len(new_lines)} 行）。"
        f"文档现在共 {new_total} 行。"
    )


# ---------------------------------------------------------------------------
# Dispatcher
# ---------------------------------------------------------------------------

def execute_tool(name: str, args: dict, doc_state: DocumentState) -> str:
    """Execute a tool by name and return the string result."""
    if name == "get_document_outline":
        return get_document_outline(doc_state)
    elif name == "search_text":
        return search_text(
            doc_state,
            query=args.get("query", ""),
            context_lines=args.get("context_lines", 2),
        )
    elif name == "read_lines":
        return read_lines(
            doc_state,
            start_line=args.get("start_line", 1),
            end_line=args.get("end_line", 1),
        )
    elif name == "replace_lines":
        return replace_lines(
            doc_state,
            start_line=args.get("start_line", 1),
            end_line=args.get("end_line", 1),
            new_content=args.get("new_content", ""),
        )
    else:
        return f"未知工具: {name}"
