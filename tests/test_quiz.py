# -*- coding: utf-8 -*-
"""M12 出题工具测试：校验/拒绝出题/重试/落库/注册/API。

出题成功主链路由 test_quiz_real_api.py 用真实 DeepSeek 验证；
本文件的 FakeLLM 只负责真实 API 无法稳定复现的失败路径
（坏 JSON、空内容、重试耗尽）。
"""
import json

import pytest
from fastapi.testclient import TestClient

from app import main, storage
from app.tools import quiz, rag_search, registry

MATERIAL = "[来源: 第5章-Nginx服务部署.md 第1页] proxy_pass 把请求转发给后端"
SOURCES = [{"source": "第5章-Nginx服务部署.md", "page": 1,
            "excerpt": "proxy_pass", "score": 0.8}]

GOOD_CHOICE = {
    "question": "proxy_pass 指令的作用是什么？",
    "options": ["转发请求到后端", "限制内存", "格式化磁盘", "查看日志"],
    "answer": "a",  # 故意小写：验证归一化为大写
    "explanation": "详见第5章 5.3 节。",
}


class FakeMsg:
    def __init__(self, content):
        self.content = content


class FakeLLM:
    """按脚本顺序吐回复，并记录调用参数。"""

    def __init__(self, contents):
        self._contents = list(contents)
        self.calls = []

    def complete(self, messages, tools=None, response_format=None):
        self.calls.append({"messages": messages, "response_format": response_format})
        return FakeMsg(self._contents.pop(0))


@pytest.fixture
def kb(monkeypatch):
    monkeypatch.setattr(rag_search, "search", lambda q: (MATERIAL, SOURCES))


@pytest.fixture
def db(tmp_path):
    return str(tmp_path / "quiz.db")


# ---------- validate_payload ----------

def test_validate_good_choice():
    assert quiz.validate_payload(dict(GOOD_CHOICE), "单选题") is None


@pytest.mark.parametrize("mutate,keyword", [
    (lambda d: d.pop("question"), "question"),
    (lambda d: d.update(answer="  "), "answer"),
    (lambda d: d.update(options=["只有一个"]), "4 个选项"),
    (lambda d: d.update(answer="E"), "A/B/C/D"),
    (lambda d: d.update(options=["a", "b", "c", ""]), "非空"),
])
def test_validate_bad_choice(mutate, keyword):
    data = dict(GOOD_CHOICE)
    mutate(data)
    assert keyword in quiz.validate_payload(data, "单选题")


def test_validate_practical_normalizes_options():
    data = {"question": "写出重载 nginx 的命令", "options": None,
            "answer": "nginx -s reload", "explanation": "平滑重载"}
    assert quiz.validate_payload(data, "命令实操题") is None
    assert data["options"] == []
    bad = dict(data, options=["不该有选项"])
    assert "空数组" in quiz.validate_payload(bad, "命令实操题")


# ---------- generate：参数与拒绝出题 ----------

def test_generate_rejects_bad_args(db):
    with pytest.raises(quiz.QuizError):
        quiz.generate("", db_path=db)
    with pytest.raises(quiz.QuizError, match="难度"):
        quiz.generate("nginx", difficulty="地狱", db_path=db)
    with pytest.raises(quiz.QuizError, match="题型"):
        quiz.generate("nginx", qtype="论述题", db_path=db)


def test_generate_refuses_without_material(monkeypatch, db):
    monkeypatch.setattr(
        rag_search, "search", lambda q: (rag_search.NO_RESULT_TEXT, [])
    )
    with pytest.raises(quiz.QuizError, match="无法出题"):
        quiz.generate("周杰伦", llm=FakeLLM([]), db_path=db)


# ---------- generate：成功、重试、耗尽 ----------

def test_generate_success_and_persist(kb, db):
    llm = FakeLLM([json.dumps(GOOD_CHOICE, ensure_ascii=False)])
    q = quiz.generate("nginx 反向代理", llm=llm, db_path=db)
    assert q["answer"] == "A"  # 小写归一化
    assert q["source"] == "第5章-Nginx服务部署.md"
    assert llm.calls[0]["response_format"] == {"type": "json_object"}
    prompt = llm.calls[0]["messages"][0]["content"]
    assert "json" in prompt and "proxy_pass" in prompt  # 官方要求含json+取材注入
    saved = storage.get_quiz(db, q["quiz_id"])
    assert saved["question"] == q["question"]
    assert json.loads(saved["options"]) == q["options"]


@pytest.mark.parametrize("first", ["这不是JSON", "", '{"question": "缺字段"}'])
def test_generate_retry_once_then_succeed(kb, db, first):
    llm = FakeLLM([first, json.dumps(GOOD_CHOICE, ensure_ascii=False)])
    q = quiz.generate("nginx", llm=llm, db_path=db)
    assert q["quiz_id"] >= 1
    assert len(llm.calls) == 2


def test_generate_fail_after_two_attempts(kb, db):
    llm = FakeLLM(["坏的", "还是坏的"])
    with pytest.raises(quiz.QuizError, match="出题失败"):
        quiz.generate("nginx", llm=llm, db_path=db)
    assert len(llm.calls) == 2  # 严格只试两次


# ---------- 工具入口与注册 ----------

def test_generate_quiz_tool_text(kb, db, monkeypatch):
    monkeypatch.setattr(quiz, "generate", lambda *a, **k: {
        "quiz_id": 7, "topic": "nginx", "difficulty": "中等", "qtype": "单选题",
        "question": "Q?", "options": ["1", "2", "3", "4"],
        "answer": "B", "explanation": "E", "source": "第5章.md"})
    text = quiz.generate_quiz("nginx")
    assert "#7" in text and "A. 1" in text and "[正确答案] B" in text
    assert "先只向学生展示" in text


def test_generate_quiz_tool_error_as_text(monkeypatch):
    def boom(*a, **k):
        raise quiz.QuizError("知识库中没有资料，无法出题")
    monkeypatch.setattr(quiz, "generate", boom)
    assert "无法出题" in quiz.generate_quiz("量子力学")


def test_registered_in_registry():
    names = [t["function"]["name"] for t in registry.TOOLS]
    assert "generate_quiz" in names
    assert registry.HANDLERS["generate_quiz"] is quiz.generate_quiz
    schema = next(t for t in registry.TOOLS
                  if t["function"]["name"] == "generate_quiz")
    props = schema["function"]["parameters"]["properties"]
    assert props["difficulty"]["enum"] == ["基础", "中等", "困难"]
    assert props["qtype"]["enum"] == ["单选题", "命令实操题"]


# ---------- REST API ----------

def test_api_quiz_generate_ok(monkeypatch):
    monkeypatch.setattr(main.quiz, "generate", lambda t, d, q: {
        "quiz_id": 1, "topic": t, "difficulty": d, "qtype": q,
        "question": "Q", "options": [], "answer": "ls",
        "explanation": "E", "source": "s.md"})
    r = TestClient(main.app).post(
        "/api/quiz/generate",
        json={"topic": "nginx", "qtype": "命令实操题"})
    assert r.status_code == 200
    assert r.json()["qtype"] == "命令实操题"
    assert r.json()["difficulty"] == "中等"  # 默认值


def test_api_quiz_generate_422(monkeypatch):
    def boom(*a):
        raise quiz.QuizError("知识库中没有该资料，无法出题")
    monkeypatch.setattr(main.quiz, "generate", boom)
    r = TestClient(main.app).post("/api/quiz/generate", json={"topic": "x"})
    assert r.status_code == 422
    assert "无法出题" in r.json()["detail"]


def test_generate_wraps_llm_network_error(kb, db):
    """审查修复项：LLM 网络层异常必须包装为 QuizError（REST 422 而非 500）。"""

    class DeadLLM:
        def complete(self, *a, **k):
            raise ConnectionError("network down")

    with pytest.raises(quiz.QuizError, match="暂时不可用"):
        quiz.generate("nginx", llm=DeadLLM(), db_path=db)
