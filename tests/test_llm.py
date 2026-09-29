from app.llm import build_messages


def test_build_messages_order():
    history = [
        {"role": "user", "content": "a"},
        {"role": "assistant", "content": "b"},
    ]
    msgs = build_messages("系统提示", history, "新问题")
    assert msgs[0] == {"role": "system", "content": "系统提示"}
    assert msgs[1:3] == history
    assert msgs[-1] == {"role": "user", "content": "新问题"}
    assert len(msgs) == 4
