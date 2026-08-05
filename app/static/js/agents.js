function addAgent() {
    const form = document.getElementById('addAgentForm');
    const data = {
        hostname: form.hostname.value,
        ip_address: form.ip_address.value,
        notes: form.notes.value
    };

    fetch('/agents/add', {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify(data)
    })
    .then(r => r.json())
    .then(result => {
        if (result.success) {
            alert(`${result.message}\n\nAgent API key (copy this into the agent's .env as JABS_AGENT_KEY):\n${result.agent_key}`);
            location.reload();
        } else {
            alert('Error: ' + result.error);
        }
    })
    .catch(e => alert('Error: ' + e));
}

function copyAgentKey(agentId) {
    const el = document.getElementById('agent-key-' + agentId);
    navigator.clipboard.writeText(el.textContent.trim());
}

function regenerateKey(agentId) {
    if (!confirm('Regenerate this agent\'s API key? The old key will stop working immediately.')) return;

    fetch(`/agents/${agentId}/regenerate-key`, {
        method: 'POST'
    })
    .then(r => r.json())
    .then(result => {
        if (result.success) {
            alert(`New API key (update the agent's .env with JABS_AGENT_KEY):\n${result.agent_key}`);
            location.reload();
        } else {
            alert('Error: ' + result.error);
        }
    })
    .catch(e => alert('Error: ' + e));
}

function saveAgent(agentId) {
    const form = document.getElementById('editAgentForm-' + agentId);
    const data = {
        hostname: form.hostname.value,
        ip_address: form.ip_address.value,
        notes: form.notes.value,
        enabled: form.elements['enabled'].checked
    };

    fetch(`/agents/${agentId}/edit`, {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify(data)
    })
    .then(r => r.json())
    .then(result => {
        if (result.success) {
            alert(result.message);
            location.reload();
        } else {
            alert('Error: ' + result.error);
        }
    })
    .catch(e => alert('Error: ' + e));
}

function deleteAgent(agentId) {
    if (!confirm('Are you sure? This will delete all associated jobs and events.')) return;

    fetch(`/agents/${agentId}/delete`, {
        method: 'POST'
    })
    .then(r => r.json())
    .then(result => {
        if (result.success) {
            alert(result.message);
            location.reload();
        } else {
            alert('Error: ' + result.error);
        }
    })
    .catch(e => alert('Error: ' + e));
}