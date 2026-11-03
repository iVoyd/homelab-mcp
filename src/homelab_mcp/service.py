"""Ties tools to policy: every call is redacted and audit-logged."""

from __future__ import annotations

import json
from collections.abc import Callable
from typing import Any

from .actions import Actions
from .audit import AuditLog, now_ms
from .config import Config
from .errors import ToolDenied, ToolError
from .host import Host
from .k3s import K3s
from .redact import Redactor
from .runner import Runner, run
from .sqlite_ro import SqliteReadOnly


class Service:
    def __init__(self, config: Config, runner: Runner = run, audit: AuditLog | None = None):
        self.config = config
        self.redactor = Redactor(config.redaction_patterns)
        self.audit = audit or AuditLog(config.audit_path)
        self.k3s = K3s(config, runner)
        self.sqlite = SqliteReadOnly(config)
        self.host = Host(config, runner)
        self.actions = Actions(config, self.k3s)

    def call(self, tool: str, fn: Callable[..., dict], **arguments: Any) -> dict:
        """Run a tool, never raise: errors become {"error": ...} results."""
        start = now_ms()
        allowed, ok, error = True, True, None
        try:
            result = fn(**arguments)
        except ToolDenied as exc:
            allowed, ok, error = False, False, str(exc)
            result = {"error": error, "denied": True}
        except ToolError as exc:
            ok, error = False, str(exc)
            result = {"error": error}
        except Exception as exc:  # unexpected bug: report, don't crash the server
            ok, error = False, f"internal error: {type(exc).__name__}: {exc}"
            result = {"error": error}
        result = self.redactor.any(result)
        size = len(json.dumps(result, default=str))
        self.audit.write(
            tool=tool,
            arguments=self.redactor.any(arguments),
            allowed=allowed,
            ok=ok,
            result_bytes=size,
            duration_ms=now_ms() - start,
            error=self.redactor.text(error) if error else None,
            executed=result.get("executed"),
        )
        return result

    # One method per MCP tool, so the server module stays a thin shim.
    def k3s_cronjobs(self, namespace: str) -> dict:
        return self.call("k3s_cronjobs", self.k3s.cronjobs, namespace=namespace)

    def k3s_jobs(self, namespace: str, limit: int = 10) -> dict:
        return self.call("k3s_jobs", self.k3s.jobs, namespace=namespace, limit=limit)

    def job_logs(self, namespace: str, job: str, tail: int = 100) -> dict:
        return self.call("job_logs", self.k3s.logs, namespace=namespace, job=job, tail=tail)

    def sqlite_query(self, db_alias: str, sql: str) -> dict:
        return self.call("sqlite_query", self.sqlite.query, db_alias=db_alias, sql=sql)

    def systemd_timers(self) -> dict:
        return self.call("systemd_timers", self.host.systemd_timers)

    def disk_usage(self, paths: list[str] | None = None) -> dict:
        return self.call("disk_usage", self.host.disk_usage, paths=paths)

    def run_job(self, cronjob: str, confirm: bool = False) -> dict:
        return self.call("run_job", self.actions.run_job, cronjob=cronjob, confirm=confirm)
