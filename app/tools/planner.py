"""M14 错题本聚合与学习规划：SQL 统计 -> RAG 取出处 -> LLM 组织计划。

三段式的用意是把确定性与生成性分开：
- 薄弱知识点的排名与分数来自 SQL 聚合，模型改不了也编不出；
- 每个知识点的讲义出处来自真实 RAG 检索，不是模型杜撰；
- LLM 只负责把上面两样组织成自然语言计划，且被要求不得超出给定资料。

错题本为空时直接拒绝生成，与 rag_search 空结果拒答、
quiz 无资料拒绝出题保持同一套防幻觉纪律。
"""
import json

from app import config, storage
from app.tools import rag_search
from app.tools.grader import PASS_SCORE

DEFAULT_TOP_N = 5
MIN_DAYS = 1
MAX_DAYS = 30

# 示例 JSON 的花括号写成 {{ }}，整段要走 str.format()
_PLAN_PROMPT = (
    "你是云计算运维课程的学习规划老师。下面给出某学生的错题统计，"
    "以及每个薄弱知识点对应的课程讲义摘录。\n"
    "请为他制定一份 {days} 天的复习计划。\n"
    "要求：\n"
    "1. 每天聚焦一个知识点，错得多、平均分低的排在前面；\n"
    "2. 每天给出「复习重点」与「练习建议」，练习建议要具体可执行；\n"
    "3. 只能依据下面给出的讲义摘录，不得编造讲义内容或出处；\n"
    "4. 若薄弱知识点少于天数，可对同一知识点分阶段安排，但不要硬凑无关内容；\n"
    "5. 只输出一个严格合法的 json 对象，不要输出其他任何内容。\n"
    "EXAMPLE JSON OUTPUT:\n"
    '{{"daily_plan": [{{"day": 1, "topic": "知识点名", '
    '"focus": "复习重点", "practice": "练习建议"}}]}}\n'
    "daily_plan 必须恰好 {days} 项，day 从 1 起连续递增。\n\n"
    "学生错题统计：\n{stats}\n\n"
    "课程讲义摘录：\n{material}\n"
)

_llm = None


class PlannerError(Exception):
    """无法生成计划（错题本为空 / 天数非法 / 模型不可用）。"""


def _get_llm():
    """LLM 客户端懒加载单例；测试可通过 make_plan(llm=...) 注入。"""
    global _llm
    if _llm is None:
        from app.llm import LLMClient

        _llm = LLMClient()
    return _llm


def weak_topics(db_path=None, top_n=DEFAULT_TOP_N):
    """返回 Top-N 薄弱知识点，附合并去重后的细粒度标签。"""
    db_path = db_path or config.DB_PATH
    rows = storage.aggregate_weak_topics(
        db_path, max_score=PASS_SCORE, limit=top_n
    )
    for row in rows:
        labels = []
        for raw in storage.weak_point_rows(
            db_path, row["topic"], max_score=PASS_SCORE
        ):
            try:
                parsed = json.loads(raw or "[]")
            except (json.JSONDecodeError, TypeError):
                continue  # 坏数据不该让整份计划挂掉
            if not isinstance(parsed, list):
                continue
            for label in parsed:
                if isinstance(label, str) and label not in labels:
                    labels.append(label)
        row["labels"] = labels
    return rows


def validate_plan(data, days):
    """校验 LLM 产出的计划结构；合格返回 None，否则返回原因。"""
    if not isinstance(data, dict):
        return "输出不是 JSON 对象"
    plan = data.get("daily_plan")
    if not isinstance(plan, list):
        return "daily_plan 缺失或不是数组"
    if len(plan) != days:
        return f"daily_plan 应有 {days} 项，实际 {len(plan)} 项"
    for i, item in enumerate(plan, start=1):
        if not isinstance(item, dict):
            return f"第 {i} 项不是对象"
        if item.get("day") != i:
            return f"第 {i} 项的 day 应为 {i}"
        for key in ("topic", "focus", "practice"):
            value = item.get(key)
            if not isinstance(value, str) or not value.strip():
                return f"第 {i} 项的 {key} 缺失或为空"
    return None


def make_plan(days=7, db_path=None, llm=None, top_n=DEFAULT_TOP_N):
    """生成复习计划（技术文档 M14 对外 API）。

    三段式：SQL 统计 -> RAG 取真实出处 -> LLM 仅做组织。
    """
    if not isinstance(days, int) or isinstance(days, bool):
        raise PlannerError("天数必须是整数")
    if not MIN_DAYS <= days <= MAX_DAYS:
        raise PlannerError(f"天数需在 {MIN_DAYS}-{MAX_DAYS} 之间")

    db_path = db_path or config.DB_PATH
    topics = weak_topics(db_path=db_path, top_n=top_n)
    if not topics:
        raise PlannerError(
            "还没有错题记录，无法生成针对性复习计划。"
            "先到「练习与批改」做几道题吧。"
        )

    # 第二段：每个薄弱知识点做一次真实检索，出处不是模型编的
    blocks, sources = [], []
    for row in topics:
        text, hits = rag_search.search(row["topic"])
        blocks.append(f"【{row['topic']}】\n{text[:800]}")
        for hit in hits:
            if hit["source"] not in sources:
                sources.append(hit["source"])

    stats = "\n".join(
        "- {topic}：做过 {total} 题，错 {wrong} 题，平均 {avg} 分{extra}".format(
            topic=r["topic"], total=r["total_count"], wrong=r["wrong_count"],
            avg=r["avg_score"],
            extra=("；薄弱点：" + "、".join(r["labels"])) if r["labels"] else "",
        )
        for r in topics
    )
    prompt = _PLAN_PROMPT.format(
        days=days, stats=stats, material="\n\n".join(blocks)
    )

    llm = llm or _get_llm()
    last_reason = "未知原因"
    for _ in range(2):  # 首次 + 重试 1 次（与 M12/M13 一致）
        try:
            msg = llm.complete(
                [{"role": "user", "content": prompt}],
                response_format={"type": "json_object"},
            )
        except Exception as err:
            raise PlannerError(
                f"学习规划服务暂时不可用（{err.__class__.__name__}），请稍后再试"
            ) from err
        content = (getattr(msg, "content", None) or "").strip()
        if not content:
            last_reason = "模型返回空内容"
            continue
        try:
            data = json.loads(content)
        except json.JSONDecodeError:
            last_reason = "JSON 解析失败"
            continue
        reason = validate_plan(data, days)
        if reason is None:
            return {
                "days": days,
                "weak_topics": topics,
                "daily_plan": data["daily_plan"],
                "sources": sources,
            }
        last_reason = reason
    raise PlannerError(f"复习计划生成失败（{last_reason}），请重试一次")


def make_study_plan(days=7):
    """Agent 工具入口：返回给 LLM 转述的 markdown 计划（registry 调用）。"""
    try:
        r = make_plan(int(days))
    except (PlannerError, ValueError, TypeError) as err:
        return f"暂时无法生成复习计划：{err}"
    lines = [f"已根据错题本生成 {r['days']} 天复习计划。", "", "薄弱知识点排名："]
    lines += [
        "{i}. {topic}（错 {wrong}/{total} 题，平均 {avg} 分）".format(
            i=i, topic=t["topic"], wrong=t["wrong_count"],
            total=t["total_count"], avg=t["avg_score"])
        for i, t in enumerate(r["weak_topics"], start=1)
    ]
    lines.append("")
    for item in r["daily_plan"]:
        lines.append(f"第 {item['day']} 天 · {item['topic']}")
        lines.append(f"  复习重点：{item['focus']}")
        lines.append(f"  练习建议：{item['practice']}")
    if r["sources"]:
        lines.append("")
        lines.append("参考讲义：" + "、".join(r["sources"]))
    return "\n".join(lines)
