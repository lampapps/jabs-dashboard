"""Universal, dashboard-side retention/purge policy.

Unlike the old per-agent rotation reconciliation, this applies a single
`retention.max_days` cutoff (see config/global.yaml) to ALL agents' data —
any completed backup_jobs row (and its cascaded events) older than the
cutoff is purged, regardless of any retention/rotation setting configured
on an individual agent.
"""

from app.settings import RETENTION_MAX_DAYS
from app.models.backup_jobs import delete_backup_jobs_older_than
from app.utils.logger import setup_logger

logger = setup_logger("scheduler", log_file="scheduler.log")


def purge_old_records():
    """Purge completed backup_jobs (and cascaded events) older than
    RETENTION_MAX_DAYS, across all agents. Returns the number of rows deleted.
    """
    if not RETENTION_MAX_DAYS or RETENTION_MAX_DAYS <= 0:
        logger.info("Retention purge skipped: retention.max_days is unset/disabled")
        return 0

    logger.debug(f"Purging completed backup_jobs older than {RETENTION_MAX_DAYS} day(s).")
    deleted_count = delete_backup_jobs_older_than(RETENTION_MAX_DAYS)
    logger.info(
        f"Retention purge complete: deleted {deleted_count} backup_jobs row(s) older than {RETENTION_MAX_DAYS} day(s)"
    )
    return deleted_count
