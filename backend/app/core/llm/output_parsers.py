import json
import re


def extract_json(text: str) -> dict:
    """Extract JSON from LLM output, handling code blocks."""
    # Try to find JSON in code block
    match = re.search(r"```(?:json)?\s*\n?(.*?)```", text, re.DOTALL)
    if match:
        text = match.group(1).strip()

    # Try to parse directly
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass

    # Try to extract JSON by finding matched braces
    start = text.find("{")
    if start != -1:
        depth = 0
        for i in range(start, len(text)):
            if text[i] == "{":
                depth += 1
            elif text[i] == "}":
                depth -= 1
                if depth == 0:
                    try:
                        return json.loads(text[start:i + 1])
                    except json.JSONDecodeError:
                        break

    return {}


def extract_latex(text: str) -> str:
    """Extract LaTeX code from LLM output, handling code blocks."""
    # Try to find LaTeX in code block
    match = re.search(r"```(?:latex|tex)?\s*\n?(.*?)```", text, re.DOTALL)
    if match:
        return match.group(1).strip()

    # If text starts with \documentclass, it's likely raw LaTeX
    stripped = text.strip()
    if stripped.startswith("\\documentclass"):
        return stripped

    return stripped
