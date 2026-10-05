"""Model for tracking each (agent, job_name)'s reported cron schedule(s),
used to compute the dashboard's "Next Event" column."""

import time
from app.models.db_core import get_db_connection


def upsert_job_schedule(agent_id, job_name, cron_schedule):
    """Create or update the cron schedule reported for a given job."""
    with get_db_connection() as conn:
        c = conn.cursor()
        now = time.time()
        c.execute("""
            INSERT INTO job_schedules (agent_id, job_name, cron_schedule, updated_at)
            VALUES (?, ?, ?, ?)
            ON CONFLICT(agent_id, job_name) DO UPDATE SET
                cron_schedule = excluded.cron_schedule,
                updated_at = excluded.updated_at
        """, (agent_id, job_name, cron_schedule, now))
        conn.commit()


def get_all_job_schedules():
    """Return {(agent_id, job_name): cron_schedule}."""
    with get_db_connection() as conn:
        c = conn.cursor()
        c.execute("SELECT agent_id, job_name, cron_schedule FROM job_schedules")
        return {(row['agent_id'], row['job_name']): row['cron_schedule'] for row in c.fetchall()}
