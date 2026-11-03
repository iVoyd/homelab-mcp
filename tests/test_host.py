def test_systemd_timers(service, runner):
    out = service.systemd_timers()
    assert runner.calls[0][0] == [
        "systemctl", "list-timers", "--all", "--no-pager", "--output=json",
    ]
    apt, fstrim = out["timers"]
    assert apt["unit"] == "apt-daily.timer"
    assert apt["activates"] == "apt-daily.service"
    assert apt["next"] == "2025-11-04T03:00:00+00:00"
    assert fstrim["next"] is None and fstrim["last"] is None


def test_systemd_failure(service, runner):
    runner.add(("systemctl",), "", returncode=1, stderr="Failed to connect to bus")
    assert "Failed to connect to bus" in service.systemd_timers()["error"]


def test_disk_usage_default_paths(service):
    out = service.disk_usage()
    assert len(out["disks"]) == 2
    root = out["disks"][1]
    assert root["path"] == "/"
    assert root["total_gb"] > 0
    assert 0 <= root["used_percent"] <= 100


def test_disk_usage_subdir_allowed(service, tmp_path):
    sub = tmp_path / "sub"
    sub.mkdir()
    out = service.disk_usage([str(sub)])
    assert "error" not in out


def test_disk_usage_rejects_relative_and_outside(make_config, runner):
    from homelab_mcp.service import Service

    cfg = make_config(disk={"allowed_paths": ["/home"]})
    svc = Service(cfg, runner=runner)
    assert svc.disk_usage(["relative/path"])["denied"]
    assert svc.disk_usage(["/etc"])["denied"]
    assert svc.disk_usage(["/home/../etc"])["denied"]


def test_disk_usage_missing_path_reports_per_path_error(service, tmp_path):
    out = service.disk_usage([str(tmp_path / "nope")])
    assert "error" in out["disks"][0]
