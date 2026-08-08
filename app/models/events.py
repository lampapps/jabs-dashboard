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



