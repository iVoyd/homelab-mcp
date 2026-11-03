# SPEC: homelab-mcp

A small Model Context Protocol (MCP) server that lets an AI assistant safely inspect a home
lab: k3s CronJobs and Job status, recent job logs, a SQLite app database (read-only), systemd
timers, and disk usage. Read-only by default, with one opt-in action behind an approval gate,
secret redaction, and an audit log. Runs on the PC1 Linux VM.

## Design

- Python, official MCP SDK (`mcp`), stdio transport. Configuration in `config.toml`:
  allowed namespaces, allowed SQLite path(s), log line caps, redaction patterns.
- Every tool call is written to an audit log (JSON lines): tool, arguments, result size,
  duration, and whether it was allowed.
- Redaction: strip API keys, tokens, emails and anything matching configured patterns
  from all outputs.
- Subprocess calls use fixed argument lists (no shell), with timeouts.

## Milestone 1: read-only tools

- `k3s_cronjobs(namespace)`: schedule, last schedule, suspended, active.
- `k3s_jobs(namespace, limit)`: recent Jobs with status, duration, completion.
- `job_logs(namespace, job, tail≤200)`: last lines of a Job's pod logs, redacted.
- `sqlite_query(db_alias, sql)`: read-only (open with `mode=ro`, reject non-SELECT,
  row cap 200, timeout).
- `systemd_timers()`, `disk_usage(paths)`.
- Done when: tests with mocked subprocess/SQLite cover every tool, redaction and the
  read-only SQL guard; `homelab-mcp --selftest` runs on the VM.

## Milestone 2: approval-gated action + client setup

- One action, `run_job(cronjob)`: creates a one-off Job from an allowed CronJob, only if
  `actions.enabled = true` in config AND the call includes `confirm: true`; otherwise it
  returns what it would do. Audit-logged.
- README: setup on the VM, MCP client config for Claude Desktop / Claude Code, security
  model (threat list: prompt injection via logs, SQL abuse, secret leaks) and how each is
  handled.
- Done when: a recorded demo (transcript or GIF) shows an assistant answering "did last
  night's job succeed, and what did it find?" using only these tools.
