import json

from homelab_mcp.runner import CommandError


def test_cronjobs_parses_schedule_and_status(service, runner):
    out = service.k3s_cronjobs("default")
    by_name = {c["name"]: c for c in out["cronjobs"]}
    nightly = by_name["nightly-report"]
    assert nightly == {
        "name": "nightly-report",
        "schedule": "15 3 * * *",
        "timezone": "Europe/Dublin",
        "suspended": False,
        "last_schedule": "2026-11-03T03:15:00Z",
        "last_successful": "2026-11-03T03:19:42Z",
        "active": 0,
    }
    assert by_name["backup-db"]["suspended"] is True
    assert by_name["backup-db"]["active"] == 1
    argv, timeout = runner.calls[0]
    assert argv == ["kubectl", "get", "cronjobs", "-n", "default", "-o", "json"]
    assert timeout == 15


def test_namespace_not_allowed_is_denied_without_running_kubectl(service, runner):
    out = service.k3s_cronjobs("kube-system")
    assert out["denied"] is True
    assert "not allowed" in out["error"]
    assert runner.calls == []


def test_jobs_newest_first_with_status_and_duration(service):
    out = service.k3s_jobs("default", limit=10)
    names = [j["name"] for j in out["jobs"]]
    assert names == ["manual-check", "nightly-report-29370435", "nightly-report-29368995"]
    running, ok, failed = out["jobs"]
    assert running["status"] == "running" and running["duration_seconds"] is None
    assert ok["status"] == "succeeded"
    assert ok["duration_seconds"] == 282
    assert ok["cronjob"] == "nightly-report"
    assert failed["status"] == "failed"
    assert failed["failure_reason"] == "BackoffLimitExceeded"
    assert failed["duration_seconds"] == 90


def test_jobs_limit_is_capped(service):
    assert len(service.k3s_jobs("default", limit=1)["jobs"]) == 1
    assert service.k3s_jobs("default", limit=10_000)["total"] == 3
    assert len(service.k3s_jobs("default", limit=0)["jobs"]) == 1


def test_job_logs_are_tailed_capped_and_redacted(service, runner):
    out = service.job_logs("default", "nightly-report-29370435", tail=500)
    argv, _ = runner.calls[0]
    assert argv == [
        "kubectl", "logs", "-n", "default", "job/nightly-report-29370435",
        "--tail=200", "--all-containers=true",
    ]
    log = out["log"]
    assert "sk-ant-" not in log
    assert "ghp_" not in log
    assert "theo@example.com" not in log
    assert "abc.def.ghijkl" not in log
    assert "[REDACTED:anthropic_key]" in log
    assert "scored 42 records" in log
    assert "untrusted" in out["note"]


def test_job_logs_tail_respects_small_value(service, runner):
    out = service.job_logs("default", "x", tail=3)
    assert "--tail=3" in runner.calls[0][0]
    assert out["lines"] == 3


def test_job_name_injection_is_rejected(service, runner):
    for bad in ["--all-namespaces", "a b", "../etc", "Job", "", "x;rm -rf"]:
        out = service.job_logs("default", bad)
        assert out.get("denied"), bad
    assert runner.calls == []


def test_kubectl_failure_is_reported(service, runner):
    runner.add(("get", "jobs"), "", returncode=1, stderr="error: connection refused")
    out = service.k3s_jobs("default")
    assert "connection refused" in out["error"]
    assert "denied" not in out


def test_kubectl_timeout_is_reported(service, runner):
    runner.raise_exc = CommandError("timed out after 15s: kubectl")
    assert "timed out" in service.k3s_cronjobs("default")["error"]


def test_bad_json_is_reported(service, runner):
    runner.add(("get", "cronjobs"), "not json")
    assert "invalid JSON" in service.k3s_cronjobs("default")["error"]


def test_kubectl_prefix_and_kubeconfig(make_config, runner):
    from homelab_mcp.service import Service

    cfg = make_config(k3s={"kubectl": ["k3s", "kubectl"], "kubeconfig": "/etc/kc.yaml"})
    Service(cfg, runner=runner).k3s_cronjobs("default")
    assert runner.calls[0][0][:4] == ["k3s", "kubectl", "--kubeconfig", "/etc/kc.yaml"]


def test_results_are_json_serialisable(service):
    json.dumps(service.k3s_jobs("default"))
