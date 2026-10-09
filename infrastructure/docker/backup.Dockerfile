FROM postgres:16-alpine

RUN apk add --no-cache aws-cli ca-certificates python3
COPY infrastructure/scripts/backup.sh /backup.sh
COPY infrastructure/scripts/backup_scheduler.py /backup_scheduler.py
RUN chmod 0755 /backup.sh

ENTRYPOINT ["python3", "/backup_scheduler.py"]
