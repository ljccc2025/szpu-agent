"""M20 多 Agent 流水线测试：讲解官 / 两阶段编排 / 异常兜底 / REST。"""
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from app import main, pipeline, storage
from app.tools import grader, quiz


class FakeLLM:
    """按脚本回放 complete() 结果，并记录收到的 messages。"""

    def __init__(self, replies=None):
        self.replies = list(replies or ["讲解正文"])
        self.seen = []

    def complete(self, messages, tools=None, response_format=None):
        self.seen.append(messages)
        text = self.replies.pop(0) if self.replies else "讲解正文"
        return SimpleNamespace(content=text, tool_calls=None)


class BoomLLM:
    def complete(self, messages, tools=None, response_format=None):
        raise RuntimeError("API 502")


HIT = {"source": "第5章-Nginx服务部署.md", "page": 3,
       "excerpt": "反向代理配置", "score": 0.91}


def _result(topic="Nginx 反向代理", score=0, qtype="单选题"):
    """构造一个批改结果（形状与 grader.grade 返回值一致）。"""
    return {
        "quiz_id": 1, "topic": topic, "qtype": qtype, "score": score,
        "passed": score >= grader.PASS_SCORE, "feedback": "回答错误",
        "weak_points": [topic], "correct_answer": "D",
        "explanation": "标准解析", "source": "第5章-Nginx服务部署.md",
    }


# ============ 任务 1：讲解官 ============


def test_explainer_retrieves_by_topic(monkeypatch):
    """讲解官必须拿知识点去做真实检索，而不是凭空讲。"""
    asked = []

    def fake_search(q):
        asked.append(q)
        return "检索到的讲义原文", [HIT]

    monkeypatch.setattr(pipeline.rag_search, "search", fake_search)
    text, sources = pipeline.explain(_result(), llm=FakeLLM(["针对性讲解"]))
    assert asked == ["Nginx 反向代理"]
    assert text == "针对性讲解"
    assert sources == [HIT]


def test_explainer_prompt_carries_grading_context(monkeypatch):
    """讲解官要看到学生的得分与点评，否则讲解无法有针对性。"""
    monkeypatch.setattr(
        pipeline.rag_search, "search", lambda q: ("讲义原文", [HIT])
    )
    llm = FakeLLM(["讲解"])
    pipeline.explain(_result(score=0), llm=llm)
    blob = "".join(m["content"] for m in llm.seen[0])
    assert "回答错误" in blob      # 点评
    assert "讲义原文" in blob      # 检索到的资料


def test_explainer_degrades_when_no_material(monkeypatch):
    """回归：检索为空时如实降级，绝不编造出处。"""
    monkeypatch.setattr(pipeline.rag_search, "search", lambda q: ("空", []))
    llm = FakeLLM(["不该被调用"])
    text, sources = pipeline.explain(_result(), llm=llm)
    assert sources == []
    assert "没有检索到" in text
    assert llm.seen == []          # 无资料时零 LLM 开销


# ============ 任务 2：两阶段编排 ============


def test_quiz_stage_event_order(monkeypatch):
    monkeypatch.setattr(pipeline.quiz, "generate", lambda *a, **k: {
        "quiz_id": 7, "topic": "T", "difficulty": "中等", "qtype": "单选题",
        "question": "题干", "options": ["A", "B", "C", "D"],
        "answer": "C", "explanation": "解析", "source": "ch5.md",
    })
    events = list(pipeline.run(topic="T"))
    assert [e for e, _ in events] == ["agent_start", "agent_output", "done"]
    assert events[0][1]["role"] == "quizmaster"
    assert events[-1][1]["quiz_id"] == 7


def test_quiz_stage_never_leaks_answer(monkeypatch):
    """回归：正确答案与解析绝不能出服务端（与 M12 同一纪律）。"""
    monkeypatch.setattr(pipeline.quiz, "generate", lambda *a, **k: {
        "quiz_id": 7, "topic": "T", "difficulty": "中等", "qtype": "单选题",
        "question": "题干", "options": ["A", "B", "C", "D"],
        "answer": "C", "explanation": "泄露了就完了", "source": "ch5.md",
    })
    payload = [p for e, p in pipeline.run(topic="T") if e == "agent_output"][0]
    assert "answer" not in payload
    assert "explanation" not in payload
    assert "泄露了就完了" not in str(payload)


def test_grade_stage_event_order(monkeypatch):
    monkeypatch.setattr(pipeline.grader, "grade", lambda *a, **k: _result())
    monkeypatch.setattr(
        pipeline.rag_search, "search", lambda q: ("讲义原文", [HIT])
    )
    events = list(pipeline.run(
        quiz_id=1, student_answer="A", llm=FakeLLM(["讲解正文"])
    ))
    assert [e for e, _ in events] == [
        "agent_start", "agent_output", "agent_start", "agent_output", "done"
    ]
    assert events[0][1]["role"] == "grader"
    assert events[2][1]["role"] == "explainer"
    assert events[3][1]["sources"] == [HIT]


def test_grade_stage_reuses_m13_not_reimplement(monkeypatch):
    """回归：批改必须走 M13 grader.grade，不得另写一套评分逻辑。"""
    called = []
    monkeypatch.setattr(
        pipeline.grader, "grade",
        lambda qid, ans, **k: called.append((qid, ans)) or _result()
    )
    monkeypatch.setattr(
        pipeline.rag_search, "search", lambda q: ("讲义", [HIT])
    )
    list(pipeline.run(quiz_id=42, student_answer="B", llm=FakeLLM()))
    assert called == [(42, "B")]


def test_domain_error_becomes_error_event(monkeypatch):
    def boom(*a, **k):
        raise quiz.QuizError("知识库里没有该知识点的资料")

    monkeypatch.setattr(pipeline.quiz, "generate", boom)
    events = list(pipeline.run(topic="不存在"))
    assert events[-1][0] == "error"
    assert "没有该知识点" in events[-1][1]["message"]


def test_unexpected_error_becomes_friendly_error(monkeypatch):
    monkeypatch.setattr(pipeline.grader, "grade", lambda *a, **k: _result())
    monkeypatch.setattr(
        pipeline.rag_search, "search", lambda q: ("讲义", [HIT])
    )
    events = list(pipeline.run(
        quiz_id=1, student_answer="A", llm=BoomLLM()
    ))
    assert events[-1][0] == "error"
    assert "繁忙" in events[-1][1]["message"]


# ============ 任务 3：SSE 与 REST ============


def test_pipeline_sse_frames(monkeypatch):
    from app import stream
    monkeypatch.setattr(pipeline.quiz, "generate", lambda *a, **k: {
        "quiz_id": 3, "topic": "T", "difficulty": "中等", "qtype": "单选题",
        "question": "题干", "options": ["A", "B", "C", "D"],
        "answer": "A", "explanation": "x", "source": "s.md",
    })
    frames = "".join(stream.pipeline_sse(topic="T"))
    assert "event: agent_start" in frames
    assert "event: done" in frames


def test_pipeline_endpoint_quiz_stage(monkeypatch):
    monkeypatch.setattr(pipeline.quiz, "generate", lambda *a, **k: {
        "quiz_id": 9, "topic": "T", "difficulty": "中等", "qtype": "单选题",
        "question": "题干", "options": ["A", "B", "C", "D"],
        "answer": "B", "explanation": "x", "source": "s.md",
    })
    r = TestClient(main.app).post("/api/pipeline/run", json={"topic": "T"})
    assert r.status_code == 200
    assert r.headers["content-type"].startswith("text/event-stream")
    assert "event: agent_start" in r.text
    assert "出题官" in r.text


def test_pipeline_endpoint_rejects_empty_request():
    """既不给 topic 也不给 quiz_id 属于语义错误，应为 422 而非 500。"""
    r = TestClient(main.app).post("/api/pipeline/run", json={})
    assert r.status_code == 422
