"""M14 学习规划测试：聚合排序 / 空态 / 校验 / 三段式 / 工具 / REST。"""
import json
from types import SimpleNamespace

import pytest

from app import config, storage
from app.tools import planner


def _attempt(db, topic, score, weak=None, qtype="单选题"):
    qid = storage.save_quiz(db, topic, "中等", qtype, "题干", "[]",
                            "A", "解析", "第5章.md")
    storage.save_attempt(db, qid, topic, qtype, "B", score, "点评",
                         json.dumps(weak or [], ensure_ascii=False))


# ---------- 任务1：storage 聚合 ----------

def test_aggregate_orders_by_wrong_count_desc(tmp_path):
    db = str(tmp_path / "t.db")
    _attempt(db, "Nginx 反向代理", 0)
    _attempt(db, "Nginx 反向代理", 0)
    _attempt(db, "Linux 文件查看", 0)
    _attempt(db, "Docker 数据卷", 100)
    rows = storage.aggregate_weak_topics(db, max_score=60, limit=5)
    assert [r["topic"] for r in rows] == ["Nginx 反向代理", "Linux 文件查看"]
    assert rows[0]["wrong_count"] == 2
    assert rows[0]["total_count"] == 2
    assert rows[0]["avg_score"] == 0.0


def test_aggregate_excludes_all_correct_topics(tmp_path):
    db = str(tmp_path / "t.db")
    _attempt(db, "Docker 数据卷", 100)
    assert storage.aggregate_weak_topics(db, max_score=60, limit=5) == []


def test_aggregate_respects_limit(tmp_path):
    db = str(tmp_path / "t.db")
    for i in range(4):
        _attempt(db, "知识点%d" % i, 0)
    assert len(storage.aggregate_weak_topics(db, max_score=60, limit=2)) == 2


def test_weak_point_rows_returns_raw_json_strings(tmp_path):
    db = str(tmp_path / "t.db")
    _attempt(db, "Nginx 反向代理", 0, weak=["Nginx 反向代理", "反向代理原理"])
    rows = storage.weak_point_rows(db, "Nginx 反向代理", max_score=60)
    assert rows == ['["Nginx 反向代理", "反向代理原理"]']


# ---------- 任务2：薄弱知识点整理 ----------

def test_weak_topics_merges_labels_and_dedups(tmp_path):
    db = str(tmp_path / "t.db")
    _attempt(db, "Nginx 反向代理", 0, weak=["Nginx 反向代理", "反向代理原理"])
    _attempt(db, "Nginx 反向代理", 40, weak=["反向代理原理"])
    rows = planner.weak_topics(db_path=db)
    assert len(rows) == 1
    r = rows[0]
    assert r["topic"] == "Nginx 反向代理"
    assert r["wrong_count"] == 2
    # 标签按「最近错题优先」合并去重，与错题本列表(id DESC)的顺序语义一致：
    # 第二次作答(id 更大)的 ["反向代理原理"] 先进，第一次的再补上新标签
    assert r["labels"] == ["反向代理原理", "Nginx 反向代理"]


def test_weak_topics_tolerates_broken_weak_points_json(tmp_path):
    db = str(tmp_path / "t.db")
    qid = storage.save_quiz(db, "X", "中等", "单选题", "q", "[]", "A", "e", "s.md")
    storage.save_attempt(db, qid, "X", "单选题", "B", 0, "点评", "不是JSON")
    rows = planner.weak_topics(db_path=db)
    assert rows[0]["labels"] == []


def test_weak_topics_empty_returns_empty_list(tmp_path):
    assert planner.weak_topics(db_path=str(tmp_path / "t.db")) == []


# ---------- 任务3：计划结构校验 ----------

def test_valid_plan_passes():
    data = {"daily_plan": [
        {"day": 1, "topic": "A", "focus": "重点", "practice": "练习"},
        {"day": 2, "topic": "B", "focus": "重点", "practice": "练习"},
    ]}
    assert planner.validate_plan(data, days=2) is None


@pytest.mark.parametrize("bad,why", [
    ({}, "缺 daily_plan"),
    ({"daily_plan": "不是数组"}, "类型错"),
    ({"daily_plan": [{"day": 1, "topic": "A", "focus": "f", "practice": "p"}]},
     "天数不符"),
    ({"daily_plan": [{"day": 2, "topic": "A", "focus": "f", "practice": "p"},
                     {"day": 1, "topic": "B", "focus": "f", "practice": "p"}]},
     "day 不连续"),
    ({"daily_plan": [{"day": 1, "topic": "", "focus": "f", "practice": "p"},
                     {"day": 2, "topic": "B", "focus": "f", "practice": "p"}]},
     "字段为空"),
])
def test_invalid_plan_rejected(bad, why):
    assert planner.validate_plan(bad, days=2) is not None, why


# ---------- 任务4：make_plan 三段式 ----------

class FakeLLM:
    def __init__(self, *contents):
        self.contents = list(contents)
        self.calls = []

    def complete(self, messages, tools=None, response_format=None):
        self.calls.append({"messages": messages,
                           "response_format": response_format})
        return SimpleNamespace(content=self.contents.pop(0))


def _plan_json(days):
    return json.dumps({"daily_plan": [
        {"day": d, "topic": "Nginx 反向代理", "focus": "重点", "practice": "练习"}
        for d in range(1, days + 1)]}, ensure_ascii=False)


@pytest.fixture()
def patched_rag(monkeypatch):
    calls = []

    def fake_search(query):
        calls.append(query)
        return ("[来源: 第5章-Nginx服务部署.md 第1页] proxy_pass 说明",
                [{"source": "第5章-Nginx服务部署.md", "page": 1,
                  "excerpt": "proxy_pass", "score": 0.8}])

    monkeypatch.setattr(planner.rag_search, "search", fake_search)
    return calls


def test_make_plan_empty_wrong_book_raises(tmp_path):
    with pytest.raises(planner.PlannerError, match="还没有错题"):
        planner.make_plan(days=3, db_path=str(tmp_path / "t.db"))


@pytest.mark.parametrize("days", [0, -1, 31])
def test_make_plan_rejects_bad_days(tmp_path, days):
    with pytest.raises(planner.PlannerError, match="天数"):
        planner.make_plan(days=days, db_path=str(tmp_path / "t.db"))


def test_make_plan_queries_rag_for_each_topic(tmp_path, patched_rag):
    db = str(tmp_path / "t.db")
    _attempt(db, "Nginx 反向代理", 0)
    _attempt(db, "Linux 文件查看", 0)
    planner.make_plan(days=2, db_path=db, llm=FakeLLM(_plan_json(2)))
    # 两者错题数与平均分相同，走 topic ASC 兜底保证排序确定（L < N）
    assert patched_rag == ["Linux 文件查看", "Nginx 反向代理"]


def test_weak_topics_tiebreak_prefers_lower_average(tmp_path):
    """错题数相同时，平均分低的排前面（比字母序优先级更高）。"""
    db = str(tmp_path / "t.db")
    _attempt(db, "AAA 知识点", 50)      # 错 1 题，均分 50
    _attempt(db, "ZZZ 知识点", 0)       # 错 1 题，均分 0
    rows = planner.weak_topics(db_path=db)
    assert [r["topic"] for r in rows] == ["ZZZ 知识点", "AAA 知识点"]


def test_make_plan_returns_stats_and_sources(tmp_path, patched_rag):
    db = str(tmp_path / "t.db")
    _attempt(db, "Nginx 反向代理", 0, weak=["反向代理原理"])
    result = planner.make_plan(days=2, db_path=db, llm=FakeLLM(_plan_json(2)))
    assert result["days"] == 2
    assert result["weak_topics"][0]["topic"] == "Nginx 反向代理"
    assert result["weak_topics"][0]["wrong_count"] == 1
    assert result["weak_topics"][0]["labels"] == ["反向代理原理"]
    assert result["sources"] == ["第5章-Nginx服务部署.md"]
    assert len(result["daily_plan"]) == 2


def test_make_plan_uses_json_mode(tmp_path, patched_rag):
    db = str(tmp_path / "t.db")
    _attempt(db, "Nginx 反向代理", 0)
    llm = FakeLLM(_plan_json(1))
    planner.make_plan(days=1, db_path=db, llm=llm)
    assert llm.calls[0]["response_format"] == {"type": "json_object"}
    prompt = llm.calls[0]["messages"][0]["content"]
    assert "json" in prompt.lower()
    assert "不得编造" in prompt


def test_make_plan_retries_once_on_bad_json(tmp_path, patched_rag):
    db = str(tmp_path / "t.db")
    _attempt(db, "Nginx 反向代理", 0)
    llm = FakeLLM("这不是json", _plan_json(1))
    result = planner.make_plan(days=1, db_path=db, llm=llm)
    assert len(result["daily_plan"]) == 1
    assert len(llm.calls) == 2


def test_make_plan_two_failures_raise(tmp_path, patched_rag):
    db = str(tmp_path / "t.db")
    _attempt(db, "Nginx 反向代理", 0)
    with pytest.raises(planner.PlannerError, match="生成失败"):
        planner.make_plan(days=1, db_path=db, llm=FakeLLM("坏", "还是坏"))


def test_make_plan_wraps_llm_network_error(tmp_path, patched_rag):
    db = str(tmp_path / "t.db")
    _attempt(db, "Nginx 反向代理", 0)

    class BoomLLM:
        def complete(self, messages, tools=None, response_format=None):
            raise RuntimeError("Connection reset")

    with pytest.raises(planner.PlannerError, match="暂时不可用"):
        planner.make_plan(days=1, db_path=db, llm=BoomLLM())


# ---------- 任务5：工具入口与注册 ----------

def test_study_plan_tool_registered():
    from app.tools import registry

    names = [t["function"]["name"] for t in registry.TOOLS]
    assert "make_study_plan" in names
    assert registry.HANDLERS["make_study_plan"] is planner.make_study_plan
    schema = next(t for t in registry.TOOLS
                  if t["function"]["name"] == "make_study_plan")
    assert set(schema["function"]["parameters"]["properties"]) == {"days"}


def test_study_plan_tool_text(tmp_path, monkeypatch, patched_rag):
    db = str(tmp_path / "t.db")
    monkeypatch.setattr(config, "DB_PATH", db)
    _attempt(db, "Nginx 反向代理", 0)
    monkeypatch.setattr(planner, "_get_llm", lambda: FakeLLM(_plan_json(2)))
    text = planner.make_study_plan(days=2)
    assert "第 1 天" in text and "第 2 天" in text
    assert "Nginx 反向代理" in text
    assert "第5章-Nginx服务部署.md" in text


def test_study_plan_tool_error_as_text(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "DB_PATH", str(tmp_path / "t.db"))
    assert planner.make_study_plan(days=7).startswith("暂时无法生成复习计划：")


# ---------- 任务6：REST ----------

def _client(tmp_path, monkeypatch):
    from fastapi.testclient import TestClient

    from app import main
    from app.core import Agent

    db = str(tmp_path / "t.db")
    monkeypatch.setattr(main, "agent", Agent(None, db))
    return TestClient(main.app), db


def test_api_plan_ok(tmp_path, monkeypatch, patched_rag):
    client, db = _client(tmp_path, monkeypatch)
    _attempt(db, "Nginx 反向代理", 0)
    monkeypatch.setattr(planner, "_get_llm", lambda: FakeLLM(_plan_json(3)))
    r = client.post("/api/plan", json={"days": 3})
    assert r.status_code == 200
    body = r.json()
    assert body["days"] == 3
    assert len(body["daily_plan"]) == 3
    assert body["weak_topics"][0]["topic"] == "Nginx 反向代理"


def test_api_plan_empty_wrong_book_422(tmp_path, monkeypatch):
    client, _ = _client(tmp_path, monkeypatch)
    r = client.post("/api/plan", json={"days": 7})
    assert r.status_code == 422
    assert "还没有错题" in r.json()["detail"]


def test_api_plan_rejects_out_of_range_days(tmp_path, monkeypatch):
    client, _ = _client(tmp_path, monkeypatch)
    assert client.post("/api/plan", json={"days": 99}).status_code == 422
