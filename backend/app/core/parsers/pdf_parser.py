import asyncio
from pathlib import Path

import fitz  # PyMuPDF

from app.core.parsers.base import BaseParser, ParsedContent


class PdfParser(BaseParser):
    async def parse(self, file_path: Path) -> ParsedContent:
        return await asyncio.to_thread(self._parse_sync, file_path)

    def _parse_sync(self, file_path: Path) -> ParsedContent:
        doc = fitz.open(str(file_path))

        full_text_parts: list[str] = []
        sections: list[dict] = []

        for page_num in range(len(doc)):
            page = doc[page_num]
            text = page.get_text().strip()
            if text:
                full_text_parts.append(text)
                sections.append({
                    "title": f"Page {page_num + 1}",
                    "content": text,
                })

        metadata = {
            "filename": file_path.name,
            "page_count": len(doc),
        }
        doc_meta = doc.metadata
        if doc_meta:
            if doc_meta.get("title"):
                metadata["title"] = doc_meta["title"]
            if doc_meta.get("author"):
                metadata["author"] = doc_meta["author"]

        doc.close()

        return ParsedContent(
            text="\n\n".join(full_text_parts),
            metadata=metadata,
            sections=sections,
        )
