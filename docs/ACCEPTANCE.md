# Приёмка 0.1.0

Предварительная реализация, не stable release. «Реализовано» не означает «подтверждено во всех ОС/реальных сервисах».

| Требование | Реализация / evidence | Состояние |
|---|---|---|
| Официальный plugin manifest, marketplace, hooks | plugin/, install.py, установлен CLI 0.159.2 | Установка подтверждена; реальный lifecycle E2E блокирован авторизацией |
| Все 10 событий + PreToolUse | hook schema/unit tests | Wire boundary проверен; реальная доставка от Codex пока не подтверждена |
| Глобальное включение после доверия | официальный plugin add; SessionStart autostarts daemon | Установка и autostart hook subprocess проверены; trust подтверждает пользователь |
| Несколько машин/проектов | two-computer HTTP E2E, scoped identity | Проверено синтетическими hook inputs |
| Один remote = один Project ID, worktrees distinct | canonical_remote, bind, unit tests | Проверено алгоритмически; две физические машины не использованы |
| Offline, restart, reconnect, lost ACK | SQLite/FULL, spool, outbox, replay E2E | Проверено |
| Долгие сессии, промежуточные checkpoint | periodic agent; Stale без ложного Completed | 13h history смоделирована; настоящий 12h+ soak не выполнен |
| Быстрые hooks, no network critical path | synchronous atomic spool; load-probe.json | p95 измерен локально; сквозной overhead реального Codex не измерен |
| Секреты/privаcy, exclude, project policies | allowlist + redaction; no source/prompts/stdout | Предусмотренные unit/E2E сценарии пройдены; фильтры не универсальный DLP |
| Collector HTTPS/auth/OpenAPI | Compose Caddy, project+machine grants, read/write separation | Collector/PostgreSQL/Compose проверены локально; публичный HTTPS deployment не выполнен |
| PostgreSQL concurrency/global order | transaction advisory append lock, immutable events | Реальный PostgreSQL тест пройден; sequence не gapless |
| Backup/restore | pg_dump/pg_restore + metadata | Реальный restore и duplicate replay пройдены, Compose backup пройден |
| Notion root + семь баз | versioned REST publisher + mock contract | Mock пройден; dedicated integration не настроена |
| Notion create/update/search/reconciliation | Chronicle Key, uncertain fences, rate limit, singleton | Mock timeout-after-commit/restart и Retry-After пройдены; real API ещё не проверен |
| Current State stable URL, JSON memory | project record URL, state API, русский renderer | Mock idempotence/API пройдены; реальный UI review ожидается |
| ADR history/proposals/conflicts | report schema, immutable revisions, conflicts | Проверено; принятие решения остаётся agent_reported |
| Issues identity/references | project-scoped issue ID, decision_ids | Проверено; автоматический semantic merge не выполняется |
| Daily/weekly reports | UTC periods, previous-period comparison, русский текст | Mock/unit пройдены; event delta не completion KPI |
| Автоматическая содержательная память | SessionStart instruction + chronicle-memory; deterministic observed summary | Наблюдения автоматические; исполнение model skill не гарантируется runtime |
| Все CLI команды | cli.py + дополнительные agent/memory/export/purge/config/notion/serve | Базовые CLI/install проверены; OS service lifecycle требует целевой машины |
| Backfill с согласием | только Chronicle JSONL v1 | Codex transcript import сознательно не поддерживается: нестабильный API |
| Linux/Windows/WSL | stdlib runtime, commandWindows, PowerShell task, systemd | Linux проверен; Windows/WSL и CI matrix не запускались в этой среде |
| Удаление/retention | purge, Notion trash, local ack TTL, collector retention script | Реализовано; provider physical deletion не гарантируется |
| Развёртывание и документация | Compose/image, operations, ChatGPT guide | Image/локальный Compose проверены; production target не задан |

## До stable

1. Восстановить валидную авторизацию Codex на целевых машинах и повторить scripts/real_codex_e2e.py. Проверить именно plugin hooks, а не только hand-fed hook boundary.
2. Настроить dedicated Notion integration через защищённое локальное окружение и parent page; выполнить live test и пользовательский UI review.
3. Прогнать Windows, WSL, Python 3.11 matrix и OS autostart/reboot.
4. Выполнить настоящий 12h+ soak с несколькими компьютерами, abrupt power/process loss и долгими tool calls, а также измерить относительное замедление Codex.
5. Выбрать production server/DNS, получить необходимые права развёртывания, настроить credentials/CA/backup retention и выполнить HTTPS acceptance.
6. Провести дополнительный security review на реальных политиках рабочих репозиториев перед разрешением export.

SessionEnd не содержит result status в проверенной документации (`reason=other`). Поэтому автоматический итог закрытой сессии Unknown. Completed/Failed не выводятся из closure/Stop/exit отдельной команды. Текущая версия не устанавливает эти два статуса сессии без отдельного подтверждённого источника; общие итоги остаются в agent_reported report.
