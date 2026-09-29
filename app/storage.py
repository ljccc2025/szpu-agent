"""M03 SQLite 存储：唯一操作数据库的模块。"""
import sqlite3
from contextlib import closing
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
    # M12 出题落库（技术文档 quizzes 表 + qtype/options/source 三列，
    # 供 M13 按题型分支批改与出处溯源）
    conn.execute(
        "CREATE TABLE IF NOT EXISTS quizzes("
        "id INTEGER PRIMARY KEY AUTOINCREMENT,"
        "topic TEXT NOT NULL,"
        "difficulty TEXT NOT NULL,"
        "qtype TEXT NOT NULL,"
        "question TEXT NOT NULL,"
        "options TEXT NOT NULL,"          # JSON 数组文本；命令实操题为 []
        "answer TEXT NOT NULL,"
        "explanation TEXT NOT NULL,"
        "source TEXT NOT NULL,"           # 取材的课件文件名（防幻觉溯源）
        "created_at TEXT DEFAULT (datetime('now','localtime')))"
    )
    # M13 批改记录。单表设计：错题 = score < PASS_SCORE 的行，
    # 不另建 wrong_questions 表，避免同一数据两处存储需维护一致性。
    conn.execute(
        "CREATE TABLE IF NOT EXISTS attempts("
        "id INTEGER PRIMARY KEY AUTOINCREMENT,"
        "quiz_id INTEGER NOT NULL,"
        "topic TEXT NOT NULL,"
        "qtype TEXT NOT NULL,"
        "student_answer TEXT NOT NULL,"
        "score INTEGER NOT NULL,"
        "feedback TEXT NOT NULL,"
        "weak_points TEXT NOT NULL,"      # JSON 数组文本
        "created_at TEXT DEFAULT (datetime('now','localtime')),"
        "FOREIGN KEY(quiz_id) REFERENCES quizzes(id))"
    )
    return conn


def save_message(db_path, session_id, role, content):
    # closing() 负责关闭连接，内层 with 负责提交事务。
    # sqlite3 的上下文管理器只提交/回滚，不会关闭连接，单用会泄漏句柄。
    with closing(_conn(db_path)) as c, c:
        c.execute(
            "INSERT INTO messages(session_id, role, content) VALUES(?,?,?)",
            (session_id, role, content),
        )


def save_quiz(db_path, topic, difficulty, qtype,
              question, options_json, answer, explanation, source):
    """保存题目，返回自增 quiz_id。"""
    with closing(_conn(db_path)) as c, c:
        cur = c.execute(
            "INSERT INTO quizzes(topic, difficulty, qtype, question,"
            " options, answer, explanation, source) VALUES(?,?,?,?,?,?,?,?)",
            (topic, difficulty, qtype, question,
             options_json, answer, explanation, source),
        )
        return cur.lastrowid


_QUIZ_COLS = ("id", "topic", "difficulty", "qtype", "question",
              "options", "answer", "explanation", "source")


def get_quiz(db_path, quiz_id):
    """按 id 取题；不存在返回 None（M13 批改入口）。"""
    with closing(_conn(db_path)) as c:
        row = c.execute(
            f"SELECT {', '.join(_QUIZ_COLS)} FROM quizzes WHERE id=?",
            (quiz_id,),
        ).fetchone()
    return dict(zip(_QUIZ_COLS, row)) if row else None


def get_history(db_path, session_id, limit=20):
    with closing(_conn(db_path)) as c:
        rows = c.execute(
            "SELECT role, content FROM ("
            "SELECT * FROM messages WHERE session_id=? ORDER BY id DESC LIMIT ?"
            ") ORDER BY id",
            (session_id, limit),
        ).fetchall()
    return [{"role": r, "content": t} for r, t in rows]


def save_attempt(db_path, quiz_id, topic, qtype,
                 student_answer, score, feedback, weak_points_json):
    """保存一次作答记录（M13 批改），返回自增 attempt_id。"""
    with closing(_conn(db_path)) as c, c:
        cur = c.execute(
            "INSERT INTO attempts(quiz_id, topic, qtype, student_answer,"
            " score, feedback, weak_points) VALUES(?,?,?,?,?,?,?)",
            (quiz_id, topic, qtype, student_answer,
             score, feedback, weak_points_json),
        )
        return cur.lastrowid


_ATTEMPT_COLS = ("id", "quiz_id", "topic", "qtype", "student_answer",
                 "score", "feedback", "weak_points", "created_at")


def list_attempts(db_path, limit=50, max_score=None):
    """按时间倒序列出作答记录；max_score 非空时只返回低于该分数的（错题本）。"""
    sql = f"SELECT {', '.join(_ATTEMPT_COLS)} FROM attempts"
    params = []
    if max_score is not None:
        sql += " WHERE score < ?"
        params.append(max_score)
    sql += " ORDER BY id DESC LIMIT ?"
    params.append(limit)
    with closing(_conn(db_path)) as c:
        rows = c.execute(sql, params).fetchall()
    return [dict(zip(_ATTEMPT_COLS, r)) for r in rows]


def aggregate_weak_topics(db_path, max_score=60, limit=5):
    """按 topic 聚合错题，返回薄弱知识点排名（M14）。

    排序：错题数多的在前；错题数相同时平均分低的在前。
    只返回至少错过一次的知识点。
    """
    with closing(_conn(db_path)) as c:
        rows = c.execute(
            "SELECT topic,"
            " SUM(CASE WHEN score < ? THEN 1 ELSE 0 END) AS wrong,"
            " COUNT(*) AS total,"
            " AVG(score) AS avg_score"
            " FROM attempts GROUP BY topic"
            " HAVING wrong > 0"
            " ORDER BY wrong DESC, avg_score ASC, topic ASC"
            " LIMIT ?",
            (max_score, limit),
        ).fetchall()
    return [
        {"topic": t, "wrong_count": w, "total_count": n,
         "avg_score": round(a, 1)}
        for t, w, n, a in rows
    ]


def weak_point_rows(db_path, topic, max_score=60, limit=20):
    """取某知识点下错题的 weak_points 原始 JSON 文本（解析交给调用方）。"""
    with closing(_conn(db_path)) as c:
        rows = c.execute(
            "SELECT weak_points FROM attempts"
            " WHERE topic=? AND score < ? ORDER BY id DESC LIMIT ?",
            (topic, max_score, limit),
        ).fetchall()
    return [r[0] for r in rows]
