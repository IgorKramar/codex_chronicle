# Codex Chronicle — архитектура

Дата исследования: 2026-10-19. Целевая проверяемая версия: Codex CLI 0.159.2.

`Codex → command hook → atomic filtered spool → Agent → SQLite outbox → HTTPS Collector → PostgreSQL → Notion Publisher`.
Standalone: Agent → SQLite → Notion Publisher. Python 3.11+; локальный путь использует только стандартную библиотеку. FastAPI/uvicorn и psycopg — зависимости серверного режима. Python выбран вместо Node/Rust ради SQLite, простого распространения и отсутствия необходимости собирать отдельные бинарники; стоимость запуска измеряется отдельно.

Hook синхронно сохраняет только разрешённую схему в файл с fsync + atomic rename, без Git/сети. Ошибки не управляют Codex. Agent отдельно собирает Git metadata (без diff/содержимого), дедуплицирует и отправляет outbox. Не подтверждённые сервером события переживают рестарт. Повторная доставка допустима; повторное применение исключает Event ID. Collector назначает глобальный номер при приёме; это порядок приёма, а не причинный порядок между машинами. Время источника и приёма сохраняется раздельно. Нет last-writer-wins для Current State: состояние строится из всех событий с указанием источников.

Project ID: UUIDv5 от нормализованного remote, явно назначенный ID имеет приоритет. Без remote выдаётся зарегистрированный UUID, сохранённый вне репозитория. Перенос/несколько каталогов — явный bind. SSH/HTTPS remote одного host/path совпадают; credentials, query и fragment исключаются. Worktree и Computer ID различимы. Сессия идентифицируется сочетанием Computer ID + Session ID + Agent ID.

Наблюдения immutable. Отчёт агента — отдельный тип `MemoryReport` и evidence=agent_reported, не доказательство теста. Exit code допускается только из структурированного завершённого результата; terminal session ID не равен завершению. `Stop` не завершает сессию. `SessionEnd(reason=other)` означает закрытие, итог Unknown. Stale означает отсутствие свежих исходных событий, не сбой/успех. Checkpoint не выдаёт живость процесса Codex за установленный факт.

Политика по умолчанию local; экспорт разрешается явно для зарегистрированных проектов. Prompts, source, stdout, transcript и произвольные поля не сохраняются. Редакция секретов — дополнительный барьер поверх allowlist. Pause/exclude применяются до сохранения. Read и write credentials разделены. API не исполняет полученный текст. Notion не получает низкоуровневые события; страницы строятся из детерминированных агрегатов и структурированных отчётов. Publisher один на хранилище (process lock); ambiguous create проверяется запросом стабильного Chronicle Key и откладывается для reconciliation, а не повторяется вслепую.

## Официальные источники

- https://developers.openai.com/plugins/build/plugins — portable `plugin.json`, `extensions.com.openai`, legacy overlay, marketplace.
- https://learn.chatgpt.com/docs/hooks — wire inputs, доверие, ограничения, все 10 требуемых событий + PreToolUse.
- https://learn.chatgpt.com/docs/cli/reference — `codex plugin marketplace add`, `codex plugin add`.
- https://developers.notion.com/reference/create-a-database — initial_data_source.
- https://developers.notion.com/reference/query-a-data-source — query по data_source_id.
- https://developers.notion.com/reference/request-limits — 429/529, Retry-After и reconciliation записи.

API Notion фиксируется на версии 2026-03-11; версия задаётся конфигурацией. Не использовать устаревший databases/{id}/query.

## Границы поддержки

Shell hooks: local orchestration, CLI/desktop, scripts должны находиться на машине исполнения. Cloud orchestration не поддерживает эти shell hooks. Плагин с hooks не предназначен для public directory. Доверие hooks пользователь подтверждает в Codex; установщик его не обходит. `async` не используется для durable capture: незавершённые background hooks отменяются при закрытии. SessionEnd ограничен 3 секундами. Windows использует commandWindows и отдельную установку Python; WSL — Linux установка внутри WSL. Реальная совместимость Windows не считается проверенной Linux-тестами.

Нет стабильного официального transcript API: backfill поддерживает только экспорт Chronicle JSONL v1 с отдельным согласием. Скрытые рассуждения не читаются. Автоматическая наблюдаемая сводка гарантируется обработкой событий; содержательные объяснения зависят от явно отправленного MemoryReport. Hook не запускает несуществующий agent/prompt handler и не принуждает модель к скрытому отчёту.

## FIP v1 extension (0.2.0)

ADR-0004 adds native fip_records/fip_operations tables beside the original event log, MemoryService and independent REST/MCP adapters. Contracts/schemas/compatibility are documented in docs/API.md and contracts/fip/v1/README.md. No Notion dependency on the read/write path. Legacy events are projected read-only. New FIP ledger has its own receipt sequence; there is no total ordering across both ledgers. New content is Notion opt-in via fip_notion_projects.


## Продолжение 2026-10-19

Применён ADR 0005: существующий Notion root задаётся отдельным NOTION_PARENT_PAGE_ID; прежний container-parent сохраняет старую семантику. Оба транспорта используют одно MemoryService; четыре дополнительные операции не меняют старые закрытые формы FIP. Local Compose не требует домена и публикует только loopback. Контракт называется Forge Interoperability Protocol; wire v1 и package 1.0.0 сохраняются. Минорные расширения добавляют методы/независимые definitions, несовместимые формы идут в v2. Полный текущий статус — ../ACCEPTANCE_STATUS.md.
