"""Model for managing backup job executions."""

import time
from app.models.db_core import get_db_connection


def create_backup_job(agent_id, job_name, backup_type, backup_set_id, backup_set_name,
                      source="", destination="", encrypt=False, sync=False, run_id=None):
    """Create a new backup job record. Returns backup_job id."""
    with get_db_connection() as conn:
        c = conn.cursor()
        now = time.time()
        c.execute("""
            INSERT INTO backup_jobs
            (agent_id, job_name, backup_type, run_id, backup_set_id, backup_set_name,
             source, destination, encrypt, sync, started_at, status, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            agent_id, job_name, backup_type, run_id, backup_set_id, backup_set_name,
            source, destination, 1 if encrypt else 0, 1 if sync else 0,
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


def delete_backup_jobs_older_than(max_days):
    """Delete completed backup jobs older than max_days, across ALL agents.

    This is the dashboard's single, universal retention policy — it applies
    the same cutoff to every agent's data regardless of any rotation/
    retention setting configured on the agent side. Only finished jobs
    (completed_at set) are eligible; a job still "running" is never purged.

    Returns the number of backup_jobs rows deleted (cascades to events).
    """
    if not max_days or max_days <= 0:
        return 0

    cutoff = time.time() - (max_days * 86400)

    with get_db_connection() as conn:
        c = conn.cursor()
        c.execute("""
            DELETE FROM backup_jobs
            WHERE completed_at IS NOT NULL AND completed_at < ?
        """, (cutoff,))
        conn.commit()
        return c.rowcount


def mark_backup_jobs_purged(agent_id, backup_set_id):
    """Mark every backup_jobs row for agent_id+backup_set_id as 'purged'.

    Called when an agent (e.g. file_backup_agent) rotates a backup set out
    of its own local storage/database. This does NOT delete the rows or
    their events — it only flips their status to 'purged' so the dashboard's
    history reflects that the underlying data no longer exists on the agent.
    Actual row deletion is handled solely by the dashboard's own time-based
    retention policy (see delete_backup_jobs_older_than above).

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

