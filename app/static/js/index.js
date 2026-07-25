// Index page JavaScript - Dashboard functionality

$(document).ready(function () {
    // --- Dashboard Backup Sets Table ---
    // One row per backup_set_id, aggregating all runs (full/incremental/
    // differential) that share that set.
    const eventsTable = $('#eventsTable').DataTable({
        ajax: {
            url: '/api/backup_sets', // Fetch aggregated data from the Flask API
            dataSrc: 'data'          // Assumes response is { "data": [...] }
        },
        columns: [
            {
                // Displays the human-friendly backup_set_name, but the
                // underlying backup_set_id (unique across hosts/jobs) is
                // used for sorting/searching via the render's 'sort'/'filter' types.
                data: 'backup_set_name',
                title: 'Backup Set ID',
                render: function (data, type, row) {
                    if (type === 'sort' || type === 'filter') {
                        return row.backup_set_id || data || '';
                    }
                    return data || '';
                }
            },
            { data: 'host', title: 'Host' },
            { data: 'job_name', title: 'Backup Title' },
            { data: 'start_time', title: 'Start Time' },
            { data: 'last_event_time', title: 'Last Event Time' },
            {
                data: 'status_counts',
                title: 'Status Summary',
                render: function (data) {
                    return renderStatusSummaryPills(data);
                }
            }
        ],
        columnDefs: [
            { targets: [1, 2, 3, 4, 5], className: 'text-center' }
        ],
        lengthMenu: [[25, 50, 75, 100], [25, 50, 75, 100]],
        pageLength: 25,
        language: {
            search: "Filter backup sets:",
            lengthMenu: "Show _MENU_ backup sets",
            info: "Showing _START_ to _END_ of _TOTAL_ backup sets",
        },
        responsive: true,
        paging: true,
        searching: true,
        ordering: true,
        order: [[3, 'desc']]
    });

    // Purge dropdown logic
    $(document).on('click', '.purge-action', function (e) {
        e.preventDefault();
        const status = $(this).data('status');
        if (confirm(`Are you sure you want to purge all "${status}" events?`)) {
            fetch(`/purge_events/${status}`, {method: 'POST'})
                .then(resp => resp.json())
                .then(data => {
                    alert(data.message);
                    // Reload the events table only, not the whole page
                    if ($('#eventsTable').length && $.fn.DataTable.isDataTable('#eventsTable')) {
                        $('#eventsTable').DataTable().ajax.reload(null, false);
                    } else {
                        location.reload();
                    }
                });
        }
    });

    // --- Persistent Drag-and-Drop for Dashboard Cards ---
    const dashboardRow = document.getElementById('dashboard-cards-row');
    const CARD_ORDER_KEY = "dashboardCardOrder";

    // Restore card order from localStorage
    function restoreCardOrder() {
        const order = JSON.parse(localStorage.getItem(CARD_ORDER_KEY) || "[]");
        if (order.length && dashboardRow) {
            // Get current cards as an array
            const cards = Array.from(dashboardRow.children);
            // Sort cards according to saved order
            order.forEach(cardId => {
                const card = cards.find(c => c.id === cardId);
                if (card) dashboardRow.appendChild(card);
            });
        }
    }

    // Save card order to localStorage
    function saveCardOrder() {
        if (!dashboardRow) return;
        const order = Array.from(dashboardRow.children).map(card => card.id);
        localStorage.setItem(CARD_ORDER_KEY, JSON.stringify(order));
    }

    // Assign unique IDs to each dashboard card if not already set
    if (dashboardRow) {
        Array.from(dashboardRow.children).forEach((card, idx) => {
            if (!card.id) card.id = `dashboard-card-${idx + 1}`;
        });
        restoreCardOrder();
    }

    // Make the dashboard cards row sortable
    if (window.Sortable && dashboardRow) {
        new Sortable(dashboardRow, {
            animation: 150,
            handle: '.fa-arrows-alt',
            draggable: '.dashboard-card',
            ghostClass: 'sortable-ghost',
            onEnd: saveCardOrder // Save order after drag-and-drop
        });
    } else {
        console.warn("SortableJS is not loaded. Drag-and-drop for dashboard cards will not work.");
    }

    // --- Charts Initialization ---
    let diskUsageChart = null;
    function initializeDiskUsageChart() {
        fetch('/api/disk_usage')
            .then(response => response.json())
            .then(data => {
                console.log("Disk Usage Data:", data);
                if (!Array.isArray(data) || data.length === 0) {
                    console.warn("No disk usage data received or data is empty.");
                    const canvas = document.getElementById('diskUsageChart');
                    if (canvas) {
                        const ctx = canvas.getContext('2d');
                        ctx.font = '16px Arial';
                        ctx.fillStyle = '#888';
                        ctx.textAlign = 'center';
                        ctx.fillText('No disk usage data available.', canvas.width / 2, canvas.height / 2);
                    }
                    return;
                }

                const labels = data.map(d => d.label || d.drive || 'Unknown Drive');
                const usedData = data.map(d => d.used_gib || 0);
                const freeData = data.map(d => d.free_gib || 0);

                const ctx = document.getElementById('diskUsageChart')?.getContext('2d');
                if (!ctx) {
                    console.error("Disk usage chart canvas not found.");
                    return;
                }

                if (diskUsageChart) {
                    diskUsageChart.destroy();
                }

                diskUsageChart = new Chart(ctx, {
                    type: 'bar',
                    data: {
                        labels: labels,
                        datasets: [
                            {
                                label: 'Used GiB',
                                data: usedData,
                                backgroundColor: 'rgba(255, 99, 132, 0.6)',
                                borderColor: 'rgba(255, 99, 132, 1)',
                                borderWidth: 1
                            },
                            {
                                label: 'Free GiB',
                                data: freeData,
                                backgroundColor: 'rgba(75, 192, 192, 0.6)',
                                borderColor: 'rgba(75, 192, 192, 1)',
                                borderWidth: 1
                            }
                        ]
                    },
                    options: {
                        indexAxis: 'y',
                        responsive: true,
                        maintainAspectRatio: false,
                        plugins: {
                            legend: { position: 'top' },
                            tooltip: {
                                callbacks: {
                                    label: function (context) {
                                        const total = (usedData[context.dataIndex] || 0) + (freeData[context.dataIndex] || 0);
                                        const percent = total > 0 ? ((context.raw / total) * 100).toFixed(1) : 0;
                                        return `${context.dataset.label}: ${context.raw.toFixed(1)} GiB (${percent}%)`;
                                    }
                                }
                            },
                            datalabels: {
                                anchor: 'center',
                                align: 'center',
                                formatter: function (value, context) {
                                    const total = (usedData[context.dataIndex] || 0) + (freeData[context.dataIndex] || 0);
                                    if (context.dataset.label === 'Used GiB' && total > 0) {
                                        const percent = ((value / total) * 100).toFixed(1);
                                        return `${percent}%`;
                                    }
                                    return null;
                                },
                                color: '#f4f4f4'
                            }
                        },
                        scales: {
                            x: {
                                stacked: true,
                                grid: { color: 'rgba(255,255,255,0.15)' },
                                title: { display: true, text: 'GiB' }
                            },
                            y: {
                                stacked: true,
                                grid: { color: 'rgba(255,255,255,0.15)' }
                            }
                        }
                    },
                    plugins: [ChartDataLabels]
                });
            })
            .catch(error => {
                console.error("Failed to load disk usage data:", error);
                const canvas = document.getElementById('diskUsageChart');
                 if (canvas) {
                        const ctx = canvas.getContext('2d');
                        ctx.font = '16px Arial';
                        ctx.fillStyle = '#dc3545';
                        ctx.textAlign = 'center';
                        ctx.fillText('Error loading disk usage data.', canvas.width / 2, canvas.height / 2);
                    }
            });
    }

    let s3UsageChart = null;
    function initializeS3UsageChart() {        fetch('/api/s3_usage')
            .then(response => response.json())
            .then(data => {
                if (data.error) {
                    const canvas = document.getElementById('s3UsageChart');
                    if (canvas) {
                        const ctx = canvas.getContext('2d');
                        ctx.font = '16px Arial';
                        ctx.fillStyle = '#dc3545';
                        ctx.textAlign = 'center';
                        ctx.fillText(data.error, canvas.width / 2, canvas.height / 2);
                    }
                    return;
                }

                console.log("S3 Usage Data:", data);
                 if (!Array.isArray(data) || data.length === 0) {
                    console.warn("No S3 usage data received or data is empty.");
                    const canvas = document.getElementById('s3UsageChart');
                    if (canvas) {
                        const ctx = canvas.getContext('2d');
                        ctx.font = '16px Arial';
                        ctx.fillStyle = '#888';
                        ctx.textAlign = 'center';
                        ctx.fillText('No S3 usage data available.', canvas.width / 2, canvas.height / 2);
                    }
                    return;
                }

                const labels = data.map(bucket => bucket.label || bucket.bucket || 'Unknown Bucket');
                const datasets = [];
                const totalUsageBytes = Array(labels.length).fill(0);

                const colorCache = {};
                let colorIndex = 0;
                const baseColors = [
                    [114, 147, 203], [225, 151, 76], [132, 186, 91], [211, 94, 96],
                    [128, 133, 133], [144, 103, 167], [171, 104, 87], [204, 194, 16]
                ];
                function getColor(label) {
                    if (!colorCache[label]) {
                        const color = baseColors[colorIndex % baseColors.length];
                        colorCache[label] = `rgba(${color[0]}, ${color[1]}, ${color[2]}, 0.6)`;
                        colorIndex++;
                    }
                    return colorCache[label];
                }

                // Collect raw byte values per (bucket, host-prefix) so we can
                // pick a sensible display unit (bytes are tiny for test
                // backups, so fixing the unit to GiB made everything round to 0).
                // Only the top-level prefix (host) becomes a chart segment —
                // sub_prefixes (jobs) are already included in the host's
                // total, so stacking them too would double-count bytes and
                // render as extra phantom segments. Sub-prefix detail is
                // still surfaced in the tooltip.
                const rawEntries = [];

                data.forEach((bucket, bucketIndex) => {
                    if (bucket.error) {
                        console.error(`Error fetching S3 data for bucket ${bucket.bucket}: ${bucket.error}`);
                        return;
                    }
                    if (!bucket.prefixes) return;

                    bucket.prefixes.forEach(prefix => {
                        const prefixBytes = prefix.size_bytes || 0;
                        totalUsageBytes[bucketIndex] += prefixBytes;

                        rawEntries.push({
                            label: prefix.prefix || 'Root',
                            bucketIndex,
                            bytes: prefixBytes,
                            subPrefixes: prefix.sub_prefixes || []
                        });
                    });
                });

                // Pick a single display unit for the whole chart, based on the
                // largest bucket total, so small test backups are still visible.
                const units = [
                    { label: 'B', divisor: 1 },
                    { label: 'KiB', divisor: 1024 },
                    { label: 'MiB', divisor: 1024 ** 2 },
                    { label: 'GiB', divisor: 1024 ** 3 },
                    { label: 'TiB', divisor: 1024 ** 4 }
                ];
                const maxBytes = Math.max(0, ...totalUsageBytes);
                let unit = units[0];
                for (const candidate of units) {
                    if (maxBytes >= candidate.divisor) {
                        unit = candidate;
                    }
                }

                const totalUsage = totalUsageBytes.map(b => b / unit.divisor);

                rawEntries.forEach(entry => {
                    const value = entry.bytes / unit.divisor;
                    const color = getColor(entry.label);
                    datasets.push({
                        label: entry.label,
                        data: labels.map((_, index) => (index === entry.bucketIndex ? value : 0)),
                        backgroundColor: color,
                        borderColor: color.replace('0.6', '1'),
                        borderWidth: 1,
                        subPrefixes: entry.subPrefixes
                    });
                });

                const ctx = document.getElementById('s3UsageChart')?.getContext('2d');
                 if (!ctx) {
                    console.error("S3 usage chart canvas not found.");
                    return;
                }

                if (s3UsageChart) {
                    s3UsageChart.destroy();
                }

                s3UsageChart = new Chart(ctx, {
                    type: 'bar',
                    data: {
                        labels: labels,
                        datasets: datasets
                    },
                    options: {
                        indexAxis: 'y',
                        responsive: true,
                        maintainAspectRatio: false,
                        plugins: {
                            legend: { display: false },
                            tooltip: {
                                callbacks: {
                                    label: function (context) {
                                        return `${context.dataset.label}: ${context.raw.toFixed(2)} ${unit.label}`;
                                    },
                                    afterLabel: function (context) {
                                        const subPrefixes = context.dataset.subPrefixes || [];
                                        if (!subPrefixes.length) return null;
                                        return subPrefixes.map(sp => {
                                            const spValue = (sp.size_bytes || 0) / unit.divisor;
                                            return `  ${sp.prefix || 'Unknown'}: ${spValue.toFixed(2)} ${unit.label}`;
                                        });
                                    }
                                }
                            },
                            datalabels: {
                                anchor: 'end',
                                align: 'end',
                                formatter: function (value, context) {
                                    const isLastDataset = context.chart.data.datasets
                                        .filter(ds => ds.data[context.dataIndex] > 0)
                                        .slice(-1)[0] === context.dataset;

                                    if (isLastDataset) {
                                        return `${totalUsage[context.dataIndex].toFixed(2)} ${unit.label}`;
                                    }
                                    return null;
                                },
                                color: '#fff'
                            }
                        },
                        scales: {
                            x: {
                                stacked: true,
                                grid: { color: 'rgba(255,255,255,0.15)' },
                                title: { display: true, text: unit.label }
                            },
                            y: {
                                stacked: true,
                                grid: { color: 'rgba(255,255,255,0.15)' }
                            }
                        }
                    },
                    plugins: [ChartDataLabels]
                });
            })
            .catch(error => {
                console.error("Failed to load S3 usage data:", error);
                 const canvas = document.getElementById('s3UsageChart');
                 if (canvas) {
                        const ctx = canvas.getContext('2d');
                        ctx.font = '16px Arial';
                        ctx.fillStyle = '#dc3545';
                        ctx.textAlign = 'center';
                        ctx.fillText('Error loading S3 usage data.', canvas.width / 2, canvas.height / 2);
                    }
            });
    }

    // Activity Trend chart (all agents, last 30 days) — data is bootstrapped
    // server-side into window.DASHBOARD_TREND (see index.html).
    let trendChart = null;
    function initializeTrendChart() {
        const trend = window.DASHBOARD_TREND || {};
        const trendLabels = trend.trendLabels || [];
        const trendData = trend.trendData || [];
        const canvas = document.getElementById('trendChart');
        if (!canvas) return;

        if (trendChart) {
            trendChart.destroy();
        }

        trendChart = new Chart(canvas, {
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

    // Initialize charts
    initializeDiskUsageChart();
    initializeS3UsageChart();
    initializeTrendChart();

    // --- Refresh dashboard data periodically ---
    // Events table: near real-time (short interval), matches existing behavior.
    setInterval(function () {
        eventsTable.ajax.reload(null, false);
    }, 10000); // every 10 seconds

    // Connected Agents card, Network Storage chart, and Cloud Storage chart:
    // these change less frequently, so refresh every few minutes. The Cloud
    // Storage endpoint is backed by a server-side cache (refreshed in the
    // background when stale), so polling it periodically is what allows the
    // chart to ever pick up newly-refreshed data without a full page reload.
    function refreshAgentsCard() {
        fetch('/partials/agents-card')
            .then(response => response.text())
            .then(html => {
                const container = document.getElementById('agents-card-body');
                if (container) container.innerHTML = html;
            })
            .catch(error => console.error("Failed to refresh Connected Agents card:", error));
    }

    setInterval(function () {
        refreshAgentsCard();
        initializeDiskUsageChart();
        initializeS3UsageChart();
    }, 120000); // every 2 minutes

}); // End document ready