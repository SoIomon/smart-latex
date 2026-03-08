"""Review agent — post-generation quality review and revision.

After all chapters are generated and assembled, this agent reviews the full
document for cross-chapter issues: content duplication, terminology
inconsistency, broken cross-references, and formatting problems.
"""

from __future__ import annotations

import json
import logging
from collections.abc import AsyncGenerator
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

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

MAX_REVIEW_TURNS = 15

_PROMPT_PATH = Path(__file__).parent / "prompts" / "review_agent_system.j2"


def _load_system_prompt() -> str:
    return _PROMPT_PATH.read_text(encoding="utf-8")


# ---------------------------------------------------------------------------
# Review agent state
# ---------------------------------------------------------------------------

@dataclass
class ReviewState:
    doc: DocumentState
    complete: bool = False
    summary: str = ""


def _report_review_complete(state: ReviewState, summary: str) -> str:
    state.complete = True
    state.summary = summary
    return f"审查完成：{summary}"


# ---------------------------------------------------------------------------
# Tool definitions
# ---------------------------------------------------------------------------

REVIEW_TOOL_DEFINITIONS: list[dict] = [
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
            "description": "在文档中搜索文本（支持正则表达式），返回匹配行及上下文。最多 20 条结果。",
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
            "name": "report_review_complete",
            "description": (
                "审查完成后调用此工具，汇报审查结果摘要。"
                "如果没有发现问题也要调用此工具说明。"
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "summary": {
                        "type": "string",
                        "description": "审查结果摘要：修复了哪些问题，或说明文档质量良好",
                    },
                },
                "required": ["summary"],
            },
        },
    },
]


# ---------------------------------------------------------------------------
# Tool dispatcher
# ---------------------------------------------------------------------------

def _execute_review_tool(name: str, args: dict, state: ReviewState) -> str:
    if name == "get_document_outline":
        return get_document_outline(state.doc)
    elif name == "search_text":
        return search_text(state.doc, query=args.get("query", ""), context_lines=args.get("context_lines", 2))
    elif name == "read_lines":
        return read_lines(state.doc, start_line=args.get("start_line", 1), end_line=args.get("end_line", 1))
    elif name == "replace_lines":
        return replace_lines(state.doc, start_line=args.get("start_line", 1), end_line=args.get("end_line", 1), new_content=args.get("new_content", ""))
    elif name == "report_review_complete":
        return _report_review_complete(state, summary=args.get("summary", "审查完成"))
    else:
        return f"未知工具: {name}"


def _format_tool_call(name: str, args: dict) -> str:
    if name == "get_document_outline":
        return "get_document_outline()"
    elif name == "search_text":
        return f"search_text(query='{args.get('query', '')}')"
    elif name == "read_lines":
        return f"read_lines({args.get('start_line')}-{args.get('end_line')})"
    elif name == "replace_lines":
        return f"replace_lines({args.get('start_line')}-{args.get('end_line')})"
    elif name == "report_review_complete":
        return "report_review_complete()"
    return f"{name}({json.dumps(args, ensure_ascii=False)})"


# ---------------------------------------------------------------------------
# Agent loop
# ---------------------------------------------------------------------------

async def run_review_agent_loop(
    latex_content: str,
    max_turns: int = MAX_REVIEW_TURNS,
) -> AsyncGenerator[AgentEvent, None]:
    """Run the review agent loop, yielding AgentEvents."""
    state = ReviewState(doc=DocumentState.from_latex(latex_content))
    system_prompt = _load_system_prompt()

    messages: list[dict] = [
        {"role": "system", "content": system_prompt},
        {
            "role": "user",
            "content": (
                f"请审查这份 LaTeX 文档（共 {state.doc.total_lines} 行）。"
                f"重点检查跨章节的内容重复、术语一致性和交叉引用问题。"
            ),
        },
    ]

    yield AgentEvent(type="thinking", data="正在审查文档质量...")

    for turn in range(max_turns):
        try:
            response = await doubao_client.chat_with_tools(
                messages=messages,
                tools=REVIEW_TOOL_DEFINITIONS,
                temperature=0.2,
                max_tokens=16384,
            )
        except Exception as e:
            logger.exception("Review agent LLM call failed")
            yield AgentEvent(type="error", data=f"LLM 调用失败: {e}")
            return

        if not response.choices:
            yield AgentEvent(type="error", data="LLM 返回空响应")
            return

        choice = response.choices[0]
        assistant_msg = choice.message

        if choice.finish_reason == "length":
            logger.warning("Review agent turn %d: output truncated", turn)
            if state.doc.modified:
                yield AgentEvent(type="latex", data=state.doc.to_latex())
            yield AgentEvent(type="done", data="输出被截断")
            return

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

        # No tool calls → agent is done
        if not assistant_msg.tool_calls:
            if state.doc.modified:
                yield AgentEvent(type="latex", data=state.doc.to_latex())
            yield AgentEvent(type="done", data=state.summary or "审查完成")
            return

        # Process tool calls
        has_replaced = False
        for tc in assistant_msg.tool_calls:
            fn_name = tc.function.name
            try:
                fn_args = json.loads(tc.function.arguments) if tc.function.arguments else {}
            except json.JSONDecodeError:
                fn_args = {}

            call_summary = _format_tool_call(fn_name, fn_args)
            yield AgentEvent(type="tool_call", data=call_summary)

            # Only one replace_lines per turn
            if fn_name == "replace_lines" and has_replaced:
                result = "已跳过：每轮只能执行一次 replace_lines（替换会改变行号），请重新用 read_lines 确认新行号后再替换"
                messages.append({"role": "tool", "tool_call_id": tc.id, "content": result})
                continue

            try:
                result = _execute_review_tool(fn_name, fn_args, state)
            except Exception as e:
                logger.exception("Review tool execution failed: %s", fn_name)
                result = f"工具执行出错: {e}"

            if fn_name == "replace_lines":
                has_replaced = True

            yield AgentEvent(type="tool_result", data=fn_name)

            messages.append({
                "role": "tool",
                "tool_call_id": tc.id,
                "content": result,
            })

            # Check if review is complete
            if state.complete:
                if state.doc.modified:
                    yield AgentEvent(type="latex", data=state.doc.to_latex())
                yield AgentEvent(type="done", data=state.summary)
                return

    # Exhausted turns
    if state.doc.modified:
        yield AgentEvent(type="latex", data=state.doc.to_latex())
    yield AgentEvent(type="done", data="审查轮次用尽")


async def review_and_revise(
    latex_content: str,
    max_turns: int = MAX_REVIEW_TURNS,
) -> tuple[str | None, str]:
    """Run review agent and return (revised_content, summary).

    Returns (None, summary) if no changes were made.
    """
    revised = None
    summary = ""
    async for event in run_review_agent_loop(latex_content, max_turns=max_turns):
        if event.type == "latex":
            revised = event.data
        elif event.type == "done":
            summary = event.data
        elif event.type == "error":
            raise RuntimeError(event.data)
    return revised, summary
