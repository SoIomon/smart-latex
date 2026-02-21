"""Front-matter builders for different templates.

Each builder knows how to create cover pages, declarations, TOC, and
headers for a specific template.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import TYPE_CHECKING, Type

from docx import Document

from app.core.compiler.word_preprocessor import WordExportMetadata

if TYPE_CHECKING:
    from app.core.compiler.latex2docx.profile import DocxProfile


class FrontmatterBuilder(ABC):
    """Abstract base for template-specific front-matter builders."""

    def __init__(self, profile: "DocxProfile | None" = None):
        self.profile = profile

    @abstractmethod
    def build(self, doc: Document, metadata: WordExportMetadata) -> None:
        """Insert all front-matter content into *doc*."""
        ...

    @abstractmethod
    def should_handle_command(self, cmd: str) -> bool:
        """Return True if this builder handles the given command."""
        ...


# Registry of template_id → builder class
_REGISTRY: dict[str, Type[FrontmatterBuilder]] = {}


def register_builder(template_id: str):
    """Decorator to register a FrontmatterBuilder for a template."""
    def decorator(cls):
        _REGISTRY[template_id] = cls
        return cls
    return decorator


def _ensure_builders_loaded():
    """Import all builder modules to trigger @register_builder decorators."""
    if _REGISTRY:
        return
    # Import submodules so their decorators execute
    from . import ucas_thesis  # noqa: F401


def get_frontmatter_builder(
    template_id: str,
    profile: "DocxProfile | None" = None,
) -> FrontmatterBuilder | None:
    """Return an instantiated builder for the given template, or None.

    If the profile has declarative frontmatter sections, prefer the
    DeclarativeFrontmatterBuilder.  Otherwise fall back to the registered
    per-template builder or the generic builder.
    """
    _ensure_builders_loaded()

    # Check for declarative frontmatter config in profile
    if profile and profile.frontmatter.sections:
        from .declarative import DeclarativeFrontmatterBuilder
        return DeclarativeFrontmatterBuilder(profile)

    cls = _REGISTRY.get(template_id)
    if cls is not None:
        return cls(profile)
    # Fall back to generic builder
    from .generic import GenericFrontmatter
    return GenericFrontmatter(profile)
