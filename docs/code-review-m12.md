# M12 智能出题工具 — 代码审查报告

> 审查规范：`chinese-code-review` skill（分级标注：必须修复 / 建议修改 / 仅供参考 / 问题）
> 审查范围：`app/tools/quiz.py`、`app/storage.py`（quizzes 表）、`app/llm.py`（response_format）、`app/tools/registry.py`、`app/main.py`（/api/quiz/generate）、`tests/test_quiz*.py`
> 审查时间：2026-09-29 ｜ 审查结论：**全部整改完成——1 个必须修复项 + 2 个建议修改项 + 1 个问题项均已修复并补回归测试（117/117 通过）**

---

## [必须修复] LLM 网络异常穿透导致 REST 接口裸 500 ✅ 已修复

`app/tools/quiz.py` generate()：`llm.complete()` 在网络/限流层面抛出的异常（LLMClient 内部重试 2 次后仍失败）未被捕获，会直接穿透到 `main.py` 路由层。

原因：路由只捕获 `QuizError` 返回 422，其他异常变成裸 500，前端拿不到任何可读信息；对话场景虽有 dispatch 兜底，REST 场景（M19 练习页）会直接白屏。

修复：在 generate() 中把 LLM 调用包进 try/except，包装为 `QuizError("出题服务暂时不可用…")` 抛出；新增回归测试 `test_generate_wraps_llm_network_error`。验证：113/113 通过。

## [建议修改] topic 无长度限制，超长输入会原样注入 Prompt ✅ 已修复

`app/main.py` QuizRequest 与 `quiz.generate()` 均未限制 topic 长度。恶意或误操作传入几 KB 文本会拉高 token 消耗，也存在 Prompt 注入面。

修复：QuizRequest 加 `Field(min_length=1, max_length=50)`（超长直接 422），generate() 内部同步截断至 `MAX_TOPIC_LEN=50`。回归测试：`test_topic_truncated_to_50`、`test_api_topic_max_length_422`。

## [建议修改] 出题接口把 answer/explanation 一并返回给前端 ✅ 已修复

`POST /api/quiz/generate` 响应包含正确答案与解析。学生在练习页 F12 即可看到答案。

修复：QuizRequest 新增 `with_answer: bool = True`；传 `false` 时响应剥离 answer/explanation（答案留在服务端，M13 批改按 quiz_id 取用），默认行为不变、契约兼容。回归测试：`test_api_with_answer_false_strips_secret`。

## [问题] 单选题正确答案的位置分布是否会偏斜？ ✅ 已修复

修复：generate() 落库前对 options 随机洗牌并同步换算 answer 字母，保证 A-D 分布均匀；落库与返回均为洗牌后结果。回归测试：`test_shuffle_keeps_answer_correct`（固定逆序洗牌验证换算正确性）。

## [仅供参考]

1. `storage.save_quiz()` 9 个位置参数偏多，可改用 dataclass/dict；但与现有 `save_message` 风格一致，保持不动。
2. `_FORMAT_HINTS`/`_PROMPT_TEMPLATE` 模块级常量命名与结构清晰，符合中英混排规范（中文说明 + 英文术语加空格）。
3. FakeLLM 用 `pop(0)` 脚本耗尽会 IndexError——测试内可控，反而能暴露多余调用，保留。
4. Commit message 已符合中文约定式提交（`feat(M12): …`）。

---

## 验证记录

| 验证层 | 结果 |
|--------|------|
| 本地 pytest（真实 DeepSeek key，含 2 个真实出题集成测试） | 117/117 通过（整改后） |
| VM pytest（.env 真实 key） | 117/117 通过（整改后复验） |
| 真实链路（对话出题→作答→解析→拒绝课外出题→REST→落库） | 全部通过 |
| DeepSeek JSON 模式官方四项要求（response_format/含 json 提示词/防截断/空内容重试） | 全部落实 |
