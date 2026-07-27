"""Model for managing backup job executions."""

import time
from app.models.db_core import get_db_connection


def create_backup_job(host_id, job_name, backup_type, backup_set_id, backup_set_name,
                      source="", destination="", encrypt=False, sync=False, run_id=None):
    """Create a new backup job record. Returns backup_job id."""
    with get_db_connection() as conn:
        c = conn.cursor()
        now = time.time()
        c.execute("""
            INSERT INTO backup_jobs
            (host_id, job_name, backup_type, run_id, backup_set_id, backup_set_name,
             source, destination, encrypt, sync, started_at, status, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            host_id, job_name, backup_type, run_id, backup_set_id, backup_set_name,
            source, destination, 1 if encrypt else 0, 1 if sync else 0,
            now, 'running', now, now
        ))
        conn.commit()
        return c.lastrowid


def get_backup_job(backup_job_id):
    """Get backup job by id. Returns dict or None."""
    with get_db_connection() as conn:
        c = conn.cursor()
        c.execute("SELECT * FROM backup_jobs WHERE id = ?", (backup_job_id,))
        row = c.fetchone()
        return dict(row) if row else None


def get_backup_job_by_run_id(run_id):
    """Get backup job by run_id (per-run UUID). Returns dict or None."""
    if not run_id:
        return None
    with get_db_connection() as conn:
        c = conn.cursor()
        c.execute("SELECT * FROM backup_jobs WHERE run_id = ?", (run_id,))
        row = c.fetchone()
        return dict(row) if row else None


def get_backup_job_by_set_id(backup_set_id):
    """Get backup job by backup_set_id. Returns dict or None."""
    with get_db_connection() as conn:
        c = conn.cursor()
        c.execute("""
            SELECT * FROM backup_jobs WHERE backup_set_id = ? ORDER BY started_at DESC LIMIT 1
        """, (backup_set_id,))
        row = c.fetchone()
        return dict(row) if row else None


def list_backup_jobs_for_host(host_id, limit=100):
    """List backup jobs for a host. Returns list of dicts."""
    with get_db_connection() as conn:
        c = conn.cursor()
        c.execute("""
            SELECT * FROM backup_jobs WHERE host_id = ? ORDER BY started_at DESC LIMIT ?
        """, (host_id, limit))
        return [dict(row) for row in c.fetchall()]


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


def delete_backup_job(backup_job_id):
    """Delete backup job (cascades to events). Returns True if successful."""
    with get_db_connection() as conn:
        c = conn.cursor()
        c.execute("DELETE FROM backup_jobs WHERE id = ?", (backup_job_id,))
        conn.commit()
        return c.rowcount > 0


def list_completed_jobs_since(since_ts):
    """List backup jobs that finished (completed/failed/skipped) since since_ts.

    Joins in the host's hostname for display purposes. Returns a list of dicts
    ordered by completion time, oldest first. Used to build the dashboard's daily
    email digest.
    """
    with get_db_connection() as conn:
        c = conn.cursor()
        c.execute("""
            SELECT bj.*, h.hostname AS hostname
            FROM backup_jobs bj
            JOIN hosts h ON h.id = bj.host_id
            WHERE bj.completed_at IS NOT NULL AND bj.completed_at >= ?
            ORDER BY bj.completed_at ASC
        """, (since_ts,))
        return [dict(row) for row in c.fetchall()]


def delete_orphaned_backup_jobs(host_id, job_name, active_backup_set_ids):
    """Delete backup jobs for a host+job_name whose backup_set_id is no longer
    present in the agent's own database (i.e. it has been rotated out).

    As a safety measure, if ``active_backup_set_ids`` is empty this is a no-op —
    an empty list from the agent could indicate a transient bug rather than a
    genuine "nothing left" state, and we never want to silently wipe all
    history for a job based on that ambiguity.

    Returns the number of backup_jobs rows deleted (cascades to events).
    """
    active_backup_set_ids = [s for s in (active_backup_set_ids or []) if s]
    if not active_backup_set_ids:
        return 0

    with get_db_connection() as conn:
        c = conn.cursor()
        placeholders = ", ".join(["?"] * len(active_backup_set_ids))
        c.execute(f"""
            SELECT id FROM backup_jobs
            WHERE host_id = ? AND job_name = ? AND backup_set_id NOT IN ({placeholders})
        """, (host_id, job_name, *active_backup_set_ids))
        orphaned_ids = [row['id'] for row in c.fetchall()]

        if not orphaned_ids:
            return 0

        orphan_placeholders = ", ".join(["?"] * len(orphaned_ids))
        c.execute(f"DELETE FROM backup_jobs WHERE id IN ({orphan_placeholders})", orphaned_ids)
        conn.commit()
        return c.rowcount
