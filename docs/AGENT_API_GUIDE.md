# JABS Server Agent Monitoring API Guide

This document describes the HTTP API implemented in [server/app/routes/agent_monitoring.py](../app/routes/agent_monitoring.py)
that any backup agent (JABS's own `agents/backup_agent`, or a custom/third-party agent)
must implement a client for in order to report activity to the JABS dashboard.

It is intended to be a complete, standalone reference — a human or an AI coding
assistant should be able to build a compatible agent client using only this
document, without needing to read the server source.

## Overview

- Base URL: the agent must know the server's base URL (e.g. `http://jabs-server:5001`).
  The reference agent reads this from the `JABS_SERVER_URL` environment variable.
- Transport: plain HTTP/HTTPS, JSON request/response bodies, `Content-Type: application/json`.
- Auth model: there is **no API key/token**. Instead, every request must include
  `hostname` + `ip_address`, and the server validates that:
  1. A host with that `hostname` already exists in the server's `hosts` table
     (hosts are pre-registered by an admin via the dashboard's Hosts page — the
     API does not create new hosts).
  2. The `ip_address` in the request matches the `ip_address` stored for that host.

  If either check fails, the server responds `403`. **This means a new agent
  machine must be registered as a host in the JABS dashboard before it can send
  any events.**
- All endpoints are POST, JSON in and JSON out.
- Timestamps are Unix epoch seconds (float or int).

## Endpoints

### 1. `POST /api/monitoring/events`

The primary endpoint. Used for three purposes, distinguished by `event_type`:

1. **Heartbeat only** (no backup in progress) — omit `backup_set_id`. Used by
   the scheduler or agent to signal "I'm alive" and optionally report agent
   version/type.
2. **Backup progress** — `event_type` such as `"heartbeat"` with a `stage`
   describing what's happening (e.g. `"Starting backup"`, `"Compressing"`).
3. **Backup completion** — `event_type` of `"backup_complete"` (success) or
   `"error"` (failure). This finalizes the backup job record with stats.

#### Request body fields

| Field | Type | Required | Notes |
|---|---|---|---|
| `hostname` | string | **yes** | Must match an existing host record exactly. |
| `ip_address` | string | **yes** | Must match the host's registered IP. |
| `version` | string | no | Agent software version; stored on the host record. |
| `agent_type` | string | no | e.g. `"backup_agent"`; stored on the host record. |
| `event_type` | string | no* | `"heartbeat"`, `"backup_complete"`, or `"error"`. Required for job/event-tracking calls; not needed for plain heartbeats with no `backup_set_id`. |
| `message` | string | no | Human-readable description of the event. |
| `stage` | string | no | Short label for current backup stage (progress events). |
| `timestamp` | number | no | Unix epoch seconds; defaults to server time if omitted. |
| `run_id` | string | no | A UUID unique to a single job *execution*. Used to correlate multiple events (start/progress/complete) belonging to the same run. Strongly recommended. |
| `backup_set_id` | string | no** | Identifier for the backup set/archive produced by this job run. **If omitted, the request is treated as a pure heartbeat** — the server updates the host's heartbeat/version/type and returns immediately without creating/updating any backup job. Required to actually create or update a backup job. |
| `backup_set_name` | string | no | Human-readable name/label for the backup set. |
| `job_name` | string | no*** | The backup job's configured name (e.g. from a job YAML). Required (with `backup_set_id`) to create a backup job. |
| `backup_type` | string | no | e.g. `"full"`, `"incremental"`, `"differential"`. If a later event for the same job upgrades to `"full"`, the server updates the stored type (never downgrades). |
| `source` | string | no | Source path/description being backed up (only used at job creation). |
| `destination` | string | no | Destination path/description (only used at job creation). |
| `encrypt` | boolean | no | Whether the job encrypts output (only used at job creation). |
| `sync` | boolean | no | Whether the job syncs to remote storage, e.g. S3 (only used at job creation). |
| `status` | string | no | For completion events: `"success"` or `"failed"`. Defaults based on `event_type` if omitted. |
| `duration_seconds` | number | no | Total job runtime — stored as `runtime_seconds` (completion events). |
| `files_backed_up` | integer | no | File count processed — stored as `files_count` (completion events). |
| `bytes_backed_up` | integer | no | Total bytes processed (uncompressed) — stored as `bytes_processed` (completion events). |
| `bytes_compressed` | integer | no | Total bytes of the compressed/output archive(s) (completion events). |
| `error_code` | integer | no | Machine-readable error code (error events). |
| `error_message` | string | no | Human-readable error detail (error events). |

\* Required if you want the event stored; omit entirely (and omit `backup_set_id`) for a bare heartbeat.
\** Omitting `backup_set_id` short-circuits to a heartbeat-only response.
\*** Only needed the first time a given `run_id`/job is reported; subsequent events for the same `run_id` reuse the existing backup job.

#### Behavior / server-side logic

1. Validates `hostname` + `ip_address` (see Auth model above). `403` on failure.
2. Updates the host's heartbeat timestamp, and `version`/`agent_type` if provided.
3. If `backup_set_id` is not provided → returns `201 {"success": true}` immediately (heartbeat only).
4. Otherwise, looks up an existing backup job by `run_id` (if provided):
   - If none exists, **creates** a new backup job (status `"running"`) using
     `job_name`, `backup_type`, `run_id`, `backup_set_id`, `backup_set_name`,
     `source`, `destination`, `encrypt`, `sync`.
   - If one exists, reuses it (and upgrades `backup_type` to `"full"` if applicable).
5. Creates an `events` row linked to the backup job (`event_type`, `message`, `stage`, `error_code`, `timestamp`).
6. If `event_type` is `"backup_complete"` or `"error"`, finalizes the backup job:
   sets `status`, `completed_at`, `runtime_seconds`, `files_count`,
   `bytes_processed`, `bytes_compressed`, `error_code`, `error_message`.

#### Responses

- `201 {"success": true}` — heartbeat only (no `backup_set_id`).
- `201 {"success": true, "event_id": <int>, "backup_job_id": <int>}` — event recorded.
- `400 {"error": "Missing required fields: hostname, ip_address"}`
- `403 {"error": "Host '<hostname>' not registered"}`
- `403 {"error": "IP address mismatch for host '<hostname>'"}`
- `500 {"error": "Failed to process event: <detail>"}`

#### Example: backup start (progress heartbeat)

```json
POST /api/monitoring/events
{
  "hostname": "P3Tiny",
  "ip_address": "192.168.1.50",
  "version": "1.4.0",
  "agent_type": "backup_agent",
  "event_type": "heartbeat",
  "message": "Starting full backup for Jim-Home",
  "stage": "Starting backup",
  "run_id": "3f9a...uuid",
  "job_name": "Jim-Home",
  "backup_type": "full",
  "backup_set_id": "Jim-Home-20260720-full",
  "backup_set_name": "Jim-Home 2026-07-20",
  "encrypt": true,
  "sync": true
}
```

#### Example: backup completion (success)

```json
POST /api/monitoring/events
{
  "hostname": "P3Tiny",
  "ip_address": "192.168.1.50",
  "event_type": "backup_complete",
  "message": "Backup Complete",
  "stage": "Completed",
  "status": "success",
  "run_id": "3f9a...uuid",
  "job_name": "Jim-Home",
  "backup_type": "full",
  "backup_set_id": "Jim-Home-20260720-full",
  "backup_set_name": "Jim-Home 2026-07-20",
  "duration_seconds": 842.3,
  "files_backed_up": 128933,
  "bytes_backed_up": 55834574848,
  "bytes_compressed": 21474836480
}
```

#### Example: backup completion (failure)

```json
POST /api/monitoring/events
{
  "hostname": "P3Tiny",
  "ip_address": "192.168.1.50",
  "event_type": "error",
  "message": "Backup 'Jim-Home' failed: disk full",
  "stage": "Error",
  "status": "failed",
  "run_id": "3f9a...uuid",
  "job_name": "Jim-Home",
  "backup_type": "full",
  "backup_set_id": "Jim-Home-20260720-full",
  "error_code": 1,
  "error_message": "disk full"
}
```

#### Example: plain heartbeat (no active job)

```json
POST /api/monitoring/events
{
  "hostname": "P3Tiny",
  "ip_address": "192.168.1.50",
  "version": "1.4.0",
  "agent_type": "backup_agent"
}
```

---

### 2. `POST /api/monitoring/sync-job-sets`

Reconciliation endpoint. Call this whenever the agent locally rotates/deletes
old backup sets for a job (e.g. keeping only the last N sets), so the server's
`backup_jobs` table doesn't accumulate orphaned rows for sets that no longer
exist on the agent.

The server deletes any `backup_jobs` rows for the given host + `job_name`
whose `backup_set_id` is **not** in the `active_backup_set_ids` list you send.
Deleting a backup job cascades to delete its associated `events`.

**Safety note:** if `active_backup_set_ids` is an empty list (or all falsy
values), the server treats this as a no-op and deletes nothing — it will never
wipe all history for a job based on an ambiguous/empty list. Always send the
*complete* current list of backup_set_ids still present in your local
database for that job — not just newly-removed ones.

#### Request body fields

| Field | Type | Required | Notes |
|---|---|---|---|
| `hostname` | string | **yes** | Must match an existing, registered host. |
| `ip_address` | string | **yes** | Must match the host's registered IP. |
| `job_name` | string | **yes** | The job whose backup sets are being reconciled. |
| `active_backup_set_ids` | array of strings | **yes** | Full list of `backup_set_id` values still present locally for this job. Must be a JSON array (can be empty, but empty means "no changes will be made"). |

#### Responses

- `200 {"success": true, "deleted_jobs": <int>}`
- `400 {"error": "Missing required fields: hostname, ip_address, job_name"}`
- `400 {"error": "active_backup_set_ids must be a list"}`
- `403 {"error": "Host '<hostname>' not registered"}`
- `403 {"error": "IP address mismatch for host '<hostname>'"}`
- `500 {"error": "Failed to sync job sets: <detail>"}`

#### Example

```json
POST /api/monitoring/sync-job-sets
{
  "hostname": "P3Tiny",
  "ip_address": "192.168.1.50",
  "job_name": "Jim-Home",
  "active_backup_set_ids": [
    "Jim-Home-20260718-full",
    "Jim-Home-20260719-incr",
    "Jim-Home-20260720-incr"
  ]
}
```

---

## Building a compatible agent client — checklist

1. **Register the host first.** Add the agent's hostname + IP as a host in the
   JABS dashboard's Hosts page before the agent sends anything (no self-registration API exists).
2. Determine `hostname` (must exactly match the registered value) and
   `ip_address` (must exactly match the registered IP) at request time.
3. Generate a `run_id` (e.g. a UUID) once per job execution and include it on
   every event for that run, so the server correlates them into one backup job.
4. Send a start/progress event with `event_type="heartbeat"`, `job_name`,
   `backup_type`, `backup_set_id`, `backup_set_name`, and optionally
   `source`/`destination`/`encrypt`/`sync` — these are only captured the first
   time the job is created for a given `run_id`.
5. Optionally send more progress events reusing the same `run_id` and
   `backup_set_id`, varying `stage`/`message`.
6. On completion, send exactly one event with `event_type="backup_complete"`
   (success) or `event_type="error"` (failure), including `status`,
   `duration_seconds`, `files_backed_up`, `bytes_backed_up`,
   `bytes_compressed` (success), or `error_code`/`error_message` (failure).
7. If your agent performs local retention/rotation of backup sets, call
   `/api/monitoring/sync-job-sets` afterward with the complete current list of
   `backup_set_id`s still retained for that job, so the server prunes anything
   rotated out.
8. For idle periods with no active backup, you may send a bare heartbeat
   (`hostname`/`ip_address`/`version`/`agent_type` only, no `backup_set_id`) to
   keep the host's "online" status and reported version/type current.
9. Treat all requests as fire-and-forget/best-effort from the agent's
   perspective: network failures should be logged and swallowed, not block or
   fail the backup job itself (see the reference implementation's use of
   `requests` with short timeouts and broad `except requests.exceptions.RequestException`).

## Reference implementation

The canonical client implementation for this API is
[agents/backup_agent/monitoring_client.py](../../agents/backup_agent/monitoring_client.py),
which provides `send_event()`, `send_backup_start()`, `send_backup_stage()`,
`send_backup_complete()`, `send_scheduler_check()`, and `sync_job_backup_sets()`
helper functions implementing everything described above.
