# WORLD FORGE → Chronicler FIP v1

WORLD FORGE ещё не подключён как реальная система. Этот документ и проверенный cross-agent test задают рабочий интеграционный контракт; Ludascope/Universal Modder/Compound Engineering не объявляются уже реализованными адаптерами.

## Границы компонентов

| Producer / consumer | Что читает | Что регистрирует |
|---|---|---|
| WORLD FORGE planner | ProjectContext, accepted/rejected decisions, failures | game_design/architecture proposals, project_context |
| Ludascope adapter (future) | mechanics/experiment history | experiment events, simulation ArtifactReference, TestResult |
| Universal Modder adapter (future) | implementation constraints and artifact links | implementation knowledge, build/test references |
| Compound Engineering adapter (future) | repeat failures, rejected alternatives, source evidence | discovery/architecture knowledge, Proposed decisions |
| Reviewer / следующий агент | bounded context, actual sources | approval via separate decide scope, explicit revisions |

Chronicler хранит память, не оркестрирует эти системы и не исполняет их код. Внешний game_id сопоставляется с устойчивым project_id; не используйте абсолютный path компьютера как глобальную identity. Разные games/private/workspaces изолируются server grants.

## Рабочий цикл

1. `get_capabilities` — подтвердить v1, поддерживаемые tools, категории и limits.
2. `get_project_state(game_id)` — current goal, заявленные mechanics implemented, open questions, llm_summary/source_ids.
3. `get_decisions(project_id, category="game_design")` и architecture; просмотреть все revision/supersedes, явно отличать Proposed/Accepted/Rejected.
4. `get_project_history`/`search_knowledge(category="experiment")` и `get_test_results` — прошлые симуляции. Поиск lexical AND; похожая формулировка не гарантирует, что результат будет найден. При необходимости перечислите историю по category и просмотрите её.
5. `get_failures` и Rejected decisions — не повторять известный эксперимент без понимания причин. Повторяющиеся ошибки группирует ваш агент по evidence и содержанию: semantic clustering в Chronicler не реализован.
6. Выполнить свою работу вне памяти. Фиксировать source commands/artifact outputs в собственной безопасной инфраструктуре, передавать в память краткий результат.
7. `append_event` с category=experiment/implementation/failure и вложенными KnowledgeRecord/TestResult. Один durable idempotency key на неизменяемый результат; не объявлять completed/Passed при одном факте запуска.
8. `register_artifact` — URI на реализацию, simulation result или test report + SHA256 при наличии + source_event_ids. Не вставлять полный репозиторий/логи/credentials в text.
9. Следующий агент ищет KnowledgeRecord, читает TestResult/ArtifactReference, разрешает source event через API. Нельзя выдавать один пересказ за независимое доказательство.

Все внешние сообщения по умолчанию agent_reported. Schema запрещает Passed с незавершённым execution_status или противоречащим exit_code, но не доказывает, что внешний агент честно запустил тест. Для доверенного CI producer используйте отдельный observe grant, не повышайте таким образом обычный planner.

## Форматы

[bootstrap.request.json](../contracts/fip/v1/examples/bootstrap.request.json) — проектный контекст.
[decision.request.json](../contracts/fip/v1/examples/decision.request.json) — Proposed game design decision.
[experiment.request.json](../contracts/fip/v1/examples/experiment.request.json) — эксперимент + implementation memory + test.
[artifact.request.json](../contracts/fip/v1/examples/artifact.request.json) — ссылка на реализацию.
[get_project_state.response.json](../contracts/fip/v1/examples/get_project_state.response.json) — bounded LLM context.

Это synthetic examples, не реальная игра или настоящие результаты Ludascope. Большие числовые simulation outputs должны храниться как artifacts в авторизованном хранилище; text summary + evidence остаётся в Chronicler.

## Межагентный сценарий — выполненная проверка

`tests/test_world_forge_integration.py` запускает настоящий loopback HTTP Collector с отдельными planner/reviewer credentials. Planner через HTTP читает history/Accepted decision, выполняет Python experiment (100 deterministic replay ticks), публикует событие/knowledge/test/artifact. Другой process через официальный MCP stdio SDK находит результат и ссылки; primary event затем читается через защищённый evidence endpoint. Прямого доступа к БД или Notion у обоих клиентов нет.

```bash
.venv/bin/pytest -q tests/test_world_forge_integration.py
```

Отдельно проверены offline restart/lost ACK, revision races, read/write separation, cross-project denial, rollback всего события при недопустимом nested TestResult, Notion outage, grant rotation/revocation и cursor snapshot. PostgreSQL/packaging результаты — evidence/FIP_VALIDATION.md.

## Ограничения v1

- Нет semantic search, embeddings, автоматической идентификации одинаковых bugs или оценки прогресса игры по количеству событий.
- У old/new ledger нет общего total order; source/receipt order оговорены в API.md. Native FIP sequence атомарен и сериализован между writers.
- Context projection краткая, не заменяет историю и primary evidence. Если лимит ответа мал — уменьшайте page size/увеличивайте byte budget.
- Нет автоматического fetch/execute artifact и прямого доступа к private repositories.
- Нет удалённого edit/delete подтверждённой истории. Revisions append-only и контролируются scopes.
- Нет подключённого настоящего WORLD FORGE/Ludascope/Universal Modder instance. Эти адаптеры будут реализованы поверх уже работающего контракта без знания DB/Notion layout.
