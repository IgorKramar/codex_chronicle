# CODEX CHRONICLE

Distributed Agent Journal & Shared Project Memory. Python 3.11+, локальный offline-журнал Codex, Collector и Notion Publisher.

**Версия 0.1.0 — предварительный выпуск.** Локальные, распределённые и mock Notion проверки выполнены. Приёмка с двумя реальными Codex заблокирована авторизацией CLI в этой среде; real Notion, Windows/WSL и непрерывный 12h+ soak ещё не подтверждены. Не считать эту версию прошедшей все критерии stable.

## Быстрый запуск

```bash
python3 -m venv ~/.local/share/codex-chronicle/venv
~/.local/share/codex-chronicle/venv/bin/pip install /path/to/codex_chronicle-0.1.0-py3-none-any.whl
~/.local/share/codex-chronicle/venv/bin/chronicle init
~/.local/share/codex-chronicle/venv/bin/chronicle install
```

Установщик использует официальный personal marketplace и `codex plugin add`; существующие hooks/config не заменяются. Перезапустите Codex и **просмотрите и разрешите hooks в Codex**. Доверие не выдаётся автоматически. После `SessionStart` hook запускает отдельный worker; новые сессии не требуют команды журналирования. Для восстановления очереди сразу после входа в ОС установите службу из [OPERATIONS.md](docs/OPERATIONS.md).

По умолчанию всё остаётся локально: prompts, source, terminal output и transcripts не сохраняются. Экспорт каждого проекта требует явной политики:

```bash
chronicle projects --discover /path/to/repository
chronicle projects
chronicle projects --project PROJECT_ID --policy export
chronicle doctor
chronicle status
chronicle report --project PROJECT_ID
```

Добавьте путь к `chronicle` в PATH для интерактивного CLI. Hook использует абсолютный путь Python, поэтому не зависит от PATH вашей shell. В Windows используйте [install-windows.ps1](scripts/install-windows.ps1); WSL устанавливается отдельно внутри дистрибутива.

## Что реализовано

- Portable `plugin.json`, compatibility manifest, 11 hooks (10 требуемых + PreToolUse), skill `chronicle-memory`.
- Атомарный отфильтрованный spool, SQLite WAL/FULL, persistent outbox, deduplication, backoff, Git metadata без diff.
- Computer/Project/Session/Turn/Agent/Event/Worktree IDs; remote SSH/HTTPS normalization, ручной bind, конкурентная защита конфигурации.
- Collector: scoped write/read credentials, PostgreSQL/SQLite, sequence cursor с согласованным порядком commit, OpenAPI, read-only память для Джарвиса.
- Notion: Observatory, семь баз, стабильная Current State URL, session/turn aggregates, ADR revisions, issues, daily/weekly сравнение. Единственный publisher, rate limiting, persisted Retry-After, reconciliation до повторного create.
- Наблюдения `observed`, отчёты `agent_reported`, агрегаты `derived`. Конфликтующие Accepted ADR отображаются явно. `Stop` не означает завершение сессии; отсутствие активности становится `Stale`.

## Документация

- [Установка, standalone, несколько компьютеров, Docker, безопасность и восстановление](docs/OPERATIONS.md)
- [Архитектура и официальные источники](docs/ARCHITECTURE.md)
- [CHATGPT_INTEGRATION.md](CHATGPT_INTEGRATION.md)
- [Матрица требований и открытая приёмка](docs/ACCEPTANCE.md)
- [OpenAPI](docs/openapi.json)
- [Доказательства проверок](evidence/VALIDATION.md)

## Разработка

```bash
python -m venv .venv
.venv/bin/pip install -r requirements-dev.lock
.venv/bin/pip install --no-deps -e .
.venv/bin/ruff check src tests scripts deploy
.venv/bin/ruff format --check src tests scripts deploy
.venv/bin/pytest -q
.venv/bin/python scripts/load_probe.py
```

`requirements-*.lock` фиксируют зависимости проверенного окружения. Wheel локального агента не требует runtime-зависимостей. Сервер устанавливается с `[server]`. Проект не отправляет сообщения другим людям и не публикует данные без настроенной export policy.
