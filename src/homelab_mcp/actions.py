"""The one write action: start a Job from an allowed CronJob.

It only runs when all of these hold:
- the CronJob is listed in actions.allowed_cronjobs (as "namespace/name"),
- its namespace is in k3s.allowed_namespaces,
- actions.enabled = true in config,
- the call passes confirm = true.
Otherwise it returns the plan (what it would do) and changes nothing.
The create goes through actions.kubeconfig, a separate kubeconfig that only
needs "get cronjobs" and "create jobs"; the read-only tools never use it.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime

from .config import Config
from .errors import ToolDenied, ToolError
from .k3s import NAME_RE, K3s

MAX_NAME = 63  # Job names end up in a label value, which is capped at 63 chars.


class Actions:
    def __init__(self, config: Config, k3s: K3s, clock=lambda: datetime.now(UTC)):
        self.config = config
        self.k3s = k3s
        self.clock = clock

    def run_job(self, cronjob: str, confirm: bool = False) -> dict:
        namespace, name = self._parse(cronjob)
        if f"{namespace}/{name}" not in self.config.actions_allowed_cronjobs:
            raise ToolDenied(
                f"{namespace}/{name} is not in actions.allowed_cronjobs; allowed: "
                f"{', '.join(self.config.actions_allowed_cronjobs) or '(none)'}"
            )
        self.k3s.check_namespace(namespace)

        # Read the CronJob with the read-only kubeconfig to show what would run.
        try:
            cj = json.loads(self.k3s.kubectl("get", "cronjob", name, "-n", namespace, "-o", "json"))
        except json.JSONDecodeError as exc:
            raise ToolError(f"kubectl returned invalid JSON: {exc}") from exc

        job_name = self._job_name(name)
        plan = {
            "action": "create Job from CronJob",
            "namespace": namespace,
            "cronjob": name,
            "job_name": job_name,
            "cronjob_schedule": cj.get("spec", {}).get("schedule"),
            "cronjob_suspended": bool(cj.get("spec", {}).get("suspend", False)),
            "command": f"kubectl create job {job_name} --from=cronjob/{name} -n {namespace}",
        }
        if not self.config.actions_enabled:
            return {
                "executed": False,
                "reason": "actions are disabled (actions.enabled = false in config)",
                "plan": plan,
            }
        if confirm is not True:
            return {
                "executed": False,
                "reason": "dry run: show this plan to the user; call again with confirm=true "
                "only after they approve",
                "plan": plan,
            }

        out = self.k3s.kubectl(
            "create", "job", job_name, f"--from=cronjob/{name}", "-n", namespace, "-o", "name",
            kubeconfig=self.config.actions_kubeconfig,
        )
        return {
            "executed": True,
            "created": out.strip(),
            "plan": plan,
            "next": "use k3s_jobs and job_logs to follow the new Job",
        }

    @staticmethod
    def _parse(cronjob: str) -> tuple[str, str]:
        if not isinstance(cronjob, str) or cronjob.count("/") != 1:
            raise ToolDenied("cronjob must be 'namespace/name', e.g. 'pipeline/nightly-run'")
        namespace, name = cronjob.split("/")
        for part in (namespace, name):
            if not NAME_RE.match(part):
                raise ToolDenied(f"invalid name: {part!r}")
        return namespace, name

    def _job_name(self, cronjob: str) -> str:
        suffix = "-manual-" + self.clock().strftime("%Y%m%d%H%M%S")
        return cronjob[: MAX_NAME - len(suffix)].rstrip("-.") + suffix
