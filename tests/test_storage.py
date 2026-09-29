import sqlite3

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


def _spy_connections(monkeypatch):
    """记录本模块打开的每一个 sqlite 连接。"""
    opened = []
    real_connect = sqlite3.connect

    def fake_connect(*args, **kwargs):
        conn = real_connect(*args, **kwargs)
        opened.append(conn)
        return conn

    monkeypatch.setattr(sqlite3, "connect", fake_connect)
    return opened


def _is_closed(conn):
    try:
        conn.execute("SELECT 1")
        return False
    except sqlite3.ProgrammingError:
        return True


def test_save_message_closes_connection(tmp_path, monkeypatch):
    """回归：sqlite3 的上下文管理器只提交事务，不关闭连接，会泄漏句柄。"""
    db = str(tmp_path / "t.db")
    opened = _spy_connections(monkeypatch)
    storage.save_message(db, "s1", "user", "你好")
    assert opened, "未观察到任何连接"
    assert all(_is_closed(c) for c in opened)


def test_get_history_closes_connection(tmp_path, monkeypatch):
    db = str(tmp_path / "t.db")
    storage.save_message(db, "s1", "user", "你好")
    opened = _spy_connections(monkeypatch)
    storage.get_history(db, "s1")
    assert opened, "未观察到任何连接"
    assert all(_is_closed(c) for c in opened)
