"""On-call alerting for Polaris DAGs: a failed task opens a GitHub issue.

Runs as the task's on_failure_callback, so only after the last retry fails.
The issue is the incident ticket: what failed, for which business day, the
tail of the log, and where to look next. One open issue per (DAG, task): while
it's open, the same task failing on later days comments on it instead of
opening a new issue every night.
"""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

REPO = "emudamah0906/polaris-claims-lakehouse"
LOG_LINES = 40


def open_incident(context) -> None:
    ti = context["task_instance"]
    ds = context["ds"]
    key = f"{ti.dag_id}: {ti.task_id} failed"
    title = f"[incident] {key} (first seen {ds})"
    log_tail = _log_tail(ti)
    body = (
        f"**Pipeline:** `{ti.dag_id}`  \n"
        f"**Business day:** `{ds}`  \n"
        f"**Task:** `{ti.task_id}` (attempt {ti.try_number} of {ti.max_tries + 1})  \n"
        f"**Airflow:** http://localhost:8080/dags/{ti.dag_id}/grid?dag_run_id={ti.run_id}&task_id={ti.task_id}\n\n"
        f"### Last {LOG_LINES} log lines\n```\n{log_tail}\n```\n\n"
        "### On-call checklist\n"
        "- [ ] Triage: what failed and why (log, COPY_HISTORY, ADF Monitor, dbt output)\n"
        "- [ ] Impact: which tables or marts are stale or wrong, for which days\n"
        "- [ ] Fix on a branch, PR that closes this issue\n"
        "- [ ] Rerun the failed day and confirm the numbers\n"
        "- [ ] RCA comment: root cause, fix, how we stop it happening again\n"
    )
    existing = _gh(["issue", "list", "--repo", REPO, "--state", "open", "--search", f'"{key}" in:title',
                    "--json", "number"])
    numbers = [i["number"] for i in json.loads(existing or "[]")]
    if numbers:
        _gh(["issue", "comment", str(numbers[0]), "--repo", REPO,
             "--body", f"Failed again on business day `{ds}`.\n\n{body}"])
    else:
        _gh(["issue", "create", "--repo", REPO, "--title", title, "--body", body,
             "--label", "incident", "--label", "sev2", "--label", "on-call"])
    # Also keep a local trail, in case GitHub is unreachable
    with open(Path(__file__).resolve().parents[2] / "alerts.log", "a") as f:
        f.write(f"{ds}  {key}\n")


def _log_tail(ti) -> str:
    from airflow.configuration import conf

    folder = (Path(conf.get("logging", "base_log_folder")) / f"dag_id={ti.dag_id}"
              / f"run_id={ti.run_id}" / f"task_id={ti.task_id}")
    attempts = sorted(folder.glob("attempt=*.log"))
    if not attempts:
        return f"(no log found under {folder})"
    return "\n".join(attempts[-1].read_text(errors="replace").splitlines()[-LOG_LINES:])


def _gh(args: list[str]) -> str:
    return subprocess.run(["gh", *args], capture_output=True, text=True, check=False).stdout
