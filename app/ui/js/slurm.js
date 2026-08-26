// ==============================================================================
// SLURM & SSH TUNNEL SUPERVISION
// ==============================================================================

async function fetchSlurmNodes() {
    try {
        const res = await fetch(`${GATEWAY_BASE}/api/slurm/nodes`);
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

async function fetchSlurmJobs() {
    try {
        const res = await fetch(`${GATEWAY_BASE}/api/slurm/jobs`);
        if (!res.ok) return;
        const data = await res.json();
        const tbody = document.getElementById('slurm-jobs-table-body');
        const jobs = data.jobs || [];

        // Update Active Jobs Top KPI
        const activeCount = document.getElementById('slurm-active-count');
        const activeBadge = document.getElementById('slurm-active-node-badge');

        const runningJobs = jobs.filter(j => j.status.toUpperCase() === 'RUNNING');
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

        if (!tbody) return;

        if (jobs.length === 0) {
            tbody.innerHTML = `
                <tr>
                    <td colspan="8" class="text-center py-6 text-slate-400 font-medium">
                        No active jobs running in Slurm partition.
                    </td>
                </tr>
            `;
            return;
        }

        tbody.innerHTML = jobs.map(j => {
            let statusBadge = 'bg-slate-100 dark:bg-slate-800 text-slate-600 dark:text-slate-400';
            const st = j.status.toUpperCase();
            if (st === 'RUNNING') {
                statusBadge = 'bg-emerald-50 dark:bg-emerald-950/50 text-emerald-600 dark:text-emerald-400 border border-emerald-200 dark:border-emerald-800/40 animate-pulse';
            } else if (st === 'PENDING') {
                statusBadge = 'bg-amber-50 dark:bg-amber-950/50 text-amber-600 dark:text-amber-400 border border-amber-200 dark:border-amber-800/40';
            } else if (st === 'CANCELLED' || st === 'FAILED') {
                statusBadge = 'bg-rose-50 dark:bg-rose-950/50 text-rose-600 dark:text-rose-400 border border-rose-200 dark:border-rose-800/40';
            }

            return `
                <tr class="hover:bg-slate-50/50 dark:hover:bg-[#111827]/40 transition-colors border-b border-slate-100 dark:border-slate-800/60 font-mono text-[11px]">
                    <td class="px-4 py-2.5 font-bold text-slate-900 dark:text-slate-100">#${j.job_id}</td>
                    <td class="px-4 py-2.5 text-slate-700 dark:text-slate-200 font-semibold">${j.name}</td>
                    <td class="px-4 py-2.5 text-slate-500">${j.partition}</td>
                    <td class="px-4 py-2.5 text-neon-600 dark:text-neon-400 font-semibold">${j.node}</td>
                    <td class="px-4 py-2.5 text-slate-500">${j.gres || '-'}</td>
                    <td class="px-4 py-2.5 text-slate-600 dark:text-slate-300">${j.time}</td>
                    <td class="px-4 py-2.5">
                        <span class="px-2 py-0.5 rounded-md font-semibold text-[10px] ${statusBadge}">
                            ${j.status}
                        </span>
                    </td>
                    <td class="px-4 py-2.5 text-right space-x-1.5">
                        <button onclick="inspectSlurmJobLog('${j.job_id}')"
                            class="px-2 py-1 rounded bg-slate-100 dark:bg-slate-800 hover:bg-slate-200 dark:hover:bg-slate-700 text-slate-700 dark:text-slate-200 font-bold transition-all"
                            title="Inspect Log Output">
                            Logs
                        </button>
                        <button onclick="cancelSlurmJob('${j.job_id}')"
                            class="px-2 py-1 rounded bg-rose-50 dark:bg-rose-950/40 hover:bg-rose-100 dark:hover:bg-rose-900/60 text-rose-600 dark:text-rose-300 font-bold border border-rose-200 dark:border-rose-800/40 transition-all"
                            title="Cancel Job">
                            Cancel
                        </button>
                    </td>
                </tr>
            `;
        }).join('');
    } catch (err) {
        console.debug('Failed to fetch slurm jobs:', err);
    }
}

async function fetchTunnelTelemetry() {
    try {
        const res = await fetch(`${GATEWAY_BASE}/api/slurm/tunnel`);
        if (!res.ok) return;
        const data = await res.json();

        const badge = document.getElementById('tunnel-status-badge');
        const info = document.getElementById('tunnel-status-info');

        if (badge) {
            if (data.alive) {
                badge.className = 'px-2.5 py-1 rounded-lg bg-emerald-50 dark:bg-emerald-950/60 border border-emerald-300 dark:border-emerald-700/60 text-emerald-700 dark:text-emerald-300 font-bold text-xs flex items-center gap-1.5 animate-pulse';
                badge.innerHTML = `<span class="w-2 h-2 rounded-full bg-emerald-500"></span> ACTIVE`;
            } else {
                badge.className = 'px-2.5 py-1 rounded-lg bg-slate-100 dark:bg-slate-800/80 border border-slate-200 dark:border-slate-700/60 text-slate-600 dark:text-slate-400 font-bold text-xs flex items-center gap-1.5';
                badge.innerHTML = `<span class="w-2 h-2 rounded-full bg-slate-400"></span> DISCONNECTED`;
            }
        }

        if (info) {
            if (data.alive) {
                info.innerText = `127.0.0.1:${data.local_port} -> ${data.target_node}:${data.remote_port} (${data.uptime_seconds}s)`;
            } else {
                info.innerText = data.last_error ? `Error: ${data.last_error}` : 'Waiting for active Slurm job...';
            }
        }
    } catch (err) {
        console.debug('Failed to fetch tunnel telemetry:', err);
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
            fetchSlurmJobs();
            fetchSlurmNodes();
        } else if (res.status === 401 || res.status === 403) {
            showToast('Admin session expired. Please sign in again.', 'error');
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
            fetchSlurmJobs();
            fetchSlurmNodes();
        } else {
            showToast(data.detail || 'Failed to cancel job', 'error');
        }
    } catch (err) {
        showToast('Network error cancelling job', 'error');
    }
}

let selectedSlurmJobId = null;

async function inspectSlurmJobLog(jobId) {
    selectedSlurmJobId = jobId;
    const logTitle = document.getElementById('slurm-log-title');
    const logContent = document.getElementById('slurm-log-terminal');
    if (logTitle) logTitle.innerText = `Live Slurm Job Logs - Job #${jobId}`;
    if (logContent) logContent.innerText = 'Fetching stdout / stderr from HPC cluster...';
    await refreshSlurmLogs();
}

async function refreshSlurmLogs() {
    const logContent = document.getElementById('slurm-log-terminal');
    if (!logContent) return;

    if (!selectedSlurmJobId) {
        const jobsRes = await fetch(`${GATEWAY_BASE}/api/slurm/jobs`);
        const jobsData = await jobsRes.json().catch(() => ({}));
        selectedSlurmJobId = jobsData.jobs?.[0]?.job_id || null;
    }
    if (!selectedSlurmJobId) {
        logContent.innerText = 'No Slurm job selected or available.';
        return;
    }

    try {
        const res = await fetch(`${GATEWAY_BASE}/api/slurm/logs/${selectedSlurmJobId}`);
        const data = await res.json();
        const stdout = data.stdout || data.log || '';
        const stderr = data.stderr || '';
        logContent.innerText = `[stdout]\n${stdout || '(empty)'}\n\n[stderr]\n${stderr || '(empty)'}`;
        logContent.scrollTop = logContent.scrollHeight;
    } catch (err) {
        logContent.innerText = 'Failed to load log file from server.';
    }
}

function closeJobLogModal() {
    const modal = document.getElementById('modal-job-logs');
    if (modal) modal.classList.add('hidden');
}
