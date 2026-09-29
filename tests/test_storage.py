from app import storage


def test_save_and_get_history(tmp_path):
    db = str(tmp_path / "t.db")
    storage.save_message(db, "s1", "user", "你好")
    storage.save_message(db, "s1", "assistant", "你好，我是助教")
    storage.save_message(db, "s2", "user", "别的会话")
    assert storage.get_history(db, "s1") == [
        {"role": "user", "content": "你好"},
        {"role": "assistant", "content": "你好，我是助教"},
    ]


def test_history_empty_for_new_session(tmp_path):
    db = str(tmp_path / "t.db")
    assert storage.get_history(db, "nobody") == []


def test_history_limit(tmp_path):
    db = str(tmp_path / "t.db")
    for i in range(30):
        storage.save_message(db, "s1", "user", f"m{i}")
    h = storage.get_history(db, "s1", limit=5)
    assert len(h) == 5
    assert h[-1]["content"] == "m29"
