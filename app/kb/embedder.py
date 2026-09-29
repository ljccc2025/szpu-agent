"""M10 嵌入模型服务：bge-small-zh-v1.5 进程内单例 + 批量编码。

sentence-transformers 6.x（2026-08 官方现行版）：
encode(texts, batch_size=, normalize_embeddings=True) 返回 numpy 数组。
归一化后向量配合 ChromaDB cosine 空间使用。
模型懒加载：首次调用约 3 秒，之后毫秒级；测试环境可整体 monkeypatch。
"""
from app import config

_model = None


def get_model():
    """进程内单例；重库放函数内 import，无 sentence-transformers 的环境也能导入本模块。"""
    global _model
    if _model is None:
        from sentence_transformers import SentenceTransformer

        _model = SentenceTransformer(config.EMBED_MODEL)
    return _model


def encode(texts):
    """批量编码文本 -> list[list[float]]（已 L2 归一化）。"""
    texts = list(texts)
    if not texts:
        return []
    vectors = get_model().encode(texts, batch_size=32, normalize_embeddings=True)
    return [v.tolist() for v in vectors]
