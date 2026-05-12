#!/usr/bin/env python3
"""MCP server: generic SQL access (Postgres / SQLite / MySQL).

Read-only by default — all `query` calls refuse INSERT/UPDATE/DELETE/DROP/etc.
Pass unsafe=True to allow mutations (still refuses DROP DATABASE/TABLE).

DSN forms:
  - postgres://user:pass@host:port/db
  - sqlite:///path/to/file.db
  - mysql://user:pass@host:port/db
"""
from __future__ import annotations

import json
import re
import sqlite3
from contextlib import contextmanager
from typing import Any
from urllib.parse import urlparse

from mcp.server.fastmcp import FastMCP

mcp = FastMCP("sql")


def _scheme(dsn: str) -> str:
    p = urlparse(dsn)
    s = p.scheme.lower()
    if s in ("postgres", "postgresql", "pg"):
        return "postgres"
    if s == "sqlite":
        return "sqlite"
    if s in ("mysql", "mariadb"):
        return "mysql"
    raise ValueError(f"unsupported DSN scheme: {s}")


@contextmanager
def _connect(dsn: str):
    s = _scheme(dsn)
    if s == "sqlite":
        path = urlparse(dsn).path
        if path.startswith("/"):
            path = path[1:] if path.startswith("//") else path
        conn = sqlite3.connect(path)
        conn.row_factory = sqlite3.Row
        try:
            yield ("sqlite", conn)
        finally:
            conn.close()
    elif s == "postgres":
        import psycopg
        # psycopg accepts the full DSN
        conn = psycopg.connect(dsn, autocommit=True)
        try:
            yield ("postgres", conn)
        finally:
            conn.close()
    elif s == "mysql":
        import pymysql
        u = urlparse(dsn)
        conn = pymysql.connect(
            host=u.hostname, port=u.port or 3306,
            user=u.username, password=u.password,
            database=(u.path or "/").lstrip("/"),
            cursorclass=pymysql.cursors.DictCursor,
            autocommit=True,
        )
        try:
            yield ("mysql", conn)
        finally:
            conn.close()


# Forbidden keywords for read-only mode (case-insensitive, word-boundary)
WRITE_KW = re.compile(
    r"\b(insert|update|delete|drop|truncate|alter|create|grant|revoke|copy|merge|replace|rename|attach|detach|vacuum|reindex)\b",
    re.IGNORECASE,
)
NUKE_KW = re.compile(
    r"\b(drop\s+(database|schema|table)|truncate\s+(database|table)|delete\s+from\s+\w+\s*;?\s*$)\b",
    re.IGNORECASE,
)


def _is_safe(sql: str, unsafe: bool) -> str | None:
    sql_clean = re.sub(r"--[^\n]*", "", sql)  # strip line comments
    sql_clean = re.sub(r"/\*.*?\*/", "", sql_clean, flags=re.S)  # strip block comments
    if not unsafe and WRITE_KW.search(sql_clean):
        return "read-only mode: write keywords detected. Pass unsafe=True if you really mean it."
    if NUKE_KW.search(sql_clean):
        return "refused: destructive operation (DROP/TRUNCATE on DATABASE/SCHEMA/TABLE)"
    return None


def _rows_to_json(cursor, kind: str) -> list[dict[str, Any]]:
    if kind == "sqlite":
        return [dict(r) for r in cursor.fetchall()]
    if kind == "postgres":
        cols = [d.name for d in cursor.description] if cursor.description else []
        return [dict(zip(cols, r)) for r in cursor.fetchall()]
    if kind == "mysql":
        return [dict(r) for r in cursor.fetchall()]
    return []


@mcp.tool()
def query(dsn: str, sql: str, params: list[Any] | None = None, limit: int = 100, unsafe: bool = False) -> str:
    """Execute a SQL query against a database.

    Read-only by default — refuses INSERT/UPDATE/DELETE/DROP/etc.
    Pass unsafe=True to allow mutations (still refuses DROP DATABASE/SCHEMA/TABLE).

    Args:
        dsn: Connection string (postgres://, sqlite:///, mysql://).
        sql: SQL query.
        params: Optional positional parameters (use %s for postgres/mysql, ? for sqlite).
        limit: Cap rows returned. Default 100.
        unsafe: Allow non-SELECT operations.

    Returns:
        JSON: {row_count, rows: [...], truncated, columns: [...]}
    """
    err = _is_safe(sql, unsafe)
    if err:
        return json.dumps({"error": err})
    try:
        with _connect(dsn) as (kind, conn):
            cur = conn.cursor()
            cur.execute(sql, params or [])
            if cur.description is None:
                # mutation
                affected = cur.rowcount if kind != "sqlite" else cur.rowcount
                return json.dumps({"affected_rows": affected, "rows": []})
            rows = _rows_to_json(cur, kind)
            truncated = len(rows) > limit
            rows = rows[:limit]
            cols = []
            if kind == "sqlite":
                cols = [d[0] for d in cur.description]
            elif kind == "postgres":
                cols = [d.name for d in cur.description]
            elif kind == "mysql":
                cols = [d[0] for d in cur.description]
            # JSON-safe coercion
            def _coerce(v):
                if isinstance(v, (bytes, bytearray)):
                    try: return v.decode("utf-8")
                    except UnicodeDecodeError: return repr(v)[:200]
                if hasattr(v, "isoformat"):
                    return v.isoformat()
                return v
            rows = [{k: _coerce(v) for k, v in r.items()} for r in rows]
            return json.dumps({
                "columns": cols,
                "row_count": len(rows),
                "rows": rows,
                "truncated": truncated,
            }, ensure_ascii=False, indent=2)
    except Exception as e:
        return json.dumps({"error": f"{type(e).__name__}: {e}"})


@mcp.tool()
def tables(dsn: str) -> str:
    """List tables (and views) in the database.

    Args:
        dsn: Connection string.

    Returns:
        JSON: [{name, schema?, type}]
    """
    try:
        with _connect(dsn) as (kind, conn):
            cur = conn.cursor()
            if kind == "sqlite":
                cur.execute("SELECT name, type FROM sqlite_master WHERE type IN ('table','view') ORDER BY name")
                return json.dumps([{"name": r[0], "type": r[1]} for r in cur.fetchall()], indent=2)
            if kind == "postgres":
                cur.execute("""
                    SELECT table_schema, table_name, table_type
                    FROM information_schema.tables
                    WHERE table_schema NOT IN ('pg_catalog','information_schema')
                    ORDER BY table_schema, table_name
                """)
                return json.dumps([{"schema": r[0], "name": r[1], "type": r[2]} for r in cur.fetchall()], indent=2)
            if kind == "mysql":
                cur.execute("""
                    SELECT table_schema, table_name, table_type
                    FROM information_schema.tables
                    WHERE table_schema = DATABASE()
                    ORDER BY table_name
                """)
                return json.dumps([{"schema": r["table_schema"], "name": r["table_name"], "type": r["table_type"]}
                                   for r in cur.fetchall()], indent=2)
        return json.dumps({"error": "unknown kind"})
    except Exception as e:
        return json.dumps({"error": f"{type(e).__name__}: {e}"})


@mcp.tool()
def describe(dsn: str, table: str, schema: str | None = None) -> str:
    """Describe columns + indexes of a table.

    Args:
        dsn: Connection string.
        table: Table name.
        schema: Optional schema (postgres/mysql).

    Returns:
        JSON: {columns: [...], indexes: [...]}
    """
    try:
        with _connect(dsn) as (kind, conn):
            cur = conn.cursor()
            cols = []
            idx = []
            if kind == "sqlite":
                cur.execute(f"PRAGMA table_info({table})")
                cols = [{"name": r[1], "type": r[2], "notnull": bool(r[3]), "default": r[4], "pk": bool(r[5])}
                        for r in cur.fetchall()]
                cur.execute(f"PRAGMA index_list({table})")
                idx = [{"name": r[1], "unique": bool(r[2])} for r in cur.fetchall()]
            elif kind == "postgres":
                where_schema = "AND table_schema = %s" if schema else ""
                args = (table, schema) if schema else (table,)
                cur.execute(f"""
                    SELECT column_name, data_type, is_nullable, column_default
                    FROM information_schema.columns
                    WHERE table_name = %s {where_schema}
                    ORDER BY ordinal_position
                """, args)
                cols = [{"name": r[0], "type": r[1], "nullable": r[2] == 'YES', "default": r[3]}
                        for r in cur.fetchall()]
                cur.execute("""
                    SELECT i.relname, ix.indisunique
                    FROM pg_class t, pg_class i, pg_index ix
                    WHERE t.oid = ix.indrelid AND i.oid = ix.indexrelid AND t.relname = %s
                """, (table,))
                idx = [{"name": r[0], "unique": r[1]} for r in cur.fetchall()]
            elif kind == "mysql":
                args_db = (table,) if not schema else (table, schema)
                where_schema = "AND table_schema = %s" if schema else "AND table_schema = DATABASE()"
                cur.execute(f"""
                    SELECT column_name, column_type, is_nullable, column_default
                    FROM information_schema.columns
                    WHERE table_name = %s {where_schema}
                    ORDER BY ordinal_position
                """, args_db)
                cols = [{"name": r["column_name"], "type": r["column_type"],
                         "nullable": r["is_nullable"] == 'YES', "default": r["column_default"]}
                        for r in cur.fetchall()]
            return json.dumps({"columns": cols, "indexes": idx}, ensure_ascii=False, indent=2)
    except Exception as e:
        return json.dumps({"error": f"{type(e).__name__}: {e}"})


@mcp.tool()
def explain(dsn: str, sql: str, params: list[Any] | None = None) -> str:
    """Run EXPLAIN on a SELECT and return the plan as text.

    Args:
        dsn: Connection string.
        sql: SQL (SELECT only).
        params: Optional params.

    Returns:
        Plan text or JSON depending on backend.
    """
    if WRITE_KW.search(re.sub(r"--[^\n]*", "", sql)):
        return json.dumps({"error": "explain only supports read queries"})
    try:
        with _connect(dsn) as (kind, conn):
            cur = conn.cursor()
            if kind == "sqlite":
                cur.execute(f"EXPLAIN QUERY PLAN {sql}", params or [])
                return json.dumps([list(r) for r in cur.fetchall()], indent=2)
            if kind == "postgres":
                cur.execute(f"EXPLAIN (FORMAT JSON) {sql}", params or [])
                row = cur.fetchone()
                return json.dumps(row[0] if row else None, ensure_ascii=False, indent=2)
            if kind == "mysql":
                cur.execute(f"EXPLAIN FORMAT=JSON {sql}", params or [])
                row = cur.fetchone()
                return json.dumps(list(row.values())[0] if row else None, indent=2)
        return json.dumps({"error": "unknown kind"})
    except Exception as e:
        return json.dumps({"error": f"{type(e).__name__}: {e}"})


if __name__ == "__main__":
    mcp.run()
