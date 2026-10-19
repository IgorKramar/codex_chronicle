import argparse
import datetime as dt
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

from . import __version__
from .agent import Agent
from .config import home, initialize, load, save
from .events import validate_event
from .memory import record
from .projects import discover
from .state import build_state, period_summary, render_state


def output(value):
    print(json.dumps(value, ensure_ascii=False, indent=2))


def parser():
    p = argparse.ArgumentParser(prog="chronicle")
    p.add_argument("--version", action="version", version=__version__)
    s = p.add_subparsers(dest="command", required=True)
    s.add_parser("init")
    x = s.add_parser("install")
    x.add_argument("--prepare-only", action="store_true")
    s.add_parser("uninstall")
    s.add_parser("doctor")
    s.add_parser("status")
    x = s.add_parser("projects")
    x.add_argument("--discover", metavar="DIRECTORY")
    x.add_argument("--bind", metavar="DIRECTORY")
    x.add_argument("--project")
    x.add_argument("--policy", choices=["local", "export", "exclude"])
    x = s.add_parser("sync")
    x.add_argument("--force", action="store_true")
    x = s.add_parser("agent")
    x.add_argument("--once", action="store_true")
    x = s.add_parser("report")
    x.add_argument("--project")
    x.add_argument("--json", action="store_true")
    x.add_argument("--date")
    x.add_argument("--weekly", action="store_true")
    s.add_parser("pause")
    s.add_parser("resume")
    x = s.add_parser("backfill")
    x.add_argument("file", type=Path)
    x.add_argument("--consent", action="store_true")
    x = s.add_parser("memory")
    x.add_argument("--project", required=True)
    x.add_argument("--session", required=True)
    x.add_argument("--agent", default="root")
    x.add_argument("--turn")
    x.add_argument("--file", type=Path, required=True)
    x = s.add_parser("export")
    x.add_argument("--project", required=True)
    x = s.add_parser("purge")
    x.add_argument("--project", required=True)
    x.add_argument("--include-pending", action="store_true")
    x.add_argument("--notion", action="store_true")
    x = s.add_parser("notion")
    x.add_argument("--parent")
    x.add_argument("--root", help="Reuse an existing Observatory page, without creating a root")
    x.add_argument(
        "--check",
        action="store_true",
        help="Check dedicated integration read access without writes",
    )
    x.add_argument("--publish", action="store_true")
    x = s.add_parser("config")
    x.add_argument("--collector-url")
    x.add_argument("--mode", choices=["Minimal", "Standard", "Verbose"])
    x = s.add_parser("serve")
    x.add_argument("--host", default="127.0.0.1")
    x.add_argument("--port", type=int, default=8787)
    s.add_parser("hook")
    s.add_parser("mcp")
    x = s.add_parser("fip-sync")
    x.add_argument("--force", action="store_true")
    x.add_argument("--retry-blocked", action="store_true")
    return p


def main(argv=None):
    a = parser().parse_args(argv)
    if a.command == "mcp":
        from .mcp_server import main as mcp_main

        mcp_main()
        return 0
    if a.command == "fip-sync":
        from .fip_client import FipClient

        client = FipClient(
            os.environ["CHRONICLE_API_URL"],
            os.environ["CHRONICLE_API_TOKEN"],
            os.environ.get("CHRONICLE_FIP_OUTBOX"),
            os.environ.get("CHRONICLE_CLIENT_ID"),
            os.environ.get("CHRONICLE_ALLOW_LOOPBACK_HTTP") == "1",
        )
        output(client.flush(a.force, a.retry_blocked))
        return 0
    if a.command == "hook":
        from .hook import main as hook

        return hook()
    try:
        if a.command == "init":
            cfg = initialize()
            output(
                {"home": cfg["home"], "computer_id": cfg["computer_id"], "default_policy": "local"}
            )
            return 0
        cfg = load()
        cmd = a.command
        if cmd == "install":
            from .install import install

            output(install(cfg, a.prepare_only))
            return 0
        if cmd == "uninstall":
            from .install import uninstall

            output(uninstall())
            return 0
        agent = Agent(cfg)
        if cmd in {"pause", "resume"}:
            cfg["paused"] = cmd == "pause"
            save(cfg)
            output({"paused": cfg["paused"]})
        elif cmd == "projects":
            if a.discover:
                discover(a.discover, cfg)
            if a.bind:
                if a.project not in cfg["projects"]:
                    raise ValueError("Сначала зарегистрируйте Project ID")
                cfg["bindings"][str(Path(a.bind).resolve())] = a.project
                save(cfg)
            if a.policy:
                if a.project not in cfg["projects"]:
                    raise ValueError("Укажите зарегистрированный --project")
                cfg["projects"][a.project]["policy"] = a.policy
                if a.policy == "exclude":
                    cfg["exclude"] += [
                        path
                        for path, pid in cfg["bindings"].items()
                        if pid == a.project and path not in cfg["exclude"]
                    ]
                else:
                    cfg["exclude"] = [
                        path for path in cfg["exclude"] if cfg["bindings"].get(path) != a.project
                    ]
                save(cfg)
            output({"projects": cfg["projects"], "bindings": cfg["bindings"]})
        elif cmd == "status":
            output(
                {
                    **agent.store.stats(),
                    "paused": cfg["paused"],
                    "mode": cfg["mode"],
                    "spool": len(list((home() / "spool").glob("*.json"))),
                    "connection": agent.store.get_meta("connection"),
                    "last_error": agent.store.get_meta("last_error"),
                }
            )
        elif cmd == "doctor":
            version = "unavailable"
            if shutil.which("codex"):
                version = subprocess.run(
                    ["codex", "--version"], capture_output=True, text=True, timeout=5
                ).stdout.strip()
            output(
                {
                    "python": sys.version.split()[0],
                    "codex": version,
                    "config_readable": True,
                    "local_store": agent.store.stats(),
                    "hook_error": (home() / "hook-error.json").exists(),
                    "write_token_configured": bool(os.environ.get("CHRONICLE_WRITE_TOKEN")),
                    "notion_token_configured": bool(os.environ.get("NOTION_TOKEN")),
                    "hooks_trust": "Проверьте доверие в Codex; установка не даёт доверия автоматически",
                    "worker_health": json.loads((home() / "agent-health.json").read_text())
                    if (home() / "agent-health.json").exists()
                    else None,
                }
            )
        elif cmd == "agent":
            agent.run(a.once)
        elif cmd == "sync":
            agent.drain()
            total = 0
            while True:
                n = agent.sync(a.force)
                total += n
                if not n:
                    break
            output({"acknowledged": total, **agent.store.stats()})
        elif cmd == "report":
            events = agent.store.events(a.project)
            if a.date or a.weekly:
                output(
                    period_summary(
                        events, a.date or dt.date.today().isoformat(), 7 if a.weekly else 1
                    )
                )
            elif a.project:
                state = build_state(events, cfg["stale_seconds"])
                output(state) if a.json else print(render_state(state))
            else:
                output(
                    {
                        pid: build_state(agent.store.events(pid), cfg["stale_seconds"])
                        for pid in cfg["projects"]
                    }
                )
        elif cmd == "memory":
            output(
                {
                    "event_id": record(
                        agent.store,
                        cfg,
                        a.project,
                        a.session,
                        json.loads(a.file.read_text(encoding="utf-8")),
                        a.agent,
                        a.turn,
                    )
                }
            )
        elif cmd == "backfill":
            if not a.consent:
                raise ValueError(
                    "Backfill требует --consent; поддерживается только Chronicle JSONL schema_version=1"
                )
            events = [
                validate_event(json.loads(line))
                for line in a.file.read_text(encoding="utf-8").splitlines()
                if line.strip()
            ]
            if any(
                e["computer_id"] != cfg["computer_id"] or e["project_id"] not in cfg["projects"]
                for e in events
            ):
                raise ValueError(
                    "Импортируйте только события этой машины и зарегистрированных проектов"
                )
            output({"accepted": len(agent.store.append(events))})
        elif cmd == "export":
            for e in agent.store.events(a.project):
                print(
                    json.dumps(
                        {k: v for k, v in e.items() if k not in {"global_sequence", "received_at"}},
                        ensure_ascii=False,
                    )
                )
        elif cmd == "purge":
            agent.store.purge(project_id=a.project, include_pending=a.include_pending)
            # Remove pre-drain envelopes for the project's registered directories too.
            for path in (home() / "spool").glob("*.json"):
                envelope = json.loads(path.read_text())
                if cfg["bindings"].get(envelope["cwd"]) == a.project:
                    path.unlink()
            if a.notion:
                from .notion import purge_project

                purge_project(agent.store, cfg, a.project)
            output({"purged": a.project})
        elif cmd == "config":
            if a.collector_url:
                from .transport import require_https

                require_https(a.collector_url)
                cfg["collector_url"] = a.collector_url
            if a.mode:
                cfg["mode"] = a.mode
            save(cfg)
            output({"saved": True})
        elif cmd == "notion":
            if a.root:
                cfg["notion_parent"] = a.root
                cfg["notion_existing_root"] = True
                save(cfg)
            if a.parent:
                cfg["notion_existing_root"] = False
                cfg["notion_parent"] = a.parent
                save(cfg)
            if a.check:
                from .notion import Publisher

                publisher = Publisher(agent.store, cfg)
                page = publisher.call("GET", "/pages/" + cfg["notion_parent"])
                output(
                    {
                        "read_access": True,
                        "page_id": page["id"],
                        "write_access": "not tested",
                        "existing_root": cfg.get("notion_existing_root", False),
                    }
                )
            if a.publish:
                from .notion import publish_store

                output(publish_store(agent.store, cfg))
        elif cmd == "serve":
            import uvicorn

            from .collector import create_app

            uvicorn.run(create_app(), host=a.host, port=a.port, log_config=None)
        return 0
    except Exception as exc:
        # Exceptions from remote libraries may contain credentials. Emit only type.
        print(
            "Chronicle: " + type(exc).__name__ + ". Проверьте параметры и chronicle doctor.",
            file=sys.stderr,
        )
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
