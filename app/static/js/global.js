// --- Theme Switcher Functions ---
function setTheme(mode) {
  localStorage.setItem('theme', mode);
  applyTheme(mode);
}

function applyTheme(mode) {
  const root = document.documentElement;
  let iconClass = 'fa-circle-half-stroke'; // Default for 'auto'

  if (mode === 'light') {
    root.setAttribute('data-bs-theme', 'light');
    iconClass = 'fa-sun text-warning';
  } else if (mode === 'dark') {
    root.setAttribute('data-bs-theme', 'dark');
    iconClass = 'fa-moon text-primary';
  } else { // 'auto' or invalid
    root.removeAttribute('data-bs-theme'); // Use OS preference via CSS media query
    iconClass = 'fa-circle-half-stroke text-secondary'; // Icon for auto
  }

  // Update both desktop and mobile theme icons
  document.querySelectorAll('#currentThemeIcon, #currentThemeIconMobile').forEach(icon => {
      if (icon) { // Check if icon exists on the page
         icon.className = 'fas me-2 ' + iconClass;
      }
  });
}
// --- End Theme Switcher Functions ---

// --- Shared Status Badge Renderer (used by jobsTable and eventsTable) ---
function renderStatusBadge(status) {
  const s = (status || '').toLowerCase();
  if (s === 'success' || s === 'completed') {
    return `<span class="badge bg-success">${s}</span>`;
  }
  if (s === 'error' || s === 'failed') {
    return `<span class="badge bg-danger">${s}</span>`;
  }
  if (s === 'skipped') {
    return `<span class="badge bg-secondary">${s}</span>`;
  }
  if (s === 'stopped') {
    return '<span class="badge bg-warning text-dark">stopped</span>';
  }
  if (s === 'running') {
    return '<span class="badge bg-info"><i class="fas fa-spinner fa-spin me-1"></i>running</span>';
  }
  if (s === 'purged') {
    return '<span class="badge bg-dark"><i class="fas fa-trash me-1"></i>purged</span>';
  }
  return `<span class="badge bg-light text-dark">${s || 'unknown'}</span>`;
}
// --- End Shared Status Badge Renderer ---


// --- Shared Status Summary Pills Renderer (e.g. {"success": 2, "error": 1}) ---
function renderStatusSummaryPills(statusCounts) {
  if (!statusCounts || typeof statusCounts !== 'object') return '';
  const statusColors = {
    success: 'bg-success',
    completed: 'bg-success',
    error: 'bg-danger',
    failed: 'bg-danger',
    skipped: 'bg-secondary',
    stopped: 'bg-warning text-dark', //see global.css for custom color to match Chart below
    running: 'bg-info',
    purged: 'bg-dark'
  };
  return Object.keys(statusCounts).sort().map(function (status) {
    const count = statusCounts[status];
    const colorClass = statusColors[status.toLowerCase()] || 'bg-light text-dark';
    return `<span class="badge ${colorClass} me-1"> ${count} </span>`;
    // return `<span class="badge ${colorClass} me-1">${status}: ${count}</span>`;
  }).join('');
}
// --- End Shared Status Summary Pills Renderer ---

// --- Shared Status Chart Color Mapping (used by Job Activity trend charts) ---
function getStatusChartColor(status) {
  const colors = {
    success: '#198754',
    completed: '#198754',
    error: '#dc3545',
    failed: '#dc3545',
    skipped: '#6c757d',
    stopped: '#b88c09',
    running: '#0dcaf0',
    purged: '#495057',
    unknown: '#adb5bd'
  };
  return colors[(status || '').toLowerCase()] || '#0d6efd';
}
// --- End Shared Status Chart Color Mapping ---

// --- Shared Status Icon Renderer (small at-a-glance icon, e.g. next to a timestamp) ---
function getStatusIcon(status) {
  const s = (status || '').toLowerCase();
  const icons = {
    success: 'fa-check-circle text-success',
    completed: 'fa-check-circle text-success',
    error: 'fa-times-circle text-danger',
    failed: 'fa-times-circle text-danger',
    skipped: 'fa-forward text-secondary',
    stopped: 'fa-pause-circle text-warning',
    running: 'fa-spinner fa-spin text-info',
    purged: 'fa-trash text-dark'
  };
  const iconClass = icons[s] || 'fa-question-circle text-muted';
  return `<i class="fas ${iconClass}" title="${s || 'unknown'}"></i>`;
}
// --- End Shared Status Icon Renderer ---

// --- Shared Transfer Rate Formatter (bytes/sec -> human-readable string) ---
function formatRate(bytesPerSecond) {
  const n = Number(bytesPerSecond);
  if (!n || n <= 0) return '—';
  const units = ['B/s', 'KiB/s', 'MiB/s', 'GiB/s', 'TiB/s'];
  let value = n;
  for (const unit of units) {
    if (Math.abs(value) < 1024.0) {
      return `${value.toFixed(1)} ${unit}`;
    }
    value /= 1024.0;
  }
  return `${value.toFixed(1)} PiB/s`;
}
// --- End Shared Transfer Rate Formatter ---

// --- Shared Auto-Refresh Helper (pauses while the tab is backgrounded) ---
// Wraps setInterval so pages don't keep polling a hidden/background tab.
function startAutoRefresh(fn, intervalMs) {
  return setInterval(function () {
    if (document.hidden) return;
    fn();
  }, intervalMs);
}
// --- End Shared Auto-Refresh Helper ---


$(document).ready(function () { // Ensure DOM is ready

    // --- Apply Stored Theme on Load  ---
    const savedTheme = localStorage.getItem('theme') || 'auto';
    applyTheme(savedTheme);
    // --- End Apply Stored Theme ---

}); // End document ready