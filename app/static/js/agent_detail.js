// agent_detail.html JavaScript - status/type/trend charts and the
// DataTables-driven Recent Jobs table (grouped by Backup Set ID).
//
// Server-rendered data is passed in via window.AGENT_DETAIL (set in an
// inline <script> block in agent_detail.html before this file loads).

function formatBytes(num) {
    num = Number(num) || 0;
    const units = ['B', 'KiB', 'MiB', 'GiB', 'TiB', 'PiB', 'EiB', 'ZiB'];
    let value = num;
    for (const unit of units) {
        if (Math.abs(value) < 1024.0) {
            return `${value.toFixed(1)}${unit}`;
        }
        value /= 1024.0;
    }
    return `${value.toFixed(1)}YiB`;
}

// renderStatusBadge() is defined in global.js (shared with eventsTable).

function initializeAgentDetailCharts(detail) {
    const statusCounts = detail.statusCounts || {};
    const typeCounts = detail.typeCounts || {};
    const trendLabels = detail.trendLabels || [];
    const trendDatasets = detail.trendDatasets || {};

    const statusLabels = Object.keys(statusCounts);
    if (statusLabels.length) {
        new Chart(document.getElementById('statusChart'), {
            type: 'doughnut',
            data: {
                labels: statusLabels,
                datasets: [{
                    data: statusLabels.map(k => statusCounts[k]),
                    backgroundColor: statusLabels.map(k => getStatusChartColor(k))
                }]
            },
            options: {
                responsive: true,
                maintainAspectRatio: false,
                plugins: { legend: { position: 'bottom' } }
            }
        });
    }

    const typeLabels = Object.keys(typeCounts);
    if (typeLabels.length) {
        new Chart(document.getElementById('typeChart'), {
            type: 'bar',
            data: {
                labels: typeLabels,
                datasets: [{
                    label: 'Jobs',
                    data: typeLabels.map(k => typeCounts[k]),
                    backgroundColor: '#0d6efd'
                }]
            },
            options: {
                responsive: true,
                maintainAspectRatio: false,
                plugins: { legend: { display: false } },
                scales: { y: { beginAtZero: true, ticks: { precision: 0 } } }
            }
        });
    }

    // Job Activity trend, segmented (stacked) by status.
    const trendStatuses = Object.keys(trendDatasets);
    new Chart(document.getElementById('trendChart'), {
        type: 'bar',
        data: {
            labels: trendLabels,
            datasets: trendStatuses.map(status => ({
                label: status,
                data: trendDatasets[status],
                backgroundColor: getStatusChartColor(status)
            }))
        },
        options: {
            responsive: true,
            maintainAspectRatio: false,
            plugins: { legend: { display: trendStatuses.length > 1, position: 'bottom' } },
            scales: {
                x: { stacked: true },
                y: { stacked: true, beginAtZero: true, ticks: { precision: 0 } }
            }
        }
    });
}

function initializeRecentJobsTable(agentId) {
    const recentJobsTable = $('#recentJobsTable').DataTable({
        ajax: {
            url: `/api/agent_jobs/${agentId}`,
            dataSrc: 'data'
        },
        columns: [
            { data: 'starttimestamp', title: 'Start' },
            { data: 'job_name', title: 'Job Name' },
            { data: 'backup_type', title: 'Type' },
            {
                data: 'event',
                title: 'Message',
                orderable: false,
                render: function (data) {
                    return data || '';
                }
            },
            { data: 'backup_set_name', title: 'Backup Set ID', visible: false },
            {
                data: null,
                title: 'Options',
                orderable: false,
                render: function (data, type, row) {
                    const encryptIcon = (row.encrypt === true || row.encrypt === 1)
                        ? '<i class="fa fa-lock text-warning me-2" title="Encryption enabled"></i>'
                        : '<i class="fa fa-lock-open text-secondary me-2" title="Encryption disabled"></i>';
                    const syncIcon = (row.sync === true || row.sync === 1)
                        ? '<i class="fa fa-cloud-upload-alt text-success" title="Sync enabled"></i>'
                        : '<i class="fa fa-cloud-upload-alt text-secondary" title="Sync disabled"></i>';
                    return encryptIcon + syncIcon;
                }
            },
            { data: 'runtime', title: 'Runtime' },
            {
                data: 'files_count',
                title: 'Files',
                render: function (data) {
                    return data ? Number(data).toLocaleString() : '—';
                }
            },
            {
                data: 'bytes_processed',
                title: 'Bytes',
                render: function (data) {
                    return data ? formatBytes(data) : '—';
                }
            },
            {
                data: 'status',
                title: 'Status',
                render: function (data) {
                    return renderStatusBadge(data);
                }
            },
            {
                data: 'id',
                title: '',
                orderable: false,
                render: function (data) {
                    return `<button type="button" class="btn btn-sm btn-outline-danger delete-job-btn" data-job-id="${data}" title="Delete this job record"><i class="fa fa-trash"></i></button>`;
                }
            }
        ],
        columnDefs: [
            { targets: [2, 5, 6, 9, 10], className: 'text-center' },
            { targets: [7, 8], className: 'text-end' }
        ],
        lengthMenu: [[25, 50, 75, 100], [25, 50, 75, 100]],
        pageLength: 25,
        // Group by Backup Set ID only (agent is implicit — this page is
        // scoped to a single agent already). Newest backup set first.
        order: [[4, 'desc'], [0, 'desc']],
        rowGroup: {
            dataSrc: 'backup_set_name',
            startRender: function (rows, group) {
                return `<i class="fa fa-layer-group me-1"></i>Backup Set: ${group || '—'}`;
            },
            endRender: function (rows, group) {
                const totalFiles = rows
                    .data()
                    .pluck('files_count')
                    .reduce((a, b) => a + (Number(b) || 0), 0);
                const totalBytes = rows
                    .data()
                    .pluck('bytes_processed')
                    .reduce((a, b) => a + (Number(b) || 0), 0);

                return `<div class="text-end">Backup Set: ${group || '—'} totals — Files: ${totalFiles.toLocaleString()}, Bytes: ${formatBytes(totalBytes)}</div>`;
            }
        },
        responsive: true,
        paging: true,
        searching: true,
        ordering: true,
        language: {
            search: "Filter jobs:",
            lengthMenu: "Show _MENU_ jobs",
            info: "Showing _START_ to _END_ of _TOTAL_ jobs",
            emptyTable: "No jobs reported by this agent yet."
        }
    });

    $('#recentJobsTable tbody').on('click', '.delete-job-btn', function () {
        const jobId = $(this).data('job-id');
        if (!confirm('Delete this job record? This cannot be undone.')) {
            return;
        }
        fetch('/api/backup_jobs/delete', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ ids: [jobId] })
        })
            .then(response => response.json())
            .then(result => {
                if (result.success) {
                    recentJobsTable.ajax.reload(null, false);
                } else {
                    alert('Failed to delete job: ' + (result.error || 'unknown error'));
                }
            })
            .catch(err => {
                alert('Failed to delete job: ' + err);
            });
    });

    // Deep-link support: if the page was opened with ?set=<backup_set_name>
    // (from index.html's eventsTable "Backup Set ID" links), filter the
    // table down to just that backup set's rows and scroll to them.
    const setParam = new URLSearchParams(window.location.search).get('set');
    if (setParam) {
        recentJobsTable.one('draw', function () {
            const escaped = setParam.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
            recentJobsTable.column(4).search(`^${escaped}$`, true, false).draw();
            setTimeout(function () {
                const rowNode = recentJobsTable.column(4).nodes().to$().filter(function () {
                    return $(this).text() === setParam;
                }).closest('tr')[0];
                if (rowNode) {
                    rowNode.scrollIntoView({ behavior: 'smooth', block: 'center' });
                    $(rowNode).addClass('table-active');
                }
            }, 100);
        });
    }

    return recentJobsTable;
}

document.addEventListener('DOMContentLoaded', function () {
    const detail = window.AGENT_DETAIL || {};
    initializeAgentDetailCharts(detail);
    initializeRecentJobsTable(detail.agentId);
});
