# Выпуск и воспроизведение

Источник: https://github.com/IgorKramar/codex_chronicle. Основная рабочая ветка текущей разработки — `master`; исходная `main` сохранена. До смены default branch владельцем клонируйте явно:

```bash
git clone --branch master https://github.com/IgorKramar/codex_chronicle.git
cd codex_chronicle
python -m venv .venv
# Unix: source .venv/bin/activate; PowerShell: .venv\Scripts\Activate.ps1
python -m pip install -r requirements-dev.lock
python -m pip install --no-deps -e .
python -m mypy src/chronicle packages/fip-contracts/src
ruff check src tests scripts packages deploy
ruff format --check src tests scripts packages deploy
python scripts/check_fip_compatibility.py
pytest -q
python -m build
python -m build packages/fip-contracts
```

Версии приложения следуют SemVer. Версия wire API (`v1`) и версия пакета fip-contracts (`1.0.0`) независимы от версии приложения. В patch исправляются ошибки без изменения контрактов. В minor добавляются операции / независимые схемы; клиент проверяет get_capabilities и игнорирует незнакомые имена операций. Уже существующие закрытые схемы сохраняются. Несовместимая форма или семантика требует `/v2` и отдельного каталога; не подменяйте compatibility-baseline.json.

Перед выпуском согласованно обновите pyproject.toml, __version__, manifests и runtime assets; проверьте CHANGELOG, locks, OpenAPI и контрактный пакет, выполните чистую установку wheel и сборку контейнера. Секреты, базы и частные логи не включаются. В Git создаётся аннотированный тег; например предварительный `v0.3.0-alpha.1`. Публикация GitHub Release выполняется после проверок через `gh release create TAG --prerelease --notes-file RELEASE_NOTES.md dist/...`. Не публикуйте stable до закрытия ACCEPTANCE_STATUS.md. В release notes обязательны изменения, Python 3.11+, инструкции установки и фактические ограничения. Автоматического выпуска stable на push нет.

CI проверяет Linux/Windows × Python 3.11/3.12, lint/format, mypy с проверкой тел функций, schema/API compatibility, unit/secret-free integration/MCP и обе сборки; отдельно pip-audit проверяет pinned зависимости. Успех конфигурации CI сам по себе не доказывает успех удалённого запуска: проверяйте GitHub Actions.

## Авторизация GitHub

В текущем managed окружении GitHub API принимает предоставленную интеграцию, но git receive-pack отклоняет её как `Invalid username or token`. История первоначально опубликована через официальный Git Data API, с проверкой точного SHA всех локальных деревьев/коммитов и без force/update существующих веток. Начальный README-коммит `main` включён merge-коммитом; обе истории сохранены.

Для обычного push на своей машине выполните `gh auth login --hostname github.com --git-protocol https --web`, `gh auth setup-git`, `git fetch origin`, `git push -u origin master`. Не передавайте токен в чат или URL. Если GitHub требует доступ к private repo / workflow, предоставьте соответствующие права своей интеграции. Нельзя сообщать об успехе git push по одному лишь `gh auth status`.
