# FIP v1 validation — Chronicle 0.2.0

Дата: 2026-10-19. Python 3.12.14, Linux. Contract version 1.0.0, JSON Schema 2020-12, OpenAPI 3.1.0, официальный MCP Python SDK 1.30.0.

## Результат

**80 passed, 1 skipped**, [JUnit](fip-pytest.xml). Единственный skipped — ранее предусмотренный live Notion test: dedicated credentials не настроены. Один deprecation warning от Starlette TestClient/httpx; ошибок тестов нет. PostgreSQL tests включены, не skipped. Ruff/static formatting/compileall и compatibility checker прошли.

Старые Codex hook/outbox/Collector/mock Notion тесты сохранены и проходят. Предыдущие результаты 0.1.0 не объявляются повторным real-Codex success.

## Проверено

- Все 14 MCP/REST operations имеют Arguments/Response JSON Schema; schemas корректны и одинаковы в canonical contracts, runtime assets и standalone package.
- Common fields, strict UTC, закрытые shapes, confidence object вместо вероятности; examples проходят schemas.
- Совместимость: baseline shapes неизменны, breaking required/enum/type/property changes обнаруживаются, включая поля с именами title/description; новые definitions допускаются. OpenAPI 3.1 с разрешимыми local references сохранён в docs/openapi.json.
- Межагентный scenario: `tests/test_world_forge_integration.py`. Planner читает history/Accepted decision через настоящий loopback HTTP, выполняет Python experiment (100 deterministic replay ticks), пишет событие/knowledge/test/artifact. Независимый MCP process через официальный stdio protocol находит результат; первичное событие читается через защищённый resolver. Клиентам не нужен доступ к DB/Notion.
- Реальный MCP stdio: initialize, tools/list, четырнадцать tools в write-enabled режиме, одиннадцать в read-only; structuredContent + JSON text, штатные ApiError.
- Read-only MCP не отправляет даже уже существующие pending writes фоном. Server read scope не разрешает writes; current project scopes и agent identity проверяются и при idempotent replay.
- SQLite/PostgreSQL: concurrent replay одного key, response persistence/restart, atomic nested records, immutable IDs, защищённые Accepted/verified revisions, конфликт predecessor/cross-author revision.
- Idempotency key с другим body отклоняется; потерянный ACK не создаёт новый record. External-client outbox переживает новый client process, сохраняет body/key и порядок зависимостей, не выдаёт queued за accepted.
- Cursor snapshot не включает новые append; фильтр/метод/права привязаны к cursor. Page/byte limits, literal casefold AND search, private project isolation и secret redaction.
- Notion outage не блокирует FIP read/write; новая FIP Notion projection требует отдельного opt-in и сохраняет стабильный Current State ID.
- Latest context учитывает archived status и retract knowledge; старые ревизии сохранены. Один факт task completion не объявляет сессию Completed.
- Token rotation/revocation без restart; malformed auth file закрывает доступ. Токены не записываются в client outbox.

## Установочные и эксплуатационные доказательства

- [fip-package-probe.json](fip-package-probe.json): чистый venv core wheel без jsonschema/MCP/FastAPI dependencies; init/prepare-install/status прошли. Второй чистый venv: fip-contracts wheel, examples и validation без Chronicle. MemoryService import не загружает FastAPI/MCP/Notion.
- [fip-container-probe.json](fip-container-probe.json): Docker image 0.2.0 + Compose postgres/collector; legacy ingestion/read и новый FIP read/discovery, deduplication и backup script прошли. Caddy не запускался, публичные порты не открывались; temporary stack удалён.
- [fip-backup-restore.json](fip-backup-restore.json): реальный pg_dump/pg_restore сохранил native FIP records и idempotency ACK; replay после restore возвращает прежний ответ без дублей. Старые events/uncertain-write fences также восстановлены.

## Границы проверки

Не подключались настоящие WORLD FORGE/Ludascope/Universal Modder: это будущие consumers. Проверен их программный контракт и внешние клиенты, не реальные будущие adapters. Нет semantic search, embedding rank или автоматического semantic deduplication.

Исходные acceptance gaps 0.1.0 остаются: реальный Codex end-to-end ранее завершился authentication error; real Notion, Windows/WSL/3.11 и настоящий 12h+ soak не подтверждены здесь. Production server/domain не задан, публичное развёртывание не выполнялось.

## Воспроизведение

```bash
.venv/bin/ruff check src tests scripts packages deploy
.venv/bin/ruff format --check src tests scripts packages deploy
.venv/bin/python scripts/check_fip_compatibility.py
# Настройте CHRONICLE_TEST_POSTGRES на отдельный локальный test instance, не production.
.venv/bin/pytest -q --junitxml=evidence/fip-pytest.xml
.venv/bin/python scripts/fip_package_probe.py
```

Без CHRONICLE_TEST_POSTGRES два PostgreSQL tests дополнительно skipped. Для container probe предварительно соберите image 0.2.0; для backup probe используйте отдельный chronicle-...-probe container. Не указывайте production DB. Static examples — synthetic; TestResult в них agent_reported, не server-attested proof.
