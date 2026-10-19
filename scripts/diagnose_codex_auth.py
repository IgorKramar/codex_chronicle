"""Reproducible official CLI probe; stores only allowlisted diagnostic facts."""

import json
import re
import subprocess
import tempfile
from pathlib import Path


def main():
    status = subprocess.run(["codex", "login", "status"], capture_output=True, text=True)
    result = {
        "login_status_exit_code": status.returncode,
        "login_reports_chatgpt": "ChatGPT" in status.stderr + status.stdout,
    }
    with tempfile.TemporaryDirectory(prefix="chronicle-auth-probe-") as cwd:
        try:
            run = subprocess.run(
                [
                    "codex",
                    "exec",
                    "--json",
                    "--ephemeral",
                    "--sandbox",
                    "read-only",
                    "--skip-git-repo-check",
                    "-C",
                    cwd,
                    "Return OK. Do not use tools, subagents or network.",
                ],
                capture_output=True,
                text=True,
                timeout=90,
            )
            text = run.stdout + run.stderr
            result.update(
                exit_code=run.returncode,
                http_statuses=sorted(set(re.findall(r"\b(?:401|403|451)\b", text))),
                unauthorized="unauthorized" in text.lower(),
                expired="expired" in text.lower(),
                refresh_token_reused="refresh_token_reused" in text,
                workspace_attestation_missing="no_biscuit_no_service" in text,
                hook_trust_required=bool(re.search(r"hook.{0,80}(trust|approv)", text, re.I)),
                event_types=sorted(
                    {
                        json.loads(line).get("type", "unknown")
                        for line in run.stdout.splitlines()
                        if line.startswith("{")
                    }
                ),
            )
        except subprocess.TimeoutExpired:
            result.update(error="timeout", seconds=90)
    Path("evidence/codex-auth-diagnostic.json").write_text(
        json.dumps(result, indent=2) + "\n", encoding="utf-8"
    )
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
