import threading
import time
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
    db = str(tmp_path / "t.db")
    fake = FakeLLM([
        _msg(tool_calls=[_tool_call("r1", "rag_search", '{"query": "nginx"}')]),
        _msg("答案带出处"),
    ])

    def fake_dispatch(name, args):
        return "检索结果", [
            {"source": "ch5.pdf", "page": 47, "excerpt": "x", "score": 0.9}
        ]

    agent = Agent(fake, db, dispatch=fake_dispatch)
    result = agent.chat("s1", "nginx 反向代理?")
    assert result["reply"] == "答案带出处"
    assert result["sources"] == [
        {"source": "ch5.pdf", "page": 47, "excerpt": "x", "score": 0.9}
    ]


class BoomLLM:
    """模拟重试耗尽后仍失败的 LLM 客户端。"""

    def complete(self, messages, tools=None):
        raise RuntimeError("API 502 Bad Gateway")


def test_llm_failure_returns_friendly_reply(tmp_path):
    """回归：LLM 失败不得把异常抛给调用方（规格 §5 要求提示服务繁忙）。"""
    db = str(tmp_path / "t.db")
    result = Agent(BoomLLM(), db).chat("s1", "我的问题")
    assert "繁忙" in result["reply"]
    assert result["sources"] == []


def test_llm_failure_keeps_user_message(tmp_path):
    """回归：LLM 失败时用户提问必须已落库（规格 §5 要求历史不丢失）。"""
    db = str(tmp_path / "t.db")
    Agent(BoomLLM(), db).chat("s1", "别把我弄丢了")
    history = storage.get_history(db, "s1")
    assert history[0] == {"role": "user", "content": "别把我弄丢了"}


def test_user_message_saved_exactly_once(tmp_path):
    db = str(tmp_path / "t.db")
    Agent(FakeLLM([_msg("好的")]), db).chat("s1", "只说一次")
    contents = [m["content"] for m in storage.get_history(db, "s1")]
    assert contents.count("只说一次") == 1


def test_concurrent_sessions_do_not_share_sources(tmp_path):
    """回归：出处经模块级全局变量传递会导致并发会话串号。"""
    barrier = threading.Barrier(2)
    results = {}

    def run(tag, page):
        def disp(name, args):
            payload = [
                {"source": tag + ".pdf", "page": page, "excerpt": tag, "score": 0.9}
            ]
            barrier.wait()
            time.sleep(0.05)
            return "检索结果", payload

        fake = FakeLLM([
            _msg(tool_calls=[_tool_call("c" + tag, "rag_search", '{"query": "q"}')]),
            _msg("答案" + tag),
        ])
        db = str(tmp_path / (tag + ".db"))
        agent = Agent(fake, db, dispatch=disp)
        results[tag] = agent.chat("s-" + tag, "问题")["sources"]

    threads = [
        threading.Thread(target=run, args=("A", 1)),
        threading.Thread(target=run, args=("B", 2)),
    ]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert results["A"][0]["source"] == "A.pdf"
    assert results["B"][0]["source"] == "B.pdf"
