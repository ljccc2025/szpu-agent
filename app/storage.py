"""M03 SQLite 存储：唯一操作数据库的模块。"""
import sqlite3
from pathlib import Path


def _conn(db_path):
    Path(db_path).parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(db_path)
    conn.execute(
        "CREATE TABLE IF NOT EXISTS messages("
        "id INTEGER PRIMARY KEY AUTOINCREMENT,"
        "session_id TEXT NOT NULL,"
        "role TEXT NOT NULL,"
        "content TEXT NOT NULL,"
        "created_at TEXT DEFAULT (datetime('now','localtime')))"
    )
    return conn


def save_message(db_path, session_id, role, content):
    with _conn(db_path) as c:
        c.execute(
            "INSERT INTO messages(session_id, role, content) VALUES(?,?,?)",
            (session_id, role, content),
        )


def get_history(db_path, session_id, limit=20):
    with _conn(db_path) as c:
        rows = c.execute(
            "SELECT role, content FROM ("
            "SELECT * FROM messages WHERE session_id=? ORDER BY id DESC LIMIT ?"
            ") ORDER BY id",
            (session_id, limit),
        ).fetchall()
    return [{"role": r, "content": t} for r, t in rows]
