import json

from app.tools import registry


def test_calculator():
    assert registry.calculator("(2+3)*4") == "20"


def test_calculator_rejects_injection():
    result = registry.dispatch("calculator", json.dumps({"expression": "__import__('os')"}))
    assert "出错" in result


def test_dispatch_unknown_tool():
    assert "未知工具" in registry.dispatch("nope", "{}")


def test_dispatch_bad_json():
    assert "JSON" in registry.dispatch("calculator", "{broken")


def test_tools_schema_shape():
    for t in registry.TOOLS:
        assert t["type"] == "function"
        assert "name" in t["function"]
        assert t["function"]["name"] in registry.HANDLERS
