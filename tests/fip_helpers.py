import copy
import hashlib
import uuid

from chronicle.memory_service import record_base


def grant(token="agent-a", agent="agent-a", scopes=None, projects=None):
    return {
        "sha256": hashlib.sha256(token.encode()).hexdigest(),
        "principal_id": "principal-" + agent,
        "agent_id": agent,
        "scopes": scopes or ["read", "write"],
        "projects": projects or ["game-one"],
        "allow_content": True,
    }


def base(pid="game-one", agent="agent-a", status="active"):
    return record_base(
        str(uuid.uuid4()),
        pid,
        str(uuid.uuid4()),
        agent_id=agent,
        session_id="session-" + agent,
        provenance="agent_reported",
        status=status,
    )


def event(
    pid="game-one",
    agent="agent-a",
    category="experiment",
    summary="Physics simulation deterministic result",
):
    b = base(pid, agent, "completed")
    return {
        **b,
        "event_id": b["record_id"],
        "event_type": "simulation_result",
        "category": category,
        "summary": summary,
        "knowledge": [],
        "test_results": [],
    }


def decision(source, agent="agent-a", status="Proposed"):
    from chronicle.memory_service import evidence

    b = base(agent=agent, status=status)
    return {
        **b,
        "decision_id": "physics-engine",
        "title": "Deterministic physics",
        "category": "architecture",
        "problem": "Reproducible simulation",
        "alternatives": ["fixed tick", "variable tick"],
        "choice": "fixed tick",
        "rationale": "Simulation reproducibility",
        "consequences": ["bounded step size"],
        "source_event_ids": [source],
        "evidence": [evidence("game-one", source)],
    }


def knowledge(source, agent="agent-a", text="Implemented deterministic physics mechanic"):
    b = base(agent=agent)
    return {
        **b,
        "knowledge_id": str(uuid.uuid4()),
        "category": "implementation",
        "title": "Physics mechanic",
        "text": text,
        "source_event_ids": [source],
    }


def artifact(source, agent="agent-a"):
    from chronicle.memory_service import evidence

    b = base(agent=agent, status="available")
    return {
        **b,
        "artifact_id": "physics-build",
        "title": "Physics implementation",
        "uri": "https://example.org/forge/commit/abc",
        "artifact_type": "implementation",
        "sha256": None,
        "source_event_ids": [source],
        "evidence": [evidence("game-one", source)],
    }


def test_result(source, agent="agent-a", status="Passed", execution="completed", code=0):
    b = base(agent=agent, status=status)
    return {
        **b,
        "test_id": str(uuid.uuid4()),
        "name": "Physics determinism",
        "runner": "pytest",
        "execution_status": execution,
        "exit_code": code,
        "summary": "Deterministic replay confirmed",
        "source_event_ids": [source],
    }


def revision(record, agent=None):
    revised = copy.deepcopy(record)
    revised.update(
        record_id=str(uuid.uuid4()),
        request_id=str(uuid.uuid4()),
        revision=record["revision"] + 1,
        supersedes=record["record_id"],
    )
    if agent:
        revised["agent_id"] = agent
    return revised
