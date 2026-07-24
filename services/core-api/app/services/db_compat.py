"""SQLite/PostgreSQL connection compatibility shim.

See services/mock-commerce-api/app/db_compat.py for the full rationale --
this is the same shim duplicated for core-api's two sqlite3-backed stores
(InquiryStore, OpsStore), consistent with how utc_now() etc. are already
duplicated between the two services rather than shared through a package.

IMPORTANT: the Postgres path has not been run against a live Postgres
instance in this environment. Best-effort translation, not a verified
migration -- see docs/postgres-migration.md before pointing it at a real
database.
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
    if _OR_IGNORE.search(sql):
        sql = _OR_IGNORE.sub("INSERT INTO", sql, count=1)
        sql = sql.rstrip().rstrip(";") + " ON CONFLICT DO NOTHING"
    sql = _LIKE.sub("ILIKE", sql)
    sql = _NAMED_PARAM.sub(r"%(\1)s", sql)
    sql = sql.replace("?", "%s")
    return sql


class PostgresConnection:
    """Wraps a psycopg connection to match the sqlite3.Connection surface
    InquiryStore/OpsStore rely on: execute/executemany/executescript
    returning a cursor with fetchone/fetchall, dict-like rows, and
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
        cursor = self._conn.cursor()
        for statement in _split_statements(script):
            cursor.execute(_rewrite_sql(statement))

    def commit(self) -> None:
        self._conn.commit()

    def rollback(self) -> None:
        self._conn.rollback()

    def close(self) -> None:
        self._conn.close()


Connection = sqlite3.Connection | PostgresConnection
