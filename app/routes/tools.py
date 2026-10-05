"""Flask routes for launching locally installed helper tools (e.g. Restic
Browser). These start a process on the dashboard server itself, so they are
restricted to requests originating from localhost.
"""

import os
import subprocess

from flask import Blueprint, current_app, jsonify, request

from app.settings import RESTIC_BROWSER_PATH

tools_bp = Blueprint('tools', __name__, url_prefix='/tools')

LOCALHOST_ADDRESSES = ('127.0.0.1', '::1')


@tools_bp.route('/launch-restic-browser', methods=['POST'])
def launch_restic_browser():
    """Launch the locally installed Restic Browser AppImage as a detached
    process on the dashboard server. Only allowed from localhost, since this
    only makes sense when the dashboard is viewed on the same machine.
    """
    if request.remote_addr not in LOCALHOST_ADDRESSES:
        return jsonify({'success': False, 'error': 'Only allowed from localhost'}), 403

    if not RESTIC_BROWSER_PATH:
        return jsonify({'success': False, 'error': 'restic_browser_path is not configured in config/global.yaml'}), 400

    if not os.path.isfile(RESTIC_BROWSER_PATH) or not os.access(RESTIC_BROWSER_PATH, os.X_OK):
        return jsonify({'success': False, 'error': f'Restic Browser not found or not executable: {RESTIC_BROWSER_PATH}'}), 404

    try:
        subprocess.Popen(
            [RESTIC_BROWSER_PATH],
            start_new_session=True,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
    except OSError as e:
        current_app.logger.error(f"Failed to launch Restic Browser: {e}")
        return jsonify({'success': False, 'error': str(e)}), 500

    return jsonify({'success': True, 'message': 'Restic Browser launched'}), 200
