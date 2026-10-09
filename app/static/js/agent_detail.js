// agent_detail.html JavaScript - status/trend charts and the
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

// renderStatusBadge() is defined in global.js (shared with jobsTable).
// formatRate() and startAutoRefresh() are also defined in global.js.

// Runtime column: a live progress bar while running (striped/indeterminate
// if the agent didn't report percent_complete), otherwise the already
// human-formatted runtime string from the server.
function renderRuntime(data, type, row) {
    if (type !== 'display') return data;
    if (row.status !== 'running') return data;

    const pct = row.percent_complete;
    const hasPct = pct !== null && pct !== undefined;
    const barStyle = hasPct ? `width: ${pct}%` : 'width: 100%';
    const barClass = hasPct
        ? 'progress-bar progress-bar-striped progress-bar-animated'
        : 'progress-bar progress-bar-striped progress-bar-animated bg-secondary';
    // The label is overlaid centered on the container (not placed inside the
    // fill div) so it stays legible at low percentages, where the fill div
    // itself is too narrow to display its own text.
    const label = hasPct ? `${pct}%` : '';
    const eta = row.eta_seconds ? ` &middot; ETA ${formatEta(row.eta_seconds)}` : '';
    return `
        <div class="progress position-relative" style="height: 1.1rem; min-width: 90px;" title="${row.current_item || ''}">
            <div class="${barClass}" style="${barStyle}"></div>
            <span class="position-absolute w-100 text-center small" style="left: 0; top: 0; line-height: 1.1rem; mix-blend-mode: difference; color: white;">${label}</span>
        </div>
        <div class="small text-muted">${row.current_item || ''}${eta}</div>
    `;
}

function formatEta(seconds) {
    const s = Number(seconds) || 0;
    const m = Math.floor(s / 60);
    const r = Math.round(s % 60);
    return m > 0 ? `${m}m ${r}s` : `${r}s`;
}

// Rate column: live bytes_per_second while running, otherwise the average
// computed from the finalized bytes_processed/runtime.
function renderRate(data, type, row) {
    if (type !== 'display') return data;
    if (row.status === 'running') {
        return row.bytes_per_second ? formatRate(row.bytes_per_second) : '—';
    }
    const runtimeSeconds = row.runtime_seconds_raw;
    if (row.bytes_processed && runtimeSeconds) {
        return formatRate(row.bytes_processed / runtimeSeconds) + ' avg';
    }
    return '—';
}

function initializeAgentDetailCharts(detail) {
    const statusCounts = detail.statusCounts || {};
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

    // Job Activity trend, segmented (stacked) by status.
    const trendStatuses = Object.keys(trendDatasets);
    new Chart(document.getElementById('trendChart'), {
        type: 'bar',
        data: {
            labels: trendLabels,
            datasets: trendStatuses.map(status => ({
                label: status,
                data: trendDatasets[status],
                backgroundColor: getStatusChartColor(status),
                barPercentage: 1.0,
                categoryPercentage: 0.95
            }))
        },
        options: {
            responsive: true,
            maintainAspectRatio: false,
            plugins: { legend: { position: 'bottom' } },
            scales: {
                x: { stacked: true, ticks: { display: false } },
                y: { stacked: true, beginAtZero: true, ticks: { precision: 0 } }
            }
        }
    });
}

function initializeeventsTable(agentId) {
    const eventsTable = $('#eventsTable').DataTable({
        ajax: {
            url: `/api/agent_jobs/${agentId}`,
            dataSrc: 'data'
        },
        columns: [
            { data: 'starttimestamp', title: 'Start' },
            { data: 'job_name', title: 'Job Name', visible: false },
            { data: 'backup_type', title: 'Type' },
            {
                data: 'event',
                title: 'Message',
                orderable: false,
                render: function (data) {
                    return data || '';
                }
            },
            { data: 'target_id', title: 'Job Target', visible: false },
            { data: 'runtime', title: 'Runtime', render: renderRuntime },
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
                data: 'bytes_per_second',
                title: 'Rate',
                orderable: false,
                render: renderRate
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
            { targets: [2, 5, 9, 10], className: 'text-center' },
            { targets: [6, 7, 8], className: 'text-end' }
        ],
        lengthMenu: [[25, 50, 75, 100], [25, 50, 75, 100]],
        pageLength: 25,
        // Two-level grouping: Job Name (the coarser NAS1→NAS2-style
        // direction/job) outermost, then Job Target (the stable per-pair/
        // per-run-set ID) nested inside it. Newest target first within each
        // level.
        order: [[1, 'asc'], [4, 'desc'], [0, 'desc']],
        rowGroup: {
            // Function-based dataSrc so an empty/legacy job_name or target_id
            // never falls through to RowGroup's default "No group" bucket —
            // it groups under our own '—' label instead, consistent with the
            // rest of the table.
            dataSrc: [
                function (rowData) { return rowData.job_name || '—'; },
                function (rowData) { return rowData.target_id || '—'; }
            ],
            startRender: function (rows, group, level) {
                if (level === 0) {
                    return `<i class="fa fa-folder me-1"></i> ${group}`;
                }
                const label = rows.data()[0].target_label || group;
                return `<i class="fa fa-layer-group me-1"></i> ${label}`;
            }
        },
        responsive: true,
        paging: true,
        searching: true,
        ordering: true,
        language: {
            search: "Filter Jobs:",
            lengthMenu: "Show _MENU_ Jobs",
            info: "Showing _START_ to _END_ of _TOTAL_ Jobs",
            emptyTable: "No jobs reported by this agent yet."
        }
    });

    $('#eventsTable tbody').on('click', '.delete-job-btn', function () {
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
                    eventsTable.ajax.reload(null, false);
                } else {
                    alert('Failed to delete job: ' + (result.error || 'unknown error'));
                }
            })
            .catch(err => {
                alert('Failed to delete job: ' + err);
            });
    });

    // Deep-link support: if the page was opened with ?job_name=<job_name>
    // (from index.html's jobsTable row links), filter the table down to
    // just that job_name's rows and scroll to them. A "Show All" button
    // (hidden by default) is revealed so the user can clear the filter and
    // see every job again without reloading the page.
    const jobNameParam = new URLSearchParams(window.location.search).get('job_name');
    const $showAllBtn = $('#showAllJobsBtn');
    if (jobNameParam) {
        eventsTable.one('draw', function () {
            const escaped = jobNameParam.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
            eventsTable.column(1).search(`^${escaped}$`, true, false).draw();
            $showAllBtn.removeClass('d-none');
            setTimeout(function () {
                const rowNode = eventsTable.column(1).nodes().to$().filter(function () {
                    return $(this).text() === jobNameParam;
                }).closest('tr')[0];
                if (rowNode) {
                    rowNode.scrollIntoView({ behavior: 'smooth', block: 'center' });
                    $(rowNode).addClass('table-active');
                }
            }, 100);
        });
    }

    $showAllBtn.on('click', function () {
        eventsTable.column(1).search('').draw();
        $showAllBtn.addClass('d-none');
        // Drop the ?job_name= param from the URL without reloading the page.
        const url = new URL(window.location.href);
        url.searchParams.delete('job_name');
        window.history.replaceState({}, '', url);
    });

    // Keep running jobs' progress/rate fresh without a full page reload.
    // RowGroup fully tears down and rebuilds <tbody> on every draw, which
    // can momentarily collapse the table's height. Restoring scroll alone
    // isn't enough — if scrolled to the bottom, the browser clamps the
    // scroll position the instant the document shrinks, before our restore
    // callback runs, producing a visible jump-and-snap-back. Locking the
    // wrapper's height for the duration of the reload prevents the collapse
    // (and thus the clamp) from happening at all; the scroll restore below
    // is then just a safety net.
    startAutoRefresh(function () {
        const wrapper = document.getElementById('eventsTable_wrapper');
        const scrollPos = window.scrollY;
        if (wrapper) wrapper.style.minHeight = `${wrapper.offsetHeight}px`;
        eventsTable.ajax.reload(function () {
            if (wrapper) wrapper.style.minHeight = '';
            window.scrollTo(window.scrollX, scrollPos);
        }, false);
    }, 5000);
    startAutoRefresh(function () {
        refreshAgentSummary(agentId);
    }, 5000);

    return eventsTable;
}

// Refresh the stat cards + Summary table, which otherwise stay frozen at
// whatever they were when the page was first loaded.
function refreshAgentSummary(agentId) {
    fetch(`/api/agent_summary/${agentId}`)
        .then(response => response.json())
        .then(data => {
            if (data.error) return;
            document.getElementById('statTotalJobs').textContent = data.total_jobs;
            document.getElementById('statSuccess').textContent = data.success;
            document.getElementById('statErrors').textContent = data.errors;
            document.getElementById('statRunning').textContent = data.running;
            document.getElementById('statStopped').textContent = data.stopped;
            document.getElementById('statPurged').textContent = data.purged;
            document.getElementById('sumFiles').textContent = data.total_files.toLocaleString();
            document.getElementById('sumBytes').textContent = data.total_bytes_fmt;
            document.getElementById('sumAvgRuntime').textContent = data.avg_runtime_fmt;
            document.getElementById('sumLastRun').textContent = data.last_run_fmt;
        })
        .catch(error => console.error('Failed to refresh agent summary:', error));
}

document.addEventListener('DOMContentLoaded', function () {
    const detail = window.AGENT_DETAIL || {};
    initializeAgentDetailCharts(detail);
    initializeeventsTable(detail.agentId);
});
