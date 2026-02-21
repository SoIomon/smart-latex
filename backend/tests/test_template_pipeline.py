"""
测试模板提取 → LaTeX 生成管线是否正确使用了模板。

测试组 1-4：确定性函数（无需 mock）
测试组 5-6：需要 mock LLM
"""

import asyncio
import json
from pathlib import Path
from unittest.mock import AsyncMock, patch, MagicMock

import pytest

# ---------------------------------------------------------------------------
# 常量
# ---------------------------------------------------------------------------
BACKEND_DIR = Path(__file__).parent.parent
TEST_DOC_DIR = BACKEND_DIR.parent / "test_doc"

TEMPLATE_DOCX = TEST_DOC_DIR / "通信所最终报告模板.docx"
CONTENT_DOCS = [
    TEST_DOC_DIR / "载荷可维可测要求.docx",
    TEST_DOC_DIR / "XY二代轨道特性分析.docx",
    TEST_DOC_DIR / "二代1.6提交材料-研发中心激光.docx",
]

CUSTOM_TEMPLATE_ID = "comm_research_report"
ARTICLE_TEMPLATE_ID = "academic_paper"

# ---------------------------------------------------------------------------
# 测试组 1：DocxParser 模板格式提取
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_parse_template_docx_extracts_formatting():
    """DocxParser 能从通信所最终报告模板.docx 正确提取格式信息。"""
    from app.core.parsers.docx_parser import DocxParser

    if not TEMPLATE_DOCX.exists():
        pytest.skip(f"模板文件不存在: {TEMPLATE_DOCX}")

    parser = DocxParser()
    parsed = await parser.parse(TEMPLATE_DOCX)

    # 文本非空
    assert parsed.text, "parsed.text 应非空"

    # 有 Heading 结构
    assert len(parsed.sections) > 0, "应包含至少一个 section（Heading 结构）"

    # 格式元数据
    fmt = parsed.metadata.get("formatting")
    assert fmt is not None, "metadata 应包含 formatting"

    # style_formats 非空且包含 Heading 相关 key
    style_formats = fmt.get("style_formats", {})
    assert style_formats, "style_formats 不应为空"
    heading_keys = [k for k in style_formats if "Heading" in k or "heading" in k.lower()]
    assert heading_keys, f"style_formats 应包含 Heading 相关 key，实际 keys: {list(style_formats.keys())}"

    # page_layouts 非空
    page_layouts = fmt.get("page_layouts", [])
    assert page_layouts, "page_layouts 不应为空"
    first_layout = page_layouts[0]
    assert "page_width_cm" in first_layout or "page_height_cm" in first_layout, "page_layout 应包含页面尺寸"

    # image_count 是整数
    assert isinstance(fmt.get("image_count", 0), int), "image_count 应为整数"


# ---------------------------------------------------------------------------
# 测试组 1b：DocxParser 表格提取（封面 + 修改记录）
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_parse_template_docx_extracts_cover_table():
    """DocxParser 能从模板 docx 中提取封面表格内容到 parsed.text。"""
    from app.core.parsers.docx_parser import DocxParser

    if not TEMPLATE_DOCX.exists():
        pytest.skip(f"模板文件不存在: {TEMPLATE_DOCX}")

    parser = DocxParser()
    parsed = await parser.parse(TEMPLATE_DOCX)

    text = parsed.text
    # 封面表格应包含机构名
    assert "上海微小卫星工程中心" in text, \
        "parsed.text 应包含封面表格中的机构名"
    # 表格标记应存在
    assert "[表格]" in text, "parsed.text 应包含 [表格] 标记"


@pytest.mark.asyncio
async def test_parse_template_docx_extracts_revision_table():
    """DocxParser 能从模板 docx 中提取修改记录表列头到 parsed.text。"""
    from app.core.parsers.docx_parser import DocxParser

    if not TEMPLATE_DOCX.exists():
        pytest.skip(f"模板文件不存在: {TEMPLATE_DOCX}")

    parser = DocxParser()
    parsed = await parser.parse(TEMPLATE_DOCX)

    text = parsed.text
    for keyword in ["更改摘要", "修改章节", "备注"]:
        assert keyword in text, f"parsed.text 应包含修改记录表列头 '{keyword}'"


@pytest.mark.asyncio
async def test_parse_template_docx_table_content_metadata():
    """tables_info 应包含 content 字段，封面表和修改记录表都有完整行内容。"""
    from app.core.parsers.docx_parser import DocxParser

    if not TEMPLATE_DOCX.exists():
        pytest.skip(f"模板文件不存在: {TEMPLATE_DOCX}")

    parser = DocxParser()
    parsed = await parser.parse(TEMPLATE_DOCX)

    fmt = parsed.metadata.get("formatting", {})
    tables = fmt.get("tables", [])
    assert len(tables) >= 2, f"应至少有 2 个表格，实际 {len(tables)}"

    # 封面表（第一个表格）应有 content 字段
    cover_table = tables[0]
    assert "content" in cover_table, "封面表格应包含 content 字段"
    cover_flat = " ".join(
        cell for row in cover_table["content"] for cell in row
    )
    assert "上海微小卫星工程中心" in cover_flat, \
        f"封面表格 content 应包含机构名，实际: {cover_flat[:200]}"

    # 修改记录表（第二个表格）应有 content 字段
    revision_table = tables[1]
    assert "content" in revision_table, "修改记录表应包含 content 字段"
    revision_flat = " ".join(
        cell for row in revision_table["content"] for cell in row
    )
    assert "更改摘要" in revision_flat or "修改章节" in revision_flat, \
        f"修改记录表 content 应包含'更改摘要'或'修改章节'，实际: {revision_flat[:200]}"


# ---------------------------------------------------------------------------
# 测试组 2：DocxParser 内容文档解析
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_parse_content_documents():
    """3 个内容文档都能被正确解析。"""
    from app.core.parsers.docx_parser import DocxParser

    parser = DocxParser()

    for doc_path in CONTENT_DOCS:
        if not doc_path.exists():
            pytest.skip(f"内容文档不存在: {doc_path}")

        parsed = await parser.parse(doc_path)

        assert parsed.text, f"{doc_path.name}: parsed.text 应非空"
        assert len(parsed.text) > 100, f"{doc_path.name}: 文本长度应 > 100，实际 {len(parsed.text)}"
        assert parsed.metadata.get("filename") == doc_path.name, (
            f"filename 应为 {doc_path.name}，实际 {parsed.metadata.get('filename')}"
        )
        assert len(parsed.sections) > 0, f"{doc_path.name}: 应有至少一个 section"


# ---------------------------------------------------------------------------
# 测试组 3：模板注册表功能
# ---------------------------------------------------------------------------


def test_template_registry_discovers_custom_template():
    """discover_templates() 结果中包含 custom_communication_final_report。"""
    from app.core.templates.registry import discover_templates

    templates = discover_templates()
    template_ids = [t["id"] for t in templates]
    assert CUSTOM_TEMPLATE_ID in template_ids, (
        f"应发现 {CUSTOM_TEMPLATE_ID}，实际模板列表: {template_ids}"
    )


def test_template_registry_returns_correct_content():
    """get_template 和 get_template_content 返回正确信息。"""
    from app.core.templates.registry import get_template, get_template_content

    # get_template
    tmpl = get_template(CUSTOM_TEMPLATE_ID)
    assert tmpl is not None, f"get_template({CUSTOM_TEMPLATE_ID}) 不应返回 None"
    assert "name" in tmpl
    assert "description" in tmpl

    # get_template_content
    content = get_template_content(CUSTOM_TEMPLATE_ID)
    assert content is not None, "get_template_content 不应返回 None"
    assert r"\documentclass" in content and "ctexrep" in content
    assert r"\titleformat{\chapter}" in content
    assert "<< title >>" in content, "模板应包含 Jinja2 变量 << title >>"


# ---------------------------------------------------------------------------
# 测试组 4：确定性管线函数 — 模板使用的核心证明
# ---------------------------------------------------------------------------


def test_detect_document_class_returns_report_for_custom_template():
    """_detect_document_class 对 custom 模板返回 'ctexrep'，对 academic_paper 返回 'article'。"""
    from app.services.generation_service import _detect_document_class

    assert _detect_document_class(CUSTOM_TEMPLATE_ID) == "ctexrep"
    assert _detect_document_class(ARTICLE_TEMPLATE_ID) == "article"


def test_section_commands_use_chapter_for_report():
    r"""report/ctexrep class 的 top 命令是 \chapter，article class 的 top 是 \section。"""
    from app.services.generation_service import _get_section_commands

    report_cmds = _get_section_commands("report")
    assert report_cmds["top"] == r"\chapter"
    assert report_cmds["second"] == r"\section"

    ctexrep_cmds = _get_section_commands("ctexrep")
    assert ctexrep_cmds["top"] == r"\chapter"
    assert ctexrep_cmds["second"] == r"\section"

    article_cmds = _get_section_commands("article")
    assert article_cmds["top"] == r"\section"
    assert article_cmds["second"] == r"\subsection"


def test_template_rules_contain_preamble_and_hierarchy():
    """_get_template_rules 返回包含模板 preamble 和章节层级信息的字符串。"""
    from app.services.generation_service import _get_template_rules

    rules = _get_template_rules(CUSTOM_TEMPLATE_ID)
    assert rules, "_get_template_rules 不应返回空字符串"

    # 应包含 preamble 中的信息
    assert r"\documentclass" in rules, "rules 应包含 \\documentclass"
    # 应包含章节层级信息
    assert r"\chapter" in rules, "rules 应包含 \\chapter 层级信息"


def test_build_preamble_uses_template_content():
    r"""_build_preamble_from_template 使用了模板的 preamble，而非默认 article。"""
    from app.services.generation_service import _build_preamble_from_template

    outline = {
        "title": "综合测试报告",
        "author": "测试作者",
        "institution": "测试机构",
        "version": "1.0",
        "abstract": "这是测试摘要内容",
    }

    preamble = _build_preamble_from_template(outline, CUSTOM_TEMPLATE_ID)

    # === 断言：来自模板 ===
    assert "ctexrep" in preamble, \
        "preamble 应包含模板的 ctexrep documentclass"
    assert r"\usepackage{titlesec}" in preamble, \
        "preamble 应包含模板特有的 titlesec 包"
    assert r"\titleformat{\chapter}" in preamble, \
        "preamble 应包含模板的 chapter 标题格式"

    # === 断言：Jinja2 变量已替换 ===
    assert "综合测试报告" in preamble, "title 应被替换为 outline 中的值"
    assert r"\begin{document}" in preamble, "应包含 \\begin{document}"

    # === 断言：无未替换的 Jinja2 变量 ===
    assert "<< title >>" not in preamble, "不应有未替换的 << title >>"

    # === 对比：academic_paper 模板应产生不同输出 ===
    article_preamble = _build_preamble_from_template(outline, ARTICLE_TEMPLATE_ID)
    assert "{article}" in article_preamble, "academic_paper 应使用 article class"
    assert "ctexrep" not in article_preamble, "academic_paper 不应包含 ctexrep class"


# ---------------------------------------------------------------------------
# 测试组 5：完整管线集成测试（mock LLM）
# ---------------------------------------------------------------------------

# --- mock 返回值 ---

MOCK_ANALYSIS = json.dumps({
    "title": "测试文档",
    "authors": [],
    "type": "报告",
    "key_topics": ["测试"],
    "sections": [{"heading": "全文", "summary": "测试内容", "key_points": []}],
    "abstract": "测试摘要",
    "references": [],
    "importance": "中",
})

MOCK_OUTLINE = json.dumps({
    "title": "综合测试报告",
    "author": "测试作者",
    "institution": "测试机构",
    "version": "1.0",
    "abstract": "测试摘要内容",
    "chapters": [
        {
            "chapter_id": 1,
            "title": "第一章",
            "description": "测试",
            "source_docs": [1],
            "subsections": [],
        }
    ],
    "appendices": [],
})

MOCK_CHAPTER_CONTENT = r"\chapter{第一章}" + "\n这是测试内容。"


async def _mock_chat(messages, temperature=0.7, max_tokens=16384):
    """根据 prompt 内容返回不同的 mock JSON。注意：先检查大纲，因为大纲 prompt 也包含「分析」二字。"""
    prompt = messages[0]["content"] if messages else ""
    if "大纲" in prompt or "outline" in prompt.lower():
        return MOCK_OUTLINE
    elif "分析" in prompt or "analysis" in prompt.lower() or "analyze" in prompt.lower():
        return MOCK_ANALYSIS
    # 默认返回 analysis
    return MOCK_ANALYSIS


async def _mock_chat_stream(messages, temperature=0.7, max_tokens=16384):
    """返回 async generator，yield 章节 LaTeX 内容。"""
    for chunk in [r"\chapter{第一章}", "\n", "这是测试内容。"]:
        yield chunk


@pytest.mark.asyncio
async def test_full_pipeline_generates_latex_using_template():
    """完整管线使用 custom 模板生成的 LaTeX 包含模板特征。"""
    from app.services.generation_service import generate_latex_pipeline_internal

    documents = [
        {"filename": "test.docx", "content": "这是一份测试文档内容，用于验证管线功能。" * 10},
    ]

    with patch("app.core.llm.chains.doubao_client") as mock_client:
        mock_client.chat = AsyncMock(side_effect=_mock_chat)
        mock_client.chat_stream = MagicMock(side_effect=_mock_chat_stream)

        # 收集所有 chunk 事件
        chunks = []
        async for event in generate_latex_pipeline_internal(documents, CUSTOM_TEMPLATE_ID):
            if event.get("event") == "chunk":
                chunks.append(event["content"])

        full_latex = "".join(chunks)

    # === 核心断言：证明用了模板 ===
    assert "ctexrep" in full_latex, \
        "输出应包含模板的 ctexrep documentclass"
    assert r"\usepackage{titlesec}" in full_latex, \
        "输出应包含模板特有的 titlesec 包"
    assert r"\titleformat{\chapter}" in full_latex, \
        "输出应包含模板的 chapter 标题格式"
    assert "综合测试报告" in full_latex, \
        "输出应包含 outline 中的 title（已替换）"
    assert r"\chapter{第一章}" in full_latex, \
        "输出应使用 \\chapter 而非 \\section"
    assert r"\end{document}" in full_latex, \
        "输出应包含 \\end{document}"


@pytest.mark.asyncio
async def test_full_pipeline_with_default_template_uses_article():
    """使用 academic_paper 模板时，输出使用 article class 而非 report。"""
    from app.services.generation_service import generate_latex_pipeline_internal

    documents = [
        {"filename": "test.docx", "content": "这是一份测试文档内容，用于验证管线功能。" * 10},
    ]

    # 修改 mock 章节内容使用 \section 而非 \chapter
    async def _article_mock_stream(messages, temperature=0.7, max_tokens=16384):
        for chunk in [r"\section{第一章}", "\n", "这是测试内容。"]:
            yield chunk

    with patch("app.core.llm.chains.doubao_client") as mock_client:
        mock_client.chat = AsyncMock(side_effect=_mock_chat)
        mock_client.chat_stream = MagicMock(side_effect=_article_mock_stream)

        chunks = []
        async for event in generate_latex_pipeline_internal(documents, ARTICLE_TEMPLATE_ID):
            if event.get("event") == "chunk":
                chunks.append(event["content"])

        full_latex = "".join(chunks)

    assert "{article}" in full_latex, "academic_paper 模板应使用 article class"
    assert "ctexrep" not in full_latex, "academic_paper 不应包含 ctexrep"
    assert r"\end{document}" in full_latex


# ---------------------------------------------------------------------------
# 测试组 6：验证 LLM prompt 中传递了模板规则
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_chapter_generation_receives_template_rules():
    """generate_chapter 的 prompt 中确实包含了模板的格式规则。"""
    from app.services.generation_service import _get_template_rules, _get_section_commands

    template_rules = _get_template_rules(CUSTOM_TEMPLATE_ID)
    section_commands = _get_section_commands("report")

    captured_messages = []

    async def _capturing_stream(messages, temperature=0.7, max_tokens=16384):
        captured_messages.append(messages)
        for chunk in [r"\chapter{测试}", "\n", "内容"]:
            yield chunk

    with patch("app.core.llm.chains.doubao_client") as mock_client:
        mock_client.chat_stream = MagicMock(side_effect=_capturing_stream)

        from app.core.llm.chains import generate_chapter

        await generate_chapter(
            doc_title="综合测试报告",
            chapter={"chapter_id": 1, "title": "第一章", "description": "测试", "subsections": []},
            chapter_index=1,
            total_chapters=1,
            source_documents=[{"filename": "test.docx", "content": "测试内容", "analysis": {}}],
            template_rules=template_rules,
            section_commands=section_commands,
        )

    assert captured_messages, "应该捕获到 LLM 调用的 messages"

    # 检查 prompt 内容
    prompt_content = captured_messages[0][0]["content"]
    assert r"\documentclass" in prompt_content or "模板" in prompt_content, \
        "prompt 应包含 documentclass 或模板相关内容"
    assert r"\chapter" in prompt_content, \
        "prompt 应包含 \\chapter 作为章节命令"
