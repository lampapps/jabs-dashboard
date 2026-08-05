"""Core database utilities and schema management for JABS.

Handles connection management, schema initialization, and table/index creation.
Clean normalized schema: agents → backup_jobs → events
"""

import secrets
import sqlite3
import os
from contextlib import contextmanager
from app.settings import DB_PATH


def generate_agent_key() -> str:
    """Generate a new random API key for an agent (hex string)."""
    return secrets.token_hex(20)


@contextmanager
def get_db_connection(db_path: str = DB_PATH):
    """Context manager for SQLite database connection with foreign key support."""
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    try:
        conn.execute("PRAGMA foreign_keys = ON")
        yield conn
    finally:
        conn.close()

def init_db(db_path: str = DB_PATH):
    """Initialize the database schema with clean normalized tables."""
    # Ensure the parent directory exists
    os.makedirs(os.path.dirname(db_path), exist_ok=True)

    with get_db_connection(db_path) as conn:
        c = conn.cursor()

        # Enable foreign key constraints
        c.execute("PRAGMA foreign_keys = ON")

        # Create tables
        _create_agents_table(c)
        _create_backup_jobs_table(c)
        _create_events_table(c)
        # Apply migrations (adds any columns older DBs are missing) before
        # creating indexes that reference those columns.
        _migrate_schema(conn)
        _create_indexes(c)
        conn.commit()

def _create_agents_table(cursor):
    """Create table for manually registered agents.

    A row represents one agent instance (identified by its unique
    `agent_key`), not necessarily one machine — multiple agents can run on
    the same host, so `hostname` is informational only and is not unique.
    """
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS agents (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        hostname TEXT NOT NULL,
        ip_address TEXT NOT NULL,
        agent_key TEXT UNIQUE NOT NULL,
        agent_version TEXT,
        agent_type TEXT,
        notes TEXT,
        last_heartbeat REAL,
        enabled BOOLEAN DEFAULT 1,
        created_at REAL NOT NULL,
        updated_at REAL NOT NULL
    );
    """)

def _create_backup_jobs_table(cursor):
    """Create table for individual backup job executions."""
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS backup_jobs (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        agent_id INTEGER NOT NULL,
        job_name TEXT NOT NULL,
        backup_type TEXT NOT NULL,
        run_id TEXT UNIQUE,
        backup_set_id TEXT NOT NULL,
        backup_set_name TEXT NOT NULL,
        source TEXT,
        destination TEXT,
        encrypt BOOLEAN DEFAULT 0,
        sync BOOLEAN DEFAULT 0,
        started_at REAL NOT NULL,
        completed_at REAL,
        status TEXT DEFAULT 'running',
        runtime_seconds INTEGER,
        files_count INTEGER,
        bytes_processed INTEGER,
        bytes_compressed INTEGER,
        error_code INTEGER,
        error_message TEXT,
        created_at REAL NOT NULL,
        updated_at REAL NOT NULL,
        FOREIGN KEY (agent_id) REFERENCES agents(id) ON DELETE CASCADE
    );
    """)

def _create_events_table(cursor):
    """Create table for backup job events."""
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS events (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        backup_job_id INTEGER NOT NULL,
        event_type TEXT NOT NULL,
        message TEXT NOT NULL,
        stage TEXT,
        error_code INTEGER,
        timestamp REAL NOT NULL,
        created_at REAL NOT NULL,
        FOREIGN KEY (backup_job_id) REFERENCES backup_jobs(id) ON DELETE CASCADE
    );
    """)

def _create_indexes(cursor):
    """Create indexes for efficient querying."""
    # Agents
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_agents_hostname ON agents(hostname)")
    cursor.execute("CREATE UNIQUE INDEX IF NOT EXISTS idx_agents_agent_key ON agents(agent_key)")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_agents_last_heartbeat ON agents(last_heartbeat DESC)")

    # Backup jobs
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_backup_jobs_agent ON backup_jobs(agent_id)")
    cursor.execute("CREATE UNIQUE INDEX IF NOT EXISTS idx_backup_jobs_run_id ON backup_jobs(run_id)")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_backup_jobs_set_id ON backup_jobs(backup_set_id)")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_backup_jobs_started ON backup_jobs(started_at DESC)")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_backup_jobs_status ON backup_jobs(status)")

    # Events
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_events_backup_job ON events(backup_job_id)")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_events_timestamp ON events(timestamp DESC)")

def _migrate_schema(conn):
    """Apply schema migrations for existing databases."""
    c = conn.cursor()
    c.execute("PRAGMA table_info(backup_jobs)")
    columns = {row[1] for row in c.fetchall()}
    if 'run_id' not in columns:
        c.execute("ALTER TABLE backup_jobs ADD COLUMN run_id TEXT")
        c.execute("CREATE UNIQUE INDEX IF NOT EXISTS idx_backup_jobs_run_id ON backup_jobs(run_id)")
