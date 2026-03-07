# 生成管线重构：Pipeline + Review

## 背景

客户反馈 smart-latex "几乎用不了"。经代码审计发现生成管线存在 5 个质量瓶颈：

1. 大纲规划对模板一无所知（只收到 `template_id` 字符串）
2. 章节之间完全孤立（互不知道对方内容，导致重复和不一致）
3. analysis 和原文双重传递（章节 prompt 同时包含分析摘要和原文，冗余）
4. template_rules 是原始 preamble 噪音（几百行 LaTeX 配置直接塞给 LLM）
5. pipeline 单程无反馈（无审查环节）

## 改动总览

| Task | 描述 | 涉及文件 |
|------|------|---------|
| A | 合并两套 pipeline 函数 | generation_service.py, generation.py |
| B | 结构化 template_rules | generation_service.py |
| C | 让大纲规划理解模板结构 | generation_service.py, chains.py, outline_planning.j2 |
| D | 精简章节生成输入 | generation_service.py, chapter_generation.j2 |
| E | 给每章注入全局上下文 | generation_service.py, chains.py, chapter_generation.j2 |
| F | 新增 Stage 4 — Review Agent | review_agent.py, review_agent_system.j2, generation_service.py |

## 各 Task 详细说明

### Task A: 合并两套 pipeline 函数

**问题**: `generate_latex_pipeline()`（有 SSE/DB）和 `generate_latex_pipeline_internal()`（无 DB）逻辑高度重复，每次改动需同步两处。

**方案**: 将 `generate_latex_pipeline()` 改为不依赖 DB 的纯函数，DB 操作留在 API 层。

- `generate_latex_pipeline(documents, template_id, project_images_dir)` — 接收文档列表，不再接收 db/project_id
- 删除 `generate_latex_pipeline_internal()`
- `_pipeline_generate()` 直接调用 `generate_latex_pipeline()`
- API 层 (`generation.py`) 先调用 `_gather_documents()` 获取文档，再传给 pipeline

### Task B: 结构化 template_rules

**问题**: `_get_template_rules()` 把整个 preamble（几百行 LaTeX 配置）塞给 LLM，信噪比极低。

**方案**: 用 `_get_structured_template_rules()` 替换，从 preamble 中提取关键格式信息：

```
模板：通信所最终报告模板（上海微小卫星工程中心通信所最终报告专用LaTeX模板...）
文档类型：ctexrep，选项：12pt, a4paper, openany, fontset=none
已加载宏包：geometry, setspace, titlesec, titletoc, caption, ...
页面版式：top=2.5cm, bottom=2.5cm, left=2.8cm, right=2.8cm
行距：1.5 倍
字体：中文使用 ctex 预定义命令（\songti、\heiti 等），不要自定义字体
章节层级：\chapter{} → \section{} → \subsection{} → \subsubsection{}
```

### Task C: 让大纲规划理解模板结构

**问题**: `outline_planning.j2` 只收到 `template_id` 字符串，不知道文档类型、层级、固定内容。

**方案**: 新增 `_get_template_structure_info(template_id)` 函数，返回：

- `name`, `description` — 模板基本信息
- `doc_class_type` — 文档类型（article/report/book）
- `section_commands` — 章节命令层级
- `fixed_sections` — 模板已包含的固定内容（封面、目录、声明等）
- `suggested_chapter_range` — 建议章节数范围

Outline prompt 中新增模板结构 section，明确告知 LLM"以上固定内容由模板自动生成，你只需规划正文章节"。

### Task D: 精简章节生成输入

**问题**: `chapter_generation.j2` 同时传 analysis 摘要和原文，analysis 是 Stage 1 中间产物，对 Stage 3 是噪音。

**方案**:

- 从章节 prompt 中移除 `doc.analysis` 相关内容（abstract、sections 循环）
- `chapter_sources` 构建时不再包含 `analysis` 字段
- 原文截取上限从 15000 提升到 20000 字符（利用省下的 token 空间）

### Task E: 给每章注入全局上下文

**问题**: 每章独立生成，互不知道对方内容，导致重复和不一致。

**方案**:

- 新增 `_build_outline_summary(chapters)` — 构建全文大纲文本
- 新增 `_mark_current_chapter(summary, index)` — 用 `>>>` 标记当前章节
- 章节 prompt 中新增"全文大纲概览"section + 协调指令：
  - 不重复其他章节已覆盖的内容
  - 保持全文术语一致
  - 只引用本章内定义的 label

### Task F: 新增 Stage 4 — Review Agent

**问题**: Pipeline 单程无反馈，内容重复、术语不一致、章节衔接差等问题无人审查。

**方案**: 所有章节拼接后，用 tool-calling agent 做一次 quality review。

**新增文件**:
- `backend/app/core/llm/review_agent.py` — Review Agent 实现
- `backend/app/core/llm/prompts/review_agent_system.j2` — 审查 system prompt

**架构**:
- 复用 `DocumentState`、`get_document_outline`、`search_text`、`read_lines`、`replace_lines` 工具
- 新增 `report_review_complete(summary)` 工具表示审查完成
- `ReviewState` dataclass 管理状态（避免全局变量并发问题）
- 最多 30 轮 tool-calling，每轮只允许一次 `replace_lines`

**审查项**（按优先级）:
1. 内容重复（最常见）
2. 术语一致性
3. 章节衔接
4. 交叉引用
5. 格式一致性
6. label 命名

**容错**: Review agent 异常时自动回退到未审查版本，不阻塞输出。

**SSE 兼容**: 前端已有的 `stage` 事件处理逻辑自然显示"阶段 4/4：审查与修订..."，无需前端改动。

## 新的 Pipeline 流程

```
Stage 1/4: 分析文档（并行，batch=10）
    ↓
Stage 2/4: 规划大纲（注入模板结构信息）
    ↓
Stage 3/4: 生成章节（并行，batch=8，注入全文大纲上下文）
    → 每章验证 + fix agent 自动修复
    ↓
Stage 4/4: Review Agent 审查修订（tool-calling，最多 30 轮）
    → 失败时回退到未审查版本
    ↓
输出最终 LaTeX
```

## 文件变更清单

| 文件 | 改动类型 | 说明 |
|------|---------|------|
| `backend/app/services/generation_service.py` | 重构 | 核心管线，新增 5 个函数，删除 2 个旧函数 |
| `backend/app/core/llm/chains.py` | 扩展 | `plan_outline` + `generate_chapter` 新增参数 |
| `backend/app/core/llm/prompts/outline_planning.j2` | 重写 | 新增模板结构 section |
| `backend/app/core/llm/prompts/chapter_generation.j2` | 重构 | 移除 analysis，新增全文大纲概览 |
| `backend/app/core/llm/review_agent.py` | **新增** | Review Agent 实现 |
| `backend/app/core/llm/prompts/review_agent_system.j2` | **新增** | Review Agent system prompt |
| `backend/app/api/v1/generation.py` | 调整 | 适配新的 pipeline 调用方式 |
| `backend/tests/test_template_pipeline.py` | 更新 | 适配函数重命名和参数变更 |

## 新增/删除的函数

**新增**:
- `_get_structured_template_rules(template_id)` — 结构化模板规则
- `_get_template_structure_info(template_id)` — 模板结构信息（给大纲规划用）
- `_build_outline_summary(chapters)` — 全文大纲摘要
- `_mark_current_chapter(summary, index)` — 标记当前章节
- `review_and_revise(latex_content)` — Review Agent 入口

**删除**:
- `_get_template_rules()` — 被 `_get_structured_template_rules()` 替代
- `generate_latex_pipeline_internal()` — 被合并进 `generate_latex_pipeline()`
