"""API routes for JABS: provides endpoints for disk/S3 usage and system utilities."""

import os
import re
import glob
import json
import shutil
import time
import socket
from concurrent.futures import ThreadPoolExecutor, TimeoutError as FuturesTimeoutError
from datetime import datetime, timedelta, timezone

import yaml
import boto3
from botocore.config import Config as BotoCoreConfig
from croniter import croniter

from flask import (
    Blueprint, jsonify, request, current_app
)

from app.settings import (
    BASE_DIR, LOG_DIR, GLOBAL_CONFIG_PATH, MAX_LOG_LINES, VERSION, DATA_DIR
)
from app.utils.logger import sizeof_fmt
from app.models.db_core import get_db_connection
from app.models.job_schedules import get_all_job_schedules

api_bp = Blueprint('api', __name__)

# How far a job's last actual run may drift from its nearest predicted cron
# occurrence before "Next Event" is flagged as possibly stale/wrong (e.g. a
# nas_sync/dns_backup JOB_CRON config value that no longer matches the real
# crontab entry).
SCHEDULE_DRIFT_TOLERANCE = timedelta(minutes=5)


def _next_event_for_schedule(cron_schedule, last_activity):
    """Return (next_event_dt, drifted) for a comma-separated cron_schedule.

    next_event_dt is the soonest upcoming run across all valid cron
    expressions (None if cron_schedule is empty/entirely invalid). drifted
    is True if the job's last_activity doesn't fall near any expression's
    predicted occurrence, suggesting the reported schedule is stale/wrong.
    """
    if not cron_schedule:
        return None, False

    now = datetime.now()
    next_runs = []
    for expr in cron_schedule.split(','):
        expr = expr.strip()
        if not expr:
            continue
        try:
            next_runs.append(croniter(expr, now).get_next(datetime))
        except (ValueError, KeyError):
            continue

    if not next_runs:
        return None, False

    next_event_dt = min(next_runs)

    drifted = False
    if last_activity:
        last_activity_dt = datetime.fromtimestamp(last_activity)
        for expr in cron_schedule.split(','):
            expr = expr.strip()
            if not expr:
                continue
            try:
                nearest_prev = croniter(expr, last_activity_dt).get_prev(datetime)
            except (ValueError, KeyError):
                continue
            if abs(last_activity_dt - nearest_prev) <= SCHEDULE_DRIFT_TOLERANCE:
                break
        else:
            drifted = True

    return next_event_dt, drifted

@api_bp.route("/api/job_targets")
def get_job_targets():
    """Return one aggregated row per (agent, job_name) for the high-level
    dashboard events table.

    A "job_name" is a stable identifier for one logical, recurring job run
    by an agent — e.g. a sync/backup script's name (local_sync_agent,
    nas_sync_agent) or a restic job (snapshot_agent). A job_name may cover
    multiple job targets (e.g. several source/destination pairs in one run)
    and multiple backup_jobs runs over time; this rolls them all up into a
    single row showing the earliest start time, the most recent activity
    time, and a summary of run statuses (e.g. "success:2, error:1").

    Rows sharing a job_run_id (set once per overall script invocation) are
    first collapsed into a single "run" using that run's earliest started_at
    — this prevents a later pair/target's start time (or any mid-run
    heartbeat/progress event) from being mistaken for the job's actual start.
    Rows without a job_run_id (older agents, or single-target jobs) each form
    their own one-row run, matching prior behavior.
    """
    try:
        with get_db_connection() as conn:
            c = conn.cursor()
            c.execute("""
                SELECT
                    a.id AS agent_id,
                    a.hostname,
                    a.agent_type,
                    bj.job_name,
                    bj.status,
                    bj.started_at,
                    bj.completed_at,
                    bj.job_run_id,
                    bj.id AS backup_job_id
                FROM backup_jobs bj
                JOIN agents a ON bj.agent_id = a.id
                ORDER BY bj.started_at ASC
            """)
            rows = c.fetchall()

            schedules_by_job = get_all_job_schedules()

            # Collapse rows into runs keyed by job_run_id (or this row's own
            # id, when absent) so each run contributes exactly one start time.
            runs = {}
            for row in rows:
                job_key = (row['agent_id'], row['job_name'])
                run_key = (job_key, row['job_run_id'] or row['backup_job_id'])
                run = runs.get(run_key)
                if run is None:
                    run = {'job_key': job_key, 'run_started_at': row['started_at'], 'status_counts': {}}
                    runs[run_key] = run
                elif row['started_at'] and (run['run_started_at'] is None or row['started_at'] < run['run_started_at']):
                    run['run_started_at'] = row['started_at']

                status = row['status'] or 'unknown'
                run['status_counts'][status] = run['status_counts'].get(status, 0) + 1

            jobs = {}
            for run in runs.values():
                key = run['job_key']
                entry = jobs.get(key)
                if entry is None:
                    entry = {
                        'start_time': run['run_started_at'],
                        'last_activity': run['run_started_at'],
                        'status_counts': {}
                    }
                    jobs[key] = entry
                else:
                    if run['run_started_at'] and (entry['start_time'] is None or run['run_started_at'] < entry['start_time']):
                        entry['start_time'] = run['run_started_at']
                    if run['run_started_at'] and (entry['last_activity'] is None or run['run_started_at'] > entry['last_activity']):
                        entry['last_activity'] = run['run_started_at']

                for status, count in run['status_counts'].items():
                    entry['status_counts'][status] = entry['status_counts'].get(status, 0) + count

            # host/agent_type are the same for every row of a given agent_id,
            # so just pick them off the first matching row per job_name.
            host_by_job = {}
            agent_type_by_job = {}
            for row in rows:
                key = (row['agent_id'], row['job_name'])
                host_by_job.setdefault(key, row['hostname'] or '')
                agent_type_by_job.setdefault(key, row['agent_type'] or '')

            transformed = []
            for key, entry in jobs.items():
                last_activity = entry['last_activity']

                status_summary = ', '.join(
                    f"{status}:{count}" for status, count in sorted(entry['status_counts'].items())
                )

                next_event_dt, schedule_drifted = _next_event_for_schedule(
                    schedules_by_job.get(key), last_activity
                )

                transformed.append({
                    'host': host_by_job.get(key, ''),
                    'agent_id': key[0],
                    'agent_type': agent_type_by_job.get(key, ''),
                    'job_name': key[1] or '',
                    'start_time': datetime.fromtimestamp(entry['start_time']).strftime('%Y-%m-%d %H:%M:%S') if entry['start_time'] else '',
                    'last_event_time': datetime.fromtimestamp(last_activity).strftime('%Y-%m-%d %H:%M:%S') if last_activity else '',
                    'next_event': next_event_dt.strftime('%Y-%m-%d %H:%M:%S') if next_event_dt else '',
                    'schedule_drifted': schedule_drifted,
                    'status_summary': status_summary,
                    'status_counts': entry['status_counts']
                })

            transformed.sort(key=lambda x: x['start_time'], reverse=True)

            return jsonify({'data': transformed})
    except Exception as e:
        current_app.logger.error("Error building jobs table data: %s", e, exc_info=True)
        return jsonify({'data': [], 'error': 'Failed to load jobs data'}), 500

@api_bp.route("/api/agent_jobs/<int:agent_id>")
def get_agent_jobs(agent_id):
    """Return recent backup jobs for a single agent, for the agent_detail page's
    DataTables-driven Recent Jobs table (grouped client-side by target_id).
    """
    try:
        with get_db_connection() as conn:
            c = conn.cursor()
            c.execute("""
                SELECT
                    bj.id,
                    bj.target_id,
                    bj.target_label,
                    bj.job_name,
                    bj.backup_type,
                    bj.status,
                    bj.started_at,
                    bj.completed_at,
                    bj.runtime_seconds,
                    bj.files_count,
                    bj.bytes_processed,
                    bj.percent_complete,
                    bj.bytes_per_second,
                    bj.eta_seconds,
                    bj.current_item,
                    bj.error_message,
                    latest_e.message as latest_event_message,
                    final_e.message as final_event_message
                FROM backup_jobs bj
                LEFT JOIN events latest_e ON latest_e.id = (
                    SELECT id FROM events WHERE backup_job_id = bj.id
                    ORDER BY timestamp DESC, id DESC LIMIT 1
                )
                LEFT JOIN events final_e ON final_e.id = (
                    SELECT id FROM events WHERE backup_job_id = bj.id
                      AND event_type IN ('backup_complete', 'error')
                    ORDER BY timestamp DESC, id DESC LIMIT 1
                )
                WHERE bj.agent_id = ?
                ORDER BY bj.started_at DESC
                LIMIT 200
            """, (agent_id,))

            rows = c.fetchall()
            transformed = []

            for row in rows:
                backup_type = (row['backup_type'] or '').lower()

                status_display = row['status'] or 'running'
                if status_display == 'running':
                    pass  # no latest_event_type joined here; job's own status is authoritative

                runtime_str = ''
                if status_display == 'running':
                    runtime_str = '<i class="fas fa-spinner fa-spin"></i>'
                elif row['runtime_seconds']:
                    try:
                        duration = float(row['runtime_seconds'])
                        hours = int(duration // 3600)
                        minutes = int((duration % 3600) // 60)
                        seconds = int(duration % 60)
                        if hours > 0:
                            runtime_str = f"{hours}h {minutes}m {seconds}s"
                        elif minutes > 0:
                            runtime_str = f"{minutes}m {seconds}s"
                        else:
                            runtime_str = f"{seconds}s"
                    except (TypeError, ValueError):
                        runtime_str = '-'
                else:
                    runtime_str = '-'

                start_time_str = datetime.fromtimestamp(row['started_at']).strftime('%Y-%m-%d %H:%M:%S') if row['started_at'] else ''

                # Prefer the terminal (backup_complete/error) event's message once
                # the job is finished, so a post-completion heartbeat (e.g. a
                # quick verify step) never overwrites "Backup/Sync complete" with
                # its own status message.
                if status_display == 'running':
                    event_message = row['latest_event_message'] or ''
                else:
                    event_message = row['final_event_message'] or row['latest_event_message'] or ''

                transformed.append({
                    'id': row['id'],
                    'starttimestamp': start_time_str,
                    'started_at': row['started_at'],
                    'job_name': row['job_name'] or '',
                    'backup_type': backup_type,
                    'event': row['error_message'] or event_message,
                    'target_id': row['target_id'] or '',
                    'target_label': row['target_label'] or row['target_id'] or '',
                    'runtime': runtime_str,
                    'runtime_seconds_raw': row['runtime_seconds'],
                    'status': status_display,
                    'files_count': row['files_count'] or 0,
                    'bytes_processed': row['bytes_processed'] or 0,
                    'percent_complete': row['percent_complete'],
                    'bytes_per_second': row['bytes_per_second'],
                    'eta_seconds': row['eta_seconds'],
                    'current_item': row['current_item'] or ''
                })

            return jsonify({'data': transformed})
    except Exception as e:
        current_app.logger.error("Error loading agent jobs for agent %s: %s", agent_id, e, exc_info=True)
        return jsonify({'data': [], 'error': 'Failed to load agent jobs'}), 500

@api_bp.route("/api/agent_summary/<int:agent_id>")
def get_agent_summary(agent_id):
    """Return the agent_detail page's stat-card/summary numbers, for periodic
    AJAX refresh (so e.g. the Running count updates without a full reload).
    """
    try:
        with get_db_connection() as conn:
            c = conn.cursor()
            c.execute("""
                SELECT COALESCE(status, 'unknown') as status, COUNT(*) as count
                FROM backup_jobs WHERE agent_id = ? GROUP BY status
            """, (agent_id,))
            status_counts = {row['status']: row['count'] for row in c.fetchall()}

            c.execute("""
                SELECT COUNT(*) as total_jobs,
                       SUM(bytes_processed) as total_bytes,
                       SUM(files_count) as total_files,
                       AVG(CASE WHEN status IN ('success', 'completed') THEN runtime_seconds END) as avg_runtime,
                       MAX(started_at) as last_run
                FROM backup_jobs WHERE agent_id = ?
            """, (agent_id,))
            totals = dict(c.fetchone())

            avg_runtime = totals['avg_runtime']
            avg_runtime_str = f"{int(avg_runtime // 60)}m {int(avg_runtime % 60)}s" if avg_runtime else '—'
            last_run_str = datetime.fromtimestamp(totals['last_run']).strftime('%Y-%m-%d %H:%M:%S') if totals['last_run'] else '—'

            return jsonify({
                'total_jobs': totals['total_jobs'] or 0,
                'success': (status_counts.get('success', 0) + status_counts.get('completed', 0)),
                'errors': (status_counts.get('error', 0) + status_counts.get('failed', 0)),
                'running': status_counts.get('running', 0),
                'stopped': status_counts.get('stopped', 0),
                'purged': status_counts.get('purged', 0),
                'total_files': totals['total_files'] or 0,
                'total_bytes_fmt': sizeof_fmt(totals['total_bytes'] or 0),
                'avg_runtime_fmt': avg_runtime_str,
                'last_run_fmt': last_run_str
            })
    except Exception as e:
        current_app.logger.error("Error loading agent summary for agent %s: %s", agent_id, e, exc_info=True)
        return jsonify({'error': 'Failed to load agent summary'}), 500

@api_bp.route('/data/dashboard/events.json')
def serve_events():
    """Serve the events from the database in JSON format."""
    try:
        with get_db_connection() as conn:
            c = conn.cursor()
            c.execute("SELECT * FROM events ORDER BY timestamp DESC LIMIT 100")
            events = [dict(row) for row in c.fetchall()]
        return jsonify(events)
    except Exception:
        return jsonify([])

@api_bp.route('/api/disk_usage')
def get_disk_usage():
    """Return disk usage statistics for configured drives."""
    import concurrent.futures
    import threading
    import time
    
    try:
        with open(GLOBAL_CONFIG_PATH, "r", encoding="utf-8") as f:
            global_config = yaml.safe_load(f)
            drives = global_config.get("drives", [])
            drive_labels = {
                d['path']: d.get('label', d['path'])
                for d in global_config.get('drives', [])
            }
    except FileNotFoundError:
        return jsonify({"error": f"Configuration file {GLOBAL_CONFIG_PATH} not found."}), 404
    except yaml.YAMLError as e:
        return jsonify({"error": f"Error parsing {GLOBAL_CONFIG_PATH}: {str(e)}"}), 500
    
    def check_drive_usage_with_timeout(drive_path, timeout=3):
        """Check disk usage for a single drive with individual timeout."""
        result = [None]
        exception = [None]
        
        def target():
            try:
                result[0] = shutil.disk_usage(drive_path)
            except (FileNotFoundError, OSError) as e:
                exception[0] = e
        
        thread = threading.Thread(target=target)
        thread.daemon = True
        thread.start()
        thread.join(timeout)
        
        if thread.is_alive():
            # Thread is still running, meaning it timed out
            raise TimeoutError(f"Drive check for {drive_path} timed out after {timeout} seconds")
        
        if exception[0]:
            raise exception[0]
        
        if result[0] is None:
            raise Exception("Unknown error occurred during drive check")
            
        return result[0]
    
    disk_usage = []
    
    # Use ThreadPoolExecutor with shorter overall timeout
    with concurrent.futures.ThreadPoolExecutor(max_workers=min(len(drives), 5)) as executor:
        # Submit all drive checks with individual 3-second timeouts
        future_to_drive = {}
        for drive in drives:
            future = executor.submit(check_drive_usage_with_timeout, drive['path'], 3)
            future_to_drive[future] = drive
        
        # Process completed futures within a 5-second overall timeout
        completed_futures = set()
        try:
            for future in concurrent.futures.as_completed(future_to_drive, timeout=5):
                completed_futures.add(future)
                drive = future_to_drive[future]
                label = drive_labels.get(drive['path'], drive['path'])
                
                try:
                    total, used, free = future.result()
                    disk_usage.append({
                        "drive": label,
                        "total_gib": round(total / (1024 ** 3), 2),
                        "used_gib": round(used / (1024 ** 3), 2),
                        "free_gib": round(free / (1024 ** 3), 2),
                        "percent_used": round((used / total) * 100, 2)
                    })
                except TimeoutError:
                    disk_usage.append({
                        "drive": label,
                        "error": "Drive check timed out (network issue or slow drive)"
                    })
                except (FileNotFoundError, OSError) as e:
                    # Handle various error conditions gracefully
                    if "Host is down" in str(e):
                        error_msg = "Network drive unavailable (host is down)"
                    elif "No such file or directory" in str(e):
                        error_msg = "Drive not found or inaccessible"
                    else:
                        error_msg = f"Error accessing drive: {str(e)}"
                        
                    disk_usage.append({
                        "drive": label,
                        "error": error_msg
                    })
        except concurrent.futures.TimeoutError:
            # Handle overall timeout - some futures didn't complete within 5 seconds
            pass
        
        # Handle any drives that didn't complete within the timeout
        for future, drive in future_to_drive.items():
            if future not in completed_futures:
                label = drive_labels.get(drive['path'], drive['path'])
                disk_usage.append({
                    "drive": label,
                    "error": "Drive check timed out (possibly network issue)"
                })
    
    return jsonify(disk_usage)

@api_bp.route('/api/s3_usage')
def get_s3_usage():
    """Return S3 bucket sizes. Serves from cache if fresh; refreshes in background if stale."""
    S3_CACHE_FILE = os.path.join(DATA_DIR, "s3_usage_cache.json")
    S3_CACHE_TTL = 1 * 3600  # 1 hours

    session = boto3.Session()
    credentials = session.get_credentials()
    if credentials is None or not credentials.access_key or not credentials.secret_key:
        return jsonify({"error": "AWS credentials not found."}), 403

    try:
        with open(GLOBAL_CONFIG_PATH, "r", encoding="utf-8") as f:
            config = yaml.safe_load(f)
            s3_buckets = config.get("s3_buckets", [])
            region = config.get("aws", {}).get("region", "us-east-1")
    except FileNotFoundError:
        return jsonify({"error": f"Configuration file {GLOBAL_CONFIG_PATH} not found."}), 404
    except yaml.YAMLError as e:
        return jsonify({"error": f"Error parsing {GLOBAL_CONFIG_PATH}: {str(e)}"}), 500

    boto_cfg = BotoCoreConfig(connect_timeout=5, read_timeout=15, retries={"max_attempts": 1})

    def load_cache():
        try:
            with open(S3_CACHE_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except (OSError, ValueError):
            return None

    def save_cache(data):
        try:
            os.makedirs(DATA_DIR, exist_ok=True)
            with open(S3_CACHE_FILE, "w", encoding="utf-8") as f:
                json.dump(data, f)
        except OSError:
            pass

    configured_buckets = sorted(
        bucket.get("bucket") if isinstance(bucket, dict) else bucket
        for bucket in s3_buckets
    )

    def cache_fresh(cache):
        if not cache:
            return False
        ts = cache.get("timestamp", 0)
        # Invalidate immediately if the configured bucket list changed, regardless of TTL
        if cache.get("buckets") != configured_buckets:
            return False
        return (time.time() - ts) < S3_CACHE_TTL

    def get_bucket_breakdown(bucket_name):
        """Scan a bucket and group object sizes by host (top-level prefix)
        and job (second-level prefix), matching the '<host>/<job>/<backup_set>/<file>'
        key layout used by backup agents. Returns a list of prefix dicts with
        size_bytes, suitable for a stacked chart.
        """
        s3 = session.client("s3", config=boto_cfg)
        paginator = s3.get_paginator("list_objects_v2")

        # host -> {"total": bytes, "jobs": {job -> bytes}}
        hosts = {}
        root_bytes = 0

        for page in paginator.paginate(Bucket=bucket_name):
            for obj in page.get("Contents", []):
                size = obj["Size"]
                parts = obj["Key"].split("/", 2)
                if len(parts) < 2 or not parts[0]:
                    # No host/job structure (root-level object)
                    root_bytes += size
                    continue

                host = parts[0]
                job = parts[1] if len(parts) > 1 and parts[1] else "(other)"

                entry = hosts.setdefault(host, {"total": 0, "jobs": {}})
                entry["total"] += size
                entry["jobs"][job] = entry["jobs"].get(job, 0) + size

        prefixes = []
        for host, entry in hosts.items():
            sub_prefixes = [
                {"prefix": job, "size_bytes": job_bytes}
                for job, job_bytes in entry["jobs"].items()
            ]
            prefixes.append({
                "prefix": host,
                "size_bytes": entry["total"],
                "sub_prefixes": sub_prefixes
            })

        if root_bytes:
            prefixes.append({"prefix": "(root)", "size_bytes": root_bytes, "sub_prefixes": []})

        return prefixes

    def build_fresh_data():
        result = []
        with ThreadPoolExecutor(max_workers=len(s3_buckets) or 1) as executor:
            futures = {}
            for bucket in s3_buckets:
                bucket_name = bucket.get("bucket") if isinstance(bucket, dict) else bucket
                label = bucket.get("label", bucket_name) if isinstance(bucket, dict) else bucket_name
                futures[executor.submit(get_bucket_breakdown, bucket_name)] = (bucket_name, label)
            for future, (bucket_name, label) in futures.items():
                try:
                    prefixes = future.result(timeout=300)
                    result.append({
                        "bucket": bucket_name,
                        "label": label,
                        "prefixes": prefixes
                    })
                except Exception as e:
                    result.append({"bucket": bucket_name, "label": label, "error": str(e)})
        return {"timestamp": time.time(), "buckets": configured_buckets, "data": result}


    cache = load_cache()
    if cache_fresh(cache):
        return jsonify(cache["data"])

    # Stale or missing: return stale data immediately while refreshing in background
    if cache:
        def refresh_cache():
            fresh = build_fresh_data()
            save_cache(fresh)
        ThreadPoolExecutor(max_workers=1).submit(refresh_cache)
        return jsonify(cache["data"])

    # No cache at all — must block and build it now
    fresh = build_fresh_data()
    save_cache(fresh)
    return jsonify(fresh["data"])

@api_bp.route('/api/trim_logs', methods=['POST'])
def trim_logs():
    """Trim log files in the log directory to a maximum number of lines."""
    log_dir = LOG_DIR
    max_lines = MAX_LOG_LINES
    if not os.path.exists(log_dir):
        return jsonify({"error": "Log directory does not exist"}), 404
    trimmed_logs = []
    log_files = glob.glob(f"{log_dir}/*.log")
    if not log_files:
        return jsonify({"error": "No log files found in the logs directory"}), 404
    for log_file in log_files:
        try:
            with open(log_file, "r", encoding="utf-8") as f:
                lines = f.readlines()
            if len(lines) > max_lines:
                with open(log_file, "w", encoding="utf-8") as f:
                    f.writelines(lines[-max_lines:])
                trimmed_logs.append({"file": log_file, "status": "trimmed"})
            else:
                trimmed_logs.append({"file": log_file, "status": "not trimmed (already small)"})
        except OSError as e:
            trimmed_logs.append({"file": log_file, "status": f"error: {str(e)}"})
    return jsonify({"trimmed_logs": trimmed_logs})

@api_bp.route('/api/purge_log/<log_name>', methods=['POST'])
def purge_log(log_name):
    """Purge the contents of a log file, only allowing .log files."""
    if not re.match(r'^[\w\-.]+\.log$', log_name):
        return jsonify({"success": False, "error": "Invalid log name"}), 400
    log_path = os.path.join(LOG_DIR, log_name)
    if not os.path.exists(log_path):
        return jsonify({"success": False, "error": "Log not found"}), 404
    try:
        with open(log_path, "w", encoding="utf-8") as f:
            f.truncate(0)
        return jsonify({"success": True})
    except OSError as e:
        return jsonify({"success": False, "error": str(e)}), 500

@api_bp.route("/api/events/delete", methods=["POST"])
def delete_events():
    """Delete events by ID from the database."""
    data = request.get_json()
    ids = data.get('ids', [])
    if not ids:
        return jsonify({"message": "No IDs provided."}), 400

    deleted_count = 0

    # Delete events
    for event_id in ids:
        try:
            with get_db_connection() as conn:
                c = conn.cursor()
                c.execute("DELETE FROM events WHERE id = ?", (event_id,))
                conn.commit()
                if c.rowcount > 0:
                    deleted_count += 1
        except Exception as e:
            current_app.logger.error("Error deleting event %s: %s", event_id, e, exc_info=True)

    current_app.logger.info("Deleted %d event(s) (requested ids: %s)", deleted_count, ids)

    return jsonify({
        "success": True,
        "deleted": deleted_count,
        "message": f"Successfully deleted {deleted_count} event(s)."
    })

@api_bp.route("/api/backup_jobs/delete", methods=["POST"])
def delete_backup_jobs():
    """Delete backup jobs by ID. Related events are removed via CASCADE."""
    data = request.get_json()
    ids = data.get('ids', [])
    if not ids:
        return jsonify({"message": "No IDs provided."}), 400

    deleted_count = 0
    with get_db_connection() as conn:
        c = conn.cursor()
        for job_id in ids:
            try:
                c.execute("DELETE FROM backup_jobs WHERE id = ?", (job_id,))
                if c.rowcount > 0:
                    deleted_count += 1
            except Exception as e:
                current_app.logger.error(f"Error deleting backup job {job_id}: {e}")
        conn.commit()

    current_app.logger.info("Deleted %d backup job(s) (requested ids: %s)", deleted_count, ids)

    return jsonify({
        "success": True,
        "deleted": deleted_count,
        "message": f"Successfully deleted {deleted_count} job(s)."
    })


@api_bp.route("/api/heartbeat")
def heartbeat():
    """Return basic health/status info for this JABS instance."""
    # Count events with error type from database
    try:
        conn = get_db_connection()
        c = conn.cursor()
        c.execute("SELECT COUNT(*) FROM events WHERE event_type = 'error'")
        error_event_count = c.fetchone()[0]
        conn.close()
    except Exception:
        error_event_count = 0

    return jsonify({
        "hostname": socket.gethostname(),
        "version": VERSION,
        "status": "ok",
        "error_event_count": error_event_count
    })

@api_bp.route('/api/monitor_targets')
def get_monitor_targets():
    """Return registered agents from the agents table."""
    try:
        with get_db_connection() as conn:
            c = conn.cursor()
            c.execute("""
                SELECT id, hostname, ip_address, agent_version, last_heartbeat, enabled
                FROM agents
                ORDER BY hostname
            """)
            agents = [dict(row) for row in c.fetchall()]

        # Format for backward compatibility
        targets = []
        api_statuses = {}

        for agent in agents:
            targets.append({
                'name': agent['hostname'],
                'hostname': agent['hostname'],
                'ip_address': agent['ip_address'],
                'enabled': agent['enabled']
            })

            api_statuses[agent['hostname']] = {
                'hostname': agent['hostname'],
                'version': agent['agent_version'],
                'last_seen': datetime.fromtimestamp(agent['last_heartbeat']).isoformat() if agent['last_heartbeat'] else None,
                'status': 'enabled' if agent['enabled'] else 'disabled'
            }

        return jsonify({
            "targets": targets,
            "api_statuses": api_statuses
        })

    except Exception as e:
        return jsonify({"error": str(e)}), 500
