"""M01 FastAPI 应用入口（FastAPI 0.141 现行 lifespan 模式）。"""
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from app import config, storage
from app.core import Agent
from app.llm import LLMClient


@asynccontextmanager
async def lifespan(_app: FastAPI):
    Path(config.DB_PATH).parent.mkdir(parents=True, exist_ok=True)
    yield


app = FastAPI(title="CloudOps Tutor", lifespan=lifespan)
agent = Agent(LLMClient())


class ChatRequest(BaseModel):
    session_id: str
    message: str


@app.get("/api/health")
def health():
    return {"status": "ok", "model": config.LLM_MODEL}


@app.post("/api/chat")
def chat(req: ChatRequest):
    return {"reply": agent.chat(req.session_id, req.message)}


@app.get("/api/history/{session_id}")
def history(session_id: str):
    return {"messages": storage.get_history(agent.db_path, session_id)}


_static = Path(__file__).resolve().parent.parent / "static"
app.mount("/", StaticFiles(directory=str(_static), html=True), name="static")
