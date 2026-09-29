# CloudOps Tutor 全量代码审查报告（M01–M11）

- 日期：2026-09-29
- 审查范围：全仓库 `app/` + `tests/` + `static/`，共 1457 行 Python + 241 行前端
- 基线提交：`e941a58`（`main`，与 `origin/main` 同步）
- 对照需求：`docs/superpowers/specs/2026-09-29-cloudops-tutor-design.md`、`docs/superpowers/plans/2026-09-29-plan1-chat-foundation.md`
- 审查流程：superpowers `requesting-code-review` + `code-reviewer` 模板 + `review-agent` 判据 + `verification-before-completion` 取证 + `chinese-code-review` 话术分级
- 验证基线（本次实跑）：`python -m pytest -q` → **64 passed, 3 skipped, 1 warning in 4.46s**；`get_diagnostics` → **0 条诊断**

本报告中每一条 Critical / Important 结论均有实跑证据，复现脚本见文末附录。

---

## 一、优点

先说做得好的地方，这些不是客套，是逐文件看完后确认的。

1. **分层纪律真的守住了。** `storage.py` 是唯一碰 SQLite 的模块，`vectorstore.py` 是唯一碰 ChromaDB 的模块，`config.py` 是唯一读环境变量的地方。1457 行里没有一处越界访问。很多同规模项目做不到这一点。

2. **依赖注入设计让测试摆脱了外部依赖。** `Agent.__init__(llm, db_path, tools, dispatch)`（`app/core.py:12-16`）四个参数全可注入，所以 64 个测试零真实 LLM 调用、零真实 Docker、4.46 秒跑完。对"现场演示"评分项来说，这是能随时证明代码可用的底气。

3. **`calculator` 用 AST 白名单而非 `eval`。** `app/tools/registry.py:24-37` 显式枚举允许的运算节点，并且 `tests/test_registry.py:10` 专门测了 `__import__('os')` 被拒。主动防注入，不是碰巧安全。

4. **防幻觉做到了实处，不是写在文档里的口号。** `app/tools/rag_search.py:12-16` 的 `NO_RESULT_TEXT`、`app/config.py:32-34` 系统提示里的"严禁编造出处"、`app/tools/rag_search.py:30` 的距离阈值过滤，三层共同约束。RAG 作业里这一环最容易糊弄，这里没糊弄。

5. **沙箱的 Docker 用法是对的，而且写明了为什么。** `app/tools/sandbox.py:10-11` 注释解释了为何用 `detach + wait + 手动 remove` 而不是 `auto_remove=True`（后者可能在读日志前就删掉容器）。`pids_limit=64`（`sandbox.py:68`）是规格没要求的额外加固。

6. **前端 `md()` 的转义顺序是对的。** `static/index.html:149-154` 先 `esc()` 再做 markdown 替换。实测输入 `<img src=x onerror=alert(1)>` 输出 `&lt;img src=x onerror=alert(1)&gt;`，安全。很多人会写反导致 XSS，这里没写反。

7. **注释含金量高。** 每个模块头部标注所属里程碑、依赖的官方 API 版本、核查日期（如 `app/kb/vectorstore.py:3-7`）。半年后回看能直接接上，答辩时也能快速定位依据。

---

## 二、问题

分级说明：**[必须修复]** = 不修不能交付；**[建议修改]** = 本次或下个迭代修；**[仅供参考]** = 不改也行。

### Critical（必须修复）

#### C1 [必须修复] 上传文件名未转义，导致存储型 XSS

**位置：** `static/index.html:147`（`esc` 定义）、`static/index.html:229`（注入点）

**问题：** `esc()` 的实现是 `d.textContent = s; return d.innerHTML`，只转义 `&`、`<`、`>`，**不转义单引号**。而第 229 行把它拼进了 HTML 属性里的 JS 字符串：

```js
<button class="del" onclick="delSource('${esc(s.source)}')">删除</button>
```

**完整攻击链（已实测打通）：**

| 环节 | 结果 |
| --- | --- |
| 构造文件名 `a');alert(1);('.pdf` | `Path(fn).suffix` = `.pdf`，**通过** `app/main.py:56` 的类型白名单 |
| 文件名写入知识库 metadata | `app/kb/ingest.py:75` 原样存入 `source` 字段 |
| `/api/kb/sources` 返回 | `app/main.py:70-72` 原样返回 |
| 前端渲染 | 属性值变为 `delSource('a');alert(1);('.pdf')` |
| 浏览器解析 | 该字符串**是合法 JS**（`new Function()` 解析通过），`alert(1)` 执行 |

需要说明的是，注入内容必须让整个 handler 保持语法合法才会执行。用 `//` 注释收尾的常见写法在这里反而无效——`Path()` 会把 `/` 当路径分隔符，导致后缀解析为空而被后端拦下。但 `a');alert(1);('.pdf` 这类配平括号的 payload 可以完全绕过，实测确认。

**为什么重要：** 演示机上任何人上传一个文件，就能在你的页面里执行任意脚本。若评委或同学懂一点安全，这是现场翻车点。

**修复：** 不要把数据拼进 `onclick`。改成 data 属性 + 事件委托：

```js
// 渲染
box.innerHTML = data.sources.map(s => `
  <div class="src-item">📄 <span class="nm">${esc(s.source)}</span>
    <span class="ck">${s.chunks} 个知识块</span>
    <button class="del" data-src="${esc(s.source)}">删除</button></div>`).join("");

// 绑定一次即可
box.addEventListener("click", e => {
  const b = e.target.closest(".del");
  if (b) delSource(b.dataset.src);
});
```

同时建议把 `esc()` 补全引号转义，作为纵深防御：

```js
function esc(s){
  return String(s).replace(/&/g,"&amp;").replace(/</g,"&lt;")
                  .replace(/>/g,"&gt;").replace(/"/g,"&quot;").replace(/'/g,"&#39;");
}
```

另外建议在 `app/main.py:53` 的上传入口对文件名做一次白名单清洗（只保留中英文、数字、`.`、`-`、`_`），从源头掐断。

---

#### C2 [必须修复] LLM 调用失败会丢失用户提问并返回 500，违反自己的设计规格

**位置：** `app/core.py:26-27`、`app/core.py:67`、`app/main.py:39-42`、`app/llm.py:46`

**问题：** `LLMClient.complete` 重试 2 次后 `raise last_err`（`app/llm.py:46`）。`Agent.chat` 没有捕获，`/api/chat` 也没有捕获，异常一路抛到 FastAPI → 返回 500。更关键的是 `storage.save_message`（`app/core.py:67`）写在循环**之后**，异常路径上根本执行不到。

**实测证据：**

```
=== P4: LLM 失败导致用户消息丢失 ===
  RESULT: chat() 直接向上抛出 RuntimeError: API 502 Bad Gateway
  落库历史: [] -> 用户提问未持久化
```

**为什么重要：** 这条**直接违反你自己写的验收规格**。`docs/superpowers/specs/2026-09-29-cloudops-tutor-design.md` §5 原文：

> LLM API 失败：重试 2 次，仍失败则前端提示服务繁忙，历史不丢失。

三个要求目前一个都没达成——500 不是友好提示，历史丢了，前端只能显示 `HTTP 500`（`static/index.html` 的 catch 分支）。演示时网络抖一下，学生刚打的问题就消失了。

**修复：** 用户消息先落库，再进循环；LLM 异常兜底成友好回复。

```python
def chat(self, session_id, user_message):
    history = storage.get_history(self.db_path, session_id, limit=config.HISTORY_LIMIT)
    storage.save_message(self.db_path, session_id, "user", user_message)  # 先落库
    messages = build_messages(config.SYSTEM_PROMPT, history, user_message)
    reply = "工具调用次数超过上限，请换个问法试试。"
    sources = []
    try:
        for _ in range(config.MAX_TOOL_ROUNDS):
            ...  # 原逻辑不动
    except Exception:
        reply = "服务暂时繁忙，请稍后再试。"
        sources = []
    storage.save_message(self.db_path, session_id, "assistant", reply)
    return {"reply": reply, "sources": sources}
```

**必须补的回归测试：** LLM 抛异常时，① 不抛到调用方；② 返回友好文案；③ 用户消息仍在库里。

---

#### C3 [必须修复] `calculator` 幂运算无上限，一次工具调用即可挂死工作线程

**位置：** `app/tools/registry.py:19`（放行 `ast.Pow`）、`app/tools/registry.py:34-37`、`app/tools/registry.py:128-131`（`dispatch` 只捕异常不设时限）

**问题：** AST 白名单挡住了注入，但没挡住**计算量**。`dispatch` 的 `try/except Exception` 对"算得慢"完全无效——它不是异常，就是纯粹地占着 CPU 不放。

**实测证据：**

```
=== P3: calculator 幂运算 CPU DoS ===
  RESULT: 表达式 '9**9**8' 超过 8 秒未返回 -> 一次工具调用即可挂死工作线程（DoS 确认）
  观测耗时 8.1s
```

**为什么重要：** `/api/chat` 是同步 `def` 路由（`app/main.py:40`），FastAPI 会把它放进 anyio 线程池执行。学生在聊天框说一句"帮我算 9 的 9 的 8 次方次方"，LLM 就会调用这个工具，该线程被永久占住，同时 CPU 打满、内存持续增长。几次就能把线程池占满导致整站假死。现场演示可以被一句话打挂。

**修复（建议两条都做）：**

```python
# 1) 移除幂运算——助教场景四则运算足够
_OPS = {ast.Add: operator.add, ast.Sub: operator.sub,
        ast.Mult: operator.mul, ast.Div: operator.truediv,
        ast.Mod: operator.mod, ast.USub: operator.neg}

# 2) 若确实要保留幂运算，必须限幅
if isinstance(node.op, ast.Pow):
    base, exp = _safe_eval(node.left), _safe_eval(node.right)
    if abs(exp) > 64 or abs(base) > 10**6:
        raise ValueError("指数或底数过大，已拒绝计算")
    return base ** exp
```

---

### Important（建议修改）

#### I1 [建议修改] `rag_search._last_sources` 是模块级全局，多用户并发时出处串号

**位置：** `app/tools/rag_search.py:10, 27, 36`、`app/core.py:55-66`

**问题：** 出处通过模块级全局变量在 `rag_search.search()` 和 `Agent.chat()` 之间传递。由于 `/api/chat` 是同步路由、跑在线程池里，多个请求会并发读写同一个全局变量。

**实测证据（两线程并发）：**

```
=== P5: rag_search 全局出处跨会话串号 ===
  会话A 期望 A.pdf，实际: [{'source': 'B.pdf', 'page': 2, ...}]
  会话B 期望 B.pdf，实际: []
  RESULT: 出处串号/丢失 -> 模块级全局状态并发缺陷确认
```

会话 A 拿到了 B 的出处，会话 B 什么都没拿到。

**为什么重要：** 出处卡是这个项目的核心卖点（对应验收标准 #1）。两台机器同时提问就会张冠李戴，而且这种错误"看起来是对的"——比不显示出处更危险，学生会照着错误的页码去翻课件。

**修复：** 让 `search()` 直接返回数据，不走全局状态。最小改动方案是给 `dispatch` 增加一个副产物通道：

```python
# rag_search.py
def search(query: str):
    ...
    return text, sources          # 不再写全局

# registry.py
def dispatch(name, arguments_json):
    ...
    out = handler(**args)
    if isinstance(out, tuple):
        return out                # (text, extra)
    return str(out), None
```

若不想改签名，也可以用 `contextvars.ContextVar` 替代模块全局，它天然按执行上下文隔离。

---

#### I2 [建议修改] SQLite 连接只提交不关闭，文件句柄持续泄漏

**位置：** `app/storage.py:21`、`app/storage.py:29`

**问题：** `with sqlite3.connect(...) as c` 这个写法有个常见误解——`sqlite3.Connection` 的上下文管理器**只负责提交或回滚事务，不会关闭连接**（CPython 官方文档明确说明）。

**实测证据：**

```
=== P1: storage.py SQLite 连接泄漏 ===
  RESULT: with 块退出后连接仍可用 -> 连接从未 close（泄漏确认）
```

`with` 块退出后 `c.execute("SELECT 1")` 依然成功，证明连接还活着。

**影响：** 每轮对话产生 3 个永不释放的连接（1 次 `get_history` + 2 次 `save_message`），只能靠 GC 兜底。长时间演示会累积文件句柄；Windows 上还容易触发 `database is locked`。

**修复：**

```python
from contextlib import closing

def save_message(db_path, session_id, role, content):
    with closing(_conn(db_path)) as c, c:
        c.execute("INSERT INTO messages(session_id, role, content) VALUES(?,?,?)",
                  (session_id, role, content))

def get_history(db_path, session_id, limit=20):
    with closing(_conn(db_path)) as c:
        rows = c.execute(...).fetchall()
    return [{"role": r, "content": t} for r, t in rows]
```

---

#### I3 [建议修改] 沙箱黑名单可轻易绕过，与"五重防线"的对外宣称不符

**位置：** `app/tools/sandbox.py:18-27`（黑名单）、`app/tools/sandbox.py:61-69`（容器参数）

**先说结论的边界：** 真正的安全边界是**一次性容器 + 禁网**，这一点你设计对了，所以黑名单被绕过**不会危害宿主机**。问题出在"宣称"和"教学正确性"上。

**实测绕过清单：**

| 命令 | 结果 |
| --- | --- |
| `rm -rf /` | BLOCKED: 删除根目录 |
| `rm --recursive --force /` | **未拦截**（正则只认 `-x` 短选项） |
| `rm --recursive /` | **未拦截** |
| `find / -delete` | **未拦截**（等效删除，不在黑名单） |
| `cat /etc/shadow` | **未拦截**（读敏感文件） |
| `> /etc/passwd` | **未拦截**（截断关键文件） |
| `$(echo cm0gLXJmIC8= \| base64 -d)` | **未拦截**（base64 编码后由 `/bin/sh -c` 解码执行） |

**为什么重要：** 两点。① `app/tools/registry.py:95` 的工具描述对学生宣称"危险命令会被安全策略自动拦截"，`技术文档-CloudOpsTutor.md` 也写了"五重防线"——实际拦不住，**这是错误的安全教学示范**；② 答辩时评委随手试一条 `rm --recursive /` 就能证伪第一重防线。

**修复建议（把定位讲清楚比堆正则更重要）：**

1. **文档与工具描述改口径**：黑名单定位为"教学提示层"，明确真正的隔离由一次性容器提供。这比假装正则能防住一切更诚实，也更像专业做法。
2. **黑名单补漏**：`--recursive`、`--force` 长选项，`find ... -delete`、`shred`、`> /etc/`。
3. **容器侧加固**（成本低、收益明显，目前这几项都缺）：

```python
container = client.containers.run(
    config.SANDBOX_IMAGE, ["/bin/sh", "-c", cmd],
    detach=True,
    network_disabled=True,
    mem_limit=config.SANDBOX_MEM,
    memswap_limit=config.SANDBOX_MEM,       # 缺失：否则内存限制可被 swap 绕过
    nano_cpus=int(config.SANDBOX_CPU * 1e9),
    pids_limit=64,
    user="nobody",                           # 缺失：当前以 root 运行
    read_only=True,                          # 缺失：根文件系统只读
    cap_drop=["ALL"],                        # 缺失：丢弃全部 capability
    security_opt=["no-new-privileges"],      # 缺失：禁止提权
)
```

这几行加上去，你的"五重防线"就名副其实了，答辩时也是加分点。

---

#### I4 [建议修改] 规格验收标准 #4 完全未实现——需要你先做排期决策

**位置：** `docs/superpowers/specs/2026-09-29-cloudops-tutor-design.md` §1 验收标准 4、§3 组件表

**实测核对：**

| 检查项 | 结果 |
| --- | --- |
| `ls app/tools/` | 只有 `rag_search.py` / `registry.py` / `sandbox.py`，**无 `quiz.py`、`grader.py`** |
| `grep -rn "quiz\|grader\|错题" app/ --include=*.py` | **0 命中** |
| 前端页签（`static/index.html:99-100`） | 只有"学习对话"、"课程知识库"，**无"练习与批改"页** |
| `docs/superpowers/plans/` | 只有 plan1，**计划 2/3/4 未落盘** |

**验收标准达成情况：**

| # | 标准 | 状态 |
| --- | --- | --- |
| 1 | 知识库问答返回带出处引用 | 已达成（但见 I1 并发缺陷） |
| 2 | 多轮对话上下文不丢失 | 已达成 |
| 3 | 沙箱中执行 Linux 命令并讲解 | 已达成 |
| 4 | 出题→作答→批改→错题入库→学习规划闭环 | **未开始** |

**为什么重要：** 4 条验收标准达成 3 条，缺的这条是一整个核心场景，而评分明确包含"现场演示"。

**这是进度问题而非实现缺陷**——计划 3/4 本来就还没写。但它需要你**尽早决策**，因为它决定剩余排期：

- 方案 A：补完 `quiz` + `grader` + 错题本 + 练习页（估计 2–3 天）
- 方案 B：调整规格，把第 4 条降级为"未来工作"，在报告里说明取舍理由

不建议悬着不决定。

---

#### I5 [建议修改] 知识库接口无鉴权、无大小限制

**位置：** `app/main.py:53-78`

**问题：** `/api/kb/upload` 对上传体积不设上限（`shutil.copyfileobj` 直接写临时文件），`/api/kb/{source}` 任何人可以 DELETE 掉整个来源的全部知识块。三个接口都没有任何身份校验。

**为什么重要：** 演示机通常挂在教室局域网里。同学传一个 2GB 文件就能塞满你的磁盘，或者把你辛苦入库的课件一键删光。

**YAGNI 提醒：** 如果你确定只在本机 `127.0.0.1` 上演示、不对外暴露端口，这条可以降级为 [仅供参考]。**请确认你的部署方式后再决定要不要做。** 如果要做，最小成本方案：

```python
from fastapi import Header

def _check(token: str | None = Header(None, alias="X-Admin-Token")):
    if token != config.ADMIN_TOKEN:
        raise HTTPException(403, "无权操作知识库")

@app.post("/api/kb/upload")
async def kb_upload(file: UploadFile = File(...), _=Depends(_check)):
    if file.size and file.size > 50 * 1024 * 1024:
        raise HTTPException(413, "文件超过 50MB")
```

---

#### I6 [建议修改] 向量库零集成测试，`chromadb` 在开发机上根本没装

**位置：** `tests/test_vectorstore.py:26, 43, 47`

**实测证据：**

```
SKIPPED [1] tests\test_vectorstore.py:26: chromadb 未安装
SKIPPED [1] tests\test_vectorstore.py:43: chromadb 未安装
SKIPPED [1] tests\test_vectorstore.py:47: chromadb 未安装
64 passed, 3 skipped
```

**为什么重要：** "64 passed" 这个数字会让人以为覆盖很充分，但 RAG 链路最核心的一环——ChromaDB 的真实读写——在这台机器上**一次都没被执行过**。`add` / `query` / `delete_by_source` / `list_sources` 的真实行为（尤其是 `configuration={"hnsw": {"space": "cosine"}}` 这个 1.x 新写法是否被当前版本接受）目前没有任何自动化证据。

**修复：** 在开发机装上 `chromadb`，让这 3 个测试真跑起来。至少在答辩前手动跑一次并截图留证。`pwtest.py` 算半个端到端验证，但它是脚本不是测试，不会在 `pytest` 里守门。

---

### Minor（仅供参考）

**M1 `/api/history` 忽略 `HISTORY_LIMIT` 配置** — `app/main.py:47`
`storage.get_history(agent.db_path, session_id)` 用的是函数默认 `limit=20`，而 `app/core.py:21` 用的是 `config.HISTORY_LIMIT`。改环境变量只有一半生效。补上 `limit=config.HISTORY_LIMIT` 即可。

**M2 `vectorstore.query` 重复调用 `count()`** — `app/kb/vectorstore.py:63, 67`
每次检索多一次全集合统计。存成局部变量 `n = col.count()` 就行。

**M3 每次读写都重跑 `CREATE TABLE IF NOT EXISTS`** — `app/storage.py:9-16`
幂等且代价很小，可接受。更干净的做法是抽出 `init_db()`，在 `app/main.py:19-22` 的 lifespan 里调一次。

**M4 txt/md 全部标记为第 1 页** — `app/kb/ingest.py:28`
出处卡一律显示"第1页"，对长 Markdown 讲义的定位价值不大。可以改用 chunk 序号，或按 Markdown 标题层级记 section 名。

**M5 `.agents/` 被提交进仓库，占了仓库 61% 的文件** — `.gitignore`
实测：`git ls-files .agents` 有 **82** 个文件，全仓库跟踪文件共 **135** 个。`.gitignore` 已忽略 `.shuncode/` 和 `.claude/`，唯独漏了 `.agents/`。评分时会稀释你自己的代码占比。建议：

```bash
echo ".agents/" >> .gitignore
git rm -r --cached .agents
```

**M6 根目录散落未跟踪的临时文件**
`chk.txt`、`push.log`、`pw_result.png`、`upsync.txt` 既没提交也没忽略。交作业前清掉或加进 `.gitignore`。

---

## 三、建议

### 修复顺序与工时估算

| 顺序 | 条目 | 预估 | 理由 |
| --- | --- | --- | --- |
| 1 | C2 LLM 失败兜底 | 30 min | 修的是规格违约，且改动最小 |
| 2 | C3 移除幂运算 | 10 min | 删一行 `ast.Pow` 即可 |
| 3 | C1 XSS 改事件委托 | 20 min | 安全问题，改法明确 |
| 4 | I2 连接关闭 | 15 min | 加 `closing()` |
| 5 | I3 容器加固 + 文档改口径 | 40 min | 答辩加分项 |
| 6 | I1 出处改接口返回 | 1 h | 要改 `search`/`dispatch`/`core` 三处 |
| 7 | I6 装 chromadb 跑通 3 个测试 | 30 min | 补上核心链路的自动化证据 |

**Critical 全部修完约 1 小时，加上 Important 约半天。**

### 其余建议

1. **I4 必须先决策再排期。** 补完第 4 个场景，还是调整规格缩小范围——这决定你剩下的时间怎么分配，不要拖。

2. **每修一条就补一个测试。** 现在 64 个测试是很好的底子，别让修复本身没有守门人：
   - C2 → 测"LLM 抛异常时用户消息仍落库且返回友好文案"
   - C3 → 测"`9**9**8` 被拒绝并返回错误提示"
   - I1 → 测"两线程并发时出处互不干扰"
   - I2 → 测"`with` 块退出后连接已关闭"

3. **文档与代码保持一致。** `技术文档-CloudOpsTutor.md` 里关于"五重防线"的表述按 I3 同步修正。评委很可能对着文档提问，文档说得比代码强会被当场问住。

4. **答辩叙事建议。** 这个项目最能打的三点是：手写 Function Calling 循环（不套 LangChain）、带出处的防幻觉 RAG、真实 Docker 沙箱。建议把演示脚本围绕这三点组织，并主动讲一句"黑名单是教学提示层，真正的隔离靠一次性容器"——主动暴露设计边界比被问出来更显专业。

---

## 四、评估

**可以合并吗：修完再合（Fix before merge）**

**理由：** 架构分层、依赖注入和测试纪律都达到了明显超出课程作业平均水准的程度，1457 行代码里没有一处架构性错误，`get_diagnostics` 零告警，64 个测试全绿。但存在 3 个**可现场触发**的 Critical：一句话挂死服务（C3）、一个文件名注入脚本（C1）、一次网络抖动丢用户数据（C2），其中 C2 直接违反项目自己的设计规格。这三条的修复成本都在 30 分钟以内，建议全部修完再打交付 tag。

---

## 五、总结

整体实现思路清晰，分层和测试纪律是这个项目最大的亮点，手写 Function Calling 循环和防幻觉 RAG 的设计都到位了。

主要问题：

1. **[必须修复]** 3 个可现场触发的缺陷：XSS（C1）、LLM 失败丢数据且违反规格（C2）、计算器 DoS（C3）
2. **[建议修改]** 并发下出处串号（I1）、连接泄漏（I2）、沙箱宣称与实现不符（I3）、验收标准 #4 未实现（I4）、知识库接口无防护（I5）、向量库零集成测试（I6）
3. **[仅供参考]** 6 条配置一致性、性能与仓库整洁问题

建议先用 1 小时清掉全部 Critical，再花半天处理 Important；I4 需要你先做"补完还是缩范围"的决策再排期。

---

## 附录：证据复现方式

所有 Critical / Important 结论均由以下脚本实跑产出，脚本存放在工作区之外（`/tmp`），不污染仓库：

| 编号 | 验证内容 | 脚本 |
| --- | --- | --- |
| P1 | SQLite 连接泄漏 | `/tmp/review_probe.py` |
| P2 | 沙箱黑名单绕过 | `/tmp/review_probe.py` |
| P3 | calculator 幂运算 DoS | `/tmp/review_probe.py` |
| P4 | LLM 失败丢用户消息 | `/tmp/review_probe.py` |
| P5 | 出处跨会话串号 | `/tmp/review_probe.py` |
| X1 | 恶意文件名后端放行判定 | `/tmp/xss3.py` |
| X2 | onclick 逃逸与 JS 可解析性 | `/tmp/xss4.js` |

复现命令：

```bash
PYTHONUTF8=1 PYTHONPATH="$(pwd)" python /tmp/review_probe.py
PYTHONUTF8=1 PYTHONPATH="$(pwd)" python /tmp/xss3.py
node /tmp/xss4.js
```

基线复现：

```bash
python -m pytest -q -rs
```

---

## 六、修复记录（2026-09-29 同日完成）

按报告给出的顺序执行，全程遵循 superpowers `test-driven-development`：先写失败测试 → 验证它因功能缺失而失败 → 实现最小改动 → 验证通过。

**红灯验证：** 新增测试首次运行 `26 failed, 62 passed, 3 skipped`。失败原因全部为功能缺失（`ValueError: too many values to unpack`、`KeyError: 'user'`、`RuntimeError: API 502`、`assert False`），无一条是笔误或写错断言。

**绿灯验证：** `python -m pytest -q` → **88 passed, 3 skipped, 1 warning in 5.22s**；`get_diagnostics` → **0 条**。

测试总数由 64 增至 88，新增 24 个回归测试。

### 已修复条目

| 编号 | 改动位置 | 做法 | 新增回归测试 |
| --- | --- | --- | --- |
| C1 XSS | `static/index.html` | 删除 `onclick` 拼接，改 `data-src` + 事件委托；`esc()` 补 `"` 与 `'` 转义 | 静态核验：`onclick="delSource(` 出现 0 次，`data-src=` 出现 1 次 |
| C2 LLM 失败丢数据 | `app/core.py` | 用户消息改为进循环前落库；循环整体包 `try/except`，失败返回"服务暂时繁忙，请稍后再试。" | `test_llm_failure_returns_friendly_reply`、`test_llm_failure_keeps_user_message`、`test_user_message_saved_exactly_once`、`test_chat_survives_llm_failure` |
| C3 计算器 DoS | `app/tools/registry.py` | 新增 `MAX_POW_EXPONENT=64` / `MAX_POW_BASE=10**6`，在求值前拦截 | `test_calculator_rejects_large_exponent`、`test_calculator_rejects_large_base`、`test_calculator_still_supports_small_power` |
| I1 出处并发串号 | `app/tools/rag_search.py`、`app/tools/registry.py`、`app/core.py` | 删除模块级 `_last_sources` 与 `pop_last_sources`；`search()` 改返回 `(文本, 出处)`，`dispatch()` 改返回 `(文本, 附带数据)` | `test_concurrent_sessions_do_not_share_sources`、`test_no_module_level_source_cache`、`test_dispatch_passes_through_extra_payload` |
| I2 连接泄漏 | `app/storage.py` | `with closing(_conn(...)) as c, c:` —— 外层关连接，内层提交事务 | `test_save_message_closes_connection`、`test_get_history_closes_connection` |
| I3 沙箱加固 | `app/tools/sandbox.py` | 黑名单补长选项 `--recursive`、`find -delete`、`shred`；容器补 `user="nobody"`、`read_only=True`、`cap_drop=["ALL"]`、`security_opt=["no-new-privileges"]`、`memswap_limit`，并挂 16MB tmpfs 保留可写 `/tmp`；模块文档改口径为"黑名单是教学提示层，隔离边界是一次性容器" | `test_long_options_and_equivalents_blocked`（6 例）、`test_normal_long_option_commands_still_pass`（4 例）、`test_container_hardening_flags` |
| M1 配置未生效 | `app/main.py` | `/api/history` 改用 `config.HISTORY_LIMIT` | `test_history_endpoint_respects_configured_limit` |
| M2 重复统计 | `app/kb/vectorstore.py` | `col.count()` 结果复用 | 由既有 `test_vectorstore.py` 覆盖（需装 chromadb 才会执行） |
| M5 / M6 仓库整洁 | `.gitignore` | 忽略 `.agents/` 与 `chk.txt`、`push.log`、`upsync.txt`、`pw_result.png` | 不适用 |

### 原始症状复测

不依赖测试套件，直接用最初发现缺陷的探针重跑一遍：

```
P1 连接泄漏     打开连接数: 2 | 全部已关闭: True
P2 黑名单       rm --recursive --force / -> 删除根目录      （原：未拦截）
                find / -delete           -> find 批量删除    （原：未拦截）
                shred /dev/sda           -> 磁盘安全擦除      （原：未拦截）
                rm --force /tmp/a.txt    -> 放行             （无误伤）
                find /etc -name '*.conf' -> 放行             （无误伤）
P3 计算器       9**9**8 -> 工具执行出错: 指数或底数过大…  耗时 0.000s（原：>8s 未返回）
                2**10   -> 1024                            （正常功能未受影响）
P4 LLM 失败     返回 {'reply': '服务暂时繁忙，请稍后再试。', 'sources': []}
                落库 [{'role':'user','content':'我的问题'}, {'role':'assistant',...}]
P5 并发出处     会话A -> A.pdf ；会话B -> B.pdf            （原：A 拿到 B.pdf、B 拿到空）
```

### 一处刻意的取舍

报告 I3 曾把 `cat /etc/shadow`、`> /etc/passwd` 列为绕过项，**本次未将其加入黑名单**。理由：它们在一个禁网、只读根、非 root、用完即焚的容器里没有实际危害，而 `cat /etc/*` 恰恰是云运维教学中的高频正常操作，拦截会误伤教学场景。真正的边界由容器提供，这一点已在模块文档中写明。

### 未完成项（需你决策后再动）

| 编号 | 状态 | 卡在哪 |
| --- | --- | --- |
| I4 验收标准 #4 | 未动 | 需先决定"补完出题/批改闭环"还是"调整规格缩小范围" |
| I5 知识库鉴权与限流 | 未动 | 需先确认部署方式：仅本机 `127.0.0.1` 演示则可降级为 [仅供参考]，挂局域网则应加固 |
| I6 chromadb 集成测试 | 未动 | 需在开发机执行 `pip install chromadb`（会改动本机 Python 环境，未擅自执行）；装好后 `tests/test_vectorstore.py` 的 3 个 skip 会变成真实执行 |
| M3 / M4 | 未动 | 纯优化项，不影响交付，留待你判断是否值得改 |

---

*本报告由 superpowers `requesting-code-review` 流程生成，遵循 `code-reviewer` 输出模板与 `chinese-code-review` 分级话术规范；修复阶段遵循 `test-driven-development` 红-绿循环；所有结论均经 `verification-before-completion` 取证，未经验证的推断不写入本文档。*
