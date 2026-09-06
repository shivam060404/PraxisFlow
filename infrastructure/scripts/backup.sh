#!/bin/sh
set -eu

backup_dir="${BACKUP_DIR:-/tmp/praxisflow-backups}"
mkdir -p "$backup_dir"
timestamp="$(date -u +%Y%m%dT%H%M%SZ)"
pg_dump \
  --host="${POSTGRES_HOST:-postgres-primary}" \
  --username="${POSTGRES_USER:-praxisflow}" \
  --dbname="${POSTGRES_DB:-praxisflow}" \
  --format=custom \
  --file="$backup_dir/praxisflow-$timestamp.dump"

find "$backup_dir" -type f -name '*.dump' -mtime +"${BACKUP_RETENTION_DAYS:-30}" -delete
