"""LaTeX math → OMML converter for Word documents.

Conversion path: LaTeX → MathML (via latex2mathml) → OMML (via MML2OMML.xsl XSLT)
Falls back to styled text if conversion fails.
"""

from __future__ import annotations

import logging
from pathlib import Path

from docx.shared import Pt

logger = logging.getLogger(__name__)

# Path to the XSLT stylesheet
_XSL_PATH = Path(__file__).parent / "xsl" / "MML2OMML.xsl"

# Lazy-loaded XSLT transform
_xslt_transform = None
_xslt_checked = False


def _get_xslt_transform():
    """Lazily load the XSLT transform for MathML → OMML."""
    global _xslt_transform, _xslt_checked
    if _xslt_checked:
        return _xslt_transform
    _xslt_checked = True

    if not _XSL_PATH.exists():
        return None

    try:
        from lxml import etree
        xsl_doc = etree.parse(str(_XSL_PATH))
        _xslt_transform = etree.XSLT(xsl_doc)
        return _xslt_transform
    except Exception:
        return None


def latex_to_omml(latex_str: str):
    """Convert a LaTeX math string to OMML element, or None."""
    try:
        import latex2mathml.converter
        mathml_str = latex2mathml.converter.convert(latex_str)
    except Exception:
        return None

    transform = _get_xslt_transform()
    if transform is None:
        return None

    try:
        from lxml import etree
        from docx.oxml.parser import parse_xml

        # latex2mathml emits a default namespace:
        #   <math xmlns="http://www.w3.org/1998/Math/MathML">
        # but MML2OMML.xsl matches the mml: prefix.  Re-tag the elements
        # so the XSLT can find them.
        _MML_NS = "http://www.w3.org/1998/Math/MathML"
        mathml_doc = etree.fromstring(mathml_str.encode("utf-8"))
        for el in mathml_doc.iter():
            if el.tag and not el.tag.startswith("{"):
                el.tag = f"{{{_MML_NS}}}{el.tag}"

        omml_doc = transform(mathml_doc)
        omml_root = omml_doc.getroot()
        if omml_root is None:
            return None
        omml_str = etree.tostring(omml_root, encoding="unicode")
        return parse_xml(omml_str)
    except Exception as e:
        logger.debug("OMML conversion failed: %s", e)
        return None


def add_math_to_paragraph(paragraph, latex_str: str, display: bool = False):
    """Add a math expression to a paragraph.

    If OMML conversion succeeds, inserts native Word math.
    Otherwise falls back to italic Cambria Math text.
    """
    omml = latex_to_omml(latex_str)
    if omml is not None:
        paragraph._element.append(omml)
        return

    # Fallback: render as styled text with symbol substitution
    text = _latex_math_to_text(latex_str)
    run = paragraph.add_run(text)
    run.font.name = "Cambria Math"
    run.italic = True
    if display:
        run.font.size = Pt(12)
    else:
        run.font.size = Pt(11)


def _latex_math_to_text(latex_str: str) -> str:
    """Best-effort conversion of LaTeX math to readable Unicode text."""
    import re
    from .text_utils import SYMBOL_MAP

    # Replace \command with Unicode symbols
    def _replace_cmd(m):
        name = m.group(1)
        return SYMBOL_MAP.get(name, m.group(0))

    text = re.sub(r"\\([a-zA-Z]+)", _replace_cmd, latex_str)
    # Clean up remaining LaTeX artifacts
    text = text.replace("\\", "")
    text = text.replace("{", "")
    text = text.replace("}", "")
    text = text.replace("^", "")
    text = text.replace("_", "")
    return text.strip()
