<div align="center">

# Codex Chronicle

**English** · [Русский](README.md)

**A local-first agent journal and shared project memory.**

Python · SQLite / PostgreSQL · REST · MCP

</div>

---

Codex Chronicle records structured development activity and makes project memory available to agents. It separates the local journal, collector/API and optional Notion publishing, so retaining project history does not require exporting everything to an external service.

**Status: preview release.** The repository describes version 0.2.0 and continuing integration work. Some live-service, cross-platform and long-running acceptance checks remain open. See the [acceptance matrix](docs/ACCEPTANCE.md) and [current acceptance status](ACCEPTANCE_STATUS.md).

## Engineering focus

| Concern | Approach |
| :--- | :--- |
| Surviving interruption | Local spool, SQLite WAL and a persistent outbox |
| Retrying safely | Idempotency keys, deduplication, backoff and immutable revisions |
| Tracking context | Project, computer, session, turn, agent, event and worktree identities |
| Separating evidence | Observed events, agent-reported information and derived aggregates |
| Sharing memory | A transport-independent service with authenticated REST and MCP interfaces |
| Controlled export | Explicit per-project policies; optional Notion publisher |

The local flow does not store prompts, source code, terminal output or transcripts by default. Project export must be configured explicitly. This is a design boundary, not a claim that arbitrary imported data is automatically safe to publish.

## Start here

- [Operations](docs/OPERATIONS.md): installation, standalone and multi-computer setups, Docker and recovery.
- [Architecture](docs/ARCHITECTURE.md): components and design decisions.
- [API](docs/API.md) and [integration guide](docs/INTEGRATION.md): service contracts and clients.
- [FIP contracts](contracts/fip/v1/README.md): schemas and examples.
- [Validation evidence](evidence/VALIDATION.md): recorded checks and their scope.
- [Release workflow](docs/RELEASE.md): clean checkout, CI and packaging.

The [Russian README](README.md) includes installation commands and notes about the ongoing work on the `master` branch. Check the documentation for the branch or release you use; integration surfaces have evolved during the preview.

## Development

From a checkout, using Python 3.11+:

```sh
python -m venv .venv
.venv/bin/pip install -r requirements-dev.lock
.venv/bin/pip install --no-deps -e .
.venv/bin/ruff check src tests scripts deploy
.venv/bin/ruff format --check src tests scripts deploy
.venv/bin/pytest -q
```

Additional load probes and live-service checks are documented separately. Mock tests and local tests are not substitutes for real-provider end-to-end acceptance.

## What this is not

Chronicle is not a claim of a completed production acceptance programme or a universal semantic memory engine. The documented search contract is lexical, and export requires deliberate configuration. Consult the acceptance documents before relying on a feature in a new environment.

---

[Igor Kramar](https://github.com/IgorKramar) · Agent infrastructure & distributed workflows
