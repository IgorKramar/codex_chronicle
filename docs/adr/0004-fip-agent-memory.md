# ADR-0004: FIP v1 agent memory and transport adapters
Status: Accepted. Date: 2026-10-19.

Контекст: WORLD FORGE и другие агенты должны читать/пополнять память независимо от Codex и Notion.
Решение: additive FIP v1 contracts + transport-independent MemoryService, новые append-only таблицы records/operations. Legacy hooks/outbox и маршруты сохраняются. Public FIP REST: /v1/memory; capability discovery: /v1/capabilities. MCP stdio server — адаптер того же service через HTTP client с durable write outbox; не получает доступ к внутренней БД и не публикует listener. HTTP bind остаётся loopback.

Публичные schemas: JSON Schema 2020-12, OpenAPI 3.1. Schemas v1 фиксированы; совместимое развитие через новые методы, отдельные definitions и объявленные capabilities. Breaking shape/enum/required changes требуют v2. Confidence — словесная оценка с обоснованием, не вероятность.

Write grants привязаны к stable principal_id и agent_id, projects и явному allow_content=true. read/write/decide/verify/revise — отдельные scopes. Принятые решения/verified records требуют соответствующих прав; чужие ревизии требуют revise. История immutable. Token file перечитывается на каждом запросе для отзыва/ротации без restart.

Idempotency key обязателен, проверяется в одной transaction с append и сохранением ответа. Повтор с другим содержимым — 409. Ревизии требуют expected predecessor и следующий revision. Server не выдаёт agent claims за observed facts. Primary evidence references проверяются на существование и project scope. Offline client сохраняет очищенный запрос до попытки отправки; queued означает локальное сохранение, а не server acceptance.

Поиск: casefold substring AND по whitespace terms в разрешённых текстовых полях; без embeddings/ranking/stemming. Cursor включает snapshot high-water marks и fingerprint фильтра/прав; cursor не является авторизацией. Все ответы имеют byte cap и page cap. Notion — optional projection, не dependency чтения/записи.
