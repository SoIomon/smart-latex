# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## 项目概述

Smart-LaTeX 是一个 AI 驱动的文档转换系统 — 上传 Word/PDF/Markdown 文档，自动生成专业 LaTeX 文档并编译为 PDF。后端 FastAPI + 前端 React。

## 常用命令

### 开发模式
```bash
./scripts/dev.sh              # 同时启动后端 (8000) 和前端 (5173)，支持热重载
```

### 仅后端
```bash
cd backend
source venv/bin/activate
uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
pytest                        # 运行全部测试
pytest tests/test_template_pipeline.py -k test_parse_template  # 运行单个测试
```

### 仅前端
```bash
cd frontend
npm run dev                   # Vite 开发服务器 localhost:5173
npm run build                 # 生产构建 → frontend/dist/
npm run lint                  # ESLint 检查
```

### 安装与生产部署
```bash
./install.sh                  # 创建 venv、安装依赖、构建前端、生成 .env
./start.sh                    # 通过后端服务前端构建产物，访问 localhost:8000
```

## 架构

### 生成管线（4 个阶段）
1. **阶段 1：文档分析** — LLM 并行分析上传文档（batch=10）
2. **阶段 2：大纲规划** — LLM 根据分析结果 + 结构化模板信息生成文档结构
3. **阶段 3：章节生成** — LLM 并行生成各章 LaTeX（batch=8），每章用 `xelatex -draftmode` 验证，出错则用 fix agent 自动修复。每章注入全文大纲上下文，避免跨章节重复
4. **阶段 4：审查修订** — tool-calling agent 审查拼接后的完整文档，检查内容重复、术语一致性、交叉引用等问题（最多 30 轮）。失败时回退到未审查版本

管线入口：`backend/app/services/generation_service.py` → `generate_latex_pipeline()`

### 后端 (`backend/app/`)
- **`api/v1/`** — FastAPI 路由：projects, documents, templates, generation, chat, compiler, selection, settings
- **`api/schemas/`** — Pydantic 请求/响应模型
- **`core/compiler/`** — 通过 latexmk 编译 LaTeX，在临时目录中沙箱运行。包含 LaTeX→DOCX 转换器（`latex2docx/`）和 Word 前后处理器
- **`core/llm/`** — LLM 集成层：
  - `client.py` — `DoubaoClient`，封装 `AsyncOpenAI`，兼容 OpenAI API
  - `chains.py` — Prompt 链函数（`analyze_document`、`plan_outline`、`generate_chapter_stream`）
  - `fix_agent.py` — 单章 LaTeX 编译错误修复 agent（tool-calling）
  - `review_agent.py` — 生成后质量审查 agent（tool-calling）
  - `tools.py` — 共享工具实现（`DocumentState`、`read_lines`、`replace_lines`、`search_text`）
  - `prompts/` — Jinja2 prompt 模板（注意：不是 LaTeX 模板）
- **`core/parsers/`** — 文档解析器（DOCX, PDF, Markdown, TXT），通过 `ParserRegistry` 分发
- **`core/templates/`** — 模板引擎，包含 `builtin/`（内置）和 `custom/`（自定义）模板。每个模板有 `meta.json`（id, name, variables, doc_class_type, support_dirs）
- **`core/fonts/`** — 跨平台 CJK 字体检测、名称映射、内置 FandolFonts 降级方案
- **`services/`** — 业务逻辑（generation, document, project, chat 服务）
- **`models/`** — SQLAlchemy 异步模型：Project → Documents, ChatMessages（级联删除）

### 前端 (`frontend/src/`)
- **`pages/`** — HomePage（项目列表）、Workspace（编辑器+聊天+文档）、TemplateGallery
- **`stores/`** — Zustand 状态管理：projectStore, editorStore, documentStore, chatStore
- **`api/`** — Axios 客户端函数（baseURL: `/api/v1`，通过 Vite 代理到后端）
- **`components/Editor/`** — CodeMirror 6 + LaTeX 语法高亮
- **`hooks/useSSE`** — Server-Sent Events 消费生成/编译进度流

### 流式传输模式
生成（`/generate`）和编译（`/compile-and-fix`）端点均使用 SSE。前端通过 `useSSE` hook 消费。事件类型：`stage`、`outline`、`chunk`、`done`、`error`。

### 数据库
SQLite + async SQLAlchemy（`aiosqlite`）。数据库文件位于 `storage/smart_latex.db`。

## 关键技术细节

### Jinja2 模板分隔符
为避免与 LaTeX `{}` 冲突，`.tex.j2` 模板文件使用自定义分隔符：
- 变量：`<< >>`（非 `{{ }}`）
- 块：`<% %>`（非 `{% %}`）
- 注释：`<# #>`（非 `{# #}`）

模板渲染必须使用 `app/core/templates/engine.py` 的 `render_string()` — 禁止用正则替换（会破坏 Jinja2 默认值）。

**注意**：`core/llm/prompts/` 下的 LLM prompt 模板使用标准 Jinja2 `{{ }}` 语法（不含 LaTeX）。只有 `.tex.j2` 文件使用自定义分隔符。

### 模板系统
- 内置模板在 `backend/app/core/templates/builtin/`，每个模板有 `meta.json` 和 `.tex.j2` 文件
- `support_dirs`（meta.json）声明需要复制到编译目录的静态文件夹（cls/sty/bst 文件）
- `doc_class_type`（"article"/"report"/"book"）决定章节命令层级
- `docx_profile`（meta.json）配置 LaTeX→DOCX 导出（字体、编号、封面、样式）

### LLM 客户端
`DoubaoClient` 封装 `AsyncOpenAI`，兼容 OpenAI API。配置在 `backend/.env` 或通过 `POST /api/v1/settings/llm` 动态修改。流式响应必须检查：某些模型返回空 `choices` 数组 — 始终加 `if not chunk.choices: continue` 守护。

### Tool-Calling Agent 模式
`fix_agent.py` 和 `review_agent.py` 共享相同模式：
- 复用 `tools.py` 中的 `DocumentState` 和工具（read_lines, replace_lines, search_text, get_document_outline）
- 通过 yield `AgentEvent` 对象通信（type: thinking/tool_call/tool_result/latex/done/error）
- 每轮限制 `replace_lines` 只能调用一次（替换会改变行号）
- 同时提供流式（`run_*_loop`）和非流式封装函数

### 字体系统
- `core/fonts/__init__.py` — 平台检测、逐字体可用性检查、FandolFonts 降级
- `core/fonts/bundled/` — 内置 FandolFonts OTF 文件 + `VERSION.json`
- `CJK_FONTSET` 配置：`auto`（默认）/ `mac` / `windows` / `linux` / `fandol`
- `remap_cjk_fonts()` 将 LaTeX 源码中的硬编码字体名转换为当前平台的等效字体
- `engine.py` 的 `_build_tex_env()` 设置 `OSFONTDIR` 包含内置字体目录
- 字体检测使用 TTL 缓存（5 分钟）；外部安装字体后调用 `refresh_cjk_fonts()` 刷新

### 文档解析
`python-docx` 的 `doc.paragraphs` 会跳过 `<w:tbl>` 元素 — 需遍历 `doc.element.body` 来捕获表格。`DocxParagraph(child, body)` 会失败（CT_Body 没有 `.part` 属性）— 使用预获取的段落列表和索引替代。

### macOS 上的 LaTeX
- TeX 发行版：`/Library/TeX/texbin/`（texlive 2025basic）
- 安装宏包：`tlmgr --usermode install <pkg>`
- CJK 字体：STSong（宋体）、Heiti SC（黑体）— macOS 没有 SimSun/SimHei
- 模板使用 `fontset=none`（ctexrep）避免字体冲突
- macOS 的 OSFONTDIR 支持文件名查找但不支持 family name 查找 — 字体必须安装到 ~/Library/Fonts

## 配置

所有配置在 `backend/.env`（通过 `pydantic-settings` 加载）。关键变量：`DOUBAO_API_KEY`、`DOUBAO_BASE_URL`、`DOUBAO_MODEL`、`DATABASE_URL`、`STORAGE_DIR`、`LATEX_CMD`、`CORS_ORIGINS`、`CJK_FONTSET`。

## 技术栈
- **后端**：FastAPI, SQLAlchemy async, Jinja2, python-docx, PyMuPDF, openai SDK, sse-starlette
- **前端**：React 19, TypeScript, Vite, Zustand, Ant Design, CodeMirror 6, Axios
- **编译**：XeLaTeX + latexmk
- **导出**：LaTeX→DOCX 直接转换器（python-docx），Pandoc 作为备选方案
