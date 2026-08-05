"""Model for managing agents (registered backup/sync agents).

Each row represents one agent instance, identified by a unique `agent_key`
that the agent sends on every API call. Multiple agents can share the same
`hostname`/`ip_address` (e.g. several agents running on one machine).
"""

import time
from app.models.db_core import get_db_connection, generate_agent_key


def create_agent(hostname, ip_address, notes=""):
    """Register a new agent. Returns (agent_id, agent_key)."""
    agent_key = generate_agent_key()
    with get_db_connection() as conn:
        c = conn.cursor()
        now = time.time()
        c.execute("""
            INSERT INTO agents (hostname, ip_address, agent_key, notes, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?)
        """, (hostname, ip_address, agent_key, notes, now, now))
        conn.commit()
        return c.lastrowid, agent_key


def get_agent(agent_id):
    """Get agent by id. Returns agent dict or None."""
    with get_db_connection() as conn:
        c = conn.cursor()
        c.execute("SELECT * FROM agents WHERE id = ?", (agent_id,))
        row = c.fetchone()
        return dict(row) if row else None


def get_agent_by_hostname(hostname):
    """Get an agent by hostname. Returns agent dict or None.

    Note: hostname is not unique (multiple agents may share a machine), so
    this returns the first match only. Prefer get_agent_by_agent_key() for
    authenticating API requests.
    """
    with get_db_connection() as conn:
        c = conn.cursor()
        c.execute("SELECT * FROM agents WHERE hostname = ?", (hostname,))
        row = c.fetchone()
        return dict(row) if row else None


def get_agent_by_agent_key(agent_key):
    """Get agent by its unique agent_key. Returns agent dict or None."""
    if not agent_key:
        return None
    with get_db_connection() as conn:
        c = conn.cursor()
        c.execute("SELECT * FROM agents WHERE agent_key = ?", (agent_key,))
        row = c.fetchone()
        return dict(row) if row else None


def regenerate_agent_key(agent_id):
    """Generate and store a new agent_key for an agent. Returns the new key, or None if agent not found."""
    new_key = generate_agent_key()
    with get_db_connection() as conn:
        c = conn.cursor()
        now = time.time()
        c.execute("UPDATE agents SET agent_key = ?, updated_at = ? WHERE id = ?", (new_key, now, agent_id))
        conn.commit()
        return new_key if c.rowcount > 0 else None


def list_agents():
    """List all agents. Returns list of agent dicts."""
    with get_db_connection() as conn:
        c = conn.cursor()
        c.execute("SELECT * FROM agents ORDER BY hostname")
        return [dict(row) for row in c.fetchall()]


def update_agent(agent_id, hostname=None, ip_address=None, agent_version=None, notes=None, enabled=None):
    """Update agent details. Returns True if successful."""
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

        params.append(agent_id)

        query = f"UPDATE agents SET {', '.join(updates)} WHERE id = ?"
        c.execute(query, params)
        conn.commit()
        return c.rowcount > 0


def update_heartbeat(agent_id):
    """Update last_heartbeat timestamp for an agent."""
    with get_db_connection() as conn:
        c = conn.cursor()
        now = time.time()
        c.execute("UPDATE agents SET last_heartbeat = ?, updated_at = ? WHERE id = ?", (now, now, agent_id))
        conn.commit()


def update_agent_version(agent_id, version):
    """Update the reported software version for an agent."""
    with get_db_connection() as conn:
        c = conn.cursor()
        now = time.time()
        c.execute("UPDATE agents SET agent_version = ?, updated_at = ? WHERE id = ?", (version, now, agent_id))
        conn.commit()


def update_agent_type(agent_id, agent_type):
    """Update the agent type (e.g. 'File Backup', 'Docker Backup')."""
    with get_db_connection() as conn:
        c = conn.cursor()
        now = time.time()
        c.execute("UPDATE agents SET agent_type = ?, updated_at = ? WHERE id = ?", (agent_type, now, agent_id))
        conn.commit()


def delete_agent(agent_id):
    """Delete an agent (cascades to backup jobs and events). Returns True if successful."""
    with get_db_connection() as conn:
        c = conn.cursor()
        c.execute("DELETE FROM agents WHERE id = ?", (agent_id,))
        conn.commit()
        return c.rowcount > 0


def get_agents_with_job_counts():
    """Get all agents with count of backup jobs for each. Returns list of agent dicts."""
    with get_db_connection() as conn:
        c = conn.cursor()
        c.execute("""
            SELECT a.*, COUNT(bj.id) as job_count
            FROM agents a
            LEFT JOIN backup_jobs bj ON a.id = bj.agent_id
            GROUP BY a.id
            ORDER BY a.hostname
        """)
        return [dict(row) for row in c.fetchall()]
