"""API routes for agent monitoring: event reporting.

Agents send events when backups start, progress, and complete.
Each agent authenticates with a unique API key (sent via the `X-API-Key`
header), which the dashboard looks up to identify the host/agent record.
"""

import time
from flask import Blueprint, jsonify, request
from app.models.hosts import get_host_by_agent_key, update_heartbeat, update_agent_version, update_agent_type
from app.models.backup_jobs import (
    create_backup_job, get_backup_job_by_run_id, finalize_backup_job, update_backup_job,
    delete_orphaned_backup_jobs, delete_old_backup_jobs
)
from app.models.events import create_event

agent_monitoring_bp = Blueprint('agent_monitoring', __name__)


def _authenticate_agent():
    """Look up the requesting agent by its API key.

    Returns (host_dict, None) on success, or (None, (json_response, status))
    on failure, so callers can `return error` directly.
    """
    agent_key = request.headers.get('X-API-Key', '').strip()
    if not agent_key:
        return None, (jsonify({"error": "Missing API key (X-API-Key header)"}), 401)

    host = get_host_by_agent_key(agent_key)
    if not host:
        return None, (jsonify({"error": "Invalid API key"}), 403)

    if not host['enabled']:
        return None, (jsonify({"error": f"Host '{host['hostname']}' is disabled"}), 403)

    return host, None


@agent_monitoring_bp.route('/api/monitoring/events', methods=['POST'])
def submit_event():
    """Submit an event from a backup agent."""
    host, error = _authenticate_agent()
    if error:
        return error

    data = request.get_json()

    job_name = data.get('job_name', '').strip()
    run_id = data.get('run_id', '').strip()
    backup_set_id = data.get('backup_set_id', '').strip()
    backup_set_name = data.get('backup_set_name', '').strip()
    backup_type = data.get('backup_type', '').strip()
    event_type = data.get('event_type', '').strip()
    message = data.get('message', '').strip()

    # Step 1: Update host heartbeat and reported version/type
    update_heartbeat(host['id'])
    if data.get('version'):
        update_agent_version(host['id'], data.get('version'))
    if data.get('agent_type'):
        update_agent_type(host['id'], data.get('agent_type'))

    # Scheduler heartbeats have no backup context — just update heartbeat and return
    if not backup_set_id:
        return jsonify({"success": True}), 201

    try:
        # Step 3: Get or create backup job (look up by run_id for per-run uniqueness)
        backup_job = get_backup_job_by_run_id(run_id) if run_id else None

        if not backup_job:
            backup_job_id = create_backup_job(
                host_id=host['id'],
                job_name=job_name,
                backup_type=backup_type,
                run_id=run_id or None,
                backup_set_id=backup_set_id,
                backup_set_name=backup_set_name,
                source=data.get('source', ''),
                destination=data.get('destination', ''),
                encrypt=data.get('encrypt', False),
                sync=data.get('sync', False)
            )
        else:
            backup_job_id = backup_job['id']
            # Only upgrade to full — never downgrade (finalize events carry the original type)
            if backup_type == 'full' and backup_job['backup_type'] != 'full':
                update_backup_job(backup_job_id, backup_type=backup_type)

        # Step 4: Create event record
        event_id = create_event(
            backup_job_id=backup_job_id,
            event_type=event_type,
            message=message,
            stage=data.get('stage'),
            error_code=data.get('error_code'),
            timestamp=data.get('timestamp', time.time())
        )

        # Step 5: Handle completion events
        if event_type in ('backup_complete', 'error'):
            finalize_backup_job(
                backup_job_id=backup_job_id,
                status=data.get('status', 'success' if event_type == 'backup_complete' else 'failed'),
                runtime_seconds=data.get('duration_seconds'),
                files_count=data.get('files_backed_up'),
                bytes_processed=data.get('bytes_backed_up'),
                bytes_compressed=data.get('bytes_compressed'),
                error_code=data.get('error_code'),
                error_message=data.get('error_message')
            )

        return jsonify({
            "success": True,
            "event_id": event_id,
            "backup_job_id": backup_job_id
        }), 201

    except Exception as e:
        return jsonify({"error": f"Failed to process event: {str(e)}"}), 500


@agent_monitoring_bp.route('/api/monitoring/sync-job-sets', methods=['POST'])
def sync_job_sets():
    """Reconcile dashboard-side backup_jobs for a host+job with the agent's own DB.

    Agents call this after rotating old backup sets out of their local database
    (see core/backup/common.rotate_backups). The agent sends the full list of
    backup_set_id values it still has locally for the job; any backup_jobs on
    the dashboard for that host+job whose backup_set_id is NOT in that list are
    considered orphaned (rotated out on the agent) and are deleted here.
    """
    data = request.get_json()

    job_name = data.get('job_name', '').strip()
    active_backup_set_ids = data.get('active_backup_set_ids', [])

    if not job_name:
        return jsonify({"error": "Missing required field: job_name"}), 400

    if not isinstance(active_backup_set_ids, list):
        return jsonify({"error": "active_backup_set_ids must be a list"}), 400

    host, error = _authenticate_agent()
    if error:
        return error

    try:
        deleted_count = delete_orphaned_backup_jobs(host['id'], job_name, active_backup_set_ids)
        return jsonify({"success": True, "deleted_jobs": deleted_count}), 200
    except Exception as e:
        return jsonify({"error": f"Failed to sync job sets: {str(e)}"}), 500


@agent_monitoring_bp.route('/api/monitoring/purge-old-jobs', methods=['POST'])
def purge_old_jobs():
    """Purge dashboard-side backup_jobs older than a retention window.

    For agents that don't do their own set-based rotation like
    file_backup_agent (see sync_job_sets above) — e.g. nas_sync_agent, which
    keeps one ongoing mirror job per pair rather than dated sets — this lets
    the agent simply say "keep the last N days of job records" (matching a
    config value like nas_sync_agent's LOG_RETENTION_DAYS).

    Only finished jobs (with a completed_at) are ever purged this way.

    Request body:
        retention_days (int, required) — delete completed jobs older than this
        job_name (str, optional)       — restrict to a single job name;
                                          omit to apply to all of the host's jobs
    """
    data = request.get_json()

    retention_days = data.get('retention_days')
    job_name = (data.get('job_name') or '').strip() or None

    try:
        retention_days = int(retention_days)
    except (TypeError, ValueError):
        return jsonify({"error": "retention_days must be an integer"}), 400

    if retention_days <= 0:
        return jsonify({"error": "retention_days must be a positive integer"}), 400

    host, error = _authenticate_agent()
    if error:
        return error

    try:
        deleted_count = delete_old_backup_jobs(host['id'], retention_days, job_name)
        return jsonify({"success": True, "deleted_jobs": deleted_count}), 200
    except Exception as e:
        return jsonify({"error": f"Failed to purge old jobs: {str(e)}"}), 500

