"""systemd timers and disk usage on the host."""

from __future__ import annotations

import json
import os
import shutil
from datetime import UTC, datetime
from pathlib import Path

from .config import Config
from .errors import ToolDenied, ToolError
from .runner import CommandError, Runner

MAX_PATHS = 20


class Host:
    def __init__(self, config: Config, runner: Runner):
        self.config = config
        self.runner = runner

    def systemd_timers(self) -> dict:
        argv = ["systemctl", "list-timers", "--all", "--no-pager", "--output=json"]
        try:
            res = self.runner(argv, self.config.systemd_timeout)
        except CommandError as exc:
            raise ToolError(str(exc)) from exc
        if res.returncode != 0:
            raise ToolError(f"systemctl failed ({res.returncode}): {res.stderr.strip()[:500]}")
        try:
            raw = json.loads(res.stdout or "[]")
        except json.JSONDecodeError as exc:
            raise ToolError(f"systemctl returned invalid JSON: {exc}") from exc
        timers = [
            {
                "unit": t.get("unit"),
                "activates": t.get("activates"),
                "next": _usec_to_iso(t.get("next")),
                "last": _usec_to_iso(t.get("last")),
            }
            for t in raw
        ]
        return {"timers": timers}

    def disk_usage(self, paths: list[str] | None = None) -> dict:
        paths = list(paths or self.config.disk_allowed_paths)
        if len(paths) > MAX_PATHS:
            raise ToolDenied(f"at most {MAX_PATHS} paths per call")
        results = []
        for p in paths:
            self._check_path(p)
            try:
                usage = shutil.disk_usage(p)
            except OSError as exc:
                results.append({"path": p, "error": exc.strerror or str(exc)})
                continue
            results.append(
                {
                    "path": p,
                    "total_gb": round(usage.total / 1e9, 2),
                    "used_gb": round(usage.used / 1e9, 2),
                    "free_gb": round(usage.free / 1e9, 2),
                    "used_percent": (
                        round(100 * usage.used / usage.total, 1) if usage.total else None
                    ),
                }
            )
        return {"disks": results}

    def _check_path(self, p: str) -> None:
        if not isinstance(p, str) or not os.path.isabs(p):
            raise ToolDenied(f"path must be absolute: {p!r}")
        real = Path(os.path.realpath(p))
        for allowed in self.config.disk_allowed_paths:
            base = Path(os.path.realpath(allowed))
            if real == base or base in real.parents:
                return
        raise ToolDenied(
            f"path {p!r} is not under an allowed path ({', '.join(self.config.disk_allowed_paths)})"
        )


def _usec_to_iso(value):
    """systemctl JSON gives timestamps as microseconds since epoch (0/None = never)."""
    if value in (None, 0, ""):
        return None
    if isinstance(value, (int, float)):
        return datetime.fromtimestamp(value / 1e6, UTC).isoformat(timespec="seconds")
    return str(value)
