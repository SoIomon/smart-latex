"""Enhanced error parser for xelatex compilation logs.

Extracts structured error information (line number, error type, context)
from xelatex log output for use by the fix agent.
"""

from __future__ import annotations

import re
from dataclasses import dataclass


@dataclass
class ParsedError:
    """A single structured error extracted from xelatex log."""

    line_number: int | None  # parsed from "l.42"
    error_type: str  # "syntax" | "font" | "package" | "undefined_command" | "environment" | "unknown"
    message: str  # full error message
    context: str  # source code context around the error line


def _classify_error(message: str) -> str:
    """Classify an error message into a category."""
    msg_lower = message.lower()

    # Font errors
    if any(kw in msg_lower for kw in ("cannot be found", "not loadable", "tfm file", "font not found")):
        return "font"

    # Package errors
    if re.search(r"file\s+'[^']+\.sty'\s+not found", msg_lower) or "not found in the database" in msg_lower:
        return "package"

    # Undefined command
    if "undefined control sequence" in msg_lower:
        return "undefined_command"

    # Undefined environment
    if "undefined environment" in msg_lower or re.search(r"environment\s+\S+\s+undefined", msg_lower):
        return "environment"

    # Syntax errors
    syntax_keywords = (
        "missing $", "missing {", "missing }", "extra {", "extra }",
        "mismatched", "runaway argument", "paragraph ended before",
        "extra alignment tab", "misplaced \\noalign", "misplaced \\omit",
        "display math should end with $$", "missing \\endgroup",
        "missing \\right", "extra \\right", "double superscript", "double subscript",
    )
    if any(kw in msg_lower for kw in syntax_keywords):
        return "syntax"

    return "unknown"


def parse_xelatex_log(log: str) -> list[ParsedError]:
    """Parse xelatex log output and extract structured errors.

    Scans for error blocks starting with '!' and extracts:
    - The error message
    - Line number from 'l.NNN' patterns
    - Source code context from the log
    """
    errors: list[ParsedError] = []
    seen: set[tuple[str, int | None]] = set()
    lines = log.split("\n")

    i = 0
    while i < len(lines):
        line = lines[i]

        # Look for error lines starting with '!'
        if not line.startswith("!"):
            i += 1
            continue

        # Collect the full error message (may span multiple lines)
        error_lines = [line[1:].strip()]  # strip the '!' prefix
        j = i + 1
        while j < len(lines) and not lines[j].startswith("!") and not lines[j].startswith("l."):
            stripped = lines[j].strip()
            if stripped:
                error_lines.append(stripped)
            j += 1

        message = " ".join(error_lines)

        # Look for line number in "l.NNN" format
        line_number: int | None = None
        context_parts: list[str] = []

        # Search forward from the error for l.NNN
        for k in range(i, min(j + 5, len(lines))):
            m = re.match(r"l\.(\d+)\s*(.*)", lines[k])
            if m:
                line_number = int(m.group(1))
                if m.group(2).strip():
                    context_parts.append(m.group(2).strip())
                # The line after l.NNN often shows what was expected
                if k + 1 < len(lines) and lines[k + 1].strip():
                    context_parts.append(lines[k + 1].strip())
                break

        context = " | ".join(context_parts) if context_parts else ""

        # Deduplicate by (message, line_number)
        key = (message, line_number)
        if key not in seen:
            seen.add(key)
            errors.append(ParsedError(
                line_number=line_number,
                error_type=_classify_error(message),
                message=message,
                context=context,
            ))

        i = j

    return errors
