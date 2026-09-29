"""M07 RAG 检索工具：查询向量化 -> Top-K -> 距离阈值过滤 -> 带出处上下文。

空结果时返回明确的防幻觉声明（技术文档 M07 要求）。
同时缓存本轮结构化出处（source/page/excerpt/score），
由 M05 核心循环取走并随 /api/chat 响应返回给前端出处卡。
"""
from app import config
from app.kb import embedder, vectorstore

_last_sources = []

NO_RESULT_TEXT = (
    "知识库中没有检索到与该问题相关的课程内容。"
    "请如实告知学生：这个问题超出了当前课程资料的范围，"
    "并明确说明你无法基于课件作答，不要编造出处或内容。"
)


def pop_last_sources():
    """取走并清空本轮出处缓存（core 循环在每次工具调用后立即调用）。"""
    global _last_sources
    out, _last_sources = _last_sources, []
    return out


def search(query: str) -> str:
    global _last_sources
    vector = embedder.encode([query])[0]
    hits = vectorstore.query(vector, k=config.RAG_TOP_K)
    kept = [h for h in hits if h["distance"] <= config.RAG_MAX_DISTANCE]

    if not kept:
        _last_sources = []
        return NO_RESULT_TEXT

    _last_sources = [
        {
            "source": h["meta"].get("source", "未知"),
            "page": h["meta"].get("page", 0),
            "excerpt": h["text"][:80],
            "score": round(1 - h["distance"], 3),
        }
        for h in kept
    ]
    blocks = [
        f"[来源: {h['meta'].get('source', '未知')} 第{h['meta'].get('page', '?')}页] {h['text']}"
        for h in kept
    ]
    return (
        "以下是课程知识库中检索到的相关内容，回答时请注明出处（来源文件与页码）：\n\n"
        + "\n\n".join(blocks)
    )
