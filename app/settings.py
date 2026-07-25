"""Application-wide settings and configuration constants."""

import os
import sys
import yaml
from dotenv import load_dotenv



VERSION = "v0.10.0"

# --- Environment Configuration ---
BASE_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))

# Path to the .env file (server's root directory)
ENV_PATH = os.path.abspath(os.path.join(BASE_DIR, '.env'))

# Load environment variables
load_dotenv(ENV_PATH)

# Environment mode (development/production)
ENV_MODE = os.environ.get("ENV_MODE", "production")

# --- Application Configuration ---
TEMPLATE_DIR = os.path.join(BASE_DIR, 'app', 'templates')
STATIC_DIR = os.path.join(BASE_DIR, 'app', 'static')
LOCK_DIR = os.path.join(BASE_DIR, 'locks')
CLI_SCRIPT = os.path.join(BASE_DIR, 'cli.py')
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
