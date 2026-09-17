# JABS Dashboard

The dashboard for JABS (Just Another Backup Script). The dashboard does **not** run backups itself — it monitors agents that perfrom backups, sync NAS, etc, and displays their status/history on the dashboard.

The dashboard is standalone so it can be deployed on its own machine, separate from any agent.

## Features

* Web dashboard showing connected agents and backup jobs with a
  Job Activity trend chart segmented by job status (success/failed/
  skipped/running), spanning `retention.max_days` days
* Digest email of all backup jobs monitored
* Network drive an AWS S3 storage usage charts
* Event ingestion API used by agents to report backup activity, plus a
  per-agent-type-aware retention purge (see Retention Purge below).
* Dashboard log viewer
* SQLite storage

## Requirements

* Python 3.12+
* `python3-venv`

## Setup

Clone or otherwise download the dashboard to you machine.

```bash
#Setup the environment
cd dashboard
./jabs-dashboard.sh setup     # creates venv, installs requirements
```

## Configuration

Create ./.env file with the following:

```text
# JABS Environment Variables

# This will display a banner, create a seperate monitor json file, and enable debug logging
# production (default) → port 5000
# development → port 5001
# Uncomment the following line if codebase is in development mode
# ENV_MODE='development'

# SMTP credentials (for email notifications)
JABS_SMTP_PASSWORD=
JABS_SMTP_USERNAME=
```

```bash
# copy config/global-example.yaml to config/global.yaml
cp config/global-example.yaml to config/global.yaml
# Edit global
nano config/global.yaml
```

```bash
# Start the server
./jabs-dashboard.sh start     # starts the server in the background
```

## Registering an Agent

Before an agent can report events, it must be registered on the dashboard so it has its own API key:

1. Open the dashboard → **Agents**
2. Add the agent's hostname and IP address (informational/display only — see auth model below) to get a generated `agent_key`
3. Configure the agent with that key (e.g. `JABS_AGENT_KEY` in its `.env`) and point its `JABS_DASHBOARD_URL` (see agent README) at this dashboard

**Auth model:** each registered agent authenticates via a unique API key sent as the `X-API-Key` header on every request — *not* by hostname/IP matching, so multiple agents can share a machine/hostname as long as each has its own key. Missing key → `401`; invalid/disabled agent → `403`. See `app/routes/agent_monitoring.py` and `app/models/hosts.py`. Keys can be viewed/regenerated from the Agents page.

## API

The dashboard's agent-facing API is fully documented in [../AGENTS_API_GUIDE.md](../AGENTS_API_GUIDE.md) — read that before writing any agent client code; don't re-derive endpoint shapes from this summary. Endpoints implemented in `app/routes/agent_monitoring.py`:

* `POST /api/monitoring/events` — report backup start/stage/complete/error events and scheduler heartbeats. Events without a `backup_set_id` are treated as heartbeats (only the host's `last_heartbeat` is updated, no job/event row is created). The first event for a given `run_id` creates a `backup_jobs` row; `backup_complete`/`error` events finalize it.
* `POST /api/monitoring/backup-set-purged` — report that an agent locally rotated (deleted) a backup set. Marks every `backup_jobs` row sharing that `backup_set_id` with `status="purged"` and logs a `"purged"` event on each — never deletes rows.

Agents are **not** responsible for telling the dashboard when to *delete* old job records — see Scheduler below.

## Scheduler (Digest Email & Retention Purge)

The dashboard has three periodic/event-driven background tasks — a digest
email, an offline-agent alert, and a retention purge — all driven by a
single standalone script, `scheduler.py`, rather than an in-process
background thread. This keeps scheduling independent of whether the web
server process is running, and mirrors how the backup agent's own scheduler
is invoked externally by cron. Run it from a single crontab entry on the
host, e.g. every 15 minutes:

```bash
crontab -e
```

```cron
*/15 * * * * cd /path/to/jabs/dashboard && venv/bin/python scheduler.py >> logs/scheduler_cron.log 2>&1
```

Every invocation of `scheduler.py` performs all three checks below; each is
independently configured in `config/global.yaml` (see [global-example.yaml](config/global-example.yaml)).

### Digest email

Sends a periodic digest summarizing backup activity (successes/failures)
across all registered agents. Unlike per-event notifications (which are sent
immediately by each backup agent — see the [file_backup_agent README](../file_backup_agent/README.md)),
the digest only covers what's completed since the *last* digest send.

Configured under `email.digest` in `config/global.yaml`:

```yaml
email:
  digest:
    enabled: true
    schedule: "0 8 * * *"   # standard 5-field cron expression
```

On each `scheduler.py` run, the next scheduled fire time (per `schedule`,
computed from the last successful send) is compared against now; the digest
is only actually sent once that time has passed — so it's safe to run
`scheduler.py` far more often than the digest itself is sent. Each send
queries `backup_jobs` for jobs completed since the last successful send
(tracked in `data/digest_state.json`) and emails an HTML summary using
`app/templates/email/digest_email.html`.

### Retention purge

Deletes `backup_jobs` rows (and their cascaded `events`) per an
agent-type-aware policy, configured in `config/global.yaml`. Each policy
has a `max_days` and a `mode`:

- `purged_only` — only rows an agent has explicitly marked
  `status="purged"` (see "Data retention" in AGENTS_API_GUIDE.md) are
  deleted, once older than `max_days` (measured from when marked purged).
  Everything else is kept indefinitely. Use for agents (e.g.
  `file_backup_agent`) that report purged sets themselves.
- `all` — any row is deleted once older than `max_days` (measured from
  `started_at`), regardless of status. Use for agents (e.g.
  `nas_sync_agent`) that never mark rows purged, so their history doesn't
  grow forever.

The top-level `max_days`/`mode` are the default, applied to any agent
whose `agent_type` isn't listed under `by_agent_type`. `by_agent_type` keys
must match the `agent_type` string an agent registers with. The default's
`max_days` also sets how many days the Job Activity graph (index.html /
agent_detail.html) shows.

```yaml
retention:
  max_days: 30
  mode: purged_only
  by_agent_type:
    "NAS Sync":
      mode: all
```

Unlike the digest email, the purge is unconditional — it runs on every
`scheduler.py` invocation, deleting whatever has become eligible per each
agent's policy.

### Offline agent alert

Sends an immediate email the moment an *enabled* agent is found to be
`offline` — i.e. its configured grace period (set per agent on the Agents
page, in minutes) has elapsed without a heartbeat or event from it. Status
is computed the same way everywhere it's displayed (Connected Agents card,
Agents page, agent detail page) by `app/models/agents.py:compute_agent_status`,
so there's a single definition of "Active" vs. "Offline" vs. "Disabled"
across the whole dashboard:

- **Disabled** — the agent's `enabled` flag is off (Edit Agent modal).
- **Active** — enabled, and a heartbeat/event arrived within the grace period.
- **Offline** — enabled, but no heartbeat/event within the grace period (or ever).

Each agent is only alerted once per offline streak (tracked via the
`offline_notified` column) — the flag clears automatically the next time the
agent sends a heartbeat, so a later offline streak will alert again.
Configured under `email.offline_alert` in `config/global.yaml`:

```yaml
email:
  offline_alert:
    enabled: true
```

No cron schedule is needed for this one — it's event-driven and checked on
every `scheduler.py` run. Uses `app/templates/email/agent_offline_email.html`.

