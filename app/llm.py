"""M04 LLM 客户端：openai SDK v3 兼容调用 DeepSeek，失败重试 2 次。

官方依据（2026-09 核查）：
- openai-python README：chat.completions.create 为"永久支持"标准接口
- api-docs.deepseek.com：base_url=https://api.deepseek.com, model=deepseek-flash
"""
import time
from types import SimpleNamespace

from openai import OpenAI

from app import config


def build_messages(system_prompt, history, user_message):
    return [
        {"role": "system", "content": system_prompt},
        *history,
        {"role": "user", "content": user_message},
    ]


class ToolCallAccumulator:
    """把流式返回的 tool_calls 分片还原成完整的工具调用（M15）。

    开 stream=True 后，同一个工具调用会被拆进多个 chunk：首片带 id 与
    function.name，后续片只带 function.arguments 的一小段。必须按 index
    分桶累积——并发多工具时 index 0/1/2 各自独立，拼错就会串号。
    """

    def __init__(self):
        self._slots = {}

    def feed(self, deltas):
        """喂入一个 chunk 的 delta.tool_calls（允许为 None）。"""
        for delta in deltas or []:
            slot = self._slots.setdefault(
                getattr(delta, "index", 0) or 0,
                {"id": None, "name": None, "args": ""},
            )
            if getattr(delta, "id", None):
                slot["id"] = delta.id
            function = getattr(delta, "function", None)
            if function is None:
                continue
            if getattr(function, "name", None):
                slot["name"] = function.name
            if getattr(function, "arguments", None):
                slot["args"] += function.arguments

    def finalize(self):
        """按 index 升序返回与非流式 msg.tool_calls 同构的对象列表。"""
        calls = []
        for index in sorted(self._slots):
            slot = self._slots[index]
            if not slot["name"]:
                continue  # 始终没拿到函数名：脏分片，丢弃比乱调用安全
            calls.append(
                SimpleNamespace(
                    id=slot["id"] or f"call_{index}",
                    type="function",
                    function=SimpleNamespace(
                        name=slot["name"], arguments=slot["args"] or "{}"
                    ),
                )
            )
        return calls


class LLMClient:
    def __init__(self, base_url=None, api_key=None, model=None):
        self.model = model or config.LLM_MODEL
        self._client = OpenAI(
            base_url=base_url or config.LLM_BASE_URL,
            # SDK v3 要求非空 key 才能构造客户端；占位符保证无 Key 环境（如 CI）可导入，
            # 真实调用时若仍是占位符会被 API 拒绝并触发重试逻辑抛错
            api_key=api_key or config.LLM_API_KEY or "sk-placeholder",
        )

    def complete(self, messages, tools=None, response_format=None):
        """返回 message 对象（含 .content 与 .tool_calls），失败重试 2 次。

        response_format：透传 DeepSeek JSON 模式（如 {"type": "json_object"}），
        官方要求同时在 prompt 中包含 "json" 字样与输出示例（M12 出题用）。
        """
        last_err = None
        for attempt in range(3):
            try:
                kwargs = {"model": self.model, "messages": messages}
                if tools:
                    kwargs["tools"] = tools
                if response_format:
                    kwargs["response_format"] = response_format
                resp = self._client.chat.completions.create(**kwargs)
                return resp.choices[0].message
            except Exception as err:  # 网络/限流等，指数退避后重试
                last_err = err
                if attempt < 2:
                    time.sleep(2 ** attempt)
        raise last_err

    def stream(self, messages, tools=None):
        """流式补全：逐块 yield (文本片段, tool_calls 分片)（M15）。

        与 complete() 不同，这里**不做重试**：流一旦开始吐字，中途重试会
        让学生看到重复内容；失败交由 Agent.chat_stream 兜底成 error 事件。
        """
        kwargs = {"model": self.model, "messages": messages, "stream": True}
        if tools:
            kwargs["tools"] = tools
        for chunk in self._client.chat.completions.create(**kwargs):
            choices = getattr(chunk, "choices", None)
            if not choices:
                continue  # 部分网关先发一个只含 usage 的空 chunk
            delta = getattr(choices[0], "delta", None)
            if delta is None:
                continue
            yield (
                getattr(delta, "content", None),
                getattr(delta, "tool_calls", None),
            )
