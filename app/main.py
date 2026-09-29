"""M01 FastAPI 应用入口（FastAPI 0.141 现行 lifespan 模式）。"""
import os
import shutil
import tempfile
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, File, HTTPException, UploadFile
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from app import config, storage
from app.core import Agent
from app.kb import ingest as kb_ingest
from app.kb import vectorstore
from app.llm import LLMClient
from app.tools import grader, planner, quiz


@asynccontextmanager
async def lifespan(_app: FastAPI):
    Path(config.DB_PATH).parent.mkdir(parents=True, exist_ok=True)
    yield


app = FastAPI(title="CloudOps Tutor", lifespan=lifespan)
agent = Agent(LLMClient())


class ChatRequest(BaseModel):
    session_id: str
    message: str


class QuizRequest(BaseModel):
    # max_length：审查修复项，防超长知识点注入 Prompt
    topic: str = Field(min_length=1, max_length=50)
    difficulty: str = "中等"
    qtype: str = "单选题"
    # False 时响应剥离答案与解析（审查修复项：练习页 F12 不可见答案）
    with_answer: bool = True


class GradeRequest(BaseModel):
    # max_length 与 grader.MAX_ANSWER_LEN 对齐，超长在入口就拒绝
    student_answer: str = Field(min_length=1, max_length=500)


class PlanRequest(BaseModel):
    # 与 planner.MIN_DAYS / MAX_DAYS 对齐，越界在入口就拒绝
    days: int = Field(default=7, ge=1, le=30)


@app.get("/api/health")
def health():
    return {"status": "ok", "model": config.LLM_MODEL}


@app.post("/api/chat")
def chat(req: ChatRequest):
    # M07 起返回 {"reply": ..., "sources": [...]}
    return agent.chat(req.session_id, req.message)


@app.get("/api/history/{session_id}")
def history(session_id: str):
    return {
        "messages": storage.get_history(
            agent.db_path, session_id, limit=config.HISTORY_LIMIT
        )
    }


# --- M12 智能出题（练习页 M19 与调试用；对话场景走 generate_quiz 工具） ---


@app.post("/api/quiz/generate")
def quiz_generate(req: QuizRequest):
    try:
        result = quiz.generate(req.topic, req.difficulty, req.qtype)
    except quiz.QuizError as err:
        # 参数非法/知识库无资料/两次生成仍不合格：语义化 422
        raise HTTPException(status_code=422, detail=str(err))
    if not req.with_answer:
        # 练习页模式：答案与解析留在服务端（M13 批改时按 quiz_id 取用）
        result = {k: v for k, v in result.items()
                  if k not in ("answer", "explanation")}
    return result


# --- M13 智能批改与错题本 ---


@app.post("/api/quiz/{quiz_id}/grade")
def quiz_grade(quiz_id: int, req: GradeRequest):
    try:
        return grader.grade(quiz_id, req.student_answer,
                            db_path=agent.db_path)
    except grader.GraderError as err:
        # 题号不存在/答案为空/沙箱或模型不可用：语义化 422
        raise HTTPException(status_code=422, detail=str(err))


@app.get("/api/attempts")
def attempts(only_wrong: bool = False):
    """作答记录；only_wrong=true 时只返回错题（score < PASS_SCORE）。"""
    return {
        "attempts": storage.list_attempts(
            agent.db_path,
            max_score=grader.PASS_SCORE if only_wrong else None,
        )
    }


@app.post("/api/plan")
def study_plan(req: PlanRequest):
    """M14 根据错题本生成复习计划。"""
    try:
        return planner.make_plan(req.days, db_path=agent.db_path)
    except planner.PlannerError as err:
        # 错题本为空/天数非法/模型不可用：语义化 422
        raise HTTPException(status_code=422, detail=str(err))


# --- M08-M09 知识库管理 ---


@app.post("/api/kb/upload")
async def kb_upload(file: UploadFile = File(...)):
    suffix = Path(file.filename or "").suffix.lower()
    if suffix not in kb_ingest.ALLOWED_SUFFIXES:
        raise HTTPException(status_code=400, detail="仅支持 PDF / TXT / MD 文件")
    with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as tmp:
        shutil.copyfileobj(file.file, tmp)
        tmp_path = tmp.name
    try:
        result = kb_ingest.ingest(tmp_path, source_name=file.filename)
    except Exception as err:
        raise HTTPException(status_code=422, detail=f"文件解析失败: {err}") from err
    finally:
        os.unlink(tmp_path)
    return result


@app.get("/api/kb/sources")
def kb_sources():
    return {"sources": vectorstore.list_sources()}


@app.delete("/api/kb/{source}")
def kb_delete(source: str):
    vectorstore.delete_by_source(source)
    return {"deleted": source}


_static = Path(__file__).resolve().parent.parent / "static"
app.mount("/", StaticFiles(directory=str(_static), html=True), name="static")
