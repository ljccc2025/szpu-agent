"""M08 摄取管道测试：清洗 / 中文感知切块 / 提取 / 入库元数据。"""
import pytest

from app.kb import ingest


# ---------- clean_text ----------

def test_clean_text_normalizes():
    raw = "第一行\r\n第二行\t\t多空格   压缩\n\n\n\n第三行  "
    out = ingest.clean_text(raw)
    assert "\r" not in out and "\t" not in out
    assert "\n\n\n" not in out
    assert out.endswith("第三行")


# ---------- chunk_text ----------

def test_short_text_single_chunk():
    assert ingest.chunk_text("短文本。", size=100, overlap=10) == ["短文本。"]


def test_chunks_break_at_punctuation():
    text = ("云计算是一种按需交付的模式。" * 10)[:200]
    chunks = ingest.chunk_text(text, size=60, overlap=10)
    # 除最后一块外，每块都应结束在句号处（中文标点感知）
    for piece in chunks[:-1]:
        assert piece.endswith("。")


def test_chunks_overlap():
    text = "a" * 300  # 无标点强制硬切
    chunks = ingest.chunk_text(text, size=100, overlap=20)
    assert len(chunks) >= 3
    total = sum(len(c) for c in chunks)
    assert total > 300  # 有重叠所以总长大于原文


def test_chunk_coverage_no_loss():
    text = "第一段内容。第二段内容！第三段内容？第四段内容；第五段收尾" * 5
    chunks = ingest.chunk_text(text, size=50, overlap=8)
    assert "".join(chunks[:1])[0] == text[0]
    assert chunks[-1].endswith(text[-1])


# ---------- extract_pages ----------

def test_extract_txt(tmp_path):
    f = tmp_path / "note.txt"
    f.write_text("nginx 反向代理笔记", encoding="utf-8")
    assert ingest.extract_pages(str(f)) == [(1, "nginx 反向代理笔记")]


def test_extract_unsupported(tmp_path):
    f = tmp_path / "evil.exe"
    f.write_bytes(b"MZ")
    with pytest.raises(ValueError):
        ingest.extract_pages(str(f))


# ---------- ingest ----------

def test_ingest_metadata_and_overwrite(tmp_path, monkeypatch):
    added = {}
    deleted = []

    monkeypatch.setattr(
        ingest.embedder, "encode", lambda texts: [[0.1, 0.2]] * len(texts)
    )
    monkeypatch.setattr(
        ingest.vectorstore,
        "add",
        lambda ids, embeddings, documents, metadatas: added.update(
            ids=ids, docs=documents, metas=metadatas
        ),
    )
    monkeypatch.setattr(
        ingest.vectorstore, "delete_by_source", lambda s: deleted.append(s)
    )

    f = tmp_path / "讲义.md"
    f.write_text("反向代理的核心是 proxy_pass 指令。" * 40, encoding="utf-8")
    result = ingest.ingest(str(f))

    assert result["source"] == "讲义.md"
    assert result["chunks"] == len(added["docs"]) > 1
    assert deleted == ["讲义.md"]  # 覆盖式写入：先删同名来源
    meta = added["metas"][0]
    assert meta["source"] == "讲义.md" and meta["page"] == 1
    assert meta["chunk_id"].startswith("讲义.md::p1::c")


def test_ingest_empty_file(tmp_path, monkeypatch):
    monkeypatch.setattr(ingest.vectorstore, "delete_by_source", lambda s: None)
    f = tmp_path / "empty.txt"
    f.write_text("", encoding="utf-8")
    assert ingest.ingest(str(f)) == {"source": "empty.txt", "chunks": 0}
