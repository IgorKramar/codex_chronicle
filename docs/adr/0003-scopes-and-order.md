# ADR-0003: Identity, export consent and receive order
Status: Accepted. Date: 2026-10-19.

Проблема: несколько машин, утечки рабочих данных, out-of-order commit при PostgreSQL sequences.
Альтернативы: один shared bearer; отдельный grant на Computer ID + projects; timestamps как глобальный порядок.
Решение: scoped write grants, отдельные read grants, local policy default. UUIDv5 canonical remote для Project ID, explicit bind без remote. PostgreSQL append использует transaction advisory lock, чтобы cursor после seq N не пропустил ещё не закоммиченный меньший seq.
Обоснование: read-only сторонний агент не должен менять журнал. Timestamp источника не является надёжным глобальным clock.
Последствия: обновление grants требует restart; append batches сериализованы; sequence может иметь пропуски после rollback/deduplication. Истории решений не удаляются; conflicting Accepted choices требуют согласования.
Компоненты: agent, collector, state, auth provisioning.
