# Smart-LaTeX 智能文档处理方案调研报告

> 调研日期：2026-02-17
> 调研范围：Claude Agent SDK、Multi-Agent 框架、RAG 长文档处理、改进路径推荐

---

## 目录

1. [当前架构分析](#1-当前架构分析)
2. [Anthropic Claude Agent SDK](#2-anthropic-claude-agent-sdk)
3. [主流 Multi-Agent 框架对比](#3-主流-multi-agent-框架对比)
4. [RAG + 长文档处理方案](#4-rag--长文档处理方案)
5. [推荐改进路径](#5-推荐改进路径)
6. [总结与建议](#6-总结与建议)

---

## 1. 当前架构分析

### 1.1 现有流程

```
上传文档 → 解析(PDF/DOCX/MD/TXT) → 拼接所有文档文本
    → LLM一次性内容整合(integrate_content) → 结构化JSON
    → LLM一次性LaTeX生成(generate_latex_stream) → 最终LaTeX
```

### 1.2 核心代码结构

| 文件 | 职责 |
|------|------|
| `backend/app/core/llm/client.py` | 豆包(doubao-pro-32k) OpenAI 兼容客户端 |
| `backend/app/core/llm/chains.py` | 两步 LLM 调用链：内容整合 + LaTeX 生成 |
| `backend/app/services/generation_service.py` | 编排服务：文档收集 → 整合 → 模板 → 流式生成 |
| `backend/app/core/parsers/` | 文档解析器：PDF、DOCX、Markdown、TXT |
| `backend/app/core/llm/prompts/` | Jinja2 提示词模板 |

### 1.3 存在的问题

1. **文档拼接暴力**：所有文档内容直接拼接，当文档超过 32K token 上下文窗口时，信息会被截断
2. **缺乏结构感知**：解析器提取的 `sections` 信息未被利用，所有文档被视为平面文本
3. **单次调用瓶颈**：整合和生成都是单次 LLM 调用，无法处理复杂/长文档
4. **无错误修正**：生成的 LaTeX 如果编译失败，没有自动修正机制
5. **无质量保证**：缺乏对生成内容的结构校验和质量检查

---

## 2. Anthropic Claude Agent SDK

### 2.1 概述

- **最新版本**：v0.1.36（2026-02-13 发布）
- **语言支持**：Python 3.10+、TypeScript
- **核心定位**：将 Claude Code 的 Agent 能力封装为 SDK，支持工具调用、流式输出、会话管理

### 2.2 架构特点

```
Your Python App
    ↓
Claude Agent SDK (Python)
    ↓ (spawn subprocess)
Claude Code CLI
    ↓ (API call)
Anthropic Claude API
```

SDK 内部通过 **MCP (Model Context Protocol)** 和 **SDK Control Protocol** 进行通信。核心接口：

- **`query()`**：无状态单次查询，每次调用独立
- **`ClaudeSDKClient`**：有状态会话客户端，支持多轮对话
- **Custom Tools**：Python 函数作为工具，通过进程内 MCP Server 实现
- **Hooks**：在 Agent 循环的特定节点插入确定性处理逻辑

### 2.3 关键功能

| 功能 | 说明 |
|------|------|
| Extended Thinking | 支持 ThinkingConfig，可控制思考深度（low/medium/high/max） |
| Structured Output | Agent 可返回符合 schema 的 JSON |
| MCP Tool Annotations | 工具元数据标注（只读、破坏性、幂等等） |
| 流式输出 | 异步迭代器逐步返回消息 |

### 2.4 与豆包 API 的兼容性评估

**结论：不兼容，不推荐直接使用。**

- Claude Agent SDK **强绑定 Claude API**，内部通过 Claude Code CLI 调用 Anthropic API
- 不支持自定义 LLM Provider，GitHub 上有用户提出此需求（Issue #410），但尚无官方解决方案
- 如需使用，必须额外购买 Anthropic API 额度，与当前豆包 API 方案并行
- SDK 的核心价值在于 Claude Code 的 Agent Loop（工具调用、自我修正），但这依赖 Claude 模型能力

### 2.5 适用场景

- 如果项目未来考虑迁移到 Claude API，可以用 Agent SDK 构建强大的文档处理 pipeline
- 对于当前基于豆包的项目，**不适合**作为核心框架

---

## 3. 主流 Multi-Agent 框架对比

### 3.1 框架概览

| 框架 | 架构模式 | 自定义 LLM | 学习曲线 | 适合场景 |
|------|---------|-----------|---------|---------|
| **LangGraph** | 图工作流 | 优秀 (LangChain 生态) | 中等 | 复杂多步骤流程 |
| **CrewAI** | 角色协作 | 优秀 (LiteLLM) | 低 | 角色分工明确的任务 |
| **AutoGen** | 对话式 | 优秀 | 中等 | 多Agent对话协作 |
| **OpenAI Agents SDK** | Provider-agnostic | 优秀 | 低 | 轻量级Agent |
| **Dify** | 低代码工作流 | 优秀 (插件) | 极低 | 快速原型/可视化 |

### 3.2 详细分析

#### 3.2.1 LangGraph

**优点：**
- 图(Graph)模型天然适合多步骤文档处理 pipeline
- 状态管理强大，每个节点可以读写共享 state
- 与 FastAPI 集成方案成熟，有生产级模板
- 支持条件分支、循环、并行执行
- 通过 LangChain 的 `ChatOpenAI` 配置自定义 base_url 即可对接豆包

**缺点：**
- 依赖 LangChain 生态，引入较多抽象层
- 调试复杂图工作流有一定门槛
- 对于简单场景可能过度工程化

**与豆包兼容性：** 完全兼容。通过 `ChatOpenAI(base_url="https://ark.cn-beijing.volces.com/api/v3", api_key=..., model="doubao-pro-32k")` 即可接入。

**文档处理 Pipeline 示例：**
```python
from langgraph.graph import StateGraph, END

# 定义状态
class DocState(TypedDict):
    documents: list[dict]
    analyzed_structure: dict
    sections_latex: list[str]
    final_latex: str

# 定义图
graph = StateGraph(DocState)
graph.add_node("analyze", analyze_document_structure)
graph.add_node("chunk", split_into_sections)
graph.add_node("generate", generate_section_latex)
graph.add_node("merge", merge_latex_sections)
graph.add_node("validate", validate_latex)
graph.add_node("fix", fix_latex_errors)

# 定义边
graph.add_edge("analyze", "chunk")
graph.add_edge("chunk", "generate")
graph.add_edge("generate", "merge")
graph.add_edge("merge", "validate")
graph.add_conditional_edges("validate", check_valid, {True: END, False: "fix"})
graph.add_edge("fix", "validate")
```

#### 3.2.2 CrewAI

**优点：**
- 角色化设计直观（分析员、LaTeX生成员、校验员）
- 通过 LiteLLM 支持几乎所有 LLM Provider
- 学习曲线低，快速上手
- 支持层级化流程管理（manager自动协调）

**缺点：**
- 对工作流的细粒度控制不如 LangGraph
- 内部默认会请求 OpenAI API（需明确配置才能避免）
- 社区报告在复杂场景下稳定性不如 LangGraph

**与豆包兼容性：** 兼容。通过设置 `LLM(model="openai/doubao-pro-32k", base_url=..., api_key=...)` 对接。

**文档处理角色设计：**
```python
from crewai import Agent, Task, Crew

analyst = Agent(
    role="文档结构分析师",
    goal="分析文档结构，提取章节、标题、关键信息",
    llm=custom_doubao_llm,
)

latex_writer = Agent(
    role="LaTeX排版专家",
    goal="根据结构化内容生成高质量LaTeX代码",
    llm=custom_doubao_llm,
)

reviewer = Agent(
    role="LaTeX质量审核员",
    goal="检查LaTeX代码的正确性和可编译性",
    llm=custom_doubao_llm,
)
```

#### 3.2.3 AutoGen (Microsoft)

**优点：**
- 多Agent对话协作模式灵活
- 支持代码执行和自我修正
- 适合需要"讨论-改进"循环的场景

**缺点：**
- 对话式架构对文档处理 pipeline 不太直观
- 设置复杂度较高
- 在结构化输出控制方面不如 LangGraph

**与豆包兼容性：** 兼容。支持 OpenAI 兼容 API。

#### 3.2.4 OpenAI Agents SDK

**优点：**
- 轻量级，API 简洁
- Provider-agnostic，原生支持自定义 model provider
- 支持 per-agent 指定不同 LLM
- 通过 LiteLLM 可接入 100+ 模型

**缺点：**
- 默认使用 Responses API，多数第三方 Provider 不支持（需切换到 Chat Completions）
- 工作流编排能力不如 LangGraph
- 生态不如 LangChain 丰富

**与豆包兼容性：** 兼容。需调用 `set_default_openai_api("chat_completions")` 后使用 `OpenAIChatCompletionsModel`。

#### 3.2.5 Dify

**优点：**
- 可视化工作流编辑器，非技术人员也能配置
- 内置 RAG pipeline
- 支持自托管部署
- 插件生态丰富
- 支持多种 LLM Provider

**缺点：**
- 作为独立平台运行，与现有 FastAPI 后端集成需要额外工作
- 对 LaTeX 生成这种特定任务缺乏原生支持
- 引入 Docker/K8s 部署复杂度
- 定制灵活性不如代码方案

### 3.3 框架选型建议

**首选推荐：LangGraph**

理由：
1. 图工作流模型最匹配文档处理 pipeline 的多步骤特性
2. 与 FastAPI 集成方案成熟，有生产级模板
3. 状态管理能力强，适合跟踪文档处理进度
4. 条件分支支持 LaTeX 编译校验 → 修正循环
5. 通过 LangChain 生态可轻松对接豆包 API

**备选推荐：CrewAI**

理由：
1. 学习曲线低，适合快速原型验证
2. 角色化设计对文档处理任务直观
3. 如果 LangGraph 过于重量级，CrewAI 是好的平衡点

---

## 4. RAG + 长文档处理方案

### 4.1 问题分析

当前使用 `doubao-pro-32k` 模型，上下文窗口为 32K token。对于中文文档：
- 约 16,000-20,000 个汉字
- 一篇 20 页的学术论文约 8,000-12,000 汉字，单篇可以处理
- 但多篇文档拼接后很容易超限
- 超限后信息截断，导致内容丢失

### 4.2 分段处理策略

#### 4.2.1 结构感知分段（推荐）

利用已有的 `ParsedContent.sections` 字段，按文档的自然结构分段：

```python
# 当前已有但未利用的结构
@dataclass
class ParsedContent:
    text: str = ""
    metadata: dict = field(default_factory=dict)
    sections: list[dict] = field(default_factory=list)  # <-- 未被使用！
```

**改进方案：**
1. 增强解析器，让 `sections` 包含完整的层级结构信息
2. 按 section 粒度调用 LLM，每个 section 独立生成 LaTeX
3. 最后合并各 section 的 LaTeX 输出

#### 4.2.2 语义分段（Semantic Chunking）

对于缺乏明确结构的文档（如纯文本），使用语义相似度进行分段：

1. 将文档分句
2. 计算相邻句子的语义相似度（使用 embedding 模型）
3. 在相似度突变点切分
4. 确保每个 chunk 在 token 限制内

#### 4.2.3 滑动窗口分段

最简单的策略，适合作为保底方案：

1. 按固定 token 数切分（如每段 8K token）
2. 相邻段有 20% 重叠，避免边界信息丢失
3. 每段独立处理后合并

### 4.3 适合 LaTeX 生成的 RAG 方案

对于 Smart-LaTeX 项目，**完整的 RAG（向量检索 + 生成）并非最优方案**，原因：

1. LaTeX 生成需要文档的**完整内容**，而非检索片段
2. 排版需要理解文档的**全局结构**，片段检索会破坏上下文
3. 增加向量数据库依赖，复杂度过高

**更适合的方案：分段处理 Pipeline（非检索式 RAG）**

```
文档 → 解析 → 结构分析 → 按章节分段
    → 每段独立生成LaTeX → 全局一致性校验 → 合并
```

### 4.4 混合方案：MapReduce 式处理

```
Step 1 (Map): 每个文档/章节独立 → LLM提取结构化信息
Step 2 (Reduce): 合并所有结构化信息 → LLM统一规划全文结构
Step 3 (Map): 按规划的结构分章节 → LLM逐章生成LaTeX
Step 4 (Reduce): 合并所有章节LaTeX → 统一格式/编号/引用
Step 5 (Validate): 编译验证 → 如失败则LLM修正
```

这种方式：
- 每次 LLM 调用的 token 数可控
- 保留了全局结构规划
- 支持长文档处理
- 可以并行处理各章节

---

## 5. 推荐改进路径

### 5.1 短期改进（1-2 周）——无需引入新框架

**目标：在现有架构上优化，解决最紧迫的长文档问题**

#### 改进 1：利用文档结构信息

```python
# generation_service.py 改进
async def generate_latex_from_documents(...):
    # 现在：直接拼接 doc.parsed_content
    # 改进：按章节组织，传递结构化信息
    documents = []
    for doc_id in document_ids:
        doc = await get_document(db, doc_id)
        if doc:
            documents.append({
                "filename": doc.original_name,
                "content": doc.parsed_content,
                "sections": doc.parsed_sections,  # 利用结构信息
            })
```

#### 改进 2：实现分段整合

```python
# chains.py 新增
async def integrate_content_chunked(documents: list[dict], template_id: str) -> dict:
    """分段整合：先单独处理每个文档，再合并"""
    # Step 1: 每个文档独立提取结构
    doc_structures = []
    for doc in documents:
        structure = await integrate_single_document(doc, template_id)
        doc_structures.append(structure)

    # Step 2: 合并所有文档结构
    if len(doc_structures) == 1:
        return doc_structures[0]
    else:
        return await merge_document_structures(doc_structures, template_id)
```

#### 改进 3：添加 LaTeX 编译验证

```python
async def validate_and_fix_latex(latex: str, max_retries: int = 2) -> str:
    """编译 LaTeX 并在失败时让 LLM 修正"""
    for attempt in range(max_retries):
        success, errors = compile_latex(latex)
        if success:
            return latex
        latex = await fix_latex_errors(latex, errors)
    return latex  # 返回最后一次尝试的结果
```

**预期效果：**
- 支持更长的文档输入
- 生成质量提升（结构化信息更完整）
- LaTeX 编译成功率提高

### 5.2 中期改进（1-2 月）——引入 LangGraph 工作流

**目标：构建结构化的文档处理 pipeline，支持复杂场景**

#### 架构设计

```
                    ┌─────────────┐
                    │  FastAPI     │
                    │  Endpoint    │
                    └──────┬──────┘
                           │
                    ┌──────▼──────┐
                    │  LangGraph  │
                    │  Workflow   │
                    └──────┬──────┘
                           │
          ┌────────────────┼────────────────┐
          │                │                │
   ┌──────▼──────┐ ┌──────▼──────┐ ┌──────▼──────┐
   │  Doc Analyze │ │  Content    │ │  LaTeX      │
   │  Node       │ │  Extract    │ │  Generate   │
   │             │ │  Node       │ │  Node       │
   └─────────────┘ └─────────────┘ └──────┬──────┘
                                          │
                                   ┌──────▼──────┐
                                   │  Compile &  │
                                   │  Validate   │
                                   │  Node       │
                                   └──────┬──────┘
                                          │
                                   ┌──────▼──────┐
                                   │  Fix Errors │
                                   │  Node       │
                                   └─────────────┘
```

#### 核心实现

```python
from langgraph.graph import StateGraph, END
from langchain_openai import ChatOpenAI

# 豆包 LLM 配置
doubao_llm = ChatOpenAI(
    model="doubao-pro-32k",
    base_url="https://ark.cn-beijing.volces.com/api/v3",
    api_key=settings.DOUBAO_API_KEY,
    temperature=0.3,
)

class LatexPipelineState(TypedDict):
    documents: list[dict]
    document_structures: list[dict]
    global_outline: dict
    section_latex: dict[str, str]
    full_latex: str
    compile_result: dict
    iteration: int

def build_latex_pipeline():
    graph = StateGraph(LatexPipelineState)

    graph.add_node("analyze_docs", analyze_documents)
    graph.add_node("plan_outline", plan_global_outline)
    graph.add_node("generate_sections", generate_sections_parallel)
    graph.add_node("merge_latex", merge_all_sections)
    graph.add_node("compile_check", compile_and_validate)
    graph.add_node("fix_errors", fix_compilation_errors)

    graph.set_entry_point("analyze_docs")
    graph.add_edge("analyze_docs", "plan_outline")
    graph.add_edge("plan_outline", "generate_sections")
    graph.add_edge("generate_sections", "merge_latex")
    graph.add_edge("merge_latex", "compile_check")
    graph.add_conditional_edges(
        "compile_check",
        should_fix_or_finish,
        {"fix": "fix_errors", "done": END},
    )
    graph.add_edge("fix_errors", "compile_check")

    return graph.compile()
```

#### 与现有代码的集成

```python
# generation_service.py 重构
from app.core.pipeline import build_latex_pipeline

pipeline = build_latex_pipeline()

async def generate_latex_from_documents(db, project_id, template_id, document_ids):
    documents = await collect_documents(db, project_id, document_ids)
    template_content = get_template_content(template_id)

    result = await pipeline.ainvoke({
        "documents": documents,
        "template_content": template_content,
        "iteration": 0,
    })

    return result["full_latex"]
```

**新增依赖：**
```
langgraph>=0.2.0
langchain-openai>=0.2.0
langchain-core>=0.3.0
```

**预期效果：**
- 完整的文档处理 pipeline，每步可独立调试
- 支持编译校验 → 自动修正循环
- 长文档分段处理成为标准流程
- 流程可视化和监控

### 5.3 长期改进（3-6 月）——全面 Agent 化

**目标：智能化文档处理，自适应不同文档类型和排版需求**

#### 方向 1：智能文档理解 Agent

- 引入多模态能力：图片识别、表格解析、公式 OCR
- Agent 自主决定文档处理策略（而非固定 pipeline）
- 根据文档类型自动选择最佳模板

#### 方向 2：交互式排版 Agent

- 用户通过自然语言指导排版（"把图表放在第三章"、"参考文献用 APA 格式"）
- Agent 理解排版意图，自主修改 LaTeX
- 支持多轮对话迭代优化

#### 方向 3：LaTeX 知识库

- 构建 LaTeX 命令、宏包、模板的向量知识库
- Agent 在生成时检索最佳实践
- 持续学习用户的排版偏好

#### 方向 4：多模型协作

- 不同任务使用最合适的模型：
  - 结构分析：doubao-pro-32k（快速、低成本）
  - LaTeX 生成：更强的模型（如 doubao-pro-128k 或其他）
  - 格式校验：轻量级模型或规则引擎

---

## 6. 总结与建议

### 6.1 核心结论

| 方案 | 与当前项目兼容性 | 实现复杂度 | 收益 | 推荐度 |
|------|-----------------|-----------|------|--------|
| Claude Agent SDK | 不兼容（需 Claude API） | 中 | 高（如用 Claude） | 不推荐 |
| LangGraph | 完全兼容 | 中 | 高 | **强烈推荐** |
| CrewAI | 完全兼容 | 低 | 中 | 推荐（备选） |
| AutoGen | 兼容 | 中高 | 中 | 一般 |
| OpenAI Agents SDK | 兼容 | 低 | 中低 | 一般 |
| Dify | 需独立部署 | 低（使用） | 中 | 特定场景推荐 |
| 纯代码分段优化 | 完全兼容 | 低 | 中 | **短期首选** |

### 6.2 推荐行动计划

```
Phase 1（立即）: 短期代码优化
├── 利用 sections 结构信息
├── 实现分段整合（MapReduce 式）
├── 添加 LaTeX 编译校验
└── 预期：1-2 周

Phase 2（中期）: 引入 LangGraph
├── 构建完整 Pipeline Graph
├── 状态管理和错误修正循环
├── 与 FastAPI 集成
└── 预期：1-2 月

Phase 3（长期）: Agent 化演进
├── 智能文档理解
├── 交互式排版 Agent
├── 多模型协作
└── 预期：3-6 月
```

### 6.3 关键建议

1. **不建议使用 Claude Agent SDK**：当前项目绑定豆包 API，Claude Agent SDK 无法对接非 Claude 模型
2. **短期立即可做**：改进 `chains.py` 中的 `integrate_content` 函数，实现分段处理，无需引入任何新依赖
3. **中期首选 LangGraph**：与 FastAPI 后端无缝集成，通过 LangChain 生态对接豆包 API，图工作流模型最匹配文档处理场景
4. **不建议引入完整 RAG**：Smart-LaTeX 的核心需求是"全文排版"而非"片段检索"，MapReduce 式分段处理更适合
5. **保持架构简洁**：短期优化足以解决当前最紧迫的长文档问题，不要过早引入重量级框架

---

## 参考资料

- [Claude Agent SDK Python - GitHub](https://github.com/anthropics/claude-agent-sdk-python)
- [Building agents with the Claude Agent SDK - Anthropic](https://www.anthropic.com/engineering/building-agents-with-the-claude-agent-sdk)
- [Agent SDK overview - Claude API Docs](https://platform.claude.com/docs/en/agent-sdk/overview)
- [Claude Agent SDK 非 Anthropic 模型兼容性讨论 - GitHub Issue #410](https://github.com/anthropics/claude-agent-sdk-python/issues/410)
- [LangGraph - Agent Orchestration Framework](https://www.langchain.com/langgraph)
- [LangGraph + FastAPI 集成指南](https://pub.towardsai.net/building-ai-workflows-with-fastapi-and-langgraph-step-by-step-guide-599937ab84f3)
- [CrewAI LLM 配置文档](https://docs.crewai.com/en/concepts/llms)
- [Multi-Agent 框架对比（2026）](https://o-mega.ai/articles/langgraph-vs-crewai-vs-autogen-top-10-agent-frameworks-2026)
- [OpenAI Agents SDK - Models](https://openai.github.io/openai-agents-python/models/)
- [Dify - Agentic Workflow Builder](https://dify.ai/)
- [Document Chunking for RAG - 9 Strategies](https://langcopilot.com/posts/2025-10-11-document-chunking-for-rag-practical-guide)
- [RAG-Anything - GitHub](https://github.com/HKUDS/RAG-Anything)
- [Chunking Strategies for RAG - Pinecone](https://www.pinecone.io/learn/chunking-strategies/)
- [FastAPI + LangGraph Agent Template - GitHub](https://github.com/wassim249/fastapi-langgraph-agent-production-ready-template)
