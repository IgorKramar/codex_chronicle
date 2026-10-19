# Установка и эксплуатация

## Поддерживаемые окружения

Python >=3.11, Git необязателен, Codex с command lifecycle hooks и plugin CLI. Проверена установка на Linux с Codex 0.159.2. Форматы сверены с официальными спецификациями, перечисленными в ARCHITECTURE.md. Windows и WSL имеют установочные пути, но требуют отдельной реальной приёмки. Shell hooks при cloud orchestration недоступны: эту поверхность нельзя покрыть данным plugin. Поддерживаемая поверхность — local orchestration с локальными scripts. Публичный directory не принимает hooks plugins; используйте personal/team marketplace.

`chronicle install` создаёт только собственный marketplace в `~/.chronicle/marketplace`, затем вызывает штатные Codex команды. Manifest ссылается на `hooks/hooks.json`. Hook definitions требуют отдельного доверия в Codex; установщик не меняет trust store. Для обновления переустановите wheel и выполните `chronicle install`, затем снова проверьте изменённые definitions. Python venv нельзя удалять после установки.

## Worker и автозапуск

SessionStart атомарно сохраняет событие и запускает worker как detached process. OS lock допускает только один worker на CHRONICLE_HOME; дубли завершаются. Hook не ждёт worker/сети/Git. Ошибки возвращают `{}` и exit 0. Ошибка записи отражается content-free флагом hook-error.json. При заполненном диске гарантировать сохранение невозможно; doctor должен контролироваться оператором.

Для автозапуска после reboot и доставки очереди до следующей сессии:

```bash
mkdir -p ~/.config/systemd/user ~/.config/chronicle
# Скопируйте deploy/chronicle-agent.service в ~/.config/systemd/user/.
# Замените /ABS/PATH на абсолютный путь chronicle из вашего venv.
systemctl --user daemon-reload
systemctl --user enable --now chronicle-agent
```

Файл `~/.config/chronicle/agent.env` (chmod 600) используется для переменных credentials; заполните его локальным редактором или secret manager. Не передавайте ключи в chat. Пользовательская служба запускается после входа; unattended boot требует настроенного администратором user lingering. На WSL используйте systemd, если он включён. Без systemd SessionStart всё равно запускает worker. PowerShell script регистрирует login task CodexChronicleAgent с неограниченной продолжительностью; для удаления используйте `Unregister-ScheduledTask -TaskName CodexChronicleAgent`.

`chronicle agent --once` выполняет один цикл. Постоянный foreground: `chronicle agent`.

Локальный установщик использует `.codex-plugin/plugin.json`: Codex 0.163.0 пропускает hooks portable-пакетов с корневым `plugin.json`. После обновления выполните `chronicle install`, откройте `/hooks` в Codex и проверьте/разрешите только hooks `codex-chronicle@chronicle-local`. Затем начните новую сессию: `SessionStart` должен автоматически запустить worker. Само наличие установленного плагина и отсутствие `hook-error.json` не доказывают вызов hooks.

## Конфигурация

`CHRONICLE_HOME` — отдельный каталог конфигурации/данных (default ~/.chronicle). Идентификатор машины создаётся один раз: не копируйте computer_id между компьютерами. Конфигурация `config.json` не содержит ключей; атомарная запись защищена revision/OS lock. Для ручного редактирования остановите worker, измените JSON локально и запустите worker снова.

| Поле | Default | Назначение |
|---|---|---|
| mode | Standard | Minimal / Standard / Verbose |
| sync_seconds | 60 | Период отправки, batch до 100 событий |
| checkpoint_seconds | 600 | Промежуточное состояние |
| publish_seconds | 600 | Notion aggregation |
| stale_seconds | 1800 | Stale при отсутствии source events |
| retention_days | 90 | Автоочистка подтверждённых локальных событий |
| autostart | true | Запуск worker из SessionStart |
| collector_url | пусто | HTTPS endpoint |
| notion_parent | пусто | Parent page, доступная integration |
| notion_version | 2026-03-11 | Явный Notion-Version header |
| exclude | [] | Корни запрещённых каталогов |

Minimal пропускает tool/subagent events; сохраняет задачи, lifecycle, отчёты. Standard сохраняет безопасные metadata действий. Verbose добавляет размеры входов/выходов, не их содержание. Все режимы исключают source/prompts/stdout/credentials. Spool и детальные события остаются на диске; Notion получает session/turn aggregates. Журналирование само не читает и не отправляет содержание changed files.

Проект default `local`. `export` разрешает отправку его накопленных безопасных событий (включая прошлые записи). `exclude` запрещает новые записи; существующее удаляется отдельно через purge. Не ставьте export рабочим/чужим репозиториям без соответствующего разрешения. Можно держать разные CHRONICLE_HOME/worker для разных trust boundaries.

```bash
chronicle projects --discover /new/directory
chronicle projects --project EXISTING_ID --bind /moved/directory
chronicle projects --project PROJECT_ID --policy local
chronicle projects --project PROJECT_ID --policy exclude
chronicle pause
chronicle resume
```

Без remote Project ID выдаётся локально и сохраняется в bindings. На второй машине сначала зарегистрируйте тот же ID в projects config, затем bind; абсолютный путь не является глобальным ID. Для нескольких remotes или переименования repo используйте bind существующего ID. Путь local worktree наружу не передаётся: экспортируется Worktree ID и безопасные relative changed filenames.

## Standalone Notion

Создайте выделенную internal integration в Notion с Read/Insert/Update content; не нужны user/email/comment capabilities. Поделитесь только целевой parent page с интеграцией. Сохраните `NOTION_TOKEN` через OS secret manager/приватный environment file, используйте ту же переменную в worker process. Ни ключ, ни файл с ним не должны попадать в Git.

```bash
chronicle notion --parent YOUR_SHARED_PARENT_PAGE_ID
# Сначала явно разрешите export нужному проекту.
chronicle notion --publish
```

Будет создана дочерняя CODEX CHRONICLE — Development Observatory. Publisher использует API 2026-03-11, databases initial_data_source и `/data_sources/{id}/query`. Страница Projects record сама является Current State, URL постоянен. Publisher управляет 10 paragraph blocks в записи; добавляйте свои заметки вне этих блоков. Удаление/перестановка managed blocks вызывает диагностическую ошибку, а не уничтожение чужого содержимого. Полный безопасный журнал доступен через API/JSONL, snapshot в Notion ограничен 18k символами; длинные агрегаты могут обрезаться.

Rate: не чаще одного запроса в 0.36 sec, persisted Retry-After для 429/529. Только один publisher на store, PostgreSQL advisory lock поддерживает несколько server processes. Не запускайте независимые Collector stores с одной Notion integration/одними Chronicle Keys: Notion не предоставляет unique constraint.

При потере ответа create сначала ищется Chronicle Key или root/database title под известным parent. Если запись не найдена, но ambiguous fence установлен, автоматическое создание останавливается. Проверьте Notion и права/индексацию. После ручного доказательства отсутствия записи оператор может сбросить соответствующий `notion:uncertain:...` meta flag в DB; сделайте backup перед изменением. Автоматического timeout-сброса нет: он создавал бы риск дублей. 401/403 требуют исправления настройки, не повторного слепого create. Doctor/status показывают обезличенные коды ошибок; секреты и полный error body не логируются.

## Несколько компьютеров и Collector

1. Установите plugin на каждой машине, разрешите hooks; зарегистрируйте и проверьте Project IDs.
2. На сервере создайте grant для каждого Computer ID и разрешённых Project IDs.
3. Доставьте credential file на машину безопасным способом, настройте CHRONICLE_WRITE_TOKEN локально.
4. Настройте HTTPS Collector URL: `chronicle config --collector-url https://chronicle.example.org`.
5. Разрешите export только авторизованным проектам и запустите `chronicle sync`.

Provisioning выполняется офлайн; токен не печатается:

```bash
python scripts/provision.py --auth-file /private/chronicle/auth.json \
  --credential-file /private/chronicle/machine-a.env --computer COMPUTER_ID --project PROJECT_ID
python scripts/provision.py --auth-file /private/chronicle/auth.json \
  --credential-file /private/chronicle/jarvis.env --read-only --project PROJECT_ID
```

`--project` повторяемый. `*` даёт доступ всем проектам — используйте осознанно только для read operators. Write grant проверяет computer_id и project_id. Reader token не может писать, writer не может читать. Для ротации создайте новый grant, обновите agent, удалите старый hash и перечитайте права клиента. Начиная с 0.2.0 auth file перечитывается на каждом запросе, restart не нужен.

## Docker Compose

Публичное развёртывание требует выбранного вами сервера, DNS и разрешения владельца. В данной среде production deployment не запускалось.

Создайте private secrets directory вне repo:

- postgres_password: случайный пароль, через secret manager.
- auth.json: grants от provision.py.
- notion_token: integration token; пустой файл допустим, если Notion пока отключён.

Файлы должны быть доступны UID 10001 (Collector), каталог приватен; проверьте ACL/owner. Compose secrets не являются автоматически encrypted at rest. Защитите диск и backups средствами ОС. Задайте `CHRONICLE_SECRETS_DIR` (absolute path), `CHRONICLE_DOMAIN`, при Notion — `NOTION_PARENT` через локальное окружение. Внутренний PostgreSQL/Collector не публикуются наружу. Caddy выдаёт HTTPS и ограничивает тело запроса. Не выключайте TLS verification.

```bash
docker compose -f deploy/compose.yaml config --quiet
docker compose -f deploy/compose.yaml up -d --build
```

Для среды с корпоративным CA используйте BuildKit `proxy_ca` secret и сохраните proxy/CA policy. Пример локальной сборки: `docker build --secret id=proxy_ca,src=/etc/ssl/certs/ca-certificates.crt -f deploy/Dockerfile -t codex-chronicle:0.2.0 .`. Для runtime outbound HTTPS смонтируйте доверенный CA bundle readonly и задайте SSL_CERT_FILE. Не добавляйте приватные сертификаты/ключи в image layers.

GET /healthz — process liveness, не доказательство доступности Notion/PostgreSQL. `/v1/metrics` и `/v1/computers` требуют scoped read token. Следите за pending, hook-error.json, quarantine, agent-health.json (PID/время), `connection`, `last_error`, `notion:last_publish`, `publisher_error` в store meta. Редактирование/удаление файлов конфигурации требует перезапуска worker при повреждённом JSON.

## Очередь, retention, backup и восстановление

SQLite WAL/FULL + fsync spool. Только acknowledged Event IDs удаляются из outbox. Backoff с jitter сохраняется в SQLite. Network/Notion ошибки не управляют Codex. Неподтверждённые/local-only события защищены от автоматической очистки: ограничивайте диск мониторингом и явной purge policy. Режим durable capture не гарантирует сохранение при отсутствии места/permission denied.

```bash
chronicle export --project PROJECT_ID > safe-events.jsonl
chronicle backfill safe-events.jsonl --consent
chronicle pause
chronicle purge --project PROJECT_ID --include-pending --notion
chronicle resume
```

Backfill поддерживает только Chronicle schema_version=1 JSONL этой машины и зарегистрированных проектов. Codex transcripts не являются стабильным API: их импорт не реализуется через эвристический парсер. Перед purge остановите активные Codex sessions или исключите проект; иначе новые события появятся снова. Purge Notion перемещает записи в trash, не гарантирует физическое удаление у провайдера. Daily/weekly pages архивируются и строятся заново без удалённого проекта. Бэкапы очищаются отдельно по вашей retention policy.

Collector default хранит события без TTL, чтобы не уничтожать shared memory. Для ограниченного retention: регулярный export/backup, затем `scripts/retention.py --days N --confirm` на остановленном Collector. Первичные доказательства старше TTL после этого доступны только в backup; факт удаления фиксируется в meta.

Backups: согласованный `pg_dump -Fc` + publisher metadata volume. Скрипт временно останавливает Collector (перерыв приёма), сохраняет backup и запускает его снова. Используйте `scripts/backup.sh /private/backup.dump` (PostgreSQL остаётся включённым). Он сохраняет database и `.publisher.tar`; metadata включает ambiguous fences. Шифруйте и копируйте backups в отдельное хранилище. Restore — в пустую БД, `scripts/restore.sh /private/backup.dump`; скрипт не удаляет существующую БД автоматически. Локальный SQLite копируйте через sqlite backup API после остановки worker, вместе с config/spool/quarantine и permissions. Никогда не копируйте только events.db при активном WAL.

## Удаление

Сначала остановите/disable user service или Windows task, затем `chronicle pause` и `chronicle uninstall`. Штатные команды удаляют только Chronicle plugin и его marketplace. История, env files и service definitions автоматически не уничтожаются; удалите их явно после export/backup. Другие plugins и hooks сохраняются.

## FIP v1 / MCP extension (0.2.0)

Новые REST/MCP интерфейсы, права и offline delivery описаны в API.md и INTEGRATION.md. Schema changes в старом event store не нужны; дополнительные fip_records/fip_operations создаются автоматически при запуске API. Backup включает обе таблицы. FIP ledger не очищается legacy retention/purge CLI. Pending external-client outbox резервируется отдельно на машине producer. MCP подключается явно и по умолчанию read-only; CHRONICLE_MCP_WRITE_ENABLED=0 также запрещает background flush. Notion для новой FIP памяти требует отдельного CHRONICLE_NOTION_PROJECTS allowlist.
