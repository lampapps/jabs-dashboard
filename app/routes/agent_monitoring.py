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
    update_backup_job_progress, mark_backup_jobs_purged
)
from app.models.events import create_event
from app.models.job_schedules import upsert_job_schedule

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
    job_run_id = (data.get('job_run_id') or '').strip()
    target_id = data.get('target_id', '').strip()
    target_label = data.get('target_label', '').strip()
    backup_type = data.get('backup_type', '').strip()
    event_type = data.get('event_type', '').strip()
    message = data.get('message', '').strip()

    # Step 1: Update agent heartbeat and reported version/type
    update_heartbeat(agent['id'])
    if data.get('version'):
        update_agent_version(agent['id'], data.get('version'))
    if data.get('agent_type'):
        update_agent_type(agent['id'], data.get('agent_type'))

    # Optional, reported independently of any job run — a comma-separated
    # list of cron expressions covering job_name, used for the dashboard's
    # "Next Event" column.
    cron_schedule = (data.get('cron_schedule') or '').strip()
    if cron_schedule and job_name:
        upsert_job_schedule(agent['id'], job_name, cron_schedule)

    # Scheduler heartbeats have no job context — just update heartbeat and return
    if not target_id:
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
                target_id=target_id,
                target_label=target_label,
                source=data.get('source', ''),
                destination=data.get('destination', ''),
                job_run_id=job_run_id or None
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

        # Step 5: Handle completion events. duration_seconds is only ever sent
        # by an agent's actual backup/sync-complete call — a post-completion
        # heartbeat/error event (e.g. a quick verify step) never includes it,
        # so this won't re-finalize (and overwrite the outcome of) a job that
        # already finished.
        is_finalize = event_type in ('backup_complete', 'error') and data.get('duration_seconds') is not None
        if is_finalize:
            finalize_backup_job(
                backup_job_id=backup_job_id,
                status=data.get('status', 'success' if event_type == 'backup_complete' else 'failed'),
                runtime_seconds=data.get('duration_seconds'),
                files_count=data.get('files_backed_up'),
                bytes_processed=data.get('bytes_backed_up'),
                bytes_compressed=data.get('bytes_compressed'),
                error_code=data.get('error_code'),
                error_message=data.get('error_message'),
                external_id=(data.get('external_id') or '').strip() or None
            )
        else:
            # Optional, best-effort mid-run progress fields — agents may send
            # any subset of these (or none) on a plain heartbeat event.
            progress_fields = (
                'percent_complete', 'bytes_per_second', 'eta_seconds', 'current_item',
                'files_backed_up', 'bytes_backed_up'
            )
            if any(data.get(f) is not None for f in progress_fields):
                update_backup_job_progress(
                    backup_job_id=backup_job_id,
                    percent_complete=data.get('percent_complete'),
                    bytes_per_second=data.get('bytes_per_second'),
                    eta_seconds=data.get('eta_seconds'),
                    current_item=data.get('current_item'),
                    files_count=data.get('files_backed_up'),
                    bytes_processed=data.get('bytes_backed_up')
                )

        return jsonify({
            "success": True,
            "event_id": event_id,
            "backup_job_id": backup_job_id
        }), 201

    except Exception as e:
        return jsonify({"error": f"Failed to process event: {str(e)}"}), 500


@agent_monitoring_bp.route('/api/monitoring/target-purged', methods=['POST'])
def target_purged():
    """Record that an agent has locally deleted specific rotated-out
    artifacts belonging to a job target (e.g. a pruned restic snapshot, a
    deleted dated image file).

    Marks every backup_jobs row for the authenticated agent whose target_id
    matches and whose external_id is in external_ids with status='purged',
    and logs a 'purged' event on each — it does NOT delete any rows. The
    dashboard's own time-based retention policy (see
    app/services/retention.py) is solely responsible for actually deleting
    old rows, on its own schedule. Call this right after successfully
    deleting the underlying artifact(s), passing back the same external_id
    value(s) reported on the original backup_complete event.
    """
    data = request.get_json()

    target_id = (data.get('target_id') or '').strip()
    external_ids = [str(x).strip() for x in (data.get('external_ids') or []) if str(x).strip()]
    message = (data.get('message') or '').strip() or 'Job target artifact(s) purged by agent'
    timestamp = data.get('timestamp', time.time())

    if not target_id:
        return jsonify({"error": "Missing required field: target_id"}), 400
    if not external_ids:
        return jsonify({"error": "Missing required field: external_ids (non-empty list)"}), 400

    agent, error = _authenticate_agent()
    if error:
        return error

    try:
        job_ids = mark_backup_jobs_purged(agent['id'], target_id, external_ids)
        for job_id in job_ids:
            create_event(backup_job_id=job_id, event_type='purged', message=message, timestamp=timestamp)
        return jsonify({"success": True, "purged_jobs": len(job_ids)}), 200
    except Exception as e:
        return jsonify({"error": f"Failed to record job target purge: {str(e)}"}), 500

