"""SQLite/PostgreSQL connection compatibility shim.

Local dev and the whole test suite run on SQLite (fast, zero setup, and the
only backend this code is actually exercised against in CI). Setting
DATABASE_URL to a postgres:// / postgresql:// URL switches connect() to
Postgres via psycopg instead, by rewriting each call site's SQLite-only SQL
at execution time so callers never have to branch on backend themselves.

IMPORTANT: the Postgres path has not been run against a live Postgres
instance in this environment (no local Postgres/Docker available). It is a
best-effort translation, not a verified migration -- see
docs/postgres-migration.md before pointing it at a real database.
"""

import os
import re
import sqlite3
from typing import Any

_NAMED_PARAM = re.compile(r":([a-zA-Z_][a-zA-Z0-9_]*)")
_OR_IGNORE = re.compile(r"(?i)\bINSERT\s+OR\s+IGNORE\s+INTO\b")
_LIKE = re.compile(r"(?i)\bLIKE\b")


def database_url() -> str | None:
    return os.getenv("DATABASE_URL")


def is_postgres() -> bool:
    url = database_url()
    return url is not None and url.startswith(("postgres://", "postgresql://"))


def _split_statements(script: str) -> list[str]:
    return [statement.strip() for statement in script.split(";") if statement.strip()]


def _rewrite_sql(sql: str) -> str:
    """Translate SQLite-flavoured SQL to Postgres-flavoured SQL.

    Only handles the specific patterns this codebase actually uses:
    INSERT OR IGNORE (-> INSERT ... ON CONFLICT DO NOTHING, which needs no
    explicit conflict target for either engine), LIKE (-> ILIKE, to keep
    SQLite's default case-insensitive match behavior), named ``:param``
    placeholders (-> ``%(param)s``), and positional ``?`` placeholders
    (-> ``%s``). None of this codebase's SQL text contains a literal ``?``
    or ``:`` outside of placeholders, so the substitutions are safe as
    plain string/regex rewrites.
    """
    if _OR_IGNORE.search(sql):
        sql = _OR_IGNORE.sub("INSERT INTO", sql, count=1)
        sql = sql.rstrip().rstrip(";") + " ON CONFLICT DO NOTHING"
    sql = _LIKE.sub("ILIKE", sql)
    sql = _NAMED_PARAM.sub(r"%(\1)s", sql)
    sql = sql.replace("?", "%s")
    return sql


class PostgresConnection:
    """Wraps a psycopg connection to match the sqlite3.Connection surface
    this codebase relies on: execute/executemany/executescript returning a
    cursor with fetchone/fetchall/rowcount, dict-like rows, and
    commit/rollback/close.
    """

    def __init__(self, dsn: str) -> None:
        import psycopg
        from psycopg.rows import dict_row

        self._conn = psycopg.connect(dsn, row_factory=dict_row)

    def execute(self, sql: str, params: Any = None) -> Any:
        cursor = self._conn.cursor()
        cursor.execute(_rewrite_sql(sql), params if params else None)
        return cursor

    def executemany(self, sql: str, seq_of_params: Any) -> Any:
        cursor = self._conn.cursor()
        cursor.executemany(_rewrite_sql(sql), list(seq_of_params))
        return cursor

    def executescript(self, script: str) -> None:
        # sqlite3.Connection.executescript() implicitly commits (its own
        # documented behavior, independent of the connection's normal
        # transaction control) -- match that here, or DDL run through this
        # method stays in an uncommitted transaction and vanishes the
        # moment the connection is closed.
        cursor = self._conn.cursor()
        for statement in _split_statements(script):
            cursor.execute(_rewrite_sql(statement))
        self._conn.commit()

    def commit(self) -> None:
        self._conn.commit()

    def rollback(self) -> None:
        self._conn.rollback()

    def close(self) -> None:
        self._conn.close()


# Return type shared by connect()/transaction(): both backends expose the
# same execute/executemany/executescript/commit/rollback/close surface, so
# call sites written against sqlite3.Connection work unmodified against
# either. Deeper function signatures across this codebase still say
# `sqlite3.Connection` for brevity; treat that as documentation of the
# SQLite-shaped API surface being used, not a runtime constraint.
Connection = sqlite3.Connection | PostgresConnection
