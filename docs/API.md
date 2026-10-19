# Chronicler Open API — FIP v1

Chronicler — самостоятельный сервис памяти в Codex Chronicle. Notion — необязательная projection. Все данные читаются из локального/серверного Store + FIP ledger; запросы API не обращаются к Notion.

Контракт: [JSON Schema](../contracts/fip/v1/README.md), [bundle](../contracts/fip/v1/fip.schema.json), [OpenAPI 3.1](openapi.json). Ранее существовавшие Chronicle endpoints сохранены. Новые FIP responses не подменяют старые JSON shapes.

## Авторизация и границы

Каждый HTTP запрос требует Bearer credential. Значения токенов никогда не передаются в query/path. API по умолчанию слушает `127.0.0.1:8787`; наружу его открывает только явно настроенный deployment/reverse proxy с HTTPS. CLI/MCP не открывают слушающий порт.

| Scope / grant | Значение |
|---|---|
| read | Чтение только перечисленных projects |
| write | Новые записи/свои допустимые ревизии |
| decide | Принятие и изменение ранее принятого решения, дополнительно к write |
| verify | verified knowledge и изменение ранее verified record, дополнительно к write |
| revise | Ревизии другого автора, дополнительно к write и нужным специальным scopes |
| observe | Явно доверенная attestation наблюдений; не давать обычному внешнему агенту |
| principal_id | Стабильная identity, сохраняется при ротации credential |
| agent_id | Идентичность автора; все вложенные записи должны совпадать |
| projects | Явный project allowlist, personal/work разделяются grants; `*` — осознанное расширение |
| allow_content=true | Явное разрешение FIP writes безопасного содержательного отчёта в эти проекты |

Read-only token не пишет; write-only token не читает историю. Нет автоматического получения прав на рабочие репозитории. Default Codex capture не изменён: исходники, полный prompt, stdout, transcripts не выгружаются. FIP schemas закрыты, произвольные payload/source_code не принимаются, известные секреты редактируются до записи. Это не универсальный DLP: не включайте приватное содержимое в текст отчёта без разрешения владельца.

Grants загружаются из CHRONICLE_AUTH_FILE на каждом запросе; revoked/expired credentials не работают. При повреждении файла доступ закрыт (503). Ротация: добавьте новый hash для того же principal_id/agent_id, доставьте новый secret локально, затем отзовите старый hash. Already authenticated in-flight request может завершиться; отзыв действует со следующей проверки.

## HTTP endpoints и MCP operations

HTTP и MCP вызывают один MemoryService, а не два набора бизнес-правил.

| Operation | HTTP | Result |
|---|---|---|
| get_capabilities | GET /v1/capabilities | CapabilityDescriptor |
| list_projects | GET /v1/memory/projects | ProjectContext page |
| get_project_state | GET /v1/memory/projects/{project_id}/state | Compact ProjectContext |
| get_project_history | GET /v1/memory/projects/{project_id}/history | AgentEvent page |
| list_sessions | GET /v1/memory/sessions | AgentSession page |
| get_session_details | GET /v1/memory/projects/{project_id}/sessions/{session_id} | One AgentSession |
| search_knowledge | GET /v1/memory/search | KnowledgeRecord page |
| get_decisions | GET /v1/memory/projects/{project_id}/decisions | DecisionRecord revisions |
| get_failures | GET /v1/memory/projects/{project_id}/failures | Failure AgentEvent page, including derived failed test events |
| get_artifacts | GET /v1/memory/projects/{project_id}/artifacts | ArtifactReference page |
| get_test_results | GET /v1/memory/projects/{project_id}/test-results | TestResult page |
| append_event | POST /v1/memory/events | Accepted immutable record ID/revision/sequence |
| register_decision | POST /v1/memory/decisions | Accepted revision |
| register_artifact | POST /v1/memory/artifacts | Accepted revision |

Evidence resolver: GET `/v1/memory/projects/{project_id}/records/{record_id}` returns RecordLookupResponse. Read scope and project scope are checked. It never reads an artifact URI or executes supplied text. Use it to follow evidence/source_event_ids rather than trusting a summary.

## Envelopes, sizes и pagination

Общие поля описаны в contracts/fip/v1/README.md. Responses содержат api_version=v1, request_id, project_id (null для списка разных проектов), timestamp UTC, status, artifact_refs, evidence. Корреляционный request_id не является ключом идемпотентности.

Read filters зависят от метода; неизвестные параметры отклоняются (422). Поддерживаются project_id/session_id/agent_id/category/status/since/until там, где соответствующие поля применимы. `since`/`until` включительные и сравнивают source timestamp; у сессии это last_activity. Статусы case-sensitive, точные enum — в schemas. Полный список параметров находится в OpenAPI и `<operation>Arguments.schema.json`.

Paged result:

```json
{"data":{"items":[],"next_cursor":null,"has_more":false,"snapshot":"opaque"}}
```

Это фрагмент полного FIP envelope. Default limit=20, maximum=100. Default/hard response budget=131072 UTF-8 bytes, request max_response_bytes может уменьшить его до 8192. Сервер может вернуть меньше limit, чтобы уложиться в byte budget. Если даже одна запись не помещается, возвращается 413, без тихого обрезания данных. get_project_state/get_session_details возвращают один bounded object. LLM summary ограничена 12000 символами, source_ids — 100; вся история доступна отдельным методом.

Передавайте next_cursor с теми же методом/фильтрами/identity/permissions. Cursor фиксирует high-water marks обоих хранилищ и время legacy session projection. Новые append не появляются в текущем обходе; начните новый обход без cursor. Cursor не является правом доступа и не является подписанным security token: каждый запрос отдельно авторизуется. Не редактируйте cursor. Retention/административное удаление может инвалидировать старый обход.

Native FIP records ordered by ledger receipt sequence. Совместимая выдача legacy: сначала legacy projections, затем FIP ledger, затем deterministic derived projections. Общего total order между двумя ledger нет. Source timestamp не является доказательством порядка между компьютерами. GET history сохраняет source IDs; native write ACK содержит FIP sequence. Поддержка единого cross-ledger ordering потребует отдельной согласованной эволюции, существующие события не переписываются.

## Поиск

`search_knowledge(query=...)`: Unicode casefold, затем split по whitespace, от 1 до 8 terms по 2–64 символа. Каждый term должен быть substring в объединённом title/text. Для решений создаётся derived KnowledgeRecord с problem/choice/rationale/consequences. Все terms обязательны (AND). Нет embeddings, semantic similarity, stemming, transliteration, quotation syntax или relevance ranking. Результаты имеют стабильный source order и обычный cursor.

Поиск видит только разрешённые проекты. Он включает native KnowledgeRecord и read-only projections событий, решений и тестов. Derived record не является новым первичным доказательством: следуйте source_event_ids/evidence. get_decisions по умолчанию возвращает все ревизии, включая Rejected/Superseded; чтобы определить актуальную native entity, следуйте revision/supersedes, не выбирайте произвольный Accepted record из прошлого.

## Запись и идемпотентность

POST body — соответствующий AgentEvent/DecisionRecord/ArtifactReference, обязательный header `Idempotency-Key`. MCP arguments — `{record, idempotency_key}`. FIP-Version header необязателен, default v1; unsupported header/version отклоняется (426). X-Request-ID можно использовать для read/error correlation.

```http
POST /v1/memory/events
Authorization: Bearer <locally configured credential>
FIP-Version: v1
Idempotency-Key: forge-experiment-001
Content-Type: application/json
```

Body: [experiment.http-body.json](../contracts/fip/v1/examples/experiment.http-body.json). Полные [request/response examples](../contracts/fip/v1/examples/) провалидированы schemas и реальным библиотечным core. Это synthetic format examples, не результаты настоящей игры.

Запись records и response/idempotency digest выполняется в одной транзакции. Повтор principal_id + operation + key + тот же body возвращает тот же ACK, в том числе после restart/потери ответа. Другой body с тем же key — 409. Сохраняйте body целиком, включая request_id/timestamp, до подтверждения; не генерируйте их заново на retry. Идемпотентность не заменяет текущую авторизацию.

Public write body ограничен 64000 UTF-8 bytes. AgentEvent может атомарно включить до восьми KnowledgeRecord и восьми TestResult плюс session/project_context. Все они должны принадлежать тому же project_id/authorized agent_id. Source/evidence links проверяются на существование и scope. Artifact URI допускает HTTPS/URN без credentials, query и fragment; SHA256 — заявленный checksum, сервер не скачивает контент для его подтверждения.

Первая ревизия entity: revision=1, supersedes=null, новый record_id. Следующая: revision=N+1 и supersedes=record_id последней ревизии. Одновременный update одного predecessor: один успех, остальные 409. История остаётся доступной. AgentEvent никогда не редактируется. Изменение status Accepted/verified не превращает текст в статистическое доказательство; provenance сохраняется.

## Offline delivery

Raw REST клиент должен иметь собственный durable outbox. Поставляемый FipClient/MCP делает это автоматически: фильтрует/валидирует body, сохраняет его в SQLite FULL до network call, поддерживает backoff/Retry-After и доставку в порядке очереди. Восстановление после restart использует те же keys. Если запись не подтверждена сервером, результат `status=queued`, `accepted=false`, а не фиктивный успех.

401/403/409/422/413 — blocked retained row, требует исправления credentials/прав или review; временные network/408/429/5xx/529 — pending retry. Blocked head останавливает зависимые записи. После исправления причины `chronicle fip-sync --retry-blocked --force` повторяет те же тела, не подменяя историю. `acknowledged` — подтверждения данного flush, `delivered` — общий локальный count. MCP периодически flush при работающем процессе; после его закрытия очередь остаётся на диске. Для unattended доставки используйте CLI timer/service.

## Ошибки и совместимость

ApiError: stable code/message/retryable; 401 unauthorized, 403 forbidden, 404 unknown or inaccessible, 409 immutable/idempotency/revision conflict, 413 budget, 422 invalid schema/reference/test claim, 426 version mismatch, 503 transient unavailable. Внешние stack traces и secret values в ответ не включаются. После 409 получите актуальную entity history и создайте новую явно согласованную ревизию с новым key; не подменяйте старый запрос.

V1 shapes frozen; новые optional поля/enum members тоже требуют v2 из-за strict validators. Новые methods/definitions — additive через get_capabilities. Compatibility checker и contract tests входят в CI. OpenAPI и schemas не означают, что все старые acceptance gaps исчезли: реальные Codex auth/Notion/Windows/WSL/12h soak остаются отдельной приёмкой.
