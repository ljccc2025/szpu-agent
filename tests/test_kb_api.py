"""M08/M09 知识库管理 API 测试：上传 / 列表 / 删除（摄取与向量库打桩）。"""
from fastapi.testclient import TestClient

from app import main


def test_upload_txt_ok(monkeypatch):
    captured = {}

    def fake_ingest(path, source_name=None):
        captured["source"] = source_name
        return {"source": source_name, "chunks": 3}

    monkeypatch.setattr(main.kb_ingest, "ingest", fake_ingest)
    client = TestClient(main.app)
    r = client.post(
        "/api/kb/upload",
        files={"file": ("讲义.txt", "nginx 反向代理".encode("utf-8"), "text/plain")},
    )
    assert r.status_code == 200
    assert r.json() == {"source": "讲义.txt", "chunks": 3}
    assert captured["source"] == "讲义.txt"


def test_upload_rejects_bad_type(monkeypatch):
    client = TestClient(main.app)
    r = client.post(
        "/api/kb/upload",
        files={"file": ("virus.exe", b"MZ", "application/octet-stream")},
    )
    assert r.status_code == 400


def test_upload_parse_error_maps_422(monkeypatch):
    def boom(path, source_name=None):
        raise ValueError("坏文件")

    monkeypatch.setattr(main.kb_ingest, "ingest", boom)
    client = TestClient(main.app)
    r = client.post(
        "/api/kb/upload", files={"file": ("bad.pdf", b"%PDF-broken", "application/pdf")}
    )
    assert r.status_code == 422


def test_sources_and_delete(monkeypatch):
    monkeypatch.setattr(
        main.vectorstore,
        "list_sources",
        lambda: [{"source": "讲义.txt", "chunks": 3}],
    )
    deleted = []
    monkeypatch.setattr(main.vectorstore, "delete_by_source", deleted.append)

    client = TestClient(main.app)
    r = client.get("/api/kb/sources")
    assert r.status_code == 200
    assert r.json()["sources"][0]["source"] == "讲义.txt"

    r = client.delete("/api/kb/讲义.txt")
    assert r.status_code == 200
    assert deleted == ["讲义.txt"]
