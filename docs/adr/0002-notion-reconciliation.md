# ADR-0002: Notion identity and uncertain writes
Status: Accepted. Date: 2026-10-19.

Проблема: Notion create не обеспечивает application-level unique Chronicle Key. Потеря ответа может привести к повторной странице.
Альтернативы: blind retry; local ID cache only; single publisher + persisted uncertain fence + remote lookup.
Решение: последний вариант. До create сохранить fence; сначала query по ключу, root/database — поиск под известным parent. Если результат неизвестен и lookup пустой, не создавать автоматически. Только ручное доказательство отсутствия позволяет снять fence.
Обоснование: отсутствие результата lookup при eventual visibility не доказывает отсутствие записи.
Последствия: publisher может потребовать оператора; сохранность metadata входит в backup. PostgreSQL advisory lock сериализует publishers на одном store. Независимые stores не должны писать в одну Chronicle область Notion.
Компоненты: publisher, collector, backup. Source: implementation task Codex Chronicle.
