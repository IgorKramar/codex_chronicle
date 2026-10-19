# FIP v1 — Forge Interoperability Protocol

JSON Schema dialect: 2020-12. Contract version: 1.0.0. API version: `v1`.
`fip.schema.json` is the canonical complete bundle, `$id=urn:fip:v1`. Named schema files reference that bundle. Resolve URNs through a local registry; do not fetch schemas from the Internet. The standalone `fip-contracts` wheel provides schemas, examples and validation helpers.

## Common fields

| Field | Required | Meaning |
|---|---|---|
| api_version | yes | Exact `v1`; incompatible versions are rejected |
| request_id | yes on records/responses, generated when absent on reads | Correlation, not an idempotency key |
| project_id | yes | Non-null on records; null on global capability/list/error envelopes |
| session_id | when applicable | Required for AgentSession; optional elsewhere |
| agent_id | when applicable | Required and grant-bound on external writes; optional/null on derived global context |
| timestamp | yes | Source record time in UTC ISO 8601 (`Z` or `+00:00`); response envelope time is server response creation |
| status | yes | Record-specific enum, or `ok`/`queued`/`error` for envelopes |
| artifact_refs | yes, can be [] | References to registered artifacts; never file contents |
| evidence | yes, can be [] for unconfirmed claims | Explicit source links with provenance |
| confidence | optional | `label` and `basis`; subjective assessment, not a probability |

`EvidenceReference` and `ArtifactLink` are compact nested references, not message envelopes: they do not recursively require the common fields. Evidence always names its own project. This avoids infinite envelope nesting.

Every stored record has an immutable record_id, revision >=1, supersedes (null for first revision), provenance (`observed`, `agent_reported`, `derived`). Entity identity uses project_id plus type plus decision_id/knowledge_id/artifact_id/test_id/session_id. Session identity also includes agent_id. AgentEvent.event_id equals record_id, is revision 1 and can never be revised. Incoming `legacy-`, `derived:`, `state:`, `session:`, `failure:` record namespaces are reserved for projections.

All supplied revision/source/actor relationships are domain constraints in addition to JSON Schema. `source_event_ids` must reference primary events in the same authorized project. `source_ids` may reference other existing project records. An Accepted decision requires decide scope and evidence; verified knowledge requires verify scope. Changing another author's entity requires revise. No public delete/update-in-place operation exists.

## Structures

- ProjectContext: declared project description/current goal and derived LLM context. `get_project_state` returns a bounded projection, not a writable predecessor.
- AgentSession: declared/derived task and lifecycle. A completed task does not automatically mean a Completed session.
- AgentEvent: immutable event; may atomically contain KnowledgeRecord, TestResult, AgentSession, ProjectContext records.
- DecisionRecord: Proposed/Accepted/Rejected/Superseded, alternatives, choice, rationale, consequences and source events.
- KnowledgeRecord: category, title, text, source events, versioned status.
- ArtifactReference: HTTPS or URN link, type, optional SHA256. No uploads/downloads or repository reading.
- EvidenceReference: event/record/test_result/commit/uri. A URI or commit reference is not proof that content was fetched or tested.
- TestResult: explicit execution status and exit code. Passed/Failed requires consistent completed execution. External results remain agent_reported unless an observe grant explicitly authorizes attestation.
- CapabilityDescriptor: functions, versions, transport descriptions, categories, search semantics and limits.
- ApiError: stable code, safe message, retryable flag; never raw database/Notion errors.

Categories: architecture, game_design, implementation, experiment, decision, failure, discovery, testing, project_context.

## Compatibility

Public v1 shapes are closed (`additionalProperties=false`) and frozen by compatibility-baseline.json. Do not add even an optional field or enum member to an existing v1 response: old strict clients would reject it. Changes to required fields, types, enums, bounds, patterns, references or meaning require v2. New operations and standalone definitions may be added; clients discover them through get_capabilities. Documentation/examples may change without changing shape. The compatibility checker is intentionally conservative and cannot prove semantic compatibility: ADR/reviewer review remains required.

Do not overwrite the baseline to make CI pass. It records the first committed public v1 shapes. Validate changes using `scripts/check_fip_compatibility.py`. Old Chronicle `/v1/projects`, `/v1/events`, etc. remain available with their original shapes; FIP uses `/v1/memory`.

Examples are synthetic and marked as such in their content. They demonstrate a format, not evidence about a real game.
