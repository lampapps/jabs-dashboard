"""Universal, dashboard-side retention/purge policy.

Unlike the old per-agent rotation reconciliation, this applies a single
`retention.max_days` cutoff (see config/global.yaml) to ALL agents' data —
any completed backup_jobs row (and its cascaded events) older than the
cutoff is purged, regardless of any retention/rotation setting configured
on an individual agent.
"""

import logging

from app.settings import RETENTION_MAX_DAYS
from app.models.backup_jobs import delete_backup_jobs_older_than

logger = logging.getLogger(__name__)


def purge_old_records():
    """Purge completed backup_jobs (and cascaded events) older than
    RETENTION_MAX_DAYS, across all agents. Returns the number of rows deleted.
    """
    if not RETENTION_MAX_DAYS or RETENTION_MAX_DAYS <= 0:
        logger.info("Retention purge skipped: retention.max_days is unset/disabled")
        return 0

    deleted_count = delete_backup_jobs_older_than(RETENTION_MAX_DAYS)
    logger.info(
        "Retention purge complete: deleted %s backup_jobs row(s) older than %s day(s)",
        deleted_count, RETENTION_MAX_DAYS
    )
    return deleted_count
