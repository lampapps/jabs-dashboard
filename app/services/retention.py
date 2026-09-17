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
    retention policy, across all agents. Logs a per-agent-type summary at
    INFO and each deleted row's identifying info at DEBUG. Returns the total
    number of rows deleted.
    """
    logger.debug(
        f"Purging backup_jobs per retention policy (default={RETENTION_DEFAULT}, "
        f"overrides={RETENTION_BY_AGENT_TYPE})."
    )
    results = delete_expired_backup_jobs(RETENTION_DEFAULT, RETENTION_BY_AGENT_TYPE)

    total = 0
    for result in results:
        agent_type = result["agent_type"] or "(no agent_type)"
        deleted_jobs = result["deleted_jobs"]
        if not deleted_jobs:
            continue
        total += len(deleted_jobs)
        policy = result["policy"]
        logger.info(
            f"Retention purge: deleted {len(deleted_jobs)} backup_jobs row(s) for "
            f"agent_type={agent_type} (mode={policy.get('mode')}, "
            f"max_days={policy.get('max_days')})"
        )
        for job in deleted_jobs:
            logger.debug(
                f"Retention purge deleted backup_jobs.id={job['id']} "
                f"hostname={job['hostname']} job_name={job['job_name']} "
                f"status={job['status']} backup_set_id={job['backup_set_id']}"
            )

    if total == 0:
        logger.info("Retention purge complete: no backup_jobs rows eligible for deletion")
    else:
        logger.info(f"Retention purge complete: deleted {total} backup_jobs row(s) total")
    return total
