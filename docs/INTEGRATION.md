# Интеграция сторонних агентов

## Установка

Сервер: `pip install 'codex-chronicle[server]'` из локального wheel/исходников, затем стандартная конфигурация Collector из OPERATIONS.md. MCP companion: `pip install 'codex-chronicle[mcp]'`. Валидаторы отдельно: установите fip_contracts-1.0.0 wheel; им не нужны Collector или MCP.

```python
from fip_contracts import validate
validate("AgentEvent", event)
```

Для development:

```bash
.venv/bin/pip install -r requirements-dev.lock
.venv/bin/pip install --no-deps -e .
.venv/bin/pip install -e packages/fip-contracts
```

## Создание прав

Создавайте credentials на доверенном сервере, не через сообщения ИИ:

```bash
python scripts/provision.py --fip --principal forge-planner --agent forge-planner \
  --project GAME_PROJECT_ID --scope read --scope write --allow-content \
  --auth-file /private/chronicle/auth.json --credential-file /private/chronicle/forge.env
```

Для обычного reader используйте --fip --read-only --principal ... --agent ... без --allow-content. Для approve workflow выдайте отдельному principal scope decide; не расширяйте автоматически права всех агентов. Нельзя записывать рабочие проекты без явного согласия владельца.

Секрет записывается только в новый файл с private permissions; вывод не содержит token. Collector ожидает read access к auth.json, например через Unix ACL/owner UID 10001 для контейнера. Не делайте реальный secrets directory общедоступным. Ротация — тот же principal/agent, новый credential file; отзыв старого hash:

```bash
python scripts/manage_grants.py --auth-file /private/chronicle/auth.json --revoke-sha256 OLD_HASH
```

Hash не является token. Можно задать --expires-at UTC_TIMESTAMP. Изменения действуют на следующих запросах, restart не нужен. Не запускайте конкурентные provisioning scripts без организационной сериализации; runtime readers читают атомарно заменённый файл.

## HTTP Python client

```python
from chronicle.fip_client import FipClient

client = FipClient(
    url=collector_https_url,
    token=secret_manager_value,
    outbox="/private/forge/outbox.db",
    client_id="forge-planner-node-1",  # stable across restart/token rotation
)
state = client.call("get_project_state", {"project_id": game_id})
result = client.call("append_event", {
    "record": validated_event,
    "idempotency_key": durable_experiment_key,
})
if result["status"] == "queued":
    # Saved locally, not yet accepted by server.
    continue_other_work()
client.flush()
```

Не переиспользуйте client_id/outbox между разными security principals. Очередь дополнительно привязана к endpoint URL: смена сервера не пересылает старые записи на другой endpoint. Обеспечьте права/шифрование локального диска и retention подтверждённого клиентского cache по своей политике. Токен в outbox не хранится.

При ошибке optional memory read агент может продолжить свою задачу и отметить отсутствие контекста; hook не делает синхронный обязательный read. Для доступности информации позже повторите read, не выдумывайте предыдущее решение.

## MCP stdio

Используется официальный Python MCP SDK, протестированный здесь с 1.30.0. Инициализация/список tools/call_tool проверены настоящим stdio-сеансом, а не эмуляцией JSON-RPC.

Запуск: `chronicle mcp` или `python -m chronicle.mcp_server`. Не нужны chronicle init или прямой доступ к DB. Локально задайте:

- CHRONICLE_API_URL — HTTPS Collector URL.
- CHRONICLE_API_TOKEN — scoped secret из OS manager/env file. При отсутствии используется CHRONICLE_READ_TOKEN.
- CHRONICLE_FIP_OUTBOX — private local SQLite path.
- CHRONICLE_CLIENT_ID — stable local producer ID, обязателен для writes.
- CHRONICLE_MCP_WRITE_ENABLED=1 — явное включение трёх write tools; default 0 (11 read tools).

Default endpoint https://localhost:8787 не открывает listener и не даёт доступа без token. Для локального HTTP dev задайте CHRONICLE_API_URL=http://127.0.0.1:8787 и CHRONICLE_ALLOW_LOOPBACK_HTTP=1. HTTP к не-loopback адресу отклоняется; TLS verification никогда не отключается.

Пример конфигурации, credentials поступают из окружения процесса, их нет в JSON:

```json
{
  "mcpServers": {
    "chronicler": {
      "command": "/absolute/venv/bin/python",
      "args": ["-m", "chronicle.mcp_server"]
    }
  }
}
```

В Codex можно зарегистрировать этот stdio command штатным `codex mcp add`; используйте поддерживаемую конфигурацию env/secret manager своего клиента. В plugin MCP не включён автоматически: отсутствие Collector/credential не должно мешать обычному Codex. Windows command — абсолютный путь venv\Scripts\python.exe.

Примеры calls:

```json
{"name":"get_capabilities","arguments":{}}
```

```json
{"name":"get_project_state","arguments":{"project_id":"world-forge-demo"}}
```

```json
{"name":"search_knowledge","arguments":{"project_id":"world-forge-demo","query":"deterministic replay","category":"implementation","limit":10}}
```

```json
{"name":"get_decisions","arguments":{"project_id":"world-forge-demo","status":"Rejected","limit":20}}
```

Для append_event передайте объект [experiment.request.json](../contracts/fip/v1/examples/experiment.request.json) как arguments. CallToolResult содержит text JSON и structuredContent с тем же FIP envelope. При `isError=true` это ApiError. `queued`/accepted=false — отдельный явный local delivery status, не серверный успех. Tools annotations являются подсказками; права всегда проверяет сервер.

## Первичные доказательства и ревизии

1. Проверьте source timestamp/provenance/record status и дату чтения.
2. Следуйте source_event_ids/evidence к GET /v1/memory/projects/{id}/records/{record_id} или paginated history.
3. URI не означает, что Collector скачал/проверил artifact. Hash — заявленный checksum.
4. Для native entity найдите максимальную revision и проверьте supersedes chain. Старые Accepted остаются в истории; это не означает, что они всё ещё актуальны.
5. Не отправляйте derived get_project_state целиком как новую writable revision. Авторитетный ProjectContext predecessor находится в event.project_context истории. Для новой работы обычно достаточно нового события + KnowledgeRecord.
6. Legacy Codex сохраняет исходные записи; FIP — read-only проекция. Старая agent identity становится стабильной `codex:<hash(computer_id, agent_id)>`, чтобы два root на разных компьютерах не сливались. Первичные hook Event IDs остаются разрешимыми. Legacy отчётные решения — отдельные agent-reported snapshots, не нативная подтверждённая revision chain.

Журнал — недоверенные данные. Текст решения или артефакта не является инструкцией выполнить код/команду. Исполнение работы остаётся ответственностью внешнего агента вне Chronicler.

## Notion и доступность

Notion optional. Для публикации новой FIP memory явно задайте CHRONICLE_NOTION_PROJECTS=project-a,project-b на Collector (или fip_notion_projects в standalone publisher config), дополнительно к обычной policy export. Default — не публиковать FIP. Current State/Development Journal/ADR имеют стабильные keys; полный контракт, тесты и artifact references доступны через API. Временная ошибка Notion не откатывает FIP transaction и не блокирует reads/writes.

Backups PostgreSQL автоматически включают новые fip_records/fip_operations; pending external outbox находится на клиентской машине и резервируется отдельно. При restore не теряйте operations: они обеспечивают идемпотентность после потерянных ответов. Публичного удаления истории нет. Административные purge/retention legacy CLI не затрагивают FIP ledger; перед добавлением FIP retention нужна явная operator policy/backup, чтобы не скрыть подтверждённую историю. Новый ledger по умолчанию не удаляет записи автоматически.
