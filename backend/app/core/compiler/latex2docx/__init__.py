"""Direct LaTeX → DOCX converter.

Public API: ``convert_latex_to_docx()``

Replaces the Pandoc-based pipeline with a direct regex tokenizer +
python-docx builder for higher-fidelity Word output.
"""

import logging
from pathlib import Path

from app.core.compiler.word_preprocessor import WordExportMetadata

logger = logging.getLogger(__name__)


def convert_latex_to_docx(
    latex_content: str,
    output_path: str | Path,
    metadata: WordExportMetadata | None = None,
    template_id: str = "",
    image_base_dir: str | Path | None = None,
    build_frontmatter: bool = False,
    strip_numbering_part: bool = False,
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
    build_frontmatter : bool, optional
        Whether to inject template front-matter elements into the output.
        Defaults to False to avoid duplicating content already present in LaTeX.
    strip_numbering_part : bool, optional
        Whether to physically remove ``word/numbering.xml`` from output.
        Defaults to False to preserve native list/numbering semantics.
    """
    output_path = Path(output_path)
    image_base_dir = Path(image_base_dir) if image_base_dir else output_path.parent
    from .converter import LatexToDocxConverter
    from .profile import load_profile

    # Load data-driven profile from template meta.json
    profile = load_profile(template_id)

    # Parse .aux/.bbl files if available (produced by TeX compilation)
    tex_structure = None
    aux_path = image_base_dir / "document.aux"
    if aux_path.exists():
        from .tex_auxfiles import parse_aux_file
        bbl_path = image_base_dir / "document.bbl"
        tex_structure = parse_aux_file(aux_path, bbl_path=bbl_path if bbl_path.exists() else None)

    converter = LatexToDocxConverter(
        metadata=metadata,
        template_id=template_id,
        image_base_dir=image_base_dir,
        profile=profile,
        tex_structure=tex_structure,
    )

    doc = converter.convert(latex_content)

    # Build front-matter only when explicitly requested.
    if build_frontmatter and metadata and (metadata.has_cover or template_id):
        try:
            from .frontmatter import get_frontmatter_builder
            builder = get_frontmatter_builder(template_id, profile)
            if builder:
                builder.build(doc, metadata)
        except Exception as e:
            logger.warning("Front-matter build failed: %s", e)

    doc.save(str(output_path))
    _inject_footnotes_part(output_path, converter.footnotes)

    # Optional compatibility hack for environments with heading-dot issues.
    if strip_numbering_part:
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


def _inject_footnotes_part(docx_path: Path, footnotes: list[tuple[int, str]]) -> None:
    """Inject ``word/footnotes.xml`` and package relationships when needed."""
    if not footnotes:
        return

    import xml.etree.ElementTree as ET
    import zipfile

    ns_w = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
    ns_ct = "http://schemas.openxmlformats.org/package/2006/content-types"
    ns_rel = "http://schemas.openxmlformats.org/package/2006/relationships"
    ET.register_namespace("w", ns_w)

    tmp_path = docx_path.with_suffix(".docx.tmp")
    try:
        with zipfile.ZipFile(docx_path, "r") as zin:
            files = {item.filename: zin.read(item.filename) for item in zin.infolist()}

        # 1) Build footnotes.xml
        footnotes_root = ET.Element(f"{{{ns_w}}}footnotes")

        def _add_separator(fid: int, sep_tag: str, sep_type: str):
            fn = ET.SubElement(
                footnotes_root,
                f"{{{ns_w}}}footnote",
                {
                    f"{{{ns_w}}}id": str(fid),
                    f"{{{ns_w}}}type": sep_type,
                },
            )
            p = ET.SubElement(fn, f"{{{ns_w}}}p")
            r = ET.SubElement(p, f"{{{ns_w}}}r")
            ET.SubElement(r, f"{{{ns_w}}}{sep_tag}")

        _add_separator(-1, "separator", "separator")
        _add_separator(0, "continuationSeparator", "continuationSeparator")

        for footnote_id, text in footnotes:
            fn = ET.SubElement(
                footnotes_root,
                f"{{{ns_w}}}footnote",
                {f"{{{ns_w}}}id": str(footnote_id)},
            )
            p = ET.SubElement(fn, f"{{{ns_w}}}p")
            pPr = ET.SubElement(p, f"{{{ns_w}}}pPr")
            ET.SubElement(pPr, f"{{{ns_w}}}pStyle", {f"{{{ns_w}}}val": "FootnoteText"})

            r_ref = ET.SubElement(p, f"{{{ns_w}}}r")
            rPr_ref = ET.SubElement(r_ref, f"{{{ns_w}}}rPr")
            ET.SubElement(rPr_ref, f"{{{ns_w}}}rStyle", {f"{{{ns_w}}}val": "FootnoteReference"})
            ET.SubElement(r_ref, f"{{{ns_w}}}footnoteRef")

            r_space = ET.SubElement(p, f"{{{ns_w}}}r")
            t_space = ET.SubElement(r_space, f"{{{ns_w}}}t", {"{http://www.w3.org/XML/1998/namespace}space": "preserve"})
            t_space.text = " "

            r_text = ET.SubElement(p, f"{{{ns_w}}}r")
            t = ET.SubElement(r_text, f"{{{ns_w}}}t")
            t.text = text

        files["word/footnotes.xml"] = ET.tostring(footnotes_root, encoding="utf-8", xml_declaration=True)

        # 2) Ensure [Content_Types].xml has footnotes override
        ct_root = ET.fromstring(files["[Content_Types].xml"])
        has_override = False
        for child in ct_root:
            if child.tag.endswith("Override") and child.attrib.get("PartName") == "/word/footnotes.xml":
                has_override = True
                break
        if not has_override:
            ET.SubElement(
                ct_root,
                f"{{{ns_ct}}}Override",
                {
                    "PartName": "/word/footnotes.xml",
                    "ContentType": "application/vnd.openxmlformats-officedocument.wordprocessingml.footnotes+xml",
                },
            )
        files["[Content_Types].xml"] = ET.tostring(ct_root, encoding="utf-8", xml_declaration=True)

        # 3) Ensure document rels references footnotes.xml
        rels_path = "word/_rels/document.xml.rels"
        rels_root = ET.fromstring(files[rels_path])
        footnote_rel_type = (
            "http://schemas.openxmlformats.org/officeDocument/2006/relationships/footnotes"
        )
        has_rel = False
        max_rid = 0
        for rel in rels_root:
            rel_type = rel.attrib.get("Type")
            rel_id = rel.attrib.get("Id", "")
            if rel_type == footnote_rel_type:
                has_rel = True
            if rel_id.startswith("rId"):
                try:
                    max_rid = max(max_rid, int(rel_id[3:]))
                except ValueError:
                    pass

        if not has_rel:
            ET.SubElement(
                rels_root,
                f"{{{ns_rel}}}Relationship",
                {
                    "Id": f"rId{max_rid + 1}",
                    "Type": footnote_rel_type,
                    "Target": "footnotes.xml",
                },
            )
        files[rels_path] = ET.tostring(rels_root, encoding="utf-8", xml_declaration=True)

        # 4) Rewrite package
        with zipfile.ZipFile(tmp_path, "w", zipfile.ZIP_DEFLATED) as zout:
            for name, data in files.items():
                zout.writestr(name, data)
        tmp_path.replace(docx_path)
    except Exception as e:
        logger.warning("Failed to inject footnotes part: %s", e)
        if tmp_path.exists():
            tmp_path.unlink()
