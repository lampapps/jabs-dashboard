"""Dashboard-side retention/purge policy.

Deletes any backup_jobs row (and its cascaded events) older than
`retention.max_days` (see config/global.yaml), regardless of agent_type or
status. RETENTION_MAX_DAYS is also used as the Job Activity graph's day
range (see app/routes/dashboard.py).
"""

from app.settings import RETENTION_MAX_DAYS
from app.models.backup_jobs import delete_expired_backup_jobs
from app.utils.logger import setup_logger

logger = setup_logger("scheduler", log_file="scheduler.log")


def purge_old_records():
    """Purge backup_jobs (and cascaded events) older than
    RETENTION_MAX_DAYS. Logs a summary at INFO and each deleted row's
    identifying info at DEBUG. Returns the total number of rows deleted.
    """
    logger.debug(f"Purging backup_jobs older than retention.max_days={RETENTION_MAX_DAYS}.")
    deleted_jobs = delete_expired_backup_jobs(RETENTION_MAX_DAYS)

    for job in deleted_jobs:
        logger.debug(
            f"Retention purge deleted backup_jobs.id={job['id']} "
            f"hostname={job['hostname']} job_name={job['job_name']} "
            f"status={job['status']} target_id={job['target_id']}"
        )

    total = len(deleted_jobs)
    if total == 0:
        logger.info("Retention purge complete: no backup_jobs rows eligible for deletion")
    else:
        logger.info(f"Retention purge complete: deleted {total} backup_jobs row(s) total")
    return total
