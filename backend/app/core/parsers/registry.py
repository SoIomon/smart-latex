from app.core.parsers.base import BaseParser
from app.core.parsers.text_parser import TextParser
from app.core.parsers.docx_parser import DocxParser
from app.core.parsers.pdf_parser import PdfParser
from app.core.parsers.markdown_parser import MarkdownParser


class ParserRegistry:
    _parsers: dict[str, type[BaseParser]] = {
        ".txt": TextParser,
        ".docx": DocxParser,
        ".pdf": PdfParser,
        ".md": MarkdownParser,
    }

    @classmethod
    def get_parser(cls, extension: str) -> BaseParser | None:
        parser_cls = cls._parsers.get(extension.lower())
        if parser_cls:
            return parser_cls()
        return None

    @classmethod
    def supported_extensions(cls) -> list[str]:
        return list(cls._parsers.keys())
