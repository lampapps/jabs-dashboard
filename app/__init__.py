"""Flask application factory and configuration."""

import os
import secrets
from datetime import datetime
from flask import Flask, render_template, send_from_directory
from app.settings import TEMPLATE_DIR, STATIC_DIR, VERSION, ENV_MODE, RESTIC_BROWSER_PATH
from app.routes import register_blueprints

def create_app():
    """Create and configure the Flask app."""
    app = Flask(__name__, template_folder=TEMPLATE_DIR, static_folder=STATIC_DIR)
    # Falls back to a random per-process key, never a static default, if unset
    app.secret_key = os.environ.get("JABS_SECRET_KEY") or secrets.token_urlsafe(32)
    register_blueprints(app)

    @app.template_filter('datetimeformat')
    def datetimeformat(value, fmt='%Y-%m-%d %H:%M:%S'):
        """Convert a Unix timestamp to a formatted date string."""
        if not value:
            return '—'
        return datetime.fromtimestamp(float(value)).strftime(fmt)

    @app.errorhandler(404)
    def page_not_found(_):
        return render_template('404.html'), 404

    @app.context_processor
    def inject_version():
        return {"VERSION": VERSION}

    @app.context_processor
    def inject_env_mode():
        # Default for templates that don't explicitly pass env_mode (e.g. the
        # dev-mode banner), so it renders consistently on every page.
        return {"env_mode": ENV_MODE}

    @app.context_processor
    def inject_restic_browser():
        return {"restic_browser_available": bool(RESTIC_BROWSER_PATH)}

    @app.route('/favicon.ico')
    def favicon():
        return send_from_directory(
            os.path.join(app.root_path, 'static'),
            'favicon.ico',
            mimetype='image/vnd.microsoft.icon'
        )

    return app
