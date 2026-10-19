# Validation record — 2026-10-19

Результаты относятся к этой Linux cloud-среде. Версия 0.1.0 предварительная.

## Выполнено

- **47 passed, 1 skipped**: pytest с подключённым PostgreSQL 17; JUnit — [pytest.xml](pytest.xml). Пропущен только opt-in real Notion test. Один Starlette TestClient deprecation warning, тесты завершились успешно.
- Ruff static checks и formatting check прошли; Python compileall прошёл.
- Два синтетических проекта/машины: hook subprocess → durable spool → SQLite → реальный loopback HTTP Collector → PostgreSQL/SQLite contract → stateful mock Notion. Потеря сети, новый Agent process/store, replay после потерянного ACK, раздельные projects/sessions, отсутствие full prompts и стабильные Notion record URLs проверены.
- Scope checks: read не пишет, write не читает, чужой Computer/Project отклоняется; oversized batch отклоняется; конфликтующий Event ID не перезаписывает данные.
- Memory: наблюдаемые test runs требуют structured completion и распознанного runner; запущенная PTY остаётся Unknown. ADR proposal/accepted/revisions/conflicts и явные source references для закрытия issues проверены.
- Mock Notion: root + семь баз, data source query, фиксированные managed blocks, idempotent upsert, lost-response-after-commit recovery, persistent Retry-After, отказ от blind create.
- [Реальный PostgreSQL backup/restore](backup-restore.json): события и uncertain-write metadata восстановлены; duplicate replay после restore не увеличивает число событий.
- [Docker Compose](container-probe.json): образ собран; postgres/collector запущены без Caddy и без public port mappings; ingestion/dedup/read API/health и deploy backup script проверены. Временные Compose volumes/containers удалены.
- [Wheel](wheel-probe.json): установка в чистый venv без dependencies; init/install --prepare-only/status/doctor прошли; manifest и skill присутствуют в wheel.
- [Глобальная установка plugin](plugin-install.json): официальный Codex CLI видит installed=true, enabled=true. Installer не обходит доверие hooks.
- [Нагрузка](load-probe.json): 25 000 unique events, 25 000 повторных доставок, 8 machines, ускоренная история на 13h; потерь/дублей в этом сценарии не обнаружено. Измерены capture и interpreter-startup latency. Это не 13h wall-clock soak и не относительный benchmark Codex.

## Не выполнено / не прошло

- [Два реальных Codex CLI](real-codex.json): оба завершились exit 1 с признаком authentication error, файл задания не создан, hook events не зарегистрированы. Login status показывал ChatGPT login, но реальный запуск не прошёл. Это **неуспешный E2E**, не подтверждение работы plugin lifecycle.
- Реальный Notion API: dedicated NOTION_TOKEN/NOTION_PARENT не настроены. `tests/test_live_notion.py` доступен для запуска после безопасной настройки; сейчас skipped. Наличие ChatGPT Notion connector не является credential для daemon REST publisher.
- Windows/WSL/Python 3.11 и CI matrix добавлены, но не запускались на соответствующих системах.
- Настоящий 12h+ soak, abrupt power loss на физической машине, осмотр настоящих Notion страниц человеком, production HTTPS/DNS и относительное замедление Codex не подтверждены.
- Внешний production server/domain не задан; публичных сетевых служб не развёрнуто.

## Воспроизведение

```bash
.venv/bin/ruff check src tests scripts deploy
.venv/bin/ruff format --check src tests scripts deploy
# Для PostgreSQL: локально задайте CHRONICLE_TEST_POSTGRES на отдельную test DB.
.venv/bin/pytest -q --junitxml=evidence/pytest.xml
.venv/bin/python scripts/load_probe.py
.venv/bin/python scripts/real_codex_e2e.py
# После локальной настройки dedicated Notion credentials:
CHRONICLE_LIVE_NOTION=1 .venv/bin/pytest -q tests/test_live_notion.py
```

Без CHRONICLE_TEST_POSTGRES PostgreSQL test также пропускается (обычный suite: 46 passed, 2 skipped). Probe scripts используют только собственные synthetic projects/test databases; real Notion probe архивирует созданный test root в finally. `container_probe.py` требует заранее собранный codex-chronicle:0.1.0 и Docker; `backup_probe.py` — отдельный chronicle-postgres-probe container и test DSN. Никогда не указывайте production DB для этих scripts.
