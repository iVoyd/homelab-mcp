import asyncio
import json

from homelab_mcp.cli import EXPECTED_TOOLS, main, selftest
from homelab_mcp.server import build_server


def read_audit(service):
    return [json.loads(line) for line in service.audit.path.read_text().splitlines()]


def test_every_call_is_audited(service):
    service.k3s_cronjobs("default")
    service.k3s_cronjobs("kube-system")
    service.sqlite_query("app", "DELETE FROM runs")
    service.sqlite_query("app", "SELECT 1")
    records = read_audit(service)
    assert [r["tool"] for r in records] == [
        "k3s_cronjobs", "k3s_cronjobs", "sqlite_query", "sqlite_query",
    ]
    assert [r["allowed"] for r in records] == [True, False, False, True]
    for r in records:
        assert set(r) >= {"ts", "tool", "arguments", "allowed", "ok", "result_bytes",
                          "duration_ms"}
        assert r["result_bytes"] > 0
    assert records[1]["arguments"] == {"namespace": "kube-system"}


def test_audit_arguments_are_redacted(service):
    service.sqlite_query("app", "SELECT 'sk-ant-api03-SECRETSECRETSECRET'")
    rec = read_audit(service)[-1]
    assert "SECRETSECRET" not in json.dumps(rec)


def test_unexpected_exception_does_not_crash(service):
    def boom(**_):
        raise RuntimeError("bug")

    out = service.call("x", boom)
    assert "internal error" in out["error"]


def test_mcp_server_lists_all_tools(service):
    server = build_server(service)
    tools = {t.name: t for t in asyncio.run(server.list_tools())}
    assert set(tools) == EXPECTED_TOOLS
    assert "max 200" in tools["job_logs"].description


def test_mcp_call_tool_end_to_end(service):
    server = build_server(service)
    res = asyncio.run(server.call_tool("k3s_jobs", {"namespace": "default", "limit": 1}))
    assert res.is_error is False
    payload = json.loads(res.content[0].text)
    assert payload["jobs"][0]["name"] == "manual-check"


def test_selftest_passes_with_fixtures(service, capsys):
    code = selftest(service)
    out = capsys.readouterr().out
    assert code == 0, out
    assert "selftest passed" in out
    assert "OK    sqlite read-only guard(app)" in out


def test_selftest_reports_failures(service, runner, capsys):
    runner.add(("get", "cronjobs"), "", returncode=1, stderr="forbidden")
    assert selftest(service) == 1
    assert "FAIL  k3s_cronjobs(default)" in capsys.readouterr().out


def test_cli_missing_config(tmp_path, monkeypatch, capsys):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.delenv("HOMELAB_MCP_CONFIG", raising=False)
    assert main(["--selftest"]) == 2
    assert "no config found" in capsys.readouterr().err


def test_cli_call_with_real_config_file(tmp_path, sample_db, capsys):
    cfg = tmp_path / "config.toml"
    cfg.write_text(
        f'[sqlite.databases]\napp = "{sample_db}"\n[audit]\npath = "{tmp_path}/a.jsonl"\n'
    )
    code = main(["--config", str(cfg), "--call", "sqlite_query",
                 "--args", '{"db_alias": "app", "sql": "SELECT count(*) FROM runs"}'])
    assert code == 0
    assert json.loads(capsys.readouterr().out)["rows"] == [[2]]
