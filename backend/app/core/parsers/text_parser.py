from pathlib import Path

from app.core.parsers.base import BaseParser, ParsedContent


class TextParser(BaseParser):
    async def parse(self, file_path: Path) -> ParsedContent:
        try:
            text = file_path.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            text = file_path.read_text(encoding="gbk", errors="replace")
        paragraphs = [p.strip() for p in text.split("\n\n") if p.strip()]
        sections = [{"title": "", "content": p} for p in paragraphs]
        return ParsedContent(
            text=text,
            metadata={"filename": file_path.name, "size": file_path.stat().st_size},
            sections=sections,
        )
