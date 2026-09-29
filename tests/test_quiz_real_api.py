# -*- coding: utf-8 -*-
"""M12 真实 DeepSeek API 集成测试（用户要求：本地测试直连真实 key）。

无 LLM_API_KEY 环境变量时自动跳过（CI/无 key 环境不炸）。
取材片段用真实讲义原文注入（本地沙箱无向量库，不影响验证目标：
DeepSeek JSON 模式出题的真实稳定性与产物质量）。
"""
import os

import pytest

from app.llm import LLMClient
from app.tools import quiz, rag_search

pytestmark = pytest.mark.skipif(
    not os.getenv("LLM_API_KEY"), reason="需要真实 DeepSeek API Key"
)

REAL_MATERIAL = (
    "[来源: 第5章-Nginx服务部署.md 第1页] 反向代理服务器接收客户端请求后，"
    "通过 proxy_pass 指令把请求转发到后端真实服务器。改完配置后必须先做"
    "语法检测再平滑重载：nginx -t 检测语法，systemctl reload nginx 平滑重载，"
    "reload 只重载配置文件，主进程不退出，正在处理的连接不受影响。"
)
REAL_SOURCES = [{"source": "第5章-Nginx服务部署.md", "page": 1,
                 "excerpt": "proxy_pass", "score": 0.8}]


@pytest.fixture
def kb(monkeypatch):
    monkeypatch.setattr(rag_search, "search", lambda q: (REAL_MATERIAL, REAL_SOURCES))


@pytest.fixture
def db(tmp_path):
    return str(tmp_path / "quiz.db")


def test_real_choice_question(kb, db):
    q = quiz.generate("Nginx 反向代理", difficulty="中等",
                      qtype="单选题", llm=LLMClient(), db_path=db)
    assert q["quiz_id"] >= 1
    assert len(q["options"]) == 4
    assert q["answer"] in ("A", "B", "C", "D")
    assert len(q["question"]) >= 5
    assert len(q["explanation"]) >= 5
    print("\n[真实出题-单选]", q["question"], "| 答案:", q["answer"])


def test_real_practical_question(kb, db):
    q = quiz.generate("Nginx 配置重载", difficulty="基础",
                      qtype="命令实操题", llm=LLMClient(), db_path=db)
    assert q["options"] == []
    assert q["answer"].strip()
    print("\n[真实出题-实操]", q["question"], "| 参考:", q["answer"])
