$(document).ready(function () {
    $('#agentsTable').DataTable({
        columnDefs: [
            { targets: [4], orderable: false }, // Agent Key
            { targets: [9], orderable: false, searchable: false } // Actions
        ],
        lengthMenu: [[25, 50, 75, 100], [25, 50, 75, 100]],
        pageLength: 25,
        language: {
            search: "Filter agents:",
            lengthMenu: "Show _MENU_ agents",
            info: "Showing _START_ to _END_ of _TOTAL_ agents",
        },
        responsive: true,
        paging: true,
        searching: true,
        ordering: true,
        order: [[0, 'asc']]
    });

    // Make the entire row a link to the agent's detail page, except for
    // actual interactive controls (buttons/links) and the responsive
    // expand toggle. Delegated since DataTables re-renders rows on every
    // page/sort/search, which would detach any listeners bound directly.
    document.addEventListener('click', function (e) {
        const row = e.target.closest('#agentsTable tr.clickable-row');
        if (!row) return;
        if (e.target.closest('a, button, .dtr-control')) return;
        window.location = row.dataset.href;
    });
});

function addAgent() {
    const form = document.getElementById('addAgentForm');
    const data = {
        hostname: form.hostname.value,
        ip_address: form.ip_address.value,
        notes: form.notes.value,
        grace_period_minutes: parseInt(form.grace_period_minutes.value, 10)
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
        grace_period_minutes: parseInt(form.grace_period_minutes.value, 10),
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