import datetime as dt
import hashlib
import json
import re
import shlex
import uuid

from .privacy import redact

HOOKS = [
    "SessionStart",
    "UserPromptSubmit",
    "PreToolUse",
    "PostToolUse",
    "SubagentStart",
    "SubagentStop",
    "PreCompact",
    "PostCompact",
    "Stop",
    "Interrupt",
    "SessionEnd",
]
MEMORY_FIELDS = [
    "Task",
    "Actions",
    "Changes",
    "Decisions",
    "Evidence",
    "Problems",
    "Next Steps",
    "Confidence",
]


def now():
    return dt.datetime.now(dt.UTC).isoformat()


def identifier(value):
    value = str(value)
    if not re.fullmatch(r"[A-Za-z0-9_.:@/-]{1,256}", value):
        raise ValueError("Invalid identifier")
    return value


def test_runner(raw):
    args = raw.get("tool_input")
    command = args.get("command") if isinstance(args, dict) else None
    if not isinstance(command, str) or re.search(r"[;&|`$<>\n]", command):
        return None
    try:
        words = shlex.split(command)
    except ValueError:
        return None
    if not words:
        return None
    exe = words[0].replace("\\", "/").rsplit("/", 1)[-1]
    if exe in {"pytest", "pytest.exe"}:
        return "pytest"
    if exe in {"python", "python3", "python.exe"} and words[1:3] == ["-m", "pytest"]:
        return "pytest"
    if exe in {"python", "python3", "python.exe"} and words[1:3] == ["-m", "unittest"]:
        return "unittest"
    if exe in {"npm", "npm.cmd"} and words[1:2] == ["test"]:
        return "npm test"
    if exe == "cargo" and words[1:2] == ["test"]:
        return "cargo test"
    if exe == "go" and words[1:2] == ["test"]:
        return "go test"
    return None


def normalize(raw, cfg):
    if not isinstance(raw, dict) or raw.get("hook_event_name") not in HOOKS:
        raise ValueError("Unsupported hook event")
    kind = raw["hook_event_name"]
    session = identifier(raw["session_id"])
    turn = identifier(raw["turn_id"]) if raw.get("turn_id") else None
    agent = identifier(raw.get("agent_id") or "root")
    payload = {}
    # Never retain prompts, arbitrary tool input/output, transcript paths or assistant text.
    for key in ("tool_name", "tool_use_id", "model", "source", "trigger", "reason", "agent_type"):
        if isinstance(raw.get(key), str):
            payload[key] = redact(raw[key][:256])
    if kind == "PostToolUse":
        response = raw.get("tool_response")
        # Only explicit completion metadata is evidence; a running PTY is not a success.
        if isinstance(response, dict) and response.get("session_id") is None:
            code = response.get("exit_code")
            if type(code) is int:
                payload["exit_code"] = code
                payload["execution_status"] = "completed"
        runner = test_runner(raw)
        if runner:
            payload["test_runner"] = runner
        payload["test_status"] = (
            ("Passed" if payload["exit_code"] == 0 else "Failed")
            if runner and "exit_code" in payload
            else "Unknown"
        )
    if cfg.get("mode") == "Verbose":
        payload["input_bytes"] = len(json.dumps(raw.get("tool_input", {})).encode())
        payload["output_bytes"] = len(json.dumps(raw.get("tool_response", {})).encode())
    if kind == "UserPromptSubmit":
        payload["task"] = "Новая задача; текст промпта не сохраняется"
    unique = raw.get("tool_use_id") if kind in {"PreToolUse", "PostToolUse"} else None
    event_id = str(uuid.uuid4())
    if unique:
        event_identity = [cfg["computer_id"], session, agent, turn, kind, str(unique)]
        event_id = str(uuid.uuid5(uuid.NAMESPACE_URL, json.dumps(event_identity)))
    return {
        "schema_version": 1,
        "event_id": event_id,
        "kind": kind,
        "computer_id": cfg["computer_id"],
        "session_id": session,
        "agent_id": agent,
        "turn_id": turn,
        "occurred_at": now(),
        "evidence": "observed",
        "payload": payload,
    }


def validate_event(event):
    allowed = {
        "schema_version",
        "event_id",
        "kind",
        "computer_id",
        "session_id",
        "agent_id",
        "turn_id",
        "occurred_at",
        "evidence",
        "payload",
        "project_id",
        "project",
        "worktree_id",
    }
    if set(event) - allowed or event.get("schema_version") != 1:
        raise ValueError("Unsupported event schema")
    for key in ("event_id", "computer_id", "session_id", "agent_id", "project_id", "worktree_id"):
        identifier(event[key])
    if event["kind"] not in HOOKS + ["Checkpoint", "MemoryReport", "GitSnapshot"]:
        raise ValueError("Unsupported kind")
    timestamp = dt.datetime.fromisoformat(event["occurred_at"])
    if timestamp.tzinfo is None:
        raise ValueError("Timezone required")
    if event["evidence"] not in {"observed", "agent_reported", "derived"}:
        raise ValueError("Invalid evidence")
    if event["kind"] == "MemoryReport" and event["evidence"] != "agent_reported":
        raise ValueError("Memory is agent reported")
    if not isinstance(event["payload"], dict):
        raise ValueError("Invalid payload")
    allowed_payload = {
        "tool_name",
        "tool_use_id",
        "model",
        "source",
        "trigger",
        "reason",
        "agent_type",
        "exit_code",
        "execution_status",
        "test_status",
        "test_runner",
        "input_bytes",
        "output_bytes",
        "task",
        "branch",
        "commit",
        "files",
        "source_idle_seconds",
        "report",
        "count",
    }
    if set(event["payload"]) - allowed_payload:
        raise ValueError("Unknown payload field")
    p = event["payload"]
    if "exit_code" in p and type(p["exit_code"]) is not int:
        raise ValueError("exit_code must be an integer")
    if p.get("test_status", "Unknown") not in {"Unknown", "Passed", "Failed"}:
        raise ValueError("Invalid test status")
    if p.get("test_status") in {"Passed", "Failed"} and (
        "exit_code" not in p or not p.get("test_runner") or p.get("execution_status") != "completed"
    ):
        raise ValueError("Test claim lacks completed execution")
    if "files" in p and (
        not isinstance(p["files"], list) or not all(isinstance(f, str) for f in p["files"])
    ):
        raise ValueError("Invalid file list")
    if set(event["project"]) - {"name", "remote"}:
        raise ValueError("Unknown project field")
    if event["kind"] == "MemoryReport":
        from .memory import validate_report

        validate_report(event["payload"]["report"])
    clean = redact(event)
    clean["occurred_at"] = timestamp.astimezone(dt.UTC).isoformat()
    if len(json.dumps(clean).encode()) > 128000:
        raise ValueError("Event too large")
    return clean


def fingerprint(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True).encode()).hexdigest()
