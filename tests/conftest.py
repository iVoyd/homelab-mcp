from pathlib import Path

import pytest

from homelab_mcp.audit import AuditLog
from homelab_mcp.config import config_from_dict
from homelab_mcp.runner import Result
from homelab_mcp.service import Service

FIXTURES = Path(__file__).parent / "fixtures"


def fixture(name: str) -> str:
    return (FIXTURES / name).read_text()


class FakeRunner:
    """Stands in for runner.run: returns recorded output keyed by argv."""

    def __init__(self):
        self.calls: list[tuple[list[str], float]] = []
        self.responses: dict[tuple[str, ...], Result] = {}
        self.raise_exc: Exception | None = None

    def add(self, key: tuple[str, ...], stdout="", returncode=0, stderr=""):
        self.responses[key] = Result(returncode, stdout, stderr)

    def __call__(self, argv, timeout):
        self.calls.append((list(argv), timeout))
        if self.raise_exc:
            raise self.raise_exc
        for key, res in reversed(self.responses.items()):  # newest first
            if all(k in argv for k in key):
                return res
        return Result(1, "", f"no fixture for {argv}")


@pytest.fixture
def sample_db(tmp_path):
    import sqlite3

    path = tmp_path / "app.db"
    conn = sqlite3.connect(path)
    conn.executescript(
        """
        CREATE TABLE runs(id INTEGER PRIMARY KEY, started TEXT, status TEXT, matches INT,
                          note TEXT);
        INSERT INTO runs(started, status, matches, note) VALUES
          ('2026-11-02T03:15:00Z', 'failed', 0, 'contact admin@example.com'),
          ('2026-11-03T03:15:00Z', 'ok', 3, 'key sk-ant-api03-ZZZZZZZZZZZZZZZZZZZZ');
        CREATE TABLE big(n INT);
        WITH RECURSIVE c(x) AS (SELECT 1 UNION ALL SELECT x+1 FROM c WHERE x < 500)
          INSERT INTO big SELECT x FROM c;
        """
    )
    conn.commit()
    conn.close()
    return path


@pytest.fixture
def make_config(tmp_path, sample_db):
    def _make(**overrides):
        data = {
            "k3s": {"kubectl": ["kubectl"], "allowed_namespaces": ["default"]},
            "sqlite": {"databases": {"app": str(sample_db)}, "timeout_seconds": 2},
            "disk": {"allowed_paths": [str(tmp_path), "/"]},
            "audit": {"path": str(tmp_path / "audit.jsonl")},
            "redaction": {"patterns": [r"HOMELAB-\d{4}"]},
        }
        for section, values in overrides.items():
            data.setdefault(section, {}).update(values)
        return config_from_dict(data)

    return _make


@pytest.fixture
def runner():
    r = FakeRunner()
    r.add(("get", "cronjobs"), fixture("kubectl_get_cronjobs.json"))
    r.add(("get", "jobs"), fixture("kubectl_get_jobs.json"))
    r.add(("logs",), fixture("kubectl_logs.txt"))
    r.add(("systemctl", "list-timers"), fixture("systemctl_list_timers.json"))
    return r


@pytest.fixture
def service(make_config, runner):
    cfg = make_config()
    return Service(cfg, runner=runner, audit=AuditLog(cfg.audit_path))
