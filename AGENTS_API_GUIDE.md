# JABS Dashboard Agent Monitoring API Guide

This document describes the HTTP API implemented in [app/routes/agent_monitoring.py](../app/routes/agent_monitoring.py)
that any backup agent (JABS's own `file_backup_agent`, or a custom/third-party agent)
must implement a client for in order to report activity to the JABS dashboard.

It is intended to be a complete, standalone reference — a human or an AI coding
assistant should be able to build a compatible agent client using only this
document, without needing to read the dashboard source.

## Overview

- Base URL: the agent must know the dashboard's base URL (e.g. `http://jabs-dashboard:5001`).
  The reference agent reads this from the `JABS_DASHBOARD_URL` environment variable
  (the older `JABS_SERVER_URL` name is still accepted as a deprecated alias).
- Transport: plain HTTP/HTTPS, JSON request/response bodies, `Content-Type: application/json`.
- Auth model: **API key**, sent on every request via the `X-API-Key` header.
  1. An admin registers each agent instance on the dashboard's Agents page,
     which generates a unique `agent_key` and returns it once (also shown in
     the Agents table, with a regenerate option).
  2. The agent stores that key (e.g. `JABS_AGENT_KEY` in its `.env`) and
     sends it as `X-API-Key: <key>` on every request.
  3. The dashboard looks up the agent by that key; it does not use
     `hostname`/`ip_address` for authentication. Multiple agents can run on
     the same machine (and share the same `hostname`/`ip_address`) as long
     as each has its own key.

  If the header is missing, respond `401`. If the key doesn't match any
  registered agent (or that agent is disabled), respond `403`. **This means a
  new agent must be registered on the JABS dashboard (obtaining a key)
  before it can send any events.**
- `hostname` / `ip_address` in the request body are still accepted and
  stored for display purposes (e.g. shown on the Agents/agent detail pages)
  but are **not** used for authentication.
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
| --- | --- | --- | --- |
| `hostname` | string | no | Informational, shown on the Agents pages. Not used for auth — set via the `X-API-Key` header instead. |
| `ip_address` | string | no | Informational only. |
| `version` | string | no | Agent software version; stored on the agent record. |
| `agent_type` | string | no | e.g. `"backup_agent"`; stored on the agent record. |
| `event_type` | string | no* | `"heartbeat"`, `"backup_complete"`, or `"error"`. Required for job/event-tracking calls; not needed for plain heartbeats with no `backup_set_id`. |
| `message` | string | no | Human-readable description of the event. |
| `stage` | string | no | Short label for current backup stage (progress events). |
| `timestamp` | number | no | Unix epoch seconds; defaults to dashboard time if omitted. |
| `run_id` | string | no | A UUID unique to a single job *execution*. Used to correlate multiple events (start/progress/complete) belonging to the same run. Strongly recommended. |
| `backup_set_id` | string | no** | Identifier for the backup set/archive produced by this job run. **If omitted, the request is treated as a pure heartbeat** — the dashboard updates the agent's heartbeat/version/type and returns immediately without creating/updating any backup job. Required to actually create or update a backup job. |
| `backup_set_name` | string | no | Human-readable name/label for the backup set. |
| `job_name` | string | no*** | The backup job's configured name (e.g. from a job YAML). Required (with `backup_set_id`) to create a backup job. |
| `backup_type` | string | no | e.g. `"full"`, `"incremental"`, `"differential"`. If a later event for the same job upgrades to `"full"`, the dashboard updates the stored type (never downgrades). |
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

#### Behavior / dashboard-side logic

1. Validates the `X-API-Key` header against the dashboard's registered agents (see Auth model above). `401` if missing, `403` if invalid/disabled.
2. Updates the agent's heartbeat timestamp, and `version`/`agent_type` if provided.
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
- `401 {"error": "Missing API key (X-API-Key header)"}`
- `403 {"error": "Invalid API key"}`
- `403 {"error": "Agent '<hostname>' is disabled"}`
- `500 {"error": "Failed to process event: <detail>"}`

#### Example: backup start (progress heartbeat)

```json
POST /api/monitoring/events
X-API-Key: 9f2c6b1a4e8d3f0c7a5b2e1d6c4f8a90b3d7e2c1
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
X-API-Key: 9f2c6b1a4e8d3f0c7a5b2e1d6c4f8a90b3d7e2c1
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
X-API-Key: 9f2c6b1a4e8d3f0c7a5b2e1d6c4f8a90b3d7e2c1
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
X-API-Key: 9f2c6b1a4e8d3f0c7a5b2e1d6c4f8a90b3d7e2c1
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
old backup sets for a job (e.g. keeping only the last N sets), so the dashboard's
`backup_jobs` table doesn't accumulate orphaned rows for sets that no longer
exist on the agent.

The dashboard deletes any `backup_jobs` rows for the given agent + `job_name`
whose `backup_set_id` is **not** in the `active_backup_set_ids` list you send.
Deleting a backup job cascades to delete its associated `events`.

**Safety note:** if `active_backup_set_ids` is an empty list (or all falsy
values), the dashboard treats this as a no-op and deletes nothing — it will never
wipe all history for a job based on an ambiguous/empty list. Always send the
*complete* current list of backup_set_ids still present in your local
database for that job — not just newly-removed ones.

#### Request body fields

| Field | Type | Required | Notes |
| --- | --- | --- | --- |
| `job_name` | string | **yes** | The job whose backup sets are being reconciled. |
| `active_backup_set_ids` | array of strings | **yes** | Full list of `backup_set_id` values still present locally for this job. Must be a JSON array (can be empty, but empty means "no changes will be made"). |

#### Responses

- `200 {"success": true, "deleted_jobs": <int>}`
- `400 {"error": "Missing required field: job_name"}`
- `400 {"error": "active_backup_set_ids must be a list"}`
- `401 {"error": "Missing API key (X-API-Key header)"}`
- `403 {"error": "Invalid API key"}`
- `500 {"error": "Failed to sync job sets: <detail>"}`

#### Example

```json
POST /api/monitoring/sync-job-sets
X-API-Key: 9f2c6b1a4e8d3f0c7a5b2e1d6c4f8a90b3d7e2c1
{
  "job_name": "Jim-Home",
  "active_backup_set_ids": [
    "Jim-Home-20260718-full",
    "Jim-Home-20260719-incr",
    "Jim-Home-20260720-incr"
  ]
}
```

---

### 3. `POST /api/monitoring/purge-old-jobs`

Time-based retention endpoint, as an alternative to `sync-job-sets` for agents
that don't rotate discrete, identifiable backup sets (e.g. `nas_sync_agent`,
which keeps one ongoing mirror job per pair rather than dated sets). Call this
periodically (e.g. once per run) to tell the dashboard to keep only the last
`retention_days` days of **completed** job records for this agent.

Only jobs with a `completed_at` timestamp are eligible — a job still
"running" is never purged this way. Deleting a backup job cascades to delete
its associated `events`.

`file_backup_agent` should **not** use this endpoint — it already purges
correctly via its own backup-rotation logic + `sync-job-sets`.

#### Request body fields

| Field | Type | Required | Notes |
| --- | --- | --- | --- |
| `retention_days` | integer | **yes** | Delete completed jobs older than this many days. Must be a positive integer. |
| `job_name` | string | no | Restrict the purge to a single job name. Omit to apply to all of this agent's jobs. |

#### Responses

- `200 {"success": true, "deleted_jobs": <int>}`
- `400 {"error": "retention_days must be an integer"}`
- `400 {"error": "retention_days must be a positive integer"}`
- `401 {"error": "Missing API key (X-API-Key header)"}`
- `403 {"error": "Invalid API key"}`
- `500 {"error": "Failed to purge old jobs: <detail>"}`

#### Example

```json
POST /api/monitoring/purge-old-jobs
X-API-Key: 9f2c6b1a4e8d3f0c7a5b2e1d6c4f8a90b3d7e2c1
{
  "retention_days": 30
}
```

---

## Building a compatible agent client — checklist

1. **Register the agent first.** Add it on the JABS dashboard's Agents page
   (no self-registration API exists) — this generates a unique `agent_key`.
   Store that key securely (e.g. `JABS_AGENT_KEY` in the agent's `.env`).
2. Send the key as `X-API-Key: <agent_key>` on every request.
3. Generate a `run_id` (e.g. a UUID) once per job execution and include it on
   every event for that run, so the dashboard correlates them into one backup job.
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
   `backup_set_id`s still retained for that job, so the dashboard prunes anything
   rotated out. If your agent doesn't have discrete, identifiable sets to
   reconcile (e.g. an ongoing mirror job), call `/api/monitoring/purge-old-jobs`
   instead with a `retention_days` value to have the dashboard purge old
   completed job records by age.
8. For idle periods with no active backup, you may send a bare heartbeat
   (`hostname`/`ip_address`/`version`/`agent_type` only, no `backup_set_id`) to
   keep the agent's "online" status and reported version/type current.
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
