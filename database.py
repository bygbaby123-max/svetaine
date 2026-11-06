"""Duomenų bazė.

- Lokaliai (kai nėra DATABASE_URL)  -> SQLite failas data.db
- Serveryje Render (kai yra DATABASE_URL) -> PostgreSQL (Neon)
"""
import os
import sqlite3
from pathlib import Path

DB_PATH = Path(__file__).resolve().parent / "data.db"
DATABASE_URL = os.getenv("DATABASE_URL", "").strip()
if DATABASE_URL.startswith("postgres://"):
    DATABASE_URL = "postgresql://" + DATABASE_URL[len("postgres://"):] + (
        "" if "sslmode=" in DATABASE_URL else "?sslmode=require"
    )


def _use_pg():
    return bool(DATABASE_URL)


class _PgCursor:
    """Cursor po INSERT ... RETURNING id (pakeicia sqlite lastrowid)."""
    __slots__ = ("_rows", "lastrowid")

    def __init__(self, rows, lastrowid):
        self._rows = rows
        self.lastrowid = lastrowid

    def fetchone(self):
        return self._rows[0] if self._rows else None

    def fetchall(self):
        return list(self._rows)


class _Conn:
    """Vienodas wrapper'is virs sqlite3 ir psycopg (PostgreSQL)."""

    __slots__ = ("_raw", "_pg")

    def __init__(self, raw, pg):
        self._raw = raw
        self._pg = pg

    @property
    def pg(self):
        return self._pg

    def execute(self, sql, params=()):
        if not self._pg:
            if params:
                return self._raw.execute(sql, params)
            return self._raw.execute(sql)

        # PostgreSQL naudoja %s vietoje ? ir ILIKE vietoje LIKE
        query = sql.replace("?", "%s").replace(" LIKE ", " ILIKE ")
        if query.lstrip()[:6].upper() == "INSERT":
            query = query.rstrip() + " RETURNING id"
            if params:
                cur = self._raw.execute(query, params)
            else:
                cur = self._raw.execute(query)
            rows = cur.fetchall()
            last = None
            if rows:
                first = rows[0]
                last = first["id"] if isinstance(first, dict) else first[0]
            return _PgCursor(rows, last)
        if params:
            return self._raw.execute(query, params)
        return self._raw.execute(query)

    def executescript(self, script):
        for stmt in (s.strip() for s in script.split(";")):
            if stmt:
                self._raw.execute(stmt)

    def commit(self):
        self._raw.commit()

    def close(self):
        self._raw.close()


def get_db():
    if _use_pg():
        import psycopg
        from psycopg.rows import dict_row

        raw = psycopg.connect(DATABASE_URL, row_factory=dict_row)
        return _Conn(raw, True)

    raw = sqlite3.connect(DB_PATH)
    raw.row_factory = sqlite3.Row
    raw.execute("PRAGMA foreign_keys = ON")
    return _Conn(raw, False)


SQLITE_SCHEMA = """
CREATE TABLE IF NOT EXISTS users (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    username TEXT UNIQUE NOT NULL,
    email TEXT UNIQUE NOT NULL,
    password_hash TEXT,
    birth_year INTEGER,
    is_admin INTEGER NOT NULL DEFAULT 0,
    is_coowner INTEGER NOT NULL DEFAULT 0,
    panel_token TEXT UNIQUE,
    created_at TEXT NOT NULL,
    last_login_at TEXT,
    last_login_ip TEXT,
    login_count INTEGER NOT NULL DEFAULT 0,
    coins INTEGER NOT NULL DEFAULT 0,
    last_bonus_date TEXT
);

CREATE TABLE IF NOT EXISTS logins (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL,
    ip TEXT,
    user_agent TEXT,
    created_at TEXT NOT NULL,
    FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS memes (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL,
    title TEXT NOT NULL,
    image TEXT NOT NULL,
    created_at TEXT NOT NULL,
    FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS meme_votes (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    meme_id INTEGER NOT NULL,
    user_id INTEGER NOT NULL,
    vote INTEGER NOT NULL,
    UNIQUE (meme_id, user_id),
    FOREIGN KEY (meme_id) REFERENCES memes(id) ON DELETE CASCADE,
    FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS meme_comments (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    meme_id INTEGER NOT NULL,
    user_id INTEGER NOT NULL,
    body TEXT NOT NULL,
    created_at TEXT NOT NULL,
    FOREIGN KEY (meme_id) REFERENCES memes(id) ON DELETE CASCADE,
    FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS chat_messages (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL,
    body TEXT NOT NULL,
    created_at TEXT NOT NULL,
    FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS direct_messages (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    from_id INTEGER NOT NULL,
    to_id INTEGER NOT NULL,
    body TEXT NOT NULL,
    created_at TEXT NOT NULL,
    read_at TEXT,
    FOREIGN KEY (from_id) REFERENCES users(id) ON DELETE CASCADE,
    FOREIGN KEY (to_id) REFERENCES users(id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS game_scores (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL,
    game TEXT NOT NULL,
    score INTEGER NOT NULL,
    created_at TEXT NOT NULL,
    FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS accessories (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    key TEXT UNIQUE NOT NULL,
    name TEXT NOT NULL,
    description TEXT NOT NULL,
    price INTEGER NOT NULL,
    emoji TEXT,
    image TEXT,
    css TEXT,
    slot TEXT NOT NULL DEFAULT 'name',
    active INTEGER NOT NULL DEFAULT 1,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS user_accessories (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL,
    accessory_id INTEGER NOT NULL,
    equipped INTEGER NOT NULL DEFAULT 0,
    bought_at TEXT NOT NULL,
    UNIQUE (user_id, accessory_id),
    FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE,
    FOREIGN KEY (accessory_id) REFERENCES accessories(id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS coin_log (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL,
    amount INTEGER NOT NULL,
    reason TEXT NOT NULL,
    created_at TEXT NOT NULL,
    FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS meta (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    key TEXT UNIQUE NOT NULL,
    value TEXT NOT NULL
);
"""

PG_USERS_DDL = """
CREATE TABLE IF NOT EXISTS users (
    id SERIAL PRIMARY KEY,
    username TEXT UNIQUE NOT NULL,
    email TEXT UNIQUE NOT NULL,
    password_hash TEXT,
    birth_year INTEGER,
    is_admin INTEGER NOT NULL DEFAULT 0,
    is_coowner INTEGER NOT NULL DEFAULT 0,
    panel_token TEXT UNIQUE,
    created_at TEXT NOT NULL,
    last_login_at TEXT,
    last_login_ip TEXT,
    login_count INTEGER NOT NULL DEFAULT 0
)
"""

PG_LOGINS_DDL = """
CREATE TABLE IF NOT EXISTS logins (
    id SERIAL PRIMARY KEY,
    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    ip TEXT,
    user_agent TEXT,
    created_at TEXT NOT NULL
)
"""

PG_MEMES_DDL = """
CREATE TABLE IF NOT EXISTS memes (
    id SERIAL PRIMARY KEY,
    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    title TEXT NOT NULL,
    image TEXT NOT NULL,
    created_at TEXT NOT NULL
)
"""

PG_MEME_VOTES_DDL = """
CREATE TABLE IF NOT EXISTS meme_votes (
    id SERIAL PRIMARY KEY,
    meme_id INTEGER NOT NULL REFERENCES memes(id) ON DELETE CASCADE,
    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    vote INTEGER NOT NULL,
    UNIQUE (meme_id, user_id)
)
"""

PG_MEME_COMMENTS_DDL = """
CREATE TABLE IF NOT EXISTS meme_comments (
    id SERIAL PRIMARY KEY,
    meme_id INTEGER NOT NULL REFERENCES memes(id) ON DELETE CASCADE,
    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    body TEXT NOT NULL,
    created_at TEXT NOT NULL
)
"""

PG_CHAT_DDL = """
CREATE TABLE IF NOT EXISTS chat_messages (
    id SERIAL PRIMARY KEY,
    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    body TEXT NOT NULL,
    created_at TEXT NOT NULL
)
"""

PG_DIRECT_DDL = """
CREATE TABLE IF NOT EXISTS direct_messages (
    id SERIAL PRIMARY KEY,
    from_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    to_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    body TEXT NOT NULL,
    created_at TEXT NOT NULL,
    read_at TEXT
)
"""

PG_GAME_SCORES_DDL = """
CREATE TABLE IF NOT EXISTS game_scores (
    id SERIAL PRIMARY KEY,
    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    game TEXT NOT NULL,
    score INTEGER NOT NULL,
    created_at TEXT NOT NULL
)
"""

PG_ACCESSORIES_DDL = """
CREATE TABLE IF NOT EXISTS accessories (
    id SERIAL PRIMARY KEY,
    key TEXT UNIQUE NOT NULL,
    name TEXT NOT NULL,
    description TEXT NOT NULL,
    price INTEGER NOT NULL,
    emoji TEXT,
    image TEXT,
    css TEXT,
    slot TEXT NOT NULL DEFAULT 'name',
    active INTEGER NOT NULL DEFAULT 1,
    created_at TEXT NOT NULL
)
"""

PG_USER_ACCESSORIES_DDL = """
CREATE TABLE IF NOT EXISTS user_accessories (
    id SERIAL PRIMARY KEY,
    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    accessory_id INTEGER NOT NULL REFERENCES accessories(id) ON DELETE CASCADE,
    equipped INTEGER NOT NULL DEFAULT 0,
    bought_at TEXT NOT NULL,
    UNIQUE (user_id, accessory_id)
)
"""

PG_COIN_LOG_DDL = """
CREATE TABLE IF NOT EXISTS coin_log (
    id SERIAL PRIMARY KEY,
    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    amount INTEGER NOT NULL,
    reason TEXT NOT NULL,
    created_at TEXT NOT NULL
)
"""

PG_META_DDL = """
CREATE TABLE IF NOT EXISTS meta (
    id SERIAL PRIMARY KEY,
    key TEXT UNIQUE NOT NULL,
    value TEXT NOT NULL
)
"""


def _add_missing_columns(conn):
    """Prideda naujus stulpelius į jau esančias lenteles (SQLite ir PostgreSQL)."""
    def have_columns(table):
        have = set()
        if conn.pg:
            rows = conn.execute(
                "SELECT column_name FROM information_schema.columns WHERE table_name = ?",
                (table,),
            ).fetchall()
            for r in rows:
                have.add(r["column_name"])
        else:
            for r in conn.execute(f"PRAGMA table_info({table})").fetchall():
                have.add(r["name"])
        return have

    for column, ddl in (
        ("is_coowner", "is_coowner INTEGER NOT NULL DEFAULT 0"),
        ("coins", "coins INTEGER NOT NULL DEFAULT 0"),
        ("last_bonus_date", "last_bonus_date TEXT"),
    ):
        if column not in have_columns("users"):
            conn.execute(f"ALTER TABLE users ADD COLUMN {ddl}")

    if "accessories" in _tables(conn):
        for column, ddl in (
            ("slot", "slot TEXT NOT NULL DEFAULT 'name'"),
        ):
            if column not in have_columns("accessories"):
                conn.execute(f"ALTER TABLE accessories ADD COLUMN {ddl}")
    conn.commit()


def _tables(conn):
    """Egzistuojančių lentelių vardai (SQLite ir PostgreSQL)."""
    if conn.pg:
        rows = conn.execute(
            "SELECT table_name FROM information_schema.tables WHERE table_schema = 'public'"
        ).fetchall()
        return {r["table_name"] for r in rows}
    rows = conn.execute(
        "SELECT name FROM sqlite_master WHERE type = 'table'"
    ).fetchall()
    return {r["name"] for r in rows}


def init_db():
    conn = get_db()
    try:
        if conn.pg:
            conn.execute(PG_USERS_DDL)
            conn.execute(PG_LOGINS_DDL)
            conn.execute(PG_MEMES_DDL)
            conn.execute(PG_MEME_VOTES_DDL)
            conn.execute(PG_MEME_COMMENTS_DDL)
            conn.execute(PG_CHAT_DDL)
            conn.execute(PG_DIRECT_DDL)
            conn.execute(PG_GAME_SCORES_DDL)
            conn.execute(PG_ACCESSORIES_DDL)
            conn.execute(PG_USER_ACCESSORIES_DDL)
            conn.execute(PG_COIN_LOG_DDL)
            conn.execute(PG_META_DDL)
        else:
            conn.executescript(SQLITE_SCHEMA)
        _add_missing_columns(conn)
        conn.commit()
    finally:
        conn.close()


def fetch_user(user_id):
    db = get_db()
    try:
        return db.execute("SELECT * FROM users WHERE id = ?", (user_id,)).fetchone()
    finally:
        db.close()
