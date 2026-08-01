// filepath: /home/jim2/jabs3/static/js/global.js

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

// --- Shared Status Badge Renderer (used by eventsTable and recentJobsTable) ---
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
  if (s === 'running') {
    return '<span class="badge bg-info"><i class="fas fa-spinner fa-spin me-1"></i>running</span>';
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
    running: 'bg-info'
  };
  return Object.keys(statusCounts).sort().map(function (status) {
    const count = statusCounts[status];
    const colorClass = statusColors[status.toLowerCase()] || 'bg-light text-dark';
    return `<span class="badge ${colorClass} me-1">${status}: ${count}</span>`;
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
    running: '#0dcaf0',
    unknown: '#adb5bd'
  };
  return colors[(status || '').toLowerCase()] || '#0d6efd';
}
// --- End Shared Status Chart Color Mapping ---


$(document).ready(function () { // Ensure DOM is ready

    // --- Apply Stored Theme on Load  ---
    const savedTheme = localStorage.getItem('theme') || 'auto';
    applyTheme(savedTheme);
    // --- End Apply Stored Theme ---

}); // End document ready