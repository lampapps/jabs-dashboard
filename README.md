# JABS Dashboard

The dashboard for JABS (Just Another Backup Script). The dashboard does not run backups itself — it monitors agents that perform backups independently, such as Restic snapshots, bidirectional NAS sync, high-availability DNS servers backup, and local file sync, and displays their status/history on the dashboard.

The dashboard is standalone so it can be deployed on its own machine, separate from any agent.

JABS started as a hand-coded bash script to meet the needs of my small home lab. I then discovered AI and quickly got carried away. The dashboard and agents are now vibe coded.

## Features

* Web dashboard showing connected agents and backup jobs with a
  Job Activity trend chart segmented by job status (success/failed/
  skipped/running)
* Scheduled digest email sent for all backup jobs monitored
* Offline agent alert sends an email when an agent is found to be `offline`
* Network drive and AWS S3 storage usage charts
* Event ingestion API used by agents to report backup activity
* Dashboard log viewer
* SQLite storage

## Requirements

* Python 3.12+
* `python3-venv`

## Setup

Clone or otherwise download the dashboard to your machine.

```bash
# Setup the environment
cd dashboard
./jabs-dashboard.sh setup     # creates venv, installs requirements
```

## Configuration

The setup function will create the required configuration and environmental files needed. Each is self-documented. Open and edit:

```bash
# Edit .env
nano .env
```

```bash
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

**Auth model:** each registered agent authenticates via a unique API key sent as the `X-API-Key` header on every request — *not* by hostname/IP matching, so multiple agents can share a machine/hostname as long as each has its own key. Missing key → `401`; invalid/disabled agent → `403`. See `app/routes/agent_monitoring.py` and `app/models/agents.py`. Keys can be viewed/regenerated from the Agents page.

## API

The dashboard's agent-facing API is fully documented in [../AGENTS_API_GUIDE.md](../AGENTS_API_GUIDE.md) — read that before writing any agent client code; don't re-derive endpoint shapes from this summary. Endpoints implemented in `app/routes/agent_monitoring.py`:

* `POST /api/monitoring/events` — report backup start/stage/complete/error events and scheduler heartbeats. Events without a `target_id` are treated as heartbeats (only the host's `last_heartbeat` is updated, no job/event row is created). The first event for a given `run_id` creates a `backup_jobs` row; `backup_complete`/`error` events finalize it.
* `POST /api/monitoring/target-purged` — report that an agent locally rotated (deleted) a job target. Marks every `backup_jobs` row sharing that `target_id` with `status="purged"` and logs a `"purged"` event on each — never deletes rows.

Agents are **not** responsible for telling the dashboard when to *delete* old job records — see Scheduler below.

## Scheduler (Digest Email & Retention Purge)

The dashboard has three periodic/event-driven background tasks — a digest email, an offline-agent alert, and a retention purge — all driven by a single standalone script, `scheduler.py`, rather than an in-process background thread. This keeps scheduling independent of whether the web server process is running. Run it from a single crontab entry on the host, e.g. every 15 minutes:

```bash
crontab -e
```

```cron
*/15 * * * * cd /path/to/jabs/dashboard && venv/bin/python scheduler.py >> logs/scheduler_cron.log 2>&1
```

Every invocation of `scheduler.py` performs all three checks below; each is independently configured in `config/global.yaml` (see [global-example.yaml](config/global-example.yaml)).

### Digest email

Sends a periodic digest summarizing backup activity (successes/failures) across all registered agents. Unlike per-event notifications (which are sent immediately by each backup agent), the digest only covers what's completed since the *last* digest send.

Configured under `email.digest` in `config/global.yaml`:

```yaml
email:
  digest:
    enabled: true
    schedule: "0 8 * * *"   # standard 5-field cron expression
```

On each `scheduler.py` run, the next scheduled fire time (per `schedule`, computed from the last successful send) is compared against now; the digest is only actually sent once that time has passed — so it's safe to run `scheduler.py` far more often than the digest itself is sent. Each send queries `backup_jobs` for jobs completed since the last successful send (tracked in `data/digest_state.json`) and emails an HTML summary using `app/templates/email/digest_email.html`.

### Retention purge

Deletes any `backup_jobs` row (and its cascaded `events`) older than
`retention.max_days`, configured in `config/global.yaml`, regardless of
agent_type or status:

```yaml
retention:
  max_days: 30
```

`max_days` also sets how many days the Job Activity graph (index.html /
agent_detail.html) shows.

Unlike the digest email, the purge is unconditional — it runs on every
`scheduler.py` invocation, deleting whatever has become eligible by age.

### Offline agent alert

Sends an immediate email the moment an *enabled* agent is found to be `offline` — i.e. its configured grace period (set per agent on the Agents page, in minutes) has elapsed without a heartbeat or event from it. Status is computed the same way everywhere it's displayed (Connected Agents card, Agents page, agent detail page) by `app/models/agents.py:compute_agent_status`, so there's a single definition of "Active" vs. "Offline" vs. "Disabled" across the whole dashboard:

- **Disabled** — the agent's `enabled` flag is off (Edit Agent modal).
- **Active** — enabled, and a heartbeat/event arrived within the grace period.
- **Offline** — enabled, but no heartbeat/event within the grace period (or ever).

Each agent is alerted the moment it goes offline, and again every `repeat_interval_minutes` for as long as it stays offline, up to `max_alerts` emails per offline streak (tracked via the `offline_alert_count`/`last_offline_alert_at` columns) — `max_alerts: 0` means keep alerting indefinitely until the agent recovers. The streak resets automatically the next time the agent sends a heartbeat, so a later offline streak alerts again from the start. Configured under `email.offline_alert` in `config/global.yaml`:

```yaml
email:
  offline_alert:
    enabled: true
    max_alerts: 1                # alert emails per offline streak; 0 = unlimited
    repeat_interval_minutes: 60   # minutes between repeat alerts
```

It is event-driven and checked on every `scheduler.py` run. Uses `app/templates/email/agent_offline_email.html`.