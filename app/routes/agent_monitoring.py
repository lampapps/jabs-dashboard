"""API routes for agent monitoring: event reporting.

Agents send events when backups start, progress, and complete.
Each agent authenticates with a unique API key (sent via the `X-API-Key`
header), which the dashboard looks up to identify the agent record.
"""

import time
from flask import Blueprint, jsonify, request
from app.models.agents import get_agent_by_agent_key, update_heartbeat, update_agent_version, update_agent_type
from app.models.backup_jobs import (
    create_backup_job, get_backup_job_by_run_id, finalize_backup_job, update_backup_job,
    mark_backup_jobs_purged
)
from app.models.events import create_event

agent_monitoring_bp = Blueprint('agent_monitoring', __name__)


def _authenticate_agent():
    """Look up the requesting agent by its API key.

    Returns (agent_dict, None) on success, or (None, (json_response, status))
    on failure, so callers can `return error` directly.
    """
    agent_key = request.headers.get('X-API-Key', '').strip()
    if not agent_key:
        return None, (jsonify({"error": "Missing API key (X-API-Key header)"}), 401)

    agent = get_agent_by_agent_key(agent_key)
    if not agent:
        return None, (jsonify({"error": "Invalid API key"}), 403)

    if not agent['enabled']:
        return None, (jsonify({"error": f"Agent '{agent['hostname']}' is disabled"}), 403)

    return agent, None


@agent_monitoring_bp.route('/api/monitoring/events', methods=['POST'])
def submit_event():
    """Submit an event from a backup agent."""
    agent, error = _authenticate_agent()
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

    # Step 1: Update agent heartbeat and reported version/type
    update_heartbeat(agent['id'])
    if data.get('version'):
        update_agent_version(agent['id'], data.get('version'))
    if data.get('agent_type'):
        update_agent_type(agent['id'], data.get('agent_type'))

    # Scheduler heartbeats have no backup context — just update heartbeat and return
    if not backup_set_id:
        return jsonify({"success": True}), 201

    try:
        # Step 3: Get or create backup job (look up by run_id for per-run uniqueness)
        backup_job = get_backup_job_by_run_id(run_id) if run_id else None

        if not backup_job:
            backup_job_id = create_backup_job(
                agent_id=agent['id'],
                job_name=job_name,
                backup_type=backup_type,
                run_id=run_id or None,
                backup_set_id=backup_set_id,
                backup_set_name=backup_set_name,
                source=data.get('source', ''),
                destination=data.get('destination', '')
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


@agent_monitoring_bp.route('/api/monitoring/backup-set-purged', methods=['POST'])
def backup_set_purged():
    """Record that an agent has locally rotated (deleted) a backup set.

    Marks every backup_jobs row sharing this backup_set_id for the
    authenticated agent with status='purged' and logs a 'purged' event on
    each — it does NOT delete any rows. The dashboard's own time-based
    retention policy (see app/services/retention.py) is solely responsible
    for actually deleting old rows, on its own schedule. Call this right
    after successfully deleting a backup set's local files (and, for
    file_backup_agent, its own DB records).

    A single backup_set_id may be shared by multiple backup_jobs rows (a
    full backup plus its incremental/differential children) — all of them
    are marked together.
    """
    data = request.get_json()

    backup_set_id = (data.get('backup_set_id') or '').strip()
    message = (data.get('message') or '').strip() or 'Backup set purged by agent'
    timestamp = data.get('timestamp', time.time())

    if not backup_set_id:
        return jsonify({"error": "Missing required field: backup_set_id"}), 400

    agent, error = _authenticate_agent()
    if error:
        return error

    try:
        job_ids = mark_backup_jobs_purged(agent['id'], backup_set_id)
        for job_id in job_ids:
            create_event(backup_job_id=job_id, event_type='purged', message=message, timestamp=timestamp)
        return jsonify({"success": True, "purged_jobs": len(job_ids)}), 200
    except Exception as e:
        return jsonify({"error": f"Failed to record backup set purge: {str(e)}"}), 500

