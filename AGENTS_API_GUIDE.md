# JABS Dashboard Agent Monitoring API Guide

This document describes the HTTP API implemented in [app/routes/agent_monitoring.py](../app/routes/agent_monitoring.py)
that any backup agent (one of JABS's own agents, or a custom/third-party agent)
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
  3. The dashboard looks up the agent by that key alone; it does not accept
     or use `hostname`/`ip_address` from the agent at all. Multiple agents
     can run on the same machine as long as each has its own key.

  If the header is missing, respond `401`. If the key doesn't match any
  registered agent (or that agent is disabled), respond `403`. **This means a
  new agent must be registered on the JABS dashboard (obtaining a key)
  before it can send any events.**
- Hostname/IP shown on the Agents/agent detail pages come solely from what
  was entered in the dashboard's Agents registration/edit form — agents
  should not send `hostname`/`ip_address` fields; the dashboard ignores them
  if present.
- All endpoints are POST, JSON in and JSON out.
- Timestamps are Unix epoch seconds (float or int).

## Endpoints

### 1. `POST /api/monitoring/events`

The primary endpoint. Used for three purposes, distinguished by `event_type`:

1. **Heartbeat only** (no job in progress) — omit `target_id`. Used by
   the scheduler or agent to signal "I'm alive" and optionally report agent
   version/type.
2. **Job progress** — `event_type` such as `"heartbeat"` with a `stage`
   describing what's happening (e.g. `"Starting backup"`, `"Compressing"`).
3. **Job completion** — `event_type` of `"backup_complete"` (success) or
   `"error"` (failure). This finalizes the backup job record with stats.

#### Request body fields

| Field | Type | Required | Notes |
| --- | --- | --- | --- |
| `version` | string | no | Agent software version; stored on the agent record. |
| `agent_type` | string | no | e.g. `"File Backup"`, `"NAS Sync"`; stored on the agent record. |
| `event_type` | string | no* | `"heartbeat"`, `"backup_complete"`, or `"error"`. Required for job/event-tracking calls; not needed for plain heartbeats with no `target_id`. |
| `message` | string | no | Human-readable description of the event. |
| `stage` | string | no | Short label for current backup stage (progress events). |
| `timestamp` | number | no | Unix epoch seconds; defaults to dashboard time if omitted. |
| `run_id` | string | no | A UUID unique to a single job *execution*. Used to correlate multiple events (start/progress/complete) belonging to the same run. Strongly recommended. |
| `job_run_id` | string | no | A UUID shared by *every* `target_id` reported during one overall script invocation (e.g. all source/destination pairs a sync agent processes in one run, or both nodes a dual-node backup agent images) — distinct from `run_id`, which is unique per `target_id`. Only needed by agents that report more than one `target_id` per invocation; omit for single-target agents. Used by the dashboard to group those targets into a single "job run" so the jobsTable's First/Last/Next Job Started reflects the overall run's true start time, not any one target's. |
| `target_id` | string | no** | Stable identifier for the logical, recurring job this run belongs to — e.g. one source/destination pair for a sync agent, one restic repo+job for a snapshot agent, or a rotating full+incrementals family for a backup agent. **This must stay the same across every run of the same job** so the dashboard can group runs together; it must **not** embed a per-run timestamp. **If omitted, the request is treated as a pure heartbeat** — the dashboard updates the agent's heartbeat/version/type and returns immediately without creating/updating any backup job. Required to actually create or update a backup job. |
| `target_label` | string | no | Human-readable label for the job target. Unlike `target_id`, this may change between runs (e.g. to reflect a formatted date), but should describe the target as a whole rather than one specific run. |
| `job_name` | string | no*** | The backup job's configured name (e.g. from a job YAML). Required (with `target_id`) to create a backup job. |
| `backup_type` | string | no | e.g. `"full"`, `"incremental"`, `"differential"`. If a later event for the same job upgrades to `"full"`, the dashboard updates the stored type (never downgrades). |
| `source` | string | no | Source path/description being backed up (only used at job creation). |
| `destination` | string | no | Destination path/description (only used at job creation). |
| `status` | string | no | For completion events: `"success"`, `"failed"`, or `"stopped"`. Defaults based on `event_type` if omitted. Send `event_type="backup_complete"` with `status="stopped"` when a job is deliberately cut short (e.g. a deadline/timeout) but is expected to resume on a future run — this finalizes the job (sets `completed_at`, stops the dashboard's "running" spinner, and includes it in the next digest email) without marking it as an error. |
| `duration_seconds` | number | no | Total job runtime — stored as `runtime_seconds` (completion events). |
| `files_backed_up` | integer | no | File count processed — stored as `files_count` (completion events). |
| `bytes_backed_up` | integer | no | Total bytes processed (uncompressed) — stored as `bytes_processed` (completion events). |
| `bytes_compressed` | integer | no | Total bytes of the compressed/output archive(s) (completion events). |
| `percent_complete` | integer | no | Mid-run progress, 0-100. Advisory/best-effort — send on a plain `heartbeat` event (no `duration_seconds`) while a job is still running; omit entirely if your agent can't compute it. Never sent on completion events (finalizing always sets 100 on success, or leaves the last-known value on failure). |
| `bytes_per_second` | number | no | Current transfer rate, mid-run only. Omit if not computable (e.g. no natural per-tick rate available). |
| `eta_seconds` | number | no | Estimated seconds remaining, mid-run only. Prefer passing a value your backup tool already computes (e.g. restic's own `seconds_remaining`) over deriving your own. |
| `current_item` | string | no | Short free-text label for what's currently happening (current filename, stage, etc.), mid-run only. |
| `error_code` | integer | no | Machine-readable error code (error events). |
| `error_message` | string | no | Human-readable error detail (error events). |
| `external_id` | string | no | Agent-chosen opaque identifier for the specific artifact this run produced (e.g. a restic snapshot ID, a dated image filename). Only meaningful on completion events (stored via `finalize_backup_job`). Later, if your agent deletes this specific artifact (e.g. during a prune/rotation step), pass this same value back via `/api/monitoring/target-purged`'s `external_ids` list so the dashboard can mark exactly that run as purged. Omit if your agent doesn't track discrete per-run artifacts. |
| `cron_schedule` | string | no | Comma-separated cron expression(s) describing when `job_name` runs (e.g. `"0 2 * * *"`). Reported independently of any job run — send it alongside any event, including a bare heartbeat. The dashboard uses it to compute the "Next Event" shown for this job; it is purely advisory and never affects when the agent itself actually runs. |

\* Required if you want the event stored; omit entirely (and omit `target_id`) for a bare heartbeat.
\** Omitting `target_id` short-circuits to a heartbeat-only response.
\*** Only needed the first time a given `run_id`/job is reported; subsequent events for the same `run_id` reuse the existing backup job.

#### Behavior / dashboard-side logic

1. Validates the `X-API-Key` header against the dashboard's registered agents (see Auth model above). `401` if missing, `403` if invalid/disabled.
2. Updates the agent's heartbeat timestamp, and `version`/`agent_type` if provided.
3. If `target_id` is not provided → returns `201 {"success": true}` immediately (heartbeat only).
4. Otherwise, looks up an existing backup job by `run_id` (if provided):
   - If none exists, **creates** a new backup job (status `"running"`) using
     `job_name`, `backup_type`, `run_id`, `job_run_id`, `target_id`, `target_label`,
     `source`, `destination`.
   - If one exists, reuses it (and upgrades `backup_type` to `"full"` if applicable).
5. Creates an `events` row linked to the backup job (`event_type`, `message`, `stage`, `error_code`, `timestamp`).
6. If `event_type` is `"backup_complete"` or `"error"` **and** `duration_seconds` is present, finalizes the backup job:
   sets `status`, `completed_at`, `runtime_seconds`, `files_count`,
   `bytes_processed`, `bytes_compressed`, `error_code`, `error_message`,
   `external_id` (if provided), and `percent_complete` (100 on success, left
   unchanged on failure/stopped).
7. Otherwise, if any of `percent_complete`/`bytes_per_second`/`eta_seconds`/`current_item`/
   `files_backed_up`/`bytes_backed_up` are present, applies them as a **non-finalizing** progress
   update (does not touch `status`/`completed_at`). Any subset of these may be sent — omitted
   fields are left unchanged.

#### Responses

- `201 {"success": true}` — heartbeat only (no `target_id`).
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
  "version": "1.4.0",
  "agent_type": "backup_agent",
  "event_type": "heartbeat",
  "message": "Starting full backup for Jim-Home",
  "stage": "Starting backup",
  "run_id": "3f9a...uuid",
  "job_name": "Jim-Home",
  "backup_type": "full",
  "target_id": "Jim-Home",
  "target_label": "Jim-Home 2026-07-20"
}
```

#### Example: mid-run progress update

Sent periodically (throttled, e.g. every 5-10s) while a job runs. Omits `duration_seconds` so
it never finalizes the job.

```json
POST /api/monitoring/events
X-API-Key: xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx
{
  "event_type": "heartbeat",
  "message": "Backup in progress",
  "run_id": "3f9a...uuid",
  "job_name": "Jim-Home",
  "backup_type": "full",
  "target_id": "Jim-Home",
  "percent_complete": 42,
  "bytes_per_second": 125829120,
  "eta_seconds": 210,
  "current_item": "/home/jim/Documents/photos"
}
```

#### Example: backup completion (success)

```json
POST /api/monitoring/events
X-API-Key: xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx
{
  "event_type": "backup_complete",
  "message": "Backup Complete",
  "stage": "Completed",
  "status": "success",
  "run_id": "3f9a...uuid",
  "job_name": "Jim-Home",
  "backup_type": "full",
  "target_id": "Jim-Home",
  "target_label": "Jim-Home 2026-07-20",
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
  "event_type": "error",
  "message": "Backup 'Jim-Home' failed: disk full",
  "stage": "Error",
  "status": "failed",
  "run_id": "3f9a...uuid",
  "job_name": "Jim-Home",
  "backup_type": "full",
  "target_id": "Jim-Home",
  "error_code": 1,
  "error_message": "disk full"
}
```

#### Example: plain heartbeat (no active job)

```json
POST /api/monitoring/events
X-API-Key: xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx
{
  "version": "1.4.0",
  "agent_type": "backup_agent"
}
```

---

## Data retention (dashboard-side deletion only)

Agents have **no way to tell the dashboard when to delete job records** —
there is no `sync-job-sets` or `purge-old-jobs` endpoint. The dashboard
deletes any `backup_jobs` row (and its cascaded events) once older than
`retention.max_days` in its own `config/global.yaml`, regardless of your
agent's `agent_type` or the row's status — see the dashboard's README.md.

If your agent prunes/deletes specific rotated-out artifacts locally (e.g. a
restic snapshot removed by `forget --prune`, a dated image file deleted by
an age-based cleanup step), it **may** call `/api/monitoring/target-purged`
(below) right after deleting them, so the dashboard's history reflects that
the underlying data no longer exists on the agent. This only marks the
matching rows' status as `"purged"` for display purposes — it has no effect
on retention timing; the rows are still deleted once they reach
`retention.max_days` like any other row.

### 2. `POST /api/monitoring/target-purged`

Call this right after your agent has successfully deleted one or more
specific artifacts it previously reported via `external_id` on a
`backup_complete` event. The dashboard marks every `backup_jobs` row for the
authenticated agent whose `target_id` matches **and** whose stored
`external_id` is in `external_ids` with `status="purged"`, and logs a
`"purged"` event on each. **This never deletes any rows immediately** — a
marked row is still deleted only once the dashboard's own `retention.max_days`
policy (see above) is reached, same as any other row.

`external_ids` is required and must be non-empty — this endpoint only marks
runs you can identify by the `external_id` they previously reported; it has
no "purge everything for this target_id" mode, so unrelated runs sharing the
same `target_id` are never affected by a call meant for one artifact.

#### Request body fields

| Field | Type | Required | Notes |
| --- | --- | --- | --- |
| `target_id` | string | **yes** | The `target_id` shared by the run(s) whose artifact(s) were just deleted locally. |
| `external_ids` | array of strings | **yes** | Non-empty list of `external_id` values (as previously reported on each run's `backup_complete` event) identifying exactly which artifacts were deleted. |
| `message` | string | no | Human-readable note; defaults to a generic message if omitted. |
| `timestamp` | number | no | Unix epoch seconds; defaults to dashboard time if omitted. |

#### Responses

- `200 {"success": true, "purged_jobs": <int>}`
- `400 {"error": "Missing required field: target_id"}`
- `400 {"error": "Missing required field: external_ids (non-empty list)"}`
- `401 {"error": "Missing API key (X-API-Key header)"}`
- `403 {"error": "Invalid API key"}`
- `500 {"error": "Failed to record job target purge: <detail>"}`

#### Example

```json
POST /api/monitoring/target-purged
X-API-Key: xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx
{
  "target_id": "jim-home",
  "external_ids": ["a1b2c3d4e5f6...", "f6e5d4c3b2a1..."],
  "message": "restic forget --prune removed 2 snapshot(s)"
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
   If your agent reports more than one `target_id` per overall invocation
   (e.g. several source/destination pairs, or multiple nodes), also generate
   one `job_run_id` per invocation and include it on every target's events —
   this lets the dashboard group them into a single "job run" for an accurate
   First/Last/Next Job Started.
4. Send a start/progress event with `event_type="heartbeat"`, `job_name`,
   `backup_type`, `target_id`, `target_label`, and optionally
   `source`/`destination` — these are only captured the first
   time the job is created for a given `run_id`.
5. Optionally send more progress events reusing the same `run_id` and
   `target_id`, varying `stage`/`message`.
6. On completion, send exactly one event with `event_type="backup_complete"`
   (success) or `event_type="error"` (failure), including `status`,
   `duration_seconds`, `files_backed_up`, `bytes_backed_up`,
   `bytes_compressed` (success), or `error_code`/`error_message` (failure).
7. For idle periods with no active backup, you may send a bare heartbeat
   (`version`/`agent_type` only, no `target_id`) to keep the agent's
   "online" status and reported version/type current.
8. Treat all requests as fire-and-forget/best-effort from the agent's
   perspective: network failures should be logged and swallowed, not block or
   fail the backup job itself (see the reference implementation's use of
   `requests` with short timeouts and broad `except requests.exceptions.RequestException`).
9. If your agent prunes/deletes specific rotated-out artifacts locally over
   time, report an `external_id` for each artifact on its `backup_complete`
   event, then call `/api/monitoring/target-purged` with the matching
   `external_ids` right after each local deletion — see "Data retention"
   above. Do not implement any client-side call that deletes/reconciles
   dashboard rows directly; only the dashboard's own scheduled retention
   purge does that.

## Reference implementation

The canonical client implementation for this API is
[local_sync_agent/monitoring_client.py](../local_sync_agent/monitoring_client.py),
which provides `send_event()`, `send_sync_start()`, `send_sync_stage()`,
`send_sync_complete()`, and `send_scheduler_check()` helper functions. For a
reference `target-purged` implementation (including `external_id` reporting
and parsing a prune tool's own deleted-artifact list), see
[snapshot_agent/monitoring_client.py](../snapshot_agent/monitoring_client.py)'s
`send_target_purged()` and [snapshot_agent/restic_client.py](../snapshot_agent/restic_client.py)'s
`forget_prune()`.
