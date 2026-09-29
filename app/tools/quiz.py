"""M12 智能出题工具：RAG 取材 -> JSON 模式生成 -> 校验重试 -> 落库。

防幻觉底线：知识库检索不到该知识点的课程资料就拒绝出题，
保证每道题都能从讲义中找到依据（技术文档 M12）。

DeepSeek JSON 模式官方要求（api-docs.deepseek.com/guides/json_mode，2026-09 核查）：
1) response_format={"type": "json_object"}；
2) prompt 必须包含 "json" 字样并给出输出示例；
3) 合理设置 max_tokens 防截断；
4) 官方明示可能偶发返回空 content —— 与解析失败一样计入重试。
"""
import json

from app import config, storage
from app.tools import rag_search

VALID_DIFFICULTIES = ("基础", "中等", "困难")
VALID_QTYPES = ("单选题", "命令实操题")

_FORMAT_HINTS = {
    "单选题": (
        'EXAMPLE JSON OUTPUT:\n'
        '{"question": "题干文字", '
        '"options": ["选项一内容", "选项二内容", "选项三内容", "选项四内容"], '
        '"answer": "A", "explanation": "解析文字"}\n'
        "options 必须恰好 4 项且不带 A./B. 前缀，answer 只能是 A/B/C/D 之一。"
    ),
    "命令实操题": (
        'EXAMPLE JSON OUTPUT:\n'
        '{"question": "请写出完成某任务的 Linux 命令", '
        '"options": [], "answer": "参考命令", "explanation": "解析文字"}\n'
        "options 必须是空数组，answer 为一条可执行的参考命令。"
    ),
}

_PROMPT_TEMPLATE = (
    "你是云计算运维课程出题专家。请基于下面给定的课程资料片段，"
    "出一道{difficulty}难度的{qtype}，考察知识点「{topic}」。\n"
    "要求：\n"
    "1. 题目必须能从资料片段中找到依据，严禁超出资料范围；\n"
    "2. 只输出一个严格合法的 json 对象，不要输出其他任何内容；\n"
    "{format_hint}\n\n"
    "课程资料片段：\n{material}"
)

_llm = None


class QuizError(Exception):
    """出题失败（无资料 / 参数非法 / 生成两次仍不合格）。"""


def _get_llm():
    """LLM 客户端懒加载单例；测试可通过 generate(llm=...) 注入。"""
    global _llm
    if _llm is None:
        from app.llm import LLMClient

        _llm = LLMClient()
    return _llm


def validate_payload(data, qtype):
    """校验模型产出；合格返回 None，否则返回原因（用于重试与测试）。"""
    if not isinstance(data, dict):
        return "输出不是 JSON 对象"
    for key in ("question", "answer", "explanation"):
        value = data.get(key)
        if not isinstance(value, str) or not value.strip():
            return f"字段 {key} 缺失或为空"
    options = data.get("options")
    if qtype == "单选题":
        if not isinstance(options, list) or len(options) != 4:
            return "单选题必须恰好 4 个选项"
        if not all(isinstance(o, str) and o.strip() for o in options):
            return "选项必须是非空文本"
        if data["answer"].strip().upper() not in ("A", "B", "C", "D"):
            return "单选题 answer 必须是 A/B/C/D"
    else:
        if options not in (None, []):
            return "命令实操题 options 必须为空数组"
        data["options"] = []
    return None


def generate(topic, difficulty="中等", qtype="单选题", llm=None, db_path=None):
    """出题主流程，返回含 quiz_id 的完整题目 dict（技术文档 M12 对外 API）。"""
    topic = (topic or "").strip()
    if not topic:
        raise QuizError("请告诉我要考察哪个知识点，例如：Nginx 反向代理")
    if difficulty not in VALID_DIFFICULTIES:
        raise QuizError(f"难度只支持：{'/'.join(VALID_DIFFICULTIES)}")
    if qtype not in VALID_QTYPES:
        raise QuizError(f"题型只支持：{'/'.join(VALID_QTYPES)}")

    material, sources = rag_search.search(topic)
    if not sources:
        raise QuizError(
            f"知识库中没有「{topic}」相关的课程资料，无法出题。"
            "请先上传对应课件，或换一个课程内的知识点。"
        )

    prompt = _PROMPT_TEMPLATE.format(
        difficulty=difficulty,
        qtype=qtype,
        topic=topic,
        format_hint=_FORMAT_HINTS[qtype],
        material=material,
    )
    llm = llm or _get_llm()
    last_reason = "未知原因"
    data = None
    for _ in range(2):  # 首次 + 重试 1 次（技术文档 M12）
        msg = llm.complete(
            [{"role": "user", "content": prompt}],
            response_format={"type": "json_object"},
        )
        content = (getattr(msg, "content", None) or "").strip()
        if not content:
            last_reason = "模型返回空内容"  # DeepSeek 官方明示的偶发情况
            continue
        try:
            candidate = json.loads(content)
        except json.JSONDecodeError:
            last_reason = "JSON 解析失败"
            continue
        reason = validate_payload(candidate, qtype)
        if reason is None:
            data = candidate
            break
        last_reason = reason
    if data is None:
        raise QuizError(f"出题失败（{last_reason}），请重试一次")

    answer = data["answer"].strip()
    if qtype == "单选题":
        answer = answer.upper()
    source = sources[0]["source"]
    quiz_id = storage.save_quiz(
        db_path or config.DB_PATH,
        topic, difficulty, qtype,
        data["question"].strip(),
        json.dumps(data["options"], ensure_ascii=False),
        answer,
        data["explanation"].strip(),
        source,
    )
    return {
        "quiz_id": quiz_id,
        "topic": topic,
        "difficulty": difficulty,
        "qtype": qtype,
        "question": data["question"].strip(),
        "options": data["options"],
        "answer": answer,
        "explanation": data["explanation"].strip(),
        "source": source,
    }


def generate_quiz(topic, difficulty="中等", qtype="单选题"):
    """Agent 工具入口：返回给 LLM 转述的文本（registry 调用）。"""
    try:
        q = generate(topic, difficulty, qtype)
    except QuizError as err:
        return str(err)
    lines = [
        f"出题成功（题号 #{q['quiz_id']}，取材：{q['source']}）",
        f"【{q['difficulty']}·{q['qtype']}】{q['question']}",
    ]
    lines += [f"{chr(65 + i)}. {opt}" for i, opt in enumerate(q["options"])]
    lines.append(f"[正确答案] {q['answer']}")
    lines.append(f"[解析] {q['explanation']}")
    lines.append(
        "注意：请先只向学生展示题号、题目与选项，等学生作答后再公布答案和解析。"
    )
    return "\n".join(lines)
