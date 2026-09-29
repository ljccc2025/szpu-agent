"""M04 LLM 客户端：openai SDK v3 兼容调用 DeepSeek，失败重试 2 次。

官方依据（2026-09 核查）：
- openai-python README：chat.completions.create 为"永久支持"标准接口
- api-docs.deepseek.com：base_url=https://api.deepseek.com, model=deepseek-flash
"""
import time

from openai import OpenAI

from app import config


def build_messages(system_prompt, history, user_message):
    return [
        {"role": "system", "content": system_prompt},
        *history,
        {"role": "user", "content": user_message},
    ]


class LLMClient:
    def __init__(self, base_url=None, api_key=None, model=None):
        self.model = model or config.LLM_MODEL
        self._client = OpenAI(
            base_url=base_url or config.LLM_BASE_URL,
            # SDK v3 要求非空 key 才能构造客户端；占位符保证无 Key 环境（如 CI）可导入，
            # 真实调用时若仍是占位符会被 API 拒绝并触发重试逻辑抛错
            api_key=api_key or config.LLM_API_KEY or "sk-placeholder",
        )

    def complete(self, messages, tools=None):
        """返回 message 对象（含 .content 与 .tool_calls），失败重试 2 次。"""
        last_err = None
        for attempt in range(3):
            try:
                kwargs = {"model": self.model, "messages": messages}
                if tools:
                    kwargs["tools"] = tools
                resp = self._client.chat.completions.create(**kwargs)
                return resp.choices[0].message
            except Exception as err:  # 网络/限流等，指数退避后重试
                last_err = err
                if attempt < 2:
                    time.sleep(2 ** attempt)
        raise last_err
