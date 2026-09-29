"""M06 工具注册与调度：OpenAI tools 协议格式（DeepSeek 官方 Tool Calls 指南同款）。

后续 M07(RAG)/M11(沙箱)/M12(出题)/M13(批改) 在此追加注册。
当前内置两个演示工具用于验证 Function Calling 全链路。
"""
import ast
import datetime
import json
import operator

_OPS = {
    ast.Add: operator.add,
    ast.Sub: operator.sub,
    ast.Mult: operator.mul,
    ast.Div: operator.truediv,
    ast.Mod: operator.mod,
    ast.Pow: operator.pow,
    ast.USub: operator.neg,
}


def _safe_eval(node):
    if isinstance(node, ast.Constant) and isinstance(node.value, (int, float)):
        return node.value
    if isinstance(node, ast.BinOp) and type(node.op) in _OPS:
        return _OPS[type(node.op)](_safe_eval(node.left), _safe_eval(node.right))
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
]

HANDLERS = {
    "calculator": calculator,
    "get_current_time": get_current_time,
}


def dispatch(name, arguments_json):
    """按名称分发执行工具；任何异常都兜底为文本，不炸整轮对话。"""
    handler = HANDLERS.get(name)
    if handler is None:
        return f"未知工具: {name}"
    try:
        args = json.loads(arguments_json) if arguments_json else {}
    except json.JSONDecodeError:
        return "工具参数不是合法 JSON"
    try:
        return str(handler(**args))
    except Exception as err:
        return f"工具执行出错: {err}"
