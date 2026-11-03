import sqlite3

import pytest

from homelab_mcp.errors import ToolDenied
from homelab_mcp.sqlite_ro import check_select_only


def test_select_returns_rows_and_columns(service):
    out = service.sqlite_query("app", "SELECT id, status, matches FROM runs ORDER BY id")
    assert out["columns"] == ["id", "status", "matches"]
    assert out["rows"] == [[1, "failed", 0], [2, "ok", 3]]
    assert out["truncated"] is False


def test_with_cte_is_allowed(service):
    out = service.sqlite_query("app", "WITH r AS (SELECT * FROM runs) SELECT count(*) FROM r")
    assert out["rows"] == [[2]]


def test_row_cap_200(service):
    out = service.sqlite_query("app", "SELECT n FROM big")
    assert out["row_count"] == 200
    assert out["truncated"] is True


def test_row_values_are_redacted(service):
    out = service.sqlite_query("app", "SELECT note FROM runs ORDER BY id")
    flat = " ".join(r[0] for r in out["rows"])
    assert "admin@example.com" not in flat
    assert "sk-ant-" not in flat


def test_unknown_alias_denied(service):
    out = service.sqlite_query("nope", "SELECT 1")
    assert out["denied"] is True


@pytest.mark.parametrize(
    "sql",
    [
        "DELETE FROM runs",
        "UPDATE runs SET status='x'",
        "INSERT INTO runs(status) VALUES('x')",
        "DROP TABLE runs",
        "CREATE TABLE t(x)",
        "PRAGMA writable_schema = ON",
        "ATTACH DATABASE '/tmp/x.db' AS x",
        "VACUUM INTO '/tmp/copy.db'",
        "SELECT 1; DELETE FROM runs",
        "select 1;\nDROP TABLE runs;",
        "/* hi */ DELETE FROM runs",
        "-- comment\nUPDATE runs SET status='x'",
        "",
        "   ",
    ],
)
def test_text_guard_rejects_non_select(service, sql, sample_db):
    out = service.sqlite_query("app", sql)
    assert out.get("denied") is True, out
    # Database is untouched.
    conn = sqlite3.connect(sample_db)
    assert conn.execute("SELECT count(*) FROM runs").fetchone() == (2,)
    conn.close()


def test_semicolon_inside_string_is_fine():
    assert check_select_only("SELECT 'a;b'") == "SELECT 'a;b'"
    assert check_select_only("SELECT 1;") == "SELECT 1"


@pytest.mark.parametrize(
    "sql",
    [
        # Passes the text guard but must still be blocked by the engine layers.
        "WITH x AS (SELECT 1) DELETE FROM runs",
        "WITH x AS (SELECT 1) INSERT INTO runs(status) SELECT 'x'",
        "SELECT load_extension('/tmp/evil.so')",
        "SELECT * FROM pragma_table_info('runs') JOIN runs",
    ],
)
def test_engine_layers_block_what_text_guard_lets_through(service, sql, sample_db):
    out = service.sqlite_query("app", sql)
    assert "error" in out, out
    conn = sqlite3.connect(sample_db)
    assert conn.execute("SELECT count(*) FROM runs").fetchone() == (2,)
    conn.close()


def test_write_cte_reported_as_denied(service):
    out = service.sqlite_query("app", "WITH x AS (SELECT 1) DELETE FROM runs")
    assert out.get("denied") is True


def test_timeout_aborts_long_query(make_config):
    from homelab_mcp.service import Service

    cfg = make_config(sqlite={"timeout_seconds": 0.2})
    svc = Service(cfg, runner=lambda *a: None)
    sql = (
        "WITH RECURSIVE c(x) AS (SELECT 1 UNION ALL SELECT x+1 FROM c) "
        "SELECT count(*) FROM c"
    )
    out = svc.sqlite_query("app", sql)
    assert "timed out" in out["error"]


def test_missing_db_file(make_config, tmp_path):
    from homelab_mcp.service import Service

    cfg = make_config(sqlite={"databases": {"gone": str(tmp_path / "missing.db")}})
    out = Service(cfg, runner=lambda *a: None).sqlite_query("gone", "SELECT 1")
    assert "not found" in out["error"]
    assert not (tmp_path / "missing.db").exists()  # mode=ro must not create it


def test_blob_values_are_summarised(service, sample_db):
    out = service.sqlite_query("app", "SELECT x'00ff'")
    assert out["rows"] == [["<2 bytes>"]]


def test_check_select_only_raises():
    with pytest.raises(ToolDenied):
        check_select_only("EXPLAIN SELECT 1")
