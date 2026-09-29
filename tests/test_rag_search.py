"""M07 RAG 检索工具测试：阈值过滤 / 防幻觉声明 / 出处格式与缓存。"""
from app import config
from app.tools import rag_search


def _hit(text, source, page, distance):
    return {
        "text": text,
        "meta": {"source": source, "page": page, "chunk_id": "x"},
        "distance": distance,
    }


def _patch(monkeypatch, hits):
    monkeypatch.setattr(rag_search.embedder, "encode", lambda texts: [[0.1, 0.2]])
    monkeypatch.setattr(rag_search.vectorstore, "query", lambda vec, k=5: hits)


def test_empty_result_returns_no_hallucination_text(monkeypatch):
    _patch(monkeypatch, [])
    out = rag_search.search("量子力学")
    assert out == rag_search.NO_RESULT_TEXT
    assert rag_search.pop_last_sources() == []


def test_distance_threshold_filters(monkeypatch):
    _patch(
        monkeypatch,
        [
            _hit("相关内容", "ch5.pdf", 47, 0.30),
            _hit("不相关内容", "ch9.pdf", 3, 0.95),
        ],
    )
    monkeypatch.setattr(config, "RAG_MAX_DISTANCE", 0.6)
    out = rag_search.search("nginx")
    assert "相关内容" in out and "不相关内容" not in out


def test_all_filtered_is_no_result(monkeypatch):
    _patch(monkeypatch, [_hit("远", "a.pdf", 1, 0.99)])
    monkeypatch.setattr(config, "RAG_MAX_DISTANCE", 0.6)
    assert rag_search.search("异次元") == rag_search.NO_RESULT_TEXT


def test_output_format_and_sources_cache(monkeypatch):
    _patch(monkeypatch, [_hit("proxy_pass 指令说明" * 20, "第5章.pdf", 47, 0.20)])
    out = rag_search.search("反向代理")
    assert "[来源: 第5章.pdf 第47页]" in out

    sources = rag_search.pop_last_sources()
    assert len(sources) == 1
    s = sources[0]
    assert s["source"] == "第5章.pdf" and s["page"] == 47
    assert len(s["excerpt"]) <= 80
    assert s["score"] == 0.8
    # 取走后清空
    assert rag_search.pop_last_sources() == []
