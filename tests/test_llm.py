"""M04 LLM 客户端测试：消息拼装 + 重试路径 + 流式分片防御分支。

其中重试相关用例为 M21 补测：覆盖率报告显示 `complete()` 的退避重试
从未被执行过——所有上层测试都注入 FakeLLM，而这条路径线上真会走
（网络抖动、限流），属于真实盲区而非死代码。
"""
import time
from types import SimpleNamespace

import pytest

from app.llm import LLMClient, ToolCallAccumulator, build_messages


def test_build_messages_order():
    history = [
        {"role": "user", "content": "a"},
        {"role": "assistant", "content": "b"},
    ]
    msgs = build_messages("系统提示", history, "新问题")
    assert msgs[0] == {"role": "system", "content": "系统提示"}
    assert msgs[1:3] == history
    assert msgs[-1] == {"role": "user", "content": "新问题"}
    assert len(msgs) == 4


# ============ M21 补测：complete() 的退避重试路径 ============


class _FlakyCompletions:
    """前 fail_times 次调用抛异常，之后返回正常响应。"""

    def __init__(self, fail_times, error=None):
        self.fail_times = fail_times
        self.calls = 0
        self.kwargs = None
        self.error = error or RuntimeError("API 502 Bad Gateway")

    def create(self, **kwargs):
        self.calls += 1
        self.kwargs = kwargs
        if self.calls <= self.fail_times:
            raise self.error
        return SimpleNamespace(
            choices=[
                SimpleNamespace(
                    message=SimpleNamespace(content="成功回答", tool_calls=None)
                )
            ]
        )


def _client(completions):
    """绕开 __init__ 里真实 OpenAI 客户端的构造。"""
    c = LLMClient.__new__(LLMClient)
    c.model = "test-model"
    c._client = SimpleNamespace(
        chat=SimpleNamespace(completions=completions)
    )
    return c


@pytest.fixture
def slept(monkeypatch):
    """退避不真等，只记录每次退避的秒数。"""
    recorded = []
    monkeypatch.setattr(time, "sleep", lambda s: recorded.append(s))
    return recorded


def test_complete_returns_on_first_success(slept):
    comp = _FlakyCompletions(0)
    msg = _client(comp).complete([{"role": "user", "content": "hi"}])
    assert msg.content == "成功回答"
    assert comp.calls == 1
    assert slept == []  # 一次就成功，不该退避


def test_complete_retries_then_succeeds(slept):
    """回归：网络抖动时应指数退避重试，而不是直接把异常抛给用户。"""
    comp = _FlakyCompletions(2)
    msg = _client(comp).complete([{"role": "user", "content": "hi"}])
    assert msg.content == "成功回答"
    assert comp.calls == 3
    assert slept == [1, 2]  # 2**0, 2**1


def test_complete_raises_after_three_failures(slept):
    """三次全失败必须抛出最后一个异常，交由上层兜底成友好文案。"""
    comp = _FlakyCompletions(99, error=RuntimeError("API 永久不可用"))
    with pytest.raises(RuntimeError, match="永久不可用"):
        _client(comp).complete([{"role": "user", "content": "hi"}])
    assert comp.calls == 3
    assert slept == [1, 2]  # 最后一次失败后不再退避


def test_complete_passes_tools_and_response_format(slept):
    comp = _FlakyCompletions(0)
    tools = [{"type": "function", "function": {"name": "x"}}]
    fmt = {"type": "json_object"}
    _client(comp).complete([], tools=tools, response_format=fmt)
    assert comp.kwargs["tools"] == tools
    assert comp.kwargs["response_format"] == fmt
    assert "stream" not in comp.kwargs  # 非流式不得误传 stream


def test_complete_omits_optional_kwargs_when_absent(slept):
    comp = _FlakyCompletions(0)
    _client(comp).complete([])
    assert "tools" not in comp.kwargs
    assert "response_format" not in comp.kwargs


# ============ M21 补测：流式分片的防御分支 ============


def test_accumulator_skips_delta_without_function():
    """分片可能只带 id 不带 function，不能因此崩掉整轮对话。"""
    acc = ToolCallAccumulator()
    acc.feed([SimpleNamespace(index=0, id="c1", function=None)])
    acc.feed([
        SimpleNamespace(
            index=0, id=None,
            function=SimpleNamespace(name="calculator", arguments="{}"),
        )
    ])
    calls = acc.finalize()
    assert len(calls) == 1
    assert calls[0].id == "c1"
    assert calls[0].function.name == "calculator"


def test_stream_skips_chunk_with_none_delta():
    """部分网关会发 delta 为 None 的收尾 chunk。"""

    class _Completions:
        def create(self, **kwargs):
            return iter([
                SimpleNamespace(choices=[SimpleNamespace(delta=None)]),
                SimpleNamespace(choices=[
                    SimpleNamespace(
                        delta=SimpleNamespace(content="正文", tool_calls=None)
                    )
                ]),
            ])

    assert [t for t, _ in _client(_Completions()).stream([])] == ["正文"]
