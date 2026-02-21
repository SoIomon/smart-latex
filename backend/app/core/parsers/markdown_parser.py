import re
from pathlib import Path

import mistune

from app.core.parsers.base import BaseParser, ParsedContent


class MarkdownParser(BaseParser):
    async def parse(self, file_path: Path) -> ParsedContent:
        raw = file_path.read_text(encoding="utf-8")
        html = mistune.html(raw)
        plain = re.sub(r"<[^>]+>", "", html).strip()

        sections: list[dict] = []
        current_section: dict | None = None

        for line in raw.split("\n"):
            heading_match = re.match(r"^(#{1,6})\s+(.+)$", line)
            if heading_match:
                if current_section:
                    sections.append(current_section)
                current_section = {
                    "title": heading_match.group(2).strip(),
                    "level": len(heading_match.group(1)),
                    "content": "",
                }
            else:
                stripped = line.strip()
                if stripped:
                    if current_section is None:
                        current_section = {"title": "", "content": ""}
                    if current_section["content"]:
                        current_section["content"] += "\n"
                    current_section["content"] += stripped

        if current_section:
            sections.append(current_section)

        return ParsedContent(
            text=plain,
            metadata={"filename": file_path.name},
            sections=sections,
        )
