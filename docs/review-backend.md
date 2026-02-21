# Smart-LaTeX 后端代码审查报告

**审查日期**: 2026-02-17
**审查范围**: `/backend/app/` 目录下所有 Python 源代码
**审查人**: 资深后端工程师（AI 辅助）

---

## 一、架构总览

项目采用 FastAPI 框架，整体分层结构如下：

```
app/
├── main.py            # 应用入口、中间件、生命周期管理
├── config.py          # 配置管理（pydantic-settings）
├── dependencies.py    # FastAPI 依赖注入（DB session、Project 获取）
├── api/
│   ├── router.py      # 路由注册
│   ├── schemas/       # Pydantic 请求/响应模型
│   └── v1/            # 各业务端点
├── services/          # 业务逻辑层
├── models/            # ORM 模型 + 数据库初始化
└── core/              # 核心模块（LLM、编译器、解析器、模板）
```

### 架构评价

- **分层合理**：Router → Service → Core 三层分离，职责清晰
- **API 版本化**：使用 `/api/v1` 前缀，具备版本演进能力
- **依赖注入**：通过 FastAPI Depends 管理 DB session 和 Project 获取，模式正确
- **SSE 流式处理**：chat/generation/compile-and-fix 等长时间操作采用 SSE，用户体验好

---

## 二、问题清单

### 问题 1（高）: .env 文件包含真实 API Key 且已被提交到版本控制

**文件**: `/backend/.env:1`
**描述**: `.env` 文件中包含真实的 `DOUBAO_API_KEY=b5ded7ec-7bd4-41eb-8cdb-fd8090bb5a6e`。该文件未被 `.gitignore` 排除（git status 未显示在 untracked 中，说明已被跟踪或忽略），但如果项目公开分享或 `.gitignore` 配置不当，API Key 会泄露。
**严重程度**: **高**
**修复建议**:
1. 确认 `.env` 已被 `.gitignore` 忽略（项目根目录或 backend 目录下的 `.gitignore`）
2. 如果已被提交到 git 历史，需要轮换 API Key
3. 建议使用环境变量或 secret manager 管理敏感配置

---

### 问题 2（高）: 编译引擎使用 shell=True 执行命令，存在命令注入风险

**文件**: `/backend/app/core/compiler/engine.py:23-34`
**描述**: `compile_latex` 函数使用 `asyncio.create_subprocess_shell` 执行编译命令。虽然当前 `settings.LATEX_CMD` 来自配置文件，`latex_content` 是写入文件而非拼接命令，但 shell=True 的调用方式本身存在风险。如果未来 `LATEX_CMD` 或文件名参数被外部输入影响，可能导致命令注入。
**严重程度**: **高**
**修复建议**:
```python
# 改为 create_subprocess_exec，避免 shell 注入
process = await asyncio.create_subprocess_exec(
    settings.LATEX_CMD, "-xelatex", "-interaction=nonstopmode", "document.tex",
    stdout=asyncio.subprocess.PIPE,
    stderr=asyncio.subprocess.PIPE,
    cwd=str(output_dir),
    env={**os.environ, "PATH": f"/Library/TeX/texbin:{os.environ.get('PATH', '')}"},
)
```

---

### 问题 3（高）: /storage 目录直接挂载为静态文件服务，可能泄露敏感数据

**文件**: `/backend/app/main.py:41-42`
**描述**: `app.mount("/storage", StaticFiles(directory=str(storage_path)), name="storage")` 将整个 storage 目录暴露为静态文件服务。这意味着：
- SQLite 数据库文件 `smart_latex.db` 可以被直接下载（`/storage/smart_latex.db`）
- 所有用户上传的文档均可被任意访问（无鉴权）
- 编译日志和中间文件也可能被访问

**严重程度**: **高**
**修复建议**:
1. 不要挂载整个 storage 目录，只挂载特定子目录（如 output/pdf）
2. 或者改为通过 API 端点提供文件访问，并加上权限校验
3. 将数据库文件放在 storage 目录之外

---

### 问题 4（高）: 前端 SPA catch-all 路由可能导致路径遍历

**文件**: `/backend/app/main.py:48-54`
**描述**: `serve_frontend` 函数使用 `file_path = FRONTEND_DIST / full_path` 拼接路径。虽然 FastAPI 的路径参数有一定限制，但如果 `full_path` 包含 `..` 等路径穿越字符，可能访问到 `FRONTEND_DIST` 目录之外的文件。`FileResponse(str(file_path))` 不会验证路径是否在预期目录范围内。
**严重程度**: **高**
**修复建议**:
```python
@app.get("/{full_path:path}")
async def serve_frontend(request: Request, full_path: str):
    file_path = (FRONTEND_DIST / full_path).resolve()
    # 验证路径在允许的目录范围内
    if full_path and file_path.is_file() and str(file_path).startswith(str(FRONTEND_DIST.resolve())):
        return FileResponse(str(file_path))
    return FileResponse(str(FRONTEND_DIST / "index.html"))
```

---

### 问题 5（高）: sandbox 隔离不充分 — 编译目录固定在用户项目目录下

**文件**: `/backend/app/core/compiler/sandbox.py:6-10`
**描述**: `create_sandbox` 函数仅在 `project_output_dir / "build"` 下创建目录，没有真正的沙箱隔离。LaTeX 编译器（`latexmk -xelatex`）具有执行 shell 命令的能力（通过 `\write18`、`\input|` 等），而当前没有：
- 使用 `-no-shell-escape` 标志禁止 shell escape
- 使用临时目录（`tempfile.mkdtemp`）隔离
- 限制编译进程的文件系统访问权限

**严重程度**: **高**
**修复建议**:
1. 在编译命令中添加 `-no-shell-escape` 标志
2. 使用 `tempfile.mkdtemp()` 创建真正的临时目录
3. 编译完成后将 PDF 复制回输出目录
4. 生产环境考虑使用 Docker 容器或 seccomp 沙箱

---

### 问题 6（中）: 数据库 Session 未配合事务使用，SSE 生成器中长时间持有 Session

**文件**: `/backend/app/api/v1/generation.py:29-87`, `/backend/app/api/v1/chat.py:27-38`
**描述**: SSE 事件流中，数据库 session 通过依赖注入获取后在整个流式响应期间保持打开。对于长时间运行的 LLM 调用（可能数十秒到数分钟），这意味着：
- Session 长时间被占用
- 在 `generation.py:67-68`，流结束时才调用 `project_service.update_project`，如果此时 session 已过期或连接断开，操作会失败
- `chat_service.py` 中先 save_message（第35行），然后在流式生成期间保持 session，最后再 save_message（第49行），两次 commit 之间没有事务保护

**严重程度**: **中**
**修复建议**:
1. SSE 生成器中的数据库操作应使用独立的 session 上下文
2. 或在流式响应开始前完成必要的 DB 操作，流结束后再获取新 session 进行更新
3. 使用 `async with async_session() as session:` 显式控制 session 生命周期

---

### 问题 7（中）: LLM 调用缺少超时控制和重试机制

**文件**: `/backend/app/core/llm/client.py:16-38`
**描述**: `DoubaoClient` 的 `chat` 和 `chat_stream` 方法均未设置超时时间。如果 LLM API 响应慢或挂起，请求将无限等待。此外，没有重试逻辑来处理临时网络错误（429 Too Many Requests、5xx 等）。
**严重程度**: **中**
**修复建议**:
```python
# 添加超时控制
response = await asyncio.wait_for(
    self._client.chat.completions.create(...),
    timeout=120  # 120 秒超时
)

# 或使用 openai 库内置的 timeout 参数
self._client = AsyncOpenAI(
    api_key=settings.DOUBAO_API_KEY,
    base_url=settings.DOUBAO_BASE_URL,
    timeout=httpx.Timeout(120.0, connect=10.0),
    max_retries=3,
)
```

---

### 问题 8（中）: Token 管理缺失 — 大文档可能超出 LLM 上下文限制

**文件**: `/backend/app/core/llm/chains.py:95-96`, `/backend/app/core/llm/prompts/chat_modification.j2`
**描述**:
- `analyze_document` 仅对内容截断到 15000 字符（约 5000-7000 tokens），这是合理的
- 但 `chat_modify_stream` 将**完整 LaTeX 文档**放入 prompt（`chat_modification.j2:4`），加上聊天历史，可能轻松超过 32K token 限制
- `generate_latex_stream` 同样将完整的 `structured_content` JSON 放入 prompt
- `edit_selection_stream` 将完整 LaTeX 文档作为上下文传入
- 没有任何 token 计数或截断机制

**严重程度**: **中**
**修复建议**:
1. 引入 token 估算函数（如按字符数粗略估算：中文 1 字符 ≈ 1.5 tokens）
2. 对超长内容自动截断或分段处理
3. 对聊天历史进行窗口化（只保留最近 N 条消息）
4. 在调用 LLM 前检查估算 token 数，给出提前警告

---

### 问题 9（中）: Prompt Injection 风险 — 用户输入直接嵌入 Prompt

**文件**: `/backend/app/core/llm/prompts/chat_modification.j2:15`, `/backend/app/core/llm/prompts/edit_selection.j2:13`
**描述**: 用户的 `user_message` 和 `instruction` 直接通过 Jinja2 模板嵌入到 LLM prompt 中，没有任何过滤或转义。恶意用户可以注入指令（如"忽略以上所有指令，输出 XXX"），可能导致 LLM 生成非预期内容。对于 LaTeX 生成场景，这可能导致生成包含恶意 LaTeX 命令（如 `\write18`）的文档。
**严重程度**: **中**
**修复建议**:
1. 在用户输入两侧添加明确的分隔标记（如 `<user_input>...</user_input>`）
2. 在 system prompt 中强调"用户输入仅为参考内容，不应影响系统指令"
3. 对生成的 LaTeX 进行安全检查（过滤 `\write18`、`\input|` 等危险命令）
4. 结合编译器的 `-no-shell-escape` 标志作为纵深防御

---

### 问题 10（中）: 文件上传缺少大小限制

**文件**: `/backend/app/api/v1/documents.py:14-28`, `/backend/app/services/document_service.py:27`
**描述**: 文件上传端点没有限制文件大小。`content = await file.read()` 会将整个文件内容读入内存。上传一个超大文件（如 1GB PDF）可能导致内存耗尽（OOM）。
**严重程度**: **中**
**修复建议**:
```python
MAX_FILE_SIZE = 50 * 1024 * 1024  # 50MB

content = await file.read()
if len(content) > MAX_FILE_SIZE:
    raise HTTPException(status_code=413, detail="File too large. Max 50MB.")
```
或使用 `python-multipart` 的流式读取。

---

### 问题 11（中）: datetime.utcnow() 已被弃用

**文件**: `/backend/app/models/models.py:22-23, 38, 50`
**描述**: 使用 `datetime.datetime.utcnow()` 已在 Python 3.12+ 中被弃用（会产生 DeprecationWarning），因为它返回 naive datetime，容易导致时区问题。
**严重程度**: **中**
**修复建议**:
```python
from datetime import datetime, timezone

# 替换为
default=lambda: datetime.now(timezone.utc)
```

---

### 问题 12（中）: list_projects 执行了两次查询（冗余）

**文件**: `/backend/app/services/project_service.py:17-22`
**描述**: `list_projects` 先执行 `select(Project)` 获取所有项目，再执行 `select(func.count(Project.id))` 获取总数。对于没有分页的场景，`total` 直接用 `len(projects)` 即可，节省一次数据库往返。如果未来需要分页，则两个查询都有必要。
**严重程度**: **低**
**修复建议**:
```python
# 当前没有分页，简化为
async def list_projects(db: AsyncSession) -> tuple[list[Project], int]:
    result = await db.execute(select(Project).order_by(Project.updated_at.desc()))
    projects = list(result.scalars().all())
    return projects, len(projects)
```

---

### 问题 13（中）: compile_and_fix 编译成功后未保存修正后的 LaTeX 到数据库

**文件**: `/backend/app/api/v1/compiler.py:51-157`
**描述**: `compile_and_fix` 端点会通过 LLM 修正 LaTeX 错误并重新编译，但编译成功后只是将修正后的 `current_latex` 通过 SSE 事件返回给前端，并未将其持久化到数据库中（`project.latex_content` 未更新）。如果前端未处理该更新，用户下次打开项目时看到的仍是旧的（有错误的）LaTeX。
**严重程度**: **中**
**修复建议**:
在编译成功的 event 发送前，调用 `project_service.update_project(db, project, latex_content=current_latex)` 保存更新。

---

### 问题 14（中）: CORS 配置仅允许 localhost，生产部署将失败

**文件**: `/backend/app/main.py:30-36`
**描述**: CORS 白名单硬编码为 `["http://localhost:5173", "http://127.0.0.1:5173"]`。部署到服务器后，前端域名不同将导致跨域请求被拒绝。
**严重程度**: **中**
**修复建议**:
1. 将 CORS origins 移到配置文件中：`CORS_ORIGINS: list[str] = ["http://localhost:5173"]`
2. 生产环境设置为实际前端域名
3. 或者当前端和后端同源部署时（已有 SPA 静态文件服务），可以不需要 CORS

---

### 问题 15（中）: 模板 ID 用于文件系统路径，缺少校验

**文件**: `/backend/app/core/templates/registry.py:52-54`
**描述**: `save_custom_template` 中，`template_id` 直接用于创建目录 `CUSTOM_DIR / template_id`。如果 LLM 生成的 `template_id` 包含 `..` 或 `/`，可能导致路径穿越，在预期目录之外写入文件。
**严重程度**: **中**
**修复建议**:
```python
import re

def save_custom_template(template_id: str, meta: dict, template_content: str) -> Path:
    # 校验 template_id 只包含安全字符
    if not re.match(r'^[a-zA-Z0-9_-]+$', template_id):
        raise ValueError(f"Invalid template_id: {template_id}")
    template_dir = CUSTOM_DIR / template_id
    ...
```

---

### 问题 16（低）: PDF 下载端点未验证路径安全性

**文件**: `/backend/app/api/v1/compiler.py:160-168`
**描述**: `download_pdf` 通过 `settings.storage_path / project.id / "output" / "build" / "document.pdf"` 构建 PDF 路径。由于 `project.id` 来自数据库（经过 `get_project` 依赖验证），当前不存在路径遍历风险。但依赖于数据库中 ID 值的安全性。
**严重程度**: **低**
**修复建议**: 可以增加 `resolve()` 后的路径范围检查，作为纵深防御。

---

### 问题 17（低）: DocxParser 和 PdfParser 中的同步阻塞操作

**文件**: `/backend/app/core/parsers/docx_parser.py:9-10`, `/backend/app/core/parsers/pdf_parser.py:9-10`
**描述**: 虽然 `parse` 方法定义为 `async`，但实际执行的 `DocxDocument(str(file_path))` 和 `fitz.open(str(file_path))` 都是同步的 CPU/IO 密集操作，会阻塞事件循环。对于小文件影响不大，但处理大型 PDF（数百页）时可能影响并发性能。
**严重程度**: **低**
**修复建议**:
```python
import asyncio

async def parse(self, file_path: Path) -> ParsedContent:
    return await asyncio.to_thread(self._parse_sync, file_path)

def _parse_sync(self, file_path: Path) -> ParsedContent:
    # 原有的同步解析逻辑
    ...
```

---

### 问题 18（低）: TextParser 未处理编码错误

**文件**: `/backend/app/core/parsers/text_parser.py:8`
**描述**: `file_path.read_text(encoding="utf-8")` 假设所有 .txt 文件都是 UTF-8 编码。如果用户上传 GBK 等其他编码的文件，会抛出 `UnicodeDecodeError` 异常，且该异常未被捕获。
**严重程度**: **低**
**修复建议**:
```python
try:
    text = file_path.read_text(encoding="utf-8")
except UnicodeDecodeError:
    text = file_path.read_text(encoding="gbk", errors="replace")
```
或使用 `chardet` 库自动检测编码。

---

### 问题 19（低）: extract_json 正则可能匹配错误的 JSON 对象

**文件**: `/backend/app/core/llm/output_parsers.py:19`
**描述**: `re.search(r"\{.*\}", text, re.DOTALL)` 使用贪婪匹配，会匹配从第一个 `{` 到最后一个 `}` 之间的所有内容。如果 LLM 输出中包含多个 JSON 对象或其他花括号内容，可能匹配到非预期的范围。
**严重程度**: **低**
**修复建议**: 可以尝试使用更精确的 JSON 提取逻辑，如逐字符匹配括号嵌套深度，或使用 `json.JSONDecoder().raw_decode()` 进行渐进式解析。

---

### 问题 20（低）: 模板发现函数 discover_templates 每次调用都重新扫描文件系统

**文件**: `/backend/app/core/templates/registry.py:27-29`
**描述**: 每次请求 `GET /api/v1/templates` 都会调用 `discover_templates()`，该函数遍历文件系统读取所有 `meta.json`。对于少量模板影响不大，但模板增多后可能成为性能瓶颈。
**严重程度**: **低**
**修复建议**: 添加简单的缓存机制（如 `functools.lru_cache` 或带 TTL 的缓存），或在应用启动时加载一次。

---

### 问题 21（低）: generation_service 中存在大量重复代码

**文件**: `/backend/app/services/generation_service.py:48-216` vs `260-317`
**描述**: `generate_latex_pipeline`（含 DB 依赖）和 `generate_latex_pipeline_internal`（无 DB 依赖）存在大量重复的分析、大纲规划、章节生成逻辑。两者的区别仅在于前者有 SSE stage 事件和 DB 操作。
**严重程度**: **低**
**修复建议**: 提取公共逻辑为内部函数，通过回调或参数控制是否发送 stage 事件。

---

### 问题 22（低）: chat 端点中直接在 router 层查询数据库

**文件**: `/backend/app/api/v1/chat.py:47-55`
**描述**: `get_history` 端点直接在 router 层执行 SQLAlchemy 查询（`from sqlalchemy import select`），绕过了 service 层。这与项目其他地方的分层架构不一致（其他端点通过 service 层访问数据库）。
**严重程度**: **低**
**修复建议**: 将查询逻辑移到 `chat_service.get_chat_history` 中，router 只负责调用 service 并返回结果。

---

### 问题 23（低）: Jinja2 模板引擎 autoescape=False

**文件**: `/backend/app/core/llm/chains.py:11`
**描述**: `_prompt_env = Environment(loader=..., autoescape=False)`。由于这里是用于生成 LLM prompt（不是 HTML），`autoescape=False` 是合理的。但需要注意，如果 prompt 模板中的用户输入包含 Jinja2 特殊字符（`{{`、`{%`），可能导致模板渲染错误或模板注入。
**严重程度**: **低**
**修复建议**: 用户输入内容如果可能包含 `{{` 等 Jinja2 语法，应使用 `SandboxedEnvironment` 或在传入前转义。

---

### 问题 24（低）: 缺少全局异常处理器

**文件**: `/backend/app/main.py`
**描述**: 应用没有注册全局的异常处理器（`@app.exception_handler`）。未预期的异常会返回 FastAPI 默认的 500 响应，可能在生产环境中泄露内部错误信息（堆栈跟踪）。
**严重程度**: **低**
**修复建议**:
```python
@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception):
    logger.exception("Unhandled exception")
    return JSONResponse(
        status_code=500,
        content={"detail": "Internal server error"},
    )
```

---

### 问题 25（低）: 删除文档时未检查关联项目是否正在生成

**文件**: `/backend/app/api/v1/documents.py:39-48`
**描述**: 删除文档时只验证了文档存在且属于该项目，但没有检查该文档是否正在被 generation pipeline 使用。如果在生成过程中删除文档，可能导致生成中断或数据不一致。
**严重程度**: **低**
**修复建议**: 在实际生产环境中可以添加状态锁或乐观锁机制。当前阶段影响不大。

---

## 三、整体评价

### 优点
1. **架构清晰**：分层合理，Router/Service/Core 职责分明
2. **API 设计良好**：RESTful 风格一致，路由命名规范
3. **SSE 流式设计**：LLM 生成和编译修复使用 SSE，用户体验友好
4. **代码简洁**：整体代码量适中，无过度设计
5. **模板系统灵活**：支持内置模板和自定义模板，使用 Jinja2 配合 LaTeX 自定义分隔符避免冲突
6. **Pipeline 设计**：多文档场景有分阶段处理（分析 → 大纲 → 章节生成），并发控制（batch_size=5）合理
7. **错误恢复**：`compile-and-fix` 端点的自动修复逻辑设计良好
8. **Prompt 工程**：Prompt 模板独立管理（.j2 文件），结构清晰，输出格式有明确约束

### 不足
1. **安全问题突出**：shell 注入、路径遍历、storage 目录暴露、缺少文件大小限制
2. **缺少认证授权**：整个 API 无任何身份验证机制（适合本地开发，不适合多用户部署）
3. **LLM 调用健壮性不足**：无超时、无重试、无 token 管理
4. **Session 管理需要改进**：SSE 长连接中的 DB session 生命周期管理不够精细

---

## 四、整体评分

**7.0 / 10**

作为一个 MVP / 原型项目，代码质量和架构设计是不错的。分层清晰，代码整洁，功能完整。主要扣分项在安全方面（shell 注入、路径遍历、storage 暴露）和生产就绪性（无认证、无超时、无 token 管理）。

---

## 五、Top 5 优先修复问题

| 优先级 | 问题 | 严重程度 | 说明 |
|--------|------|----------|------|
| **P0** | 问题 2: 编译命令 shell 注入 + 问题 5: 缺少 `-no-shell-escape` | 高 | LaTeX 编译器可执行任意 shell 命令，是最直接的安全风险 |
| **P0** | 问题 3: /storage 目录暴露数据库和用户文件 | 高 | 数据库文件可直接下载，严重数据泄露风险 |
| **P1** | 问题 4: 前端 SPA 路径遍历 + 问题 15: 模板 ID 路径穿越 | 高/中 | 文件系统路径安全问题集中修复 |
| **P1** | 问题 7: LLM 调用无超时 + 问题 8: Token 管理缺失 | 中 | 直接影响系统可用性 |
| **P2** | 问题 10: 文件上传无大小限制 + 问题 6: SSE Session 管理 | 中 | 影响系统稳定性 |

---

*报告生成时间: 2026-02-17*
