"""Generate schema-validated examples, including responses produced by the real core."""

import json
import tempfile
from pathlib import Path

from chronicle.contracts import validate
from chronicle.memory_service import MemoryService, evidence, record_base
from chronicle.store import Store

ROOT = Path(__file__).resolve().parents[1]


def main():
    target = ROOT / "contracts/fip/v1/examples"
    target.mkdir(parents=True, exist_ok=True)

    def base(rid, status="active"):
        return record_base(
            rid,
            "world-forge-demo",
            "req-" + rid,
            "2026-10-19T10:00:00Z",
            "forge-planner",
            "forge-session-001",
            "agent_reported",
            status,
        )

    source = "evt-design-001"
    context = {
        **base("context-game-001"),
        "name": "WORLD FORGE Demo",
        "description": "Synthetic deterministic combat prototype",
        "current_goal": "Make combat replays reproducible",
        "implemented": [],
        "open_questions": ["Replay verification"],
        "llm_summary": "Prototype context; results need primary evidence.",
        "source_ids": [source],
    }
    event = {
        **base(source, "completed"),
        "event_id": source,
        "event_type": "design_research",
        "category": "game_design",
        "summary": "Compare fixed and variable combat simulation ticks",
        "knowledge": [],
        "test_results": [],
        "project_context": context,
    }
    decision = {
        **base("decision-fixed-tick-001", "Proposed"),
        "decision_id": "combat-clock",
        "category": "game_design",
        "title": "Fixed combat tick",
        "problem": "Replay nondeterminism",
        "alternatives": ["Fixed tick", "Variable tick"],
        "choice": "Fixed tick",
        "rationale": "Deterministic replay",
        "consequences": ["Bound simulation step size"],
        "source_event_ids": [source],
        "evidence": [evidence("world-forge-demo", source)],
    }
    result_id = "evt-simulation-001"
    result = {
        **base(result_id, "completed"),
        "event_id": result_id,
        "event_type": "simulation_result",
        "category": "experiment",
        "summary": "Synthetic example: 100 replay ticks matched",
        "knowledge": [
            {
                **base("knowledge-replay-001"),
                "knowledge_id": "replay-mechanic",
                "category": "implementation",
                "title": "Deterministic replay mechanic",
                "text": "100 ticks matched in the example experiment; agent-reported, not server-attested.",
                "source_event_ids": [result_id],
            }
        ],
        "test_results": [
            {
                **base("test-replay-001", "Passed"),
                "test_id": "replay-check",
                "name": "Replay equality",
                "runner": "python",
                "execution_status": "completed",
                "exit_code": 0,
                "summary": "Synthetic example result",
                "source_event_ids": [result_id],
            }
        ],
    }
    artifact = {
        **base("artifact-replay-001", "available"),
        "artifact_id": "replay-implementation",
        "title": "Replay implementation and test report",
        "uri": "https://example.org/world-forge/commits/demo",
        "artifact_type": "implementation",
        "sha256": None,
        "source_event_ids": [result_id],
        "evidence": [evidence("world-forge-demo", result_id)],
    }
    requests = [
        ("append_event", "bootstrap", event),
        ("register_decision", "decision", decision),
        ("append_event", "experiment", result),
        ("register_artifact", "artifact", artifact),
    ]
    actor = {
        "sha256": "0" * 64,
        "principal_id": "forge-planner",
        "agent_id": "forge-planner",
        "scopes": ["read", "write"],
        "projects": ["world-forge-demo"],
        "allow_content": True,
    }
    samples = {}
    with tempfile.TemporaryDirectory(prefix="fip-examples-") as tmp:
        service = MemoryService(Store(Path(tmp) / "db"))
        for operation, label, record in requests:
            args = {"record": record, "idempotency_key": "example-" + label}
            validate(operation + "Arguments", args)
            response = service.execute(operation, args, actor)
            samples[label + ".request.json"] = args
            samples[label + ".response.json"] = response
            samples[label + ".http-body.json"] = record
        for operation, args in [
            ("get_capabilities", {}),
            ("get_project_state", {"project_id": "world-forge-demo"}),
            (
                "search_knowledge",
                {"project_id": "world-forge-demo", "query": "deterministic replay"},
            ),
        ]:
            samples[operation + ".request.json"] = args
            samples[operation + ".response.json"] = service.execute(operation, args, actor)
    for name, value in samples.items():
        (target / name).write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n")
    packaged = ROOT / "packages/fip-contracts/src/fip_contracts/examples/v1"
    packaged.mkdir(parents=True, exist_ok=True)
    for name, value in samples.items():
        (packaged / name).write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n")
    print("Generated schema-validated synthetic FIP requests and real-core responses")


if __name__ == "__main__":
    main()
