"""M20 多 Agent 批改流水线：出题官 -> 批改官 -> 讲解官三角色接力。

本模块**只做编排，不重写业务**：
  - 出题官 = 直接调用 M12 `quiz.generate`（已含 RAG 取材、JSON 校验重试、
    选项洗牌、答案不进上下文等一整套纪律，重写只会产生两套会漂移的逻辑）
  - 批改官 = 直接调用 M13 `grader.grade`
  - 讲解官 = 本模块**唯一新增**的角色

两阶段设计：「出题 -> 学生作答 -> 批改」中间是人工暂停，接口不可能一条
直线跑到底。带 topic 走阶段一，带 quiz_id + student_answer 走阶段二。

防幻觉纪律与全项目一致：讲解官检索不到资料就如实降级说明，绝不凭空讲，
与 rag_search 空结果拒答、quiz 无资料拒绝出题、planner 空错题本拒绝生成同源。
"""
from app import config
from app.llm import LLMClient
from app.tools import grader, quiz, rag_search

# 角色代号 -> 中文名，前端时间线直接用这里的名字，避免两处写死
ROLES = {
    "quizmaster": "出题官",
    "grader": "批改官",
    "explainer": "讲解官",
}

EXPLAINER_SYSTEM = (
    "你是云计算运维课程的讲解官。学生刚做完一道题并已被批改，"
    "请针对他的错误给出讲解。要求："
    "1) 只使用下面提供的课程资料，不得引入资料之外的内容；"
    "2) 必须注明出处（来源文件与页码）；"
    "3) 先点明错在哪，再讲正确的理解，最后给一句可操作的建议；"
    "4) 控制在 300 字以内，语气鼓励但不敷衍。"
)

NO_MATERIAL_TEMPLATE = (
    "知识库中没有检索到与「{topic}」相关的课程内容，"
    "无法给出有出处的讲解。请先上传该知识点的课件后重试。"
)

_llm = None


def _get_llm():
    """懒加载 LLM 客户端（与 planner/quiz/grader 同一套写法）。"""
    global _llm
    if _llm is None:
        _llm = LLMClient()
    return _llm


def explain(result, llm=None):
    """讲解官：拿批改结果做真实 RAG，产出带出处的针对性讲解。

    返回 (讲解文本, 出处列表)。检索为空时直接降级返回，**不调用 LLM**——
    既守住防幻觉纪律，也省掉一次无意义的 API 开销。
    """
    material, sources = rag_search.search(result["topic"])
    if not sources:
        return NO_MATERIAL_TEMPLATE.format(topic=result["topic"]), []

    user = (
        f"知识点：{result['topic']}\n"
        f"题型：{result['qtype']}\n"
        f"学生得分：{result['score']}/100\n"
        f"批改点评：{result['feedback']}\n"
        f"正确答案：{result['correct_answer']}\n\n"
        f"课程资料：\n{material}"
    )
    msg = (llm or _get_llm()).complete([
        {"role": "system", "content": EXPLAINER_SYSTEM},
        {"role": "user", "content": user},
    ])
    return (msg.content or "").strip(), sources


def run_quiz_stage(topic, difficulty="中等", qtype="单选题",
                   db_path=None, llm=None):
    """阶段一：出题官。产出 (事件名, 载荷)。"""
    yield "agent_start", {"role": "quizmaster", "name": ROLES["quizmaster"]}
    q = quiz.generate(topic, difficulty, qtype, llm=llm, db_path=db_path)
    # 与 M12 generate_quiz 同一条纪律：answer 与 explanation 绝不出服务端，
    # 否则前端按 F12 就能直接看到答案。
    yield "agent_output", {
        "role": "quizmaster",
        "quiz_id": q["quiz_id"],
        "topic": q["topic"],
        "difficulty": q["difficulty"],
        "qtype": q["qtype"],
        "question": q["question"],
        "options": q["options"],
        "source": q["source"],
    }
    yield "done", {"stage": "quiz", "quiz_id": q["quiz_id"]}


def run_grade_stage(quiz_id, student_answer, db_path=None, llm=None,
                    runner=None):
    """阶段二：批改官 -> 讲解官。"""
    yield "agent_start", {"role": "grader", "name": ROLES["grader"]}
    r = grader.grade(
        quiz_id, student_answer, llm=llm, db_path=db_path, runner=runner
    )
    yield "agent_output", {
        "role": "grader",
        "quiz_id": r["quiz_id"],
        "topic": r["topic"],
        "score": r["score"],
        "passed": r["passed"],
        "feedback": r["feedback"],
        "weak_points": r["weak_points"],
        "correct_answer": r["correct_answer"],
        "source": r["source"],
    }

    yield "agent_start", {"role": "explainer", "name": ROLES["explainer"]}
    text, sources = explain(r, llm=llm)
    yield "agent_output", {
        "role": "explainer", "explanation": text, "sources": sources,
    }
    yield "done", {
        "stage": "grade", "score": r["score"], "passed": r["passed"],
    }


def run(topic=None, difficulty="中等", qtype="单选题", quiz_id=None,
        student_answer=None, db_path=None, llm=None, runner=None):
    """流水线入口：带 quiz_id 走阶段二，否则走阶段一。

    领域异常（出题失败、题号不存在等）原文透传给前端，其余异常统一兜底成
    友好文案——与 Agent.chat_stream 同一套错误纪律。
    """
    try:
        if quiz_id is not None:
            yield from run_grade_stage(
                quiz_id, student_answer, db_path=db_path, llm=llm,
                runner=runner,
            )
        else:
            yield from run_quiz_stage(
                topic, difficulty, qtype, db_path=db_path, llm=llm,
            )
    except (quiz.QuizError, grader.GraderError) as err:
        yield "error", {"message": str(err)}
    except Exception:
        yield "error", {"message": "服务暂时繁忙，请稍后再试。"}
