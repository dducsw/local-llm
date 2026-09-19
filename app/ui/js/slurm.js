// ==============================================================================
// SLURM & SSH TUNNEL SUPERVISION
// ==============================================================================

function getActiveHpcUser() {
    return localStorage.getItem('hpc_admin_username') || sessionStorage.getItem('hpc_admin_username') || 'user';
}

async function fetchSlurmNodes() {
    try {
        const res = await fetch(`${GATEWAY_BASE}/api/slurm/nodes`, {
            headers: getAdminHeaders()
        });
        if (!res.ok) return;
        const data = await res.json();
        const tbody = document.getElementById('slurm-nodes-table-body');
        const nodes = data.nodes || [];

        // Update Slurm Top KPI Summary
        const statusText = document.getElementById('slurm-cluster-status-text');
        const statusDot = document.getElementById('slurm-cluster-status-dot');
        const statusSub = document.getElementById('slurm-cluster-status-sub');
        const nodeCount = document.getElementById('slurm-node-count');
        const nodesIdle = document.getElementById('slurm-nodes-idle');
        const nodesMixed = document.getElementById('slurm-nodes-mixed');
        const nodesDrain = document.getElementById('slurm-nodes-drain');
        const gpuCount = document.getElementById('slurm-gpu-count');
        const driverInfo = document.getElementById('slurm-driver-info');

        if (nodes.length > 0) {
            if (statusText) statusText.innerText = 'OPERATIONAL';
            if (statusDot) statusDot.className = 'w-3 h-3 bg-neon-500 rounded-full animate-neon-pulse';
            if (statusSub) statusSub.innerText = `${nodes.length} Nodes Connected`;
            if (nodeCount) nodeCount.innerText = nodes.length;

            let idle = 0, mixed = 0, drain = 0, gpus = 0;
            nodes.forEach(n => {
                const st = (n.state || '').toLowerCase();
                if (st.includes('idle')) idle++;
                else if (st.includes('alloc') || st.includes('mix')) mixed++;
                else if (st.includes('drain') || st.includes('down')) drain++;
                else idle++;

                const gresStr = (n.gres || '');
                if (gresStr.includes('gpu:v100:')) {
                    const match = gresStr.match(/gpu:v100:(\d+)/);
                    if (match) gpus += parseInt(match[1], 10);
                } else if (gresStr.includes('gpu:')) {
                    const match = gresStr.match(/gpu:(\d+)/);
                    if (match) gpus += parseInt(match[1], 10);
                    else gpus += 1;
                }
            });

            if (nodesIdle) nodesIdle.innerText = `${idle} IDLE`;
            if (nodesMixed) nodesMixed.innerText = `${mixed} MIXED`;
            if (nodesDrain) nodesDrain.innerText = `${drain} DRAIN`;
            if (gpuCount) gpuCount.innerText = gpus || 16;
            if (driverInfo) driverInfo.innerText = 'Tesla V100 (SM70)';
        }

        if (!tbody) return;

        if (nodes.length === 0) {
            tbody.innerHTML = `
                <tr>
                    <td colspan="6" class="text-center py-6 text-slate-400 font-medium">
                        No Slurm compute nodes found or cluster unreachable.
                    </td>
                </tr>
            `;
            return;
        }

        tbody.innerHTML = nodes.map(n => {
            let stateBadge = 'bg-slate-100 dark:bg-slate-800 text-slate-600 dark:text-slate-400';
            const st = n.state.toLowerCase();
            if (st.includes('idle')) {
                stateBadge = 'bg-emerald-50 dark:bg-emerald-950/50 text-emerald-600 dark:text-emerald-400 border border-emerald-200 dark:border-emerald-800/40';
            } else if (st.includes('alloc') || st.includes('mix')) {
                stateBadge = 'bg-cyan-50 dark:bg-cyan-950/50 text-cyan-600 dark:text-cyan-400 border border-cyan-200 dark:border-cyan-800/40';
            } else if (st.includes('drain') || st.includes('down')) {
                stateBadge = 'bg-rose-50 dark:bg-rose-950/50 text-rose-600 dark:text-rose-400 border border-rose-200 dark:border-rose-800/40';
            }

            const memNum = parseInt(n.memory, 10);
            const memDisplay = isNaN(memNum) ? (n.memory || '-') : `${Math.round(memNum / 1024)} GB`;

            return `
                <tr class="hover:bg-slate-50/50 dark:hover:bg-[#111827]/40 transition-colors border-b border-slate-100 dark:border-slate-800/60 font-mono text-[11px]">
                    <td class="px-4 py-2.5 font-bold text-slate-900 dark:text-slate-100">${n.node}</td>
                    <td class="px-4 py-2.5">
                        <span class="px-2 py-0.5 rounded-md font-semibold text-[10px] ${stateBadge}">
                            ${n.state}
                        </span>
                    </td>
                    <td class="px-4 py-2.5 text-slate-600 dark:text-slate-300">${n.cpus}</td>
                    <td class="px-4 py-2.5 text-slate-600 dark:text-slate-300 font-semibold">${memDisplay}</td>
                    <td class="px-4 py-2.5 text-neon-600 dark:text-neon-400 font-semibold">${n.gres || '-'}</td>
                    <td class="px-4 py-2.5 text-slate-500">${n.partition}</td>
                </tr>
            `;
        }).join('');
    } catch (err) {
        console.debug('Failed to fetch slurm nodes:', err);
    }
}

let slurmQueueMode = 'all-queue'; // 'all-queue' (GPU Queue squeue) or 'my-jobs' (User Serving Jobs)
let slurmCurrentPartition = 'gpu-queue';
let cachedQueueData = [];
let cachedMyJobsData = [];

function setSlurmQueueMode(mode) {
    slurmQueueMode = mode;
    const tabAll = document.getElementById('queue-tab-all');
    const tabMine = document.getElementById('queue-tab-mine');

    const labelScope = document.getElementById('queue-stat-label-scope');
    const labelTotal = document.getElementById('queue-stat-label-total');
    const labelRunning = document.getElementById('queue-stat-label-running');
    const labelPending = document.getElementById('queue-stat-label-pending');
    const statScope = document.getElementById('queue-stat-partition');
    const statTotal = document.getElementById('queue-stat-total');
    const statRunning = document.getElementById('queue-stat-running');
    const statPending = document.getElementById('queue-stat-pending');

    if (mode === 'all-queue') {
        if (tabAll) tabAll.className = 'px-3.5 py-1.5 rounded-lg bg-neon-500 text-slate-950 font-black transition-all flex items-center gap-1.5 shadow-glow-neon-sm';
        if (tabMine) tabMine.className = 'px-3.5 py-1.5 rounded-lg text-slate-600 dark:text-slate-400 hover:text-slate-900 dark:hover:text-white transition-all flex items-center gap-1.5';

        if (labelScope) labelScope.innerText = 'Partition:';
        if (labelTotal) labelTotal.innerText = 'Total Jobs:';
        if (labelRunning) labelRunning.innerText = 'Running (R):';
        if (labelPending) labelPending.innerText = 'Pending (PD):';
        if (statScope) statScope.innerText = slurmCurrentPartition;
        if (statTotal) statTotal.innerText = cachedQueueData.length;
        if (statRunning) statRunning.innerText = cachedQueueData.filter(j => j.status === 'R').length;
        if (statPending) statPending.innerText = cachedQueueData.filter(j => j.status === 'PD').length;
    } else {
        if (tabAll) tabAll.className = 'px-3.5 py-1.5 rounded-lg text-slate-600 dark:text-slate-400 hover:text-slate-900 dark:hover:text-white transition-all flex items-center gap-1.5';
        if (tabMine) tabMine.className = 'px-3.5 py-1.5 rounded-lg bg-neon-500 text-slate-950 font-black transition-all flex items-center gap-1.5 shadow-glow-neon-sm';

        if (labelScope) labelScope.innerText = 'User Account:';
        if (labelTotal) labelTotal.innerText = 'Serving Jobs:';
        if (labelRunning) labelRunning.innerText = 'Running (R):';
        if (labelPending) labelPending.innerText = 'Pending (PD):';
        if (statScope) statScope.innerText = getActiveHpcUser();
        if (statTotal) statTotal.innerText = cachedMyJobsData.length;
        if (statRunning) statRunning.innerText = cachedMyJobsData.filter(j => (j.status || '').toUpperCase() === 'RUNNING').length;
        if (statPending) statPending.innerText = cachedMyJobsData.filter(j => (j.status || '').toUpperCase() === 'PENDING').length;
    }

    refreshSlurmQueueView();
}

function onSlurmPartitionChange(val) {
    slurmCurrentPartition = val;
    refreshSlurmQueueView();
}

async function refreshSlurmQueueView() {
    if (slurmQueueMode === 'all-queue') {
        await fetchSlurmQueue();
    } else {
        await fetchSlurmJobs();
    }
}

async function fetchSlurmQueue() {
    try {
        const partition = slurmCurrentPartition || 'gpu-queue';
        const res = await fetch(`${GATEWAY_BASE}/api/slurm/queue?partition=${encodeURIComponent(partition)}`, {
            headers: getAdminHeaders()
        });
        if (!res.ok) return;
        const data = await res.json();
        cachedQueueData = data.jobs || [];

        const totalBadge = document.getElementById('queue-total-badge');
        if (totalBadge) totalBadge.innerText = data.total ?? cachedQueueData.length;

        // Update stats bar if in all-queue mode
        if (slurmQueueMode === 'all-queue') {
            const statPart = document.getElementById('queue-stat-partition');
            const statTotal = document.getElementById('queue-stat-total');
            const statRunning = document.getElementById('queue-stat-running');
            const statPending = document.getElementById('queue-stat-pending');

            if (statPart) statPart.innerText = data.partition || partition;
            if (statTotal) statTotal.innerText = data.total ?? cachedQueueData.length;
            if (statRunning) statRunning.innerText = data.running ?? 0;
            if (statPending) statPending.innerText = data.pending ?? 0;
        }

        // Top KPI sync
        const activeCount = document.getElementById('slurm-active-count');
        const activeBadge = document.getElementById('slurm-active-node-badge');
        if (activeCount) activeCount.innerText = data.running ?? 0;
        if (activeBadge) {
            const runningNodes = [...new Set(cachedQueueData.filter(j => j.status === 'R').map(j => j.reason || j.node).filter(n => n && !n.startsWith('(')))];
            if (runningNodes.length > 0) {
                activeBadge.innerText = `Nodes: ${runningNodes.join(', ')}`;
            } else if (cachedQueueData.length > 0) {
                activeBadge.innerText = `Queued: ${cachedQueueData.length} jobs`;
            } else {
                activeBadge.innerText = 'Nodes: Idle';
            }
        }

        if (slurmQueueMode === 'all-queue') {
            renderSlurmCurrentQueue();
        }
    } catch (err) {
        console.debug('Failed to fetch slurm queue:', err);
    }
}

async function fetchSlurmJobs() {
    try {
        // Fetch queue in background too to keep badge updated
        fetchSlurmQueue().catch(() => {});

        const res = await fetch(`${GATEWAY_BASE}/api/slurm/jobs`, {
            headers: getAdminHeaders()
        });
        if (!res.ok) return;
        const data = await res.json();
        const jobs = data.jobs || [];
        cachedMyJobsData = jobs;

        const mineBadge = document.getElementById('queue-mine-badge');
        if (mineBadge) mineBadge.innerText = jobs.length;

        const runningJobs = jobs.filter(j => (j.status || '').toUpperCase() === 'RUNNING');

        if (slurmQueueMode === 'my-jobs') {
            const statTotal = document.getElementById('queue-stat-total');
            const statRunning = document.getElementById('queue-stat-running');
            const statPending = document.getElementById('queue-stat-pending');
            const statScope = document.getElementById('queue-stat-partition');

            if (statScope) statScope.innerText = getActiveHpcUser();
            if (statTotal) statTotal.innerText = jobs.length;
            if (statRunning) statRunning.innerText = runningJobs.length;
            if (statPending) statPending.innerText = jobs.filter(j => (j.status || '').toUpperCase() === 'PENDING').length;

            const activeCount = document.getElementById('slurm-active-count');
            const activeBadge = document.getElementById('slurm-active-node-badge');
            if (activeCount) activeCount.innerText = runningJobs.length;
            if (activeBadge) {
                if (runningJobs.length > 0) {
                    const nodesList = [...new Set(runningJobs.map(j => j.node).filter(Boolean))].join(', ');
                    activeBadge.innerText = `Node: ${nodesList || 'Active'}`;
                } else if (jobs.length > 0) {
                    activeBadge.innerText = `Queued: #${jobs[0].job_id}`;
                } else {
                    activeBadge.innerText = 'Node: --';
                }
            }
            renderSlurmCurrentQueue();
        }
    } catch (err) {
        console.debug('Failed to fetch slurm jobs:', err);
    }
}

function renderSlurmCurrentQueue() {
    const tbody = document.getElementById('slurm-jobs-table-body');
    if (!tbody) return;

    const filterStatus = (document.getElementById('slurm-queue-status-filter')?.value || 'all').toUpperCase();
    const isAllQueue = (slurmQueueMode === 'all-queue');
    const rawList = isAllQueue ? cachedQueueData : cachedMyJobsData;

    let filtered = rawList;
    if (filterStatus !== 'ALL') {
        filtered = rawList.filter(j => {
            const st = (j.status || '').toUpperCase();
            if (filterStatus === 'R') return st === 'R' || st === 'RUNNING';
            if (filterStatus === 'PD') return st === 'PD' || st === 'PENDING';
            return st === filterStatus;
        });
    }

    if (filtered.length === 0) {
        if (isAllQueue) {
            tbody.innerHTML = `
                <tr>
                    <td colspan="9" class="text-center py-12 text-slate-400">
                        <div class="flex flex-col items-center gap-2">
                            <div class="p-3 rounded-2xl bg-slate-100 dark:bg-slate-800/60 text-slate-400">
                                <i data-lucide="layers" class="w-6 h-6 stroke-1"></i>
                            </div>
                            <span class="text-xs font-bold text-slate-700 dark:text-slate-300">No active jobs found in Slurm partition ${slurmCurrentPartition}.</span>
                            <span class="text-[11px] text-slate-500">All compute nodes are currently idle or jobs matching the filter have finished.</span>
                        </div>
                    </td>
                </tr>
            `;
        } else {
            tbody.innerHTML = `
                <tr>
                    <td colspan="9" class="text-center py-12 text-slate-400">
                        <div class="flex flex-col items-center gap-2.5">
                            <div class="p-3 rounded-2xl bg-neon-500/10 text-neon-400 border border-neon-500/20 shadow-glow-neon-sm">
                                <i data-lucide="cpu" class="w-6 h-6"></i>
                            </div>
                            <div class="space-y-0.5">
                                <span class="text-xs font-bold text-slate-900 dark:text-white block">No Active Serving Jobs for ${getActiveHpcUser()}</span>
                                <span class="text-[11px] text-slate-500 block">You currently have no active LLM serving processes running in Slurm.</span>
                            </div>
                            <div class="flex items-center gap-2 pt-1.5">
                                <button onclick="openSubmitJobModal()" class="px-3.5 py-1.5 rounded-xl bg-neon-500 hover:bg-neon-400 text-slate-950 font-black text-xs uppercase flex items-center gap-1.5 shadow-glow-neon-sm transition-all">
                                    <i data-lucide="plus-circle" class="w-3.5 h-3.5"></i>
                                    <span>Launch Serving Job</span>
                                </button>
                                <button onclick="setSlurmQueueMode('all-queue')" class="px-3.5 py-1.5 rounded-xl bg-slate-100 hover:bg-slate-200 dark:bg-[#111827] dark:hover:bg-slate-800 text-slate-700 dark:text-slate-300 font-bold text-xs transition-all">
                                    <span>View All Cluster Jobs</span>
                                </button>
                            </div>
                        </div>
                    </td>
                </tr>
            `;
        }
        if (window.lucide) lucide.createIcons();
        return;
    }

    tbody.innerHTML = filtered.map(j => {
        const rawSt = (j.status || '').toUpperCase();
        let stateBadge = 'bg-slate-100 dark:bg-slate-800 text-slate-600 dark:text-slate-400';
        let stateLabel = rawSt;

        if (rawSt === 'R' || rawSt === 'RUNNING') {
            stateBadge = 'bg-emerald-50 dark:bg-emerald-950/60 text-emerald-600 dark:text-emerald-400 border border-emerald-300 dark:border-emerald-700/60';
            stateLabel = 'RUNNING (R)';
        } else if (rawSt === 'PD' || rawSt === 'PENDING') {
            stateBadge = 'bg-amber-50 dark:bg-amber-950/60 text-amber-600 dark:text-amber-400 border border-amber-300 dark:border-amber-700/60';
            stateLabel = 'PENDING (PD)';
        } else if (rawSt === 'CG' || rawSt === 'COMPLETING') {
            stateBadge = 'bg-cyan-50 dark:bg-cyan-950/60 text-cyan-600 dark:text-cyan-400 border border-cyan-300 dark:border-cyan-700/60';
            stateLabel = 'COMPLETING';
        } else if (rawSt === 'CD' || rawSt === 'COMPLETED') {
            stateBadge = 'bg-slate-100 dark:bg-slate-800 text-slate-500 border border-slate-300 dark:border-slate-700';
            stateLabel = 'COMPLETED';
        } else if (rawSt === 'CA' || rawSt === 'CANCELLED' || rawSt === 'F' || rawSt === 'FAILED') {
            stateBadge = 'bg-rose-50 dark:bg-rose-950/60 text-rose-600 dark:text-rose-400 border border-rose-300 dark:border-rose-700/60';
            stateLabel = 'FAILED/CANCEL';
        }

        const currentUser = getActiveHpcUser().toLowerCase();
        const username = j.user || currentUser;
        const isMe = (username.toLowerCase() === currentUser || username.toLowerCase() === 'user');
        const userBadge = isMe
            ? `<span class="inline-flex items-center gap-1 px-2 py-0.5 rounded-md font-bold text-[10px] bg-neon-500/15 text-neon-400 border border-neon-500/30">
                 <span class="w-1.5 h-1.5 rounded-full bg-neon-500 animate-pulse"></span>${username} (You)
               </span>`
            : `<span class="inline-flex items-center gap-1 px-2 py-0.5 rounded-md font-medium text-[10px] bg-slate-100 dark:bg-slate-800/80 text-slate-700 dark:text-slate-300 border border-slate-200 dark:border-slate-700/50">
                 ${username}
               </span>`;

        // Node / Reason
        const reasonText = j.reason || j.node || '-';
        const isReason = reasonText.startsWith('(') || reasonText.includes('Limit') || reasonText.includes('Priority') || reasonText.includes('Resources');
        const nodeDisplay = isReason
            ? `<span class="text-amber-500 dark:text-amber-400 text-[10px] font-mono">${reasonText}</span>`
            : `<span class="text-slate-700 dark:text-neon-400 font-bold flex items-center gap-1">
                 <i data-lucide="server" class="w-3 h-3 text-neon-500"></i>${reasonText}
               </span>`;

        // Clean Job ID (without array suffixes for log inspection)
        const cleanJobId = (j.job_id || '').split('_')[0];

        return `
            <tr class="hover:bg-slate-50/50 dark:hover:bg-[#111827]/40 transition-colors border-b border-slate-100 dark:border-slate-800/60 font-mono text-[11px]">
                <td class="px-3 py-2.5 font-bold text-slate-900 dark:text-slate-100">#${j.job_id}</td>
                <td class="px-3 py-2.5 text-slate-500">${j.partition || '-'}</td>
                <td class="px-3 py-2.5 text-slate-700 dark:text-slate-200 font-semibold truncate max-w-[140px]" title="${j.name}">${j.name || '-'}</td>
                <td class="px-3 py-2.5">${userBadge}</td>
                <td class="px-3 py-2.5">
                    <span class="px-2 py-0.5 rounded-md font-bold text-[9px] ${stateBadge}">
                        ${stateLabel}
                    </span>
                </td>
                <td class="px-3 py-2.5 text-slate-600 dark:text-slate-300">${j.time || '0:00'}</td>
                <td class="px-3 py-2.5 text-slate-500">${j.nodes || '1'}</td>
                <td class="px-3 py-2.5">${nodeDisplay}</td>
                <td class="px-3 py-2.5 text-right space-x-1.5 whitespace-nowrap">
                    <button onclick="inspectSlurmJobLog('${cleanJobId}')"
                        class="px-2.5 py-1 rounded-lg bg-slate-100 dark:bg-slate-800 hover:bg-slate-200 dark:hover:bg-slate-700 text-slate-700 dark:text-slate-200 font-bold text-[10px] transition-all"
                        title="View job log output">
                        Logs
                    </button>
                    ${isMe ? `
                    <button onclick="cancelSlurmJob('${cleanJobId}')"
                        class="px-2.5 py-1 rounded-lg bg-rose-50 dark:bg-rose-950/40 hover:bg-rose-100 dark:hover:bg-rose-900/60 text-rose-600 dark:text-rose-300 font-bold text-[10px] border border-rose-200 dark:border-rose-800/40 transition-all"
                        title="Cancel job (scancel)">
                        Cancel
                    </button>
                    ` : ''}
                </td>
            </tr>
        `;
    }).join('');

    if (window.lucide) lucide.createIcons();
}

async function fetchTunnelTelemetry() {
    try {
        const res = await fetch(`${GATEWAY_BASE}/api/slurm/tunnel`, {
            headers: getAdminHeaders()
        });
        if (!res.ok) return;
        const data = await res.json();

        const badge = document.getElementById('tunnel-status-badge');
        const info = document.getElementById('tunnel-status-info');
        const targetNodeEl = document.getElementById('tunnel-target-node');
        const upstreamBadge = document.getElementById('tunnel-upstream-badge');
        const latencyBadge = document.getElementById('tunnel-latency-badge');

        if (badge) {
            if (data.alive) {
                if (data.upstream_healthy) {
                    badge.className = 'px-2.5 py-0.5 rounded-full bg-emerald-50 dark:bg-emerald-950/60 border border-emerald-300 dark:border-emerald-700/60 text-emerald-700 dark:text-emerald-300 font-bold text-[10px] flex items-center gap-1.5 animate-pulse';
                    badge.innerHTML = `<span class="w-2 h-2 rounded-full bg-emerald-500"></span> ONLINE & SERVING`;
                } else {
                    badge.className = 'px-2.5 py-0.5 rounded-full bg-cyan-50 dark:bg-cyan-950/60 border border-cyan-300 dark:border-cyan-700/60 text-cyan-700 dark:text-cyan-300 font-bold text-[10px] flex items-center gap-1.5';
                    badge.innerHTML = `<span class="w-2 h-2 rounded-full bg-cyan-400"></span> TUNNEL UP (WARMING UP)`;
                }
            } else {
                badge.className = 'px-2.5 py-0.5 rounded-full bg-slate-100 dark:bg-slate-800/80 border border-slate-200 dark:border-slate-700/60 text-slate-600 dark:text-slate-400 font-bold text-[10px] flex items-center gap-1.5';
                badge.innerHTML = `<span class="w-2 h-2 rounded-full bg-slate-400"></span> DISCONNECTED`;
            }
        }

        if (info) {
            info.innerText = data.route || (data.alive ? `127.0.0.1:${data.local_port} -> ${data.target_node}:${data.remote_port}` : '127.0.0.1:18000 -> Standby');
        }

        if (targetNodeEl) {
            targetNodeEl.innerText = data.target_node ? `${data.target_node} (Job #${data.job_id || '--'})` : 'Auto-negotiated via Slurm';
        }

        if (upstreamBadge) {
            if (data.upstream_healthy) {
                upstreamBadge.className = 'font-bold text-emerald-600 dark:text-emerald-400';
                upstreamBadge.innerText = 'HTTP 200 OK';
            } else if (data.alive) {
                upstreamBadge.className = 'font-bold text-amber-500';
                upstreamBadge.innerText = data.upstream_status || 'Waiting for Model';
            } else {
                upstreamBadge.className = 'font-bold text-slate-500';
                upstreamBadge.innerText = 'Offline';
            }
        }

        if (latencyBadge) {
            latencyBadge.innerText = data.upstream_latency_ms ? `(${data.upstream_latency_ms}ms RTT)` : (data.alive ? `(${data.uptime_seconds}s uptime)` : '--');
        }
    } catch (err) {
        console.debug('Failed to fetch tunnel telemetry:', err);
    }
}

async function restartTunnelAction() {
    try {
        showToast('Cycling and reconnecting SSH tunnel...', 'info');
        const res = await fetch(`${GATEWAY_BASE}/api/slurm/tunnel/restart`, {
            method: 'POST',
            headers: getAdminHeaders()
        });
        const data = await res.json();
        if (res.ok && data.status === 'running') {
            showToast('SSH tunnel reconnected successfully!', 'success');
        } else {
            showToast(data.tunnel?.last_error || 'SSH tunnel reset to standby.', 'info');
        }
        await fetchTunnelTelemetry();
    } catch (err) {
        showToast(`Failed to reconnect tunnel: ${err.message || err}`, 'error');
    }
}

async function probeTunnelHealthAction() {
    try {
        await fetchTunnelTelemetry();
        showToast('Tunnel health telemetry refreshed.', 'success');
    } catch (err) {
        showToast(`Probe failed: ${err.message || err}`, 'error');
    }
}

function updateSlurmScriptPreview() {
    const modelSelect = document.getElementById('submit-job-model');
    const tpInput = document.getElementById('submit-job-tp');
    const codeEl = document.getElementById('submit-job-script-code');
    const descEl = document.getElementById('submit-job-script-desc');
    if (!modelSelect || !codeEl || !descEl) return;

    const val = modelSelect.value || '';
    const tp = parseInt(tpInput?.value, 10) || 1;

    if (val.includes('llama') || val.includes('.gguf')) {
        codeEl.innerText = 'infra/llama-cpp/run_qwen_server.sbatch';
        descEl.innerText = 'llama.cpp CUDA server on V100 GPU with automatic reverse SSH tunnel.';
    } else if (val.includes('1cat') || val.includes('AWQ')) {
        if (tp > 1) {
            codeEl.innerText = 'infra/1cat-vllm/slurm/serving/vllm-1cat-multigpu.sbatch';
            descEl.innerText = `1Cat-vLLM Multi-GPU Tensor Parallelism (TP=${tp}) with FLASH_ATTN_V100 & TurboMind AWQ.`;
        } else {
            codeEl.innerText = 'infra/1cat-vllm/slurm/serving/vllm-1cat-singlegpu.sbatch';
            descEl.innerText = '1Cat-vLLM Single-GPU serving with FLASH_ATTN_V100 & TurboMind AWQ kernels on V100.';
        }
    } else {
        codeEl.innerText = 'infra/vllm/slurm/serving/vllm-singlegpu.sbatch';
        descEl.innerText = 'Standard vLLM Engine with Prefix Caching & Chunked Prefill on NUMA Socket 0.';
    }
}

function openSubmitJobModal() {
    if (typeof isAdmin === 'function' && !isAdmin()) {
        showToast('Administrator privileges required to submit Slurm jobs', 'warning');
        return;
    }
    const modal = document.getElementById('modal-submit-job');
    if (modal) {
        modal.classList.remove('hidden');
        updateSlurmScriptPreview();
    }
}

function closeSubmitJobModal() {
    const modal = document.getElementById('modal-submit-job');
    if (modal) modal.classList.add('hidden');
}

async function submitSlurmJobAction() {
    if (typeof isAdmin === 'function' && !isAdmin()) {
        showToast('Administrator privileges required to submit Slurm jobs', 'warning');
        return;
    }

    const submitBtn = document.querySelector('#modal-submit-job button[onclick="submitSlurmJobAction()"]');
    const originalText = submitBtn ? submitBtn.innerHTML : 'Submit Job';
    const model = document.getElementById('submit-job-model').value;
    const partition = document.getElementById('submit-job-partition').value;
    const gres = document.getElementById('submit-job-gres').value.trim() || 'gpu:1';
    const time_limit = document.getElementById('submit-job-time').value.trim() || '01:00:00';
    const tp = parseInt(document.getElementById('submit-job-tp').value, 10) || 1;

    if (submitBtn) {
        submitBtn.disabled = true;
        submitBtn.innerText = 'Submitting to HPC...';
    }

    try {
        const res = await fetch(`${GATEWAY_BASE}/api/slurm/jobs/submit`, {
            method: 'POST',
            headers: getAdminHeaders({ 'Content-Type': 'application/json' }),
            body: JSON.stringify({ model, partition, gres, time_limit, tp })
        });
        const data = await res.json().catch(() => ({}));
        if (res.ok) {
            showToast(data.message || `Submitted sbatch job ID #${data.job_id}`, 'success');
            closeSubmitJobModal();
            refreshSlurmQueueView();
            fetchSlurmNodes();
        } else if (res.status === 401 || res.status === 403) {
            showToast('Admin session expired or access denied.', 'error');
        } else {
            showToast(data.detail || `Failed to submit sbatch job (HTTP ${res.status})`, 'error');
        }
    } catch (err) {
        showToast(`Submission error: ${err.message || err}`, 'error');
    } finally {
        if (submitBtn) {
            submitBtn.disabled = false;
            submitBtn.innerHTML = originalText;
        }
    }
}

async function cancelSlurmJob(jobId) {
    if (typeof isAdmin === 'function' && !isAdmin()) {
        showToast('Administrator privileges required to cancel Slurm jobs', 'warning');
        return;
    }

    if (!confirm(`Are you sure you want to cancel Slurm job #${jobId}? (scancel ${jobId})`)) {
        return;
    }
    try {
        const res = await fetch(`${GATEWAY_BASE}/api/slurm/jobs/${jobId}/cancel`, {
            method: 'POST',
            headers: getAdminHeaders()
        });
        const data = await res.json();
        if (res.ok) {
            showToast(data.message || `Cancelled Slurm job #${jobId}`, 'info');
            refreshSlurmQueueView();
            fetchSlurmNodes();
        } else {
            showToast(data.detail || 'Failed to cancel job', 'error');
        }
    } catch (err) {
        showToast('Network error cancelling job', 'error');
    }
}

let selectedSlurmJobId = null;
let liveLogEventSource = null;

async function inspectSlurmJobLog(jobId) {
    selectedSlurmJobId = jobId;
    const logTitle = document.getElementById('slurm-log-title');
    const logContent = document.getElementById('slurm-log-terminal');
    if (logTitle) logTitle.innerText = `Live Slurm Job Logs - Job #${jobId}`;
    if (logContent) logContent.innerText = `[Job #${jobId}] Fetching latest log output...`;

    // Smooth scroll down to the log terminal console
    if (logContent) {
        const terminalCard = logContent.closest('.glass-card') || logContent;
        terminalCard.scrollIntoView({ behavior: 'smooth', block: 'center' });
    }

    // Immediately fetch existing log content via REST API
    refreshSlurmLogs(false);

    // Automatically initiate live streaming on select
    startLiveLogStream(jobId);
}

function startLiveLogStream(jobId) {
    const id = jobId || selectedSlurmJobId;
    if (!id) {
        showToast('Please select an active Slurm job first', 'warning');
        return;
    }
    selectedSlurmJobId = id;
    stopLiveLogStream(false);

    const logContent = document.getElementById('slurm-log-terminal');
    const badge = document.getElementById('slurm-log-stream-badge');
    const dot = document.getElementById('slurm-log-live-dot');
    const btnText = document.getElementById('btn-stream-logs-text');
    const btn = document.getElementById('btn-toggle-stream-logs');

    if (badge) {
        badge.innerText = '● LIVE (SSE)';
        badge.className = 'px-2 py-0.5 rounded-full bg-emerald-50 dark:bg-emerald-950/60 text-emerald-600 dark:text-emerald-400 text-[10px] font-mono font-bold border border-emerald-200 dark:border-emerald-800/40 shadow-sm animate-pulse';
    }
    if (dot) dot.className = 'w-2.5 h-2.5 rounded-full bg-emerald-500 animate-neon-pulse';
    if (btnText) btnText.innerText = 'Pause Stream';
    if (btn) btn.className = 'px-3 py-1.5 rounded-lg bg-amber-400 hover:bg-amber-300 text-slate-950 font-black text-xs uppercase flex items-center gap-1.5 transition-all shadow-sm';

    try {
        const session = localStorage.getItem('hpc_admin_session') || sessionStorage.getItem('hpc_admin_session') || (typeof adminToken !== 'undefined' ? adminToken : '') || '';
        const tokenQuery = session ? `?token=${encodeURIComponent(session)}` : '';
        liveLogEventSource = new EventSource(`${GATEWAY_BASE}/api/slurm/logs/${id}/stream${tokenQuery}`);

        liveLogEventSource.onmessage = function (event) {
            if (!event.data) return;
            try {
                const data = JSON.parse(event.data);
                const text = data.log || data.stdout || data.stderr;
                if (text && logContent) {
                    logContent.innerText = text;
                    const autoscroll = document.getElementById('slurm-log-autoscroll');
                    if (autoscroll && autoscroll.checked) {
                        logContent.scrollTop = logContent.scrollHeight;
                    }
                }
            } catch (e) {}
        };

        liveLogEventSource.onerror = function () {
            if (badge) {
                badge.innerText = 'RECONNECTING';
                badge.className = 'px-2 py-0.5 rounded-full bg-amber-50 dark:bg-amber-950/50 text-amber-600 dark:text-amber-400 text-[10px] font-mono font-bold border border-amber-200';
            }
            // Fallback: refresh once via normal authenticated fetch
            refreshSlurmLogs(false);
        };
    } catch (err) {
        showToast('Failed to connect SSE stream', 'error');
        stopLiveLogStream(true);
    }
}

function stopLiveLogStream(showNotice = true) {
    if (liveLogEventSource) {
        liveLogEventSource.close();
        liveLogEventSource = null;
    }

    const badge = document.getElementById('slurm-log-stream-badge');
    const dot = document.getElementById('slurm-log-live-dot');
    const btnText = document.getElementById('btn-stream-logs-text');
    const btn = document.getElementById('btn-toggle-stream-logs');

    if (badge) {
        badge.innerText = 'PAUSED';
        badge.className = 'px-2 py-0.5 rounded-full bg-slate-100 dark:bg-slate-800 text-[10px] font-mono font-bold text-slate-600 dark:text-slate-400 border border-slate-200 dark:border-slate-700';
    }
    if (dot) dot.className = 'w-2.5 h-2.5 rounded-full bg-slate-400';
    if (btnText) btnText.innerText = 'Start Live Stream';
    if (btn) btn.className = 'px-3 py-1.5 rounded-lg bg-neon-500 text-slate-950 hover:bg-neon-400 font-black text-xs uppercase flex items-center gap-1.5 transition-all shadow-sm';

    if (showNotice) showToast('Live stream paused', 'info');
}

function toggleLiveLogStream() {
    if (liveLogEventSource) {
        stopLiveLogStream(true);
    } else {
        startLiveLogStream();
    }
}

function clearSlurmLogTerminal() {
    const logContent = document.getElementById('slurm-log-terminal');
    if (logContent) {
        logContent.innerText = '[Log Cleared] Waiting for new data...';
    }
    showToast('Log viewer cleared', 'info');
}

async function refreshSlurmLogs(showToastMsg = true) {
    const logContent = document.getElementById('slurm-log-terminal');
    if (!logContent) return;

    if (!selectedSlurmJobId) {
        const jobsRes = await fetch(`${GATEWAY_BASE}/api/slurm/jobs`, {
            headers: getAdminHeaders()
        });
        const jobsData = await jobsRes.json().catch(() => ({}));
        selectedSlurmJobId = jobsData.jobs?.[0]?.job_id || null;
    }
    if (!selectedSlurmJobId) {
        logContent.innerText = 'No Slurm job selected or available.';
        return;
    }

    try {
        const res = await fetch(`${GATEWAY_BASE}/api/slurm/logs/${selectedSlurmJobId}`, {
            headers: getAdminHeaders()
        });
        const data = await res.json();
        const text = data.log || (data.stdout && data.stderr ? `=== STDOUT ===\n${data.stdout}\n\n=== STDERR ===\n${data.stderr}` : (data.stdout || data.stderr || ''));
        logContent.innerText = text || '(no output received yet)';
        const autoscroll = document.getElementById('slurm-log-autoscroll');
        if (autoscroll && autoscroll.checked) {
            logContent.scrollTop = logContent.scrollHeight;
        }
        if (showToastMsg) showToast('Logs refreshed', 'info');
    } catch (err) {
        logContent.innerText = 'Failed to load log file from server.';
    }
}

function closeJobLogModal() {
    stopLiveLogStream(false);
    const modal = document.getElementById('modal-job-logs');
    if (modal) modal.classList.add('hidden');
}
