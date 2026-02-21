from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class ParsedContent:
    text: str = ""
    metadata: dict = field(default_factory=dict)
    sections: list[dict] = field(default_factory=list)


class BaseParser(ABC):
    @abstractmethod
    async def parse(self, file_path: Path) -> ParsedContent:
        raise NotImplementedError
