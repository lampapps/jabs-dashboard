"""Model for managing hosts (registered backup machines)."""

import time
from app.models.db_core import get_db_connection


def create_host(hostname, ip_address, notes=""):
    """Create a new registered host. Returns host id."""
    with get_db_connection() as conn:
        c = conn.cursor()
        now = time.time()
        c.execute("""
            INSERT INTO hosts (hostname, ip_address, notes, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?)
        """, (hostname, ip_address, notes, now, now))
        conn.commit()
        return c.lastrowid


def get_host(host_id):
    """Get host by id. Returns host dict or None."""
    with get_db_connection() as conn:
        c = conn.cursor()
        c.execute("SELECT * FROM hosts WHERE id = ?", (host_id,))
        row = c.fetchone()
        return dict(row) if row else None


def get_host_by_hostname(hostname):
    """Get host by hostname. Returns host dict or None."""
    with get_db_connection() as conn:
        c = conn.cursor()
        c.execute("SELECT * FROM hosts WHERE hostname = ?", (hostname,))
        row = c.fetchone()
        return dict(row) if row else None


def list_hosts():
    """List all hosts. Returns list of host dicts."""
    with get_db_connection() as conn:
        c = conn.cursor()
        c.execute("SELECT * FROM hosts ORDER BY hostname")
        return [dict(row) for row in c.fetchall()]


def update_host(host_id, hostname=None, ip_address=None, agent_version=None, notes=None, enabled=None):
    """Update host details. Returns True if successful."""
    with get_db_connection() as conn:
        c = conn.cursor()
        now = time.time()

        updates = ["updated_at = ?"]
        params = [now]

        if hostname is not None:
            updates.append("hostname = ?")
            params.append(hostname)
        if ip_address is not None:
            updates.append("ip_address = ?")
            params.append(ip_address)
        if agent_version is not None:
            updates.append("agent_version = ?")
            params.append(agent_version)
        if notes is not None:
            updates.append("notes = ?")
            params.append(notes)
        if enabled is not None:
            updates.append("enabled = ?")
            params.append(1 if enabled else 0)

        params.append(host_id)

        query = f"UPDATE hosts SET {', '.join(updates)} WHERE id = ?"
        c.execute(query, params)
        conn.commit()
        return c.rowcount > 0


def update_heartbeat(host_id):
    """Update last_heartbeat timestamp for a host."""
    with get_db_connection() as conn:
        c = conn.cursor()
        now = time.time()
        c.execute("UPDATE hosts SET last_heartbeat = ?, updated_at = ? WHERE id = ?", (now, now, host_id))
        conn.commit()


def update_agent_version(host_id, version):
    """Update agent version for a host."""
    with get_db_connection() as conn:
        c = conn.cursor()
        now = time.time()
        c.execute("UPDATE hosts SET agent_version = ?, updated_at = ? WHERE id = ?", (version, now, host_id))
        conn.commit()


def update_agent_type(host_id, agent_type):
    """Update agent type for a host (e.g. 'File Backup', 'Docker Backup')."""
    with get_db_connection() as conn:
        c = conn.cursor()
        now = time.time()
        c.execute("UPDATE hosts SET agent_type = ?, updated_at = ? WHERE id = ?", (agent_type, now, host_id))
        conn.commit()


def delete_host(host_id):
    """Delete host (cascades to backup jobs and events). Returns True if successful."""
    with get_db_connection() as conn:
        c = conn.cursor()
        c.execute("DELETE FROM hosts WHERE id = ?", (host_id,))
        conn.commit()
        return c.rowcount > 0


def get_hosts_with_job_counts():
    """Get all hosts with count of backup jobs for each. Returns list of host dicts."""
    with get_db_connection() as conn:
        c = conn.cursor()
        c.execute("""
            SELECT h.*, COUNT(bj.id) as job_count
            FROM hosts h
            LEFT JOIN backup_jobs bj ON h.id = bj.host_id
            GROUP BY h.id
            ORDER BY h.hostname
        """)
        return [dict(row) for row in c.fetchall()]
