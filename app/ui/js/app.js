// ==============================================================================
// 1. GLOBAL STATE & CONFIGURATION
// ==============================================================================
const GATEWAY_BASE = window.location.port === '9000' || window.location.port === '8000'
    ? `${window.location.protocol}//${window.location.hostname}:${window.location.port}`
    : `${window.location.protocol}//${window.location.host}`;

let activeApiKey = localStorage.getItem('hpc_active_api_key') || localStorage.getItem('hpc_llm_api_key') || 'sk-hpc-demo';
let adminToken = '';
let syncIntervals = [];

// ==============================================================================
// 2. THEME & UI HELPERS
// ==============================================================================
function toggleTheme() {
    const isDark = document.documentElement.classList.contains('dark');
    if (isDark) {
        document.documentElement.classList.remove('dark');
        localStorage.setItem('hpc_theme', 'light');
    } else {
        document.documentElement.classList.add('dark');
        localStorage.setItem('hpc_theme', 'dark');
    }
    updateThemeIcons();
    if (typeof updateChartColors === 'function') {
        updateChartColors();
    }
}

function updateThemeIcons() {
    const isDark = document.documentElement.classList.contains('dark');
    const navIcon = document.getElementById('theme-toggle-icon');
    const loginIcon = document.getElementById('login-theme-icon');
    
    if (navIcon) {
        navIcon.setAttribute('data-lucide', isDark ? 'sun' : 'moon');
    }
    if (loginIcon) {
        loginIcon.setAttribute('data-lucide', isDark ? 'sun' : 'moon');
    }
    if (window.lucide) {
        lucide.createIcons();
    }
}

function togglePasswordVisibility() {
    const passInput = document.getElementById('screen-login-pass');
    const eyeIcon = document.getElementById('eye-icon');
    if (passInput) {
        const isPassword = passInput.type === 'password';
        passInput.type = isPassword ? 'text' : 'password';
        if (eyeIcon) {
            eyeIcon.setAttribute('data-lucide', isPassword ? 'eye-off' : 'eye');
            if (window.lucide) lucide.createIcons();
        }
    }
}

function toggleSettingsMenu(event) {
    if (event) event.stopPropagation();
    const menu = document.getElementById('settings-dropdown-menu');
    if (menu) {
        menu.classList.toggle('hidden');
        if (window.lucide) lucide.createIcons();
    }
}

function toggleModelDropdown(event) {
    if (event) event.stopPropagation();
    const menu = document.getElementById('global-model-dropdown-menu');
    const chevron = document.getElementById('model-dropdown-chevron');
    if (menu) {
        menu.classList.toggle('hidden');
        if (chevron) chevron.classList.toggle('rotate-180');
        if (window.lucide) lucide.createIcons();
    }
}

function selectGlobalModel(modelId) {
    if (!modelId) return;
    currentSelectedModel = modelId;

    const label = document.getElementById('global-model-selected-label');
    const metricName = document.getElementById('metric-model-name');
    const playSelect = document.getElementById('play-model-select');
    const chatSelect = document.getElementById('chat-model-select');

    if (label) label.innerText = modelId;
    if (metricName) metricName.innerText = modelId;
    if (playSelect) playSelect.value = modelId;
    if (chatSelect) chatSelect.value = modelId;

    if (typeof updateChatModelDisplay === 'function') updateChatModelDisplay(modelId);
    if (typeof onGlobalModelFilterChange === 'function') onGlobalModelFilterChange(modelId);

    const menu = document.getElementById('global-model-dropdown-menu');
    const chevron = document.getElementById('model-dropdown-chevron');
    if (menu) menu.classList.add('hidden');
    if (chevron) chevron.classList.remove('rotate-180');

    // Highlight active model in dropdown list
    const items = document.querySelectorAll('#global-model-items-list > div');
    items.forEach(el => {
        if (el.getAttribute('data-model-id') === modelId) {
            el.classList.add('bg-neon-500/10', 'border-neon-500/30');
        } else {
            el.classList.remove('bg-neon-500/10', 'border-neon-500/30');
        }
    });

    showToast(`Target model set to ${modelId}`, 'info');
}

function toggleSystemPrompt() {
    const el = document.getElementById('play-system-prompt');
    if (el) el.classList.toggle('hidden');
}

function setPresetPrompt(text) {
    const promptInput = document.getElementById('play-prompt');
    if (promptInput) {
        promptInput.value = text;
        promptInput.focus();
        showToast('Preset prompt loaded', 'info');
    }
}

// Close dropdowns when clicking outside
document.addEventListener('click', function (e) {
    const settingsWrapper = document.getElementById('header-settings-dropdown-wrapper');
    const settingsMenu = document.getElementById('settings-dropdown-menu');
    if (settingsMenu && !settingsMenu.classList.contains('hidden') && settingsWrapper && !settingsWrapper.contains(e.target)) {
        settingsMenu.classList.add('hidden');
    }

    const modelWrapper = document.getElementById('global-model-dropdown-wrapper');
    const modelMenu = document.getElementById('global-model-dropdown-menu');
    const chevron = document.getElementById('model-dropdown-chevron');
    if (modelMenu && !modelMenu.classList.contains('hidden') && modelWrapper && !modelWrapper.contains(e.target)) {
        modelMenu.classList.add('hidden');
        if (chevron) chevron.classList.remove('rotate-180');
    }
});

// ==============================================================================
// 3. TOAST NOTIFICATION SYSTEM
// ==============================================================================
function showToast(message, type = 'info') {
    const container = document.getElementById('toast-container');
    if (!container) return;

    const toast = document.createElement('div');
    const id = 'toast-' + Date.now();
    toast.id = id;

    const colors = {
        success: 'bg-emerald-500 text-slate-950 shadow-emerald-500/30',
        error: 'bg-rose-500 text-white shadow-rose-500/30',
        warning: 'bg-amber-400 text-slate-950 shadow-amber-400/30',
        info: 'bg-slate-900 dark:bg-slate-100 text-white dark:text-slate-900 shadow-slate-900/30'
    };

    const icons = {
        success: 'check-circle-2',
        error: 'alert-circle',
        warning: 'alert-triangle',
        info: 'info'
    };

    toast.className = `flex items-center gap-2.5 px-4 py-3 rounded-xl font-bold text-xs shadow-lg transition-all duration-300 transform translate-y-2 opacity-0 ${colors[type] || colors.info}`;
    toast.innerHTML = `
        <i data-lucide="${icons[type] || 'info'}" class="w-4 h-4 shrink-0"></i>
        <span>${message}</span>
    `;

    container.appendChild(toast);
    if (window.lucide) lucide.createIcons();

    setTimeout(() => {
        toast.classList.remove('translate-y-2', 'opacity-0');
    }, 10);

    setTimeout(() => {
        toast.classList.add('opacity-0', 'translate-x-full');
        setTimeout(() => toast.remove(), 300);
    }, 3500);
}

// ==============================================================================
// 4. TAB NAVIGATION & MANUAL REFRESH CONTROLLER
// ==============================================================================
function switchNavTab(tabName) {
    switchTab(tabName);
}

function switchTab(tabName) {
    const validTabs = ['telemetry', 'slurm', 'chatbot', 'keys', 'settings'];
    const activeName = tabName === 'playground' ? 'chatbot' : tabName;

    validTabs.forEach(t => {
        const view = document.getElementById(`view-${t}`);
        if (view) {
            if (t === activeName) {
                view.classList.remove('hidden');
            } else {
                view.classList.add('hidden');
            }
        }
    });

    // Update styling for all nav buttons (both desktop and mobile)
    document.querySelectorAll('[data-nav-tab]').forEach(btn => {
        const btnTab = btn.getAttribute('data-nav-tab');
        if (btnTab === activeName) {
            btn.className = 'px-3.5 py-1.5 rounded-lg bg-white dark:bg-neon-500 text-neon-800 dark:text-slate-950 font-black shadow-sm dark:shadow-glow-neon-sm transition-all flex items-center gap-2 whitespace-nowrap shrink-0';
        } else {
            btn.className = 'px-3.5 py-1.5 rounded-lg text-slate-600 dark:text-slate-400 hover:text-slate-900 dark:hover:text-white transition-all flex items-center gap-2 whitespace-nowrap shrink-0';
        }
    });

    if (window.lucide) lucide.createIcons();

    // Trigger tab-specific refresh routines (Manual on click)
    if (activeName === 'telemetry') {
        if (typeof fetchRealtimeMetrics === 'function') fetchRealtimeMetrics();
        if (typeof fetchTimeseriesMetrics === 'function') fetchTimeseriesMetrics();
        if (typeof fetchMetricsLogs === 'function') fetchMetricsLogs();
        if (typeof fetchAvailableModels === 'function') fetchAvailableModels();
    } else if (activeName === 'slurm') {
        if (typeof fetchSlurmNodes === 'function') fetchSlurmNodes();
        if (typeof fetchSlurmJobs === 'function') fetchSlurmJobs();
        if (typeof fetchTunnelTelemetry === 'function') fetchTunnelTelemetry();
    } else if (activeName === 'chatbot') {
        if (typeof fetchAvailableModels === 'function') fetchAvailableModels();
    } else if (activeName === 'keys') {
        if (typeof fetchApiKeys === 'function') fetchApiKeys();
        if (typeof fetchAvailableModels === 'function') fetchAvailableModels();
    }
}

function refreshDashboardTelemetry() {
    if (typeof fetchRealtimeMetrics === 'function') fetchRealtimeMetrics();
    if (typeof fetchTimeseriesMetrics === 'function') fetchTimeseriesMetrics();
    if (typeof fetchMetricsLogs === 'function') fetchMetricsLogs();
    if (typeof fetchAvailableModels === 'function') fetchAvailableModels();
    showToast('Telemetry refreshed', 'success');
}

function manualRefreshDashboard() {
    const activeBtn = document.querySelector('[data-nav-tab].bg-white, [data-nav-tab].dark\\:bg-neon-500');
    const currentTab = activeBtn ? activeBtn.getAttribute('data-nav-tab') : 'telemetry';
    switchTab(currentTab || 'telemetry');
    showToast('Data refreshed', 'info');
}

// Copy to Clipboard utility
async function copyToClipboard(text, message = 'Copied to clipboard!') {
    try {
        await navigator.clipboard.writeText(text);
        showToast(message, 'success');
    } catch (err) {
        showToast('Failed to copy', 'error');
    }
}
