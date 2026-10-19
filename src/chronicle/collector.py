import asyncio
import datetime as dt
import hashlib
import hmac
import json
import os
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from pydantic import BaseModel, ConfigDict, Field

from .events import now, validate_event
from .state import build_state, period_summary, session_key
from .store import ConflictError, Store


class EventBatch(BaseModel):
    model_config = ConfigDict(extra="forbid")
    events: list[dict] = Field(min_length=1, max_length=100)


def create_app(location=None, grants=None, publisher_cfg=None):
    store = Store(location or os.environ.get("CHRONICLE_DATABASE", "collector.db"))
    if grants is None:
        auth_file = os.environ.get("CHRONICLE_AUTH_FILE")
        if not auth_file:
            raise RuntimeError("CHRONICLE_AUTH_FILE is required; no default credentials")
        grants = json.loads(Path(auth_file).read_text(encoding="utf-8"))
    if not grants or any(len(g.get("sha256", "")) != 64 for g in grants):
        raise RuntimeError("Explicit hashed authentication grants required")
    if not publisher_cfg and os.environ.get("NOTION_PARENT"):
        publisher_cfg = {
            "notion_parent": os.environ["NOTION_PARENT"],
            "home": os.environ.get("CHRONICLE_STATE_DIR", "/data"),
            "publish_seconds": int(os.environ.get("CHRONICLE_PUBLISH_SECONDS", "600")),
        }

    @asynccontextmanager
    async def lifespan(app):
        stop = asyncio.Event()

        async def publish_loop():
            while not stop.is_set():
                try:
                    from .notion import publish_store

                    cfg = dict(publisher_cfg)
                    cfg["projects"] = {
                        e["project_id"]: {**e["project"], "policy": "export"}
                        for e in store.events()
                    }
                    await asyncio.to_thread(publish_store, store, cfg)
                except Exception as exc:
                    store.set_meta("publisher_error", {"code": type(exc).__name__, "at": now()})
                try:
                    await asyncio.wait_for(
                        stop.wait(), timeout=publisher_cfg.get("publish_seconds", 600)
                    )
                except TimeoutError:
                    pass

        task = asyncio.create_task(publish_loop()) if publisher_cfg else None
        yield
        stop.set()
        if task:
            await task

    app = FastAPI(
        title="Codex Chronicle read and ingestion API",
        version="0.1.0",
        lifespan=lifespan,
        docs_url=None,
        redoc_url=None,
    )
    app.state.store = store
    bearer = HTTPBearer(auto_error=False)

    def auth(c: HTTPAuthorizationCredentials = Depends(bearer)):
        digest = hashlib.sha256(c.credentials.encode()).hexdigest() if c else ""
        for grant in grants:
            if hmac.compare_digest(grant["sha256"], digest):
                return grant
        raise HTTPException(401, "Authentication required", headers={"WWW-Authenticate": "Bearer"})

    def reader(g=Depends(auth)):
        if "read" not in g.get("scopes", []):
            raise HTTPException(403, "Read scope required")
        return g

    def visible(grant, project_id):
        return project_id in grant.get("projects", []) or "*" in grant.get("projects", [])

    def events_for(grant, project_id=None):
        if project_id and not visible(grant, project_id):
            raise HTTPException(404, "Project not found")
        return [e for e in store.events(project_id) if visible(grant, e["project_id"])]

    @app.get("/healthz", include_in_schema=False)
    def health():
        return {"status": "ok"}

    @app.post("/v1/events", tags=["ingestion"])
    async def ingest(request: Request, grant=Depends(auth)):
        if "write" not in grant.get("scopes", []):
            raise HTTPException(403, "Write scope required")
        raw = bytearray()
        async for chunk in request.stream():
            raw.extend(chunk)
            if len(raw) > 1_000_000:
                raise HTTPException(413, "Batch too large")
        try:
            batch = EventBatch.model_validate_json(raw)
            events = [validate_event(e) for e in batch.events]
            for e in events:
                if e["computer_id"] != grant.get("computer_id") or not visible(
                    grant, e["project_id"]
                ):
                    raise HTTPException(403, "Computer or project scope mismatch")
            # Sync database I/O runs outside the ASGI event loop.
            ids = await asyncio.to_thread(store.append, events, True)
            return {"accepted": ids}
        except ConflictError:
            raise HTTPException(409, "Conflicting Event ID") from None
        except (ValueError, KeyError, TypeError):
            raise HTTPException(422, "Invalid safe event schema") from None

    # Explicit OpenAPI request model while retaining streamed request-size enforcement.
    app.routes[-1].openapi_extra = {
        "requestBody": {
            "required": True,
            "content": {"application/json": {"schema": EventBatch.model_json_schema()}},
        }
    }

    @app.get("/v1/projects", operation_id="list_projects", tags=["memory"])
    def list_projects(grant=Depends(reader)):
        result = {}
        for e in events_for(grant):
            result[e["project_id"]] = {"project_id": e["project_id"], **e["project"]}
        return list(result.values())

    @app.get("/v1/projects/{project_id}/state", operation_id="get_project_state", tags=["memory"])
    def get_project_state(project_id: str, grant=Depends(reader)):
        events = events_for(grant, project_id)
        if not events:
            raise HTTPException(404, "Project not found")
        return build_state(events)

    @app.get("/v1/sessions/active", operation_id="list_active_sessions", tags=["memory"])
    def list_active_sessions(grant=Depends(reader)):
        return [s for s in build_state(events_for(grant))["sessions"] if s["status"] == "Running"]

    @app.get("/v1/activity", operation_id="get_recent_activity", tags=["memory"])
    def get_recent_activity(after: int = 0, limit: int = 100, grant=Depends(reader)):
        if after < 0 or not 1 <= limit <= 1000:
            raise HTTPException(422, "Invalid pagination")
        items = [e for e in events_for(grant) if e["global_sequence"] > after][:limit]
        return {"events": items, "next_after": items[-1]["global_sequence"] if items else after}

    @app.get("/v1/projects/{project_id}/decisions", operation_id="get_decisions", tags=["memory"])
    def get_decisions(project_id: str, grant=Depends(reader)):
        return build_state(events_for(grant, project_id))["decisions"]

    @app.get("/v1/projects/{project_id}/issues", operation_id="get_open_issues", tags=["memory"])
    def get_open_issues(project_id: str, grant=Depends(reader)):
        state = build_state(events_for(grant, project_id))
        return {
            k: v for k, v in state["issues"].items() if state["issue_states"][k]["status"] == "Open"
        }

    @app.get("/v1/summaries/daily", operation_id="get_daily_summary", tags=["memory"])
    def get_daily_summary(date: str, grant=Depends(reader)):
        try:
            dt.date.fromisoformat(date)
        except ValueError:
            raise HTTPException(422, "Use YYYY-MM-DD") from None
        return period_summary(events_for(grant), date)

    @app.get("/v1/events/{event_id}", operation_id="get_evidence", tags=["evidence"])
    def get_evidence(event_id: str, grant=Depends(reader)):
        for e in events_for(grant):
            if e["event_id"] == event_id:
                return e
        raise HTTPException(404, "Event not found")

    @app.get("/v1/computers", tags=["diagnostics"])
    def computers(grant=Depends(reader)):
        latest = {}
        for e in events_for(grant):
            latest[e["computer_id"]] = {
                "computer_id": e["computer_id"],
                "last_received": e["received_at"],
                "last_session": session_key(e),
            }
        return list(latest.values())

    @app.get("/v1/metrics", tags=["diagnostics"])
    def metrics(grant=Depends(reader)):
        events = events_for(grant)
        return {
            "events": len(events),
            "projects": len({e["project_id"] for e in events}),
            "sessions": len({session_key(e) for e in events}),
        }

    return app
