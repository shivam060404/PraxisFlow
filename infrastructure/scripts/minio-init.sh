#!/bin/sh
set -eu

mc alias set minio http://minio:9000 "$MINIO_ROOT_USER" "$MINIO_ROOT_PASSWORD"

for bucket in meeting-audio meeting-transcripts; do
  mc mb "minio/$bucket" --ignore-existing
done

mc admin policy info minio praxisflow-app >/dev/null 2>&1 || \
  mc admin policy create minio praxisflow-app /policies/app.json
mc admin user info minio "$MINIO_APP_ACCESS_KEY" >/dev/null 2>&1 || \
  mc admin user add minio "$MINIO_APP_ACCESS_KEY" "$MINIO_APP_SECRET_KEY"

mc admin policy attach minio praxisflow-app --user="$MINIO_APP_ACCESS_KEY"
