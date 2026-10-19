"""Official Notion REST API publisher; no LLM, no blind create retries."""

import datetime as dt
import os
import time
from collections import defaultdict
from contextlib import contextmanager
from pathlib import Path
from typing import Any

from .config import ProcessLock
from .events import fingerprint
from .privacy import redact
from .state import (
    build_state,
    json_text,
    period_summary,
    render_period_summary,
    render_state,
    session_key,
)
from .transport import TransportError, request, require_https

COLLECTIONS = {
    "Projects": {
        "Project ID": "rich_text",
        "Description": "rich_text",
        "Git remote": "rich_text",
        "Directories": "rich_text",
        "Status": "rich_text",
        "Last Activity": "date",
        "Active Agents": "number",
        "Last Commit": "rich_text",
        "Current State": "url",
        "Errors": "number",
        "Open Tasks": "rich_text",
    },
    "Sessions": {
        "Session ID": "rich_text",
        "Project ID": "rich_text",
        "Computer ID": "rich_text",
        "Agent ID": "rich_text",
        "Parent Session": "rich_text",
        "Model": "rich_text",
        "Started": "date",
        "Ended": "date",
        "Status": "select",
        "Task": "rich_text",
        "Result": "rich_text",
        "Changed Files": "rich_text",
        "Git Commit": "rich_text",
        "Tests": "rich_text",
        "Errors": "rich_text",
        "Journal": "url",
    },
    "Development Journal": {
        "Project ID": "rich_text",
        "Source ID": "rich_text",
        "Evidence": "select",
        "Date": "date",
        "Session": "rich_text",
        "Count": "number",
    },
    "Architectural Decisions": {
        "Project ID": "rich_text",
        "Decision ID": "rich_text",
        "Status": "select",
        "Problem": "rich_text",
        "Alternatives": "rich_text",
        "Choice": "rich_text",
        "Rationale": "rich_text",
        "Consequences": "rich_text",
        "Components": "rich_text",
        "Source ID": "rich_text",
        "Date": "date",
        "Supersedes": "rich_text",
    },
    "Issues & Discoveries": {
        "Project ID": "rich_text",
        "Issue ID": "rich_text",
        "Type": "select",
        "Status": "select",
        "Source ID": "rich_text",
        "Decisions": "rich_text",
    },
    "Daily Reports": {"Period": "date", "Events": "number", "Previous Events": "number"},
    "Weekly Reports": {"Period": "date", "Events": "number", "Previous Events": "number"},
}


class UncertainWrite(RuntimeError):
    pass


def text(value):
    content = json_text(redact(value))
    return [
        {"type": "text", "text": {"content": content[i : i + 1900]}}
        for i in range(0, min(len(content), 9500), 1900)
    ] or []


def block(content):
    return {"object": "block", "type": "paragraph", "paragraph": {"rich_text": text(content)}}


def prop(kind, value):
    if kind in {"title", "rich_text"}:
        return {kind: text(value)}
    if kind == "date":
        return {"date": {"start": value} if value else None}
    if kind == "select":
        return {"select": {"name": str(value)} if value else None}
    return {kind: value}


@contextmanager
def publisher_lock(store, cfg):
    if store.postgres:
        with store.connect() as c:
            locked = c.execute("SELECT pg_try_advisory_lock(94732041) AS locked").fetchone()[
                "locked"
            ]
            if not locked:
                raise RuntimeError("Publisher already active")
            try:
                yield
            finally:
                c.execute("SELECT pg_advisory_unlock(94732041)")
    else:
        with ProcessLock(Path(cfg["home"]) / "publisher.lock"):
            yield


class Publisher:
    def __init__(self, store, cfg, token=None, base_url="https://api.notion.com/v1", interval=0.36):
        require_https(base_url, cfg.get("allow_loopback_http", False))
        self.store, self.cfg = store, cfg
        self.base = base_url.rstrip("/")
        self.token = token or os.environ.get("NOTION_TOKEN")
        token_file = os.environ.get("NOTION_TOKEN_FILE") or cfg.get("notion_token_file")
        if not self.token and token_file:
            secret_path = Path(token_file)
            if os.name != "nt" and secret_path.stat().st_mode & 0o077:
                raise RuntimeError("Notion token file must be private (chmod 600)")
            self.token = secret_path.read_text(encoding="utf-8").strip()
        if not self.token:
            raise RuntimeError("NOTION_TOKEN required; configure locally, never in chat")
        self.interval, self.last = interval, 0.0
        self.sources = store.get_meta("notion:sources", {})

    def call(self, method, path, body=None):
        remaining = self.store.get_meta("notion:retry_at", 0) - time.time()
        if remaining > 0:
            raise TransportError(429, remaining)
        time.sleep(max(0, self.interval - (time.monotonic() - self.last)))
        self.last = time.monotonic()
        try:
            return request(
                method,
                self.base + path,
                body,
                {
                    "Authorization": "Bearer " + str(self.token),
                    "Notion-Version": self.cfg.get("notion_version", "2026-03-11"),
                },
            )
        except TransportError as exc:
            if exc.status in {429, 529}:
                self.store.set_meta("notion:retry_at", time.time() + max(1, exc.retry_after))
            raise

    def pages(self, path, method="GET", body=None):
        cursor = None
        while True:
            query = dict(body or {})
            if cursor:
                query["start_cursor"] = cursor
            if method == "GET":
                import urllib.parse

                url = path + ("?" + urllib.parse.urlencode(query) if query else "")
                result = self.call(method, url)
            else:
                result = self.call(method, path, query)
            yield from result.get("results", [])
            if not result.get("has_more"):
                return
            cursor = result.get("next_cursor")
            if not cursor:
                raise RuntimeError("Invalid Notion pagination")

    def create_once(self, key, finder, path, body):
        # Every attempt reconciles before create, including after lost responses/restarts.
        existing = finder()
        marker = "notion:uncertain:" + key
        if existing:
            self.store.set_meta(marker, False)
            return existing
        if self.store.get_meta(marker, False):
            raise UncertainWrite("Uncertain create requires reconciliation; never blindly recreate")
        self.store.set_meta(marker, True)
        try:
            result = self.call("POST", path, body)
        except TransportError as exc:
            if exc.status in {400, 401, 403, 404, 422, 429}:
                self.store.set_meta(marker, False)
            raise
        self.store.set_meta(marker, False)
        return result

    def ensure_root(self):
        parent = self.cfg["notion_parent"]
        title = "CODEX CHRONICLE — Development Observatory"

        def find():
            matches = [
                b
                for b in self.pages(f"/blocks/{parent}/children")
                if b.get("type") == "child_page" and b["child_page"].get("title") == title
            ]
            if len(matches) > 1:
                raise RuntimeError("Duplicate Chronicle roots; resolve explicitly")
            return matches[0] if matches else None

        if self.cfg.get("notion_existing_root"):
            # Explicit root mode never creates or edits the supplied user's page.
            root = self.call("GET", "/pages/" + parent)
            if root.get("in_trash") or root.get("archived"):
                raise RuntimeError("Configured Notion root is archived")
            actual_title = "".join(
                t.get("plain_text", t.get("text", {}).get("content", ""))
                for prop in root.get("properties", {}).values()
                if prop.get("type") == "title" or "title" in prop
                for t in prop.get("title", [])
            )
            if actual_title != title:
                raise RuntimeError("Configured page is not the Chronicle Observatory root")
        else:
            root = self.create_once(
                "root:" + parent,
                find,
                "/pages",
                {
                    "parent": {"type": "page_id", "page_id": parent},
                    "properties": {"title": prop("title", title)},
                },
            )
        self.root_id = root["id"]
        self.store.set_meta("notion:root", self.root_id)
        for name, fields in COLLECTIONS.items():

            def finder(name=name):
                matches = [
                    b
                    for b in self.pages(f"/blocks/{self.root_id}/children")
                    if b.get("type") == "child_database"
                    and b["child_database"].get("title") == name
                ]
                if len(matches) > 1:
                    raise RuntimeError("Duplicate Chronicle databases")
                return self.call("GET", "/databases/" + matches[0]["id"]) if matches else None

            schema: dict[str, Any] = {
                "Name": {"title": {}},
                "Chronicle Key": {"rich_text": {}},
                "Summary": {"rich_text": {}},
                **{k: {v: {}} for k, v in fields.items()},
            }
            database = self.create_once(
                "database:" + name,
                finder,
                "/databases",
                {
                    "parent": {"type": "page_id", "page_id": self.root_id},
                    "title": text(name),
                    "initial_data_source": {"properties": schema},
                },
            )
            sources = database.get("data_sources", [])
            if not sources:
                database = self.call("GET", "/databases/" + database["id"])
                sources = database.get("data_sources", [])
            if len(sources) != 1:
                raise RuntimeError("Expected a single owned data source")
            self.sources[name] = sources[0]["id"]
            self.store.set_meta("notion:sources", self.sources)

    def lookup(self, source, key):
        result = list(
            self.pages(
                f"/data_sources/{source}/query",
                "POST",
                {
                    "filter": {"property": "Chronicle Key", "rich_text": {"equals": key}},
                    "page_size": 100,
                },
            )
        )
        if len(result) > 1:
            raise RuntimeError("Duplicate Chronicle Key; refusing ambiguous update")
        return result[0] if result else None

    def upsert(self, collection, key, name, content, values):
        source = self.sources[collection]
        safe_content = json_text(redact(content))
        # Bounded readable snapshot. Full evidence stays in Chronicle storage/API.
        chunks = [safe_content[i : i + 1800] for i in range(0, min(len(safe_content), 18000), 1800)]
        chunks += [""] * (10 - len(chunks))
        properties = {
            "Name": prop("title", name),
            "Chronicle Key": prop("rich_text", key),
            "Summary": prop("rich_text", safe_content[:1800]),
        }
        for field, value in values.items():
            properties[field] = prop(COLLECTIONS[collection][field], value)
        digest = fingerprint([properties, chunks])
        mapping_key = "notion:page:" + key
        saved = self.store.get_meta(mapping_key, {})
        if saved.get("digest") == digest and saved.get("id"):
            return saved
        page = self.create_once(
            "page:" + key,
            lambda: self.lookup(source, key),
            "/pages",
            {
                "parent": {"type": "data_source_id", "data_source_id": source},
                "properties": properties,
                "children": [block(x) for x in chunks],
            },
        )
        pid = page["id"]
        self.call("PATCH", "/pages/" + pid, {"properties": properties})
        # Never append after an uncertain write. Fixed 10 blocks are created atomically with page.
        owned = [b for b in self.pages(f"/blocks/{pid}/children") if b.get("type") == "paragraph"]
        if len(owned) != 10:
            raise RuntimeError("Managed snapshot blocks changed; refusing destructive repair")
        for b, chunk in zip(owned, chunks, strict=True):
            current = "".join(
                t.get("plain_text", t.get("text", {}).get("content", ""))
                for t in b.get("paragraph", {}).get("rich_text", [])
            )
            if current != chunk:
                self.call("PATCH", "/blocks/" + b["id"], {"paragraph": {"rich_text": text(chunk)}})
        result = {
            "id": pid,
            "url": page.get("url", "https://www.notion.so/" + pid.replace("-", "")),
            "digest": digest,
            "project_id": values.get("Project ID"),
        }
        self.store.set_meta(mapping_key, result)
        return result

    def publish(self):
        self.ensure_root()
        allowed = {
            pid for pid, p in self.cfg.get("projects", {}).items() if p.get("policy") == "export"
        }
        events = [e for e in self.store.events() if e["project_id"] in allowed]
        # Optional FIP projection. All memory remains in the ledger even if Notion fails.
        fip_rows = []
        with self.store.connect() as c:
            exists = (
                c.execute("SELECT to_regclass('fip_records') AS name").fetchone()["name"]
                if self.store.postgres
                else c.execute(
                    "SELECT name FROM sqlite_master WHERE type='table' AND name='fip_records'"
                ).fetchone()
            )
        if exists:
            from .fip_store import Ledger

            fip_allowed = set(self.cfg.get("fip_notion_projects", []))
            fip_rows = Ledger(self.store).rows(
                list(allowed if "*" in fip_allowed else allowed & fip_allowed)
            )
        fip_contexts = {}
        if fip_rows:
            from .memory_service import MemoryService

            memory = MemoryService(self.store)
            for pid in sorted({r["body"]["project_id"] for r in fip_rows}):
                fip_contexts[pid] = memory.execute(
                    "get_project_state",
                    {"project_id": pid},
                    {"sha256": "0" * 64, "scopes": ["read"], "projects": [pid]},
                )["data"]
        grouped = defaultdict(list)
        for e in events:
            grouped[e["project_id"]].append(e)
        count = 0
        for pid, history in grouped.items():
            state = build_state(history)
            state["updated_at"] = max(e["received_at"] for e in history)
            project = self.cfg["projects"][pid]
            last_commit = next(
                (e["payload"]["commit"] for e in reversed(history) if e["payload"].get("commit")),
                "",
            )
            old = self.store.get_meta("notion:page:project:" + pid, {})
            values = {
                "Project ID": pid,
                "Description": state["latest_report"].get("Task", "Не зафиксировано"),
                "Git remote": project.get("remote", ""),
                "Directories": "Worktree IDs: "
                + ", ".join(sorted({e["worktree_id"] for e in history})),
                "Status": "Running"
                if any(s["status"] == "Running" for s in state["sessions"])
                else "Unknown",
                "Last Activity": state["last_activity"],
                "Active Agents": sum(s["status"] == "Running" for s in state["sessions"]),
                "Last Commit": last_commit,
                "Current State": old.get("url"),
                "Errors": sum(r["exit_code"] != 0 for r in state["tool_results"]),
                "Open Tasks": state["latest_report"].get("Next Steps", []),
            }
            content = render_state(state)
            if pid in fip_contexts:
                content = (
                    "## FIP v1 agent memory\n" + fip_contexts[pid]["llm_summary"] + "\n\n" + content
                )
            current = self.upsert("Projects", "project:" + pid, project["name"], content, values)
            if not values["Current State"]:
                self.call(
                    "PATCH",
                    "/pages/" + current["id"],
                    {"properties": {"Current State": prop("url", current["url"])}},
                )
            for s in state["sessions"]:
                session_events = [e for e in history if session_key(e) == s["key"]]
                payloads = [e["payload"] for e in session_events]
                self.upsert(
                    "Sessions",
                    "session:" + pid + ":" + s["key"],
                    s["session_id"],
                    s,
                    {
                        "Session ID": s["session_id"],
                        "Project ID": pid,
                        "Computer ID": s["computer_id"],
                        "Agent ID": s["agent_id"],
                        "Parent Session": s["session_id"] if s["agent_id"] != "root" else "",
                        "Model": s["model"],
                        "Started": s["started_at"],
                        "Ended": s["ended_at"],
                        "Status": s["status"],
                        "Task": s["task"],
                        "Result": "См. отчёт агента и первичные события; успех не установлен автоматически",
                        "Changed Files": sorted({f for p in payloads for f in p.get("files", [])}),
                        "Git Commit": last_commit,
                        "Tests": [
                            r for r in state["tool_results"] if r["event_id"] in s["event_ids"]
                        ],
                        "Errors": [p for p in payloads if p.get("exit_code", 0) != 0],
                        "Journal": current["url"],
                    },
                )
                # One meaningful aggregate per session and turn, not a row per tool call.
                turns = defaultdict(list)
                for e in session_events:
                    turns[e.get("turn_id") or "session"].append(e)
                for turn, items in turns.items():
                    summary = {
                        "kinds": dict(__import__("collections").Counter(e["kind"] for e in items)),
                        "source_ids": [e["event_id"] for e in items],
                        "completed_runs": [
                            e["payload"] for e in items if "exit_code" in e["payload"]
                        ],
                        "changed_files": sorted(
                            {f for e in items for f in e["payload"].get("files", [])}
                        ),
                        "commits": sorted(
                            {e["payload"]["commit"] for e in items if e["payload"].get("commit")}
                        ),
                        "reports": [
                            e["payload"]["report"] for e in items if e["kind"] == "MemoryReport"
                        ],
                    }
                    self.upsert(
                        "Development Journal",
                        "journal:" + pid + ":" + s["key"] + ":" + turn,
                        "Ход " + turn,
                        summary,
                        {
                            "Project ID": pid,
                            "Source ID": items[-1]["event_id"],
                            "Evidence": "derived",
                            "Date": items[-1]["occurred_at"],
                            "Session": s["key"],
                            "Count": len(items),
                        },
                    )
            for did, revisions in state["decisions"].items():
                for revision in revisions:
                    self.upsert(
                        "Architectural Decisions",
                        "adr:" + pid + ":" + did + ":" + revision["source_event"],
                        did,
                        revision,
                        {
                            "Project ID": pid,
                            "Decision ID": did,
                            "Status": revision["status"],
                            "Problem": revision["problem"],
                            "Alternatives": revision["alternatives"],
                            "Choice": revision["choice"],
                            "Rationale": revision["rationale"],
                            "Consequences": revision["consequences"],
                            "Components": revision.get("components", []),
                            "Source ID": revision["source_event"],
                            "Date": next(
                                e["occurred_at"]
                                for e in history
                                if e["event_id"] == revision["source_event"]
                            ),
                            "Supersedes": revision.get("supersedes", ""),
                        },
                    )
            for iid, revisions in state["issues"].items():
                issue = revisions[-1]
                self.upsert(
                    "Issues & Discoveries",
                    "issue:" + pid + ":" + iid,
                    issue["title"],
                    revisions,
                    {
                        "Project ID": pid,
                        "Issue ID": iid,
                        "Type": issue["type"],
                        "Status": state["issue_states"][iid]["status"],
                        "Source ID": issue["source_event"],
                        "Decisions": issue.get("decision_ids", []),
                    },
                )
            count += 1
        for pid, context in fip_contexts.items():
            project_rows = [r for r in fip_rows if r["body"]["project_id"] == pid]
            if pid not in grouped:
                old = self.store.get_meta("notion:page:project:" + pid, {})
                values = {
                    "Project ID": pid,
                    "Description": context["description"],
                    "Git remote": "",
                    "Directories": "External agent memory (FIP v1)",
                    "Status": context["status"],
                    "Last Activity": max(r["body"]["timestamp"] for r in project_rows),
                    "Active Agents": 0,
                    "Last Commit": "",
                    "Current State": old.get("url"),
                    "Errors": sum(
                        r["body"]["status"] in {"failed", "Failed"} for r in project_rows
                    ),
                    "Open Tasks": context["open_questions"],
                }
                current = self.upsert(
                    "Projects", "project:" + pid, context["name"], context["llm_summary"], values
                )
                if not old.get("url"):
                    self.call(
                        "PATCH",
                        "/pages/" + current["id"],
                        {"properties": {"Current State": prop("url", current["url"])}},
                    )
                count += 1
            self.upsert(
                "Development Journal",
                "fip-journal:" + pid,
                "FIP v1 — " + context["name"],
                context["llm_summary"],
                {
                    "Project ID": pid,
                    "Source ID": project_rows[-1]["body"]["record_id"],
                    "Evidence": "derived",
                    "Date": project_rows[-1]["body"]["timestamp"],
                    "Session": "FIP v1",
                    "Count": len(project_rows),
                },
            )
            for row in project_rows:
                r = row["body"]
                if row["kind"] == "DecisionRecord":
                    self.upsert(
                        "Architectural Decisions",
                        "fip-adr:" + r["record_id"],
                        r["title"],
                        r,
                        {
                            "Project ID": pid,
                            "Decision ID": r["decision_id"],
                            "Status": r["status"],
                            "Problem": r["problem"],
                            "Alternatives": r["alternatives"],
                            "Choice": r["choice"],
                            "Rationale": r["rationale"],
                            "Consequences": r["consequences"],
                            "Components": [r["category"]],
                            "Source ID": r["record_id"],
                            "Date": r["timestamp"],
                            "Supersedes": r["supersedes"] or "",
                        },
                    )
        dates = {
            dt.datetime.fromisoformat(e["occurred_at"]).astimezone(dt.UTC).date() for e in events
        }
        for days, collection, starts in [
            (1, "Daily Reports", dates),
            (7, "Weekly Reports", {d - dt.timedelta(days=d.weekday()) for d in dates}),
        ]:
            for date in sorted(starts):
                summary = period_summary(events, date.isoformat(), days)
                # Avoid generation timestamps causing perpetual writes.
                for state in summary["projects"].values():
                    state.pop("updated_at", None)
                self.upsert(
                    collection,
                    collection + ":" + date.isoformat(),
                    date.isoformat(),
                    render_period_summary(summary),
                    {
                        "Period": date.isoformat(),
                        "Events": summary["event_count"],
                        "Previous Events": summary["previous_event_count"],
                    },
                )
        self.store.set_meta("notion:last_publish", {"projects": count, "at": time.time()})
        return {"projects": count, "root": self.root_id}


def publish_store(store, cfg):
    with publisher_lock(store, cfg):
        return Publisher(store, cfg).publish()


def purge_project(store, cfg, project_id):
    with publisher_lock(store, cfg):
        publisher = Publisher(store, cfg)
        for collection, source in publisher.sources.items():
            if "Project ID" not in COLLECTIONS[collection]:
                continue
            pages = list(
                publisher.pages(
                    f"/data_sources/{source}/query",
                    "POST",
                    {"filter": {"property": "Project ID", "rich_text": {"equals": project_id}}},
                )
            )
            for page in pages:
                publisher.call("PATCH", "/pages/" + page["id"], {"in_trash": True})
        # Daily/weekly reports can contain multiple projects: archive, invalidate cache, rebuild.
        for collection in ("Daily Reports", "Weekly Reports"):
            source = publisher.sources.get(collection)
            if source:
                for page in publisher.pages(f"/data_sources/{source}/query", "POST", {}):
                    publisher.call("PATCH", "/pages/" + page["id"], {"in_trash": True})
        with store.connect() as c:
            c.execute("DELETE FROM meta WHERE key LIKE 'notion:page:%'")
