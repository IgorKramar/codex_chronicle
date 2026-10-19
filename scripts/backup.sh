#!/bin/sh
set -eu
# Usage: scripts/backup.sh /absolute/private/backup.dump
# Run from repo root with deployment variables already configured.
umask 077
out=${1:?Provide private backup destination}
docker compose -f deploy/compose.yaml stop collector
trap 'docker compose -f deploy/compose.yaml start collector >/dev/null' EXIT
docker compose -f deploy/compose.yaml exec -T postgres pg_dump -U chronicle -d chronicle -Fc > "$out"
test -s "$out"
# Publisher caches/uncertain-write fences are essential for safe recovery.
docker compose -f deploy/compose.yaml run --rm -T --no-deps --entrypoint tar collector -C /data -cf - . > "$out.publisher.tar"
