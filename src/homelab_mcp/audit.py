"""Append one JSON line per tool call."""

from __future__ import annotations

import json
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any


class AuditLog:
    def __init__(self, path: str | Path):
        self.path = Path(path).expanduser()

    def write(
        self,
        *,
        tool: str,
        arguments: dict[str, Any],
        allowed: bool,
        ok: bool,
        result_bytes: int,
        duration_ms: float,
        error: str | None = None,
        executed: bool | None = None,
    ) -> None:
        record = {
            "ts": datetime.now(UTC).isoformat(timespec="seconds"),
            "tool": tool,
            "arguments": arguments,
            "allowed": allowed,
            "ok": ok,
            "result_bytes": result_bytes,
            "duration_ms": round(duration_ms, 1),
        }
        if error:
            record["error"] = error
        if executed is not None:
            record["executed"] = executed
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.path.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(record, default=str) + "\n")


def now_ms() -> float:
    return time.monotonic() * 1000
