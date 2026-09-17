"""Model for managing backup job executions."""

import time
from app.models.db_core import get_db_connection


def create_backup_job(agent_id, job_name, backup_type, backup_set_id, backup_set_name,
                      source="", destination="", run_id=None):
    """Create a new backup job record. Returns backup_job id."""
    with get_db_connection() as conn:
        c = conn.cursor()
        now = time.time()
        c.execute("""
            INSERT INTO backup_jobs
            (agent_id, job_name, backup_type, run_id, backup_set_id, backup_set_name,
             source, destination, started_at, status, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            agent_id, job_name, backup_type, run_id, backup_set_id, backup_set_name,
            source, destination,
            now, 'running', now, now
        ))
        conn.commit()
        return c.lastrowid


def get_backup_job_by_run_id(run_id):
    """Get backup job by run_id (per-run UUID). Returns dict or None."""
    if not run_id:
        return None
    with get_db_connection() as conn:
        c = conn.cursor()
        c.execute("SELECT * FROM backup_jobs WHERE run_id = ?", (run_id,))
        row = c.fetchone()
        return dict(row) if row else None


def finalize_backup_job(backup_job_id, status, runtime_seconds=None, files_count=None,
                       bytes_processed=None, bytes_compressed=None,
                       error_code=None, error_message=None):
    """Finalize a backup job with completion results. Returns True if successful."""
    with get_db_connection() as conn:
        c = conn.cursor()
        now = time.time()
        c.execute("""
            UPDATE backup_jobs
            SET status = ?, completed_at = ?, runtime_seconds = ?, files_count = ?,
                bytes_processed = ?, bytes_compressed = ?, error_code = ?, error_message = ?,
                updated_at = ?
            WHERE id = ?
        """, (
            status, now, runtime_seconds, files_count, bytes_processed, bytes_compressed,
            error_code, error_message, now, backup_job_id
        ))
        conn.commit()
        return c.rowcount > 0


def update_backup_job(backup_job_id, **kwargs):
    """Update backup job fields. Returns True if successful."""
    with get_db_connection() as conn:
        c = conn.cursor()
        now = time.time()

        updates = ["updated_at = ?"]
        params = [now]

        allowed_fields = {
            'status', 'completed_at', 'runtime_seconds', 'files_count',
            'bytes_processed', 'bytes_compressed', 'error_code', 'error_message',
            'backup_type'
        }

        for key, value in kwargs.items():
            if key in allowed_fields:
                updates.append(f"{key} = ?")
                params.append(value)

        params.append(backup_job_id)

        query = f"UPDATE backup_jobs SET {', '.join(updates)} WHERE id = ?"
        c.execute(query, params)
        conn.commit()
        return c.rowcount > 0


def list_completed_jobs_since(since_ts):
    """List backup jobs that finished (completed/failed/skipped) since since_ts.

    Joins in the agent's hostname for display purposes. Returns a list of dicts
    ordered by completion time, oldest first. Used to build the dashboard's daily
    email digest.
    """
    with get_db_connection() as conn:
        c = conn.cursor()
        c.execute("""
            SELECT bj.*, a.hostname AS hostname
            FROM backup_jobs bj
            JOIN agents a ON a.id = bj.agent_id
            WHERE bj.completed_at IS NOT NULL AND bj.completed_at >= ?
            ORDER BY bj.completed_at ASC
        """, (since_ts,))
        return [dict(row) for row in c.fetchall()]


def delete_expired_backup_jobs(default_policy, by_agent_type=None):
    """Delete backup_jobs rows (and cascaded events) per an agent-type-aware
    retention policy.

    Each policy is a dict: {"max_days": int, "mode": "purged_only" | "all"}.
    - mode "purged_only": only rows with status='purged' are eligible,
      measured from updated_at (when marked purged). Use for agents that
      explicitly report purged sets (e.g. file_backup_agent) -- all other
      rows are kept indefinitely.
    - mode "all": any row is eligible regardless of status, measured from
      started_at. Use for agents that never mark rows as purged (e.g.
      nas_sync_agent), so their history doesn't grow forever.

    default_policy applies to any agent whose agents.agent_type is NULL or
    isn't listed in by_agent_type. Returns a list of per-agent-type result
    dicts: {"agent_type": str|None, "policy": dict, "deleted_jobs": [...]}
    where deleted_jobs holds {"id", "hostname", "job_name", "status",
    "backup_set_id"} for every row actually deleted, so the caller can log
    exactly what was removed.
    """
    by_agent_type = by_agent_type or {}

    with get_db_connection() as conn:
        c = conn.cursor()
        c.execute("SELECT DISTINCT agent_type FROM agents")
        agent_types = [row['agent_type'] for row in c.fetchall()]

        results = []
        for agent_type in agent_types:
            policy = by_agent_type.get(agent_type, default_policy) if agent_type else default_policy
            deleted_jobs = _delete_backup_jobs_for_agent_type(c, agent_type, policy)
            results.append({"agent_type": agent_type, "policy": policy, "deleted_jobs": deleted_jobs})
        conn.commit()
        return results


def _delete_backup_jobs_for_agent_type(cursor, agent_type, policy):
    """Run one policy's DELETE for a single agent_type (or NULL).

    Returns a list of {"id", "hostname", "job_name", "status",
    "backup_set_id"} dicts for every row deleted.
    """
    max_days = policy.get("max_days")
    if not max_days or max_days <= 0:
        return []

    cutoff = time.time() - (max_days * 86400)
    agent_filter = "a.agent_type = ?" if agent_type is not None else "a.agent_type IS NULL"
    params = [agent_type] if agent_type is not None else []

    if policy.get("mode") == "all":
        status_filter = ""
        age_column = "bj.started_at"
    else:
        status_filter = "AND bj.status = 'purged'"
        age_column = "bj.updated_at"

    cursor.execute(f"""
        SELECT bj.id, a.hostname, bj.job_name, bj.status, bj.backup_set_id
        FROM backup_jobs bj
        JOIN agents a ON a.id = bj.agent_id
        WHERE {agent_filter} {status_filter} AND {age_column} < ?
    """, (*params, cutoff))
    matched = [dict(row) for row in cursor.fetchall()]
    if not matched:
        return []

    ids = [row['id'] for row in matched]
    placeholders = ", ".join(["?"] * len(ids))
    cursor.execute(f"DELETE FROM backup_jobs WHERE id IN ({placeholders})", ids)
    return matched


def mark_backup_jobs_purged(agent_id, backup_set_id):
    """Mark every backup_jobs row for agent_id+backup_set_id as 'purged'.

    Called when an agent (e.g. file_backup_agent) rotates a backup set out
    of its own local storage/database. This does NOT delete the rows or
    their events — it only flips their status to 'purged' so the dashboard's
    history reflects that the underlying data no longer exists on the agent.
    Actual row deletion is handled solely by the dashboard's own retention
    policy (see delete_expired_backup_jobs above).

    A single backup_set_id can be shared by multiple backup_jobs rows (a
    full backup plus its incremental/differential children), so all of them
    are updated together.

    Returns the list of backup_job ids that were updated.
    """
    with get_db_connection() as conn:
        c = conn.cursor()
        c.execute(
            "SELECT id FROM backup_jobs WHERE agent_id = ? AND backup_set_id = ?",
            (agent_id, backup_set_id)
        )
        job_ids = [row['id'] for row in c.fetchall()]
        if not job_ids:
            return []

        now = time.time()
        placeholders = ", ".join(["?"] * len(job_ids))
        c.execute(
            f"UPDATE backup_jobs SET status = 'purged', updated_at = ? WHERE id IN ({placeholders})",
            (now, *job_ids)
        )
        conn.commit()
        return job_ids

