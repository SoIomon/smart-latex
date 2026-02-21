"""Chat agent loop for LaTeX document editing.

Instead of dumping the full LaTeX into the prompt, the agent uses tools
to inspect and modify the document on demand, keeping context usage low.
"""

from __future__ import annotations

import json
import logging
from collections.abc import AsyncGenerator
from dataclasses import dataclass
from typing import Any

from app.core.llm.client import doubao_client
from app.core.llm.tools import TOOL_DEFINITIONS, DocumentState, execute_tool

logger = logging.getLogger(__name__)

MAX_AGENT_TURNS = 15
MAX_HISTORY_ROUNDS = 6  # keep last N user/assistant pairs
CHUNK_SIZE = 50  # characters per simulated stream chunk

SYSTEM_PROMPT = """\
你是一个专业的 LaTeX 文档编辑助手。你可以通过工具来查看和修改用户的 LaTeX 文档。

## 工作流程
1. 先调用 get_document_outline() 了解文档结构
2. 用 search_text() 搜索相关内容的位置
3. 用 read_lines() 阅读需要修改的具体内容
4. 用 replace_lines() 精确替换需要修改的行
5. 最后用自然语言回复用户，说明你做了什么修改

## 重要规则
- 修改前一定要先用 read_lines 确认内容，不要凭记忆替换
- 保持 LaTeX 语法正确，确保文档可以用 xelatex 编译
- 保持中文支持（ctex 包）
- 每次只修改必要的部分，不要重写整个文档
- 如果用户的请求不涉及修改文档（比如提问），直接用文字回复即可
- 回复要简洁，说明做了什么修改以及修改的理由
- 每次只调用一个 replace_lines，因为替换会改变行号。如果需要多处修改，每次替换后重新用 search_text 或 read_lines 确认新的行号再做下一次替换
"""


@dataclass
class AgentEvent:
    """Event yielded by the agent loop for SSE streaming."""

    type: str  # thinking | tool_call | tool_result | content | latex | done | error
    data: str


def _truncate_history(history: list[dict]) -> list[dict]:
    """Keep only the most recent MAX_HISTORY_ROUNDS user/assistant pairs."""
    # Filter to user and assistant messages only
    pairs: list[dict] = [m for m in history if m["role"] in ("user", "assistant")]
    if len(pairs) <= MAX_HISTORY_ROUNDS * 2:
        return pairs
    return pairs[-(MAX_HISTORY_ROUNDS * 2) :]


def _build_initial_messages(
    history: list[dict],
    user_message: str,
    total_lines: int,
) -> list[dict]:
    """Build the initial message list for the agent."""
    messages: list[dict] = [{"role": "system", "content": SYSTEM_PROMPT}]

    # Add truncated history (excluding the current user message which is last)
    truncated = _truncate_history(history)
    messages.extend(truncated)

    # Current user message with document metadata
    messages.append({
        "role": "user",
        "content": f"{user_message}\n\n[当前文档共 {total_lines} 行]",
    })
    return messages


def _format_tool_call(name: str, args: dict) -> str:
    """Human-readable summary of a tool call."""
    if name == "get_document_outline":
        return "get_document_outline()"
    elif name == "search_text":
        q = args.get("query", "")
        return f"search_text(query='{q}')"
    elif name == "read_lines":
        return f"read_lines({args.get('start_line')}-{args.get('end_line')})"
    elif name == "replace_lines":
        return f"replace_lines({args.get('start_line')}-{args.get('end_line')})"
    return f"{name}({json.dumps(args, ensure_ascii=False)})"


async def run_agent_loop(
    latex_content: str,
    history: list[dict],
    user_message: str,
) -> AsyncGenerator[AgentEvent, None]:
    """Run the agent loop, yielding AgentEvents for SSE streaming.

    Parameters
    ----------
    latex_content : str
        The current full LaTeX document content.
    history : list[dict]
        Previous chat messages (role/content dicts), *excluding* the
        current user message.
    user_message : str
        The new user instruction.
    """
    doc_state = DocumentState.from_latex(latex_content)
    messages = _build_initial_messages(history, user_message, doc_state.total_lines)

    yield AgentEvent(type="thinking", data="正在分析你的请求...")

    for turn in range(MAX_AGENT_TURNS):
        try:
            response = await doubao_client.chat_with_tools(
                messages=messages,
                tools=TOOL_DEFINITIONS,
                temperature=0.5,
                max_tokens=16384,
            )
        except Exception as e:
            logger.exception("Agent LLM call failed")
            yield AgentEvent(type="error", data=f"LLM 调用失败: {e}")
            return

        if not response.choices:
            yield AgentEvent(type="error", data="LLM 返回空响应")
            return

        choice = response.choices[0]
        assistant_msg = choice.message

        # Guard against truncated output — tool_calls may be incomplete
        if choice.finish_reason == "length":
            logger.warning("Agent turn %d: output truncated (finish_reason=length)", turn)
            yield AgentEvent(type="error", data="模型输出被截断，请尝试更简单的指令。")
            if doc_state.modified:
                yield AgentEvent(type="latex", data=doc_state.to_latex())
            yield AgentEvent(type="done", data="")
            return

        # Build the assistant message dict for conversation history
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

        # --- No tool calls → final text response ---
        if not assistant_msg.tool_calls:
            final_text = assistant_msg.content or ""

            # Yield content in small chunks for streaming effect
            for i in range(0, len(final_text), CHUNK_SIZE):
                yield AgentEvent(type="content", data=final_text[i : i + CHUNK_SIZE])

            # If document was modified, yield the updated latex
            if doc_state.modified:
                yield AgentEvent(type="latex", data=doc_state.to_latex())

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
                result = execute_tool(fn_name, fn_args, doc_state)
            except Exception as e:
                logger.exception("Tool execution failed: %s", fn_name)
                result = f"工具执行出错: {e}"

            yield AgentEvent(type="tool_result", data=fn_name)

            # Append tool result to conversation
            messages.append({
                "role": "tool",
                "tool_call_id": tc.id,
                "content": result,
            })

    # Exhausted turns
    yield AgentEvent(type="content", data="操作步骤过多，已停止。请尝试更简单的指令。")
    if doc_state.modified:
        yield AgentEvent(type="latex", data=doc_state.to_latex())
    yield AgentEvent(type="done", data="")
