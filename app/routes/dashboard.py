"""Flask routes for the JABS dashboard web interface, including agent status and storage views."""

import os
import json
import time
from datetime import datetime, timezone

import requests
import yaml
from cron_descriptor import get_description
from flask import Blueprint, render_template, current_app, abort
from markupsafe import Markup
import mistune

from app.settings import BASE_DIR, CONFIG_DIR, GLOBAL_CONFIG_PATH, ENV_MODE
from app.models.db_core import get_db_connection
from app.utils.logger import sizeof_fmt

dashboard_bp = Blueprint('dashboard', 'dashboard')

def load_storage_config(config_path):
    """Load storage configuration from a YAML file."""
    with open(config_path, "r", encoding="utf-8") as f:
        config = yaml.safe_load(f)
    drives = config.get("drives", [])
    s3_buckets = config.get("s3_buckets", [])
    return drives, s3_buckets

def _get_agents_summary():
    """Query registered hosts + their backup metrics for the Connected Agents card."""
    agents = []
    try:
        with get_db_connection() as conn:
            c = conn.cursor()
            c.execute("""
                SELECT h.id, h.hostname, h.ip_address, h.agent_version, h.agent_type,
                       h.last_heartbeat, h.enabled,
                       CASE
                           WHEN h.last_heartbeat IS NOT NULL AND
                                h.last_heartbeat > ?
                           THEN 'online'
                           ELSE 'offline'
                       END as status
                FROM hosts h
                ORDER BY h.hostname ASC
            """, (time.time() - 3600,))  # Online if heartbeat in last hour
            rows = c.fetchall()

            for row in rows:
                agent_data = dict(row)

                # Get backup metrics for this host (last 30 days)
                c.execute("""
                    SELECT COUNT(*) as total_backups,
                           SUM(CASE WHEN status = 'success' THEN 1 ELSE 0 END) as successful,
                           SUM(CASE WHEN status = 'failed' THEN 1 ELSE 0 END) as failed,
                           MAX(started_at) as last_backup_time,
                           SUM(bytes_processed) as total_bytes
                    FROM backup_jobs
                    WHERE host_id = ? AND started_at > ?
                """, (agent_data['id'], time.time() - 86400 * 30))  # Last 30 days

                metrics = c.fetchone()
                agent_data['metrics'] = {
                    'total_backups': metrics['total_backups'] or 0,
                    'successful': metrics['successful'] or 0,
                    'failed': metrics['failed'] or 0,
                    'last_backup': metrics['last_backup_time'],
                    'total_bytes': metrics['total_bytes'] or 0
                }

                # Job count for the "Jobs" column (all-time, matches Hosts page)
                c.execute("SELECT COUNT(*) as job_count FROM backup_jobs WHERE host_id = ?", (agent_data['id'],))
                agent_data['job_count'] = c.fetchone()['job_count'] or 0

                agents.append(agent_data)
    except Exception as e:
        current_app.logger.error(f"Error loading hosts from database: {e}")
        agents = []
    return agents

def _get_global_stats():
    """Query aggregate backup_jobs totals/status counts and a 30-day activity
    trend across all registered agents, for the dashboard's Stat Cards and
    Activity Trend chart.
    """
    with get_db_connection() as conn:
        c = conn.cursor()

        # Status breakdown (all-time, all hosts)
        c.execute("""
            SELECT COALESCE(status, 'unknown') as status, COUNT(*) as count
            FROM backup_jobs
            GROUP BY status
        """)
        status_counts = {row['status']: row['count'] for row in c.fetchall()}

        # Aggregate totals for the stat cards
        c.execute("""
            SELECT COUNT(*) as total_jobs,
                   SUM(bytes_processed) as total_bytes,
                   SUM(files_count) as total_files,
                   AVG(CASE WHEN status IN ('success', 'completed') THEN runtime_seconds END) as avg_runtime,
                   MAX(started_at) as last_run
            FROM backup_jobs
        """)
        totals = dict(c.fetchone())

        # 30-day activity trend (continuous series, zero-filled for empty days)
        thirty_days_ago = time.time() - 86400 * 30
        c.execute("""
            SELECT date(started_at, 'unixepoch') as day, COUNT(*) as count
            FROM backup_jobs
            WHERE started_at > ?
            GROUP BY day
        """, (thirty_days_ago,))
        daily_counts = {row['day']: row['count'] for row in c.fetchall()}
        trend_labels = []
        trend_data = []
        for i in range(29, -1, -1):
            day = datetime.fromtimestamp(time.time() - 86400 * i).strftime('%Y-%m-%d')
            trend_labels.append(day)
            trend_data.append(daily_counts.get(day, 0))

    return status_counts, totals, trend_labels, trend_data

@dashboard_bp.route("/")
def dashboard():
    """Render the dashboard with connected backup agents and their statuses."""
    agents = _get_agents_summary()
    status_counts, totals, trend_labels, trend_data = _get_global_stats()

    with open('config/global.yaml', encoding="utf-8") as f:
        global_config = yaml.safe_load(f)


    return render_template(
        "index.html",
        agents=agents,
        problems={},
        api_statuses={},
        env_mode=ENV_MODE,
        status_counts=status_counts,
        totals=totals,
        trend_labels=trend_labels,
        trend_data=trend_data,
        sizeof_fmt=sizeof_fmt
    )

@dashboard_bp.route("/partials/agents-card")
def agents_card_partial():
    """Render just the Connected Agents table body, for periodic AJAX refresh on the dashboard."""
    agents = _get_agents_summary()
    return render_template("partials/agents_table.html", agents=agents)

@dashboard_bp.route("/agents/<int:host_id>")
def agent_detail(host_id):
    """Render a detail dashboard for a single registered agent/host.

    Shows aggregate event/status counts, backup-type breakdown, a 30-day
    activity trend, and a recent-jobs table — i.e. everything the agent
    reports to the dashboard for this host.
    """
    with get_db_connection() as conn:
        c = conn.cursor()
        c.execute("""
            SELECT h.*,
                   CASE
                       WHEN h.last_heartbeat IS NOT NULL AND h.last_heartbeat > ?
                       THEN 'online'
                       ELSE 'offline'
                   END as status
            FROM hosts h
            WHERE h.id = ?
        """, (time.time() - 3600, host_id))
        host_row = c.fetchone()
        if not host_row:
            abort(404)
        host = dict(host_row)

        # Status breakdown (all-time) — powers the status doughnut chart
        c.execute("""
            SELECT COALESCE(status, 'unknown') as status, COUNT(*) as count
            FROM backup_jobs
            WHERE host_id = ?
            GROUP BY status
        """, (host_id,))
        status_counts = {row['status']: row['count'] for row in c.fetchall()}

        # Backup type breakdown (all-time) — powers the backup-type bar chart
        c.execute("""
            SELECT COALESCE(backup_type, 'unknown') as backup_type, COUNT(*) as count
            FROM backup_jobs
            WHERE host_id = ?
            GROUP BY backup_type
        """, (host_id,))
        type_counts = {row['backup_type']: row['count'] for row in c.fetchall()}

        # Aggregate totals for the stat cards
        c.execute("""
            SELECT COUNT(*) as total_jobs,
                   SUM(bytes_processed) as total_bytes,
                   SUM(files_count) as total_files,
                   AVG(CASE WHEN status IN ('success', 'completed') THEN runtime_seconds END) as avg_runtime,
                   MAX(started_at) as last_run
            FROM backup_jobs
            WHERE host_id = ?
        """, (host_id,))
        totals = dict(c.fetchone())

        # 30-day activity trend (continuous series, zero-filled for empty days)
        thirty_days_ago = time.time() - 86400 * 30
        c.execute("""
            SELECT date(started_at, 'unixepoch') as day, COUNT(*) as count
            FROM backup_jobs
            WHERE host_id = ? AND started_at > ?
            GROUP BY day
        """, (host_id, thirty_days_ago))
        daily_counts = {row['day']: row['count'] for row in c.fetchall()}
        trend_labels = []
        trend_data = []
        for i in range(29, -1, -1):
            day = datetime.fromtimestamp(time.time() - 86400 * i).strftime('%Y-%m-%d')
            trend_labels.append(day)
            trend_data.append(daily_counts.get(day, 0))

        # Recent jobs are now fetched client-side via /api/agent_jobs/<host_id>
        # for the DataTables-driven Recent Jobs table on agent_detail.html.

    return render_template(
        "agent_detail.html",
        host=host,
        status_counts=status_counts,
        type_counts=type_counts,
        totals=totals,
        trend_labels=trend_labels,
        trend_data=trend_data,
        sizeof_fmt=sizeof_fmt,
        env_mode=ENV_MODE
    )

@dashboard_bp.route("/documentation")
def documentation():
    """Render the documentation page from README.md."""
    readme_path = os.path.join(BASE_DIR, "README.md")
    if not os.path.exists(readme_path):
        content = "<p>README.md not found.</p>"
    else:
        with open(readme_path, "r", encoding="utf-8") as f:
            md_content = f.read()
        markdown_renderer = mistune.create_markdown(renderer=mistune.HTMLRenderer())
        content = Markup(markdown_renderer(md_content))
    return render_template("documentation.html", content=content, env_mode=ENV_MODE)

@dashboard_bp.route("/change_log")
def change_log():
    """Render the documentation page from CHANGELOG.md."""
    changelog_path = os.path.join(BASE_DIR, "CHANGELOG.md")
    if not os.path.exists(changelog_path):
        content = "<CHANGELOG.md not found.</p>"
    else:
        with open(changelog_path, "r", encoding="utf-8") as f:
            md_content = f.read()
        markdown_renderer = mistune.create_markdown(renderer=mistune.HTMLRenderer())
        content = Markup(markdown_renderer(md_content))
    return render_template("change_log.html", content=content, env_mode=ENV_MODE)

@dashboard_bp.route("/license")
def license_page():
    """Render the documentation page from LICENSE.md."""
    license_path = os.path.join(BASE_DIR, "LICENSE.md")
    if not os.path.exists(license_path):
        content = "<LICENSE.md not found.</p>"
    else:
        with open(license_path, "r", encoding="utf-8") as f:
            md_content = f.read()
        markdown_renderer = mistune.create_markdown(renderer=mistune.HTMLRenderer())
        content = Markup(markdown_renderer(md_content))
    return render_template("license.html", content=content, env_mode=ENV_MODE)
