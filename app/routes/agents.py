"""Flask routes for agent management: register, edit, and remove agents."""

from flask import Blueprint, render_template, request, jsonify, current_app
from app.models import agents

agents_bp = Blueprint('agents', __name__, url_prefix='/agents')


@agents_bp.route('')
def list_agents():
    """Render the agent management page."""
    try:
        agents_list = agents.get_agents_with_job_counts()
        return render_template('agents.html', agents=agents_list)
    except Exception as e:
        current_app.logger.error(f"Error loading agents: {e}")
        return render_template('agents.html', agents=[], error=str(e))


@agents_bp.route('/add', methods=['POST'])
def add_agent():
    """Register a new agent. Multiple agents may share the same hostname/IP
    (e.g. several agents on one machine) since each gets its own unique API key.
    """
    try:
        data = request.get_json()
        hostname = data.get('hostname', '').strip()
        ip_address = data.get('ip_address', '').strip()
        notes = data.get('notes', '').strip()

        if not hostname or not ip_address:
            return jsonify({'success': False, 'error': 'Hostname and IP address required'}), 400

        agent_id, agent_key = agents.create_agent(hostname, ip_address, notes)
        return jsonify({
            'success': True,
            'agent_id': agent_id,
            'agent_key': agent_key,
            'message': f'Agent "{hostname}" registered'
        }), 201

    except Exception as e:
        current_app.logger.error(f"Error adding agent: {e}")
        return jsonify({'success': False, 'error': str(e)}), 500


@agents_bp.route('/<int:agent_id>/edit', methods=['POST'])
def edit_agent(agent_id):
    """Update agent details."""
    try:
        agent = agents.get_agent(agent_id)
        if not agent:
            return jsonify({'success': False, 'error': 'Agent not found'}), 404

        data = request.get_json()
        hostname = data.get('hostname')
        ip_address = data.get('ip_address')
        notes = data.get('notes')
        enabled = data.get('enabled')

        success = agents.update_agent(agent_id, hostname=hostname, ip_address=ip_address, notes=notes, enabled=enabled)
        if success:
            return jsonify({'success': True, 'message': 'Agent updated'}), 200
        else:
            return jsonify({'success': False, 'error': 'Agent not found'}), 404

    except Exception as e:
        current_app.logger.error(f"Error editing agent: {e}")
        return jsonify({'success': False, 'error': str(e)}), 500


@agents_bp.route('/<int:agent_id>/regenerate-key', methods=['POST'])
def regenerate_agent_key(agent_id):
    """Generate a new API key for an agent, invalidating the old one."""
    try:
        agent = agents.get_agent(agent_id)
        if not agent:
            return jsonify({'success': False, 'error': 'Agent not found'}), 404

        new_key = agents.regenerate_agent_key(agent_id)
        return jsonify({'success': True, 'agent_key': new_key, 'message': 'API key regenerated'}), 200

    except Exception as e:
        current_app.logger.error(f"Error regenerating agent key: {e}")
        return jsonify({'success': False, 'error': str(e)}), 500


@agents_bp.route('/<int:agent_id>/delete', methods=['POST'])
def delete_agent(agent_id):
    """Delete an agent (cascades to jobs and events)."""
    try:
        agent = agents.get_agent(agent_id)
        if not agent:
            return jsonify({'success': False, 'error': 'Agent not found'}), 404

        hostname = agent['hostname']
        success = agents.delete_agent(agent_id)
        if success:
            return jsonify({'success': True, 'message': f'Agent "{hostname}" deleted'}), 200
        else:
            return jsonify({'success': False, 'error': 'Failed to delete agent'}), 500

    except Exception as e:
        current_app.logger.error(f"Error deleting agent: {e}")
        return jsonify({'success': False, 'error': str(e)}), 500
