import json
import uuid

from .events import MEMORY_FIELDS, now
from .privacy import redact


def validate_report(report):
    if not isinstance(report, dict) or set(report) != set(MEMORY_FIELDS):
        raise ValueError("Report must contain exactly: " + ", ".join(MEMORY_FIELDS))
    if not isinstance(report["Task"], str) or not isinstance(report["Confidence"], str):
        raise ValueError("Task and Confidence must be strings")
    for field in set(MEMORY_FIELDS) - {"Task", "Confidence"}:
        if not isinstance(report[field], list):
            raise ValueError(field + " must be an array")
    for d in report["Decisions"]:
        if not isinstance(d, dict) or not {
            "id",
            "status",
            "problem",
            "alternatives",
            "choice",
            "rationale",
            "consequences",
        } <= set(d):
            raise ValueError("Decision missing ADR fields")
        if d["status"] not in {"Proposed", "Accepted", "Superseded", "Rejected"}:
            raise ValueError("Invalid decision status")
    for p in report["Problems"]:
        if not isinstance(p, dict) or not {"id", "type", "title", "status"} <= set(p):
            raise ValueError("Problem missing fields")
        if p["type"] not in {
            "Bug",
            "Limitation",
            "Discovery",
            "Improvement",
            "Research",
            "Technical Debt",
        }:
            raise ValueError("Invalid problem type")
        if p["status"] not in {"Open", "Resolved"}:
            raise ValueError("Invalid problem status")
    if len(json.dumps(report).encode()) > 64000:
        raise ValueError("Report too large")
    return redact(report)


def record(store, cfg, project_id, session_id, report, agent_id="root", turn_id=None):
    report = validate_report(report)
    project = cfg["projects"][project_id]
    event = {
        "schema_version": 1,
        "event_id": str(uuid.uuid4()),
        "kind": "MemoryReport",
        "computer_id": cfg["computer_id"],
        "session_id": session_id,
        "agent_id": agent_id,
        "turn_id": turn_id,
        "occurred_at": now(),
        "evidence": "agent_reported",
        "project_id": project_id,
        "worktree_id": "memory",
        "project": {"name": project["name"], "remote": project["remote"]},
        "payload": {"report": report},
    }
    store.append([event])
    return event["event_id"]
