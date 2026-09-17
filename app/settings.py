"""Application-wide settings and configuration constants."""

import os
import sys
import yaml
from dotenv import load_dotenv



VERSION = "0.12.10"

# --- Environment Configuration ---
BASE_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))

# Path to the .env file (dashboard's root directory)
ENV_PATH = os.path.abspath(os.path.join(BASE_DIR, '.env'))

# Load environment variables
load_dotenv(ENV_PATH)

# Environment mode (development | production default )
# Do not edit here, edit in .env
ENV_MODE = os.environ.get("ENV_MODE", "production")

# --- Application Configuration ---
TEMPLATE_DIR = os.path.join(BASE_DIR, 'app', 'templates')
STATIC_DIR = os.path.join(BASE_DIR, 'app', 'static')
LOCK_DIR = os.path.join(BASE_DIR, 'locks')
#CLI_SCRIPT = os.path.join(BASE_DIR, 'cli.py') depreciated
PYTHON_EXECUTABLE = sys.executable or "python3"

# --- CONFIG Configuration ---
CONFIG_DIR = os.path.join(BASE_DIR, 'config')
JOBS_DIR = os.path.join(CONFIG_DIR, 'jobs')
GLOBAL_CONFIG_PATH = os.path.join(CONFIG_DIR, "global.yaml")

# --- Data Configuration ---
DATA_DIR = os.path.join(BASE_DIR, 'data')
DB_PATH = os.path.join(DATA_DIR, "jabs.sqlite")

# --- Logging Configuration ---
LOG_DIR = os.path.join(BASE_DIR, 'logs')
MAX_LOG_LINES = 10000

# --- SMTP Configuration ---
with open(GLOBAL_CONFIG_PATH, "r", encoding="utf-8") as f:
    GLOBAL_CONFIG = yaml.safe_load(f)

EMAIL_CONFIG = GLOBAL_CONFIG.get("email", {})

# --- Retention Configuration ---
# Per-agent-type deletion policy applied on the dashboard (see
# app/services/retention.py and app/models/backup_jobs.py). RETENTION_DEFAULT
# applies to any agent_type not listed in RETENTION_BY_AGENT_TYPE, which
# holds only the overridden fields merged on top of the default. Each
# policy dict has "max_days" and "mode" ("purged_only" or "all").
# RETENTION_MAX_DAYS (the default's max_days) is also used as the Job
# Activity graph's day range (app/routes/dashboard.py), so the graph stays
# limited to a fixed window even though older, retained jobs remain in the
# database.
RETENTION_CONFIG = GLOBAL_CONFIG.get("retention", {})
RETENTION_DEFAULT = {
    "max_days": RETENTION_CONFIG.get("max_days", 90),
    "mode": RETENTION_CONFIG.get("mode", "purged_only"),
}
RETENTION_BY_AGENT_TYPE = {
    agent_type: {**RETENTION_DEFAULT, **overrides}
    for agent_type, overrides in RETENTION_CONFIG.get("by_agent_type", {}).items()
}
RETENTION_MAX_DAYS = RETENTION_DEFAULT["max_days"]
