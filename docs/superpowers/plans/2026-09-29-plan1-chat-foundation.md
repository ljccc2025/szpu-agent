# CloudOps Tutor 计划 1：多轮对话地基 实现计划

> **面向 AI 代理的工作者：** 必需子技能：使用 superpowers:subagent-driven-development（推荐）或 superpowers:executing-plans 逐任务实现此计划。步骤使用复选框（`- [ ]`）语法来跟踪进度。

**目标：** 跑通 FastAPI 后端 + 浏览器聊天页的多轮对话（含 SQLite 历史持久化），为后续 RAG 与工具调用打地基。

**架构：** 浏览器单页（Vue3 CDN 版，无构建链）通过 POST /api/chat 与后端交互；后端从 SQLite 读取会话历史、拼装 messages、调用 OpenAI 兼容 API 生成回复并落库。Agent 核心与 LLM 客户端解耦，测试全部用 FakeLLM 注入，不依赖真实 API。

**技术栈：** Python 3.10+、FastAPI、uvicorn、openai SDK、sqlite3（标准库）、pytest、httpx；前端 Vue3 + Element Plus（CDN 引入）

**计划拆分说明：** 本规格共 4 份计划。计划 1=本文件（多轮对话）；计划 2=RAG 知识库；计划 3=工具调用（沙箱/出题/批改）；计划 4=打磨（SSE 流式、LLM 重试、可选多 Agent）。SSE 流式与 API 重试特意推迟到计划 4，本计划用同步 JSON 返回。

---

## 文件结构

```
app/
  __init__.py        # 空文件，标记包
  config.py          # 环境变量配置（唯一读 env 的地方）
  storage.py         # SQLite 消息读写（唯一碰数据库的地方）
  llm.py             # OpenAI 兼容客户端封装 + messages 拼装
  core.py            # Agent 编排：历史 -> LLM -> 落库
  main.py            # FastAPI 路由 + 静态文件挂载
static/
  index.html         # Vue3 聊天页（单文件，CDN 引入）
tests/
  __init__.py
  test_storage.py
  test_llm.py
  test_core.py
  test_api.py
requirements.txt
.env.example
.gitignore
```

---

### 任务 0：项目骨架与依赖

**文件：**
- 创建：`requirements.txt`、`.env.example`、`.gitignore`、`app/__init__.py`、`tests/__init__.py`

- [ ] **步骤 1：创建文件**

`requirements.txt`：

```
fastapi
uvicorn[standard]
openai
python-dotenv
pytest
httpx
```

`.env.example`：

```
LLM_BASE_URL=https://api.deepseek.com
LLM_API_KEY=在这里填你的key
LLM_MODEL=deepseek-chat
DB_PATH=data/tutor.db
```

`.gitignore`：

```
.env
data/
__pycache__/
.venv/
```

`app/__init__.py` 与 `tests/__init__.py` 均为空文件。

- [ ] **步骤 2：安装依赖并验证**

运行：`python -m venv .venv && source .venv/Scripts/activate && pip install -r requirements.txt`
预期：安装成功无报错（Windows Git Bash 下虚拟环境激活路径是 `.venv/Scripts/activate`）。

- [ ] **步骤 3：Commit**

```bash
git add requirements.txt .env.example .gitignore app/__init__.py tests/__init__.py
git commit -m "chore: 项目骨架与依赖"
```

---

### 任务 1：配置模块

**文件：**
- 创建：`app/config.py`

- [ ] **步骤 1：编写实现**（配置无逻辑，直接实现，不写测试）

```python
import os

from dotenv import load_dotenv

load_dotenv()

LLM_BASE_URL = os.getenv("LLM_BASE_URL", "https://api.deepseek.com")
LLM_API_KEY = os.getenv("LLM_API_KEY", "")
LLM_MODEL = os.getenv("LLM_MODEL", "deepseek-chat")
DB_PATH = os.getenv("DB_PATH", "data/tutor.db")

SYSTEM_PROMPT = (
    "你是 CloudOps Tutor，一名云计算运维课程的智能助教。"
    "面向高职学生，回答准确、简洁、循序渐进；"
    "涉及命令时给出示例并解释每个参数。"
)
```

- [ ] **步骤 2：Commit**

```bash
git add app/config.py
git commit -m "feat: 配置模块"
```

---

### 任务 2：SQLite 消息存储

**文件：**
- 创建：`app/storage.py`
- 测试：`tests/test_storage.py`

- [ ] **步骤 1：编写失败的测试**

```python
from app import storage


def test_save_and_get_history(tmp_path):
    db = str(tmp_path / "t.db")
    storage.save_message(db, "s1", "user", "你好")
    storage.save_message(db, "s1", "assistant", "你好，我是助教")
    storage.save_message(db, "s2", "user", "别的会话")
    assert storage.get_history(db, "s1") == [
        {"role": "user", "content": "你好"},
        {"role": "assistant", "content": "你好，我是助教"},
    ]


def test_history_empty_for_new_session(tmp_path):
    db = str(tmp_path / "t.db")
    assert storage.get_history(db, "nobody") == []
```

- [ ] **步骤 2：运行测试验证失败**

运行：`pytest tests/test_storage.py -v`
预期：FAIL，报错 `AttributeError`（storage 无 save_message）或 `ImportError`。

- [ ] **步骤 3：编写最少实现代码**

```python
import sqlite3
from pathlib import Path


def _conn(db_path):
    Path(db_path).parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(db_path)
    conn.execute(
        "CREATE TABLE IF NOT EXISTS messages("
        "id INTEGER PRIMARY KEY AUTOINCREMENT,"
        "session_id TEXT NOT NULL,"
        "role TEXT NOT NULL,"
        "content TEXT NOT NULL,"
        "created_at TEXT DEFAULT (datetime('now','localtime')))"
    )
    return conn


def save_message(db_path, session_id, role, content):
    with _conn(db_path) as c:
        c.execute(
            "INSERT INTO messages(session_id, role, content) VALUES(?,?,?)",
            (session_id, role, content),
        )


def get_history(db_path, session_id, limit=20):
    with _conn(db_path) as c:
        rows = c.execute(
            "SELECT role, content FROM ("
            "SELECT * FROM messages WHERE session_id=? ORDER BY id DESC LIMIT ?"
            ") ORDER BY id",
            (session_id, limit),
        ).fetchall()
    return [{"role": r, "content": t} for r, t in rows]
```

- [ ] **步骤 4：运行测试验证通过**

运行：`pytest tests/test_storage.py -v`
预期：2 passed。

- [ ] **步骤 5：Commit**

```bash
git add app/storage.py tests/test_storage.py
git commit -m "feat: SQLite 消息存储"
```

---

### 任务 3：LLM 客户端封装

**文件：**
- 创建：`app/llm.py`
- 测试：`tests/test_llm.py`

- [ ] **步骤 1：编写失败的测试**

```python
from app.llm import build_messages


def test_build_messages_order():
    history = [
        {"role": "user", "content": "a"},
        {"role": "assistant", "content": "b"},
    ]
    msgs = build_messages("系统提示", history, "新问题")
    assert msgs[0] == {"role": "system", "content": "系统提示"}
    assert msgs[1:3] == history
    assert msgs[-1] == {"role": "user", "content": "新问题"}
    assert len(msgs) == 4
```

- [ ] **步骤 2：运行测试验证失败**

运行：`pytest tests/test_llm.py -v`
预期：FAIL，`ImportError: cannot import name 'build_messages'`。

- [ ] **步骤 3：编写最少实现代码**

```python
from openai import OpenAI

from app import config


def build_messages(system_prompt, history, user_message):
    return [
        {"role": "system", "content": system_prompt},
        *history,
        {"role": "user", "content": user_message},
    ]


class LLMClient:
    def __init__(self, base_url=None, api_key=None, model=None):
        self.model = model or config.LLM_MODEL
        self._client = OpenAI(
            base_url=base_url or config.LLM_BASE_URL,
            api_key=api_key or config.LLM_API_KEY,
        )

    def complete(self, messages):
        resp = self._client.chat.completions.create(
            model=self.model, messages=messages
        )
        return resp.choices[0].message.content
```

- [ ] **步骤 4：运行测试验证通过**

运行：`pytest tests/test_llm.py -v`
预期：1 passed（LLMClient 走真实网络，不在单测覆盖，任务 6 端到端验证）。

- [ ] **步骤 5：Commit**

```bash
git add app/llm.py tests/test_llm.py
git commit -m "feat: LLM 客户端封装与消息拼装"
```

---

### 任务 4：Agent 核心编排

**文件：**
- 创建：`app/core.py`
- 测试：`tests/test_core.py`

- [ ] **步骤 1：编写失败的测试**

```python
from app import storage
from app.core import Agent


class FakeLLM:
    def __init__(self):
        self.seen = []

    def complete(self, messages):
        self.seen.append(messages)
        return "回答" + str(len(self.seen))


def test_chat_saves_and_replies(tmp_path):
    db = str(tmp_path / "t.db")
    agent = Agent(FakeLLM(), db)
    assert agent.chat("s1", "你好") == "回答1"
    assert storage.get_history(db, "s1") == [
        {"role": "user", "content": "你好"},
        {"role": "assistant", "content": "回答1"},
    ]


def test_second_turn_includes_first(tmp_path):
    db = str(tmp_path / "t.db")
    fake = FakeLLM()
    agent = Agent(fake, db)
    agent.chat("s1", "第一句")
    agent.chat("s1", "第二句")
    second_call = fake.seen[1]
    contents = [m["content"] for m in second_call]
    assert "第一句" in contents
    assert "回答1" in contents
    assert contents[-1] == "第二句"
```

- [ ] **步骤 2：运行测试验证失败**

运行：`pytest tests/test_core.py -v`
预期：FAIL，`ImportError: cannot import name 'Agent'`。

- [ ] **步骤 3：编写最少实现代码**

```python
from app import config, storage
from app.llm import build_messages


class Agent:
    def __init__(self, llm, db_path=None):
        self.llm = llm
        self.db_path = db_path or config.DB_PATH

    def chat(self, session_id, user_message):
        history = storage.get_history(self.db_path, session_id)
        messages = build_messages(config.SYSTEM_PROMPT, history, user_message)
        reply = self.llm.complete(messages)
        storage.save_message(self.db_path, session_id, "user", user_message)
        storage.save_message(self.db_path, session_id, "assistant", reply)
        return reply
```

- [ ] **步骤 4：运行测试验证通过**

运行：`pytest tests/test_core.py -v`
预期：2 passed。

- [ ] **步骤 5：Commit**

```bash
git add app/core.py tests/test_core.py
git commit -m "feat: Agent 核心编排（多轮对话）"
```

---

### 任务 5：FastAPI 接口

**文件：**
- 创建：`app/main.py`
- 测试：`tests/test_api.py`

- [ ] **步骤 1：编写失败的测试**

```python
from fastapi.testclient import TestClient

from app import main
from app.core import Agent


class FakeLLM:
    def complete(self, messages):
        return "收到：" + messages[-1]["content"]


def _client(tmp_path, monkeypatch):
    monkeypatch.setattr(main, "agent", Agent(FakeLLM(), str(tmp_path / "t.db")))
    return TestClient(main.app)


def test_chat_endpoint(tmp_path, monkeypatch):
    client = _client(tmp_path, monkeypatch)
    r = client.post("/api/chat", json={"session_id": "s1", "message": "你好"})
    assert r.status_code == 200
    assert r.json()["reply"] == "收到：你好"


def test_history_endpoint(tmp_path, monkeypatch):
    client = _client(tmp_path, monkeypatch)
    client.post("/api/chat", json={"session_id": "s1", "message": "你好"})
    r = client.get("/api/history/s1")
    assert r.status_code == 200
    assert len(r.json()["messages"]) == 2
```

- [ ] **步骤 2：运行测试验证失败**

运行：`pytest tests/test_api.py -v`
预期：FAIL，`ModuleNotFoundError: No module named 'app.main'`。

- [ ] **步骤 3：编写最少实现代码**

```python
from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from app import storage
from app.core import Agent
from app.llm import LLMClient

app = FastAPI(title="CloudOps Tutor")
agent = Agent(LLMClient())


class ChatRequest(BaseModel):
    session_id: str
    message: str


@app.post("/api/chat")
def chat(req: ChatRequest):
    return {"reply": agent.chat(req.session_id, req.message)}


@app.get("/api/history/{session_id}")
def history(session_id: str):
    return {"messages": storage.get_history(agent.db_path, session_id)}


app.mount("/", StaticFiles(directory="static", html=True), name="static")
```

注意：`history` 端点读取 `agent.db_path` 而非 config，保证测试注入的临时库同样生效。static 目录必须先存在（任务 6 创建）；在任务 5 阶段先执行 `mkdir -p static && touch static/.gitkeep`。

- [ ] **步骤 4：运行测试验证通过**

运行：`mkdir -p static && touch static/.gitkeep && pytest tests/test_api.py -v`
预期：2 passed。

- [ ] **步骤 5：Commit**

```bash
git add app/main.py tests/test_api.py static/.gitkeep
git commit -m "feat: FastAPI 聊天与历史接口"
```

---

### 任务 6：前端聊天页与端到端验收

**文件：**
- 创建：`static/index.html`

- [ ] **步骤 1：编写聊天页**

```html
<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8">
<title>CloudOps Tutor</title>
<script src="https://unpkg.com/vue@3/dist/vue.global.prod.js"></script>
<link rel="stylesheet" href="https://unpkg.com/element-plus/dist/index.css">
<script src="https://unpkg.com/element-plus"></script>
<style>
  body { max-width: 760px; margin: 24px auto; font-family: system-ui; }
  .msg { padding: 10px 14px; border-radius: 8px; margin: 8px 0; white-space: pre-wrap; }
  .user { background: #e8f3ff; text-align: right; }
  .assistant { background: #f5f5f5; }
</style>
</head>
<body>
<div id="app">
  <h2>CloudOps Tutor 云运维学习助教</h2>
  <div>
    <div v-for="m in messages" :class="['msg', m.role]">{{ m.content }}</div>
    <div v-if="loading" class="msg assistant">思考中……</div>
  </div>
  <el-input v-model="input" placeholder="输入问题，回车发送"
            @keyup.enter="send" :disabled="loading"></el-input>
</div>
<script>
const { createApp } = Vue;
createApp({
  data() {
    return { input: "", loading: false, messages: [],
             sessionId: "web-" + Date.now() };
  },
  methods: {
    async send() {
      if (!this.input.trim() || this.loading) return;
      const text = this.input;
      this.messages.push({ role: "user", content: text });
      this.input = ""; this.loading = true;
      try {
        const r = await fetch("/api/chat", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ session_id: this.sessionId, message: text })
        });
        const data = await r.json();
        this.messages.push({ role: "assistant", content: data.reply });
      } catch (e) {
        this.messages.push({ role: "assistant", content: "请求失败，请检查后端是否启动" });
      } finally { this.loading = false; }
    }
  }
}).use(ElementPlus).mount("#app");
</script>
</body>
</html>
```

- [ ] **步骤 2：端到端手动验收**

1. `cp .env.example .env`，填入真实 `LLM_API_KEY`
2. 运行：`uvicorn app.main:app --reload`
3. 浏览器打开 `http://127.0.0.1:8000`
4. 验收清单：
   - 发送"什么是 Docker 镜像？"能收到中文回答
   - 追问"它和容器有什么区别？"回答体现上下文（多轮对话验收点）
   - 重启 uvicorn 后 `GET /api/history/<session_id>` 仍能返回历史（持久化验收点）

- [ ] **步骤 3：跑全量测试**

运行：`pytest -v`
预期：全部 passed。

- [ ] **步骤 4：Commit**

```bash
git add static/index.html
git commit -m "feat: Vue3 聊天页，计划1 完成"
```

---

## 自检记录

1. **规格覆盖度**：规格验收标准 2（多轮上下文）由任务 4/6 覆盖；标准 1/3/4 分别属于计划 2/3；SSE 流式与 LLM 重试明确推迟至计划 4（见头部拆分说明）。
2. **占位符扫描**：无"待定/TODO/类似任务N"；所有代码步骤均含完整代码。
3. **类型一致性**：`storage.save_message/get_history(db_path, ...)` 签名在任务 2/4/5 一致；`Agent(llm, db_path)` 与 `complete(messages)` 在任务 4/5 测试与实现一致。
