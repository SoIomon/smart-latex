"""Compilation fix agent — tool-driven LaTeX error repair.

Instead of sending the full LaTeX source to the LLM, this agent uses tools
to inspect error locations and make targeted fixes.
"""

from __future__ import annotations

import json
import logging
from collections.abc import AsyncGenerator
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from app.core.compiler.error_parser import ParsedError
from app.core.llm.agent import AgentEvent
from app.core.llm.client import doubao_client
from app.core.llm.tools import (
    DocumentState,
    get_document_outline,
    read_lines,
    replace_lines,
    search_text,
)

logger = logging.getLogger(__name__)

MAX_FIX_TURNS = 10

_PROMPT_PATH = Path(__file__).parent / "prompts" / "fix_agent_system.j2"


def _load_system_prompt() -> str:
    """Load the fix agent system prompt (plain text, no Jinja rendering needed)."""
    return _PROMPT_PATH.read_text(encoding="utf-8")


# ---------------------------------------------------------------------------
# Fix-agent specific state
# ---------------------------------------------------------------------------

@dataclass
class FixAgentState:
    """State for the fix agent loop."""

    doc: DocumentState
    errors: list[ParsedError]
    unfixable: bool = False
    unfixable_reason: str = ""


# ---------------------------------------------------------------------------
# New tool implementations (fix-agent only)
# ---------------------------------------------------------------------------

def report_unfixable(state: FixAgentState, reason: str) -> str:
    """Mark the errors as unfixable (environment issues, not format errors)."""
    state.unfixable = True
    state.unfixable_reason = reason
    return f"已标记为不可修复: {reason}"


def get_error_context(
    state: FixAgentState,
    error_index: int,
    context_lines: int = 5,
) -> str:
    """Read source lines around a specific parsed error."""
    if error_index < 0 or error_index >= len(state.errors):
        return f"错误索引 {error_index} 超出范围（共 {len(state.errors)} 个错误）"

    err = state.errors[error_index]
    if err.line_number is None:
        return f"错误 #{error_index} 没有行号信息，请使用 search_text 搜索相关内容。"

    start = max(1, err.line_number - context_lines)
    end = min(state.doc.total_lines, err.line_number + context_lines)
    return read_lines(state.doc, start, end)


# ---------------------------------------------------------------------------
# Tool definitions (OpenAI function-calling schema)
# ---------------------------------------------------------------------------

FIX_TOOL_DEFINITIONS: list[dict] = [
    {
        "type": "function",
        "function": {
            "name": "get_document_outline",
            "description": (
                "返回文档的章节大纲（\\chapter, \\section, \\subsection 等），"
                "帮助你快速了解文档结构。"
            ),
            "parameters": {"type": "object", "properties": {}, "required": []},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "search_text",
            "description": "在文档中搜索文本（支持正则表达式），返回匹配行及上下文。",
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "搜索关键词或正则表达式"},
                    "context_lines": {
                        "type": "integer",
                        "description": "每条匹配前后显示的上下文行数，默认 2",
                        "default": 2,
                    },
                },
                "required": ["query"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "read_lines",
            "description": "读取文档指定行范围的内容（行号从 1 开始），单次最多 200 行。",
            "parameters": {
                "type": "object",
                "properties": {
                    "start_line": {"type": "integer", "description": "起始行号（1-based，含）"},
                    "end_line": {"type": "integer", "description": "结束行号（1-based，含）"},
                },
                "required": ["start_line", "end_line"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "replace_lines",
            "description": (
                "替换文档指定行范围的内容。行号从 1 开始。"
                "替换前请先用 read_lines 确认要替换的内容。"
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "start_line": {"type": "integer", "description": "起始行号（1-based，含）"},
                    "end_line": {"type": "integer", "description": "结束行号（1-based，含）"},
                    "new_content": {"type": "string", "description": "替换后的新内容（可以是多行文本）"},
                },
                "required": ["start_line", "end_line", "new_content"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "report_unfixable",
            "description": (
                "当错误是环境问题（字体缺失、包未安装等）而非格式错误时调用此工具，"
                "说明原因并终止修复流程。"
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "reason": {"type": "string", "description": "不可修复的原因说明"},
                },
                "required": ["reason"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_error_context",
            "description": (
                "根据错误索引（从错误列表中），快速读取该错误所在行附近的源码。"
                "比 read_lines 更方便——自动定位到错误行号。"
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "error_index": {
                        "type": "integer",
                        "description": "错误在错误列表中的索引（从 0 开始）",
                    },
                    "context_lines": {
                        "type": "integer",
                        "description": "错误行前后各显示多少行，默认 5",
                        "default": 5,
                    },
                },
                "required": ["error_index"],
            },
        },
    },
]


# ---------------------------------------------------------------------------
# Tool dispatcher
# ---------------------------------------------------------------------------

def _execute_fix_tool(name: str, args: dict, state: FixAgentState) -> str:
    """Execute a fix-agent tool by name."""
    if name == "get_document_outline":
        return get_document_outline(state.doc)
    elif name == "search_text":
        return search_text(
            state.doc,
            query=args.get("query", ""),
            context_lines=args.get("context_lines", 2),
        )
    elif name == "read_lines":
        return read_lines(
            state.doc,
            start_line=args.get("start_line", 1),
            end_line=args.get("end_line", 1),
        )
    elif name == "replace_lines":
        return replace_lines(
            state.doc,
            start_line=args.get("start_line", 1),
            end_line=args.get("end_line", 1),
            new_content=args.get("new_content", ""),
        )
    elif name == "report_unfixable":
        return report_unfixable(state, reason=args.get("reason", "未知原因"))
    elif name == "get_error_context":
        return get_error_context(
            state,
            error_index=args.get("error_index", 0),
            context_lines=args.get("context_lines", 5),
        )
    else:
        return f"未知工具: {name}"


# ---------------------------------------------------------------------------
# Format helpers
# ---------------------------------------------------------------------------

def _format_errors_for_prompt(errors: list[ParsedError]) -> str:
    """Format parsed errors into a readable list for the LLM."""
    parts: list[str] = []
    for i, err in enumerate(errors):
        loc = f"第 {err.line_number} 行" if err.line_number else "行号未知"
        parts.append(
            f"[错误 #{i}] ({err.error_type}) {loc}\n"
            f"  消息: {err.message}\n"
            f"  上下文: {err.context or '无'}"
        )
    return "\n\n".join(parts)


def _format_tool_call(name: str, args: dict) -> str:
    """Human-readable summary of a tool call."""
    if name == "get_document_outline":
        return "get_document_outline()"
    elif name == "search_text":
        return f"search_text(query='{args.get('query', '')}')"
    elif name == "read_lines":
        return f"read_lines({args.get('start_line')}-{args.get('end_line')})"
    elif name == "replace_lines":
        return f"replace_lines({args.get('start_line')}-{args.get('end_line')})"
    elif name == "report_unfixable":
        return f"report_unfixable(reason='{args.get('reason', '')[:50]}')"
    elif name == "get_error_context":
        return f"get_error_context(#{args.get('error_index')})"
    return f"{name}({json.dumps(args, ensure_ascii=False)})"


# ---------------------------------------------------------------------------
# Agent loop
# ---------------------------------------------------------------------------

async def run_fix_agent_loop(
    latex_content: str,
    parsed_errors: list[ParsedError],
) -> AsyncGenerator[AgentEvent, None]:
    """Run the fix agent loop, yielding AgentEvents for SSE streaming.

    Parameters
    ----------
    latex_content : str
        The current full LaTeX document content.
    parsed_errors : list[ParsedError]
        Structured errors parsed from the xelatex log.
    """
    state = FixAgentState(
        doc=DocumentState.from_latex(latex_content),
        errors=parsed_errors,
    )

    system_prompt = _load_system_prompt()
    error_summary = _format_errors_for_prompt(parsed_errors)

    messages: list[dict] = [
        {"role": "system", "content": system_prompt},
        {
            "role": "user",
            "content": (
                f"以下是 xelatex 编译产生的 {len(parsed_errors)} 个错误，"
                f"文档共 {state.doc.total_lines} 行。请分析并修复。\n\n"
                f"{error_summary}"
            ),
        },
    ]

    yield AgentEvent(type="thinking", data="正在分析编译错误...")

    for turn in range(MAX_FIX_TURNS):
        try:
            response = await doubao_client.chat_with_tools(
                messages=messages,
                tools=FIX_TOOL_DEFINITIONS,
                temperature=0.2,
                max_tokens=16384,
            )
        except Exception as e:
            logger.exception("Fix agent LLM call failed")
            yield AgentEvent(type="error", data=f"LLM 调用失败: {e}")
            return

        if not response.choices:
            yield AgentEvent(type="error", data="LLM 返回空响应")
            return

        choice = response.choices[0]
        assistant_msg = choice.message

        # Guard against truncated output
        if choice.finish_reason == "length":
            logger.warning("Fix agent turn %d: output truncated", turn)
            yield AgentEvent(type="error", data="模型输出被截断。")
            if state.doc.modified:
                yield AgentEvent(type="latex", data=state.doc.to_latex())
            yield AgentEvent(type="done", data="")
            return

        # Build assistant message dict for conversation history
        msg_dict: dict[str, Any] = {"role": "assistant", "content": assistant_msg.content or ""}
        if assistant_msg.tool_calls:
            msg_dict["tool_calls"] = [
                {
                    "id": tc.id,
                    "type": "function",
                    "function": {
                        "name": tc.function.name,
                        "arguments": tc.function.arguments,
                    },
                }
                for tc in assistant_msg.tool_calls
            ]
        messages.append(msg_dict)

        # --- No tool calls → agent is done ---
        if not assistant_msg.tool_calls:
            if state.doc.modified:
                yield AgentEvent(type="latex", data=state.doc.to_latex())
            yield AgentEvent(type="done", data="")
            return

        # --- Process tool calls ---
        for tc in assistant_msg.tool_calls:
            fn_name = tc.function.name
            try:
                fn_args = json.loads(tc.function.arguments) if tc.function.arguments else {}
            except json.JSONDecodeError:
                fn_args = {}

            call_summary = _format_tool_call(fn_name, fn_args)
            yield AgentEvent(type="tool_call", data=call_summary)

            # Execute
            try:
                result = _execute_fix_tool(fn_name, fn_args, state)
            except Exception as e:
                logger.exception("Fix tool execution failed: %s", fn_name)
                result = f"工具执行出错: {e}"

            yield AgentEvent(type="tool_result", data=fn_name)

            # Append tool result to conversation
            messages.append({
                "role": "tool",
                "tool_call_id": tc.id,
                "content": result,
            })

            # Check if agent declared unfixable
            if state.unfixable:
                yield AgentEvent(type="unfixable", data=state.unfixable_reason)
                return

    # Exhausted turns
    if state.doc.modified:
        yield AgentEvent(type="latex", data=state.doc.to_latex())
    yield AgentEvent(type="done", data="")
