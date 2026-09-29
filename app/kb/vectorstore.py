"""M09 向量库封装：ChromaDB 1.5.x 的唯一入口。

官方现行 API（docs.trychroma.com，2026-09 核查）：
- chromadb.PersistentClient(path=...)
- get_or_create_collection(name, configuration={"hnsw": {"space": "cosine"}})
  （configuration 为 1.x 官方写法，取代旧版 metadata={"hnsw:space": ...}）
- add / query / delete(where=...) / get

本模块不持有 embedding_function：向量一律由 M10 编码后显式传入，
避免 Chroma 拉取其默认 ONNX 模型。
"""
from app import config

_client = None
_collection = None


def _ensure_sqlite():
    """Chroma 需要 sqlite>=3.35；老系统(如 Rocky 8 的 3.26)按官方
    troubleshooting 方案用 pysqlite3-binary 顶替标准库 sqlite3。"""
    import sqlite3

    if sqlite3.sqlite_version_info < (3, 35, 0):
        try:
            __import__("pysqlite3")
            import sys

            sys.modules["sqlite3"] = sys.modules.pop("pysqlite3")
        except ImportError:
            pass  # 无 pysqlite3 时让 chromadb 自己报错，便于定位


def get_collection():
    global _client, _collection
    if _collection is None:
        _ensure_sqlite()
        import chromadb

        _client = chromadb.PersistentClient(path=config.CHROMA_DIR)
        _collection = _client.get_or_create_collection(
            name="course_kb",
            configuration={"hnsw": {"space": "cosine"}},
        )
    return _collection


def reset():
    """测试隔离/切换存储目录时重置单例。"""
    global _client, _collection
    _client = None
    _collection = None


def add(ids, embeddings, documents, metadatas):
    get_collection().add(
        ids=ids, embeddings=embeddings, documents=documents, metadatas=metadatas
    )


def query(embedding, k=5):
    """向量检索 Top-K -> [{text, meta, distance}]，distance 为 cosine 距离(越小越相似)。"""
    col = get_collection()
    if col.count() == 0:
        return []
    res = col.query(
        query_embeddings=[embedding],
        n_results=min(k, col.count()),
        include=["documents", "metadatas", "distances"],
    )
    hits = []
    for text, meta, dist in zip(
        res["documents"][0], res["metadatas"][0], res["distances"][0]
    ):
        hits.append({"text": text, "meta": meta or {}, "distance": dist})
    return hits


def delete_by_source(source):
    get_collection().delete(where={"source": source})


def list_sources():
    """[{source, chunks}] 按来源文件聚合。"""
    col = get_collection()
    if col.count() == 0:
        return []
    res = col.get(include=["metadatas"])
    counter = {}
    for meta in res["metadatas"]:
        src = (meta or {}).get("source", "未知")
        counter[src] = counter.get(src, 0) + 1
    return [{"source": s, "chunks": n} for s, n in sorted(counter.items())]


def count():
    return get_collection().count()
