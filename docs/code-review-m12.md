# M12 智能出题工具 — 代码审查报告

> 审查规范：`chinese-code-review` skill（分级标注：必须修复 / 建议修改 / 仅供参考 / 问题）
> 审查范围：`app/tools/quiz.py`、`app/storage.py`（quizzes 表）、`app/llm.py`（response_format）、`app/tools/registry.py`、`app/main.py`（/api/quiz/generate）、`tests/test_quiz*.py`
> 审查时间：2026-09-29 ｜ 审查结论：**1 个必须修复项已当场修复并补回归测试，其余为建议与参考项，可合入**

---

## [必须修复] LLM 网络异常穿透导致 REST 接口裸 500 ✅ 已修复

`app/tools/quiz.py` generate()：`llm.complete()` 在网络/限流层面抛出的异常（LLMClient 内部重试 2 次后仍失败）未被捕获，会直接穿透到 `main.py` 路由层。

原因：路由只捕获 `QuizError` 返回 422，其他异常变成裸 500，前端拿不到任何可读信息；对话场景虽有 dispatch 兜底，REST 场景（M19 练习页）会直接白屏。

修复：在 generate() 中把 LLM 调用包进 try/except，包装为 `QuizError("出题服务暂时不可用…")` 抛出；新增回归测试 `test_generate_wraps_llm_network_error`。验证：113/113 通过。

## [建议修改] topic 无长度限制，超长输入会原样注入 Prompt

`app/main.py` QuizRequest 与 `quiz.generate()` 均未限制 topic 长度。恶意或误操作传入几 KB 文本会拉高 token 消耗，也存在 Prompt 注入面。

建议：Pydantic 字段加 `max_length=50`（知识点名称不会超过这个数），generate() 同步截断。教学项目风险低，纳入 M13 迭代一并处理。

## [建议修改] 出题接口把 answer/explanation 一并返回给前端

`POST /api/quiz/generate` 响应包含正确答案与解析。学生在练习页 F12 即可看到答案。

说明：这与技术文档 M12 的 API 定义一致，且 M13 批改需要服务端存有答案（已落库）。建议 M19 练习页开发时增加"不含答案的出题响应"变体（如 `?with_answer=false`），本次不改接口契约。

## [问题] 单选题正确答案的位置分布是否会偏斜？

LLM 出题时正确答案常偏向 A/C。当前未做选项洗牌。是否需要在 generate() 落库前随机打乱 options 并同步换算 answer 字母？——留给 M13/M19 联调时观察真实分布再决定，避免过早优化。

## [仅供参考]

1. `storage.save_quiz()` 9 个位置参数偏多，可改用 dataclass/dict；但与现有 `save_message` 风格一致，保持不动。
2. `_FORMAT_HINTS`/`_PROMPT_TEMPLATE` 模块级常量命名与结构清晰，符合中英混排规范（中文说明 + 英文术语加空格）。
3. FakeLLM 用 `pop(0)` 脚本耗尽会 IndexError——测试内可控，反而能暴露多余调用，保留。
4. Commit message 已符合中文约定式提交（`feat(M12): …`）。

---

## 验证记录

| 验证层 | 结果 |
|--------|------|
| 本地 pytest（真实 DeepSeek key，含 2 个真实出题集成测试） | 113/113 通过 |
| VM pytest（.env 真实 key） | 112/112 通过（修复项后待复验 113） |
| 真实链路（对话出题→作答→解析→拒绝课外出题→REST→落库） | 全部通过 |
| DeepSeek JSON 模式官方四项要求（response_format/含 json 提示词/防截断/空内容重试） | 全部落实 |
