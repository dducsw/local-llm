// ==============================================================================
// API KEY MANAGEMENT
// ==============================================================================

async function fetchApiKeys() {
    try {
        const res = await fetch(`${GATEWAY_BASE}/admin/keys`, {
            headers: getAdminHeaders()
        });
        if (!res.ok) return;
        const data = await res.json();
        const tbody = document.getElementById('keys-table-body');
        if (!tbody) return;

        const keys = data.data || [];
        if (keys.length === 0) {
            tbody.innerHTML = `
                <tr>
                    <td colspan="7" class="text-center py-6 text-slate-400 font-medium">
                        No API Keys created yet. Click "Generate API Key" to create one.
                    </td>
                </tr>
            `;
            return;
        }

        tbody.innerHTML = keys.map(k => `
            <tr class="hover:bg-slate-50/50 dark:hover:bg-[#111827]/40 transition-colors border-b border-slate-100 dark:border-slate-800/60 font-mono text-[11px]">
                <td class="px-4 py-2.5 font-bold text-slate-900 dark:text-slate-100">${k.name}</td>
                <td class="px-4 py-2.5 text-slate-500">${k.prefix}...</td>
                <td class="px-4 py-2.5 text-slate-600 dark:text-slate-300">${k.allowed_models.join(', ')}</td>
                <td class="px-4 py-2.5 text-slate-600 dark:text-slate-300">${k.rpm} req/m</td>
                <td class="px-4 py-2.5">
                    <span class="px-2 py-0.5 rounded-md font-semibold text-[10px] ${k.enabled ? 'bg-emerald-50 dark:bg-emerald-950/50 text-emerald-600 dark:text-emerald-400 border border-emerald-200 dark:border-emerald-800/40' : 'bg-slate-100 dark:bg-slate-800 text-slate-400'}">
                        ${k.enabled ? 'Active' : 'Revoked'}
                    </span>
                </td>
                <td class="px-4 py-2.5 text-slate-400">${new Date(k.created_at * 1000).toLocaleDateString()}</td>
                <td class="px-4 py-2.5 text-right">
                    ${k.enabled ? `
                        <button onclick="revokeApiKeyAction(${k.id})"
                            class="px-2 py-1 rounded bg-rose-50 dark:bg-rose-950/40 hover:bg-rose-100 dark:hover:bg-rose-900/60 text-rose-600 dark:text-rose-300 font-bold border border-rose-200 dark:border-rose-800/40 transition-all">
                            Revoke
                        </button>
                    ` : '<span class="text-slate-400 text-[10px]">Disabled</span>'}
                </td>
            </tr>
        `).join('');
    } catch (err) {
        console.debug('Failed to fetch API keys:', err);
    }
}

function openCreateKeyModal() {
    const modal = document.getElementById('modal-create-key');
    if (modal) modal.classList.remove('hidden');
}

function closeCreateKeyModal() {
    const modal = document.getElementById('modal-create-key');
    if (modal) modal.classList.add('hidden');
}

async function generateApiKeyAction() {
    const name = document.getElementById('new-key-name').value.trim();
    const rpm = parseInt(document.getElementById('new-key-rpm').value, 10) || 60;
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
            body: JSON.stringify({ name, rpm, allowed_models: allowedModels })
        });
        const data = await res.json();

        if (res.ok) {
            closeCreateKeyModal();
            fetchApiKeys();
            showKeyCreatedModal(data.api_key);
        } else {
            showToast(data.detail || 'Failed to create API key', 'error');
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
    if (!confirm('Are you sure you want to revoke this API Key? Client applications using this key will immediately lose access.')) {
        return;
    }
    try {
        const res = await fetch(`${GATEWAY_BASE}/admin/keys/${keyId}`, {
            method: 'DELETE',
            headers: getAdminHeaders()
        });
        if (res.ok) {
            showToast('API Key revoked successfully', 'success');
            fetchApiKeys();
        } else {
            showToast('Failed to revoke API key', 'error');
        }
    } catch (err) {
        showToast('Network error revoking key', 'error');
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
    const name = document.getElementById('page-key-name')?.value.trim();
    const rpm = parseInt(document.getElementById('page-key-rpm')?.value, 10) || 60;
    const model = document.getElementById('page-key-model')?.value || '*';
    const allowedModels = model === '*' ? ['*'] : [model];

    if (!name) {
        showToast('Please enter an Application / Client name', 'warning');
        return;
    }

    try {
        const res = await fetch(`${GATEWAY_BASE}/admin/keys`, {
            method: 'POST',
            headers: getAdminHeaders({ 'Content-Type': 'application/json' }),
            body: JSON.stringify({ name, rpm, allowed_models: allowedModels })
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
            showToast(data.detail || 'Failed to generate key', 'error');
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
