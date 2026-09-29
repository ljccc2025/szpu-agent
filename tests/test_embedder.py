"""M10 嵌入服务测试：单例懒加载 + 批量编码（模型用假实现注入，不下载真模型）。"""
from app.kb import embedder


class FakeVector(list):
    def tolist(self):
        return list(self)


class FakeModel:
    def __init__(self):
        self.calls = 0

    def encode(self, texts, batch_size=32, normalize_embeddings=True):
        self.calls += 1
        assert normalize_embeddings is True
        return [FakeVector([float(len(t)), 0.0]) for t in texts]


def test_encode_empty_returns_empty(monkeypatch):
    monkeypatch.setattr(embedder, "get_model", lambda: FakeModel())
    assert embedder.encode([]) == []


def test_encode_batch(monkeypatch):
    fake = FakeModel()
    monkeypatch.setattr(embedder, "get_model", lambda: fake)
    vecs = embedder.encode(["你好", "nginx 配置"])
    assert vecs == [[2.0, 0.0], [8.0, 0.0]]
    assert isinstance(vecs[0], list)


def test_model_singleton(monkeypatch):
    created = []

    class FakeST:
        def __init__(self, name):
            created.append(name)

    import sys
    import types

    fake_module = types.SimpleNamespace(SentenceTransformer=FakeST)
    monkeypatch.setitem(sys.modules, "sentence_transformers", fake_module)
    monkeypatch.setattr(embedder, "_model", None)
    m1 = embedder.get_model()
    m2 = embedder.get_model()
    assert m1 is m2
    assert len(created) == 1
    monkeypatch.setattr(embedder, "_model", None)
