"""M02 配置管理：唯一读取环境变量的模块。"""
import os

from dotenv import load_dotenv

load_dotenv()

LLM_BASE_URL = os.getenv("LLM_BASE_URL", "https://api.deepseek.com")
LLM_API_KEY = os.getenv("LLM_API_KEY", "")
# DeepSeek 官方 2026-09 现行模型名（旧名 deepseek-chat 已于 2026-07 弃用）
LLM_MODEL = os.getenv("LLM_MODEL", "deepseek-flash")
DB_PATH = os.getenv("DB_PATH", "data/tutor.db")
MAX_TOOL_ROUNDS = int(os.getenv("MAX_TOOL_ROUNDS", "5"))
HISTORY_LIMIT = int(os.getenv("HISTORY_LIMIT", "20"))

SYSTEM_PROMPT = (
    "你是 CloudOps Tutor，一名云计算运维课程的智能助教。"
    "面向高职学生，回答准确、简洁、循序渐进；涉及命令时给出示例并解释参数。"
    "当需要计算或查询当前时间时，使用提供的工具。"
)
