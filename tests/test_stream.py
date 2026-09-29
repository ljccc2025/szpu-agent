"""M15 流式输出测试：分片累积 / 流式接口 / 流式循环 / SSE 封装 / REST。"""
import json
from types import SimpleNamespace

from fastapi.testclient import TestClient

from app import main, storage, stream
from app.core import Agent
from app.llm import LLMClient, ToolCallAccumulator
from app.tools import registry


def _tc_delta(index, cid=None, name=None, args=None):
    """构造一个 delta.tool_calls 分片。"""
    return SimpleNamespace(
        index=index, id=cid,
        function=SimpleNamespace(name=name, arguments=args),
    )


def _chunk(text=None, tool_calls=None):
    """构造一个流式 chunk（与 openai SDK 的结构同构）。"""
    delta = SimpleNamespace(content=text, tool_calls=tool_calls)
    return SimpleNamespace(choices=[SimpleNamespace(delta=delta)])


# ============ 任务 1：ToolCallAccumulator ============


def test_accumulator_rebuilds_single_call():
    acc = ToolCallAccumulator()
    acc.feed([_tc_delta(0, "call_a", "calculator", "")])
    acc.feed([_tc_delta(0, args='{"expre')])
    acc.feed([_tc_delta(0, args='ssion": "2+3"}')])
    calls = acc.finalize()
    assert len(calls) == 1
    assert calls[0].id == "call_a"
    assert calls[0].function.name == "calculator"
    assert json.loads(calls[0].function.arguments) == {"expression": "2+3"}


def test_accumulator_keeps_two_calls_separate():
    """回归：并发多工具按 index 分桶，拼错就会串号。"""
    acc = ToolCallAccumulator()
    acc.feed([
        _tc_delta(0, "c0", "calculator", '{"expression":'),
        _tc_delta(1, "c1", "rag_search", '{"query":'),
    ])
    acc.feed([_tc_delta(0, args='"1+1"}'), _tc_delta(1, args='"nginx"}')])
    calls = acc.finalize()
    assert [c.function.name for c in calls] == ["calculator", "rag_search"]
    assert json.loads(calls[0].function.arguments) == {"expression": "1+1"}
    assert json.loads(calls[1].function.arguments) == {"query": "nginx"}


def test_accumulator_ignores_empty_and_nameless():
    """空分片与始终拿不到函数名的脏数据都不该产出调用。"""
    acc = ToolCallAccumulator()
    acc.feed(None)
    acc.feed([])
    acc.feed([_tc_delta(0, args="{}")])
    assert acc.finalize() == []


def test_is_failure_matches_dispatch_error_texts():
    """tool_end 的 ok 字段靠它判定，必须与 dispatch 的失败文本对齐。"""
    assert registry.is_failure(registry.dispatch("不存在的工具", "{}")[0])
    assert registry.is_failure(registry.dispatch("calculator", "不是JSON")[0])
    assert registry.is_failure(
        registry.dispatch("calculator", '{"expression": "1/0"}')[0]
    )
    assert not registry.is_failure(
        registry.dispatch("calculator", '{"expression": "1+1"}')[0]
    )


def test_chat_stream_tool_end_reports_failure(tmp_path):
    """回归：工具失败时 tool_end.ok 必须是 false，不能一律报成功。"""
    db = str(tmp_path / "t.db")
    rounds = [
        [_chunk(tool_calls=[_tc_delta(0, "c1", "不存在的工具", "{}")])],
        [_chunk("抱歉")],
    ]
    events = _events(Agent(FakeStreamLLM(rounds), db), msg="乱调工具")
    tool_end = [p for e, p in events if e == "tool_end"][0]
    assert tool_end["ok"] is False


# ============ 任务 2：LLMClient.stream ============


class _FakeCompletions:
    def __init__(self, chunks):
        self.chunks = chunks
        self.kwargs = None

    def create(self, **kwargs):
        self.kwargs = kwargs
        return iter(self.chunks)


def _fake_client(chunks):
    """绕开 __init__ 的真实网络客户端构造，只装一个假 completions。"""
    comp = _FakeCompletions(chunks)
    client = LLMClient.__new__(LLMClient)
    client.model = "test-model"
    client._client = SimpleNamespace(
        chat=SimpleNamespace(completions=comp)
    )
    return client, comp


def test_stream_yields_text_pieces():
    client, comp = _fake_client([_chunk("云"), _chunk("计算")])
    pieces = [t for t, _ in client.stream([{"role": "user", "content": "hi"}])]
    assert pieces == ["云", "计算"]
    assert comp.kwargs["stream"] is True


def test_stream_passes_tools_through():
    tools = [{"type": "function", "function": {"name": "x"}}]
    client, comp = _fake_client([_chunk("ok")])
    list(client.stream([{"role": "user", "content": "hi"}], tools=tools))
    assert comp.kwargs["tools"] == tools


def test_stream_skips_chunk_without_choices():
    """部分网关先发只含 usage 的空 chunk，不能让它炸掉整条流。"""
    client, _ = _fake_client([SimpleNamespace(choices=[]), _chunk("正文")])
    assert [t for t, _ in client.stream([])] == ["正文"]


# ============ 任务 3：Agent.chat_stream ============


class FakeStreamLLM:
    """按脚本回放多轮流式响应；每轮是一个 chunk 列表。"""

    def __init__(self, rounds):
        self.rounds = list(rounds)
        self.seen = []

    def stream(self, messages, tools=None):
        self.seen.append([dict(m) for m in messages])
        for chunk in self.rounds.pop(0):
            choice = chunk.choices[0]
            yield choice.delta.content, choice.delta.tool_calls


class BoomStreamLLM:
    """模拟流式调用直接失败。"""

    def stream(self, messages, tools=None):
        raise RuntimeError("API 502 Bad Gateway")
        yield  # noqa: unreachable —— 让本函数成为生成器函数


def _events(agent, sid="s1", msg="你好"):
    return list(agent.chat_stream(sid, msg))


def test_chat_stream_emits_tokens_then_done(tmp_path):
    db = str(tmp_path / "t.db")
    agent = Agent(FakeStreamLLM([[_chunk("你"), _chunk("好")]]), db)
    events = _events(agent)
    assert [e for e, _ in events] == ["token", "token", "done"]
    assert events[-1][1]["reply"] == "你好"


def test_chat_stream_saves_history(tmp_path):
    db = str(tmp_path / "t.db")
    agent = Agent(FakeStreamLLM([[_chunk("好的")]]), db)
    _events(agent, msg="请问")
    assert storage.get_history(db, "s1") == [
        {"role": "user", "content": "请问"},
        {"role": "assistant", "content": "好的"},
    ]


def test_chat_stream_tool_events(tmp_path):
    db = str(tmp_path / "t.db")
    rounds = [
        [_chunk(tool_calls=[
            _tc_delta(0, "c1", "calculator", '{"expression": "2+3"}')
        ])],
        [_chunk("等于 5")],
    ]
    events = _events(Agent(FakeStreamLLM(rounds), db), msg="算一下")
    assert [e for e, _ in events] == [
        "tool_start", "tool_end", "token", "done"
    ]
    assert events[0][1]["name"] == "calculator"
    assert events[1][1]["ok"] is True
    assert events[-1][1]["reply"] == "等于 5"


def test_chat_stream_deduplicates_sources(tmp_path):
    db = str(tmp_path / "t.db")
    rounds = [
        [_chunk(tool_calls=[
            _tc_delta(0, "r1", "rag_search", '{"query": "nginx"}')
        ])],
        [_chunk("带出处的答案")],
    ]
    hit = {"source": "ch5.pdf", "page": 47, "excerpt": "x", "score": 0.9}

    def fake_dispatch(name, args):
        return "检索结果", [hit, dict(hit)]

    agent = Agent(FakeStreamLLM(rounds), db, dispatch=fake_dispatch)
    done = _events(agent, msg="nginx?")[-1]
    assert done[0] == "done"
    assert done[1]["sources"] == [hit]


def test_chat_stream_loop_limit(tmp_path):
    db = str(tmp_path / "t.db")
    endless = [
        [_chunk(tool_calls=[_tc_delta(0, "x", "get_current_time", "{}")])]
    ] * 5
    done = _events(Agent(FakeStreamLLM(endless), db), msg="疯狂调工具")[-1]
    assert done[0] == "done"
    assert "上限" in done[1]["reply"]


def test_chat_stream_error_event(tmp_path):
    db = str(tmp_path / "t.db")
    events = _events(Agent(BoomStreamLLM(), db), msg="我的问题")
    assert events[-1][0] == "error"
    assert "繁忙" in events[-1][1]["message"]


def test_chat_stream_error_keeps_user_message(tmp_path):
    """回归：流式失败时用户提问必须已落库（与非流式同一纪律）。"""
    db = str(tmp_path / "t.db")
    _events(Agent(BoomStreamLLM(), db), msg="别把我弄丢了")
    assert storage.get_history(db, "s1")[0] == {
        "role": "user", "content": "别把我弄丢了",
    }


# ============ 任务 4：SSE 封装与 REST 端点 ============


def test_sse_pack_frame_format():
    assert stream.sse_pack("token", {"text": "hi"}) == (
        'event: token\ndata: {"text": "hi"}\n\n'
    )


def test_sse_pack_keeps_chinese_readable():
    """ensure_ascii=False：中文直接可读，不是 \\uXXXX 转义。"""
    assert "云计算" in stream.sse_pack("token", {"text": "云计算"})


def test_sse_pack_escapes_newlines():
    """回归：裸换行会截断 SSE 帧，JSON 编码必须把它转义掉。"""
    frame = stream.sse_pack("token", {"text": "第一行\n第二行"})
    assert "\\n" in frame
    assert frame.count("\n") == 3


def test_chat_stream_endpoint(tmp_path, monkeypatch):
    monkeypatch.setattr(
        main, "agent",
        Agent(FakeStreamLLM([[_chunk("收到")]]), str(tmp_path / "t.db")),
    )
    r = TestClient(main.app).post(
        "/api/chat/stream", json={"session_id": "s1", "message": "你好"}
    )
    assert r.status_code == 200
    assert r.headers["content-type"].startswith("text/event-stream")
    assert "event: token" in r.text
    assert "event: done" in r.text


def test_chat_stream_endpoint_reports_error(tmp_path, monkeypatch):
    monkeypatch.setattr(
        main, "agent", Agent(BoomStreamLLM(), str(tmp_path / "t.db"))
    )
    r = TestClient(main.app).post(
        "/api/chat/stream", json={"session_id": "s1", "message": "你好"}
    )
    assert r.status_code == 200
    assert "event: error" in r.text


def test_plain_chat_endpoint_still_works(tmp_path, monkeypatch):
    """回归：新增流式端点不得影响原 /api/chat。"""

    class FakeLLM:
        def complete(self, messages, tools=None):
            return SimpleNamespace(content="非流式回答", tool_calls=None)

    monkeypatch.setattr(
        main, "agent", Agent(FakeLLM(), str(tmp_path / "t.db"))
    )
    r = TestClient(main.app).post(
        "/api/chat", json={"session_id": "s1", "message": "你好"}
    )
    assert r.json()["reply"] == "非流式回答"
