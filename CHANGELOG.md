# Changelog

## Unreleased — integration completion

- Expanded REST/MCP to 18 operations: recent activity, daily summaries, independent test and knowledge registration. Existing FIP v1 shapes remain compatible.
- Reused the existing Notion Observatory root, added dedicated-token file setup/read preflight, and prevented live tests from archiving the user root.
- Added private loopback Docker Compose, strict body type checking, dependency audit CI and real-clock soak/live integration runners.
- Fixed explicit UTF-8 reads/writes and equal-timestamp lifecycle handling after actual Windows CI failures; increased detached-worker startup allowance.
- Published preserved Git history in IgorKramar/codex_chronicle using official Git Data API because managed git push authorization is rejected.
- Stable acceptance remains open: real Codex 401/451, dedicated Notion integration, full Windows/WSL plugin checks and completed 12h soak.

## 0.2.0 — 2026-10-19, preliminary

- Added FIP v1 contracts, standalone fip-contracts 1.0.0 package, OpenAPI 3.1 and capability discovery.
- Added transport-independent MemoryService and immutable native records/revisions alongside legacy Codex events.
- Added all fourteen agent operations through REST and official MCP stdio, bounded pagination, literal AND search and evidence resolution.
- Added mandatory write idempotency, atomic nested records, optimistic revisions, project/actor scopes and protected decisions/verified memory.
- Added durable external-client outbox with ordered retry, grant hot reload/revocation/rotation, separate opt-in FIP Notion projection.
- Added WORLD FORGE cross-agent integration scenario, contract compatibility baseline/checker, examples and guides.
- Retained 0.1 legacy routes and existing Codex hook formats; original real-Codex/Notion/OS/soak acceptance gaps remain.

## 0.1.0 — 2026-10-19, preliminary

- Added portable Codex plugin, compatibility manifest, eleven lifecycle handlers and chronicle-memory skill.
- Added fast filtered atomic spool, auto-start local worker, SQLite WAL outbox, retry/backoff, project mapping and CLI.
- Added PostgreSQL/SQLite Collector, scoped machine/project authentication, separate read permissions and OpenAPI memory endpoints.
- Added official Notion REST publisher, seven collections, stable Current State, ADR histories/conflicts, issues and daily/weekly aggregates.
- Added persisted ambiguous-write fences, remote reconciliation and rate limiting.
- Added Linux/Windows installation paths, Docker Compose/Caddy, dependency locks, backup/restore and operator documentation.
- Validated synthetic distributed E2E, PostgreSQL concurrency, backup/restore, mock Notion, Docker and 25k-event accelerated history.
- Real Codex acceptance blocked by CLI authorization; live Notion, Windows/WSL and wall-clock 12h+ soak remain pending. No stable release or production deployment claimed.

### Additional validation fixes

- Daily activity summaries count primary events, excluding derived failure projections; inverted time windows are rejected.
- Windows platform-only lock types are checked without requiring fcntl/msvcrt stubs from the other OS.
