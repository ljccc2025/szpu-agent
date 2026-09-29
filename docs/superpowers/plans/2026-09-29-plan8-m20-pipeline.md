# M20 多 Agent 批改流水线 实现计划

> **面向 AI 代理的工作者：** 必需子技能：使用 superpowers:subagent-driven-development（推荐）或 superpowers:executing-plans 逐任务实现此计划。步骤使用复选框（`- [ ]`）语法来跟踪进度。

**目标：** 把「出题官 → 批改官 → 讲解官」三角色接力做成一条可视化流水线，全过程经 SSE 推给前端时间线。

**架构：** 本模块**只做编排，不重写业务**。出题官直接调 M12 `quiz.generate`，批改官直接调 M13 `grader.grade`，真正新增的只有讲解官。SSE 帧封装复用 M15 的 `stream.sse_pack`。

**技术栈：** 复用 `app/tools/quiz.py`、`app/tools/grader.py`、`app/tools/rag_search.py`、`app/llm.py`、`app/stream.py`；`pytest`；原生 JS 前端。

---

## 先厘清：M20 到底新增了什么

| 角色 | 实现方式 | 是否新代码 |
| --- | --- | --- |
| 出题官 | 直接调用 M12 `quiz.generate()` | 否，复用 |
| 批改官 | 直接调用 M13 `grader.grade()` | 否，复用 |
| **讲解官** | **新增**：拿批改结果做真实 RAG，产出带出处的针对性讲解 | **是** |
| 流水线编排 | **新增**：角色顺序、事件流、异常兜底 | **是** |

据实描述：M20 = **一层编排 + 一个新角色**，而不是"三个新智能体"。它的价值在于把原本藏在后台的多角色协作**变成看得见的过程**，这正是技术文档把它列为「可选亮点」的原因。

---

## 设计决策记录

| 冲突 / 待定 | 技术文档原文 | 本计划采用 | 理由 |
| --- | --- | --- | --- |
| 文件位置 | `app/agents/pipeline.py`（新建包） | **`app/pipeline.py`** | 它是编排层，与 `app/core.py`、`app/stream.py` 同级；为单个模块新开一层包收益不抵回归风险。与 M14 `planner.py` 就近放进 `app/tools/`、M15 `stream.py` 放在 `app/` 同一种就近原则 |
| 中间要等学生作答 | 未明确 | **两阶段，同一端点按参数分流** | 「出题→**学生作答**→批改」中间是人工暂停，接口不可能一条直线跑到底。带 `topic` 走阶段一，带 `quiz_id`+`student_answer` 走阶段二 |
| 出题官要不要重写 | 「各自独立 system prompt」 | **不重写，直接复用 `quiz.generate`** | M12 已含 RAG 取材、JSON 校验重试、选项洗牌、答案不进上下文等一整套纪律，重写一份只会产生两套会漂移的逻辑 |
| 答案泄露 | 未提及 | **阶段一输出剥掉 answer/explanation** | 与 M12 `generate_quiz` 同一条纪律：正确答案绝不出服务端，否则按 F12 就能看到 |
| 讲解官取材 | 「讲解官补充讲解」 | **必须做真实 RAG 检索并带出处** | 与 `rag_search` 空结果拒答、`quiz` 无资料拒绝出题、`planner` 空错题本拒绝生成同一套防幻觉纪律 |
| 讲解官无资料时 | 未提及 | **如实降级说明，不凭空讲** | 同上。宁可说"没检索到"，不可编造出处 |
| SSE 封装 | 「复用 M15 SSE」 | **复用 `stream.sse_pack`，在 `stream.py` 加 `pipeline_sse`** | 编排逻辑归 `pipeline.py`，SSE 成帧归 `stream.py`，两层职责不混 |

---

## 事件协议

| 事件 | data 结构 | 时机 |
| --- | --- | --- |
| `agent_start` | `{"role": "quizmaster", "name": "出题官"}` | 某角色开始工作 |
| `agent_output` | `{"role": ..., ...角色产出}` | 该角色产出结果 |
| `done` | `{"stage": "quiz"\|"grade", ...}` | 本阶段结束 |
| `error` | `{"message": "..."}` | 异常兜底 |

**阶段一（出题）**：`agent_start(出题官)` → `agent_output(题目，不含答案)` → `done`
**阶段二（批改+讲解）**：`agent_start(批改官)` → `agent_output(评分点评)` → `agent_start(讲解官)` → `agent_output(讲解+出处)` → `done`

---

## 文件结构

| 文件 | 动作 | 职责 |
| --- | --- | --- |
| `app/pipeline.py` | 创建 | 三角色编排、讲解官实现、事件流 |
| `app/stream.py` | 修改（文件尾） | 新增 `pipeline_sse()` |
| `app/main.py` | 修改 | 新增 `POST /api/pipeline/run` 与 `PipelineRequest` |
| `static/index.html` | 修改（练习页 + JS 尾部） | 三角色时间线可视化 |
| `tests/test_pipeline.py` | 创建 | 角色顺序 / 答案不外泄 / 讲解官 RAG / 空资料降级 / 异常兜底 / REST |
| `技术文档-CloudOpsTutor.md` | 修改（M20 条目） | 同步文件位置、两阶段设计与复用关系 |

---

## 任务 1：讲解官（唯一的新角色）

**文件：** 创建 `app/pipeline.py`；测试 `tests/test_pipeline.py`

- [ ] **步骤 1：编写失败的测试** —— ① 讲解官拿 `topic` 去检索；② 产出带 sources；③ 检索为空时返回降级说明且 `sources == []`；④ 不调用 LLM 就不该产生讲解（空资料时零 LLM 开销）
- [ ] **步骤 2：实现 `explain(result, llm=None)`**
- [ ] **步骤 3：跑测试确认转绿**

## 任务 2：两阶段编排

- [ ] **步骤 1：编写失败的测试** —— 阶段一事件顺序、阶段一输出**不含** answer/explanation、阶段二四个事件顺序、异常兜底成 `error`
- [ ] **步骤 2：实现 `run_quiz_stage` / `run_grade_stage` / `run`**
- [ ] **步骤 3：跑测试确认转绿**

## 任务 3：SSE 与 REST 端点

- [ ] **步骤 1：编写失败的测试** —— `/api/pipeline/run` 返回 `text/event-stream`，两阶段各自含正确事件；参数非法返回 422
- [ ] **步骤 2：`stream.pipeline_sse()` + `main.py` 挂 `StreamingResponse`**
- [ ] **步骤 3：跑测试确认转绿**

## 任务 4：前端三角色时间线

- [ ] **步骤 1：** 练习页加「多 Agent 流水线」入口与竖向时间线容器
- [ ] **步骤 2：** 三张角色卡依次点亮（等待 / 进行中 / 完成三态）
- [ ] **步骤 3：** 讲解官输出复用 `citeHTML()` 渲染出处卡
- [ ] **步骤 4：** 阶段一结束后就地收集学生作答，再触发阶段二

## 任务 5：验证与交付

- [ ] **步骤 1：** `python -m pytest --cov=app` 全绿且覆盖率不低于 `fail_under=85`
- [ ] **步骤 2：** `get_diagnostics` 零错误
- [ ] **步骤 3：** 同步技术文档 M20 条目
- [ ] **步骤 4：** 中文 commit + push（CI 自动跑）
- [ ] **步骤 5：** 虚拟机重建镜像 + 容器内实测流水线全链路

---

## 验收标准

1. `POST /api/pipeline/run {topic}` 流式推出「出题官」事件并返回题目，**响应中不含正确答案与解析**。
2. `POST /api/pipeline/run {quiz_id, student_answer}` 依次推出「批改官」「讲解官」四个事件。
3. 讲解官的讲解带真实出处；知识库无相关资料时如实降级，不编造。
4. 前端练习页能看到三张角色卡依次点亮的时间线。
5. 既有 202+ 测试全部保持通过，覆盖率门槛不倒退。
6. 容器内实测流水线可用。
