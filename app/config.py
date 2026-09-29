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

# --- M07-M10 RAG 知识库 ---
CHROMA_DIR = os.getenv("CHROMA_DIR", "data/chroma")
EMBED_MODEL = os.getenv("EMBED_MODEL", "BAAI/bge-small-zh-v1.5")
RAG_TOP_K = int(os.getenv("RAG_TOP_K", "5"))
# cosine 距离阈值：小于该值视为相关（技术文档 M07: distance<0.6）
RAG_MAX_DISTANCE = float(os.getenv("RAG_MAX_DISTANCE", "0.6"))

# --- M11 沙箱执行 ---
SANDBOX_IMAGE = os.getenv("SANDBOX_IMAGE", "alpine:3.24")
SANDBOX_TIMEOUT = int(os.getenv("SANDBOX_TIMEOUT", "10"))
SANDBOX_MEM = os.getenv("SANDBOX_MEM", "512m")
SANDBOX_CPU = float(os.getenv("SANDBOX_CPU", "0.5"))

SYSTEM_PROMPT = (
    "你是 CloudOps Tutor，一名云计算运维课程的智能助教。"
    "面向高职学生，回答准确、简洁、循序渐进；涉及命令时给出示例并解释参数。"
    "当学生询问课程知识点、概念或配置方法时，优先调用 rag_search 检索课程知识库，"
    "并在回答中注明出处（来源文件与页码）；若检索不到相关内容，必须如实说明"
    "该问题超出课程资料范围，严禁编造出处。"
    "当学生要求执行、演示或验证 Linux 命令时，调用 run_command 在安全沙箱中真实执行，"
    "并结合输出讲解；命令被安全策略拦截时，向学生解释该命令的危险性。"
    "当学生要求出题、练习或测验时，调用 generate_quiz 出题；出题后先只展示题号、"
    "题目与选项，等学生作答后再公布正确答案与解析；知识库没有相关资料时如实告知无法出题。"
    "当需要计算或查询当前时间时，使用对应工具。"
)
