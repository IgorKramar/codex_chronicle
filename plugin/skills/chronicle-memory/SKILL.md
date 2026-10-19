---
name: chronicle-memory
description: Save concise Russian project memory after a meaningful development stage, completed turn or before compaction, using explicit evidence.
---

Сохраните краткий структурированный отчёт в Codex Chronicle после значимого этапа.
Не читайте hidden reasoning, .env, credentials, SSH keys или полные transcripts.
Не публикуйте source, полные промпты, приватные данные. Наблюдения отделяйте от объяснений.
Работайте только с доказательствами текущей сессии. Не называйте тест успешным по факту запуска.
Вывод инструмента с session_id означает, что выполнение ещё может продолжаться.

1. Выполните `chronicle projects` и выберите зарегистрированный Project ID.
2. Создайте временный JSON с полями:
   Task: string; Actions: array; Changes: array; Decisions: array; Evidence: array;
   Problems: array; Next Steps: array; Confidence: string.
3. Decision содержит id, status (Proposed/Accepted/Superseded/Rejected), problem,
   alternatives, choice, rationale, consequences; components и supersedes при наличии.
   Принятие решения должно быть явно подтверждено. Сохраняйте id при ревизии.
4. Problem содержит id, type (Bug/Limitation/Discovery/Improvement/Research/Technical Debt),
   title, status (Open/Resolved); decision_ids при наличии. Используйте существующий id.
5. Evidence: Event ID / commit SHA / путь тестового отчёта + фактический результат.
   Агентское утверждение в Evidence остаётся agent_reported, пока не проверен источник.
6. Выполните `chronicle memory --project PROJECT_ID --session SESSION_ID --file REPORT.json`.
   Session ID берите из контекста окружения, не выдумывайте. Если неизвестен — ограничьтесь
   наблюдаемым автоматическим журналом, сообщите об отсутствии ID.
7. Удалите временный файл. Не вызывайте sync для проекта без разрешённой export policy.

Пишите по-русски, оставляйте команды, имена API и пути без перевода. Если чего-то не знаете,
укажите «Не подтверждено». Не заменяйте отсутствие evidence уверенностью формулировки.
Неполный/неудачный отчёт не должен мешать основной задаче Codex.
