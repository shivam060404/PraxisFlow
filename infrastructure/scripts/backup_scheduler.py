"""Run the database backup daily at the configured UTC hour."""

import logging
import os
import subprocess
import sys
import time
from datetime import datetime, timedelta, timezone

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
backup_hour = int(os.environ.get("BACKUP_HOUR_UTC", "2"))
if not 0 <= backup_hour <= 23:
    raise ValueError("BACKUP_HOUR_UTC must be between 0 and 23")

while True:
    now = datetime.now(timezone.utc)
    next_run = now.replace(hour=backup_hour, minute=0, second=0, microsecond=0)
    if next_run <= now:
        next_run += timedelta(days=1)
    delay = max(0, (next_run - now).total_seconds())
    logging.info("Next PostgreSQL backup scheduled at %s UTC", next_run.isoformat())
    time.sleep(delay)
    result = subprocess.run(["/backup.sh"], check=False)
    if result.returncode:
        logging.error("Backup failed with exit code %s; stopping for container restart", result.returncode)
        sys.exit(result.returncode)
