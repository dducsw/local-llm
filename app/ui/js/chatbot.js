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

    const model = document.getElementById('play-model-select')?.value || 'qwen3.5-9b';
    const maxTokens = parseInt(document.getElementById('play-max-tokens')?.value, 10) || 512;
    const temperature = parseFloat(document.getElementById('play-temperature')?.value) || 0.7;
    const systemPrompt = document.getElementById('play-system-prompt')?.value.trim() || '';
    const outputEl = document.getElementById('play-output');
    const runBtn = document.getElementById('send-infer-btn');
    const stopBtn = document.getElementById('abort-infer-btn');

    if (outputEl) outputEl.textContent = '';
    if (runBtn) runBtn.classList.add('hidden');
    if (stopBtn) stopBtn.classList.remove('hidden');

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
            throw new Error(errData.detail?.error?.message || errData.error?.message || 'Inference error');
        }

        const contentType = res.headers.get('content-type') || '';
        if (contentType.includes('application/json')) {
            const data = await res.json();
            const msg = data.choices?.[0]?.message || {};
            responseText = msg.content || msg.reasoning_content || '';
            if (outputEl) outputEl.textContent = responseText;
            generatedTokenCount = data.usage?.completion_tokens || 10;
            const hudToks = document.getElementById('hud-tokens');
            if (hudToks) hudToks.innerText = generatedTokenCount;
            return;
        }

        const reader = res.body.getReader();
        const decoder = new TextDecoder('utf-8');
        let buffer = '';

        while (true) {
            const { done, value } = await reader.read();
            if (done) break;

            if (!firstTokenTime) {
                firstTokenTime = performance.now();
                const ttft = (firstTokenTime - startTime).toFixed(0);
                const hudTtft = document.getElementById('hud-ttft');
                const metricTtft = document.getElementById('metric-ttft');
                if (hudTtft) hudTtft.innerText = `${ttft}ms`;
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
                    const delta = parsed.choices?.[0]?.delta;
                    const chunk = delta?.content || delta?.reasoning_content || '';
                    if (chunk) {
                        responseText += chunk;
                        if (outputEl) {
                            outputEl.textContent = responseText;
                            outputEl.scrollTop = outputEl.scrollHeight;
                        }
                        generatedTokenCount++;
                        const hudToks = document.getElementById('hud-tokens');
                        if (hudToks) hudToks.innerText = generatedTokenCount;
                    }
                } catch (err) { }
            }
        }

        const totalElapsed = (performance.now() - startTime) / 1000;
        const tokPerSec = (generatedTokenCount / totalElapsed).toFixed(1);

        const hudTime = document.getElementById('hud-time');
        const metricSpeed = document.getElementById('metric-speed');
        if (hudTime) hudTime.innerText = `${totalElapsed.toFixed(2)}s`;
        if (metricSpeed) metricSpeed.innerText = tokPerSec;

        totalRequests++;
        totalTokens += generatedTokenCount;
        const reqEl = document.getElementById('metric-total-requests');
        const tokEl = document.getElementById('metric-total-tokens');
        if (reqEl) reqEl.innerText = totalRequests;
        if (tokEl) tokEl.innerText = totalTokens;

        addLedgerRecord({
            id: reqId,
            model: model,
            tokens: generatedTokenCount,
            latency: (totalElapsed * 1000).toFixed(0),
            speed: tokPerSec,
            status: '200 OK',
            time: new Date().toLocaleTimeString()
        });

        showToast(`Inference completed: ${generatedTokenCount} tokens @ ${tokPerSec} tok/s`, 'success');

    } catch (error) {
        if (error.name === 'AbortError') {
            if (outputEl) outputEl.textContent += '\n\n[Inference stopped by user]';
            showToast('Inference cancelled', 'info');
        } else {
            if (outputEl) outputEl.textContent = `Error: ${error.message}`;
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
    appendChatMessage('user', text);

    const sysPrompt = document.getElementById('chat-system-prompt')?.value.trim() || 'You are a helpful, direct, and concise AI assistant.';
    const temp = parseFloat(document.getElementById('chat-temp')?.value) || 0.7;
    const maxTokens = parseInt(document.getElementById('chat-tokens')?.value, 10) || 2048;

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
        const authKey = localStorage.getItem('hpc_admin_session') || sessionStorage.getItem('hpc_admin_session') || activeApiKey || 'admin123';
        const res = await fetch(`${GATEWAY_BASE}/v1/chat/completions`, {
            method: 'POST',
            signal: chatAbortController.signal,
            headers: {
                'Authorization': `Bearer ${authKey}`,
                'X-Admin-Session': authKey,
                'Content-Type': 'application/json'
            },
            body: JSON.stringify({
                model: currentSelectedModel || document.getElementById('chat-model-select')?.value || 'qwen3.5-9b',
                messages: messagesPayload,
                temperature: temp,
                max_tokens: maxTokens,
                stream: true
            })
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

            scheduleRender(true);

            const elapsed = (performance.now() - startTime) / 1000;
            const completionTokens = data.usage?.completion_tokens || 10;
            const speed = (completionTokens / (elapsed || 1)).toFixed(1);
            const liveSpeed = document.getElementById('chat-live-speed');
            if (liveSpeed) liveSpeed.innerText = speed;

            conversationHistory.push({ role: 'assistant', content: fullContent || fullReasoning });
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

        scheduleRender(true);
        conversationHistory.push({ role: 'assistant', content: fullContent || fullReasoning });

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

function appendChatMessage(role, content) {
    const container = document.getElementById('chat-messages-container');
    if (!container) return null;

    const row = document.createElement('div');
    row.className = 'flex items-start gap-3';

    const isUser = role === 'user';
    const modelName = currentSelectedModel || document.getElementById('chat-model-select')?.value || 'AI Assistant';
    const avatar = isUser ? 'U' : modelName.slice(0, 2).toUpperCase();
    const avatarBg = isUser ? 'bg-slate-700 text-white' : 'bg-gradient-to-tr from-neon-600 to-emerald-400 text-slate-950 font-black';
    const bubbleBg = isUser ? 'bg-neon-50/80 dark:bg-neon-950/20 border border-neon-200 dark:border-neon-500/30' : 'bg-slate-100/80 dark:bg-[#111827] border border-slate-200/80 dark:border-slate-800';

    row.innerHTML = `
        <div class="w-8 h-8 rounded-xl ${avatarBg} font-bold flex items-center justify-center text-[10px] flex-shrink-0 shadow-sm" title="${isUser ? 'You' : escapeHtml(modelName)}">
            ${avatar}
        </div>
        <div class="p-4 rounded-2xl ${bubbleBg} text-xs text-slate-800 dark:text-slate-100 leading-relaxed max-w-2xl w-full markdown-body">
            ${!isUser ? `<div class="text-[10px] font-bold text-neon-700 dark:text-neon-400 font-mono mb-2">${escapeHtml(modelName)}</div>` : ''}
            ${isUser ? `<p>${escapeHtml(content).replace(/\n/g, '<br>')}</p>` : formatMarkdownText(content)}
        </div>
    `;

    container.appendChild(row);
    container.scrollTop = container.scrollHeight;

    if (isUser) {
        conversationHistory.push({ role: 'user', content: content });
    }

    return row.querySelector('.markdown-body');
}

function stopChatStreaming() {
    if (chatAbortController) chatAbortController.abort();
}

function clearChatHistory() {
    conversationHistory = [];
    const modelName = currentSelectedModel || document.getElementById('chat-model-select')?.value || 'AI Assistant';
    const container = document.getElementById('chat-messages-container');
    if (container) {
        container.innerHTML = `
            <div class="flex items-start gap-3">
                <div class="w-8 h-8 rounded-xl bg-gradient-to-tr from-neon-600 to-emerald-400 text-slate-950 font-black flex items-center justify-center text-xs flex-shrink-0 shadow-sm dark:shadow-glow-neon-sm">
                    ${escapeHtml(modelName.slice(0, 2).toUpperCase())}
                </div>
                <div class="p-4 rounded-2xl bg-slate-100/80 dark:bg-[#111827] border border-slate-200/80 dark:border-slate-800 text-xs text-slate-800 dark:text-slate-100 leading-relaxed max-w-2xl w-full markdown-body">
                    <div class="text-[10px] font-bold text-neon-700 dark:text-neon-400 font-mono mb-2">${escapeHtml(modelName)}</div>
                    <p>Chat session cleared. How can I assist your AI engineering workload today?</p>
                </div>
            </div>
        `;
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
