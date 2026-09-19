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

let sseEventSource = null;
let sseReconnectTimer = null;

function renderRealtimeMetrics(data) {
    if (!data || data.error) return;

    // 1. Active Serving Model Card
    const modelName = document.getElementById('metric-model-name');
    const modelUpstream = document.getElementById('metric-model-upstream');
    const modelBadge = document.getElementById('metric-model-status-badge');
    const modelProvider = document.getElementById('metric-model-provider');
    const modelKvCache = document.getElementById('metric-model-kv-cache');

    if (modelName) modelName.innerText = data.model || 'qwen3.5-9b';
    if (modelUpstream) {
        const upstream = data.upstream_target || '127.0.0.1:18000';
        const backend = data.backend_type || 'vLLM Engine';
        const nodeStr = data.active_node ? ` @ ${data.active_node}` : '';
        modelUpstream.innerText = `${upstream} (${backend}${nodeStr})`;
    }
    
    const statusText = data.status || 'SERVING';
    if (modelBadge) {
        modelBadge.innerText = statusText;
        if (statusText === 'SERVING') {
            modelBadge.className = 'px-2 py-0.5 rounded-full bg-emerald-50 dark:bg-emerald-950/60 text-emerald-600 dark:text-emerald-400 text-[10px] font-bold font-mono border border-emerald-200 dark:border-emerald-800/40';
        } else if (statusText === 'WARMING_UP') {
            modelBadge.className = 'px-2 py-0.5 rounded-full bg-amber-50 dark:bg-amber-950/60 text-amber-600 dark:text-amber-400 text-[10px] font-bold font-mono border border-amber-200 dark:border-amber-800/40';
        } else {
            modelBadge.className = 'px-2 py-0.5 rounded-full bg-slate-100 dark:bg-slate-800 text-slate-600 dark:text-slate-400 text-[10px] font-bold font-mono border border-slate-200 dark:border-slate-700';
        }
    }

    if (modelKvCache) {
        const kvFree = data.kv_cache_free_pct !== undefined ? Math.round(data.kv_cache_free_pct) : 100;
        const running = data.vllm_running_reqs || 0;
        modelKvCache.innerText = `${kvFree}% free • ${running} active`;
    } else if (modelProvider) {
        const running = data.vllm_running_reqs || 0;
        modelProvider.innerText = `vLLM • ${running} active req`;
    }

    // 2. GPU VRAM & Hardware HUD Card
    const vramUsage = document.getElementById('metric-vram-usage');
    const vramTotal = document.getElementById('metric-vram-total');
    const vramPct = document.getElementById('metric-vram-pct');
    const vramBar = document.getElementById('metric-vram-bar');
    const tempBadge = document.getElementById('metric-gpu-temp-badge');
    const gpuUtil = document.getElementById('metric-gpu-util');
    const gpuPower = document.getElementById('metric-gpu-power');

    const usedGb = (data.vram_used_gb !== undefined && data.vram_used_gb !== null) ? data.vram_used_gb : 0.0;
    const totalGb = (data.vram_total_gb !== undefined && data.vram_total_gb !== null) ? data.vram_total_gb : 16.0;
    const pct = (data.vram_used_pct !== undefined && data.vram_used_pct !== null) ? data.vram_used_pct : Math.round((usedGb / (totalGb || 1)) * 100);

    if (vramUsage) vramUsage.innerText = (typeof usedGb === 'number') ? usedGb.toFixed(1) : usedGb;
    if (vramTotal) vramTotal.innerText = (typeof totalGb === 'number') ? totalGb.toFixed(1) : totalGb;
    if (vramPct) vramPct.innerText = `${pct}%`;
    if (vramBar) vramBar.style.width = `${Math.min(100, Math.max(0, pct))}%`;

    const hudVram = document.getElementById('hud-vram');
    if (hudVram) {
        const usedFormatted = (typeof usedGb === 'number') ? usedGb.toFixed(1) : usedGb;
        const totalFormatted = (typeof totalGb === 'number') ? Math.round(totalGb) : totalGb;
        hudVram.innerText = `${usedFormatted} / ${totalFormatted} GB`;
        hudVram.title = `VRAM: ${usedFormatted} / ${totalGb} GB (${pct}%)`;
    }

    if (tempBadge) {
        tempBadge.innerText = data.gpu_temperature_c ? `${data.gpu_temperature_c}°C` : (data.status || 'ONLINE');
    }
    if (gpuUtil) gpuUtil.innerText = `${data.gpu_utilization_pct !== undefined ? data.gpu_utilization_pct : 0}`;
    if (gpuPower) gpuPower.innerText = (data.gpu_power_w !== null && data.gpu_power_w !== undefined) ? `${Math.round(data.gpu_power_w)}` : '--';

    // 3. Generation Speed & TTFT Card
    const kpiSpeed = document.getElementById('metric-speed');
    const kpiTtft = document.getElementById('metric-ttft');

    if (kpiSpeed && data.current_tok_per_sec !== undefined && data.current_tok_per_sec !== null && data.current_tok_per_sec > 0) {
        kpiSpeed.innerText = `${data.current_tok_per_sec}`;
    }
    if (kpiTtft && data.last_ttft_ms !== undefined && data.last_ttft_ms !== null && data.last_ttft_ms > 0) {
        kpiTtft.innerText = `${data.last_ttft_ms.toFixed(0)} ms`;
    }

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
}

function updateSseStatus(isLive) {
    const sseBadge = document.getElementById('telemetry-sse-status');
    if (!sseBadge) return;
    if (isLive) {
        sseBadge.innerHTML = `<span class="w-1.5 h-1.5 rounded-full bg-emerald-400 animate-ping"></span><span class="text-emerald-400 font-semibold">LIVE (SSE)</span>`;
        sseBadge.className = "inline-flex items-center gap-1.5 px-2 py-0.5 rounded-full bg-emerald-500/10 border border-emerald-500/30 text-[10px] font-mono shadow-sm";
    } else {
        sseBadge.innerHTML = `<span class="w-1.5 h-1.5 rounded-full bg-amber-400"></span><span class="text-amber-400 font-semibold">POLL (3s)</span>`;
        sseBadge.className = "inline-flex items-center gap-1.5 px-2 py-0.5 rounded-full bg-amber-500/10 border border-amber-500/30 text-[10px] font-mono shadow-sm";
    }
}

function initRealtimeSSE() {
    if (typeof EventSource === 'undefined') {
        console.warn('Browser does not support SSE. Falling back to HTTP polling.');
        updateSseStatus(false);
        return;
    }

    if (sseEventSource) {
        sseEventSource.close();
        sseEventSource = null;
    }

    try {
        sseEventSource = new EventSource(`${GATEWAY_BASE}/api/metrics/live-stream`);
        
        sseEventSource.onopen = () => {
            updateSseStatus(true);
        };

        sseEventSource.onmessage = (event) => {
            try {
                const data = JSON.parse(event.data);
                renderRealtimeMetrics(data);
                updateSseStatus(true);
            } catch (err) {
                console.debug('Failed to parse SSE telemetry packet:', err);
            }
        };

        sseEventSource.onerror = () => {
            updateSseStatus(false);
            if (sseEventSource) {
                sseEventSource.close();
                sseEventSource = null;
            }
            if (!sseReconnectTimer) {
                sseReconnectTimer = setTimeout(() => {
                    sseReconnectTimer = null;
                    initRealtimeSSE();
                }, 5000);
            }
        };
    } catch (e) {
        updateSseStatus(false);
    }
}

async function fetchRealtimeMetrics() {
    // Fallback or explicit trigger
    try {
        const res = await fetch(`${GATEWAY_BASE}/api/metrics/realtime`);
        if (!res.ok) return;
        const data = await res.json();
        renderRealtimeMetrics(data);
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
        if (logs.length > 0) {
            const latest = logs[0];
            const hudSpeed = document.getElementById('hud-speed');
            const hudTtft = document.getElementById('hud-ttft');
            const statusPill = document.getElementById('play-status-pill');
            const isInferRunning = abortController !== null;
            if (hudSpeed && !isInferRunning && latest.tok_per_sec) {
                const spd = typeof latest.tok_per_sec === 'number' ? latest.tok_per_sec.toFixed(1) : latest.tok_per_sec;
                hudSpeed.innerText = `${spd} tok/s`;
            }
            if (hudTtft && !isInferRunning && latest.ttft_ms) {
                const ttft = typeof latest.ttft_ms === 'number' ? latest.ttft_ms.toFixed(0) : latest.ttft_ms;
                hudTtft.innerText = `${ttft} ms`;
            }
            if (statusPill && !isInferRunning && latest.tok_per_sec) {
                const spd = typeof latest.tok_per_sec === 'number' ? latest.tok_per_sec.toFixed(1) : latest.tok_per_sec;
                statusPill.innerText = `Latest: ${spd} tok/s`;
                statusPill.className = 'text-[10px] font-mono font-bold px-2 py-0.5 rounded-md bg-neon-500/15 text-neon-500 border border-neon-500/30';
            }
        }
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
