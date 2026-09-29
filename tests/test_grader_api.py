"""M13 批改 REST 层测试。"""
from fastapi.testclient import TestClient

from app import main, storage
from app.core import Agent


def _client(tmp_path, monkeypatch):
    db = str(tmp_path / "t.db")
    monkeypatch.setattr(main, "agent", Agent(None, db))
    return TestClient(main.app), db


def _mk_quiz(db, qtype="单选题", answer="A"):
    return storage.save_quiz(
        db, "Nginx 反向代理", "中等", qtype, "题干文字",
        '["转发请求","压缩响应","限流","缓存"]' if qtype == "单选题" else "[]",
        answer, "proxy_pass 用于转发请求。", "第5章-Nginx服务部署.md",
    )


def test_grade_endpoint_returns_score(tmp_path, monkeypatch):
    client, db = _client(tmp_path, monkeypatch)
    qid = _mk_quiz(db)
    r = client.post(f"/api/quiz/{qid}/grade", json={"student_answer": "A"})
    assert r.status_code == 200
    body = r.json()
    assert body["score"] == 100 and body["passed"] is True
    assert body["source"] == "第5章-Nginx服务部署.md"


def test_grade_endpoint_unknown_quiz_returns_422(tmp_path, monkeypatch):
    client, _ = _client(tmp_path, monkeypatch)
    r = client.post("/api/quiz/999999/grade", json={"student_answer": "A"})
    assert r.status_code == 422
    assert "不存在" in r.json()["detail"]


def test_grade_endpoint_rejects_empty_answer(tmp_path, monkeypatch):
    client, db = _client(tmp_path, monkeypatch)
    qid = _mk_quiz(db)
    r = client.post(f"/api/quiz/{qid}/grade", json={"student_answer": ""})
    assert r.status_code == 422


def test_attempts_endpoint_lists_all_and_wrong_only(tmp_path, monkeypatch):
    client, db = _client(tmp_path, monkeypatch)
    qid = _mk_quiz(db)
    client.post(f"/api/quiz/{qid}/grade", json={"student_answer": "A"})
    client.post(f"/api/quiz/{qid}/grade", json={"student_answer": "C"})

    all_rows = client.get("/api/attempts").json()["attempts"]
    assert len(all_rows) == 2

    wrong = client.get("/api/attempts?only_wrong=true").json()["attempts"]
    assert [r["student_answer"] for r in wrong] == ["C"]
