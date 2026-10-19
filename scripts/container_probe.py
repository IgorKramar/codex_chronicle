"""Compose acceptance without exposing public ports or starting Caddy."""

import hashlib
import json
import os
import secrets
import subprocess
import tempfile
from pathlib import Path


def main():
    with tempfile.TemporaryDirectory(prefix="chronicle-compose-") as tmp:
        root = Path(tmp)
        root.chmod(0o755)  # synthetic secrets only; readable by image UID during test
        (root / "postgres_password").write_text(secrets.token_urlsafe(32), encoding="utf-8")
        (root / "notion_token").write_text("", encoding="utf-8")
        grants = [
            {
                "sha256": hashlib.sha256(token.encode()).hexdigest(),
                "scopes": [scope],
                "computer_id": "smoke-machine" if scope == "write" else None,
                "projects": ["smoke-project"],
            }
            for scope, token in [
                ("read", "smoke-read-only-test"),
                ("write", "smoke-write-only-test"),
            ]
        ]
        (root / "auth.json").write_text(json.dumps(grants), encoding="utf-8")
        for path in root.iterdir():
            path.chmod(0o644)  # disposable test credentials, not production file permissions
        env = {
            **os.environ,
            "CHRONICLE_SECRETS_DIR": str(root),
            "CHRONICLE_DOMAIN": "unused.example.test",
            "COMPOSE_PROJECT_NAME": "chronicle-acceptance",
        }
        compose = ["docker", "compose", "-f", "deploy/compose.yaml"]

        def run(args, **kwargs):
            from chronicle.privacy import redact

            result = subprocess.run(args, env=env, capture_output=True, check=False, **kwargs)
            if result.returncode:
                raise RuntimeError(redact(result.stderr.decode(errors="replace")[-2000:]))
            return result

        from chronicle import __version__

        image = "codex-chronicle:" + __version__
        run(["docker", "tag", image, "chronicle-acceptance-collector"])
        try:
            run(compose + ["config", "--quiet"])
            run(compose + ["up", "-d", "--no-build", "--wait", "postgres", "collector"])
            code = """
import json, time, urllib.request, urllib.error
from chronicle.events import normalize
opener=urllib.request.build_opener(urllib.request.ProxyHandler({}))
for i in range(100):
 try:
  assert json.load(opener.open('http://127.0.0.1:8787/healthz'))['status']=='ok'
  break
 except OSError:
  time.sleep(.1)
else: raise AssertionError('collector did not start')
e=normalize({'hook_event_name':'SessionStart','session_id':'smoke-session'},{'computer_id':'smoke-machine'})
e.update(project_id='smoke-project',worktree_id='smoke-worktree',project={'name':'Synthetic Compose Probe','remote':''})
for i in range(2):
 req=urllib.request.Request('http://127.0.0.1:8787/v1/events',data=json.dumps({'events':[e]}).encode(),headers={'Content-Type':'application/json','Authorization':'Bearer smoke-write-only-test'})
 assert json.load(opener.open(req))['accepted']==[e['event_id']]
req=urllib.request.Request('http://127.0.0.1:8787/v1/projects/smoke-project/state',headers={'Authorization':'Bearer smoke-read-only-test'})
state=json.load(opener.open(req))
assert state['event_count']==1
req=urllib.request.Request('http://127.0.0.1:8787/v1/capabilities',headers={'Authorization':'Bearer smoke-read-only-test'})
assert json.load(opener.open(req))['notion_required'] is False
req=urllib.request.Request('http://127.0.0.1:8787/v1/memory/projects/smoke-project/state',headers={'Authorization':'Bearer smoke-read-only-test'})
assert json.load(opener.open(req))['data']['project_id']=='smoke-project'
print(json.dumps({'container_ingestion':'passed','deduplication':'passed','read_api':'passed','fip_read_api':'passed','events':1}))
"""
            result = run(compose + ["exec", "-T", "collector", "python", "-"], input=code.encode())
            evidence = json.loads(result.stdout)
            run(["sh", "scripts/backup.sh", str(root / "backup.dump")])
            assert (root / "backup.dump").stat().st_size > 0
            assert (root / "backup.dump.publisher.tar").stat().st_size > 0
            evidence.update(
                compose_config="passed",
                compose_backup="passed",
                public_ports_opened=False,
                caddy_started=False,
                image=image,
            )
            Path(
                os.environ.get("CHRONICLE_PROBE_EVIDENCE", "evidence/container-probe.json")
            ).write_text(json.dumps(evidence, indent=2) + "\n", encoding="utf-8")
            print(json.dumps(evidence))
        except Exception as exc:
            from chronicle.privacy import redact

            logs = run(compose + ["logs", "--no-color", "--tail", "45", "collector"])
            raise RuntimeError(redact(logs.stdout.decode(errors="replace"))) from exc
        finally:
            run(compose + ["down", "--volumes", "--remove-orphans"])


if __name__ == "__main__":
    main()
