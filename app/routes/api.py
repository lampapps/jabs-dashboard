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

from flask import (
    Blueprint, jsonify, request, flash, url_for, current_app
)

from app.settings import (
    BASE_DIR, LOG_DIR, GLOBAL_CONFIG_PATH, MAX_LOG_LINES, VERSION, DATA_DIR
)
from app.utils.logger import sizeof_fmt
from app.models.db_core import get_db_connection

api_bp = Blueprint('api', __name__)

@api_bp.route("/api/events")
def get_events():
    """Return backup jobs with their latest event from normalized schema."""
    try:
        with get_db_connection() as conn:
            c = conn.cursor()
            c.execute("""
                SELECT
                    bj.id,
                    bj.backup_set_id,
                    bj.backup_set_name,
                    h.hostname,
                    bj.job_name,
                    bj.backup_type,
                    bj.encrypt,
                    bj.sync,
                    bj.status,
                    bj.started_at,
                    bj.completed_at,
                    bj.runtime_seconds,
                    latest_e.event_type as latest_event_type,
                    latest_e.message as latest_event_message
                FROM backup_jobs bj
                JOIN hosts h ON bj.host_id = h.id
                LEFT JOIN events latest_e ON latest_e.id = (
                    SELECT id FROM events WHERE backup_job_id = bj.id
                    ORDER BY timestamp DESC, id DESC LIMIT 1
                )
                ORDER BY bj.started_at DESC
            """)

            rows = c.fetchall()
            transformed = []

            for row in rows:
                backup_type = (row['backup_type'] or '').lower()

                # Format backup type for display
                if backup_type == 'dryrun':
                    backup_type_display = 'Dry Run'
                elif backup_type == 'differential':
                    backup_type_display = 'Differential'
                else:
                    backup_type_display = backup_type.capitalize() if backup_type else ''

                # Determine status from job status or latest event type.
                # Trust the job's own (finalized) status once it's no longer
                # "running" — only use the latest event as a fallback while
                # the job is still in progress, so terminal statuses like
                # "skipped" aren't clobbered by a generic "backup_complete"
                # event type.
                status_display = row['status'] or 'running'
                if status_display == 'running':
                    if row['latest_event_type'] == 'error':
                        status_display = 'error'
                    elif row['latest_event_type'] in ('backup_complete',):
                        status_display = 'completed'

                # Show spinner while running, formatted duration when we have
                # one, otherwise a dash for terminal states with no duration
                # (e.g. skipped backups).
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
                    except:
                        runtime_str = '-'
                else:
                    runtime_str = '-'

                # Format event message
                event_text = row['latest_event_message'] or ''

                # Format start time
                start_time_str = datetime.fromtimestamp(row['started_at']).strftime('%Y-%m-%d %H:%M:%S') if row['started_at'] else ''

                transformed_event = {
                    'id': row['id'],
                    'starttimestamp': start_time_str,
                    'host': row['hostname'] or '',
                    'job_name': row['job_name'] or '',
                    'backup_type': backup_type,
                    'event': event_text,
                    'backup_set_name': row['backup_set_name'] or '',
                    'encrypt': 1 if row['encrypt'] else 0,
                    'sync': 1 if row['sync'] else 0,
                    'runtime': runtime_str,
                    'status': status_display,
                    'set_name': row['backup_set_id'] or ''
                }
                transformed.append(transformed_event)

            return jsonify({'data': transformed})
    except Exception as e:
        import traceback
        traceback.print_exc()
        return jsonify({'data': [], 'error': str(e)})

@api_bp.route("/api/backup_sets")
def get_backup_sets():
    """Return one aggregated row per backup set (backup_set_id) for the
    high-level dashboard events table.

    Each backup set may have multiple backup_jobs runs (full/incremental/
    differential) over time; this rolls them up into a single row showing
    the earliest start time, the most recent activity time, and a summary
    of run statuses (e.g. "success:2, error:1").
    """
    try:
        with get_db_connection() as conn:
            c = conn.cursor()
            c.execute("""
                SELECT
                    bj.backup_set_id,
                    bj.backup_set_name,
                    h.id AS host_id,
                    h.hostname,
                    bj.job_name,
                    bj.status,
                    bj.started_at,
                    bj.completed_at
                FROM backup_jobs bj
                JOIN hosts h ON bj.host_id = h.id
                ORDER BY bj.started_at ASC
            """)
            rows = c.fetchall()

            c.execute("""
                SELECT bj.backup_set_id, MAX(e.timestamp) as last_event_time
                FROM events e
                JOIN backup_jobs bj ON e.backup_job_id = bj.id
                GROUP BY bj.backup_set_id
            """)
            last_event_by_set = {row['backup_set_id']: row['last_event_time'] for row in c.fetchall()}

            sets = {}
            for row in rows:
                set_id = row['backup_set_id']
                entry = sets.get(set_id)
                if entry is None:
                    entry = {
                        'backup_set_id': set_id,
                        'backup_set_name': row['backup_set_name'] or set_id,
                        'host': row['hostname'] or '',
                        'host_id': row['host_id'],
                        'job_name': row['job_name'] or '',
                        'start_time': row['started_at'],
                        'last_activity': row['completed_at'] or row['started_at'],
                        'status_counts': {}
                    }
                    sets[set_id] = entry
                else:
                    if row['started_at'] and (entry['start_time'] is None or row['started_at'] < entry['start_time']):
                        entry['start_time'] = row['started_at']
                    activity = row['completed_at'] or row['started_at']
                    if activity and (entry['last_activity'] is None or activity > entry['last_activity']):
                        entry['last_activity'] = activity

                status = row['status'] or 'unknown'
                entry['status_counts'][status] = entry['status_counts'].get(status, 0) + 1

            transformed = []
            for set_id, entry in sets.items():
                last_event_time = last_event_by_set.get(set_id)
                last_activity = entry['last_activity']
                if last_event_time and (last_activity is None or last_event_time > last_activity):
                    last_activity = last_event_time

                status_summary = ', '.join(
                    f"{status}:{count}" for status, count in sorted(entry['status_counts'].items())
                )

                transformed.append({
                    'backup_set_id': set_id,
                    'backup_set_name': entry['backup_set_name'],
                    'host': entry['host'],
                    'host_id': entry['host_id'],
                    'job_name': entry['job_name'],
                    'start_time': datetime.fromtimestamp(entry['start_time']).strftime('%Y-%m-%d %H:%M:%S') if entry['start_time'] else '',
                    'last_event_time': datetime.fromtimestamp(last_activity).strftime('%Y-%m-%d %H:%M:%S') if last_activity else '',
                    'status_summary': status_summary,
                    'status_counts': entry['status_counts']
                })

            transformed.sort(key=lambda x: x['start_time'], reverse=True)

            return jsonify({'data': transformed})
    except Exception as e:
        import traceback
        traceback.print_exc()
        return jsonify({'data': [], 'error': str(e)})

@api_bp.route("/api/agent_jobs/<int:host_id>")
def get_agent_jobs(host_id):
    """Return recent backup jobs for a single host, for the agent_detail page's
    DataTables-driven Recent Jobs table (grouped client-side by backup_set_name).
    """
    try:
        with get_db_connection() as conn:
            c = conn.cursor()
            c.execute("""
                SELECT
                    bj.id,
                    bj.backup_set_id,
                    bj.backup_set_name,
                    bj.job_name,
                    bj.backup_type,
                    bj.encrypt,
                    bj.sync,
                    bj.status,
                    bj.started_at,
                    bj.completed_at,
                    bj.runtime_seconds,
                    bj.files_count,
                    bj.bytes_processed,
                    bj.error_message,
                    latest_e.message as latest_event_message
                FROM backup_jobs bj
                LEFT JOIN events latest_e ON latest_e.id = (
                    SELECT id FROM events WHERE backup_job_id = bj.id
                    ORDER BY timestamp DESC, id DESC LIMIT 1
                )
                WHERE bj.host_id = ?
                ORDER BY bj.started_at DESC
                LIMIT 200
            """, (host_id,))

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

                transformed.append({
                    'id': row['id'],
                    'starttimestamp': start_time_str,
                    'job_name': row['job_name'] or '',
                    'backup_type': backup_type,
                    'event': row['error_message'] or row['latest_event_message'] or '',
                    'backup_set_name': row['backup_set_name'] or row['backup_set_id'] or '',
                    'encrypt': 1 if row['encrypt'] else 0,
                    'sync': 1 if row['sync'] else 0,
                    'runtime': runtime_str,
                    'status': status_display,
                    'files_count': row['files_count'] or 0,
                    'bytes_processed': row['bytes_processed'] or 0
                })

            return jsonify({'data': transformed})
    except Exception as e:
        import traceback
        traceback.print_exc()
        return jsonify({'data': [], 'error': str(e)})

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

    def cache_fresh(cache):
        ts = cache.get("timestamp", 0) if cache else 0
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
        return {"timestamp": time.time(), "data": result}


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
            print(f"Error deleting event {event_id}: {e}")

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
    """Return registered hosts from the hosts table."""
    try:
        with get_db_connection() as conn:
            c = conn.cursor()
            c.execute("""
                SELECT id, hostname, ip_address, agent_version, last_heartbeat, enabled
                FROM hosts
                ORDER BY hostname
            """)
            hosts = [dict(row) for row in c.fetchall()]

        # Format for backward compatibility
        targets = []
        api_statuses = {}

        for host in hosts:
            targets.append({
                'name': host['hostname'],
                'hostname': host['hostname'],
                'ip_address': host['ip_address'],
                'enabled': host['enabled']
            })

            api_statuses[host['hostname']] = {
                'hostname': host['hostname'],
                'version': host['agent_version'],
                'last_seen': datetime.fromtimestamp(host['last_heartbeat']).isoformat() if host['last_heartbeat'] else None,
                'status': 'enabled' if host['enabled'] else 'disabled'
            }

        return jsonify({
            "targets": targets,
            "api_statuses": api_statuses
        })

    except Exception as e:
        return jsonify({"error": str(e)}), 500
