// ==============================================================================
// INFERENCE PLAYGROUND & CHATBOT STUDIO
// ==============================================================================

let currentSelectedModel = '';
let abortController = null;
let chatAbortController = null;
let conversationHistory = [];
let totalRequests = 0;
let totalTokens = 0;
let ledger = [];
let activeFilter = 'all';

// Preset System Instructions Dictionary
const SYSTEM_PROMPT_PRESETS = {
    general: "You are a helpful, concise, and technically accurate AI assistant running locally on your HPC cluster via AI Local Gateway.",
    coder: "You are a senior AI software engineer and Python/CUDA specialist. Provide clean, well-structured, production-ready code with concise technical explanations and optimal time/space complexity.",
    hpc: "You are an HPC Systems and Slurm Workload Manager specialist. Assist with writing robust sbatch scripts, Apptainer/Singularity container execution, multi-GPU parallelism, and Tesla V100 GPU tuning.",
    vi: "Bạn là một trợ lý AI thông minh, hỗ trợ bằng tiếng Việt chuẩn xác, lưu loát và chuyên nghiệp cho các tác vụ kỹ thuật, lập trình và xử lý ngôn ngữ tự nhiên.",
    latex: "You are an academic researcher and LaTeX formatting expert. Provide rigorous mathematical formulations, clean LaTeX equations, and structured research summaries."
};

function applySystemPromptPreset(presetKey) {
    const promptInput = document.getElementById('chat-system-prompt');
    if (promptInput && SYSTEM_PROMPT_PRESETS[presetKey]) {
        promptInput.value = SYSTEM_PROMPT_PRESETS[presetKey];
        updateContextWindowMeter();
        showToast(`Loaded preset: ${presetKey.toUpperCase()}`, 'info');
    }
}

function updateChatSettings() {
    try {
        const settings = {
            temp: parseFloat(document.getElementById('chat-temp')?.value) || 0.7,
            top_p: parseFloat(document.getElementById('chat-topp')?.value) || 0.9,
            max_tokens: parseInt(document.getElementById('chat-tokens')?.value, 10) || 2048,
            presence: parseFloat(document.getElementById('chat-presence')?.value) || 0.0,
            frequency: parseFloat(document.getElementById('chat-frequency')?.value) || 0.0,
        };
        localStorage.setItem('hpc_chat_settings', JSON.stringify(settings));
    } catch (e) {}
}

function loadChatSettings() {
    try {
        const saved = localStorage.getItem('hpc_chat_settings');
        if (!saved) return;
        const s = JSON.parse(saved);
        const t = document.getElementById('chat-temp');
        const tp = document.getElementById('chat-topp');
        const tok = document.getElementById('chat-tokens');
        const pr = document.getElementById('chat-presence');
        const fr = document.getElementById('chat-frequency');

        if (t && s.temp !== undefined) { t.value = s.temp; document.getElementById('chat-val-temp').innerText = parseFloat(s.temp).toFixed(2); }
        if (tp && s.top_p !== undefined) { tp.value = s.top_p; document.getElementById('chat-val-topp').innerText = parseFloat(s.top_p).toFixed(2); }
        if (tok && s.max_tokens !== undefined) { tok.value = s.max_tokens; document.getElementById('chat-val-tokens').innerText = s.max_tokens; }
        if (pr && s.presence !== undefined) { pr.value = s.presence; document.getElementById('chat-val-presence').innerText = parseFloat(s.presence).toFixed(2); }
        if (fr && s.frequency !== undefined) { fr.value = s.frequency; document.getElementById('chat-val-frequency').innerText = parseFloat(s.frequency).toFixed(2); }
    } catch (e) {}
}

// Token Estimation Engine (Accurate Fast Approximation)
function estimateTokenCount(text) {
    if (!text) return 0;
    const str = String(text);
    // Count CJK & Vietnamese complex characters (often 1-2 tokens per char)
    const nonAsciiCount = (str.match(/[^\x00-\x7F]/g) || []).length;
    // Latin words & symbols (~4 chars per token)
    const asciiChars = str.length - nonAsciiCount;
    return Math.max(1, Math.ceil(asciiChars / 3.8 + nonAsciiCount * 1.2));
}

function updateContextWindowMeter() {
    const maxContext = 32768; // Standard context limit for Qwen 3.5
    const sysPrompt = document.getElementById('chat-system-prompt')?.value || '';
    const userInput = document.getElementById('chat-user-input')?.value || '';

    let totalChars = sysPrompt.length;
    conversationHistory.forEach(m => totalChars += (m.content || '').length);
    const historyTokens = estimateTokenCount(sysPrompt) + conversationHistory.reduce((acc, m) => acc + estimateTokenCount(m.content), 0);
    const inputTokens = estimateTokenCount(userInput);
    const totalEstTokens = historyTokens + (userInput ? inputTokens : 0);

    const pct = Math.min(100, Math.max(0.1, (totalEstTokens / maxContext) * 100));
    const pctStr = pct.toFixed(1) + '%';

    const pctEl = document.getElementById('chat-context-pct');
    const barEl = document.getElementById('chat-context-bar');
    const usedEl = document.getElementById('chat-context-used');
    const maxEl = document.getElementById('chat-context-max');
    const headerTokens = document.getElementById('chat-header-tokens-counter');
    const inputLiveTokens = document.getElementById('chat-input-live-tokens');

    if (pctEl) pctEl.innerText = pctStr;
    if (usedEl) usedEl.innerText = `${totalEstTokens.toLocaleString()} tokens`;
    if (maxEl) maxEl.innerText = `${maxContext.toLocaleString()} max`;
    if (headerTokens) headerTokens.innerText = `~${totalEstTokens.toLocaleString()} tok (${pctStr})`;
    if (inputLiveTokens) inputLiveTokens.innerText = `Input: ~${inputTokens} tok • Total: ~${totalEstTokens} tok`;

    if (barEl) {
        barEl.style.width = `${pct}%`;
        if (pct > 80) {
            barEl.className = 'bg-gradient-to-r from-rose-500 to-rose-600 h-full rounded-full transition-all duration-300';
        } else if (pct > 50) {
            barEl.className = 'bg-gradient-to-r from-amber-400 to-amber-500 h-full rounded-full transition-all duration-300';
        } else {
            barEl.className = 'bg-gradient-to-r from-neon-500 to-emerald-400 h-full rounded-full transition-all duration-300';
        }
    }
}

function onChatInputChanged() {
    updateContextWindowMeter();
}

async function fetchAvailableModels() {
    try {
        const res = await fetch(`${GATEWAY_BASE}/v1/models`, {
            headers: getAdminHeaders({ 'Authorization': `Bearer ${activeApiKey}` })
        });
        if (!res.ok) return;
        const data = await res.json();
        const models = data.data || [];

        const playSelect = document.getElementById('play-model-select');
        const chatSelect = document.getElementById('chat-model-select');
        const pageKeySelect = document.getElementById('page-key-model');
        const globalLabel = document.getElementById('global-model-selected-label');
        const metricModelName = document.getElementById('metric-model-name');
        const globalCount = document.getElementById('model-dropdown-count');
        const globalList = document.getElementById('global-model-items-list');

        if (models.length > 0) {
            currentSelectedModel = currentSelectedModel || models[0].id;
            if (globalLabel) globalLabel.innerText = currentSelectedModel;
            if (metricModelName) metricModelName.innerText = currentSelectedModel;
            if (globalCount) globalCount.innerText = models.length;

            if (playSelect) {
                playSelect.innerHTML = models.map(m => `
                    <option value="${m.id}" ${m.id === currentSelectedModel ? 'selected' : ''}>${m.id} (${(m.status || 'READY').toUpperCase()})</option>
                `).join('');
            }

            if (chatSelect) {
                chatSelect.innerHTML = models.map(m => `
                    <option value="${m.id}" ${m.id === currentSelectedModel ? 'selected' : ''}>${m.id}</option>
                `).join('');
                chatSelect.value = currentSelectedModel;
            }

            updateChatModelDisplay(currentSelectedModel);

            if (pageKeySelect) {
                pageKeySelect.innerHTML = `<option value="*">All Models (*)</option>` + models.map(m => `
                    <option value="${m.id}">${m.id}</option>
                `).join('');
            }

            if (globalList) {
                globalList.innerHTML = models.map(m => `
                    <div onclick="selectGlobalModel('${m.id}')" data-model-id="${m.id}"
                        class="p-2.5 rounded-xl border border-transparent ${m.id === currentSelectedModel ? 'bg-neon-500/10 border-neon-500/30' : 'hover:bg-slate-100 dark:hover:bg-slate-800/80'} cursor-pointer flex items-center justify-between text-xs transition-all">
                        <div class="truncate mr-2">
                            <span class="font-bold text-slate-800 dark:text-slate-100 font-mono block truncate">${m.id}</span>
                            <span class="text-[10px] text-slate-400 font-mono block truncate">${m.owned_by || 'vLLM Engine'}</span>
                        </div>
                        <span class="px-2 py-0.5 rounded-full text-[10px] font-bold font-mono shrink-0 bg-emerald-50 dark:bg-emerald-950/60 text-emerald-600 dark:text-emerald-400 border border-emerald-200 dark:border-emerald-800/40">
                            ${(m.status || 'ONLINE').toUpperCase()}
                        </span>
                    </div>
                `).join('');
            }
            updateContextWindowMeter();
        }
    } catch (err) {
        console.debug('Failed to fetch available models:', err);
    }
}

function updateChatModelDisplay(modelId) {
    const displayName = modelId || 'AI Assistant';
    const headerName = document.getElementById('chat-header-model-name');
    const selectedPill = document.getElementById('chat-selected-model-pill');
    const welcomeAvatar = document.getElementById('chat-welcome-avatar');

    if (headerName) headerName.innerText = displayName;
    if (selectedPill) selectedPill.innerText = displayName;
    if (welcomeAvatar) welcomeAvatar.innerText = displayName.slice(0, 2).toUpperCase();
}

function onGlobalModelFilterChange(modelId) {
    currentSelectedModel = modelId;
    updateChatModelDisplay(modelId);
}

// Single-Turn Playground Inference
async function executeInference() {
    const prompt = document.getElementById('play-prompt')?.value.trim();
    if (!prompt) {
        showToast('Please enter a prompt to generate inference', 'warning');
        return;
    }

    const model = document.getElementById('play-model-select')?.value || currentSelectedModel || (typeof availableModels !== 'undefined' && availableModels[0]?.id) || 'default';
    const maxTokens = parseInt(document.getElementById('play-max-tokens')?.value, 10) || 512;
    const temperature = parseFloat(document.getElementById('play-temperature')?.value) || 0.7;
    const systemPrompt = document.getElementById('play-system-prompt')?.value.trim() || '';
    const outputEl = document.getElementById('play-output');
    const runBtn = document.getElementById('send-infer-btn');
    const stopBtn = document.getElementById('abort-infer-btn');
    const statusPill = document.getElementById('play-status-pill');

    if (outputEl) {
        outputEl.textContent = 'Connecting to model and running benchmark...';
    }
    if (runBtn) runBtn.classList.add('hidden');
    if (stopBtn) stopBtn.classList.remove('hidden');
    if (statusPill) {
        statusPill.innerText = 'Running...';
        statusPill.className = 'text-[10px] font-mono font-bold px-2 py-0.5 rounded-md bg-amber-500/10 text-amber-500 border border-amber-500/30 animate-pulse';
    }

    // Reset Benchmark HUD meters
    const hudSpeed = document.getElementById('hud-speed');
    const hudTime = document.getElementById('hud-time');
    const hudToks = document.getElementById('hud-tokens');
    const hudTtft = document.getElementById('hud-ttft');
    const hudVram = document.getElementById('hud-vram');

    if (hudSpeed) hudSpeed.innerText = '... tok/s';
    if (hudTime) hudTime.innerText = '0.0s';
    if (hudToks) hudToks.innerText = '0';
    if (hudTtft) hudTtft.innerText = '... ms';

    // Populate initial VRAM from dashboard
    const curVramUsage = document.getElementById('metric-vram-usage')?.innerText || '0.0';
    const curVramTotal = document.getElementById('metric-vram-total')?.innerText || '32.0';
    const curVramPct = document.getElementById('metric-vram-pct')?.innerText || '0%';
    if (hudVram) hudVram.innerText = `${curVramUsage} / ${curVramTotal} GB (${curVramPct})`;

    const startTime = performance.now();
    let firstTokenTime = null;
    let generatedTokenCount = 0;
    let responseText = '';
    const reqId = 'req_' + Math.random().toString(36).substring(2, 9);

    abortController = new AbortController();

    const messages = [];
    if (systemPrompt) messages.push({ role: 'system', content: systemPrompt });
    messages.push({ role: 'user', content: prompt });

    try {
        const authKey = localStorage.getItem('hpc_admin_session') || sessionStorage.getItem('hpc_admin_session') || activeApiKey || 'admin123';
        const res = await fetch(`${GATEWAY_BASE}/v1/chat/completions`, {
            method: 'POST',
            signal: abortController.signal,
            headers: {
                'Authorization': `Bearer ${authKey}`,
                'X-Admin-Session': authKey,
                'Content-Type': 'application/json'
            },
            body: JSON.stringify({
                model: model,
                messages: messages,
                temperature: temperature,
                max_tokens: maxTokens,
                stream: true
            })
        });

        if (!res.ok) {
            const errData = await res.json().catch(() => ({ error: { message: 'HTTP Error ' + res.status } }));
            throw new Error(errData.detail?.error?.message || errData.error?.message || `HTTP Error ${res.status}`);
        }

        const contentType = res.headers.get('content-type') || '';
        const isJson = contentType.includes('application/json');

        if (isJson) {
            const data = await res.json();
            const msg = data.choices?.[0]?.message || {};
            responseText = msg.content || msg.reasoning_content || '';
            generatedTokenCount = data.usage?.completion_tokens || Math.max(1, Math.round(responseText.length / 4));
            firstTokenTime = performance.now();
            if (outputEl) outputEl.textContent = responseText;
        } else {
            const reader = res.body.getReader();
            const decoder = new TextDecoder('utf-8');
            let buffer = '';
            let isFirstChunk = true;

            while (true) {
                const { done, value } = await reader.read();
                if (done) break;

                if (!firstTokenTime) {
                    firstTokenTime = performance.now();
                    const ttft = (firstTokenTime - startTime).toFixed(0);
                    const metricTtft = document.getElementById('metric-ttft');
                    if (hudTtft) hudTtft.innerText = `${ttft} ms`;
                    if (metricTtft) metricTtft.innerText = `${ttft} ms`;
                }

                buffer += decoder.decode(value, { stream: true });
                const lines = buffer.split('\n');
                buffer = lines.pop();

                for (const line of lines) {
                    const trimmed = line.trim();
                    if (!trimmed || !trimmed.startsWith('data:')) continue;
                    const dataStr = trimmed.substring(5).trim();
                    if (dataStr === '[DONE]') continue;

                    try {
                        const parsed = JSON.parse(dataStr);
                        if (parsed.usage?.completion_tokens) {
                            generatedTokenCount = parsed.usage.completion_tokens;
                        }
                        const delta = parsed.choices?.[0]?.delta;
                        const chunk = delta?.content || delta?.reasoning_content || '';
                        if (chunk) {
                            if (isFirstChunk) {
                                responseText = '';
                                isFirstChunk = false;
                            }
                            responseText += chunk;
                            if (outputEl) {
                                outputEl.textContent = responseText;
                                outputEl.scrollTop = outputEl.scrollHeight;
                            }
                            if (!parsed.usage?.completion_tokens) {
                                generatedTokenCount++;
                            }
                            if (hudToks) hudToks.innerText = generatedTokenCount;

                            // Live throughput computation
                            const elapsedSeconds = (performance.now() - startTime) / 1000;
                            if (elapsedSeconds > 0.05) {
                                const liveSpeed = (generatedTokenCount / elapsedSeconds).toFixed(1);
                                if (hudSpeed) hudSpeed.innerText = `${liveSpeed} tok/s`;
                                if (hudTime) hudTime.innerText = `${elapsedSeconds.toFixed(1)}s`;
                            }
                        }
                    } catch (err) { }
                }
            }
        }

        // Fallback token calculation if exact usage was omitted
        if (generatedTokenCount === 0 && responseText) {
            generatedTokenCount = Math.max(1, Math.round(responseText.length / 4));
        }

        const totalElapsed = (performance.now() - startTime) / 1000;
        const tokPerSec = (generatedTokenCount / Math.max(0.01, totalElapsed)).toFixed(1);
        const ttftVal = firstTokenTime ? (firstTokenTime - startTime).toFixed(0) : Math.round(totalElapsed * 1000);

        // Update Benchmark HUD meters with vibrant results
        const metricSpeed = document.getElementById('metric-speed');
        const metricTtft = document.getElementById('metric-ttft');
        if (hudSpeed) hudSpeed.innerText = `${tokPerSec} tok/s`;
        if (hudTime) hudTime.innerText = `${totalElapsed.toFixed(2)}s`;
        if (hudTtft) hudTtft.innerText = `${ttftVal} ms`;
        if (hudToks) hudToks.innerText = generatedTokenCount;
        if (metricSpeed) metricSpeed.innerText = tokPerSec;
        if (metricTtft) metricTtft.innerText = `${ttftVal} ms`;

        // Update status pill to completed
        if (statusPill) {
            statusPill.innerText = `✓ ${tokPerSec} tok/s (${totalElapsed.toFixed(1)}s)`;
            statusPill.className = 'text-[10px] font-mono font-bold px-2 py-0.5 rounded-md bg-neon-500/15 text-neon-500 border border-neon-500/40';
        }

        // Read and update VRAM pill
        let vramStr = hudVram?.innerText || '-- GB';
        const vramUsageEl = document.getElementById('metric-vram-usage');
        const vramTotalEl = document.getElementById('metric-vram-total');
        if (vramUsageEl && vramTotalEl && vramUsageEl.innerText !== '0.0' && vramUsageEl.innerText !== '--') {
            const u = vramUsageEl.innerText;
            const t = Math.round(parseFloat(vramTotalEl.innerText) || 32);
            vramStr = `${u} / ${t} GB`;
            if (hudVram) hudVram.innerText = vramStr;
        }

        // Fetch live VRAM from backend API to ensure 100% accurate reading
        try {
            fetch(`${GATEWAY_BASE}/api/metrics/realtime`)
                .then(r => r.json())
                .then(d => {
                    if (d && d.vram_used_gb !== undefined && hudVram) {
                        const u = typeof d.vram_used_gb === 'number' ? d.vram_used_gb.toFixed(1) : d.vram_used_gb;
                        const t = Math.round(d.vram_total_gb || 32);
                        hudVram.innerText = `${u} / ${t} GB`;
                        hudVram.title = `VRAM: ${u} / ${d.vram_total_gb} GB (${d.vram_used_pct || 0}%)`;
                    }
                })
                .catch(() => {});
        } catch (e) {}

        // Append high-visibility Benchmark summary block directly into the console
        const summaryBlock = `\n\n══════════════════════════════════════════════════════════════
⚡ BENCHMARK RESULT:
• Model:        ${model}
• Status:       200 OK (Completed)
• Throughput:   ${tokPerSec} tok/s
• Generated:    ${generatedTokenCount} tokens in ${totalElapsed.toFixed(2)}s
• First Token:  ${ttftVal} ms (TTFT)
• VRAM Usage:   ${vramStr}
══════════════════════════════════════════════════════════════`;

        if (outputEl) {
            outputEl.textContent = (responseText || '[No response text received from model]') + summaryBlock;
            outputEl.scrollTop = outputEl.scrollHeight;
        }

        totalRequests++;
        totalTokens += generatedTokenCount;
        const reqEl = document.getElementById('metric-total-requests');
        const tokEl = document.getElementById('metric-total-tokens');
        if (reqEl) reqEl.innerText = totalRequests;
        if (tokEl) tokEl.innerText = totalTokens;

        // Immediate post-inference real-time hardware telemetry refresh
        if (typeof fetchRealtimeMetrics === 'function') {
            fetchRealtimeMetrics().catch(() => {});
        }

        addLedgerRecord({
            id: reqId,
            model: model,
            tokens: generatedTokenCount,
            latency: (totalElapsed * 1000).toFixed(0),
            speed: tokPerSec,
            status: '200 OK',
            time: new Date().toLocaleTimeString()
        });

        showToast(`Benchmark: ${generatedTokenCount} tokens @ ${tokPerSec} tok/s`, 'success');

    } catch (error) {
        if (error.name === 'AbortError') {
            if (outputEl) outputEl.textContent += '\n\n[Inference stopped by user]';
            if (statusPill) {
                statusPill.innerText = 'Stopped';
                statusPill.className = 'text-[10px] font-mono font-bold px-2 py-0.5 rounded-md bg-amber-500/15 text-amber-500 border border-amber-500/30';
            }
            showToast('Inference cancelled', 'info');
        } else {
            if (outputEl) {
                outputEl.textContent = `[Inference Error] ${error.message}\n\nPlease check that the target model is running and Slurm compute worker is online.`;
            }
            if (statusPill) {
                statusPill.innerText = '✗ Failed';
                statusPill.className = 'text-[10px] font-mono font-bold px-2 py-0.5 rounded-md bg-rose-500/15 text-rose-500 border border-rose-500/30';
            }
            showToast(`Error: ${error.message}`, 'error');
            addLedgerRecord({
                id: reqId,
                model: model,
                tokens: 0,
                latency: '0',
                speed: '0',
                status: 'ERROR',
                time: new Date().toLocaleTimeString()
            });
        }
    } finally {
        if (runBtn) runBtn.classList.remove('hidden');
        if (stopBtn) stopBtn.classList.add('hidden');
        abortController = null;
    }
}

function abortInference() {
    if (abortController) abortController.abort();
}

function addLedgerRecord(rec) {
    ledger.unshift(rec);
    if (ledger.length > 50) ledger.pop();
    renderLedger();
}

function renderLedger() {
    const container = document.getElementById('tx-feed-container');
    if (!container) return;
    container.innerHTML = '';

    const filtered = ledger.filter(item => {
        if (activeFilter === '200') return item.status === '200 OK';
        if (activeFilter === 'err') return item.status !== '200 OK';
        return true;
    });

    const pageInfo = document.getElementById('page-info-text');
    if (pageInfo) pageInfo.innerText = `Showing recent ${filtered.length} calls`;

    if (filtered.length === 0) {
        container.innerHTML = `
            <div class="p-6 text-center text-slate-400 text-xs rounded-xl bg-slate-50 dark:bg-[#111827] border border-slate-200/70 dark:border-slate-800">
                No inference records logged yet
            </div>`;
        return;
    }

    filtered.forEach(item => {
        const isSuccess = item.status === '200 OK';
        const card = document.createElement('div');
        card.className = 'p-3 rounded-xl bg-slate-50 dark:bg-[#111827] border border-slate-200/70 dark:border-slate-800 hover:border-neon-500/50 transition-all flex items-center justify-between text-xs';
        card.innerHTML = `
            <div class="flex items-center gap-3">
                <span class="w-2 h-7 rounded-full ${isSuccess ? 'bg-neon-500' : 'bg-rose-500'}"></span>
                <div>
                    <div class="flex items-center gap-2">
                        <span class="font-bold text-slate-900 dark:text-white font-mono">${item.id}</span>
                        <span class="px-2 py-0.5 rounded bg-slate-200 dark:bg-slate-800 text-[10px] font-mono font-semibold text-slate-700 dark:text-slate-300">${item.model}</span>
                    </div>
                    <div class="text-[11px] text-slate-400 font-mono mt-0.5">
                        ${item.time} • ${item.latency}ms • ${item.speed} tok/s
                    </div>
                </div>
            </div>
            <div class="text-right font-mono">
                <span class="text-xs font-bold ${isSuccess ? 'text-neon-700 dark:text-neon-400' : 'text-rose-500'}">${item.status}</span>
                <span class="block text-[11px] text-slate-400">${item.tokens} tok</span>
            </div>
        `;
        container.appendChild(card);
    });
}

function filterLogs(type) {
    activeFilter = type;
    const btnAll = document.getElementById('filter-all-btn');
    const btnOk = document.getElementById('filter-ok-btn');
    const btnErr = document.getElementById('filter-err-btn');

    [btnAll, btnOk, btnErr].forEach(b => {
        if (b) b.className = 'px-2 py-1 rounded text-slate-600 dark:text-slate-400 font-medium';
    });

    if (type === 'all' && btnAll) btnAll.className = 'px-2 py-1 rounded bg-white dark:bg-neon-500 text-neon-800 dark:text-slate-950 font-black shadow-sm';
    if (type === '200' && btnOk) btnOk.className = 'px-2 py-1 rounded bg-white dark:bg-neon-500 text-neon-800 dark:text-slate-950 font-black shadow-sm';
    if (type === 'err' && btnErr) btnErr.className = 'px-2 py-1 rounded bg-white dark:bg-neon-500 text-neon-800 dark:text-slate-950 font-black shadow-sm';

    renderLedger();
}

function clearLedger() {
    ledger = [];
    renderLedger();
    showToast('Ledger audit cleared', 'info');
}

// Multi-Turn Chatbot Studio
async function sendChatMessage() {
    const input = document.getElementById('chat-user-input');
    if (!input) return;
    const text = input.value.trim();
    if (!text) return;

    input.value = '';
    if (typeof autoResizeTextarea === 'function') autoResizeTextarea(input);
    const starters = document.getElementById('chat-prompt-starters');
    if (starters) starters.classList.add('hidden');

    appendChatMessage('user', text);
    updateContextWindowMeter();

    const sysPrompt = document.getElementById('chat-system-prompt')?.value.trim() || 'You are a helpful, direct, and concise AI assistant.';
    const temp = parseFloat(document.getElementById('chat-temp')?.value) || 0.7;
    const topP = parseFloat(document.getElementById('chat-topp')?.value) || 0.9;
    const maxTokens = parseInt(document.getElementById('chat-tokens')?.value, 10) || 2048;
    const presencePenalty = parseFloat(document.getElementById('chat-presence')?.value) || 0.0;
    const frequencyPenalty = parseFloat(document.getElementById('chat-frequency')?.value) || 0.0;

    const sendBtn = document.getElementById('chat-send-btn');
    const stopBtn = document.getElementById('chat-stop-btn');
    if (sendBtn) sendBtn.classList.add('hidden');
    if (stopBtn) stopBtn.classList.remove('hidden');

    const assistantBubble = appendChatMessage('assistant', '...');
    let fullContent = '';
    let fullReasoning = '';
    let rawAccumulatedContent = '';
    let tokenCount = 0;
    const startTime = performance.now();

    chatAbortController = new AbortController();

    const messagesPayload = [];
    if (sysPrompt) messagesPayload.push({ role: 'system', content: sysPrompt });
    conversationHistory.forEach(msg => messagesPayload.push(msg));

    let streamDone = false;
    let renderScheduled = false;
    function scheduleRender(isFinal = false) {
        if (isFinal) {
            streamDone = true;
            renderBubble();
            updateContextWindowMeter();
            return;
        }
        if (renderScheduled) return;
        renderScheduled = true;
        requestAnimationFrame(() => {
            renderBubble();
            renderScheduled = false;
        });
    }

    function renderBubble() {
        if (!assistantBubble) return;
        let html = '';
        if (fullReasoning) {
            const isThinking = !streamDone && !fullContent;
            html += `
                <details ${isThinking || !fullContent ? 'open' : ''} class="mb-3 select-none group">
                    <summary class="text-[11px] font-medium text-slate-500 dark:text-slate-400 hover:text-slate-800 dark:hover:text-slate-200 transition-colors py-0.5 cursor-pointer list-none flex items-center gap-1.5">
                        <span class="text-xs transform transition-transform group-open:rotate-90 inline-block text-slate-400">▶</span>
                        <span class="${isThinking ? 'text-purple-600 dark:text-purple-400 font-semibold animate-pulse' : 'text-slate-500 font-medium'}">
                            ${isThinking ? 'Thinking...' : 'Thought process'}
                        </span>
                    </summary>
                    <div class="mt-1.5 pl-3 border-l-2 border-purple-400 dark:border-purple-700 text-[11px] text-slate-600 dark:text-slate-300 font-mono whitespace-pre-wrap leading-relaxed max-h-96 overflow-y-auto">
                        ${escapeHtml(fullReasoning)}
                    </div>
                </details>
            `;
        }
        if (fullContent) {
            html += formatMarkdownText(fullContent);
        } else if (!fullReasoning) {
            html += '<span class="animate-pulse text-slate-400">...</span>';
        } else if (streamDone && !fullContent) {
            html += '<div class="text-[12px] text-slate-400 italic mt-1">(Thinking completed)</div>';
        }
        assistantBubble.innerHTML = html;
        const container = document.getElementById('chat-messages-container');
        if (container) container.scrollTop = container.scrollHeight;
    }

    try {
        const authKey = localStorage.getItem('hpc_admin_session') || sessionStorage.getItem('hpc_admin_session') || activeApiKey || '';
        const requestPayload = {
            model: currentSelectedModel || document.getElementById('chat-model-select')?.value || (typeof availableModels !== 'undefined' && availableModels[0]?.id) || 'default',
            messages: messagesPayload,
            temperature: temp,
            top_p: topP,
            max_tokens: maxTokens,
            stream: true
        };
        if (presencePenalty !== 0.0) requestPayload.presence_penalty = presencePenalty;
        if (frequencyPenalty !== 0.0) requestPayload.frequency_penalty = frequencyPenalty;

        const res = await fetch(`${GATEWAY_BASE}/v1/chat/completions`, {
            method: 'POST',
            signal: chatAbortController.signal,
            headers: {
                'Authorization': `Bearer ${authKey}`,
                'X-Admin-Session': authKey,
                'Content-Type': 'application/json'
            },
            body: JSON.stringify(requestPayload)
        });

        if (!res.ok) {
            const err = await res.json().catch(() => ({ error: { message: 'HTTP Error ' + res.status } }));
            throw new Error(err.detail?.error?.message || err.detail || err.error?.message || 'Chat generation error');
        }

        if (assistantBubble) assistantBubble.textContent = '';
        const contentType = res.headers.get('content-type') || '';

        if (contentType.includes('application/json')) {
            const data = await res.json();
            const msg = data.choices?.[0]?.message || {};
            let rawContent = msg.content || '';
            fullReasoning = msg.reasoning_content || '';

            if (rawContent.includes('<think>')) {
                const s = rawContent.indexOf('<think>');
                const e = rawContent.indexOf('</think>');
                if (e !== -1) {
                    fullReasoning = (fullReasoning ? fullReasoning + '\n' : '') + rawContent.slice(s + 7, e).trim();
                    fullContent = (rawContent.slice(0, s) + rawContent.slice(e + 8)).trimStart();
                } else {
                    fullReasoning = (fullReasoning ? fullReasoning + '\n' : '') + rawContent.slice(s + 7).trim();
                    fullContent = rawContent.slice(0, s);
                }
            } else {
                fullContent = rawContent;
            }

            conversationHistory.push({ role: 'assistant', content: fullContent || fullReasoning });
            scheduleRender(true);
            updateContextWindowMeter();

            const elapsed = (performance.now() - startTime) / 1000;
            const completionTokens = data.usage?.completion_tokens || 10;
            const speed = (completionTokens / (elapsed || 1)).toFixed(1);
            const liveSpeed = document.getElementById('chat-live-speed');
            if (liveSpeed) liveSpeed.innerText = speed;
            return;
        }

        const reader = res.body.getReader();
        const decoder = new TextDecoder('utf-8');
        let buffer = '';

        while (true) {
            const { done, value } = await reader.read();
            if (done) break;

            buffer += decoder.decode(value, { stream: true });
            const lines = buffer.split('\n');
            buffer = lines.pop();

            for (const line of lines) {
                const trimmed = line.trim();
                if (!trimmed || !trimmed.startsWith('data:')) continue;
                const dataStr = trimmed.substring(5).trim();
                if (dataStr === '[DONE]') continue;

                try {
                    const parsed = JSON.parse(dataStr);
                    const delta = parsed.choices?.[0]?.delta;
                    if (delta) {
                        if (delta.reasoning_content) {
                            fullReasoning += delta.reasoning_content;
                            tokenCount++;
                        }
                        if (delta.content) {
                            rawAccumulatedContent += delta.content;
                            tokenCount++;

                            // Automatically parse inline <think>...</think> tags if model emits them in content
                            if (rawAccumulatedContent.includes('<think>')) {
                                const thinkStart = rawAccumulatedContent.indexOf('<think>');
                                const thinkEnd = rawAccumulatedContent.indexOf('</think>');
                                if (thinkEnd !== -1) {
                                    // Finished thinking, separate thought & main response
                                    const extractedThought = rawAccumulatedContent.slice(thinkStart + 7, thinkEnd).trim();
                                    fullReasoning = (fullReasoning && !fullReasoning.includes(extractedThought)) ? (fullReasoning + '\n' + extractedThought) : extractedThought;
                                    fullContent = (rawAccumulatedContent.slice(0, thinkStart) + rawAccumulatedContent.slice(thinkEnd + 8)).trimStart();
                                } else {
                                    // Still thinking inside <think> tag
                                    fullReasoning = rawAccumulatedContent.slice(thinkStart + 7);
                                    fullContent = rawAccumulatedContent.slice(0, thinkStart);
                                }
                            } else {
                                fullContent = rawAccumulatedContent;
                            }
                        }
                        scheduleRender(false);

                        const elapsed = (performance.now() - startTime) / 1000;
                        if (elapsed > 0) {
                            const speed = (tokenCount / elapsed).toFixed(1);
                            const liveSpeed = document.getElementById('chat-live-speed');
                            if (liveSpeed) liveSpeed.innerText = speed;
                        }
                    }
                } catch (e) { }
            }
        }

        conversationHistory.push({ role: 'assistant', content: fullContent || fullReasoning });
        scheduleRender(true);
        updateContextWindowMeter();

    } catch (err) {
        if (err.name === 'AbortError') {
            scheduleRender(true);
            if (assistantBubble) assistantBubble.innerHTML += '<div class="mt-2 text-slate-400 italic text-[11px]">⏹️ Response generation stopped by user.</div>';
        } else {
            if (assistantBubble) assistantBubble.innerHTML = `<span class="text-rose-500 font-bold">Error: ${escapeHtml(err.message)}</span>`;
        }
    } finally {
        if (sendBtn) sendBtn.classList.remove('hidden');
        if (stopBtn) stopBtn.classList.add('hidden');
        chatAbortController = null;
        if (window.lucide) lucide.createIcons();
    }
}

function toggleChatParametersDrawer() {
    const drawer = document.getElementById('chat-parameters-drawer');
    if (drawer) {
        drawer.classList.toggle('hidden');
        if (window.lucide) lucide.createIcons();
    }
}

function useStarterPrompt(text) {
    const input = document.getElementById('chat-user-input');
    if (input) {
        input.value = text;
        if (typeof autoResizeTextarea === 'function') autoResizeTextarea(input);
        sendChatMessage();
    }
}

function appendChatMessage(role, content) {
    const container = document.getElementById('chat-messages-container');
    if (!container) return null;

    const row = document.createElement('div');
    row.className = 'flex items-start gap-3.5';

    const isUser = role === 'user';
    const modelName = currentSelectedModel || document.getElementById('chat-model-select')?.value || 'AI Assistant';
    const avatar = isUser ? 'U' : modelName.slice(0, 2).toUpperCase();
    const avatarBg = isUser ? 'bg-slate-700 text-white' : 'bg-neon-500 text-slate-950 font-black shadow-glow-neon-sm';
    const bubbleBg = isUser ? 'bg-neon-50/80 dark:bg-neon-500/10 border border-neon-200 dark:border-neon-500/30' : 'bg-white dark:bg-[#0a0f18] border border-slate-200 dark:border-slate-800';

    row.innerHTML = `
        <div class="w-8 h-8 rounded-xl ${avatarBg} font-bold flex items-center justify-center text-[10px] flex-shrink-0 shadow-sm font-mono" title="${isUser ? 'You' : escapeHtml(modelName)}">
            ${avatar}
        </div>
        <div class="p-4 rounded-2xl ${bubbleBg} text-xs text-slate-800 dark:text-slate-100 leading-relaxed max-w-3xl w-full shadow-sm markdown-body">
            ${!isUser ? `<div class="text-[10px] font-bold text-neon-600 dark:text-neon-400 font-mono mb-2 flex items-center justify-between">
                <span>${escapeHtml(modelName)}</span>
                <button type="button" onclick="copyResponseText(this)" class="text-slate-400 hover:text-neon-400 font-sans flex items-center gap-1 text-[10px] transition-colors" title="Copy response">
                    <i data-lucide="copy" class="w-3 h-3"></i>
                    <span>Copy</span>
                </button>
            </div>` : ''}
            ${isUser ? `<p>${escapeHtml(content).replace(/\n/g, '<br>')}</p>` : formatMarkdownText(content)}
        </div>
    `;

    container.appendChild(row);
    container.scrollTop = container.scrollHeight;
    if (window.lucide) lucide.createIcons();

    if (isUser) {
        conversationHistory.push({ role: 'user', content: content });
    }

    return row.querySelector('.markdown-body');
}

function copyResponseText(btn) {
    const bubble = btn.closest('.markdown-body');
    if (!bubble) return;
    const textToCopy = bubble.innerText.replace(/^[^\n]*\n/, '').trim(); // skip header
    navigator.clipboard.writeText(textToCopy).then(() => {
        const originalHtml = btn.innerHTML;
        btn.innerHTML = `<i data-lucide="check" class="w-3 h-3 text-neon-500"></i><span class="text-neon-400 font-bold">Copied!</span>`;
        if (window.lucide) lucide.createIcons();
        setTimeout(() => {
            btn.innerHTML = originalHtml;
            if (window.lucide) lucide.createIcons();
        }, 2000);
    }).catch(() => {
        showToast('Failed to copy text', 'error');
    });
}

function stopChatStreaming() {
    if (chatAbortController) chatAbortController.abort();
}

function clearChatHistory() {
    conversationHistory = [];
    updateContextWindowMeter();
    const modelName = currentSelectedModel || document.getElementById('chat-model-select')?.value || 'AI Assistant';
    const container = document.getElementById('chat-messages-container');
    if (container) {
        container.innerHTML = `
            <div class="flex items-start gap-3.5">
                <div id="chat-welcome-avatar" class="w-8 h-8 rounded-xl bg-gradient-to-tr from-emerald-600 to-teal-400 text-slate-950 font-black flex items-center justify-center text-xs flex-shrink-0 shadow-sm font-mono">
                    ${escapeHtml(modelName.slice(0, 2).toUpperCase())}
                </div>
                <div id="chat-welcome-bubble" class="p-4 rounded-2xl bg-white dark:bg-[#1e293b]/70 border border-slate-200/80 dark:border-slate-800/80 text-xs text-slate-800 dark:text-slate-100 leading-relaxed max-w-3xl w-full shadow-sm markdown-body">
                    <div class="font-bold text-emerald-600 dark:text-emerald-400 mb-1 flex items-center gap-1.5">
                        <i data-lucide="sparkles" class="w-3.5 h-3.5"></i>
                        <span>AI Local Serving Assistant</span>
                    </div>
                    <p>Chat session refreshed. Select a quick starter prompt below or enter a new query:</p>
                </div>
            </div>

            <div id="chat-prompt-starters" class="grid grid-cols-1 sm:grid-cols-2 gap-3 pl-11 max-w-3xl">
                <button type="button" onclick="useStarterPrompt('Benchmark inference performance and explain the latency & memory differences between FP16 and GGUF Q4_K_M on Tesla V100.')"
                    class="prompt-starter-chip p-3 rounded-2xl bg-white dark:bg-[#1e293b]/50 border border-slate-200/90 dark:border-slate-800 text-left hover:border-emerald-500/50 hover:bg-emerald-50/50 dark:hover:bg-emerald-950/20 transition-all shadow-sm group">
                    <div class="flex items-center gap-2 text-emerald-600 dark:text-emerald-400 font-bold text-xs mb-1">
                        <i data-lucide="zap" class="w-3.5 h-3.5"></i>
                        <span>Performance Benchmark</span>
                    </div>
                    <p class="text-[11px] text-slate-500 dark:text-slate-400 line-clamp-2">Compare FP16 vs GGUF Q4_K_M throughput on Tesla V100...</p>
                </button>

                <button type="button" onclick="useStarterPrompt('Write a Python script using the standard openai package to stream chat completions from gateway http://localhost:9001/v1.')"
                    class="prompt-starter-chip p-3 rounded-2xl bg-white dark:bg-[#1e293b]/50 border border-slate-200/90 dark:border-slate-800 text-left hover:border-emerald-500/50 hover:bg-emerald-50/50 dark:hover:bg-emerald-950/20 transition-all shadow-sm group">
                    <div class="flex items-center gap-2 text-teal-600 dark:text-teal-400 font-bold text-xs mb-1">
                        <i data-lucide="code" class="w-3.5 h-3.5"></i>
                        <span>Python Client Example</span>
                    </div>
                    <p class="text-[11px] text-slate-500 dark:text-slate-400 line-clamp-2">Connect and stream chat completions via OpenAI SDK...</p>
                </button>

                <button type="button" onclick="useStarterPrompt('Draft an optimized sbatch script to launch a vLLM serving engine for Qwen on our Slurm HPC cluster.')"
                    class="prompt-starter-chip p-3 rounded-2xl bg-white dark:bg-[#1e293b]/50 border border-slate-200/90 dark:border-slate-800 text-left hover:border-emerald-500/50 hover:bg-emerald-50/50 dark:hover:bg-emerald-950/20 transition-all shadow-sm group">
                    <div class="flex items-center gap-2 text-sky-600 dark:text-sky-400 font-bold text-xs mb-1">
                        <i data-lucide="layers" class="w-3.5 h-3.5"></i>
                        <span>Slurm Sbatch Script</span>
                    </div>
                    <p class="text-[11px] text-slate-500 dark:text-slate-400 line-clamp-2">Production sbatch template for vLLM compute node serving...</p>
                </button>

                <button type="button" onclick="useStarterPrompt('Explain how PagedAttention in vLLM solves KV Cache memory fragmentation during continuous batching.')"
                    class="prompt-starter-chip p-3 rounded-2xl bg-white dark:bg-[#1e293b]/50 border border-slate-200/90 dark:border-slate-800 text-left hover:border-emerald-500/50 hover:bg-emerald-50/50 dark:hover:bg-emerald-950/20 transition-all shadow-sm group">
                    <div class="flex items-center gap-2 text-indigo-600 dark:text-indigo-400 font-bold text-xs mb-1">
                        <i data-lucide="help-circle" class="w-3.5 h-3.5"></i>
                        <span>PagedAttention Architecture</span>
                    </div>
                    <p class="text-[11px] text-slate-500 dark:text-slate-400 line-clamp-2">How virtual paging and contiguous blocks maximize VRAM...</p>
                </button>
            </div>
        `;
        if (window.lucide) lucide.createIcons();
    }
    showToast('Chat history cleared', 'info');
}

function exportChatTranscript() {
    if (conversationHistory.length === 0) {
        showToast('No conversation history to export', 'error');
        return;
    }
    let text = `# AI Local LLM Chat Transcript (${currentSelectedModel || 'model'})\n\n`;
    conversationHistory.forEach(m => {
        text += `### ${m.role.toUpperCase()}\n${m.content}\n\n`;
    });
    const blob = new Blob([text], { type: 'text/markdown' });
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = `chat_${currentSelectedModel || 'llm'}_${Date.now()}.md`;
    a.click();
    URL.revokeObjectURL(url);
    showToast('Chat transcript exported as Markdown', 'success');
}

// Markdown renderer configuration
if (typeof marked !== 'undefined') {
    const renderer = new marked.Renderer();

    renderer.code = function (code, lang) {
        let codeText = '';
        if (typeof code === 'object' && code.text !== undefined) {
            lang = code.lang || '';
            codeText = code.text;
        } else {
            codeText = code || '';
        }

        const validLang = lang && typeof hljs !== 'undefined' && hljs.getLanguage(lang) ? lang : '';
        let highlighted = '';
        try {
            highlighted = validLang
                ? hljs.highlight(codeText, { language: validLang, ignoreIllegals: true }).value
                : (typeof hljs !== 'undefined' ? hljs.highlightAuto(codeText).value : escapeHtml(codeText));
        } catch (e) {
            highlighted = escapeHtml(codeText);
        }

        const displayLang = (validLang || 'CODE').toUpperCase();
        const codeId = 'code_' + Math.random().toString(36).substring(2, 9);

        return `
            <div class="code-wrapper not-prose">
                <div class="code-header">
                    <span class="font-mono text-neon-400 font-bold">${displayLang}</span>
                    <button type="button" class="code-copy-btn" onclick="copyCodeBlock(this, '${codeId}')">
                        <i data-lucide="copy" class="w-3 h-3"></i>
                        <span>Copy</span>
                    </button>
                </div>
                <pre><code id="${codeId}" class="hljs ${validLang}">${highlighted}</code></pre>
            </div>
        `;
    };

    marked.setOptions({
        renderer: renderer,
        gfm: true,
        breaks: true,
        smartLists: true,
        smartypants: true
    });
}

function formatMarkdownText(str) {
    if (!str) return '';
    try {
        if (typeof marked !== 'undefined') {
            return marked.parse(str);
        }
    } catch (e) {
        console.error('Marked parsing error:', e);
    }
    return escapeHtml(str).replace(/\n/g, '<br>');
}

function copyCodeBlock(btn, codeId) {
    const codeEl = document.getElementById(codeId);
    if (!codeEl) return;
    navigator.clipboard.writeText(codeEl.innerText).then(() => {
        const originalHtml = btn.innerHTML;
        btn.innerHTML = `<span class="text-neon-400 font-bold">Copied!</span>`;
        setTimeout(() => {
            btn.innerHTML = originalHtml;
            if (window.lucide) lucide.createIcons();
        }, 2000);
    }).catch(() => {
        showToast('Failed to copy code', 'error');
    });
}

function escapeHtml(text) {
    return text
        .replace(/&/g, "&amp;")
        .replace(/</g, "&lt;")
        .replace(/>/g, "&gt;");
}

// Auto-initialize Chatbot Settings and Context Window Meter
if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', () => {
        loadChatSettings();
        updateContextWindowMeter();
    });
} else {
    loadChatSettings();
    updateContextWindowMeter();
}
