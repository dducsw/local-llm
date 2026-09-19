// ==============================================================================
// API KEY MANAGEMENT
// ==============================================================================

function formatKeyExpiration(expiresAt, isExpired) {
    if (!expiresAt || expiresAt === 0) {
        return '<span class="text-slate-400 font-semibold">Permanent</span>';
    }
    const now = Math.floor(Date.now() / 1000);
    if (isExpired || expiresAt < now) {
        return '<span class="text-rose-500 font-bold bg-rose-50 dark:bg-rose-950/50 px-1.5 py-0.5 rounded border border-rose-200 dark:border-rose-800/40 text-[10px]">Expired</span>';
    }
    const diffHours = Math.round((expiresAt - now) / 3600);
    if (diffHours < 24) {
        return `<span class="text-amber-600 dark:text-amber-400 font-bold text-[10px]">${diffHours}h left</span>`;
    }
    const diffDays = Math.round(diffHours / 24);
    return `<span class="text-emerald-600 dark:text-emerald-400 font-semibold text-[10px]">${diffDays}d left</span>`;
}

let currentLoadedKeys = [];

async function fetchApiKeys() {
    try {
        const res = await fetch(`${GATEWAY_BASE}/admin/keys`, {
            headers: getAdminHeaders()
        });
        if (res.status === 401) {
            console.warn('Authentication required or session expired for API keys.');
            return;
        }
        if (!res.ok) {
            const errData = await res.json().catch(() => ({}));
            console.debug('Failed to fetch API keys status:', res.status, errData);
            return;
        }
        const data = await res.json();
        const tbody = document.getElementById('page-keys-table-body') || document.getElementById('keys-table-body');
        const keys = data.data || [];
        currentLoadedKeys = keys;

        // Update KPI Summary Counters
        const totalElem = document.getElementById('keys-stat-total');
        const activeElem = document.getElementById('keys-stat-active');
        const prefixElem = document.getElementById('keys-active-prefix-banner');
        if (totalElem) totalElem.innerText = keys.length;
        if (activeElem) activeElem.innerText = keys.filter(k => k.enabled && !k.is_expired).length;
        if (prefixElem) {
            const currentKey = localStorage.getItem('hpc_active_api_key') || localStorage.getItem('hpc_llm_api_key') || 'sk-hpc-auto...';
            prefixElem.innerText = currentKey.length > 16 ? currentKey.substring(0, 16) + '...' : currentKey;
        }

        if (!tbody) return;

        if (keys.length === 0) {
            tbody.innerHTML = `
                <tr>
                    <td colspan="7" class="text-center py-6 text-slate-400 font-medium">
                        No API Keys created yet.
                    </td>
                </tr>
            `;
            return;
        }

        const userIsAdmin = typeof isAdmin === 'function' ? isAdmin() : true;

        tbody.innerHTML = keys.map(k => `
            <tr class="hover:bg-slate-50/50 dark:hover:bg-[#111827]/40 transition-colors border-b border-slate-100 dark:border-slate-800/60 font-mono text-[11px]">
                <td class="px-3 py-2.5 text-slate-500 font-bold">${k.prefix}...</td>
                <td class="px-3 py-2.5 font-bold text-slate-900 dark:text-slate-100">${escapeHtml(k.name)}</td>
                <td class="px-3 py-2.5 text-slate-600 dark:text-slate-300">
                    <span class="px-2 py-0.5 rounded bg-slate-100 dark:bg-slate-800 border border-slate-200 dark:border-slate-700 text-[10px]">
                        ${k.allowed_models.includes('*') ? 'All Models (*)' : k.allowed_models.join(', ')}
                    </span>
                </td>
                <td class="px-3 py-2.5 text-slate-600 dark:text-slate-300 font-semibold">${k.rpm} RPM</td>
                <td class="px-3 py-2.5">${formatKeyExpiration(k.expires_at, k.is_expired)}</td>
                <td class="px-3 py-2.5">
                    ${userIsAdmin ? `
                    <button onclick="toggleApiKeyAction(${k.id})"
                        class="px-2 py-0.5 rounded-md font-semibold text-[10px] cursor-pointer transition-all ${k.enabled && !k.is_expired ? 'bg-emerald-50 dark:bg-emerald-950/50 text-emerald-600 dark:text-emerald-400 border border-emerald-200 dark:border-emerald-800/40 hover:bg-emerald-100' : 'bg-slate-100 dark:bg-slate-800 text-slate-400 border border-slate-200 dark:border-slate-700 hover:bg-slate-200'}">
                        ${k.enabled && !k.is_expired ? '● Active' : (k.is_expired ? '✕ Expired' : '○ Disabled')}
                    </button>
                    ` : `
                    <span class="px-2 py-0.5 rounded-md font-semibold text-[10px] ${k.enabled && !k.is_expired ? 'bg-emerald-50 dark:bg-emerald-950/50 text-emerald-600 dark:text-emerald-400 border border-emerald-200 dark:border-emerald-800/40' : 'bg-slate-100 dark:bg-slate-800 text-slate-400 border border-slate-200 dark:border-slate-700'}">
                        ${k.enabled && !k.is_expired ? '● Active' : (k.is_expired ? '✕ Expired' : '○ Disabled')}
                    </span>
                    `}
                </td>
                <td class="px-3 py-2.5 text-right space-x-1 whitespace-nowrap">
                    <button onclick="openViewKeyModalById(${k.id})" title="View API Key Info & Code Snippets"
                        class="px-2 py-1 rounded bg-slate-100 dark:bg-slate-800 hover:bg-slate-200 dark:hover:bg-slate-700 text-slate-700 dark:text-slate-300 font-bold border border-slate-200 dark:border-slate-700 transition-all text-[10px]">
                        View
                    </button>
                    ${userIsAdmin ? `
                    <button onclick="revokeApiKeyAction(${k.id})" title="Revoke & Delete Key"
                        class="px-2 py-1 rounded bg-rose-50 dark:bg-rose-950/40 hover:bg-rose-100 dark:hover:bg-rose-900/60 text-rose-600 dark:text-rose-300 font-bold border border-rose-200 dark:border-rose-800/40 transition-all text-[10px]">
                        Revoke
                    </button>
                    ` : ''}
                </td>
            </tr>
        `).join('');
        if (window.lucide) lucide.createIcons();
    } catch (err) {
        console.debug('Failed to fetch API keys:', err);
    }
}

function openViewKeyModalById(keyId) {
    const keyObj = currentLoadedKeys.find(k => k.id === keyId);
    if (!keyObj) return;

    const modal = document.getElementById('modal-view-key');
    const clientSpan = document.getElementById('modal-key-client');
    const modelsSpan = document.getElementById('modal-key-models');
    const rpmSpan = document.getElementById('modal-key-rpm');
    const expiresSpan = document.getElementById('modal-key-expires');
    const curlPre = document.getElementById('modal-key-curl');

    if (clientSpan) clientSpan.innerText = `${keyObj.name || '--'} (${keyObj.created_by || 'admin'})`;
    if (modelsSpan) {
        modelsSpan.innerText = keyObj.allowed_models.includes('*') ? 'All Models (*)' : keyObj.allowed_models.join(', ');
    }
    if (rpmSpan) rpmSpan.innerText = `${keyObj.rpm} RPM`;
    if (expiresSpan) {
        expiresSpan.innerHTML = formatKeyExpiration(keyObj.expires_at, keyObj.is_expired);
    }

    const hostBase = window.location.origin;
    const modelToUse = keyObj.allowed_models.includes('*') ? ((typeof availableModels !== 'undefined' && availableModels[0]?.id) || 'default') : keyObj.allowed_models[0];

    if (curlPre) {
        curlPre.innerText = `curl -N -X POST ${hostBase}/v1/chat/completions \\
  -H "Authorization: Bearer <YOUR_API_KEY>" \\
  -H "Content-Type: application/json" \\
  -d '{
    "model": "${modelToUse}",
    "messages": [{"role": "user", "content": "Hello!"}],
    "stream": true
  }'`;
    }

    if (modal) modal.classList.remove('hidden');
    if (window.lucide) lucide.createIcons();
}

function closeViewKeyModal() {
    const modal = document.getElementById('modal-view-key');
    if (modal) modal.classList.add('hidden');
}

function openCreateKeyModal() {
    if (typeof isAdmin === 'function' && !isAdmin()) {
        showToast('Administrator privileges required to create keys', 'warning');
        return;
    }
    const modal = document.getElementById('modal-create-key');
    if (modal) modal.classList.remove('hidden');
}

function closeCreateKeyModal() {
    const modal = document.getElementById('modal-create-key');
    if (modal) modal.classList.add('hidden');
}

async function generateApiKeyAction() {
    if (typeof isAdmin === 'function' && !isAdmin()) {
        showToast('Administrator privileges required to create keys', 'warning');
        return;
    }

    const name = document.getElementById('new-key-name').value.trim();
    const rpm = parseInt(document.getElementById('new-key-rpm').value, 10) || 60;
    const duration = document.getElementById('new-key-duration')?.value || 'never';
    const allowed = document.getElementById('new-key-models').value.trim();
    const allowedModels = allowed ? allowed.split(',').map(s => s.trim()) : ['*'];

    if (!name) {
        showToast('Please enter an API Key description name', 'warning');
        return;
    }

    try {
        const res = await fetch(`${GATEWAY_BASE}/admin/keys`, {
            method: 'POST',
            headers: getAdminHeaders({ 'Content-Type': 'application/json' }),
            body: JSON.stringify({ name, rpm, allowed_models: allowedModels, duration })
        });
        const data = await res.json();

        if (res.ok) {
            closeCreateKeyModal();
            fetchApiKeys();
            showKeyCreatedModal(data.api_key);
        } else {
            const errMsg = data.detail ? (typeof data.detail === 'string' ? data.detail : (data.detail.error?.message || JSON.stringify(data.detail))) : (data.error?.message || 'Failed to create API key');
            showToast(errMsg, 'error');
        }
    } catch (err) {
        showToast('Network error creating API key', 'error');
    }
}

function showKeyCreatedModal(rawKey) {
    const modal = document.getElementById('modal-key-display');
    const keyBox = document.getElementById('generated-key-box');
    if (keyBox) keyBox.value = rawKey;
    if (modal) modal.classList.remove('hidden');
}

function closeKeyDisplayModal() {
    const modal = document.getElementById('modal-key-display');
    if (modal) modal.classList.add('hidden');
}

async function revokeApiKeyAction(keyId) {
    if (typeof isAdmin === 'function' && !isAdmin()) {
        showToast('Administrator privileges required to revoke keys', 'warning');
        return;
    }

    if (!confirm('Are you sure you want to revoke this API Key? Client applications using this key will immediately lose access.')) {
        return;
    }
    try {
        const res = await fetch(`${GATEWAY_BASE}/admin/keys/${keyId}`, {
            method: 'DELETE',
            headers: getAdminHeaders()
        });
        if (res.ok) {
            showToast('API Key revoked and removed from registry', 'success');
            fetchApiKeys();
        } else {
            showToast('Failed to revoke API key', 'error');
        }
    } catch (err) {
        showToast('Network error revoking key', 'error');
    }
}

async function toggleApiKeyAction(keyId) {
    if (typeof isAdmin === 'function' && !isAdmin()) {
        showToast('Administrator privileges required to modify keys', 'warning');
        return;
    }

    try {
        const res = await fetch(`${GATEWAY_BASE}/admin/keys/${keyId}/toggle`, {
            method: 'POST',
            headers: getAdminHeaders()
        });
        if (res.ok) {
            const data = await res.json();
            showToast(`API Key is now ${data.enabled ? 'Active' : 'Disabled'}`, 'info');
            fetchApiKeys();
        } else {
            showToast('Failed to toggle API key status', 'error');
        }
    } catch (err) {
        showToast('Network error toggling key status', 'error');
    }
}

// ==============================================================================
// PAGE IN-LINE KEY ACTIONS
// ==============================================================================
function fetchKeysManagement() {
    fetchApiKeys();
    showToast('API Keys registry refreshed', 'info');
}

async function createKeyFromPage() {
    if (typeof isAdmin === 'function' && !isAdmin()) {
        showToast('Administrator privileges required to create keys', 'warning');
        return;
    }

    const name = document.getElementById('page-key-name')?.value.trim();
    const rpm = parseInt(document.getElementById('page-key-rpm')?.value, 10) || 60;
    const model = document.getElementById('page-key-model')?.value || '*';
    const duration = document.getElementById('page-key-duration')?.value || 'never';
    const allowedModels = model === '*' ? ['*'] : [model];

    if (!name) {
        showToast('Please enter an Application / Client name', 'warning');
        return;
    }

    try {
        const res = await fetch(`${GATEWAY_BASE}/admin/keys`, {
            method: 'POST',
            headers: getAdminHeaders({ 'Content-Type': 'application/json' }),
            body: JSON.stringify({ name, rpm, allowed_models: allowedModels, duration })
        });
        const data = await res.json();

        if (res.ok && data.api_key) {
            const banner = document.getElementById('page-issued-key-banner');
            const valBox = document.getElementById('page-issued-key-val');
            if (valBox) valBox.innerText = data.api_key;
            if (banner) banner.classList.remove('hidden');

            showToast('API Key generated successfully!', 'success');
            fetchApiKeys();
            if (window.lucide) lucide.createIcons();
        } else {
            const errMsg = data.detail ? (typeof data.detail === 'string' ? data.detail : (data.detail.error?.message || JSON.stringify(data.detail))) : (data.error?.message || 'Failed to generate key');
            showToast(errMsg, 'error');
        }
    } catch (err) {
        showToast('Network error generating key', 'error');
    }
}

function copyGeneratedKey() {
    const valBox = document.getElementById('page-issued-key-val');
    const key = valBox ? valBox.innerText.trim() : '';
    if (!key) {
        showToast('No key to copy', 'error');
        return;
    }
    copyToClipboard(key, 'Secret API Key copied to clipboard!');
}

function usePageIssuedKey() {
    const valBox = document.getElementById('page-issued-key-val');
    const key = valBox ? valBox.innerText.trim() : '';
    if (!key) {
        showToast('No key to apply', 'error');
        return;
    }
    localStorage.setItem('hpc_active_api_key', key);
    localStorage.setItem('hpc_llm_api_key', key);
    activeApiKey = key;
    showToast('Applied new API Key to current session', 'success');
}
