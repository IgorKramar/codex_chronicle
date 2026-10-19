import copy
import json
from pathlib import Path

import pytest
from fip_helpers import artifact, decision, event, knowledge
from fip_helpers import test_result as make_test
from jsonschema import Draft202012Validator, ValidationError

from chronicle.contracts import BUNDLE, OPERATIONS, embedded, validate


@pytest.mark.parametrize(
    "name,record",
    [
        ("AgentEvent", event()),
        ("DecisionRecord", decision("source")),
        ("ArtifactReference", artifact("source")),
        ("KnowledgeRecord", knowledge("source")),
        ("TestResult", make_test("source")),
    ],
)
def test_record_schemas(name, record):
    validate(name, record)
    record["confidence"] = 0.99
    with pytest.raises(ValidationError):
        validate(name, record)


def test_all_schemas_and_mcp_inputs_are_valid():
    Draft202012Validator.check_schema(BUNDLE)
    for op in OPERATIONS:
        Draft202012Validator.check_schema(embedded(op + "Arguments"))
        Draft202012Validator.check_schema(embedded(op + "ToolResult"))
    assert len(OPERATIONS) == 14


def test_schema_source_package_and_runtime_do_not_drift():
    root = Path(__file__).parents[1]
    canonical = json.loads((root / "contracts/fip/v1/fip.schema.json").read_text())
    packaged = json.loads(
        (root / "packages/fip-contracts/src/fip_contracts/schemas/v1/fip.schema.json").read_text()
    )
    assert canonical == BUNDLE == packaged


def test_utc_and_closed_shapes():
    e = event()
    e["timestamp"] = "2026-10-19T10:00:00+03:00"
    with pytest.raises(ValidationError):
        validate("AgentEvent", e)
    e = event()
    e["source_code"] = "private"
    with pytest.raises(ValidationError):
        validate("AgentEvent", e)


def test_fip_version_compatibility_detects_breaking_changes():
    import importlib.util

    path = Path(__file__).parents[1] / "scripts/check_fip_compatibility.py"
    spec = importlib.util.spec_from_file_location("compat", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    baseline = copy.deepcopy(BUNDLE)
    assert module.check(baseline, BUNDLE) == []
    changed = copy.deepcopy(BUNDLE)
    changed["$defs"]["AgentEvent"]["required"].append("new_required")
    assert module.check(baseline, changed)
    changed = copy.deepcopy(BUNDLE)
    changed["$defs"]["DecisionRecord"]["properties"]["status"]["enum"].append("Maybe")
    assert module.check(baseline, changed)
    changed = copy.deepcopy(BUNDLE)
    changed["$defs"]["NewOptionalOperation"] = {"type": "string"}
    assert not module.check(baseline, changed)
    changed = copy.deepcopy(BUNDLE)
    changed["$defs"]["KnowledgeRecord"]["properties"]["title"]["type"] = "integer"
    assert module.check(baseline, changed)
    changed = copy.deepcopy(BUNDLE)
    del changed["$defs"]["ProjectContext"]["properties"]["description"]
    assert module.check(baseline, changed)


def test_distributed_examples_validate_against_public_schema():
    root = Path(__file__).parents[1] / "contracts/fip/v1/examples"
    mapping = {
        "bootstrap": "append_event",
        "experiment": "append_event",
        "decision": "register_decision",
        "artifact": "register_artifact",
    }
    for label, operation in mapping.items():
        validate(
            operation + "Arguments", json.loads((root / (label + ".request.json")).read_text())
        )
        validate(
            operation + "Response", json.loads((root / (label + ".response.json")).read_text())
        )
    for op in ("get_capabilities", "get_project_state", "search_knowledge"):
        validate(op + "Response", json.loads((root / (op + ".response.json")).read_text()))
