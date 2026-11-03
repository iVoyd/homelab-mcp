"""Command line entry point: run the stdio server, or --selftest."""

from __future__ import annotations

import argparse
import asyncio
import json
import sys

from . import __version__
from .config import ConfigError, load_config
from .server import build_server
from .service import Service

EXPECTED_TOOLS = {
    "k3s_cronjobs", "k3s_jobs", "job_logs", "sqlite_query", "systemd_timers", "disk_usage",
    "run_job",
}


def selftest(service: Service, out=None) -> int:
    """Call every tool once against the real host. Returns a process exit code."""
    out = out or sys.stdout
    cfg = service.config
    checks: list[tuple[str, dict | str]] = []  # str = reason skipped

    tools = {t.name for t in asyncio.run(build_server(service).list_tools())}
    missing = EXPECTED_TOOLS - tools
    checks.append(("mcp tool registry", {"error": f"missing {missing}"} if missing else {}))

    ns = cfg.allowed_namespaces[0] if cfg.allowed_namespaces else None
    if ns:
        checks.append((f"k3s_cronjobs({ns})", service.k3s_cronjobs(ns)))
        jobs = service.k3s_jobs(ns, 5)
        checks.append((f"k3s_jobs({ns})", jobs))
        latest = (jobs.get("jobs") or [None])[0]
        if latest:
            checks.append(
                (f"job_logs({ns}, {latest['name']})", service.job_logs(ns, latest["name"], 5))
            )
        else:
            checks.append(("job_logs", "no Jobs found to read logs from"))
    else:
        skip = "no k3s.allowed_namespaces"
        checks += [("k3s_cronjobs", skip), ("k3s_jobs", skip), ("job_logs", skip)]

    if cfg.sqlite_databases:
        alias = sorted(cfg.sqlite_databases)[0]
        checks.append(
            (f"sqlite_query({alias})",
             service.sqlite_query(alias, "SELECT name FROM sqlite_master LIMIT 5"))
        )
        denied = service.sqlite_query(alias, "DELETE FROM sqlite_master")
        guard = {} if denied.get("denied") else {"error": "write was not denied!"}
        checks.append((f"sqlite read-only guard({alias})", guard))
    else:
        checks.append(("sqlite_query", "no sqlite.databases"))

    checks.append(("systemd_timers", service.systemd_timers()))
    checks.append(("disk_usage", service.disk_usage()))

    # run_job is only ever called without confirm here, so it cannot create anything.
    if cfg.actions_allowed_cronjobs:
        target = cfg.actions_allowed_cronjobs[0]
        plan = service.run_job(target, confirm=False)
        if "error" not in plan and plan.get("executed") is not False:
            plan = {"error": "dry run reported executed!"}
        checks.append((f"run_job dry run({target})", plan))
    else:
        checks.append(("run_job dry run", "no actions.allowed_cronjobs"))
    print(f"actions.enabled = {str(cfg.actions_enabled).lower()}", file=out)

    failures = 0
    for name, result in checks:
        if isinstance(result, str):
            line = f"SKIP  {name}  ({result})"
        elif "error" in result:
            failures += 1
            line = f"FAIL  {name}  {result['error']}"
        else:
            line = f"OK    {name}"
        print(line, file=out)
    print(f"\nconfig: {cfg.source}\naudit log: {service.audit.path}", file=out)
    print("selftest " + ("passed" if failures == 0 else f"failed ({failures})"), file=out)
    return 0 if failures == 0 else 1


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="homelab-mcp", description=__doc__)
    parser.add_argument("--config", help="path to config.toml")
    parser.add_argument("--selftest", action="store_true", help="call every tool once and exit")
    parser.add_argument("--call", metavar="TOOL", help="call one tool and print JSON (debug)")
    parser.add_argument("--args", default="{}", help="JSON arguments for --call")
    parser.add_argument("--version", action="version", version=__version__)
    args = parser.parse_args(argv)

    try:
        config = load_config(args.config)
    except ConfigError as exc:
        print(f"homelab-mcp: {exc}", file=sys.stderr)
        return 2
    service = Service(config)

    if args.selftest:
        return selftest(service)
    if args.call:
        if args.call not in EXPECTED_TOOLS:
            print(f"unknown tool {args.call}", file=sys.stderr)
            return 2
        result = getattr(service, args.call)(**json.loads(args.args))
        print(json.dumps(result, indent=2))
        return 0 if "error" not in result else 1

    build_server(service).run("stdio")
    return 0


if __name__ == "__main__":
    sys.exit(main())
