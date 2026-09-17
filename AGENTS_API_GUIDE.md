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
| `agent_type` | string | no | e.g. `"File Backup"`, `"NAS Sync"`; stored on the agent record. Also the key the dashboard operator uses to configure a per-agent-type retention policy for your agent (see "Data retention" below) — agree on a stable string with the dashboard operator. |
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
| `status` | string | no | For completion events: `"success"`, `"failed"`, or `"stopped"`. Defaults based on `event_type` if omitted. Send `event_type="backup_complete"` with `status="stopped"` when a job is deliberately cut short (e.g. a deadline/timeout) but is expected to resume on a future run — this finalizes the job (sets `completed_at`, stops the dashboard's "running" spinner, and includes it in the next digest email) without marking it as an error. |
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
     `source`, `destination`.
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
X-API-Key: xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx
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
  "backup_set_name": "Jim-Home 2026-07-20"
}
```

#### Example: backup completion (success)

```json
POST /api/monitoring/events
X-API-Key: xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx
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
X-API-Key: xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx
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
X-API-Key: xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx
{
  "hostname": "P3Tiny",
  "ip_address": "192.168.1.50",
  "version": "1.4.0",
  "agent_type": "backup_agent"
}
```

---

## Data retention (dashboard-side deletion only)

Agents have **no way to tell the dashboard when to delete job records** —
there is no `sync-job-sets` or `purge-old-jobs` endpoint. The dashboard
applies a per-agent-type retention policy (`retention` in its own
`config/global.yaml`, see the dashboard's README.md), keyed by the
`agent_type` string your agent reports in its `/api/monitoring/events`
calls (see the request body table above). Each policy is one of:

- `purged_only` (the default) — only rows your agent has explicitly marked
  `status="purged"` (see below) are ever deleted, once older than the
  policy's `max_days`, measured from when they were marked purged.
  Everything else your agent reports is kept indefinitely.
- `all` — any row of your agent's is deleted once older than `max_days`
  (measured from when the job started), regardless of status. This is
  meant for agents that have no concept of "purged" sets and would
  otherwise accumulate history forever.

If your `agent_type` isn't explicitly configured on the dashboard, it falls
back to the default policy (`purged_only` unless the dashboard operator
changed it) — meaning your agent's rows are retained indefinitely unless
you also call `backup-set-purged` below. If you're building a new agent
(e.g. something Restic-snapshot-based) and want your history reliably
pruned, either mark sets `purged` as you rotate them, or ask the dashboard
operator to configure `mode: all` for your `agent_type`.

If your agent rotates/deletes its own local records, it is not required to
notify the dashboard — new events keep flowing normally via
`/api/monitoring/events`. However, if your agent tracks discrete backup
sets locally (like `file_backup_agent`), it **should** call
`/api/monitoring/backup-set-purged` (below) right after deleting a set
locally, so the dashboard's history reflects that the underlying data no
longer exists on the agent — this only marks status; actual row deletion
still depends on your agent_type's configured policy.

### 2. `POST /api/monitoring/backup-set-purged`

Call this right after your agent has successfully deleted a backup set's
local files (and its own DB records, if any). The dashboard marks every
`backup_jobs` row sharing this `backup_set_id` (for the authenticated agent)
with `status="purged"` and logs a `"purged"` event on each. **This never
deletes any rows immediately** — only the dashboard's own retention policy
for your `agent_type` (see above) removes these rows, and only once its
`max_days` has passed since they were marked purged.

A single `backup_set_id` may be shared by multiple `backup_jobs` rows (a
full backup plus its incremental/differential children) — all of them are
marked together.

#### Request body fields

| Field | Type | Required | Notes |
| --- | --- | --- | --- |
| `backup_set_id` | string | **yes** | The `backup_set_id` of the set that was just deleted locally. |
| `message` | string | no | Human-readable note; defaults to a generic message if omitted. |
| `timestamp` | number | no | Unix epoch seconds; defaults to dashboard time if omitted. |

#### Responses

- `200 {"success": true, "purged_jobs": <int>}`
- `400 {"error": "Missing required field: backup_set_id"}`
- `401 {"error": "Missing API key (X-API-Key header)"}`
- `403 {"error": "Invalid API key"}`
- `500 {"error": "Failed to record backup set purge: <detail>"}`

#### Example

```json
POST /api/monitoring/backup-set-purged
X-API-Key: xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx
{
  "hostname": "P3Tiny",
  "ip_address": "192.168.1.50",
  "backup_set_id": "3f9a1c2e-...-uuid",
  "message": "Backup set rotated out of local storage"
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
   `source`/`destination` — these are only captured the first
   time the job is created for a given `run_id`.
5. Optionally send more progress events reusing the same `run_id` and
   `backup_set_id`, varying `stage`/`message`.
6. On completion, send exactly one event with `event_type="backup_complete"`
   (success) or `event_type="error"` (failure), including `status`,
   `duration_seconds`, `files_backed_up`, `bytes_backed_up`,
   `bytes_compressed` (success), or `error_code`/`error_message` (failure).
7. For idle periods with no active backup, you may send a bare heartbeat
   (`hostname`/`ip_address`/`version`/`agent_type` only, no `backup_set_id`) to
   keep the agent's "online" status and reported version/type current.
8. Treat all requests as fire-and-forget/best-effort from the agent's
   perspective: network failures should be logged and swallowed, not block or
   fail the backup job itself (see the reference implementation's use of
   `requests` with short timeouts and broad `except requests.exceptions.RequestException`).
9. If your agent tracks discrete backup sets locally and rotates them out
   over time, call `/api/monitoring/backup-set-purged` right after each local
   deletion — see "Data retention" above. Do not implement any client-side
   call that deletes/reconciles dashboard rows directly; only the dashboard's
   own scheduled retention purge does that.

## Reference implementation

The canonical client implementation for this API is
[file_backup_agent/monitoring_client.py](../file_backup_agent/monitoring_client.py),
which provides `send_event()`, `send_backup_start()`, `send_backup_stage()`,
`send_backup_complete()`, `send_scheduler_check()`, and
`send_backup_set_purged()` helper functions implementing everything described
above.
