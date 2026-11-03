"""The only place that starts subprocesses. Fixed argv, no shell, always a timeout."""

from __future__ import annotations

import subprocess
from dataclasses import dataclass
from typing import Protocol


class CommandError(Exception):
    pass


@dataclass
class Result:
    returncode: int
    stdout: str
    stderr: str


class Runner(Protocol):
    def __call__(self, argv: list[str], timeout: float) -> Result: ...


def run(argv: list[str], timeout: float) -> Result:
    if not argv or not all(isinstance(a, str) for a in argv):
        raise CommandError("argv must be a non-empty list of strings")
    try:
        proc = subprocess.run(  # noqa: S603 - fixed argv, shell=False
            argv,
            capture_output=True,
            text=True,
            timeout=timeout,
            shell=False,
            check=False,
        )
    except FileNotFoundError as exc:
        raise CommandError(f"command not found: {argv[0]}") from exc
    except subprocess.TimeoutExpired as exc:
        raise CommandError(f"timed out after {timeout:g}s: {argv[0]}") from exc
    return Result(proc.returncode, proc.stdout, proc.stderr)
