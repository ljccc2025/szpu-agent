import json

from app.tools import registry


def test_calculator():
    assert registry.calculator("(2+3)*4") == "20"


def test_calculator_rejects_injection():
    result = registry.dispatch("calculator", json.dumps({"expression": "__import__('os')"}))
    text, extra = result
    assert "出错" in text and extra is None


def test_dispatch_unknown_tool():
    text, extra = registry.dispatch("nope", "{}")
    assert "未知工具" in text and extra is None


def test_dispatch_bad_json():
    text, extra = registry.dispatch("calculator", "{broken")
    assert "JSON" in text and extra is None


def test_tools_schema_shape():
    for t in registry.TOOLS:
        assert t["type"] == "function"
        assert "name" in t["function"]
        assert t["function"]["name"] in registry.HANDLERS


def test_calculator_rejects_large_exponent():
    """回归：幂运算无上限时 9**9**8 会占死工作线程，指数超限必须在计算前拒绝。"""
    text, extra = registry.dispatch("calculator", json.dumps({"expression": "2**1000"}))
    assert "过大" in text
    assert extra is None


def test_calculator_rejects_large_base():
    text, _ = registry.dispatch("calculator", json.dumps({"expression": "99999999**3"}))
    assert "过大" in text


def test_calculator_still_supports_small_power():
    assert registry.calculator("2**10") == "1024"


def test_dispatch_passes_through_extra_payload(monkeypatch):
    """工具可返回 (文本, 附带数据)，dispatch 需原样透传附带数据。"""
    monkeypatch.setitem(
        registry.HANDLERS, "fake_tool", lambda: ("文本", [{"source": "a.pdf"}])
    )
    text, extra = registry.dispatch("fake_tool", "{}")
    assert text == "文本"
    assert extra == [{"source": "a.pdf"}]
