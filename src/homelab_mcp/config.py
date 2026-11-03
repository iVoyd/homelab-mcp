"""Load config.toml into a plain dataclass."""

from __future__ import annotations

import os
import tomllib
from dataclasses import dataclass, field
from pathlib import Path

LOG_LINES_HARD_CAP = 200
SQL_ROWS_HARD_CAP = 200


class ConfigError(Exception):
    pass


@dataclass
class Config:
    kubectl: list[str] = field(default_factory=lambda: ["kubectl"])
    kubeconfig: str = ""
    allowed_namespaces: list[str] = field(default_factory=list)
    k3s_timeout: float = 15.0
    log_max_lines: int = LOG_LINES_HARD_CAP
    sqlite_databases: dict[str, str] = field(default_factory=dict)
    sqlite_timeout: float = 5.0
    sqlite_max_rows: int = SQL_ROWS_HARD_CAP
    disk_allowed_paths: list[str] = field(default_factory=lambda: ["/"])
    systemd_timeout: float = 10.0
    audit_path: str = "~/.local/state/homelab-mcp/audit.jsonl"
    redaction_patterns: list[str] = field(default_factory=list)
    actions_enabled: bool = False
    actions_kubeconfig: str = ""
    actions_allowed_cronjobs: list[str] = field(default_factory=list)
    source: str = "<defaults>"


def default_config_path() -> Path | None:
    """Return the first config file that exists, in search order."""
    candidates = []
    if os.environ.get("HOMELAB_MCP_CONFIG"):
        candidates.append(Path(os.environ["HOMELAB_MCP_CONFIG"]))
    candidates.append(Path("config.toml"))
    candidates.append(Path.home() / ".config" / "homelab-mcp" / "config.toml")
    for path in candidates:
        if path.is_file():
            return path
    return None


def load_config(path: str | Path | None = None) -> Config:
    if path is None:
        path = default_config_path()
        if path is None:
            raise ConfigError(
                "no config found: pass --config, set HOMELAB_MCP_CONFIG, or create "
                "~/.config/homelab-mcp/config.toml (see config.example.toml)"
            )
    path = Path(path).expanduser()
    try:
        data = tomllib.loads(path.read_text())
    except (OSError, tomllib.TOMLDecodeError) as exc:
        raise ConfigError(f"cannot read {path}: {exc}") from exc
    return config_from_dict(data, source=str(path))


def config_from_dict(data: dict, source: str = "<dict>") -> Config:
    k3s = data.get("k3s", {})
    logs = data.get("logs", {})
    sqlite = data.get("sqlite", {})
    disk = data.get("disk", {})
    systemd = data.get("systemd", {})
    audit = data.get("audit", {})
    redaction = data.get("redaction", {})
    actions = data.get("actions", {})

    kubectl = k3s.get("kubectl", ["kubectl"])
    if isinstance(kubectl, str):
        kubectl = kubectl.split()
    if not kubectl or not all(isinstance(p, str) for p in kubectl):
        raise ConfigError("k3s.kubectl must be a non-empty list of strings")

    databases = dict(sqlite.get("databases", {}))
    for alias, db_path in databases.items():
        if not Path(db_path).expanduser().is_absolute():
            raise ConfigError(f"sqlite.databases.{alias} must be an absolute path")

    enabled = actions.get("enabled", False)
    if not isinstance(enabled, bool):
        raise ConfigError("actions.enabled must be true or false")
    action_kubeconfig = actions.get("kubeconfig", "")
    if enabled and not action_kubeconfig:
        raise ConfigError("actions.enabled = true needs actions.kubeconfig (a separate kubeconfig)")
    if enabled and action_kubeconfig == k3s.get("kubeconfig", ""):
        raise ConfigError("actions.kubeconfig must differ from k3s.kubeconfig")
    allowed_cronjobs = list(actions.get("allowed_cronjobs", []))
    for entry in allowed_cronjobs:
        if not isinstance(entry, str) or entry.count("/") != 1:
            raise ConfigError(f"actions.allowed_cronjobs entry {entry!r} must be 'namespace/name'")

    return Config(
        kubectl=list(kubectl),
        kubeconfig=k3s.get("kubeconfig", ""),
        allowed_namespaces=list(k3s.get("allowed_namespaces", [])),
        k3s_timeout=float(k3s.get("timeout_seconds", 15)),
        log_max_lines=min(int(logs.get("max_lines", LOG_LINES_HARD_CAP)), LOG_LINES_HARD_CAP),
        sqlite_databases=databases,
        sqlite_timeout=float(sqlite.get("timeout_seconds", 5)),
        sqlite_max_rows=min(int(sqlite.get("max_rows", SQL_ROWS_HARD_CAP)), SQL_ROWS_HARD_CAP),
        disk_allowed_paths=list(disk.get("allowed_paths", ["/"])),
        systemd_timeout=float(systemd.get("timeout_seconds", 10)),
        audit_path=audit.get("path", "~/.local/state/homelab-mcp/audit.jsonl"),
        redaction_patterns=list(redaction.get("patterns", [])),
        actions_enabled=enabled,
        actions_kubeconfig=action_kubeconfig,
        actions_allowed_cronjobs=allowed_cronjobs,
        source=source,
    )
