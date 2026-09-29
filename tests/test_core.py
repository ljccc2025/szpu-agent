from types import SimpleNamespace

from app import storage
from app.core import Agent


def _msg(content=None, tool_calls=None):
    return SimpleNamespace(content=content, tool_calls=tool_calls)


def _tool_call(cid, name, args):
    return SimpleNamespace(
        id=cid, function=SimpleNamespace(name=name, arguments=args)
    )


class FakeLLM:
    def __init__(self, script):
        self.script = list(script)
        self.seen = []

    def complete(self, messages, tools=None):
        self.seen.append([dict(m) for m in messages])
        return self.script.pop(0)


def test_plain_chat_saves_history(tmp_path):
    db = str(tmp_path / "t.db")
    agent = Agent(FakeLLM([_msg("你好呀")]), db)
    assert agent.chat("s1", "你好")["reply"] == "你好呀"
    assert storage.get_history(db, "s1") == [
        {"role": "user", "content": "你好"},
        {"role": "assistant", "content": "你好呀"},
    ]


def test_second_turn_includes_first(tmp_path):
    db = str(tmp_path / "t.db")
    fake = FakeLLM([_msg("回答1"), _msg("回答2")])
    agent = Agent(fake, db)
    agent.chat("s1", "第一句")
    agent.chat("s1", "第二句")
    contents = [m["content"] for m in fake.seen[1]]
    assert "第一句" in contents and "回答1" in contents
    assert contents[-1] == "第二句"


def test_tool_call_roundtrip(tmp_path):
    db = str(tmp_path / "t.db")
    fake = FakeLLM([
        _msg(tool_calls=[_tool_call("c1", "calculator", '{"expression": "2+3"}')]),
        _msg("等于 5"),
    ])
    agent = Agent(fake, db)
    assert agent.chat("s1", "算一下 2+3")["reply"] == "等于 5"
    second_call = fake.seen[1]
    roles = [m["role"] for m in second_call]
    assert "tool" in roles
    tool_msg = [m for m in second_call if m["role"] == "tool"][0]
    assert tool_msg["content"] == "5"
    assert tool_msg["tool_call_id"] == "c1"


def test_loop_limit_breaks(tmp_path):
    db = str(tmp_path / "t.db")
    endless = _msg(tool_calls=[_tool_call("x", "get_current_time", "{}")])
    agent = Agent(FakeLLM([endless] * 5), db)
    reply = agent.chat("s1", "疯狂调工具")
    assert "上限" in reply["reply"]


def test_rag_sources_collected(tmp_path, monkeypatch):
    from app.tools import rag_search

    db = str(tmp_path / "t.db")
    fake = FakeLLM([
        _msg(tool_calls=[_tool_call("r1", "rag_search", '{"query": "nginx"}')]),
        _msg("答案带出处"),
    ])

    def fake_dispatch(name, args):
        rag_search._last_sources = [
            {"source": "ch5.pdf", "page": 47, "excerpt": "x", "score": 0.9}
        ]
        return "检索结果"

    agent = Agent(fake, db, dispatch=fake_dispatch)
    result = agent.chat("s1", "nginx 反向代理?")
    assert result["reply"] == "答案带出处"
    assert result["sources"] == [
        {"source": "ch5.pdf", "page": 47, "excerpt": "x", "score": 0.9}
    ]
