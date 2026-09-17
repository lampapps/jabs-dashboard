"""Dashboard-side, per-agent-type retention/purge policy.

Each agent_type gets a policy of {"max_days": int, "mode": "purged_only" |
"all"} (see config/global.yaml). "purged_only" only deletes rows an agent
has explicitly marked status='purged' (age measured from when marked
purged) -- everything else is kept indefinitely. "all" deletes any row of
that age regardless of status -- for agents that never mark rows purged.
Agent types not explicitly configured use RETENTION_DEFAULT. The default's
max_days is also used as the Job Activity graph's day range (see
app/routes/dashboard.py).
"""

from app.settings import RETENTION_DEFAULT, RETENTION_BY_AGENT_TYPE
from app.models.backup_jobs import delete_expired_backup_jobs
from app.utils.logger import setup_logger

logger = setup_logger("scheduler", log_file="scheduler.log")


def purge_old_records():
    """Purge expired backup_jobs (and cascaded events) per each agent_type's
    retention policy, across all agents. Returns the number of rows deleted.
    """
    logger.debug(
        f"Purging backup_jobs per retention policy (default={RETENTION_DEFAULT}, "
        f"overrides={RETENTION_BY_AGENT_TYPE})."
    )
    deleted_count = delete_expired_backup_jobs(RETENTION_DEFAULT, RETENTION_BY_AGENT_TYPE)
    logger.info(f"Retention purge complete: deleted {deleted_count} backup_jobs row(s)")
    return deleted_count
