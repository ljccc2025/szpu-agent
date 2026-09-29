"""M09 向量库测试：真实 ChromaDB 1.5.x 持久化实例（临时目录隔离）。"""
import importlib.util

import pytest

from app import config
from app.kb import vectorstore

pytestmark = pytest.mark.skipif(
    importlib.util.find_spec("chromadb") is None, reason="chromadb 未安装"
)


@pytest.fixture()
def store(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "CHROMA_DIR", str(tmp_path / "chroma"))
    vectorstore.reset()
    yield vectorstore
    vectorstore.reset()


def _vec(x, y):
    return [x, y]


def test_add_and_query(store):
    store.add(
        ids=["a", "b"],
        embeddings=[_vec(1.0, 0.0), _vec(0.0, 1.0)],
        documents=["nginx 反向代理", "docker 数据卷"],
        metadatas=[
            {"source": "ch5.pdf", "page": 47, "chunk_id": "a"},
            {"source": "ch8.pdf", "page": 12, "chunk_id": "b"},
        ],
    )
    hits = store.query(_vec(1.0, 0.0), k=2)
    assert len(hits) == 2
    assert hits[0]["text"] == "nginx 反向代理"
    assert hits[0]["meta"]["source"] == "ch5.pdf"
    assert hits[0]["distance"] < hits[1]["distance"]


def test_query_empty_collection(store):
    assert store.query(_vec(1.0, 0.0), k=5) == []


def test_delete_by_source_and_list_sources(store):
    store.add(
        ids=["a", "b", "c"],
        embeddings=[_vec(1, 0), _vec(0, 1), _vec(1, 1)],
        documents=["x", "y", "z"],
        metadatas=[
            {"source": "f1.pdf", "page": 1, "chunk_id": "a"},
            {"source": "f1.pdf", "page": 2, "chunk_id": "b"},
            {"source": "f2.md", "page": 1, "chunk_id": "c"},
        ],
    )
    assert store.list_sources() == [
        {"source": "f1.pdf", "chunks": 2},
        {"source": "f2.md", "chunks": 1},
    ]
    store.delete_by_source("f1.pdf")
    assert store.count() == 1
    assert store.list_sources() == [{"source": "f2.md", "chunks": 1}]
