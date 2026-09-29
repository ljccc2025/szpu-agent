"""M05 Agent 核心：手写 Function Calling 循环（DeepSeek 官方 Tool Calls 流程）。

流程：取历史 -> 拼 messages -> LLM 决策 -> 有 tool_calls 则执行回填再问
      -> 最多 MAX_TOOL_ROUNDS 轮熔断 -> 落库返回。
"""
from app import config, storage
from app.llm import build_messages
from app.tools import registry


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
        messages = build_messages(config.SYSTEM_PROMPT, history, user_message)
        reply = "工具调用次数超过上限，请换个问法试试。"
        sources = []
        for _ in range(config.MAX_TOOL_ROUNDS):
            msg = self.llm.complete(messages, tools=self.tools or None)
            tool_calls = getattr(msg, "tool_calls", None)
            if not tool_calls:
                reply = msg.content or ""
                break
            # 官方协议：assistant(tool_calls) -> role=tool 逐个回填
            messages.append(
                {
                    "role": "assistant",
                    "content": msg.content or "",
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
            )
            for call in tool_calls:
                result = self.dispatch(call.function.name, call.function.arguments)
                messages.append(
                    {"role": "tool", "tool_call_id": call.id, "content": result}
                )
                if call.function.name == "rag_search":
                    from app.tools import rag_search

                    sources.extend(rag_search.pop_last_sources())
        storage.save_message(self.db_path, session_id, "user", user_message)
        storage.save_message(self.db_path, session_id, "assistant", reply)
        return {"reply": reply, "sources": sources}
