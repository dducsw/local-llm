// ==============================================================================
// REALTIME TELEMETRY & ANALYTICS
// ==============================================================================

let throughputChart = null;

function initThroughputChart() {
    const ctx = document.getElementById('throughput-chart');
    if (!ctx) return;

    const isDark = document.documentElement.classList.contains('dark');
    const gridColor = isDark ? 'rgba(255, 255, 255, 0.05)' : 'rgba(0, 0, 0, 0.05)';
    const textColor = isDark ? '#94a3b8' : '#64748b';

    throughputChart = new Chart(ctx, {
        type: 'line',
        data: {
            labels: [],
            datasets: [
                {
                    label: 'Tokens / min',
                    data: [],
                    borderColor: '#00ff88',
                    backgroundColor: isDark ? 'rgba(0, 255, 136, 0.12)' : 'rgba(0, 230, 118, 0.15)',
                    borderWidth: 2.5,
                    fill: true,
                    tension: 0.35,
                    pointRadius: 3,
                    pointHoverRadius: 6,
                    pointBackgroundColor: '#00ff88',
                    yAxisID: 'y'
                },
                {
                    label: 'Cumulative Tokens',
                    data: [],
                    borderColor: '#38bdf8',
                    backgroundColor: 'transparent',
                    borderWidth: 1.8,
                    borderDash: [4, 4],
                    pointRadius: 2,
                    yAxisID: 'y1'
                }
            ]
        },
        options: {
            responsive: true,
            maintainAspectRatio: false,
            interaction: {
                mode: 'index',
                intersect: false,
            },
            plugins: {
                legend: {
                    position: 'top',
                    labels: {
                        color: textColor,
                        font: { family: 'Plus Jakarta Sans', size: 11, weight: '600' },
                        usePointStyle: true,
                        boxWidth: 8
                    }
                },
                tooltip: {
                    backgroundColor: isDark ? '#0a0f18' : '#ffffff',
                    titleColor: isDark ? '#f8fafc' : '#0f172a',
                    bodyColor: isDark ? '#cbd5e1' : '#334155',
                    borderColor: isDark ? '#1a2436' : '#e2e8f0',
                    borderWidth: 1,
                    padding: 10,
                    bodyFont: { family: 'JetBrains Mono', size: 11 },
                    titleFont: { family: 'Plus Jakarta Sans', size: 12, weight: '700' }
                }
            },
            scales: {
                x: {
                    grid: { color: gridColor },
                    ticks: { color: textColor, font: { family: 'JetBrains Mono', size: 10 } }
                },
                y: {
                    type: 'linear',
                    display: true,
                    position: 'left',
                    grid: { color: gridColor },
                    ticks: { color: textColor, font: { family: 'JetBrains Mono', size: 10 } },
                    title: { display: true, text: 'Tokens/min', color: textColor, font: { size: 10 } }
                },
                y1: {
                    type: 'linear',
                    display: true,
                    position: 'right',
                    grid: { drawOnChartArea: false },
                    ticks: { color: '#38bdf8', font: { family: 'JetBrains Mono', size: 10 } },
                    title: { display: true, text: 'Tok/s', color: '#38bdf8', font: { size: 10 } }
                }
            }
        }
    });
}

function updateChartColors() {
    if (!throughputChart) return;
    const isDark = document.documentElement.classList.contains('dark');
    const gridColor = isDark ? 'rgba(255, 255, 255, 0.05)' : 'rgba(0, 0, 0, 0.05)';
    const textColor = isDark ? '#94a3b8' : '#64748b';

    throughputChart.options.plugins.legend.labels.color = textColor;
    throughputChart.options.plugins.tooltip.backgroundColor = isDark ? '#0a0f18' : '#ffffff';
    throughputChart.options.plugins.tooltip.titleColor = isDark ? '#f8fafc' : '#0f172a';
    throughputChart.options.plugins.tooltip.bodyColor = isDark ? '#cbd5e1' : '#334155';
    throughputChart.options.plugins.tooltip.borderColor = isDark ? '#1a2436' : '#e2e8f0';

    throughputChart.options.scales.x.grid.color = gridColor;
    throughputChart.options.scales.x.ticks.color = textColor;
    throughputChart.options.scales.y.grid.color = gridColor;
    throughputChart.options.scales.y.ticks.color = textColor;
    throughputChart.options.scales.y.title.color = textColor;

    throughputChart.update();
}

async function fetchRealtimeMetrics() {
    try {
        const res = await fetch(`${GATEWAY_BASE}/api/metrics/realtime`);
        if (!res.ok) return;
        const data = await res.json();

        // 1. Active Serving Model Card
        const modelName = document.getElementById('metric-model-name');
        const modelUpstream = document.getElementById('metric-model-upstream');
        const modelBadge = document.getElementById('metric-model-status-badge');
        const modelProvider = document.getElementById('metric-model-provider');

        if (modelName) modelName.innerText = data.model || 'qwen3.5-9b';
        if (modelUpstream) modelUpstream.innerText = '127.0.0.1:18000 (vLLM Engine)';
        if (modelBadge) {
            modelBadge.innerText = 'SERVING';
            modelBadge.className = 'px-2 py-0.5 rounded-full bg-emerald-50 dark:bg-emerald-950/60 text-emerald-600 dark:text-emerald-400 text-[10px] font-bold font-mono border border-emerald-200 dark:border-emerald-800/40';
        }
        if (modelProvider) modelProvider.innerText = 'vLLM • QOS gpu-q';

        // 2. VRAM & Node Allocation Card
        const vramUsage = document.getElementById('metric-vram-usage');
        const vramSub = document.getElementById('metric-vram-sub');
        const nodeStatus = document.getElementById('metric-node-status');

        if (vramUsage) vramUsage.innerText = `${data.nodes_count || 4}`;
        if (vramSub) vramSub.innerText = 'nodes in cluster';
        if (nodeStatus) nodeStatus.innerText = 'ONLINE (OPERATIONAL)';

        // 3. Generation Speed & TTFT Card
        const kpiSpeed = document.getElementById('metric-speed');
        const kpiTtft = document.getElementById('metric-ttft');

        if (kpiSpeed) kpiSpeed.innerText = `${data.current_tok_per_sec || 0.0}`;
        if (kpiTtft) kpiTtft.innerText = `${data.last_ttft_ms ? data.last_ttft_ms.toFixed(0) : '0'} ms`;

        // 4. Gateway Requests & Total Tokens Card
        const kpiRequests = document.getElementById('metric-total-requests');
        const kpiTokens = document.getElementById('metric-total-tokens');

        if (kpiRequests) kpiRequests.innerText = (data.total_requests || 0).toLocaleString();
        if (kpiTokens) kpiTokens.innerText = (data.total_tokens || 0).toLocaleString();

        const promptTokens = document.getElementById('stat-prompt-tokens');
        const completionTokens = document.getElementById('stat-completion-tokens');
        const totalTokens = document.getElementById('stat-total-tokens');
        const speedLabel = document.getElementById('stat-speed-label');
        const speedBar = document.getElementById('stat-speed-bar');
        if (promptTokens) promptTokens.innerText = (data.total_prompt_tokens || 0).toLocaleString();
        if (completionTokens) completionTokens.innerText = (data.total_completion_tokens || 0).toLocaleString();
        if (totalTokens) totalTokens.innerText = (data.total_tokens || 0).toLocaleString();
        if (speedLabel) speedLabel.innerText = `${data.current_tok_per_sec || 0.0} tok/s`;
        if (speedBar) speedBar.style.width = `${Math.min((data.current_tok_per_sec || 0) / 50 * 100, 100)}%`;
    } catch (err) {
        console.debug('Failed to fetch realtime metrics:', err);
    }
}

async function fetchTimeseriesMetrics() {
    try {
        if (!throughputChart) {
            initThroughputChart();
        }

        const res = await fetch(`${GATEWAY_BASE}/api/metrics/timeseries`);
        if (!res.ok) return;
        const data = await res.json();

        if (throughputChart) {
            throughputChart.data.labels = data.labels || [];
            throughputChart.data.datasets[0].data = data.tokens_per_minute || [];
            throughputChart.data.datasets[1].data = data.cumulative_tokens || [];
            throughputChart.update('none');
        }
    } catch (err) {
        console.debug('Failed to fetch timeseries metrics:', err);
    }
}

async function fetchMetricsLogs() {
    try {
        const res = await fetch(`${GATEWAY_BASE}/api/metrics/logs?limit=30`);
        if (!res.ok) return;
        const data = await res.json();
        const tbody = document.getElementById('audit-logs-table-body');
        if (!tbody) return;

        const logs = data.logs || [];
        if (logs.length === 0) {
            tbody.innerHTML = `
                <tr>
                    <td colspan="7" class="text-center py-6 text-slate-400 font-medium">
                        No inference requests recorded yet.
                    </td>
                </tr>
            `;
            return;
        }

        tbody.innerHTML = logs.map(l => `
            <tr class="hover:bg-slate-50/50 dark:hover:bg-[#111827]/40 transition-colors border-b border-slate-100 dark:border-slate-800/60 font-mono text-[11px]">
                <td class="px-4 py-2.5 text-slate-400">${l.time}</td>
                <td class="px-4 py-2.5 text-slate-800 dark:text-slate-200 font-semibold">${l.id}</td>
                <td class="px-4 py-2.5 text-neon-600 dark:text-neon-400">${l.model}</td>
                <td class="px-4 py-2.5 text-slate-600 dark:text-slate-300 font-bold">${l.tokens}</td>
                <td class="px-4 py-2.5 text-slate-600 dark:text-slate-300">${l.latency_ms ? l.latency_ms.toFixed(0) + ' ms' : '-'}</td>
                <td class="px-4 py-2.5 text-slate-600 dark:text-slate-300">${l.tok_per_sec ? l.tok_per_sec.toFixed(1) + ' t/s' : '-'}</td>
                <td class="px-4 py-2.5">
                    <span class="px-2 py-0.5 rounded-md font-semibold text-[10px] ${l.status.includes('OK') ? 'bg-emerald-50 dark:bg-emerald-950/50 text-emerald-600 dark:text-emerald-400 border border-emerald-200 dark:border-emerald-800/40' : 'bg-rose-50 dark:bg-rose-950/50 text-rose-600 dark:text-rose-400 border border-rose-200 dark:border-rose-800/40'}">
                        ${l.status}
                    </span>
                </td>
            </tr>
        `).join('');
    } catch (err) {
        console.debug('Failed to fetch audit logs:', err);
    }
}
