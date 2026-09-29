"""M06 工具注册与调度：OpenAI tools 协议格式（DeepSeek 官方 Tool Calls 指南同款）。

后续 M07(RAG)/M11(沙箱)/M12(出题)/M13(批改) 在此追加注册。
当前内置两个演示工具用于验证 Function Calling 全链路。
"""
import ast
import datetime
import json
import operator

from app.tools import grader, planner, quiz, rag_search, sandbox

_OPS = {
    ast.Add: operator.add,
    ast.Sub: operator.sub,
    ast.Mult: operator.mul,
    ast.Div: operator.truediv,
    ast.Mod: operator.mod,
    ast.Pow: operator.pow,
    ast.USub: operator.neg,
}

# 幂运算限幅：9**9**8 这类表达式会算到天荒地老并吃光内存，
# 而 dispatch 的 try/except 只兜得住异常、兜不住"算得慢"。
MAX_POW_EXPONENT = 64
MAX_POW_BASE = 10 ** 6


def _safe_eval(node):
    if isinstance(node, ast.Constant) and isinstance(node.value, (int, float)):
        return node.value
    if isinstance(node, ast.BinOp) and type(node.op) in _OPS:
        left, right = _safe_eval(node.left), _safe_eval(node.right)
        if isinstance(node.op, ast.Pow) and (
            abs(right) > MAX_POW_EXPONENT or abs(left) > MAX_POW_BASE
        ):
            raise ValueError("指数或底数过大，已拒绝计算（防止占满服务线程）")
        return _OPS[type(node.op)](left, right)
    if isinstance(node, ast.UnaryOp) and type(node.op) in _OPS:
        return _OPS[type(node.op)](_safe_eval(node.operand))
    raise ValueError("表达式含不支持的语法")


def calculator(expression: str) -> str:
    """安全计算四则运算表达式（AST 白名单，无 eval 注入风险）。"""
    tree = ast.parse(expression, mode="eval")
    return str(_safe_eval(tree.body))


def get_current_time() -> str:
    return datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")


TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "calculator",
            "description": "计算数学表达式，支持加减乘除、取余、幂运算，例如 (2+3)*4",
            "parameters": {
                "type": "object",
                "properties": {
                    "expression": {"type": "string", "description": "数学表达式"}
                },
                "required": ["expression"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_current_time",
            "description": "获取服务器当前日期和时间",
            "parameters": {"type": "object", "properties": {}},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "rag_search",
            "description": (
                "检索云计算运维课程知识库（课件/讲义/实验手册），"
                "返回带出处的课程原文。学生询问课程知识点、概念、"
                "命令用法、配置方法时应优先调用本工具"
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": "检索关键词或问题，用简洁中文描述",
                    }
                },
                "required": ["query"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "run_command",
            "description": (
                "在安全沙箱（一次性 Docker 容器，无网络、限资源、10秒超时）中"
                "真实执行 Linux 命令并返回输出。学生要求执行、演示、验证命令"
                "效果时调用本工具；常见危险命令会被黑名单拦下并给出讲解，"
                "但真正的隔离来自一次性容器本身，黑名单不保证覆盖所有写法"
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "command": {
                        "type": "string",
                        "description": "要执行的 shell 命令，如 ls -la /etc",
                    }
                },
                "required": ["command"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "generate_quiz",
            "description": (
                "根据课程知识库出一道练习题（先检索课程资料取材，"
                "题目必有讲义依据；知识库没有该知识点资料时会拒绝出题）。"
                "学生要求出题、练习、测验、考察某知识点时调用"
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "topic": {
                        "type": "string",
                        "description": "要考察的知识点，如：Nginx 反向代理",
                    },
                    "difficulty": {
                        "type": "string",
                        "enum": ["基础", "中等", "困难"],
                        "description": "难度，默认中等",
                    },
                    "qtype": {
                        "type": "string",
                        "enum": ["单选题", "命令实操题"],
                        "description": "题型，默认单选题",
                    },
                },
                "required": ["topic"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "grade_answer",
            "description": (
                "批改学生对某道练习题的作答，给出分数、点评与薄弱知识点。"
                "单选题直接比对答案；命令实操题会把学生命令与参考命令"
                "都放进沙箱真实执行后再判定效果是否等价。"
                "学生提交答案、要求批改/判分/对答案时调用本工具"
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "quiz_id": {
                        "type": "integer",
                        "description": "要批改的题号，来自 generate_quiz 返回的题号",
                    },
                    "student_answer": {
                        "type": "string",
                        "description": (
                            "学生的作答内容；单选题填 A/B/C/D，"
                            "命令实操题填完整的 shell 命令"
                        ),
                    },
                },
                "required": ["quiz_id", "student_answer"],
            },
        },
    },
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
]

HANDLERS = {
    "calculator": calculator,
    "get_current_time": get_current_time,
    "rag_search": rag_search.search,
    "run_command": sandbox.run_command,
    "generate_quiz": quiz.generate_quiz,
    "grade_answer": grader.grade_answer,
    "make_study_plan": planner.make_study_plan,
}


def dispatch(name, arguments_json):
    """按名称分发执行工具，返回 (文本结果, 附带数据)。

    附带数据用于把结构化信息（如 RAG 出处）随本次调用交还调用方，
    取代原先的模块级全局缓存——全局缓存在并发请求下会串号。
    任何异常都兜底为文本，不炸整轮对话。
    """
    handler = HANDLERS.get(name)
    if handler is None:
        return f"未知工具: {name}", None
    try:
        args = json.loads(arguments_json) if arguments_json else {}
    except json.JSONDecodeError:
        return "工具参数不是合法 JSON", None
    try:
        result = handler(**args)
    except Exception as err:
        return f"工具执行出错: {err}", None
    if isinstance(result, tuple):
        text, extra = result
        return str(text), extra
    return str(result), None


# dispatch 把失败也写成文本返回（不抛异常），这些前缀就是失败的全部形态。
# 与下方 is_failure 放在一起维护，避免上层去硬编码字符串匹配。
FAILURE_PREFIXES = ("未知工具:", "工具参数不是合法 JSON", "工具执行出错:")


def is_failure(result_text):
    """判断 dispatch 返回的文本是否代表调度层失败（M15 tool_end 如实上报）。"""
    return str(result_text).startswith(FAILURE_PREFIXES)
