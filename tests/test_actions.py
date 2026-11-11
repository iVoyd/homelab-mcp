import json
from datetime import UTC, datetime

import pytest

from homelab_mcp.cli import selftest
from homelab_mcp.config import ConfigError, config_from_dict
from homelab_mcp.service import Service

from .conftest import fixture

TARGET = "default/nightly-report"
FIXED = datetime(2026, 11, 3, 9, 30, 0, tzinfo=UTC)


@pytest.fixture
def action_runner(runner):
    runner.add(("get", "cronjob", "nightly-report"), fixture("kubectl_get_cronjob_single.json"))
    runner.add(("create", "job"), "job.batch/nightly-report-manual-20261103093000\n")
    return runner


def make_service(make_config, runner, enabled):
    actions = {"allowed_cronjobs": [TARGET], "enabled": enabled}
    if enabled:
        actions["kubeconfig"] = "/home/voyd/.kube/homelab-mcp-runner.yaml"
    svc = Service(make_config(actions=actions), runner=runner)
    svc.actions.clock = lambda: FIXED
    return svc


def creates(runner):
    return [argv for argv, _ in runner.calls if "create" in argv]


def audit(svc):
    return [json.loads(x) for x in svc.audit.path.read_text().splitlines()]


def test_disabled_returns_plan_even_with_confirm(make_config, action_runner):
    svc = make_service(make_config, action_runner, enabled=False)
    out = svc.run_job(TARGET, confirm=True)
    assert out["executed"] is False
    assert "disabled" in out["reason"]
    assert out["plan"]["job_name"] == "nightly-report-manual-20261103093000"
    assert out["plan"]["cronjob_schedule"] == "15 3 * * *"
    assert creates(action_runner) == []
    assert audit(svc)[-1]["executed"] is False


def test_enabled_without_confirm_is_dry_run(make_config, action_runner):
    svc = make_service(make_config, action_runner, enabled=True)
    for confirm in (False, "true", 1):
        out = svc.run_job(TARGET, confirm=confirm)
        assert out["executed"] is False, confirm
        assert "dry run" in out["reason"]
    assert creates(action_runner) == []


def test_enabled_and_confirm_creates_job_with_action_kubeconfig(make_config, action_runner):
    svc = make_service(make_config, action_runner, enabled=True)
    out = svc.run_job(TARGET, confirm=True)
    assert out["executed"] is True
    assert out["created"] == "job.batch/nightly-report-manual-20261103093000"
    (argv,) = creates(action_runner)
    assert argv == [
        "kubectl", "--kubeconfig", "/home/voyd/.kube/homelab-mcp-runner.yaml",
        "create", "job", "nightly-report-manual-20261103093000",
        "--from=cronjob/nightly-report", "-n", "default", "-o", "name",
    ]
    # The lookup used the read-only kubeconfig (none configured here), not the action one.
    get_argv = next(a for a, _ in action_runner.calls if "get" in a)
    assert "/home/voyd/.kube/homelab-mcp-runner.yaml" not in get_argv
    rec = audit(svc)[-1]
    assert rec["tool"] == "run_job" and rec["executed"] is True and rec["allowed"] is True
    assert rec["arguments"] == {"cronjob": TARGET, "confirm": True}


@pytest.mark.parametrize(
    "cronjob",
    ["default/backup-db", "kube-system/nightly-report", "nightly-report", "a/b/c",
     "default/--all", "default/", ""],
)
def test_not_allowlisted_or_malformed_is_denied(make_config, action_runner, cronjob):
    svc = make_service(make_config, action_runner, enabled=True)
    out = svc.run_job(cronjob, confirm=True)
    assert out.get("denied") is True, out
    assert action_runner.calls == []
    assert audit(svc)[-1]["allowed"] is False


def test_allowlisted_but_namespace_not_allowed(make_config, action_runner):
    cfg = make_config(actions={"allowed_cronjobs": ["other/x"]})
    out = Service(cfg, runner=action_runner).run_job("other/x", confirm=True)
    assert out["denied"] is True
    assert action_runner.calls == []


def test_missing_cronjob_reports_error_and_creates_nothing(make_config, runner):
    runner.add(("get", "cronjob"), "", returncode=1, stderr='cronjobs "x" not found')
    svc = make_service(make_config, runner, enabled=True)
    out = svc.run_job(TARGET, confirm=True)
    assert "not found" in out["error"]
    assert creates(runner) == []


def test_create_failure_is_reported(make_config, action_runner):
    action_runner.add(("create", "job"), "", returncode=1, stderr="forbidden: cannot create jobs")
    svc = make_service(make_config, action_runner, enabled=True)
    out = svc.run_job(TARGET, confirm=True)
    assert "forbidden" in out["error"]
    assert audit(svc)[-1]["ok"] is False


def test_long_cronjob_name_is_truncated_to_63(make_config, runner):
    long = "a" * 60
    runner.add(("get", "cronjob", long), '{"spec": {"schedule": "* * * * *"}}')
    cfg = make_config(actions={"allowed_cronjobs": [f"default/{long}"]})
    svc = Service(cfg, runner=runner)
    name = svc.run_job(f"default/{long}")["plan"]["job_name"]
    assert len(name) <= 63
    assert name.startswith("a" * 40) and "-manual-" in name


def test_config_requires_separate_kubeconfig():
    with pytest.raises(ConfigError, match="needs actions.kubeconfig"):
        config_from_dict({"actions": {"enabled": True}})
    with pytest.raises(ConfigError, match="must differ"):
        config_from_dict({"k3s": {"kubeconfig": "/k"}, "actions": {"enabled": True,
                                                                   "kubeconfig": "/k"}})
    with pytest.raises(ConfigError, match="true or false"):
        config_from_dict({"actions": {"enabled": "yes"}})
    with pytest.raises(ConfigError, match="namespace/name"):
        config_from_dict({"actions": {"allowed_cronjobs": ["nonamespace"]}})


def test_selftest_runs_dry_run_only(make_config, action_runner, capsys):
    svc = make_service(make_config, action_runner, enabled=True)
    assert selftest(svc) == 0
    out = capsys.readouterr().out
    assert f"OK    run_job dry run({TARGET})" in out
    assert creates(action_runner) == []


def test_tool_annotations(service):
    import asyncio

    from homelab_mcp.server import build_server

    tools = {t.name: t for t in asyncio.run(build_server(service).list_tools())}
    assert tools["run_job"].annotations.read_only_hint is False
    assert all(t.annotations.read_only_hint for n, t in tools.items() if n != "run_job")
