#!/bin/sh
set -eu
# Fresh stopped collector / empty database only. Existing data is never dropped here.
input=${1:?Provide backup.dump}
docker compose -f deploy/compose.yaml stop collector
docker compose -f deploy/compose.yaml exec -T postgres pg_restore -U chronicle -d chronicle --exit-on-error < "$input"
docker compose -f deploy/compose.yaml run --rm -T --no-deps --entrypoint tar collector -C /data -xf - < "$input.publisher.tar"
docker compose -f deploy/compose.yaml up -d collector
