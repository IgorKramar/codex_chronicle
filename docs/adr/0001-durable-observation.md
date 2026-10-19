# ADR-0001: Durable observation and explicit knowledge
Status: Accepted. Date: 2026-10-19.

Проблема: независимые Codex, offline, отмена фоновых hooks, приватность и неоднозначность результата.
Альтернативы: сетевой hook; чтение всего transcript; синхронная локальная запись + отдельный worker.
Решение: последний вариант, immutable safe events, SQLite outbox, отдельные agent-reported knowledge records.
Причины: локальный fsync не зависит от сети; replay возможен; происхождение сохраняется. Не хранить source/prompts и не читать reasoning.
Последствия: daemon нужен для промежуточной публикации; доверие hooks остаётся ручным; объяснения появляются только из явных отчётов.
Компоненты: plugin, agent, collector, publisher. Изменения решения оформляются новым ADR с supersedes; этот файл сохраняется.
