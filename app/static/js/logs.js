  
    document.getElementById("trimLogsButton").addEventListener("click", function () {
        if (confirm("Are you sure you want to trim all logs? This will keep only the last " + window.MAX_LOG_LINES + " lines of each log file.")) {
            fetch('/api/trim_logs', { method: 'POST' })
            .then(response => response.json())
            .then (data => {
                alert("Logs have been trimmed successfully!");
                location.reload();
            })
            .catch(error => {
                alert("An error occurred while trimming the logs.");
            });
        }
    });

    // raw text cache: { [logName]: { [tail || 'full']: text } }
    const logContentCache = {};

    function fetchLogContent(logName, tail) {
        const key = tail || 'full';
        logContentCache[logName] = logContentCache[logName] || {};
        if (logContentCache[logName][key] !== undefined) {
            return Promise.resolve(logContentCache[logName][key]);
        }
        const url = '/logs/content/' + encodeURIComponent(logName) + (tail ? '?tail=' + tail : '');
        return fetch(url)
            .then(response => response.json())
            .then(data => {
                logContentCache[logName][key] = data.content;
                return data.content;
            });
    }

    // Renders rawText into pre with syntax colorization, tracking the raw source for later filter/search passes.
    function renderLogContent(pre, rawText) {
        pre.dataset.rawContent = rawText;

        let html = rawText
            .replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')

            // --- timestamps: both "2026-09-25 12:08:21,281" and "[2026-09-25 08:00:10]"
            .replace(/(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}(?:,\d+)?)/g,
                '<span class="log-ts">$1</span>')

            // --- levels, both "INFO:" (werkzeug) and bracketed "] INFO" (nas_sync) styles
            .replace(/\b(ERROR|CRITICAL|FATAL)\b:?/g, '<span class="lvl-error">$&</span>')
            .replace(/\b(WARNING|WARN)\b:?/g, '<span class="lvl-warn">$&</span>')
            .replace(/\bINFO\b:?/g, '<span class="lvl-info">$&</span>')
            .replace(/\bDEBUG\b:?/g, '<span class="lvl-debug">$&</span>')

            // --- IP addresses
            .replace(/\b(\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3})\b/g,
                '<span class="log-ip">$1</span>')

            // --- HTTP method + path + status, e.g.  "GET /api/job_targets" 200
            .replace(/"(GET|POST|PUT|PATCH|DELETE|HEAD|OPTIONS)\s+([^"]+)"\s+(\d{3})/g,
                (match, method, path, status) => {
                    const code = parseInt(status, 10);
                    const statusClass =
                        code >= 500 ? 'status-5xx' :
                        code >= 400 ? 'status-4xx' :
                        code >= 300 ? 'status-3xx' :
                        'status-2xx';
                    return `"<span class="http-method">${method}</span> <span class="log-path">${path}</span>" <span class="${statusClass}">${status}</span>`;
                })

            // --- status keywords in message bodies (nas_sync-style)
            .replace(/\b(SUCCESS|OK)\b/g, '<span class="lvl-ok">$1</span>')
            .replace(/\b(STOP|Failed|FAILED)\b/g, '<span class="lvl-error">$1</span>')
            .replace(/\bDEADLINE\b/g, '<span class="lvl-warn">DEADLINE</span>')

            // --- bare file paths not already wrapped (e.g. log/credentials file mentions)
            .replace(/(~?\/[\w.\-\/]+\.\w+)(?![^<]*>)/g,
                '<span class="log-path">$1</span>');

        // Baseline without search <mark> tags, so each search pass starts clean instead of nesting.
        pre._cleanHtml = html;
        pre.innerHTML = html;
    }

    function colorizeLogs(root = document) {
        root.querySelectorAll('pre.log-viewer').forEach(pre => {
            if (pre.dataset.rawContent !== undefined) return;
            renderLogContent(pre, pre.textContent);
        });
    }

    // Render preview previews on initial load (server already injected the last-20-lines text).
    document.querySelectorAll('pre.log-viewer[id^="log-pre-"]').forEach(pre => {
        renderLogContent(pre, pre.dataset.originalContent);
    });

    // Lazy-load full content + auto-scroll to bottom the first time a modal is shown.
    document.addEventListener('shown.bs.modal', (e) => {
        const pre = e.target.querySelector('pre.log-viewer[id^="log-full-"]');
        if (!pre) return;
        if (pre.dataset.loaded === 'true') {
            pre.scrollTop = pre.scrollHeight;
            return;
        }
        fetchLogContent(pre.dataset.logName).then(content => {
            renderLogContent(pre, content);
            pre.dataset.loaded = 'true';
            pre.scrollTop = pre.scrollHeight;
        });
    });

    // Preview tail-length selector
    document.querySelectorAll('.log-tail-select').forEach(function(select) {
        select.addEventListener('change', function() {
            const logId = this.dataset.logId;
            const pre = document.getElementById('log-pre-' + logId);
            if (!pre) return;
            const tail = parseInt(this.value, 10);
            fetchLogContent(pre.dataset.logName, tail).then(content => {
                pre.dataset.originalContent = content;
                renderLogContent(pre, content);
            });
        });
    });

    // Badge filter logic — resolves the target pre from whichever card/modal the badge lives in,
    // and always filters against full file content so matches outside the visible tail aren't missed.
    document.querySelectorAll('.log-filter-badge').forEach(function(badge) {
        badge.addEventListener('click', function() {
            const logId = this.dataset.logId;
            const filter = this.dataset.filter;
            const scope = this.closest('.modal') || this.closest('.card');
            const pre = scope ? scope.querySelector('pre.log-viewer') : null;
            if (!pre) return;

            const isActive = this.classList.contains('log-filter-active');
            scope.querySelectorAll('.log-filter-badge[data-log-id="' + logId + '"]').forEach(function(b) {
                b.classList.remove('log-filter-active');
                b.style.outline = '';
            });

            const isPreview = pre.id.startsWith('log-pre-');

            const applyFilter = (rawText) => {
                const lines = rawText.split('\n');
                let filtered;
                if (filter === 'OTHER') {
                    filtered = lines.filter(l => l && !l.includes('INFO') && !l.includes('WARNING') && !l.includes('ERROR') && !l.includes('DEBUG'));
                } else {
                    filtered = lines.filter(l => l.includes(filter));
                }
                renderLogContent(pre, filtered.length ? filtered.join('\n') : '(no matching lines)');
            };

            if (isActive || filter === 'ALL') {
                if (isPreview) {
                    renderLogContent(pre, pre.dataset.originalContent);
                } else {
                    fetchLogContent(pre.dataset.logName).then(content => renderLogContent(pre, content));
                }
                return;
            }

            this.classList.add('log-filter-active');
            this.style.outline = '2px solid #fff';
            fetchLogContent(pre.dataset.logName).then(applyFilter);
        });
    });

    function purgeLog(logName) {
        if (confirm("Purge all lines from " + logName + "? This cannot be undone.")) {
            fetch('/api/purge_log/' + encodeURIComponent(logName), { method: 'POST' })
            .then(response => response.json())
            .then(data => {
                if (data.success) {
                    alert("Log purged.");
                    location.reload();
                } else {
                    alert("Failed to purge log: " + (data.error || "Unknown error"));
                }
            })
            .catch(error => {
                alert("An error occurred while purging the log.");
            });
        }
    }

    // Search/highlight within the full-view modal, tag-safe so it doesn't break colorization spans.
    function highlightSearch(pre, term) {
        const countLabel = document.querySelector('.log-search-count[data-log-id="' + pre.dataset.searchLogId + '"]');
        const baseHtml = pre._cleanHtml !== undefined ? pre._cleanHtml : pre.innerHTML;

        if (!term) {
            pre.innerHTML = baseHtml;
            if (countLabel) countLabel.textContent = '';
            return 0;
        }

        const segments = baseHtml.split(/(<[^>]+>)/);
        let matchCount = 0;
        const escaped = term.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
        const re = new RegExp('(' + escaped + ')', 'gi');
        for (let i = 0; i < segments.length; i++) {
            if (segments[i].startsWith('<')) continue;
            segments[i] = segments[i].replace(re, (m) => { matchCount++; return '<mark>' + m + '</mark>'; });
        }
        pre.innerHTML = segments.join('');
        if (countLabel) countLabel.textContent = matchCount + ' match' + (matchCount === 1 ? '' : 'es');
        return matchCount;
    }

    let searchDebounce;
    document.querySelectorAll('.log-search-input').forEach(function(input) {
        const logId = input.dataset.logId;
        const pre = document.getElementById('log-full-' + logId);
        if (pre) pre.dataset.searchLogId = logId;
        input.addEventListener('input', function() {
            clearTimeout(searchDebounce);
            searchDebounce = setTimeout(() => {
                highlightSearch(pre, this.value.trim());
                const first = pre.querySelector('mark');
                if (first) first.scrollIntoView({ block: 'center' });
            }, 150);
        });
    });

    function stepSearchMatch(logId, dir) {
        const pre = document.getElementById('log-full-' + logId);
        if (!pre) return;
        const marks = Array.from(pre.querySelectorAll('mark'));
        if (!marks.length) return;
        let idx = marks.findIndex(m => m.classList.contains('log-search-current'));
        marks.forEach(m => m.classList.remove('log-search-current'));
        idx = ((idx === -1 ? 0 : idx + dir) + marks.length) % marks.length;
        marks[idx].classList.add('log-search-current');
        marks[idx].scrollIntoView({ block: 'center' });
    }
    document.querySelectorAll('.log-search-next').forEach(btn => btn.addEventListener('click', () => stepSearchMatch(btn.dataset.logId, 1)));
    document.querySelectorAll('.log-search-prev').forEach(btn => btn.addEventListener('click', () => stepSearchMatch(btn.dataset.logId, -1)));

    // Copy-to-clipboard
    document.querySelectorAll('.log-copy-btn').forEach(function(btn) {
        btn.addEventListener('click', function() {
            const pre = document.getElementById('log-full-' + this.dataset.logId);
            if (!pre) return;
            navigator.clipboard.writeText(pre.dataset.rawContent || pre.textContent).then(() => {
                const original = this.innerHTML;
                this.innerHTML = '<i class="fa-solid fa-check"></i> Copied!';
                setTimeout(() => { this.innerHTML = original; }, 1500);
            });
        });
    });

    // Line-wrap toggle
    document.querySelectorAll('.log-wrap-toggle').forEach(function(btn) {
        btn.addEventListener('click', function() {
            const pre = document.getElementById('log-full-' + this.dataset.logId);
            if (!pre) return;
            pre.classList.toggle('log-nowrap');
        });
    });