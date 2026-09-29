# CloudOps Tutor — 云运维学习助教 Agent 全栈技术方案与架构文档

---

## 一、需求深度复述与分析

### 1.1 功能模块分析

| 功能模块 | 需求描述 | 技术要求 | 优先级 |
|---------|---------|---------|--------|
| 多轮对话问答 | 带上下文记忆的课程问答，支持连续追问 | 会话历史持久化+messages拼装+上下文窗口管理 | P0 |
| RAG 知识库问答 | 导入课程资料（PDF/Markdown），回答附出处引用 | 文档切块+向量化+相似度检索+引用溯源 | P0 |
| 工具调用（Function Calling） | Agent 自主决定调用检索/沙箱/出题/批改工具 | 手写 Function Calling 循环+工具注册表+循环上限 | P0 |
| Linux 命令沙箱 | 真实执行学生输入的命令并讲解结果 | Docker 一次性容器+命令黑名单+资源限制 | P0 |
| 智能出题 | 按知识点+难度生成选择题/命令实操题 | RAG 取材+结构化 JSON 输出+题目落库 | P0 |
| 智能批改 | 评分+逐条点评+薄弱点标记 | 结构化评分 Prompt+沙箱实测对比+错题入库 | P0 |
| 学习规划 | 基于错题本生成针对性复习计划 | 错题统计+知识点聚合+计划生成 Prompt | P1 |
| 知识库管理 | 上传/查看/删除课程资料 | 文件上传接口+摄取管道+向量库增删 | P1 |
| SSE 流式输出 | 回答打字机式逐字呈现 | FastAPI StreamingResponse+前端 EventSource | P1 |
| 多 Agent 批改流水线 | 出题官→批改官→讲解官三角色接力（加分亮点） | 多角色 Prompt+流水线编排+过程可视化 | P2 |
| 历史记录 | 查看历史对话与批改成绩 | SQLite 持久化+查询接口 | P1 |
| 一键部署演示 | 答辩现场快速拉起全套服务 | Docker Compose 编排+环境变量注入 | P2 |

### 1.2 非功能需求分析

| 需求维度 | 具体要求 | 技术挑战 |
|---------|---------|---------|
| 可完成性 | 零基础+AI辅助编程，1个月内交付 | 模块必须可独立裁剪，每周有可演示产物 |
| 演示稳定性 | 答辩现场 6 步演示流程零翻车 | LLM重试兜底、预置演示数据、固定演示脚本 |
| 安全性 | 沙箱执行学生任意命令不伤宿主机 | 容器禁网+黑名单+超时+内存上限+用后即毁 |
| 成本 | 学生自费 API，控制在 10 元以内 | DeepSeek 低价模型+本地嵌入模型（零 API 费）|
| 可解释性 | 答辩时每行代码都能讲清楚 | 不用重框架，手写 Agent 循环约 100 行 |
| 中文优先 | 界面/回答/点评全中文 | 中文嵌入模型 bge-small-zh+中文 Prompt 工程 |

### 1.3 隐含技术挑战

| 挑战 | 描述 | 影响范围 |
|-----|------|---------|
| 幻觉控制 | RAG 检索为空时模型可能伪造出处 | RAG 工具、Prompt 设计、引用渲染 |
| 工具调用死循环 | LLM 反复调用同一工具不产出答案 | Agent 核心循环（单轮上限 5 次强制终止）|
| 沙箱逃逸 | 学生命令可能试图破坏宿主机 | 沙箱模块全部安全策略 |
| 中文切块质量 | PDF 提取中文常有乱码/断行 | 摄取管道清洗规则、切块策略 |
| 结构化输出稳定性 | 出题/批改要求严格 JSON，模型可能跑偏 | JSON Schema 约束+解析失败重试 |
| 会话上下文膨胀 | 长对话超出模型上下文窗口 | 历史截断策略（保留最近 20 条）|

### 1.4 本软件与通用聊天机器人/低代码平台的本质区别

| 对比维度 | 本软件 | 通用聊天机器人 | 低代码平台(Dify/Coze) |
|---------|--------|--------------|---------------------|
| 工具真实性 | Docker 沙箱真实执行命令 | 无执行能力，只会"嘴上说" | 沙箱类工具受限或无 |
| 知识边界 | RAG 限定课程资料并附出处 | 全网知识无出处，幻觉难查 | RAG 可配但定制受限 |
| 教学闭环 | 出题→批改→错题本→复习规划全链路 | 无状态，不跟踪学习进度 | 需拼接多个应用 |
| 代码掌控度 | 全部自研，答辩每行能讲 | — | 黑盒节点，讲不出原理 |
| 专业贴合 | 云计算运维课程专属工具链 | 通用 | 通用 |

---

## 二、终极技术栈选型（带具体版本及决策矩阵）

### 2.1 后端 Web 框架

| 维度 | 详情 |
|------|------|
| **我们的选择** | **FastAPI 0.115.x + uvicorn 0.32.x** |
| 备选方案 | Flask 3.x、Django 5.x |
| 决定性理由 | 1) 原生 async 支持，SSE 流式输出零阻塞；2) Pydantic 自动请求校验+自动生成 /docs 交互文档（答辩演示加分）；3) 代码量比 Django 少一个数量级，零基础友好；4) 与 openai SDK 的异步调用天然契合 |
| 关键应用点 | 聊天接口、知识库上传、历史查询、静态页面挂载 |

**🎯 推荐Skills**: `fastapi-python`（新装，`.agents/skills/fastapi-python`，已验证）

### 2.2 Agent 核心框架

| 维度 | 详情 |
|------|------|
| **我们的选择** | **手写 Function Calling 循环（约 100 行）** |
| 备选方案 | LangChain 0.3.x、LangGraph、AutoGen |
| 决定性理由 | 1) 零基础用重框架出 bug 无法排查，手写循环每行可控；2) 答辩讲"我自己实现了 Agent 循环"远比"我调了 LangChain"有含金量；3) OpenAI tools 协议本身已足够简单；4) 无版本地狱 |
| 关键应用点 | 消息循环、工具分发、循环上限熔断、结果回填 |

**🎯 推荐Skills**: `software-architecture`（本地 `.shuncode/mcp-tools/software-architecture`）、`tdd_workflow`（MCP 工具直用）

### 2.3 LLM 接入

| 维度 | 详情 |
|------|------|
| **我们的选择** | **DeepSeek API（deepseek-chat）+ openai SDK 1.x 兼容调用** |
| 备选方案 | 智谱 GLM-4-Flash（免费）、通义 qwen-turbo |
| 决定性理由 | 1) 完全兼容 OpenAI SDK，仅改 baseURL；2) 国内直连低延迟；3) 输入 ¥1/1M tokens，全项目开发+演示预算 <10 元；4) Function Calling 支持成熟；5) base_url 可配置，随时一键切换备选模型 |
| 关键应用点 | 对话生成、工具调用决策、出题/批改结构化输出 |

**🎯 推荐Skills**: `fastapi-python`（异步 API 调用模式）、`systematic-debugging`（本地，API 异常排查）

### 2.4 RAG 向量数据库

| 维度 | 详情 |
|------|------|
| **我们的选择** | **ChromaDB 1.5.x（本地嵌入式模式）** |
| 备选方案 | FAISS、Milvus Lite、Qdrant |
| 决定性理由 | 1) pip 装完即用，无独立服务进程；2) 自带持久化（SQLite+parquet），重启不丢；3) API 三行代码完成增查删；4) 支持 metadata 过滤（按课程/章节筛选）|
| 关键应用点 | 课程资料向量存取、Top-K 相似度检索、来源 metadata 回带 |

**🎯 推荐Skills**: `rag-skills`（新装，`.agents/skills/rag-skills`，已验证——含向量库选型/分块/检索质量指南）

### 2.5 嵌入模型

| 维度 | 详情 |
|------|------|
| **我们的选择** | **BAAI/bge-small-zh-v1.5 + sentence-transformers 6.x（本地推理）** |
| 备选方案 | 智谱 embedding-3 API、text-embedding-3-small |
| 决定性理由 | 1) 中文检索质量在同体积模型中最优；2) 仅 90MB，CPU 可跑，笔记本无压力；3) 本地推理零 API 费用、离线可演示；4) sentence-transformers 一行 encode |
| 关键应用点 | 文档切块向量化、查询向量化 |

**🎯 推荐Skills**: `rag-skills`（嵌入模型选型章节）、`performance-engineer`（本地，批量编码性能）

### 2.6 命令沙箱

| 维度 | 详情 |
|------|------|
| **我们的选择** | **Docker Engine + docker SDK for Python 7.x（一次性容器）** |
| 备选方案 | subprocess+seccomp、WebAssembly(WASI)、SSH 到废弃虚拟机 |
| 决定性理由 | 1) 云计算运维专业本身就学 Docker——沙箱即教学内容本身，答辩双重加分；2) `network_disabled=True`+内存/CPU 限额+`auto_remove=True` 四行配置即达生产级隔离；3) alpine 镜像 5MB 秒级启动 |
| 关键应用点 | 学生命令真实执行、实操题判分、容器安全策略 |

**🎯 推荐Skills**: `docker-build-strategies`（新装，已验证）、`docker-compose-patterns`（新装，已验证）

### 2.7 业务数据持久化

| 维度 | 详情 |
|------|------|
| **我们的选择** | **SQLite（Python 标准库 sqlite3）** |
| 备选方案 | PostgreSQL、MySQL、TinyDB |
| 决定性理由 | 1) 零部署零配置，单文件即库；2) 演示单用户场景性能绰绰有余；3) 标准库自带，依赖清单再减一项；4) DBeaver 可直接打开给评委看表结构 |
| 关键应用点 | 对话历史、题目记录、错题本、批改成绩 |

**🎯 推荐Skills**: `test_driven_development`（MCP 工具直用，存储层单测先行）

### 2.8 前端框架

| 维度 | 详情 |
|------|------|
| **我们的选择** | **Vue 3.5（CDN 全局构建）+ Element Plus 2.8（CDN）** |
| 备选方案 | Vite+Vue SFC 工程化、React 18、纯原生 JS |
| 决定性理由 | 1) CDN 引入免 Node 构建链，零基础少踩 80% 的坑；2) Element Plus 组件库中文文档最全；3) 单 HTML 文件即一个页面，改完刷新即生效；4) 保留后期升级 Vite 工程的路径 |
| 关键应用点 | 聊天页、知识库管理页、练习批改页 |

**🎯 推荐Skills**: `vue-best-practices`（本地 `.shuncode/mcp-tools/vue-best-practices`）、`ui-ux-pro-max`（本地，界面美化）、`web-design-skill-main`（本地）

### 2.9 实时通信

| 维度 | 详情 |
|------|------|
| **我们的选择** | **SSE（Server-Sent Events）via FastAPI StreamingResponse** |
| 备选方案 | WebSocket、HTTP 轮询 |
| 决定性理由 | 1) 单向推送场景 SSE 比 WebSocket 简单一半；2) 浏览器原生 EventSource/fetch 流式读取，无需额外库；3) 断线自动重连 |
| 关键应用点 | 回答逐字流式、多 Agent 流水线过程推送 |

**🎯 推荐Skills**: `fastapi-python`（StreamingResponse 模式）

### 2.10 测试与质量保证

| 维度 | 详情 |
|------|------|
| **我们的选择** | **pytest 8.x + httpx(TestClient) + FakeLLM 注入** |
| 备选方案 | unittest、Playwright E2E |
| 决定性理由 | 1) 全部单测不依赖真实 LLM API（FakeLLM 注入），CI 零成本可重复；2) TestClient 直测 FastAPI 无需起服务；3) TDD 流程与 superpowers 技能链无缝衔接 |
| 关键应用点 | 四工具单测、存储层单测、API 集成测试 |

**🎯 推荐Skills**: `tdd_workflow` + `test_driven_development`（MCP 工具直用）、`verification-before-completion`（本地）

### 2.11 部署与演示

| 维度 | 详情 |
|------|------|
| **我们的选择** | **Docker Compose v2（compose.yaml 单文件编排）** |
| 备选方案 | 裸 uvicorn 启动、Nginx+Gunicorn |
| 决定性理由 | 1) `docker compose up` 一条命令拉起全套，答辩现场最稳；2) 云计算运维专业展示 Compose 编排能力本身就是评分点；3) 环境变量注入与 .env 天然集成 |
| 关键应用点 | 一键启动、演示环境复原 |

**🎯 推荐Skills**: `docker-compose-patterns`（新装，已验证）

### 2.12 文档解析

| 维度 | 详情 |
|------|------|
| **我们的选择** | **pypdf 6.x + markdown 原生读取** |
| 备选方案 | pdfplumber、unstructured、OCR 方案 |
| 决定性理由 | 1) 课程 PPT 导出 PDF 多为文字版，pypdf 纯 Python 无系统依赖；2) 扫描件场景保留 ocr-document-processor 技能作升级路径 |
| 关键应用点 | 知识库摄取管道的文本提取 |

**🎯 推荐Skills**: `ocr-document-processor`（本地，扫描件兜底）、`rag-skills`（切块策略章节）

---

## 三、高保真系统架构与模块详设

### 3.1 架构全景图

```
┌────────────────────────── 浏览器 ──────────────────────────┐
│  聊天页(index.html) │ 知识库页(kb.html) │ 练习页(practice.html) │
└──────────────────────────┬─────────────────────────────────┘
                           │ REST + SSE
┌──────────────────────────▼─────────────────────────────────┐
│                  FastAPI (app/main.py)                      │
│  ┌────────────── 路由层 api/routes.py + stream.py ────────┐ │
│  └──────────────────────┬─────────────────────────────────┘ │
│  ┌──────────────────────▼─────────────────────────────────┐ │
│  │        Agent 核心 core.py（Function Calling 循环）      │ │
│  │   ┌─────────── 工具注册表 tools/registry.py ─────────┐  │ │
│  └───┼───────────┬──────────┬──────────┬────────────────┘  │ │
│      ▼           ▼          ▼          ▼                    │
│  rag_search   sandbox     quiz      grader                  │
│      │           │          │          │                    │
│  ┌───▼───┐  ┌───▼────┐  ┌──▼──────────▼──┐                 │
│  │ChromaDB│  │Docker  │  │ SQLite         │                 │
│  │+bge嵌入│  │一次性容器│ │ (对话/题目/错题) │                 │
│  └───────┘  └────────┘  └────────────────┘                 │
│  知识库摄取: kb/ingest.py ← 上传 PDF/MD                     │
│  可选亮点: agents/pipeline.py 多Agent批改流水线              │
└─────────────────────────────────────────────────────────────┘
```

### 3.2 全部功能模块深度分解（总计 22 个核心模块）

---

#### 模块 01: FastAPI 应用入口

| 属性 | 内容 |
|------|------|
| **模块ID** | M01-AppEntry |
| **物理文件路径** | `app/main.py` |
| **核心职责** | 应用装配：注册路由、挂载静态目录、初始化 Agent 实例与生命周期钩子 |
| **对外API** | `app: FastAPI`（uvicorn 入口） |
| **内部技术** | FastAPI 0.115, lifespan 钩子预热嵌入模型, StaticFiles |
| **交互流程** | uvicorn 启动→lifespan 预热 bge 模型→注册 /api 路由→挂载 static/→就绪 |

**🔧 核心技术栈**: `fastapi` 0.115.x、`uvicorn` 0.32.x

**🎯 推荐Skills**: `fastapi-python`（✅ 新装已验证）

---

#### 模块 02: 配置管理

| 属性 | 内容 |
|------|------|
| **模块ID** | M02-Config |
| **物理文件路径** | `app/config.py` |
| **核心职责** | 唯一读取环境变量的地方：LLM 地址/密钥/模型、DB 路径、沙箱参数、系统 Prompt |
| **对外API** | `LLM_BASE_URL, LLM_API_KEY, LLM_MODEL, DB_PATH, CHROMA_DIR, SANDBOX_IMAGE, SYSTEM_PROMPT` |
| **内部技术** | python-dotenv, os.getenv 带默认值 |
| **交互流程** | import 时 load_dotenv→各模块 from app import config 取值 |

**🔧 核心技术栈**: `python-dotenv` 1.x

**🎯 推荐Skills**: `fastapi-python`（配置管理模式）

---

#### 模块 03: SQLite 存储服务

| 属性 | 内容 |
|------|------|
| **模块ID** | M03-Storage |
| **物理文件路径** | `app/storage.py` |
| **核心职责** | 对话历史、题目、答题记录、错题本四张表的全部读写；唯一碰 SQLite 的模块 |
| **对外API** | `save_message() / get_history() / save_quiz() / save_attempt() / get_wrong_questions()` |
| **内部技术** | sqlite3 标准库, CREATE TABLE IF NOT EXISTS 自迁移, 参数化查询防注入 |
| **交互流程** | 各工具/核心调用→打开连接→执行→with 自动提交关闭 |

**🔧 核心技术栈**: `sqlite3`（标准库）

**🎯 推荐Skills**: `test_driven_development`（MCP 直用，先写存储单测）

**核心表结构**:
```sql
messages(id, session_id, role, content, created_at)
quizzes(id, topic, difficulty, qtype, question, options, answer, explanation, source, created_at)
attempts(id, quiz_id, student_answer, score, feedback, created_at)
-- 错题本 = attempts 中 score < 60 的记录联查 quizzes
```

---

#### 模块 04: LLM 客户端

| 属性 | 内容 |
|------|------|
| **模块ID** | M04-LLMClient |
| **物理文件路径** | `app/llm.py` |
| **核心职责** | 封装 OpenAI 兼容调用：普通补全、带 tools 补全、流式补全、失败重试 2 次 |
| **对外API** | `LLMClient.complete(messages) / complete_with_tools(messages, tools) / stream(messages)` |
| **内部技术** | openai SDK 1.x, base_url 注入, tenacity 风格简易重试 |
| **交互流程** | Agent 核心传 messages→SDK 调 DeepSeek→异常重试→返回 message 对象 |

**🔧 核心技术栈**: `openai` 1.x

**🎯 推荐Skills**: `fastapi-python`（异步调用）、`systematic-debugging`（本地，超时/限流排查）

---

#### 模块 05: Agent 核心编排（Function Calling 循环）

| 属性 | 内容 |
|------|------|
| **模块ID** | M05-AgentCore |
| **物理文件路径** | `app/core.py` |
| **核心职责** | 整个项目的心脏：取历史→拼 messages→LLM 决策→有 tool_calls 则执行工具回填再问→最多 5 轮→落库返回 |
| **对外API** | `Agent.chat(session_id, message) -> reply` / `Agent.chat_stream(...)` |
| **内部技术** | 手写循环, tool_calls JSON 解析, 循环上限熔断, 依赖注入(llm/db 可换 Fake) |
| **交互流程** | 路由层调用→循环体→工具注册表分发→结果以 role=tool 回填→产出最终回答 |

**🔧 核心技术栈**: 纯 Python + `openai` tools 协议

**🎯 推荐Skills**: `software-architecture`（本地）、`tdd_workflow`（MCP 直用）、`architect-review`（本地，循环设计评审）

**循环伪代码**:
```python
for step in range(5):                    # 熔断上限
    resp = llm.complete_with_tools(messages, TOOLS)
    if not resp.tool_calls:
        return resp.content              # 最终回答
    for call in resp.tool_calls:
        result = registry.dispatch(call.name, call.arguments)
        messages.append(tool_result(call.id, result))
return "工具调用次数超限，请换个问法"
```

---

#### 模块 06: 工具注册与调度

| 属性 | 内容 |
|------|------|
| **模块ID** | M06-ToolRegistry |
| **物理文件路径** | `app/tools/registry.py` |
| **核心职责** | 集中声明 4 个工具的 JSON Schema；按名称分发执行；工具异常兜底为错误文本 |
| **对外API** | `TOOLS: list[dict]`（OpenAI tools 格式）、`dispatch(name, args_json) -> str` |
| **内部技术** | dict 映射表, json.loads 容错, 单工具异常不炸整轮对话 |
| **交互流程** | Agent 核心→dispatch→查映射表→执行→返回字符串结果 |

**🔧 核心技术栈**: 纯 Python

**🎯 推荐Skills**: `software-architecture`（本地，接口边界设计）

---

#### 模块 07: RAG 检索工具

| 属性 | 内容 |
|------|------|
| **模块ID** | M07-RAGSearch |
| **物理文件路径** | `app/tools/rag_search.py` |
| **核心职责** | 查询向量化→ChromaDB Top-5 检索→拼装带出处的上下文文本；空结果时明确声明防幻觉 |
| **对外API** | `search(query: str) -> str`（含 [来源: 文件名 p.X] 标记） |
| **内部技术** | 相似度阈值过滤(distance<0.6), metadata 回带 source/page |
| **交互流程** | Agent 决策调用→embedder 编码→vectorstore 查询→格式化返回 |

**🔧 核心技术栈**: `chromadb` 1.5.x（系统 sqlite<3.35 时按官方方案用 pysqlite3-binary 顶替）、`sentence-transformers` 6.x

**🎯 推荐Skills**: `rag-skills`（✅ 新装已验证——检索质量/重排章节）

---

#### 模块 08: 知识库摄取管道

| 属性 | 内容 |
|------|------|
| **模块ID** | M08-KBIngest |
| **物理文件路径** | `app/kb/ingest.py` |
| **核心职责** | 上传文件→按类型提取文本→清洗（去页眉页脚/修断行）→重叠切块（500字/重叠80）→批量向量化入库 |
| **对外API** | `ingest(file_path) -> {chunks: int, source: str}` |
| **内部技术** | pypdf 提取, 中文标点感知切块, chunk metadata(source/page/chunk_id) |
| **交互流程** | kb.html 上传→路由存临时文件→ingest→返回切块数给前端展示 |

**🔧 核心技术栈**: `pypdf` 5.x、`chromadb`、`sentence-transformers`

**🎯 推荐Skills**: `rag-skills`（分块策略章节）、`ocr-document-processor`（本地，扫描件兜底）

---

#### 模块 09: 向量库封装

| 属性 | 内容 |
|------|------|
| **模块ID** | M09-VectorStore |
| **物理文件路径** | `app/kb/vectorstore.py` |
| **核心职责** | ChromaDB 唯一入口：collection 获取、增删查、按 source 删除整个文件的块 |
| **对外API** | `add(chunks, metas) / query(vec, k=5) / delete_by_source(source) / list_sources()` |
| **内部技术** | PersistentClient(path=CHROMA_DIR), get_or_create_collection |
| **交互流程** | ingest 写入 / rag_search 查询 / kb 管理页删除 |

**🔧 核心技术栈**: `chromadb` 1.5.x（系统 sqlite<3.35 时按官方方案用 pysqlite3-binary 顶替）

**🎯 推荐Skills**: `rag-skills`（向量库运维章节）、`performance-engineer`（本地）

---

#### 模块 10: 嵌入模型服务

| 属性 | 内容 |
|------|------|
| **模块ID** | M10-Embedder |
| **物理文件路径** | `app/kb/embedder.py` |
| **核心职责** | bge-small-zh 模型单例加载（进程内只载一次）、文本批量编码 |
| **对外API** | `encode(texts: list[str]) -> list[list[float]]` |
| **内部技术** | sentence-transformers, 模块级懒加载单例, batch_size=32 |
| **交互流程** | 首次调用加载模型(约3秒)→后续毫秒级编码 |

**🔧 核心技术栈**: `sentence-transformers` 6.x、`BAAI/bge-small-zh-v1.5`

**🎯 推荐Skills**: `performance-engineer`（本地，编码批量化）

---

#### 模块 11: 沙箱执行工具

| 属性 | 内容 |
|------|------|
| **模块ID** | M11-Sandbox |
| **物理文件路径** | `app/tools/sandbox.py` |
| **核心职责** | 在一次性 Docker 容器中执行 Linux 命令，五重防线：黑名单→禁网→内存 512M→CPU 0.5核→10 秒超时 |
| **对外API** | `run(cmd: str) -> {stdout, exit_code, blocked: bool}` |
| **内部技术** | docker SDK, alpine:3.24 镜像, auto_remove=True, network_disabled=True |
| **交互流程** | Agent 调用→黑名单正则预检→containers.run→捕获输出→容器自毁→返回 |

**🔧 核心技术栈**: `docker`(SDK) 7.x、`alpine:3.24`（2026-09 最新稳定版）

**🎯 推荐Skills**: `docker-build-strategies`（✅ 新装已验证）、`systematic-debugging`（本地）

**安全黑名单（部分）**:
```python
BLOCKED = [r"rm\s+-rf\s+/", r"mkfs", r"dd\s+if=", r":\(\)\{.*\};:", r"shutdown", r"reboot"]
```

---

#### 模块 12: 智能出题工具

| 属性 | 内容 |
|------|------|
| **模块ID** | M12-Quiz |
| **物理文件路径** | `app/tools/quiz.py` |
| **核心职责** | 按知识点+难度出题：先 RAG 取材保证题目源自课程资料，再结构化 JSON 生成，题目落库 |
| **对外API** | `generate(topic, difficulty, qtype) -> {question, options?, answer, explanation}` |
| **内部技术** | response_format=json_object, JSON 解析失败自动重试 1 次, 落库 quizzes 表 |
| **交互流程** | Agent/练习页调用→rag_search 取知识片段→出题 Prompt→JSON 校验→存库返回 |

**🔧 核心技术栈**: `openai` 3.x、`sqlite3`

**🎯 推荐Skills**: `rag-skills`（取材检索）、`test_driven_development`（MCP 直用）

**出题 Prompt 要点**: `你是云计算运维课程出题专家，基于给定课程资料片段出一道{difficulty}难度的{qtype}，考察{topic}，输出严格 JSON：{"question":..., "options":[...], "answer":..., "explanation":...}，题目必须能从资料中找到依据`

---

#### 模块 13: 智能批改工具

| 属性 | 内容 |
|------|------|
| **模块ID** | M13-Grader |
| **物理文件路径** | `app/tools/grader.py` |
| **核心职责** | 两种批改模式（与 M12 题型严格对齐）：单选题确定性比对答案字母，不调 LLM；命令实操题把学生命令与参考命令都放进沙箱真实执行，再交 LLM 裁决效果等价性。简答题待 M12 支持该题型后再补 |
| **对外API** | `grade(quiz_id, student_answer, llm=None, db_path=None, runner=None) -> {quiz_id, topic, qtype, score, passed, feedback, weak_points, correct_answer, explanation, source}` |
| **内部技术** | JSON 模式评分 Prompt(0-100)+校验重试, 沙箱双跑联动, attempts 单表落库（错题 = score<60 的查询，不另建 wrong_questions 表） |
| **交互流程** | 学生提交→查 quizzes 表→按题型分支→评分→attempts 落库→返回点评 |

**🔧 核心技术栈**: `openai` SDK v3（3.20.x，JSON 模式）、`sqlite3`、复用 M11 沙箱 `run()`

**🔌 REST 接口**: `POST /api/quiz/{quiz_id}/grade`（失败返回 422）、`GET /api/attempts?only_wrong=true`（错题本）

**🛡️ 答案保护**: 标准答案只从 quizzes 表按 id 取，不经由对话上下文或前端流转

**🎯 推荐Skills**: `test_driven_development`（MCP 直用）、`chinese_code_review`（点评话术分级参考：必须修复/建议/仅供参考）

---

#### 模块 14: 错题本与学习规划

| 属性 | 内容 |
|------|------|
| **模块ID** | M14-StudyPlanner |
| **物理文件路径** | `app/tools/planner.py`（与其余四个 Agent 工具同目录，不另建 `app/study/` 包） |
| **核心职责** | 聚合错题本→统计薄弱知识点 Top-N→生成 N 天针对性复习计划（每天知识点+复习重点+练习建议）|
| **对外API** | `make_plan(days=7, db_path=None, llm=None, top_n=5) -> {days, weak_topics, daily_plan, sources}` |
| **内部技术** | **三段式**：① SQL 聚合出排名与分数（确定性，模型改不了）② 每个知识点做真实 RAG 检索取讲义出处（防幻觉）③ LLM 仅把前两者组织成自然语言计划。错题本为空直接拒绝生成，不编计划 |
| **交互流程** | 用户请求"帮我做复习计划"→Agent 调用→统计→生成→返回 markdown 计划 |

**🔧 核心技术栈**: `sqlite3`（聚合查询在 `app/storage.py`）、`openai` SDK v3（3.20.x，JSON 模式+校验重试）、复用 M07 `rag_search.search`

**🔌 REST 接口**: `POST /api/plan`（body `{"days": 7}`，1-30；错题本为空或模型不可用返回 422）

**🖥️ 前端入口**: 练习页错题本卡片内「生成复习计划」按钮；对话内说"帮我做复习计划"触发 `make_study_plan` 工具

**📊 排序口径**: 错题数 DESC → 平均分 ASC → 知识点名 ASC（三级兜底保证顺序确定可测）

**🎯 推荐Skills**: `software-architecture`（本地）

---

#### 模块 15: SSE 流式输出层

| 属性 | 内容 |
|------|------|
| **模块ID** | M15-SSEStream |
| **物理文件路径** | `app/stream.py`（SSE 封装）+ `app/core.py::Agent.chat_stream`（流式循环）+ `app/llm.py::ToolCallAccumulator`（分片还原） |
| **核心职责** | 把 Agent 的流式 token 与工具调用事件封装为 SSE 事件流（event: token / tool_start / tool_end / done）|
| **对外API** | `POST /api/chat/stream`（text/event-stream，另有 error 事件兜底；与非流式 `/api/chat` 并存不替换） |
| **内部技术** | StreamingResponse + 同步生成器（openai 客户端是同步的，FastAPI 自动放入线程池）；`tool_calls` 按 index 分桶累积还原；`X-Accel-Buffering: no` 防反代缓冲 |
| **交互流程** | 前端 `fetch` + `ReadableStream` 逐帧解析（EventSource 只支持 GET，承载不了 POST 会话体）→逐 token 打字机渲染→工具事件渲染为"正在执行 xx 工具…"气泡→`done` 补出处卡 |

**🔧 核心技术栈**: `fastapi` StreamingResponse

**🎯 推荐Skills**: `fastapi-python`（✅ 新装已验证——StreamingResponse 生成器模式）

> 实现说明（2026-09-29 落地）：开 `stream=True` 后同一个工具调用会被拆进多个 chunk，首片带 `id` 与 `function.name`，后续片只带 `function.arguments` 的片段，必须按 `index` 分桶累积才能还原；并发多工具时拼错即串号。该逻辑抽成 `ToolCallAccumulator` 纯类单测覆盖。流式过程中**不做重试**——流一旦开始吐字，中途重试会让学生看到重复内容，失败统一兜底成 `error` 事件。

---

#### 模块 16: REST 路由层

| 属性 | 内容 |
|------|------|
| **模块ID** | M16-APIRoutes |
| **物理文件路径** | `app/api/routes.py` |
| **核心职责** | 全部非流式端点：chat、history、kb 上传/列表/删除、quiz 生成、grade 提交、plan 生成 |
| **对外API** | `/api/chat /api/chat/stream /api/history/{sid} /api/kb/* /api/quiz/generate /api/quiz/{id}/grade /api/attempts /api/plan` |
| **内部技术** | APIRouter, Pydantic 请求模型, UploadFile |
| **交互流程** | 前端 REST 调用→Pydantic 校验→委托对应模块→统一 JSON 返回 |

**🔧 核心技术栈**: `fastapi`、`pydantic` 2.x

**🎯 推荐Skills**: `fastapi-python`（路由组织模式）

---

#### 模块 17: 前端聊天页

| 属性 | 内容 |
|------|------|
| **模块ID** | M17-ChatPage |
| **物理文件路径** | `static/index.html` |
| **核心职责** | 主界面：消息列表（用户/助手气泡+markdown 渲染+出处角标）、流式打字机、工具调用过程展示 |
| **对外API** | 页面路由 `/` |
| **内部技术** | Vue3 CDN, Element Plus, marked.js 渲染 markdown, fetch 流读取 |
| **交互流程** | 输入→POST /api/chat/stream→逐 token 追加→done 后渲染出处 |

**🔧 核心技术栈**: `vue` 3.5 CDN、`element-plus` 2.8、`marked` 12.x

**🎯 推荐Skills**: `vue-best-practices`（本地）、`ui-ux-pro-max`（本地，聊天界面视觉）

---

#### 模块 18: 前端知识库管理页

| 属性 | 内容 |
|------|------|
| **模块ID** | M18-KBPage |
| **物理文件路径** | `static/kb.html` |
| **核心职责** | 拖拽上传课程资料、显示摄取进度与切块数、已导入文件列表、删除文件（联动向量库清理）|
| **对外API** | 页面路由 `/kb.html` |
| **内部技术** | el-upload 组件, FormData 上传, 列表轮询 |
| **交互流程** | 拖入 PDF→POST /api/kb/upload→显示"已切 N 块"→列表刷新 |

**🔧 核心技术栈**: `vue` 3.5、`element-plus` el-upload

**🎯 推荐Skills**: `vue-best-practices`（本地）、`web-design-skill-main`（本地）

---

#### 模块 19: 前端练习与批改页

| 属性 | 内容 |
|------|------|
| **模块ID** | M19-PracticePage |
| **物理文件路径** | `static/index.html`（第三个页签「练习与批改」；与 M17/M18 同页，不另建 practice.html） |
| **核心职责** | 选知识点/难度/题型→出题→作答（单选题选项按钮／命令实操题等宽输入框）→提交批改→展示分数点评与出处→同页错题本表格 |
| **对外API** | 页内 `POST /api/quiz/generate`（with_answer=false）、`POST /api/quiz/{id}/grade`、`GET /api/attempts` |
| **内部技术** | 题型条件渲染, 批改结果分级配色（≥80绿/60-79黄/<60红）, data 属性+事件委托（不拼 onclick）, 后端不可达时降级演示数据 |
| **交互流程** | 出题→答题→POST /api/quiz/{id}/grade→点评渲染→同页错题本刷新 |

**🔧 核心技术栈**: 原生 JS（无框架、无 CDN 依赖，断网可演示）、内联 SVG 图标、CSS 语义色 token 双主题

**🎨 设计系统**（ui-ux-pro-max 生成）: 风格 Data-Dense Dashboard + Dark Mode(OLED) 双主题；浅色 B2B Service「navy #0F172A + CTA #0369A1」，深色 OLED「code dark #0F172A + run green #22C55E」；字体用系统栈而非 Google Fonts CDN（离线可用）

**✅ 验收脚本**: `pwtest_ui.py` —— 24 项浏览器断言（结构/深色模式/XSS 回归/练习控件/出题批改闭环/错题本/375px 响应式/控制台零报错）

**🎯 推荐Skills**: `ui-ux-designer`（本地）、`vue-best-practices`（本地）

---

#### 模块 20: 多 Agent 批改流水线（可选亮点）

| 属性 | 内容 |
|------|------|
| **模块ID** | M20-MultiAgentPipeline |
| **物理文件路径** | `app/pipeline.py`（编排 + 讲解官）+ `app/stream.py::pipeline_sse`（成帧） |
| **核心职责** | 出题官→批改官→讲解官三角色接力，全过程 SSE 推送给前端时间线可视化。出题官复用 M12、批改官复用 M13，**讲解官为本模块新增** |
| **对外API** | `POST /api/pipeline/run`（SSE：agent_start / agent_output / done / error），两阶段按参数分流 |
| **内部技术** | 角色顺序编排, 过程事件流, 讲解官 RAG 取材, 领域异常透传 |
| **交互流程** | 练习页触发→出题官出题→学生作答→批改官评分→讲解官补充讲解→前端时间线展示 |

**🔧 核心技术栈**: `openai` 1.x、复用 M15 SSE

**🎯 推荐Skills**: `subagent_driven_development`（MCP 直用——多智能体分工+两阶段审查思想直接映射）、`architect-review`（本地）

> 实现说明（2026-09-29 落地）：
>
> **据实描述本模块的增量**：出题官直接调用 M12 `quiz.generate`，批改官直接调用 M13 `grader.grade`，二者均不重写——它们已含 RAG 取材、JSON 校验重试、选项洗牌、答案不进上下文、沙箱双跑等成套纪律，另写一份只会产生两套会漂移的逻辑。**M20 = 一层编排 + 一个新角色（讲解官）**，其价值在于把原本藏在后台的多角色协作变成看得见的过程，而非"实现了三个智能体"。
>
> **两阶段设计**：「出题 → **学生作答** → 批改」中间是人工暂停，接口不可能一条直线跑到底。带 `topic` 走阶段一（出题官），带 `quiz_id` + `student_answer` 走阶段二（批改官 → 讲解官），同一端点按参数分流；参数缺失返回语义 422 而非裸 500。
>
> **讲解官（唯一新增角色）**：拿批改结果里的 `topic` 做真实 RAG 检索，把「学生得分 + 批改点评 + 正确答案 + 讲义原文」一并交给 LLM，产出带出处的针对性讲解。**检索为空时如实降级并且完全不调用 LLM**——既守住防幻觉纪律（与 `rag_search` 空结果拒答、`quiz` 无资料拒绝出题、`planner` 空错题本拒绝生成同源），也省掉一次无意义的 API 开销。
>
> **答案防泄露**：阶段一的 `agent_output` 剥掉 `answer` 与 `explanation`，与 M12 `generate_quiz` 同一条纪律——否则前端按 F12 就能直接看到答案。已有专门的回归测试守住。
>
> **分层**：编排逻辑在 `app/pipeline.py`，SSE 成帧复用 `app/stream.py`，两层职责不混。文件放在 `app/` 而非新建 `app/agents/` 包，与 `core.py`/`stream.py` 同为编排层，遵循与 M14、M15 一致的就近原则。
>
> **实跑取证**：新增 12 个测试，全量 **221 passed / 5 skipped**，覆盖率 89.85%（门槛 85% 通过），`app/pipeline.py` 覆盖率 89%。

---

#### 模块 21: 测试与质量保障

| 属性 | 内容 |
|------|------|
| **模块ID** | M21-Testing |
| **物理文件路径** | `tests/`（17 个测试文件）+ `pyproject.toml`（pytest/coverage 配置）+ `requirements-dev.txt` + `.github/workflows/ci.yml` |
| **核心职责** | 全模块单测+API 集成测试；FakeLLM/FakeSandbox 注入使测试零 API 成本、零 Docker 依赖；覆盖率量化并设防倒退门槛；每次推送由 GitHub Actions 自动执行 |
| **对外API** | `python -m pytest --cov=app` 全绿且覆盖率 ≥ `fail_under` |
| **内部技术** | pytest fixtures, tmp_path 临时库, monkeypatch 注入, coverage 分支覆盖, GitHub Actions + pip 缓存 |
| **交互流程** | 每任务 TDD：红→绿→重构→commit→push 触发 CI |

**🔧 核心技术栈**: `pytest` 9.1、`pytest-cov` 7.1、`coverage` 7.16、`httpx`、GitHub Actions

**🎯 推荐Skills**: `tdd_workflow` + `test_driven_development`（MCP 直用）、`verification-before-completion`（本地，交付前核验清单）

> 实现说明（2026-09-29 落地）：
>
> **基线实测**：209 passed / 5 skipped，行覆盖 91%、分支覆盖 90%（810 条语句）。
>
> **门槛口径**：`fail_under = 85`，定位是「防倒退的地板」而非虚荣指标。本机与 CI 环境覆盖率不同（见下），取较低一侧再留缓冲，保证两处共用一个数字都不会误报。
>
> **5 个 skip 的成因已定位，并非疏漏**：`test_quiz_real_api.py` 的 2 个用例需要真实 DeepSeek API Key，CI 刻意不注入（不消耗自费额度，也不因上游抖动变红）；`test_vectorstore.py` 的 3 个用例在开发机因未装 chromadb 而跳过，**在 CI 中会真实执行**——这正是引入 CI 的实质价值：补上开发机永远测不到的向量库盲区。
>
> **覆盖率发现的真实缺陷**：`app/llm.py` 原覆盖率仅 72%，`complete()` 的指数退避重试逻辑从未被任何测试执行过——所有上层测试都注入 FakeLLM。补测后该模块达 100%，总覆盖率由 89% 升至 91%。
>
> **CI 依赖取舍**：`sentence-transformers` 默认拉 CUDA 版 torch 约 2.5GB，工作流改用 PyTorch 官方 CPU 索引（约 200MB）并启用 pip 缓存；Python 固定 3.11，与生产虚拟机（Rocky Linux 8.9 + Python 3.11.13）保持一致。
>
> **依赖分层**：`requirements.txt` 仅保留运行依赖（移出 `pytest`、`httpx`），测试依赖收敛到 `requirements-dev.txt`，M22 构建镜像时可直接只装前者。

---

#### 模块 22: 部署与答辩演示

| 属性 | 内容 |
|------|------|
| **模块ID** | M22-DeployDemo |
| **物理文件路径** | `Dockerfile`（多阶段）、`compose.yaml`、`.dockerignore`、`docs/演示脚本.md` |
| **核心职责** | 一键 `docker compose up` 拉起；固定 6 步演示脚本（问答→追问→出题→答题→批改→复习计划）；演示数据预置 |
| **对外API** | `docker compose up -d`，服务暴露在宿主 **8001**（避开宿主已运行的 8000） |
| **内部技术** | 多阶段构建, 构建期烘焙嵌入模型, healthcheck, 卷挂载持久化 data/, 非 root 运行 + `group_add` 取得 docker socket 权限 |
| **交互流程** | 答辩前 compose up→打开浏览器→照脚本走 |

**🔧 核心技术栈**: Docker Compose v2、`docker-build-strategies` 多阶段构建

**🎯 推荐Skills**: `docker-compose-patterns` + `docker-build-strategies`（✅ 新装已验证）、`chinese-documentation`（本地，演示文档）

> 实现说明（2026-09-29 落地，镜像 **1.89GB**，构建耗时约 6 分钟）：
>
> **目标机实测约束（决定了实现方式）**：① `pypi.org` 不可达，`Dockerfile` 必须写死清华镜像源；② `python:3.11-slim` 已在本地缓存，构建刻意不拉新基础镜像；③ **不能写 `# syntax=docker/dockerfile:1`**——该指令会让 BuildKit 去 Docker Hub 拉前端镜像，国内网络下会卡死构建（已实测踩坑）；④ `sentence-transformers` 默认拉 2.5GB CUDA 版 torch，改用 PyTorch 官方 CPU 索引。
>
> **模型烘焙**：构建期经 `hf-mirror.com` 把 `BAAI/bge-small-zh-v1.5` 下进镜像，运行时零下载，答辩现场断网也能启动。
>
> **沙箱的 DooD 取舍**：容器内要启动沙箱子容器，唯一办法是挂载 `/var/run/docker.sock`。**代价是容器内进程等价于宿主 root**（可通过 Docker API 挂载宿主任意目录）。这是教学项目为保住「真实执行 Linux 命令」核心卖点的明确取舍，不适用于生产；生产应使用 gVisor / Kata 等真正的沙箱运行时。容器本身以非 root 用户 `app`(uid 1000) 运行，靠 compose 的 `group_add: ["987"]` 取得 socket 权限（987 为本机 docker 组 GID）。
>
> **部署踩坑记录**：宿主 `data/` 原属主为 root，容器以 uid 1000 运行导致 SQLite 报 `attempt to write a readonly database`。首次部署须执行 `chown -R 1000:1000 data`；root 身份的旧服务不受影响（root 绕过权限检查）。
>
> **端口策略**：容器映射 `8001:8000`，与宿主原有 uvicorn 服务并行运行，互不干扰。既便于灰度验证，也为答辩留了一条随时可切回的后路。
>
> **容器内实测取证**：healthcheck 转 healthy；RAG 问答返回 5 条真实出处（第5章-Nginx服务部署.md）；沙箱真实起子容器执行 `uname -a` 返回宿主内核信息且退出码 0；SSE 流式 143 帧（118 token + tool_start/tool_end/done）；全程宿主 8000 服务未受影响。

---

## 四、工程化配置

### 4.1 完整目录结构

```
szpu人工智能课程期末作业Agent/
├── app/
│   ├── __init__.py
│   ├── main.py              # M01 入口
│   ├── config.py            # M02 配置
│   ├── storage.py           # M03 存储
│   ├── llm.py               # M04 LLM客户端
│   ├── core.py              # M05 Agent核心
│   ├── api/
│   │   ├── routes.py        # M16 REST路由
│   │   └── stream.py        # M15 SSE
│   ├── tools/
│   │   ├── registry.py      # M06 工具注册
│   │   ├── rag_search.py    # M07 RAG检索
│   │   ├── sandbox.py       # M11 沙箱
│   │   ├── quiz.py          # M12 出题
│   │   └── grader.py        # M13 批改
│   ├── kb/
│   │   ├── ingest.py        # M08 摄取
│   │   ├── vectorstore.py   # M09 向量库
│   │   └── embedder.py      # M10 嵌入
│   ├── study/
│   │   └── planner.py       # M14 学习规划
│   └── agents/
│       └── pipeline.py      # M20 多Agent(可选)
├── static/                  # M17-19 三个页面
├── tests/                   # M21 测试
├── data/                    # SQLite + Chroma 持久化(gitignore)
├── docs/                    # 规格/计划/演示脚本
├── .agents/skills/          # 新装技能(fastapi-python等4个)
├── compose.yaml  Dockerfile  requirements.txt  .env.example
```

### 4.2 requirements.txt

```
fastapi
uvicorn[standard]
openai
python-dotenv
chromadb
sentence-transformers
pypdf
docker
pytest
httpx
```

### 4.3 compose.yaml

```yaml
services:
  tutor:
    build: .
    ports: ["8000:8000"]
    env_file: .env
    volumes:
      - ./data:/app/data
      - /var/run/docker.sock:/var/run/docker.sock   # 沙箱需要
    healthcheck:
      test: ["CMD", "curl", "-f", "http://localhost:8000/api/health"]
      interval: 10s
      retries: 3
```

### 4.4 环境变量（.env.example）

```env
# ---- LLM ----
LLM_BASE_URL=https://api.deepseek.com
LLM_API_KEY=sk-your-key            # https://platform.deepseek.com/api_keys
LLM_MODEL=deepseek-chat
# ---- 数据 ----
DB_PATH=data/tutor.db
CHROMA_DIR=data/chroma
# ---- 沙箱 ----
SANDBOX_IMAGE=alpine:3.24
SANDBOX_TIMEOUT=10
SANDBOX_MEM_LIMIT=512m
```

### 4.5 从零启动的"傻瓜式"指南

```markdown
## 前置条件
- Python 3.10+、Git、Docker Desktop（沙箱与部署用）

## 本地开发模式
python -m venv .venv && source .venv/Scripts/activate
pip install -r requirements.txt
cp .env.example .env   # 填入 DeepSeek Key
uvicorn app.main:app --reload
# 打开 http://127.0.0.1:8000

## 一键演示模式
docker compose up -d

## 常用命令
pytest -v          # 全量测试
pytest tests/test_tools.py -v   # 只测工具
```

---

## 五、关键设计决策补充

### 5.1 数据流向图（RAG 问答主链路）

```
用户提问 → 聊天页 → POST /api/chat/stream
              ↓
        Agent 核心循环
              ↓ LLM 决策: 需要查资料
        tool_call: rag_search
              ↓ bge 编码 → ChromaDB Top-5 → 阈值过滤
        带出处片段回填 messages
              ↓ LLM 综合生成
        SSE 逐 token → 前端打字机 → 出处角标渲染
              ↓
        messages 落库 SQLite
```

### 5.2 沙箱安全模型（五重防线）

```
学生命令 → ① 黑名单正则预检(拒绝 rm -rf / 等)
        → ② network_disabled=True (容器禁网)
        → ③ mem_limit=512m + cpu_quota=50%
        → ④ timeout=10s 强杀
        → ⑤ auto_remove=True 用后即毁
宿主机文件系统零挂载，容器内破坏不外溢
```

### 5.3 性能与稳定性策略

1. **嵌入模型单例**：进程内只加载一次 bge（省 3 秒/次）
2. **历史截断**：每轮只带最近 20 条消息，防上下文膨胀
3. **LLM 重试**：失败自动重试 2 次，间隔 1s/2s
4. **JSON 输出校验**：出题/批改解析失败自动重试 1 次
5. **演示兜底**：预置知识库+预置题库，现场断网也能演示沙箱与错题本
6. **工具熔断**：单轮最多 5 次工具调用

### 5.4 Skills 使用总览

| 技能 | 来源/位置 | 服务的模块 | 状态 |
|------|----------|-----------|------|
| fastapi-python | 新装 `.agents/skills/` | M01/02/04/15/16 | ✅ 已验证 |
| rag-skills | 新装 `.agents/skills/` | M07/08/09/12 | ✅ 已验证 |
| docker-build-strategies | 新装 `.agents/skills/`（Docker官方） | M11/22 | ✅ 已验证 |
| docker-compose-patterns | 新装 `.agents/skills/`（Docker官方） | M22 | ✅ 已验证 |
| tdd_workflow / test_driven_development | MCP 工具直接调用 | M03/05/12/13/21 | ✅ 可直用 |
| subagent_driven_development | MCP 工具直接调用 | M20 + 整体开发流程 | ✅ 可直用 |
| chinese_code_review | MCP 工具（需 /chinese-code-review 显式触发） | M13 点评话术 + 代码评审 | ✅ 可直用 |
| software-architecture / architect-review | 本地 `.shuncode/mcp-tools/` | M05/06/14/20 | ✅ 本地可读 |
| vue-best-practices / ui-ux-pro-max / web-design-skill-main / ui-ux-designer | 本地 `.shuncode/mcp-tools/` | M17/18/19 | ✅ 本地可读 |
| systematic-debugging | 本地 `.shuncode/mcp-tools/` | M04/11 排障 | ✅ 本地可读 |
| performance-engineer | 本地 `.shuncode/mcp-tools/` | M09/10 | ✅ 本地可读 |
| ocr-document-processor | 本地 `.shuncode/mcp-tools/` | M08 扫描件兜底 | ✅ 本地可读 |
| verification-before-completion | 本地 `.shuncode/mcp-tools/` | M21 交付核验 | ✅ 本地可读 |
| brainstorming / writing-plans / executing-plans | 本地 `.shuncode/mcp-tools/` | 全流程（已用前两个产出规格与计划1） | ✅ 已实战 |
| chinese-git-workflow / chinese-commit-conventions / chinese-documentation | 本地 `.shuncode/mcp-tools/` | 提交规范/报告撰写 | ✅ 本地可读 |
