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
from app.tools import quiz


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
