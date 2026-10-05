"""Model for managing backup job executions."""

import time
from app.models.db_core import get_db_connection


def create_backup_job(agent_id, job_name, backup_type, target_id, target_label,
                      source="", destination="", run_id=None, job_run_id=None):
    """Create a new backup job record. Returns backup_job id.

    job_run_id, when provided, is a UUID shared by every target/pair under
    one overall agent-script invocation (distinct from the per-target
    run_id), used to group multi-pair job runs for First/Last/Next Event.
    """
    with get_db_connection() as conn:
        c = conn.cursor()
        now = time.time()
        c.execute("""
            INSERT INTO backup_jobs
            (agent_id, job_name, backup_type, run_id, target_id, target_label,
             source, destination, started_at, status, job_run_id, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            agent_id, job_name, backup_type, run_id, target_id, target_label,
            source, destination,
            now, 'running', job_run_id, now, now
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
                       error_code=None, error_message=None, external_id=None):
    """Finalize a backup job with completion results. Returns True if successful.

    external_id, when provided, is an agent-chosen opaque identifier for the
    underlying artifact this run produced (e.g. a restic snapshot ID, or an
    image filename) — stored so a later purge report can match it via
    mark_backup_jobs_purged().
    """
    with get_db_connection() as conn:
        c = conn.cursor()
        now = time.time()
        # Success always reaches 100%; failures/stopped keep their last-known
        # percent so the UI can show e.g. "failed at 63%" instead of blanking it.
        percent_complete = 100 if status == 'success' else None
        c.execute("""
            UPDATE backup_jobs
            SET status = ?, completed_at = ?, runtime_seconds = ?, files_count = ?,
                bytes_processed = ?, bytes_compressed = ?, error_code = ?, error_message = ?,
                external_id = COALESCE(?, external_id),
                percent_complete = COALESCE(?, percent_complete),
                bytes_per_second = NULL, eta_seconds = NULL, current_item = NULL,
                updated_at = ?
            WHERE id = ?
        """, (
            status, now, runtime_seconds, files_count, bytes_processed, bytes_compressed,
            error_code, error_message, external_id, percent_complete, now, backup_job_id
        ))
        conn.commit()
        return c.rowcount > 0


def update_backup_job_progress(backup_job_id, percent_complete=None, bytes_per_second=None,
                              eta_seconds=None, current_item=None, files_count=None,
                              bytes_processed=None):
    """Apply a non-finalizing progress update from a running job.

    Only columns passed as non-None are updated, so an agent can report any
    subset of fields (e.g. restic has no computed rate, dd has no percent).
    Never touches status/completed_at — only finalize_backup_job() does that.
    """
    with get_db_connection() as conn:
        c = conn.cursor()
        now = time.time()

        updates = ["updated_at = ?", "progress_updated_at = ?"]
        params = [now, now]

        fields = {
            'percent_complete': percent_complete,
            'bytes_per_second': bytes_per_second,
            'eta_seconds': eta_seconds,
            'current_item': current_item,
            'files_count': files_count,
            'bytes_processed': bytes_processed,
        }
        for key, value in fields.items():
            if value is not None:
                updates.append(f"{key} = ?")
                params.append(value)

        if len(updates) == 2:
            return False  # nothing to update besides timestamps

        params.append(backup_job_id)
        query = f"UPDATE backup_jobs SET {', '.join(updates)} WHERE id = ?"
        c.execute(query, params)
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


def delete_expired_backup_jobs(max_days):
    """Delete backup_jobs rows (and cascaded events) older than max_days,
    measured from started_at, regardless of agent_type or status.

    Returns a list of {"id", "hostname", "job_name", "status",
    "target_id"} dicts for every row actually deleted, so the caller can
    log exactly what was removed.
    """
    if not max_days or max_days <= 0:
        return []

    cutoff = time.time() - (max_days * 86400)

    with get_db_connection() as conn:
        c = conn.cursor()
        c.execute("""
            SELECT bj.id, a.hostname, bj.job_name, bj.status, bj.target_id
            FROM backup_jobs bj
            JOIN agents a ON a.id = bj.agent_id
            WHERE bj.started_at < ?
        """, (cutoff,))
        matched = [dict(row) for row in c.fetchall()]
        if not matched:
            return []

        ids = [row['id'] for row in matched]
        placeholders = ", ".join(["?"] * len(ids))
        c.execute(f"DELETE FROM backup_jobs WHERE id IN ({placeholders})", ids)
        conn.commit()
        return matched


def mark_backup_jobs_purged(agent_id, target_id, external_ids):
    """Mark backup_jobs rows for agent_id+target_id whose external_id is in
    external_ids as 'purged'.

    Called when an agent deletes specific rotated-out artifacts (e.g. a
    pruned restic snapshot, a deleted dated image file) belonging to a
    target_id it still otherwise keeps running. This does NOT delete the
    rows or their events — it only flips their status to 'purged' so the
    dashboard's history reflects that the underlying data no longer exists
    on the agent. Actual row deletion is handled solely by the dashboard's
    own retention policy (see delete_expired_backup_jobs above).

    external_ids is a required, non-empty list — only rows whose stored
    external_id (set via finalize_backup_job) matches one of these values
    are marked, so unrelated runs sharing the same target_id are untouched.

    Returns the list of backup_job ids that were updated.
    """
    if not external_ids:
        return []

    with get_db_connection() as conn:
        c = conn.cursor()
        placeholders = ", ".join(["?"] * len(external_ids))
        c.execute(
            f"SELECT id FROM backup_jobs WHERE agent_id = ? AND target_id = ? AND external_id IN ({placeholders})",
            (agent_id, target_id, *external_ids)
        )
        job_ids = [row['id'] for row in c.fetchall()]
        if not job_ids:
            return []

        now = time.time()
        job_placeholders = ", ".join(["?"] * len(job_ids))
        c.execute(
            f"UPDATE backup_jobs SET status = 'purged', updated_at = ? WHERE id IN ({job_placeholders})",
            (now, *job_ids)
        )
        conn.commit()
        return job_ids

