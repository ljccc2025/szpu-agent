"""M05 Agent 核心：手写 Function Calling 循环（DeepSeek 官方 Tool Calls 流程）。

流程：取历史 -> 拼 messages -> LLM 决策 -> 有 tool_calls 则执行回填再问
      -> 最多 MAX_TOOL_ROUNDS 轮熔断 -> 落库返回。
"""
from app import config, storage
from app.llm import ToolCallAccumulator, build_messages
from app.tools import registry


def _assistant_tool_calls_message(content, tool_calls):
    """官方协议：assistant(tool_calls) 消息，其后跟 role=tool 逐个回填。"""
    return {
        "role": "assistant",
        "content": content or "",
        "tool_calls": [
            {
                "id": c.id,
                "type": "function",
                "function": {
                    "name": c.function.name,
                    "arguments": c.function.arguments,
                },
            }
            for c in tool_calls
        ],
    }


def _merge_sources(sources, extra):
    """多轮检索可能命中同一知识块，按(来源,页码,摘录)去重后并入。"""
    for s in extra or []:
        if not any(
            s["source"] == x["source"]
            and s["page"] == x["page"]
            and s["excerpt"] == x["excerpt"]
            for x in sources
        ):
            sources.append(s)


class Agent:
    def __init__(self, llm, db_path=None, tools=None, dispatch=None):
        self.llm = llm
        self.db_path = db_path or config.DB_PATH
        self.tools = registry.TOOLS if tools is None else tools
        self.dispatch = dispatch or registry.dispatch

    def chat(self, session_id, user_message):
        """返回 {"reply": str, "sources": list}；sources 为 RAG 出处（M07）。"""
        history = storage.get_history(
            self.db_path, session_id, limit=config.HISTORY_LIMIT
        )
        # 先落库用户提问：LLM 失败时也不能把学生刚打的问题弄丢（规格 §5）
        storage.save_message(self.db_path, session_id, "user", user_message)
        messages = build_messages(config.SYSTEM_PROMPT, history, user_message)
        reply = "工具调用次数超过上限，请换个问法试试。"
        sources = []
        try:
            for _ in range(config.MAX_TOOL_ROUNDS):
                msg = self.llm.complete(messages, tools=self.tools or None)
                tool_calls = getattr(msg, "tool_calls", None)
                if not tool_calls:
                    reply = msg.content or ""
                    break
                # 官方协议：assistant(tool_calls) -> role=tool 逐个回填
                messages.append(
                    _assistant_tool_calls_message(msg.content, tool_calls)
                )
                for call in tool_calls:
                    result, extra = self.dispatch(
                        call.function.name, call.function.arguments
                    )
                    messages.append(
                        {"role": "tool", "tool_call_id": call.id, "content": result}
                    )
                    _merge_sources(sources, extra)
        except Exception:
            # LLM 重试 2 次后仍失败：给友好提示，历史已保留（规格 §5）
            reply = "服务暂时繁忙，请稍后再试。"
            sources = []
        storage.save_message(self.db_path, session_id, "assistant", reply)
        return {"reply": reply, "sources": sources}

    def chat_stream(self, session_id, user_message):
        """M15 流式版 chat()：逐事件产出 (事件名, 载荷)。

        事件：token / tool_start / tool_end / done / error。
        与 chat() 共用同一套纪律——先落库用户提问、最多 MAX_TOOL_ROUNDS
        轮熔断、出处去重、异常兜底成友好文案且历史不丢（规格 §5）。
        """
        history = storage.get_history(
            self.db_path, session_id, limit=config.HISTORY_LIMIT
        )
        # 与 chat() 一致：先落库用户提问，LLM 失败时也不能把提问弄丢
        storage.save_message(self.db_path, session_id, "user", user_message)
        messages = build_messages(config.SYSTEM_PROMPT, history, user_message)
        reply = "工具调用次数超过上限，请换个问法试试。"
        sources = []
        failed = False
        try:
            for _ in range(config.MAX_TOOL_ROUNDS):
                parts = []
                accumulator = ToolCallAccumulator()
                for text, call_deltas in self.llm.stream(
                    messages, tools=self.tools or None
                ):
                    if text:
                        parts.append(text)
                        yield "token", {"text": text}
                    accumulator.feed(call_deltas)
                tool_calls = accumulator.finalize()
                if not tool_calls:
                    reply = "".join(parts)
                    break
                messages.append(
                    _assistant_tool_calls_message("".join(parts), tool_calls)
                )
                for call in tool_calls:
                    name = call.function.name
                    yield "tool_start", {"name": name}
                    result, extra = self.dispatch(
                        name, call.function.arguments
                    )
                    yield "tool_end", {
                        "name": name, "ok": not registry.is_failure(result)
                    }
                    messages.append(
                        {"role": "tool", "tool_call_id": call.id,
                         "content": result}
                    )
                    _merge_sources(sources, extra)
        except Exception:
            reply = "服务暂时繁忙，请稍后再试。"
            sources = []
            failed = True
        storage.save_message(self.db_path, session_id, "assistant", reply)
        if failed:
            yield "error", {"message": reply}
        else:
            yield "done", {"reply": reply, "sources": sources}
