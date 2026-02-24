from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class ParsedContent:
    text: str = ""
    metadata: dict = field(default_factory=dict)
    sections: list[dict] = field(default_factory=list)
    images: list[dict] = field(default_factory=list)
    # 每个 dict: {"filename": "figure_001.png", "data": bytes,
    #             "content_type": "image/png", "width_cm": 12.5, "height_cm": 8.0}


class BaseParser(ABC):
    @abstractmethod
    async def parse(self, file_path: Path) -> ParsedContent:
        raise NotImplementedError
