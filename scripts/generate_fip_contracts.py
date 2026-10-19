"""Canonical FIP v1 schemas; copy identical schemas into distributable packages."""

import copy
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ID = "urn:fip:v1"
CATEGORIES = [
    "architecture",
    "game_design",
    "implementation",
    "experiment",
    "decision",
    "failure",
    "discovery",
    "testing",
    "project_context",
]


def ref(name):
    return {"$ref": ID + "#/$defs/" + name}


def obj(properties, required=()):
    return {
        "type": "object",
        "properties": properties,
        "required": list(required),
        "additionalProperties": False,
    }


def arr(items, maximum=100):
    return {"type": "array", "items": items, "maxItems": maximum}


def string(maximum=4000):
    return {"type": "string", "maxLength": maximum}


identifier = {"type": "string", "pattern": r"^[A-Za-z0-9_.:@/-]{1,256}$", "maxLength": 256}
nullable_id = {"anyOf": [identifier, {"type": "null"}]}
utc = {"type": "string", "format": "date-time", "pattern": r"(?:Z|\+00:00)$"}
defs = {}
defs["Confidence"] = obj(
    {"label": {"enum": ["unknown", "low", "medium", "high"]}, "basis": string(1000)},
    ["label", "basis"],
)
defs["EvidenceReference"] = obj(
    {
        "evidence_id": identifier,
        "project_id": identifier,
        "kind": {"enum": ["event", "record", "commit", "test_result", "uri"]},
        "target_id": nullable_id,
        "uri": {
            "anyOf": [{"type": "string", "format": "uri", "maxLength": 2000}, {"type": "null"}]
        },
        "provenance": {"enum": ["observed", "agent_reported", "derived"]},
        "description": string(1000),
    },
    ["evidence_id", "project_id", "kind", "target_id", "uri", "provenance"],
)
defs["ArtifactLink"] = obj(
    {"artifact_id": identifier, "record_id": nullable_id}, ["artifact_id", "record_id"]
)
common = {
    "api_version": {"const": "v1"},
    "request_id": identifier,
    "project_id": nullable_id,
    "session_id": nullable_id,
    "agent_id": nullable_id,
    "timestamp": utc,
    "status": string(64),
    "artifact_refs": arr(ref("ArtifactLink"), 20),
    "evidence": arr(ref("EvidenceReference"), 30),
    "confidence": ref("Confidence"),
}
required_common = [
    "api_version",
    "request_id",
    "project_id",
    "timestamp",
    "status",
    "artifact_refs",
    "evidence",
]
record = {
    "record_id": identifier,
    "revision": {"type": "integer", "minimum": 1},
    "supersedes": nullable_id,
    "provenance": {"enum": ["observed", "agent_reported", "derived"]},
}


def model(name, fields, required, statuses):
    props = {**common, **record, **fields, "project_id": identifier, "status": {"enum": statuses}}
    defs[name] = obj(props, required_common + list(record) + list(required))


model(
    "ProjectContext",
    {
        "name": string(256),
        "description": string(4000),
        "current_goal": string(2000),
        "implemented": arr(string(1000), 30),
        "open_questions": arr(string(1000), 30),
        "llm_summary": string(12000),
        "source_ids": arr(identifier, 100),
    },
    [
        "name",
        "description",
        "current_goal",
        "implemented",
        "open_questions",
        "llm_summary",
        "source_ids",
    ],
    ["active", "archived", "unknown"],
)
model(
    "AgentSession",
    {
        "session_id": identifier,
        "agent_id": identifier,
        "task": string(2000),
        "started_at": utc,
        "ended_at": {"anyOf": [utc, {"type": "null"}]},
        "last_activity": utc,
    },
    ["session_id", "agent_id", "task", "started_at", "ended_at", "last_activity"],
    ["Running", "Completed", "Failed", "Interrupted", "Stale", "Unknown"],
)
model(
    "KnowledgeRecord",
    {
        "knowledge_id": identifier,
        "category": {"enum": CATEGORIES},
        "title": string(256),
        "text": string(12000),
        "source_event_ids": arr(identifier, 30),
    },
    ["knowledge_id", "category", "title", "text", "source_event_ids"],
    ["proposed", "active", "verified", "superseded", "retracted"],
)
model(
    "DecisionRecord",
    {
        "decision_id": identifier,
        "category": {"enum": ["architecture", "game_design", "decision"]},
        "title": string(256),
        "problem": string(2000),
        "alternatives": arr(string(1000), 20),
        "choice": string(4000),
        "rationale": string(4000),
        "consequences": arr(string(1000), 20),
        "source_event_ids": arr(identifier, 30),
    },
    [
        "decision_id",
        "category",
        "title",
        "problem",
        "alternatives",
        "choice",
        "rationale",
        "consequences",
        "source_event_ids",
    ],
    ["Proposed", "Accepted", "Rejected", "Superseded"],
)
model(
    "ArtifactReference",
    {
        "artifact_id": identifier,
        "title": string(256),
        "uri": {"type": "string", "format": "uri", "maxLength": 2000},
        "artifact_type": {
            "enum": ["implementation", "test_report", "simulation", "build", "document", "other"]
        },
        "sha256": {"anyOf": [{"type": "string", "pattern": "^[a-f0-9]{64}$"}, {"type": "null"}]},
        "source_event_ids": arr(identifier, 30),
    },
    ["artifact_id", "title", "uri", "artifact_type", "sha256", "source_event_ids"],
    ["available", "superseded", "unavailable"],
)
model(
    "TestResult",
    {
        "test_id": identifier,
        "name": string(256),
        "runner": string(256),
        "execution_status": {"enum": ["started", "completed", "unknown"]},
        "exit_code": {"anyOf": [{"type": "integer"}, {"type": "null"}]},
        "summary": string(4000),
        "source_event_ids": arr(identifier, 30),
    },
    ["test_id", "name", "runner", "execution_status", "exit_code", "summary", "source_event_ids"],
    ["Passed", "Failed", "Unknown", "Skipped"],
)
model(
    "AgentEvent",
    {
        "event_id": identifier,
        "event_type": string(128),
        "category": {"enum": CATEGORIES},
        "summary": string(4000),
        "knowledge": arr(ref("KnowledgeRecord"), 8),
        "test_results": arr(ref("TestResult"), 8),
        "session": {"anyOf": [ref("AgentSession"), {"type": "null"}]},
        "project_context": {"anyOf": [ref("ProjectContext"), {"type": "null"}]},
    },
    ["event_id", "event_type", "category", "summary", "knowledge", "test_results"],
    ["recorded", "started", "completed", "failed", "unknown"],
)
defs["CapabilityDescriptor"] = obj(
    {
        **common,
        "service": {"const": "Chronicler"},
        "contract_version": {"const": "1.0.0"},
        "supported_api_versions": arr(string(16), 10),
        "operations": arr(string(128), 100),
        "memory_categories": arr(string(64), 20),
        "transports": arr(string(64), 10),
        "search_semantics": string(2000),
        "max_page_size": {"type": "integer"},
        "max_response_bytes": {"type": "integer"},
        "write_requires_idempotency_key": {"const": True},
        "notion_required": {"const": False},
    },
    required_common
    + [
        "service",
        "contract_version",
        "supported_api_versions",
        "operations",
        "memory_categories",
        "transports",
        "search_semantics",
        "max_page_size",
        "max_response_bytes",
        "write_requires_idempotency_key",
        "notion_required",
    ],
)
defs["ApiError"] = obj(
    {**common, "code": string(128), "message": string(2000), "retryable": {"type": "boolean"}},
    required_common + ["code", "message", "retryable"],
)
filters = {
    "project_id": identifier,
    "session_id": identifier,
    "agent_id": identifier,
    "category": {"enum": CATEGORIES},
    "status": string(64),
    "since": utc,
    "until": utc,
    "cursor": string(3000),
    "limit": {"type": "integer", "minimum": 1, "maximum": 100},
    "max_response_bytes": {"type": "integer", "minimum": 8192, "maximum": 131072},
    "query": {"type": "string", "minLength": 2, "maxLength": 256},
    "api_version": {"const": "v1"},
    "request_id": identifier,
}
READS = {
    "list_projects": ("ProjectContext", []),
    "get_project_state": ("ProjectContext", ["project_id"]),
    "get_project_history": ("AgentEvent", ["project_id"]),
    "list_sessions": ("AgentSession", []),
    "get_session_details": ("AgentSession", ["project_id", "session_id"]),
    "search_knowledge": ("KnowledgeRecord", ["query"]),
    "get_decisions": ("DecisionRecord", ["project_id"]),
    "get_failures": ("AgentEvent", ["project_id"]),
    "get_artifacts": ("ArtifactReference", ["project_id"]),
    "get_test_results": ("TestResult", ["project_id"]),
}
WRITES = {
    "append_event": "AgentEvent",
    "register_decision": "DecisionRecord",
    "register_artifact": "ArtifactReference",
}
for op, (item, required) in READS.items():
    allowed = set(filters) - {"query"}
    if op == "search_knowledge":
        allowed.add("query")
    if op in {"list_sessions", "get_artifacts", "get_test_results"}:
        allowed.discard("category")
    if op == "list_projects":
        allowed -= {"session_id", "agent_id", "category"}
    if op == "get_project_state":
        allowed = {"project_id", "api_version", "request_id", "max_response_bytes"}
    if op == "get_session_details":
        allowed = {
            "project_id",
            "session_id",
            "agent_id",
            "api_version",
            "request_id",
            "max_response_bytes",
        }
    defs[op + "Arguments"] = obj(
        {k: copy.deepcopy(v) for k, v in filters.items() if k in allowed}, required
    )
    data = obj(
        {
            "items": arr(ref(item)),
            "next_cursor": {"type": ["string", "null"]},
            "has_more": {"type": "boolean"},
            "snapshot": string(3000),
        },
        ["items", "next_cursor", "has_more", "snapshot"],
    )
    if op in {"get_project_state", "get_session_details"}:
        data = ref(item)
    defs[op + "Response"] = obj({**common, "data": data}, required_common + ["data"])
for op, item in WRITES.items():
    defs[op + "Arguments"] = obj(
        {"record": ref(item), "idempotency_key": identifier}, ["record", "idempotency_key"]
    )
    defs[op + "Response"] = obj(
        {
            **common,
            "data": obj(
                {
                    "record_id": identifier,
                    "revision": {"type": "integer"},
                    "sequence": {"type": "integer"},
                    "accepted": {"const": True},
                },
                ["record_id", "revision", "sequence", "accepted"],
            ),
        },
        required_common + ["data"],
    )
defs["get_capabilitiesArguments"] = obj({"api_version": {"const": "v1"}, "request_id": identifier})
defs["get_capabilitiesResponse"] = ref("CapabilityDescriptor")
defs["RecordLookupResponse"] = obj(
    {
        **common,
        "data": obj(
            {
                "record_type": {
                    "enum": [
                        "ProjectContext",
                        "AgentSession",
                        "AgentEvent",
                        "DecisionRecord",
                        "KnowledgeRecord",
                        "ArtifactReference",
                        "TestResult",
                    ]
                },
                "record": {
                    "oneOf": [
                        ref(k)
                        for k in [
                            "ProjectContext",
                            "AgentSession",
                            "AgentEvent",
                            "DecisionRecord",
                            "KnowledgeRecord",
                            "ArtifactReference",
                            "TestResult",
                        ]
                    ]
                },
            },
            ["record_type", "record"],
        ),
    },
    required_common + ["data"],
)
defs["QueuedWriteResponse"] = obj(
    {
        **common,
        "data": obj(
            {
                "operation": {"enum": list(WRITES)},
                "idempotency_key": identifier,
                "queued": {"const": True},
                "accepted": {"const": False},
            },
            ["operation", "idempotency_key", "queued", "accepted"],
        ),
    },
    required_common + ["data"],
)
for op in [*READS, *WRITES, "get_capabilities"]:
    defs[op + "ToolResult"] = {
        "anyOf": [ref(op + "Response"), ref("ApiError")]
        + ([ref("QueuedWriteResponse")] if op in WRITES else [])
    }
project_identifier = {"type": "string", "pattern": r"^[A-Za-z0-9_.:@-]{1,256}$", "maxLength": 256}
for definition in defs.values():
    if "project_id" in definition.get("properties", {}):
        original = definition["properties"]["project_id"]
        definition["properties"]["project_id"] = (
            {"anyOf": [project_identifier, {"type": "null"}]}
            if "anyOf" in original
            else project_identifier
        )
BUNDLE = {
    "$schema": "https://json-schema.org/draft/2020-12/schema",
    "$id": ID,
    "title": "FIP v1 contracts",
    "$defs": defs,
}


def main():
    target = ROOT / "contracts/fip/v1"
    target.mkdir(parents=True, exist_ok=True)
    encoded = json.dumps(BUNDLE, ensure_ascii=False, indent=2) + "\n"
    (target / "fip.schema.json").write_text(encoded)
    for name in defs:
        (target / (name + ".schema.json")).write_text(
            json.dumps(
                {
                    "$schema": BUNDLE["$schema"],
                    "$id": "urn:fip:v1:" + name,
                    "$ref": ID + "#/$defs/" + name,
                },
                indent=2,
            )
            + "\n"
        )
    for dest in [
        ROOT / "src/chronicle/assets/fip/v1",
        ROOT / "packages/fip-contracts/src/fip_contracts/schemas/v1",
    ]:
        dest.mkdir(parents=True, exist_ok=True)
        (dest / "fip.schema.json").write_text(encoded)
    baseline = target / "compatibility-baseline.json"
    if not baseline.exists():
        baseline.write_text(encoded)


if __name__ == "__main__":
    main()
