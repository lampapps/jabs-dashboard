"""Model for managing backup job events."""

import time
from app.models.db_core import get_db_connection


def create_event(backup_job_id, event_type, message, stage=None, error_code=None, timestamp=None):
    """Create a new event record. Returns event id."""
    with get_db_connection() as conn:
        c = conn.cursor()
        now = time.time()
        ts = timestamp or now
        c.execute("""
            INSERT INTO events (backup_job_id, event_type, message, stage, error_code, timestamp, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?)
        """, (backup_job_id, event_type, message, stage, error_code, ts, now))
        conn.commit()
        return c.lastrowid


def get_event(event_id):
    """Get event by id. Returns dict or None."""
    with get_db_connection() as conn:
        c = conn.cursor()
        c.execute("SELECT * FROM events WHERE id = ?", (event_id,))
        row = c.fetchone()
        return dict(row) if row else None


def list_events_for_backup_job(backup_job_id):
    """Get all events for a backup job. Returns list of dicts ordered by timestamp."""
    with get_db_connection() as conn:
        c = conn.cursor()
        c.execute("""
            SELECT * FROM events WHERE backup_job_id = ? ORDER BY timestamp ASC
        """, (backup_job_id,))
        return [dict(row) for row in c.fetchall()]


def list_recent_events(limit=100):
    """Get recent events across all backups. Returns list of dicts."""
    with get_db_connection() as conn:
        c = conn.cursor()
        c.execute("""
            SELECT * FROM events ORDER BY timestamp DESC LIMIT ?
        """, (limit,))
        return [dict(row) for row in c.fetchall()]


def delete_event(event_id):
    """Delete an event. Returns True if successful."""
    with get_db_connection() as conn:
        c = conn.cursor()
        c.execute("DELETE FROM events WHERE id = ?", (event_id,))
        conn.commit()
        return c.rowcount > 0
