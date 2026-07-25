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
    const trendData = detail.trendData || [];

    const statusColors = {
        success: '#198754', completed: '#198754',
        error: '#dc3545', failed: '#dc3545',
        skipped: '#6c757d',
        running: '#0dcaf0',
        unknown: '#adb5bd'
    };

    const statusLabels = Object.keys(statusCounts);
    if (statusLabels.length) {
        new Chart(document.getElementById('statusChart'), {
            type: 'doughnut',
            data: {
                labels: statusLabels,
                datasets: [{
                    data: statusLabels.map(k => statusCounts[k]),
                    backgroundColor: statusLabels.map(k => statusColors[k] || '#0d6efd')
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

    new Chart(document.getElementById('trendChart'), {
        type: 'bar',
        data: {
            labels: trendLabels,
            datasets: [{
                label: 'Jobs per day',
                data: trendData,
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

function initializeRecentJobsTable(hostId) {
    const recentJobsTable = $('#recentJobsTable').DataTable({
        ajax: {
            url: `/api/agent_jobs/${hostId}`,
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
            }
        ],
        columnDefs: [
            { targets: [2, 5, 6, 9], className: 'text-center' },
            { targets: [7, 8], className: 'text-end' }
        ],
        lengthMenu: [[25, 50, 75, 100], [25, 50, 75, 100]],
        pageLength: 25,
        // Group by Backup Set ID only (host is implicit — this page is
        // scoped to a single host already). Newest backup set first.
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
}

document.addEventListener('DOMContentLoaded', function () {
    const detail = window.AGENT_DETAIL || {};
    initializeAgentDetailCharts(detail);
    initializeRecentJobsTable(detail.hostId);
});
