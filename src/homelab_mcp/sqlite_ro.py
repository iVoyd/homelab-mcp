"""Read-only SQLite queries.

Four layers, any one of which blocks writes on its own:
1. Text guard: one statement, must start with SELECT or WITH.
2. The file is opened with ?mode=ro (SQLite refuses writes).
3. PRAGMA query_only = ON.
4. An authorizer that only allows SELECT/READ/function calls (no ATTACH,
   PRAGMA, writes, or DDL).
Plus a row cap and a wall-clock timeout via the progress handler.
"""

from __future__ import annotations

import re
import sqlite3
import time
from pathlib import Path
from urllib.parse import quote

from .config import SQL_ROWS_HARD_CAP, Config
from .errors import ToolDenied, ToolError

_COMMENT_RE = re.compile(r"--[^\n]*|/\*.*?\*/", re.S)
_STRING_RE = re.compile(r"'(?:[^']|'')*'|\"(?:[^\"]|\"\")*\"")

_ALLOWED_ACTIONS = {sqlite3.SQLITE_SELECT, sqlite3.SQLITE_READ, sqlite3.SQLITE_FUNCTION}
_ALLOWED_ACTIONS |= {getattr(sqlite3, "SQLITE_RECURSIVE", 33)}  # WITH RECURSIVE
_DENIED_FUNCTIONS = {"load_extension", "readfile", "writefile", "edit", "fts3_tokenizer"}


def check_select_only(sql: str) -> str:
    """Reject anything that is not a single SELECT/WITH statement. Returns cleaned SQL."""
    if not isinstance(sql, str) or not sql.strip():
        raise ToolDenied("empty SQL")
    if len(sql) > 10_000:
        raise ToolDenied("SQL too long (max 10000 characters)")
    stripped = _COMMENT_RE.sub(" ", sql).strip()
    stripped = stripped.rstrip(";").strip()
    # Remove string literals before looking for extra statements.
    if ";" in _STRING_RE.sub("''", stripped):
        raise ToolDenied("only one statement is allowed")
    first = stripped.split(None, 1)[0].upper() if stripped else ""
    if first not in {"SELECT", "WITH"}:
        raise ToolDenied(f"only SELECT queries are allowed (got {first or 'nothing'})")
    return stripped


def _authorizer(action, arg1, arg2, dbname, source):
    if action == sqlite3.SQLITE_FUNCTION:
        denied = (arg2 or "").lower() in _DENIED_FUNCTIONS
        return sqlite3.SQLITE_DENY if denied else sqlite3.SQLITE_OK
    return sqlite3.SQLITE_OK if action in _ALLOWED_ACTIONS else sqlite3.SQLITE_DENY


class SqliteReadOnly:
    def __init__(self, config: Config):
        self.config = config

    def query(self, db_alias: str, sql: str) -> dict:
        if db_alias not in self.config.sqlite_databases:
            raise ToolDenied(
                f"unknown db_alias {db_alias!r}; known: "
                f"{', '.join(sorted(self.config.sqlite_databases)) or '(none)'}"
            )
        cleaned = check_select_only(sql)
        path = Path(self.config.sqlite_databases[db_alias]).expanduser()
        if not path.is_file():
            raise ToolError(f"database file not found for alias {db_alias!r}")

        max_rows = min(self.config.sqlite_max_rows, SQL_ROWS_HARD_CAP)
        deadline = time.monotonic() + self.config.sqlite_timeout
        uri = f"file:{quote(str(path))}?mode=ro"
        conn = sqlite3.connect(uri, uri=True, timeout=self.config.sqlite_timeout)
        try:
            conn.execute("PRAGMA query_only = ON")
            conn.set_authorizer(_authorizer)
            # Returning non-zero aborts the query; checked every 10k VM steps.
            conn.set_progress_handler(lambda: int(time.monotonic() > deadline), 10_000)
            try:
                cur = conn.execute(cleaned)
                rows = cur.fetchmany(max_rows + 1)
            except sqlite3.OperationalError as exc:
                if "interrupted" in str(exc):
                    raise ToolError(
                        f"query timed out after {self.config.sqlite_timeout:g}s"
                    ) from exc
                if "not authorized" in str(exc):
                    raise ToolDenied(f"query not allowed: {exc}") from exc
                raise ToolError(f"sqlite error: {exc}") from exc
            except sqlite3.DatabaseError as exc:
                raise ToolError(f"sqlite error: {exc}") from exc
            columns = [d[0] for d in cur.description or []]
        finally:
            conn.close()

        truncated = len(rows) > max_rows
        rows = rows[:max_rows]
        return {
            "db_alias": db_alias,
            "columns": columns,
            "rows": [[_jsonable(v) for v in row] for row in rows],
            "row_count": len(rows),
            "truncated": truncated,
        }


def _jsonable(value):
    if isinstance(value, bytes):
        return f"<{len(value)} bytes>"
    return value
