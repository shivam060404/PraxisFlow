#!/bin/sh
set -eu

umask 077
backup_dir="${BACKUP_DIR:-/backups}"
mkdir -p "$backup_dir"
timestamp="$(date -u +%Y%m%dT%H%M%SZ)"
backup_file="$backup_dir/praxisflow-$timestamp.dump"

pg_dump \
  --dbname="${BACKUP_DATABASE_URL:?BACKUP_DATABASE_URL is required}" \
  --format=custom \
  --no-owner \
  --no-password \
  --file="$backup_file"

aws --endpoint-url "${S3_ENDPOINT:?S3_ENDPOINT is required}" s3 cp \
  "$backup_file" "s3://${S3_BUCKET:?S3_BUCKET is required}/$timestamp.dump" \
  --only-show-errors

find "$backup_dir" -type f -name '*.dump' -mtime +"${BACKUP_RETENTION_DAYS:-30}" -delete

# Keep the object store inside the configured retention window as well.
cutoff_epoch=$(( $(date -u +%s) - ${BACKUP_RETENTION_DAYS:-30} * 86400 ))
aws --endpoint-url "$S3_ENDPOINT" s3 ls "s3://$S3_BUCKET/" | \
while read -r object_date object_time object_size object_key; do
  [ -n "${object_key:-}" ] || continue
  object_epoch=$(date -u -d "$object_date $object_time" +%s)
  if [ "$object_epoch" -lt "$cutoff_epoch" ]; then
    aws --endpoint-url "$S3_ENDPOINT" s3 rm "s3://$S3_BUCKET/$object_key" --only-show-errors
  fi
done
