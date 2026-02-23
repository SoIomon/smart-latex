from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from app.api.v1.compiler import download_word, _should_rebuild_frontmatter
from app.config import settings
from app.core.compiler.engine import CompileResult
from app.core.compiler.word_preprocessor import WordExportMetadata, preprocess_latex_for_word
from app.core.compiler.latex2docx import convert_latex_to_docx
from app.core.compiler.latex2docx.profile import (
    DocxProfile,
    LabelsConfig,
    MetadataFieldRuleConfig,
    PreprocessorConfig,
)


def test_should_rebuild_frontmatter_only_for_explicit_frontmatter_flow():
    meta = WordExportMetadata()
    assert _should_rebuild_frontmatter(r"\section{A}", meta) is False
    assert _should_rebuild_frontmatter(r"\maketitle\section{A}", meta) is True

    explicit_cover = r"\begingroup 编写 审核 批准 \endgroup \section{A}"
    assert _should_rebuild_frontmatter(explicit_cover, meta) is False


def test_preprocess_latex_for_word_normalizes_advisor_en_prefix():
    latex = r"""
\documentclass{Style/ucasthesis}
\ADVISOR{Supervisor: Professor}
\begin{document}
\end{document}
"""
    _, metadata = preprocess_latex_for_word(latex, "ucas_thesis")
    assert metadata.advisor_en == "Professor"


def test_preprocess_latex_for_word_uses_profile_metadata_field_rules():
    latex = r"""
\documentclass{article}
\title{Demo}
\MENTOR{Tutor: Dr. Alice}
\begin{document}
\end{document}
"""
    profile = DocxProfile(
        preprocessor=PreprocessorConfig(
            title_implies_cover=True,
            preamble_metadata_fields=[
                MetadataFieldRuleConfig(
                    attr="advisor_en",
                    command="MENTOR",
                    strip_prefix_regex=r"^\s*tutor\s*[:：]\s*",
                )
            ],
        )
    )

    with patch("app.core.compiler.latex2docx.profile.load_profile", return_value=profile):
        _, metadata = preprocess_latex_for_word(latex, "demo")

    assert metadata.advisor_en == "Dr. Alice"
    assert metadata.has_cover is True


def test_preprocess_latex_for_word_uses_profile_frontmatter_labels_and_strip_commands():
    latex = r"""
\documentclass{article}
\begin{document}
\customfront
\keywords{甲}
\KEYWORDS{Beta}
{\contentsname}
{\listfigurename}
{\listtablename}
\end{document}
"""
    profile = DocxProfile(
        labels=LabelsConfig(
            toc="TABLE OF CONTENTS",
            list_of_figures="FIGURE INDEX",
            list_of_tables="TABLE INDEX",
            keywords_zh_prefix="KW-ZH: ",
            keywords_en_prefix="KW-EN: ",
        ),
        preprocessor=PreprocessorConfig(
            strip_body_commands=["customfront"],
        ),
    )

    with patch("app.core.compiler.latex2docx.profile.load_profile", return_value=profile):
        cleaned, _ = preprocess_latex_for_word(latex, "demo")

    assert "\\customfront" not in cleaned
    assert "\\textbf{KW-ZH: }甲" in cleaned
    assert "\\textbf{KW-EN: }Beta" in cleaned
    assert "{TABLE OF CONTENTS}" in cleaned
    assert "{FIGURE INDEX}" in cleaned
    assert "{TABLE INDEX}" in cleaned


def test_convert_latex_to_docx_defaults_preserve_numbering_and_skip_frontmatter(tmp_path: Path):
    out = tmp_path / "out.docx"
    fake_doc = MagicMock()
    fake_doc.save.side_effect = lambda p: Path(p).write_bytes(b"docx")
    fake_converter = MagicMock()
    fake_converter.convert.return_value = fake_doc

    with patch("app.core.compiler.latex2docx.profile.load_profile", return_value=MagicMock()), \
         patch("app.core.compiler.latex2docx.converter.LatexToDocxConverter", return_value=fake_converter), \
         patch("app.core.compiler.latex2docx._strip_numbering_part") as strip_mock, \
         patch("app.core.compiler.latex2docx._inject_footnotes_part") as footnote_mock, \
         patch("app.core.compiler.latex2docx.frontmatter.get_frontmatter_builder") as builder_mock:
        convert_latex_to_docx(
            latex_content=r"\begin{document}ok\end{document}",
            output_path=out,
            metadata=WordExportMetadata(has_cover=True),
            template_id="ucas_thesis",
        )

    assert out.exists()
    strip_mock.assert_not_called()
    footnote_mock.assert_called_once()
    builder_mock.assert_not_called()


def test_convert_latex_to_docx_can_enable_frontmatter_and_strip_numbering(tmp_path: Path):
    out = tmp_path / "out.docx"
    fake_doc = MagicMock()
    fake_doc.save.side_effect = lambda p: Path(p).write_bytes(b"docx")
    fake_converter = MagicMock()
    fake_converter.convert.return_value = fake_doc
    fake_builder = MagicMock()

    with patch("app.core.compiler.latex2docx.profile.load_profile", return_value=MagicMock()), \
         patch("app.core.compiler.latex2docx.converter.LatexToDocxConverter", return_value=fake_converter), \
         patch("app.core.compiler.latex2docx._strip_numbering_part") as strip_mock, \
         patch("app.core.compiler.latex2docx._inject_footnotes_part") as footnote_mock, \
         patch("app.core.compiler.latex2docx.frontmatter.get_frontmatter_builder", return_value=fake_builder):
        convert_latex_to_docx(
            latex_content=r"\begin{document}ok\end{document}",
            output_path=out,
            metadata=WordExportMetadata(has_cover=True),
            template_id="ucas_thesis",
            build_frontmatter=True,
            strip_numbering_part=True,
        )

    fake_builder.build.assert_called_once()
    strip_mock.assert_called_once_with(out)
    footnote_mock.assert_called_once()


@pytest.mark.asyncio
async def test_download_word_compiles_before_convert(tmp_path: Path, monkeypatch):
    project = SimpleNamespace(
        id="p1",
        name="demo",
        template_id="",
        latex_content=r"\begin{document}Hello\end{document}",
    )
    monkeypatch.setattr(settings, "STORAGE_DIR", str(tmp_path))
    sequence: list[str] = []

    async def fake_compile(latex_content, output_dir, support_dirs=None):
        sequence.append("compile")
        output_dir.mkdir(parents=True, exist_ok=True)
        (output_dir / "document.tex").write_text(latex_content, encoding="utf-8")
        return CompileResult(success=True, pdf_path=str(output_dir / "document.pdf"), log="")

    def fake_preprocess(content, template_id=""):
        return content, WordExportMetadata()

    def fake_convert(**kwargs):
        sequence.append("convert")
        out = Path(kwargs["output_path"])
        out.write_bytes(b"docx")

    with patch("app.api.v1.compiler.compile_latex", side_effect=fake_compile), \
         patch("app.api.v1.compiler.preprocess_latex_for_word", side_effect=fake_preprocess), \
         patch("app.api.v1.compiler.convert_latex_to_docx", side_effect=fake_convert):
        response = await download_word(project)

    assert sequence == ["compile", "convert"]
    assert response.path.endswith("document.docx")
