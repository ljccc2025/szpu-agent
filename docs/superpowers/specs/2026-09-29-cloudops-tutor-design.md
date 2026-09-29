# CloudOps Tutor — 云运维学习助教 Agent 设计规格

- 日期：2026-09-29
- 状态：已批准（头脑风暴阶段完成）
- 项目背景：SZPU 人工智能课程期末作业，作者为云计算运维专业学生，零编程基础，采用 AI 辅助编程，开发周期约一个月。评分包含现场演示、代码与报告。

## 1. 目标与成功标准

构建一个面向云计算运维专业学生的智能助教 Agent，覆盖课程问答、命令实操练习、自动出题与批改、学习规划四类场景。

验收标准：

1. 知识库问答返回带出处引用的回答。
2. 连续追问时上下文不丢失（多轮对话）。
3. Agent 能通过工具调用在沙箱中执行 Linux 命令并讲解结果。
4. 完整跑通"出题 -> 作答 -> 批改 -> 错题入库 -> 学习规划"闭环。

## 2. 总体架构

浏览器（Vue3 单页应用）通过 HTTP/SSE 访问 FastAPI 后端。后端核心是一个手写的 Function Calling 循环（不使用 LangChain），LLM 采用 OpenAI 兼容 API（DeepSeek / 智谱 GLM，base_url 可配置）。四个工具挂载在循环上：RAG 检索、沙箱执行、出题、批改。数据层为 ChromaDB（向量库，嵌入模型 bge-small-zh 本地运行）与 SQLite（对话历史、题目与错题本）。

```
浏览器: 聊天页 | 知识库管理页 | 练习与批改页
   |  HTTP / SSE
FastAPI 后端
   Agent 核心: LLM + Function Calling 循环 (单轮最多 5 次工具调用)
   工具: rag_search | sandbox | quiz | grader
   存储: ChromaDB (向量) + SQLite (业务数据)
   沙箱: 一次性 Docker 容器
```

## 3. 组件与接口

| 组件 | 职责 | 接口 |
| --- | --- | --- |
| agent/core.py | Function Calling 循环 | chat(session_id, message) -> 流式回复 |
| tools/rag_search.py | 知识库检索，返回带出处片段 | search(query) -> [{text, source}] |
| tools/sandbox.py | 一次性 Docker 容器执行命令 | run(cmd) -> {stdout, exit_code} |
| tools/quiz.py | 按知识点与难度出题 | generate(topic, difficulty) |
| tools/grader.py | 评分、逐条点评、薄弱点标记 | grade(question, answer) |
| kb/ingest.py | PDF/Markdown 切块向量化入库 | ingest(file) |
| storage.py | SQLite 读写 | CRUD |
| 前端三页面 | 聊天 / 知识库 / 练习批改 | REST + SSE |

每个组件单一职责、可独立测试；工具不依赖彼此，可单独裁剪。

## 4. 关键数据流（练习模式）

1. 学生请求出题 -> Agent 调 quiz.generate（内部先经 RAG 取知识点，保证题目源自课程资料）。
2. 学生提交答案 -> Agent 调 grader.grade -> 返回分数、点评与知识库出处。
3. 命令实操题 -> Agent 调 sandbox.run 真实执行学生命令并对比预期输出评分。
4. 错题写入 SQLite 错题本 -> 学习规划功能读取错题本生成针对性复习计划。

## 5. 错误处理

- LLM API 失败：重试 2 次，仍失败则前端提示服务繁忙，历史不丢失。
- 沙箱安全：命令黑名单（rm -rf、shutdown 等）、容器禁网、10 秒超时、512MB 内存上限、用后即毁。
- RAG 空结果：明示"课程资料未覆盖，以下为模型自身知识"，禁止伪造出处。
- 工具循环上限：单轮最多 5 次工具调用，超限终止并向用户说明。

## 6. 测试策略

- pytest 单元测试：四个工具独立测试，不依赖 LLM。
- 演示脚本：固定 6 步流程（问答 -> 追问 -> 出题 -> 答题 -> 批改 -> 学习报告）。
- 手动验收：对照第 1 节验收标准逐条勾选。

## 7. 里程碑（4 周）

| 周 | 交付物 | 兜底策略 |
| --- | --- | --- |
| 1 | 后端+前端聊天页，多轮对话跑通 | 最高优先级地基 |
| 2 | RAG 知识库（上传/检索/带出处回答） | 完成即覆盖主要评分点 |
| 3 | 工具调用：沙箱、出题、批改 | 沙箱受阻则砍沙箱保出题批改 |
| 4 | 打磨界面、报告、演示排练；可选多 Agent | 多 Agent 为纯加分项可砍 |

## 8. 可选亮点（仅第 4 周时间富余时）

多 Agent 批改流水线：出题官 -> 批改官 -> 讲解官三角色接力，前端可视化各 Agent 发言。

## 9. 明确不做（YAGNI）

- 用户注册登录体系（演示用单用户即可）。
- 移动端适配。
- 生产级部署（Docker Compose 一键本地启动即可）。
- 多课程/多租户知识库隔离。
