"""Direct LaTeX → DOCX converter.

Public API: ``convert_latex_to_docx()``

Replaces the Pandoc-based pipeline with a direct regex tokenizer +
python-docx builder for higher-fidelity Word output.
"""

import logging
from pathlib import Path

from app.core.compiler.word_preprocessor import WordExportMetadata

from .converter import LatexToDocxConverter
from .profile import DocxProfile, load_profile

logger = logging.getLogger(__name__)


def convert_latex_to_docx(
    latex_content: str,
    output_path: str | Path,
    metadata: WordExportMetadata | None = None,
    template_id: str = "",
    image_base_dir: str | Path | None = None,
) -> None:
    """Convert LaTeX content directly to a DOCX file.

    Parameters
    ----------
    latex_content : str
        Full LaTeX document source (including preamble).
    output_path : str | Path
        Where to save the generated .docx file.
    metadata : WordExportMetadata, optional
        Metadata extracted by the preprocessor.
    template_id : str, optional
        Template identifier for front-matter selection.
    image_base_dir : str | Path, optional
        Base directory for resolving ``\\includegraphics`` paths.
    """
    output_path = Path(output_path)
    image_base_dir = Path(image_base_dir) if image_base_dir else output_path.parent

    # Load data-driven profile from template meta.json
    profile = load_profile(template_id)

    # Parse .aux file if available (produced by TeX compilation)
    tex_structure = None
    aux_path = image_base_dir / "document.aux"
    if aux_path.exists():
        from .tex_auxfiles import parse_aux_file
        tex_structure = parse_aux_file(aux_path)

    converter = LatexToDocxConverter(
        metadata=metadata,
        template_id=template_id,
        image_base_dir=image_base_dir,
        profile=profile,
        tex_structure=tex_structure,
    )

    doc = converter.convert(latex_content)

    # Build front-matter if applicable
    if metadata and (metadata.has_cover or template_id):
        try:
            from .frontmatter import get_frontmatter_builder
            builder = get_frontmatter_builder(template_id, profile)
            if builder:
                builder.build(doc, metadata)
        except Exception as e:
            logger.warning("Front-matter build failed: %s", e)

    doc.save(str(output_path))

    # Post-process: physically remove word/numbering.xml from the DOCX
    # package.  python-docx's default template ships with numbering
    # definitions that cause phantom dots/bullets on Heading-styled
    # paragraphs in many Word versions.  Removing the file entirely is
    # the only reliable fix across Word for Mac/Windows/WPS.
    _strip_numbering_part(output_path)

    logger.info("Saved DOCX to %s", output_path)


def _strip_numbering_part(docx_path: Path) -> None:
    """Remove word/numbering.xml from a saved DOCX (ZIP) file."""
    import re as _re
    import zipfile

    tmp_path = docx_path.with_suffix(".docx.tmp")
    try:
        with zipfile.ZipFile(docx_path, "r") as zin, \
             zipfile.ZipFile(tmp_path, "w", zipfile.ZIP_DEFLATED) as zout:
            for item in zin.infolist():
                if item.filename == "word/numbering.xml":
                    continue
                data = zin.read(item.filename)
                if item.filename == "[Content_Types].xml":
                    data = _re.sub(
                        rb'<Override[^>]*PartName="/word/numbering\.xml"[^>]*/>\s*',
                        b"", data,
                    )
                if item.filename == "word/_rels/document.xml.rels":
                    data = _re.sub(
                        rb'<Relationship[^>]*Target="numbering\.xml"[^>]*/>\s*',
                        b"", data,
                    )
                zout.writestr(item, data)
        tmp_path.replace(docx_path)
    except Exception as e:
        logger.warning("Failed to strip numbering part: %s", e)
        if tmp_path.exists():
            tmp_path.unlink()
