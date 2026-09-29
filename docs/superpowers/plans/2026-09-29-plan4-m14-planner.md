# M14 错题本聚合与学习规划 实现计划

> **面向 AI 代理的工作者：** 必需子技能：使用 superpowers:subagent-driven-development（推荐）或 superpowers:executing-plans 逐任务实现此计划。步骤使用复选框（`- [ ]`）语法来跟踪进度。

**目标：** 实现 `make_plan(days=7)`，把 `attempts` 错题本聚合成 Top-N 薄弱知识点，再生成一份带讲义出处的 N 天复习计划。

**架构：** 三段式，把确定性与生成性分开——① SQL 聚合出薄弱知识点排名（可断言、不经模型）；② 对每个知识点做 RAG 检索取真实讲义出处（防幻觉）；③ LLM 只负责把「统计 + 出处」组织成自然语言计划，且被约束只能用给定资料。

**技术栈：** `sqlite3`（复用 M03 storage）、`openai` SDK v3 JSON 模式（复用 M04 LLMClient）、复用 M07 `rag_search.search`、`pytest`、原生 JS 前端。

---

## 设计决策记录

| 冲突 / 待定 | 技术文档原文 | 本计划采用 | 理由 |
| --- | --- | --- | --- |
| 文件位置 | `app/study/planner.py`（新建独立包） | **`app/tools/planner.py`** | 其余四个 Agent 工具全在 `app/tools/`；M14 交互流程自述「Agent 调用」，它就是第五个工具，不该单开一个包 |
| 技术栈标注 | `openai` **1.x** | **SDK v3（3.20.x）** | 与 `requirements.txt`、`app/llm.py` 实际一致；同 M13 那处过时标注 |
| 薄弱点口径 | 未明确 | **以 `topic` 为主键 SQL 聚合**，`weak_points` 标签作为补充展示 | `topic` 与题目一一对应、可断言；`weak_points` 粒度不稳定（含「命令安全意识」这类跨知识点标签） |
| 生成方式 | 「规划 Prompt 结合 RAG 补充资料出处」 | **三段式：SQL 统计 → RAG 取出处 → LLM 仅做组织** | 分数与排名不能让模型编；出处必须来自真实检索 |
| 空错题本 | 未提及 | **抛 `PlannerError` 拒绝生成** | 与 `rag_search` 空结果拒答、`quiz` 无资料拒绝出题同一套防幻觉纪律 |
| 前端入口 | 未提及 | **对话工具 + 练习页按钮双入口** | M22 六步演示可在练习页一屏内走完，不用切页签 |

---

## 文件结构

| 文件 | 动作 | 职责 |
| --- | --- | --- |
| `app/storage.py` | 修改（文件尾） | 新增 `aggregate_weak_topics` 与 `weak_point_rows`，SQL 只出现在此模块 |
| `app/tools/planner.py` | 创建 | 薄弱点整理、RAG 取材、LLM 组织计划、工具入口 |
| `app/tools/registry.py` | 修改（`:11` 导入、`TOOLS` 尾、`HANDLERS`） | 注册 `make_study_plan` |
| `app/main.py` | 修改（导入、`/api/attempts` 之后） | 新增 `POST /api/plan` |
| `static/index.html` | 修改（练习页错题本卡片、JS 尾部） | 「根据错题生成复习计划」按钮与结果渲染 |
| `tests/test_planner.py` | 创建 | 聚合/排序/空态/校验/三段式/工具/REST |
| `技术文档-CloudOpsTutor.md` | 修改（M14、M16 条目） | 同步文件位置、技术栈、REST 端点 |

---

## 任务 1：storage 聚合查询

**文件：** 修改 `app/storage.py`（`list_attempts` 之后）；测试 `tests/test_planner.py`

- [ ] **步骤 1：编写失败的测试**

创建 `tests/test_planner.py`：

```python
"""M14 学习规划测试：聚合排序 / 空态 / 校验 / 三段式 / 工具 / REST。"""
import json
from types import SimpleNamespace

import pytest

from app import config, storage
from app.tools import planner


def _attempt(db, topic, score, weak=None, qtype="单选题"):
    qid = storage.save_quiz(db, topic, "中等", qtype, "题干", "[]",
                            "A", "解析", "第5章.md")
    storage.save_attempt(db, qid, topic, qtype, "B", score, "点评",
                         json.dumps(weak or [], ensure_ascii=False))


def test_aggregate_orders_by_wrong_count_desc(tmp_path):
    db = str(tmp_path / "t.db")
    _attempt(db, "Nginx 反向代理", 0)
    _attempt(db, "Nginx 反向代理", 0)
    _attempt(db, "Linux 文件查看", 0)
    _attempt(db, "Docker 数据卷", 100)          # 全对，不该出现
    rows = storage.aggregate_weak_topics(db, max_score=60, limit=5)
    assert [r["topic"] for r in rows] == ["Nginx 反向代理", "Linux 文件查看"]
    assert rows[0]["wrong_count"] == 2
    assert rows[0]["total_count"] == 2
    assert rows[0]["avg_score"] == 0.0


def test_aggregate_excludes_all_correct_topics(tmp_path):
    db = str(tmp_path / "t.db")
    _attempt(db, "Docker 数据卷", 100)
    assert storage.aggregate_weak_topics(db, max_score=60, limit=5) == []


def test_aggregate_respects_limit(tmp_path):
    db = str(tmp_path / "t.db")
    for i in range(4):
        _attempt(db, "知识点%d" % i, 0)
    assert len(storage.aggregate_weak_topics(db, max_score=60, limit=2)) == 2


def test_weak_point_rows_returns_raw_json_strings(tmp_path):
    db = str(tmp_path / "t.db")
    _attempt(db, "Nginx 反向代理", 0, weak=["Nginx 反向代理", "反向代理原理"])
    rows = storage.weak_point_rows(db, "Nginx 反向代理", max_score=60)
    assert rows == ['["Nginx 反向代理", "反向代理原理"]']
```

- [ ] **步骤 2：运行测试验证失败**

运行：`python -m pytest tests/test_planner.py -q`
预期：FAIL，`ModuleNotFoundError: No module named 'app.tools.planner'`

- [ ] **步骤 3：建空模块再跑一次**

创建 `app/tools/planner.py`，内容仅一行：

```python
"""M14 学习规划工具（实现中）。"""
```

运行：`python -m pytest tests/test_planner.py -q`
预期：FAIL，`AttributeError: module 'app.storage' has no attribute 'aggregate_weak_topics'`

- [ ] **步骤 4：编写最少实现代码**

在 `app/storage.py` 的 `list_attempts` 之后追加：

```python
def aggregate_weak_topics(db_path, max_score=60, limit=5):
    """按 topic 聚合错题，返回薄弱知识点排名（M14）。

    排序：错题数多的在前；错题数相同时平均分低的在前。
    只返回至少错过一次的知识点。
    """
    with closing(_conn(db_path)) as c:
        rows = c.execute(
            "SELECT topic,"
            " SUM(CASE WHEN score < ? THEN 1 ELSE 0 END) AS wrong,"
            " COUNT(*) AS total,"
            " AVG(score) AS avg_score"
            " FROM attempts GROUP BY topic"
            " HAVING wrong > 0"
            " ORDER BY wrong DESC, avg_score ASC, topic ASC"
            " LIMIT ?",
            (max_score, limit),
        ).fetchall()
    return [
        {"topic": t, "wrong_count": w, "total_count": n,
         "avg_score": round(a, 1)}
        for t, w, n, a in rows
    ]


def weak_point_rows(db_path, topic, max_score=60, limit=20):
    """取某知识点下错题的 weak_points 原始 JSON 文本（解析交给调用方）。"""
    with closing(_conn(db_path)) as c:
        rows = c.execute(
            "SELECT weak_points FROM attempts"
            " WHERE topic=? AND score < ? ORDER BY id DESC LIMIT ?",
            (topic, max_score, limit),
        ).fetchall()
    return [r[0] for r in rows]
```

- [ ] **步骤 5：运行测试验证通过**

运行：`python -m pytest tests/test_planner.py -q`
预期：4 passed

- [ ] **步骤 6：Commit**

```bash
git add app/storage.py app/tools/planner.py tests/test_planner.py
git commit -m "feat(M14): attempts 按知识点聚合的薄弱点统计查询"
```

---

## 任务 2：薄弱知识点整理

**文件：** 修改 `app/tools/planner.py`；测试 `tests/test_planner.py`

- [ ] **步骤 1：编写失败的测试**

追加到 `tests/test_planner.py`：

```python
def test_weak_topics_merges_labels_and_dedups(tmp_path):
    db = str(tmp_path / "t.db")
    _attempt(db, "Nginx 反向代理", 0, weak=["Nginx 反向代理", "反向代理原理"])
    _attempt(db, "Nginx 反向代理", 40, weak=["反向代理原理"])
    rows = planner.weak_topics(db_path=db)
    assert len(rows) == 1
    r = rows[0]
    assert r["topic"] == "Nginx 反向代理"
    assert r["wrong_count"] == 2
    assert r["labels"] == ["Nginx 反向代理", "反向代理原理"]  # 去重且保序


def test_weak_topics_tolerates_broken_weak_points_json(tmp_path):
    db = str(tmp_path / "t.db")
    qid = storage.save_quiz(db, "X", "中等", "单选题", "q", "[]", "A", "e", "s.md")
    storage.save_attempt(db, qid, "X", "单选题", "B", 0, "点评", "不是JSON")
    rows = planner.weak_topics(db_path=db)
    assert rows[0]["labels"] == []          # 坏数据不炸，降级为空


def test_weak_topics_empty_returns_empty_list(tmp_path):
    assert planner.weak_topics(db_path=str(tmp_path / "t.db")) == []
```

- [ ] **步骤 2：运行测试验证失败**

运行：`python -m pytest tests/test_planner.py -k weak_topics -q`
预期：FAIL，`AttributeError: module 'app.tools.planner' has no attribute 'weak_topics'`

- [ ] **步骤 3：编写最少实现代码**

把 `app/tools/planner.py` 全文替换为：

```python
"""M14 错题本聚合与学习规划：SQL 统计 -> RAG 取出处 -> LLM 组织计划。

三段式的用意是把确定性与生成性分开：
- 薄弱知识点的排名与分数来自 SQL 聚合，模型改不了也编不出；
- 每个知识点的讲义出处来自真实 RAG 检索，不是模型杜撰；
- LLM 只负责把上面两样组织成自然语言计划，且被要求不得超出给定资料。

错题本为空时直接拒绝生成，与 rag_search 空结果拒答、
quiz 无资料拒绝出题保持同一套防幻觉纪律。
"""
import json

from app import config, storage
from app.tools import rag_search
from app.tools.grader import PASS_SCORE

DEFAULT_TOP_N = 5
MIN_DAYS = 1
MAX_DAYS = 30

_llm = None


class PlannerError(Exception):
    """无法生成计划（错题本为空 / 天数非法 / 模型不可用）。"""


def _get_llm():
    """LLM 客户端懒加载单例；测试可通过 make_plan(llm=...) 注入。"""
    global _llm
    if _llm is None:
        from app.llm import LLMClient

        _llm = LLMClient()
    return _llm


def weak_topics(db_path=None, top_n=DEFAULT_TOP_N):
    """返回 Top-N 薄弱知识点，附合并去重后的细粒度标签。"""
    db_path = db_path or config.DB_PATH
    rows = storage.aggregate_weak_topics(
        db_path, max_score=PASS_SCORE, limit=top_n
    )
    for row in rows:
        labels = []
        for raw in storage.weak_point_rows(
            db_path, row["topic"], max_score=PASS_SCORE
        ):
            try:
                parsed = json.loads(raw or "[]")
            except (json.JSONDecodeError, TypeError):
                continue  # 坏数据不该让整份计划挂掉
            if not isinstance(parsed, list):
                continue
            for label in parsed:
                if isinstance(label, str) and label not in labels:
                    labels.append(label)
        row["labels"] = labels
    return rows
```

- [ ] **步骤 4：运行测试验证通过**

运行：`python -m pytest tests/test_planner.py -q`
预期：7 passed

- [ ] **步骤 5：Commit**

```bash
git add app/tools/planner.py tests/test_planner.py
git commit -m "feat(M14): 薄弱知识点整理(标签合并去重+坏数据降级)"
```

---

## 任务 3：计划结构校验

**文件：** 修改 `app/tools/planner.py`；测试 `tests/test_planner.py`

- [ ] **步骤 1：编写失败的测试**

追加到 `tests/test_planner.py`：

```python
def test_valid_plan_passes():
    data = {"daily_plan": [
        {"day": 1, "topic": "A", "focus": "重点", "practice": "练习"},
        {"day": 2, "topic": "B", "focus": "重点", "practice": "练习"},
    ]}
    assert planner.validate_plan(data, days=2) is None


@pytest.mark.parametrize("bad,why", [
    ({}, "缺 daily_plan"),
    ({"daily_plan": "不是数组"}, "类型错"),
    ({"daily_plan": [{"day": 1, "topic": "A", "focus": "f", "practice": "p"}]},
     "天数不符"),
    ({"daily_plan": [{"day": 2, "topic": "A", "focus": "f", "practice": "p"},
                     {"day": 1, "topic": "B", "focus": "f", "practice": "p"}]},
     "day 不连续"),
    ({"daily_plan": [{"day": 1, "topic": "", "focus": "f", "practice": "p"},
                     {"day": 2, "topic": "B", "focus": "f", "practice": "p"}]},
     "字段为空"),
])
def test_invalid_plan_rejected(bad, why):
    assert planner.validate_plan(bad, days=2) is not None, why
```

- [ ] **步骤 2：运行测试验证失败**

运行：`python -m pytest tests/test_planner.py -k plan -q`
预期：FAIL，`AttributeError: ... has no attribute 'validate_plan'`

- [ ] **步骤 3：编写最少实现代码**

在 `app/tools/planner.py` 的 `weak_topics` 之后追加：

```python
def validate_plan(data, days):
    """校验 LLM 产出的计划结构；合格返回 None，否则返回原因。"""
    if not isinstance(data, dict):
        return "输出不是 JSON 对象"
    plan = data.get("daily_plan")
    if not isinstance(plan, list):
        return "daily_plan 缺失或不是数组"
    if len(plan) != days:
        return f"daily_plan 应有 {days} 项，实际 {len(plan)} 项"
    for i, item in enumerate(plan, start=1):
        if not isinstance(item, dict):
            return f"第 {i} 项不是对象"
        if item.get("day") != i:
            return f"第 {i} 项的 day 应为 {i}"
        for key in ("topic", "focus", "practice"):
            value = item.get(key)
            if not isinstance(value, str) or not value.strip():
                return f"第 {i} 项的 {key} 缺失或为空"
    return None
```

- [ ] **步骤 4：运行测试验证通过**

运行：`python -m pytest tests/test_planner.py -q`
预期：13 passed

- [ ] **步骤 5：Commit**

```bash
git add app/tools/planner.py tests/test_planner.py
git commit -m "feat(M14): 复习计划结构校验(天数/day连续性/字段非空)"
```

---

## 任务 4：make_plan 三段式主流程

**文件：** 修改 `app/tools/planner.py`；测试 `tests/test_planner.py`

- [ ] **步骤 1：编写失败的测试**

追加到 `tests/test_planner.py`：

```python
class FakeLLM:
    def __init__(self, *contents):
        self.contents = list(contents)
        self.calls = []

    def complete(self, messages, tools=None, response_format=None):
        self.calls.append({"messages": messages,
                           "response_format": response_format})
        return SimpleNamespace(content=self.contents.pop(0))


def _plan_json(days):
    return json.dumps({"daily_plan": [
        {"day": d, "topic": "Nginx 反向代理", "focus": "重点", "practice": "练习"}
        for d in range(1, days + 1)]}, ensure_ascii=False)


@pytest.fixture()
def patched_rag(monkeypatch):
    calls = []

    def fake_search(query):
        calls.append(query)
        return ("[来源: 第5章-Nginx服务部署.md 第1页] proxy_pass 说明",
                [{"source": "第5章-Nginx服务部署.md", "page": 1,
                  "excerpt": "proxy_pass", "score": 0.8}])

    monkeypatch.setattr(planner.rag_search, "search", fake_search)
    return calls


def test_make_plan_empty_wrong_book_raises(tmp_path):
    with pytest.raises(planner.PlannerError, match="还没有错题"):
        planner.make_plan(days=3, db_path=str(tmp_path / "t.db"))


@pytest.mark.parametrize("days", [0, -1, 31])
def test_make_plan_rejects_bad_days(tmp_path, days):
    with pytest.raises(planner.PlannerError, match="天数"):
        planner.make_plan(days=days, db_path=str(tmp_path / "t.db"))


def test_make_plan_queries_rag_for_each_topic(tmp_path, patched_rag):
    db = str(tmp_path / "t.db")
    _attempt(db, "Nginx 反向代理", 0)
    _attempt(db, "Linux 文件查看", 0)
    planner.make_plan(days=2, db_path=db, llm=FakeLLM(_plan_json(2)))
    assert patched_rag == ["Nginx 反向代理", "Linux 文件查看"]


def test_make_plan_returns_stats_and_sources(tmp_path, patched_rag):
    db = str(tmp_path / "t.db")
    _attempt(db, "Nginx 反向代理", 0, weak=["反向代理原理"])
    result = planner.make_plan(days=2, db_path=db, llm=FakeLLM(_plan_json(2)))
    assert result["days"] == 2
    assert result["weak_topics"][0]["topic"] == "Nginx 反向代理"
    assert result["weak_topics"][0]["wrong_count"] == 1
    assert result["weak_topics"][0]["labels"] == ["反向代理原理"]
    assert result["sources"] == ["第5章-Nginx服务部署.md"]
    assert len(result["daily_plan"]) == 2


def test_make_plan_uses_json_mode(tmp_path, patched_rag):
    db = str(tmp_path / "t.db")
    _attempt(db, "Nginx 反向代理", 0)
    llm = FakeLLM(_plan_json(1))
    planner.make_plan(days=1, db_path=db, llm=llm)
    assert llm.calls[0]["response_format"] == {"type": "json_object"}
    prompt = llm.calls[0]["messages"][0]["content"]
    assert "json" in prompt.lower()
    assert "不得编造" in prompt


def test_make_plan_retries_once_on_bad_json(tmp_path, patched_rag):
    db = str(tmp_path / "t.db")
    _attempt(db, "Nginx 反向代理", 0)
    llm = FakeLLM("这不是json", _plan_json(1))
    result = planner.make_plan(days=1, db_path=db, llm=llm)
    assert len(result["daily_plan"]) == 1
    assert len(llm.calls) == 2


def test_make_plan_two_failures_raise(tmp_path, patched_rag):
    db = str(tmp_path / "t.db")
    _attempt(db, "Nginx 反向代理", 0)
    with pytest.raises(planner.PlannerError, match="生成失败"):
        planner.make_plan(days=1, db_path=db, llm=FakeLLM("坏", "还是坏"))


def test_make_plan_wraps_llm_network_error(tmp_path, patched_rag):
    db = str(tmp_path / "t.db")
    _attempt(db, "Nginx 反向代理", 0)

    class BoomLLM:
        def complete(self, messages, tools=None, response_format=None):
            raise RuntimeError("Connection reset")

    with pytest.raises(planner.PlannerError, match="暂时不可用"):
        planner.make_plan(days=1, db_path=db, llm=BoomLLM())
```

- [ ] **步骤 2：运行测试验证失败**

运行：`python -m pytest tests/test_planner.py -k make_plan -q`
预期：FAIL，`AttributeError: ... has no attribute 'make_plan'`

- [ ] **步骤 3：编写最少实现代码**

在 `app/tools/planner.py` 的 `_llm = None` 之前插入 Prompt 模板：

```python
# 示例 JSON 的花括号写成 {{ }}，整段要走 str.format()
_PLAN_PROMPT = (
    "你是云计算运维课程的学习规划老师。下面给出某学生的错题统计，"
    "以及每个薄弱知识点对应的课程讲义摘录。\n"
    "请为他制定一份 {days} 天的复习计划。\n"
    "要求：\n"
    "1. 每天聚焦一个知识点，错得多、平均分低的排在前面；\n"
    "2. 每天给出「复习重点」与「练习建议」，练习建议要具体可执行；\n"
    "3. 只能依据下面给出的讲义摘录，不得编造讲义内容或出处；\n"
    "4. 若薄弱知识点少于天数，可对同一知识点分阶段安排，但不要硬凑无关内容；\n"
    "5. 只输出一个严格合法的 json 对象，不要输出其他任何内容。\n"
    "EXAMPLE JSON OUTPUT:\n"
    '{{"daily_plan": [{{"day": 1, "topic": "知识点名", '
    '"focus": "复习重点", "practice": "练习建议"}}]}}\n'
    "daily_plan 必须恰好 {days} 项，day 从 1 起连续递增。\n\n"
    "学生错题统计：\n{stats}\n\n"
    "课程讲义摘录：\n{material}\n"
)
```

在 `validate_plan` 之后追加：

```python
def make_plan(days=7, db_path=None, llm=None, top_n=DEFAULT_TOP_N):
    """生成复习计划（技术文档 M14 对外 API）。

    三段式：SQL 统计 -> RAG 取真实出处 -> LLM 仅做组织。
    """
    if not isinstance(days, int) or isinstance(days, bool):
        raise PlannerError("天数必须是整数")
    if not MIN_DAYS <= days <= MAX_DAYS:
        raise PlannerError(f"天数需在 {MIN_DAYS}-{MAX_DAYS} 之间")

    db_path = db_path or config.DB_PATH
    topics = weak_topics(db_path=db_path, top_n=top_n)
    if not topics:
        raise PlannerError(
            "还没有错题记录，无法生成针对性复习计划。"
            "先到「练习与批改」做几道题吧。"
        )

    # 第二段：每个薄弱知识点做一次真实检索，出处不是模型编的
    blocks, sources = [], []
    for row in topics:
        text, hits = rag_search.search(row["topic"])
        blocks.append(f"【{row['topic']}】\n{text[:800]}")
        for hit in hits:
            if hit["source"] not in sources:
                sources.append(hit["source"])

    stats = "\n".join(
        "- {topic}：做过 {total} 题，错 {wrong} 题，平均 {avg} 分{extra}".format(
            topic=r["topic"], total=r["total_count"], wrong=r["wrong_count"],
            avg=r["avg_score"],
            extra=("；薄弱点：" + "、".join(r["labels"])) if r["labels"] else "",
        )
        for r in topics
    )
    prompt = _PLAN_PROMPT.format(
        days=days, stats=stats, material="\n\n".join(blocks)
    )

    llm = llm or _get_llm()
    last_reason = "未知原因"
    for _ in range(2):  # 首次 + 重试 1 次（与 M12/M13 一致）
        try:
            msg = llm.complete(
                [{"role": "user", "content": prompt}],
                response_format={"type": "json_object"},
            )
        except Exception as err:
            raise PlannerError(
                f"学习规划服务暂时不可用（{err.__class__.__name__}），请稍后再试"
            ) from err
        content = (getattr(msg, "content", None) or "").strip()
        if not content:
            last_reason = "模型返回空内容"
            continue
        try:
            data = json.loads(content)
        except json.JSONDecodeError:
            last_reason = "JSON 解析失败"
            continue
        reason = validate_plan(data, days)
        if reason is None:
            return {
                "days": days,
                "weak_topics": topics,
                "daily_plan": data["daily_plan"],
                "sources": sources,
            }
        last_reason = reason
    raise PlannerError(f"复习计划生成失败（{last_reason}），请重试一次")
```

- [ ] **步骤 4：运行测试验证通过**

运行：`python -m pytest tests/test_planner.py -q`
预期：24 passed

- [ ] **步骤 5：Commit**

```bash
git add app/tools/planner.py tests/test_planner.py
git commit -m "feat(M14): make_plan三段式(SQL统计+RAG出处+LLM组织)"
```

---

## 任务 5：Agent 工具入口与注册

**文件：** 修改 `app/tools/planner.py`、`app/tools/registry.py`；测试 `tests/test_planner.py`

- [ ] **步骤 1：编写失败的测试**

追加到 `tests/test_planner.py`：

```python
def test_study_plan_tool_registered():
    from app.tools import registry

    names = [t["function"]["name"] for t in registry.TOOLS]
    assert "make_study_plan" in names
    assert registry.HANDLERS["make_study_plan"] is planner.make_study_plan
    schema = next(t for t in registry.TOOLS
                  if t["function"]["name"] == "make_study_plan")
    assert set(schema["function"]["parameters"]["properties"]) == {"days"}


def test_study_plan_tool_text(tmp_path, monkeypatch, patched_rag):
    db = str(tmp_path / "t.db")
    monkeypatch.setattr(config, "DB_PATH", db)
    _attempt(db, "Nginx 反向代理", 0)
    monkeypatch.setattr(planner, "_get_llm", lambda: FakeLLM(_plan_json(2)))
    text = planner.make_study_plan(days=2)
    assert "第 1 天" in text and "第 2 天" in text
    assert "Nginx 反向代理" in text
    assert "第5章-Nginx服务部署.md" in text


def test_study_plan_tool_error_as_text(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "DB_PATH", str(tmp_path / "t.db"))
    assert planner.make_study_plan(days=7).startswith("暂时无法生成复习计划：")
```

- [ ] **步骤 2：运行测试验证失败**

运行：`python -m pytest tests/test_planner.py -k study_plan -q`
预期：FAIL，`AttributeError: ... has no attribute 'make_study_plan'`

- [ ] **步骤 3：编写最少实现代码**

在 `app/tools/planner.py` 末尾追加：

```python
def make_study_plan(days=7):
    """Agent 工具入口：返回给 LLM 转述的 markdown 计划（registry 调用）。"""
    try:
        r = make_plan(int(days))
    except (PlannerError, ValueError, TypeError) as err:
        return f"暂时无法生成复习计划：{err}"
    lines = [f"已根据错题本生成 {r['days']} 天复习计划。", "", "薄弱知识点排名："]
    lines += [
        "{i}. {topic}（错 {wrong}/{total} 题，平均 {avg} 分）".format(
            i=i, topic=t["topic"], wrong=t["wrong_count"],
            total=t["total_count"], avg=t["avg_score"])
        for i, t in enumerate(r["weak_topics"], start=1)
    ]
    lines.append("")
    for item in r["daily_plan"]:
        lines.append(f"第 {item['day']} 天 · {item['topic']}")
        lines.append(f"  复习重点：{item['focus']}")
        lines.append(f"  练习建议：{item['practice']}")
    if r["sources"]:
        lines.append("")
        lines.append("参考讲义：" + "、".join(r["sources"]))
    return "\n".join(lines)
```

修改 `app/tools/registry.py:11`：

```python
from app.tools import grader, planner, quiz, rag_search, sandbox
```

在 `TOOLS` 列表末尾（`grade_answer` 条目之后、`]` 之前）追加：

```python
    {
        "type": "function",
        "function": {
            "name": "make_study_plan",
            "description": (
                "根据学生错题本生成针对性复习计划：先统计做错最多的知识点，"
                "再检索对应课程讲义，最后排出逐天的复习重点与练习建议。"
                "学生要求复习计划、学习规划、不知道该复习什么时调用本工具；"
                "错题本为空时会明确拒绝，不会编造计划"
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "days": {
                        "type": "integer",
                        "description": "计划天数，默认 7，可选范围 1-30",
                    },
                },
            },
        },
    },
```

修改 `HANDLERS`，在 `"grade_answer"` 之后追加一行：

```python
    "make_study_plan": planner.make_study_plan,
```

- [ ] **步骤 4：运行测试验证通过**

运行：`python -m pytest tests/test_planner.py tests/test_registry.py -q`
预期：全部 passed

- [ ] **步骤 5：Commit**

```bash
git add app/tools/planner.py app/tools/registry.py tests/test_planner.py
git commit -m "feat(M14): make_study_plan工具入口并注册到Function Calling"
```

---

## 任务 6：REST 路由与前端入口

**文件：** 修改 `app/main.py`、`static/index.html`；测试 `tests/test_planner.py`

- [ ] **步骤 1：编写失败的测试**

追加到 `tests/test_planner.py`：

```python
def test_api_plan_ok(tmp_path, monkeypatch, patched_rag):
    from fastapi.testclient import TestClient

    from app import main
    from app.core import Agent

    db = str(tmp_path / "t.db")
    monkeypatch.setattr(main, "agent", Agent(None, db))
    _attempt(db, "Nginx 反向代理", 0)
    monkeypatch.setattr(planner, "_get_llm", lambda: FakeLLM(_plan_json(3)))
    r = TestClient(main.app).post("/api/plan", json={"days": 3})
    assert r.status_code == 200
    body = r.json()
    assert body["days"] == 3
    assert len(body["daily_plan"]) == 3
    assert body["weak_topics"][0]["topic"] == "Nginx 反向代理"


def test_api_plan_empty_wrong_book_422(tmp_path, monkeypatch):
    from fastapi.testclient import TestClient

    from app import main
    from app.core import Agent

    monkeypatch.setattr(main, "agent", Agent(None, str(tmp_path / "t.db")))
    r = TestClient(main.app).post("/api/plan", json={"days": 7})
    assert r.status_code == 422
    assert "还没有错题" in r.json()["detail"]


def test_api_plan_rejects_out_of_range_days(tmp_path, monkeypatch):
    from fastapi.testclient import TestClient

    from app import main
    from app.core import Agent

    monkeypatch.setattr(main, "agent", Agent(None, str(tmp_path / "t.db")))
    r = TestClient(main.app).post("/api/plan", json={"days": 99})
    assert r.status_code == 422
```

- [ ] **步骤 2：运行测试验证失败**

运行：`python -m pytest tests/test_planner.py -k api_plan -q`
预期：FAIL，三个用例均返回 404（路由未注册）

- [ ] **步骤 3：编写最少实现代码**

修改 `app/main.py` 的工具导入行：

```python
from app.tools import grader, planner, quiz
```

在 `GradeRequest` 类之后追加请求模型：

```python
class PlanRequest(BaseModel):
    # 与 planner.MIN_DAYS / MAX_DAYS 对齐，越界在入口就拒绝
    days: int = Field(default=7, ge=1, le=30)
```

在 `attempts` 路由之后追加：

```python
@app.post("/api/plan")
def study_plan(req: PlanRequest):
    """M14 根据错题本生成复习计划。"""
    try:
        return planner.make_plan(req.days, db_path=agent.db_path)
    except planner.PlannerError as err:
        # 错题本为空/天数非法/模型不可用：语义化 422
        raise HTTPException(status_code=422, detail=str(err))
```

在 `static/index.html` 的错题本卡片头部按钮组中，`f-all` 按钮之后追加：

```html
            <button class="btn sm" id="mkplan">生成复习计划</button>
```

在错题本卡片的 `</div>` 之前（`<div id="wb">` 之后）追加计划展示容器：

```html
        <div id="plan-box" style="display:none;margin-top:16px;
          border-top:1px solid var(--border);padding-top:16px;"></div>
```

在 `static/index.html` 的 `setWb` 函数之后追加：

```javascript
$("#mkplan").addEventListener("click", async () => {
  const btn = $("#mkplan"), box = $("#plan-box");
  btn.disabled = true; btn.innerHTML = '<span class="spin"></span>生成中';
  box.style.display = ""; box.innerHTML = '<div class="sk"></div><div class="sk" style="width:70%"></div>';
  try{
    const p = await api("/api/plan", { method: "POST", body: JSON.stringify({ days: 7 }) });
    box.innerHTML = `
      <div class="card-h" style="margin-bottom:12px">
        ${icon(I.book, 16)}<h2>${esc(p.days)} 天复习计划</h2>
        <span class="chip brand">依据 ${p.weak_topics.length} 个薄弱知识点</span></div>
      <div style="display:flex;gap:6px;flex-wrap:wrap;margin-bottom:14px">
        ${p.weak_topics.map(t => `<span class="chip danger">${esc(t.topic)}
          · 错 ${esc(t.wrong_count)}/${esc(t.total_count)}</span>`).join("")}
      </div>
      ${p.daily_plan.map(d => `
        <div class="src" style="align-items:flex-start">
          <span class="chip brand" style="flex-shrink:0">第 ${esc(d.day)} 天</span>
          <div style="min-width:0">
            <div style="font-weight:600;margin-bottom:4px">${esc(d.topic)}</div>
            <div style="color:var(--muted-fg);line-height:1.75">
              复习重点：${esc(d.focus)}<br>练习建议：${esc(d.practice)}</div>
          </div></div>`).join("")}
      ${p.sources.length ? `<div class="meta-line">${icon(I.book, 14)}
        参考讲义：${p.sources.map(esc).join("、")}</div>` : ""}`;
  }catch(err){
    box.innerHTML = `<div class="empty">${icon(I.alert, 30)}${esc(err.message)}</div>`;
  }finally{
    btn.disabled = false; btn.textContent = "生成复习计划";
  }
});
```

把 `static/index.html` 顶部副标题补上学习规划：

```html
    <div class="brand-txt"><b>CloudOps Tutor</b><span>云运维学习助教 · RAG 知识库 · 沙箱实操 · 智能批改 · 学习规划</span></div>
```

- [ ] **步骤 4：运行测试验证通过**

运行：`python -m pytest -q`
预期：全部 passed，`get_diagnostics` 0 条

- [ ] **步骤 5：Commit**

```bash
git add app/main.py static/index.html tests/test_planner.py
git commit -m "feat(M14): 复习计划REST接口与练习页入口"
```

---

## 任务 7：同步技术文档

**文件：** 修改 `技术文档-CloudOpsTutor.md`（M14、M16 条目）

- [ ] **步骤 1：修正 M14 条目**

把物理文件路径由 `app/study/planner.py` 改为 `app/tools/planner.py`（与其余四个工具同目录），技术栈由 `openai 1.x` 改为 `openai SDK v3（3.20.x，JSON 模式）`，并补充三段式说明、REST 端点 `POST /api/plan`、空错题本拒绝策略。

- [ ] **步骤 2：修正 M16 条目**

标注全部端点当前实现在 `app/main.py`（未拆分 `app/api/routes.py`），并把 `plan 生成` 标记为已实现。

- [ ] **步骤 3：Commit**

```bash
git add 技术文档-CloudOpsTutor.md
git commit -m "docs(M14,M16): 修正planner文件位置与技术栈,补REST端点"
```

---

## 任务 8：全量回归与部署验证

- [ ] **步骤 1：本地全量**

运行：`python -m pytest -q`，预期 `178 passed, 5 skipped`
运行 MCP 工具 `get_diagnostics`（scope `.`），预期 0 条

- [ ] **步骤 2：真实数据探针**

写一次性脚本，塞入若干条已知分数的作答记录，断言 `weak_topics` 的排名顺序与 `wrong_count` 与手工计算一致，证明聚合口径正确。

- [ ] **步骤 3：上传 VM 并逐文件 md5 核对**

```bash
tar czf - --exclude='__pycache__' --exclude='*.pyc' app static tests docs \
  requirements.txt .env.example deploy.sh apitest.sh pwtest.py pwtest_ui.py \
  | ssh root@192.168.100.136 "cd /root/szpu-agent && tar xzf -"
```

- [ ] **步骤 4：VM 编译四件套**

`compileall` / `pip install -r requirements.txt` / `pytest` / `import app.main`，退出码必须全为 0

- [ ] **步骤 5：Playwright 六步闭环**

扩充 `pwtest_ui.py`：出题 → 作答 → 批改 → 错题本 → **点「生成复习计划」→ 断言出现「第 1 天」与参考讲义** → 控制台零报错

- [ ] **步骤 6：停止点 —— 合并 main 前请示用户**

---

## 计划自检结果

**1. 规格覆盖度**

| 技术文档 M14 要求 | 对应任务 |
| --- | --- |
| 聚合错题本 | 任务 1（SQL）+ 任务 2（标签合并） |
| 统计薄弱知识点 Top-N | 任务 1 `limit` + 任务 2 `top_n` |
| 生成 7 天复习计划（每天知识点+练习建议） | 任务 3（校验）+ 任务 4（生成） |
| `make_plan(days=7) -> {weak_topics, daily_plan}` | 任务 4（返回值为其超集，另含 `days` 与 `sources`） |
| SQL 聚合统计 | 任务 1 |
| 规划 Prompt 结合 RAG 补充资料出处 | 任务 4 第二段 |
| 交互流程「用户请求→Agent 调用→返回 markdown」 | 任务 5 |

设计规格 §1 验收标准 4 的「学习规划」由任务 4/5/6 共同覆盖；§4 数据流第 4 条「错题本→学习规划」由任务 1/2 覆盖。

**2. 占位符扫描**：无 TODO／待定／"类似任务 N"／无代码的代码步骤。

**3. 类型一致性**：
- `storage.aggregate_weak_topics` 返回 `{topic, wrong_count, total_count, avg_score}`，任务 2 在其上补 `labels`，任务 4/5/6 一路沿用同名字段。
- `rag_search.search(query)` 返回 `(text, sources)` 元组，与 `app/tools/rag_search.py` 现状一致。
- `PASS_SCORE` 从 `app.tools.grader` 导入，不重复定义魔数。
- `MIN_DAYS=1 / MAX_DAYS=30` 与 `PlanRequest` 的 `ge=1, le=30` 一致。
- 前端 `p.weak_topics[].wrong_count / total_count`、`p.daily_plan[].day/topic/focus/practice`、`p.sources` 与任务 4 返回值逐字对应。
