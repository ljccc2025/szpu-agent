from types import SimpleNamespace

from fastapi.testclient import TestClient

from app import main
from app.core import Agent


class FakeLLM:
    def complete(self, messages, tools=None):
        return SimpleNamespace(
            content="收到：" + messages[-1]["content"], tool_calls=None
        )


def _client(tmp_path, monkeypatch):
    monkeypatch.setattr(main, "agent", Agent(FakeLLM(), str(tmp_path / "t.db")))
    return TestClient(main.app)


def test_health(tmp_path, monkeypatch):
    client = _client(tmp_path, monkeypatch)
    r = client.get("/api/health")
    assert r.status_code == 200
    assert r.json()["status"] == "ok"


def test_chat_endpoint(tmp_path, monkeypatch):
    client = _client(tmp_path, monkeypatch)
    r = client.post("/api/chat", json={"session_id": "s1", "message": "你好"})
    assert r.status_code == 200
    assert r.json()["reply"] == "收到：你好"


def test_history_endpoint(tmp_path, monkeypatch):
    client = _client(tmp_path, monkeypatch)
    client.post("/api/chat", json={"session_id": "s1", "message": "你好"})
    r = client.get("/api/history/s1")
    assert r.status_code == 200
    assert len(r.json()["messages"]) == 2


def test_static_page_served(tmp_path, monkeypatch):
    client = _client(tmp_path, monkeypatch)
    r = client.get("/")
    assert r.status_code == 200
    assert "CloudOps Tutor" in r.text
