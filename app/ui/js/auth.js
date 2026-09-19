// ==============================================================================
// AUTHENTICATION & SESSION MANAGEMENT
// ==============================================================================

function getAdminHeaders(extraHeaders = {}) {
    const session = localStorage.getItem('hpc_admin_session') || sessionStorage.getItem('hpc_admin_session') || adminToken || '';
    return {
        'X-Admin-Session': session,
        'X-Admin-Token': session,
        'Authorization': `Bearer ${session}`,
        ...extraHeaders
    };
}

async function checkAdminAuth() {
    const session = localStorage.getItem('hpc_admin_session') || sessionStorage.getItem('hpc_admin_session');
    if (session) {
        try {
            const res = await fetch(`${GATEWAY_BASE}/api/auth/me`, {
                headers: {
                    'X-Admin-Session': session,
                    'Authorization': `Bearer ${session}`
                }
            });
            if (res.ok) {
                const data = await res.json();
                if (data.authenticated) {
                    if (data.username) {
                        if (localStorage.getItem('hpc_admin_session')) {
                            localStorage.setItem('hpc_admin_username', data.username);
                        } else {
                            sessionStorage.setItem('hpc_admin_username', data.username);
                        }
                    }
                    try {
                        document.cookie = `hpc_admin_session=${encodeURIComponent(session)}; path=/; max-age=604800; SameSite=Lax`;
                    } catch (e) {}
                    showMainDashboard(data.username || 'admin', data.role || 'viewer');
                    return true;
                }
            }
        } catch (err) {
            console.warn('Auth verification check failed:', err);
        }
    }
    showLoginScreen();
    return false;
}

function showMainDashboard(username, role) {
    const loginScreen = document.getElementById('login-screen-view');
    const mainDashboard = document.getElementById('main-dashboard-view');
    const adminUserBadge = document.getElementById('navbar-admin-user');

    if (loginScreen) loginScreen.classList.add('hidden');
    if (mainDashboard) mainDashboard.classList.remove('hidden');
    if (adminUserBadge) adminUserBadge.innerText = username || 'User';

    // Apply role-based permissions immediately
    if (typeof applyRolePermissions === 'function') {
        applyRolePermissions(role);
    }

    startBackgroundSync();
    if (typeof fetchApiKeys === 'function') fetchApiKeys();
    if (typeof fetchAvailableModels === 'function') fetchAvailableModels();
    switchTab('telemetry');
}

function showLoginScreen() {
    const loginScreen = document.getElementById('login-screen-view');
    const mainDashboard = document.getElementById('main-dashboard-view');

    stopBackgroundSync();
    if (mainDashboard) mainDashboard.classList.add('hidden');
    if (loginScreen) loginScreen.classList.remove('hidden');
    if (window.lucide) lucide.createIcons();
}

async function performScreenLogin() {
    const user = document.getElementById('screen-login-user').value.trim();
    const pass = document.getElementById('screen-login-pass').value.trim();
    const remember = document.getElementById('remember-session').checked;
    const btn = document.getElementById('btn-login-submit');
    const btnText = document.getElementById('btn-login-text');
    const errBanner = document.getElementById('login-error-banner');
    const errText = document.getElementById('login-error-text');

    if (!user || !pass) {
        if (errBanner) {
            errText.innerText = 'Please enter both username and password';
            errBanner.classList.remove('hidden');
        }
        return;
    }

    if (btn) btn.disabled = true;
    if (btnText) btnText.innerText = 'Verifying Credentials...';
    if (errBanner) errBanner.classList.add('hidden');

    try {
        const res = await fetch(`${GATEWAY_BASE}/api/auth/login`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ username: user, password: pass })
        });
        const data = await res.json();

        if (res.ok && data.status === 'ok') {
            const role = data.role || 'viewer';
            if (remember) {
                localStorage.setItem('hpc_admin_session', data.token);
                localStorage.setItem('hpc_admin_username', data.username);
                localStorage.setItem('hpc_user_role', role);
            } else {
                sessionStorage.setItem('hpc_admin_session', data.token);
                sessionStorage.setItem('hpc_admin_username', data.username);
                sessionStorage.setItem('hpc_user_role', role);
            }
            adminToken = data.token;
            try {
                document.cookie = `hpc_admin_session=${encodeURIComponent(data.token)}; path=/; max-age=604800; SameSite=Lax`;
            } catch (e) {}
            showToast(`Signed in as ${data.username} (${role.toUpperCase()})`, 'success');
            showMainDashboard(data.username, role);
        } else {
            if (errBanner) {
                errText.innerText = data.detail || 'Invalid username or password';
                errBanner.classList.remove('hidden');
            }
        }
    } catch (err) {
        if (errBanner) {
            errText.innerText = 'Network error connecting to Gateway API';
            errBanner.classList.remove('hidden');
        }
    } finally {
        if (btn) btn.disabled = false;
        if (btnText) btnText.innerText = 'Sign In to Dashboard';
        if (window.lucide) lucide.createIcons();
    }
}

async function performLogout() {
    try {
        await fetch(`${GATEWAY_BASE}/api/auth/logout`, {
            method: 'POST',
            headers: getAdminHeaders()
        });
    } catch (err) {
        // Ignore network errors on logout
    }

    localStorage.removeItem('hpc_admin_session');
    localStorage.removeItem('hpc_admin_username');
    localStorage.removeItem('hpc_user_role');
    sessionStorage.removeItem('hpc_admin_session');
    sessionStorage.removeItem('hpc_admin_username');
    sessionStorage.removeItem('hpc_user_role');
    adminToken = '';
    try {
        document.cookie = 'hpc_admin_session=; path=/; max-age=0; SameSite=Lax';
    } catch (e) {}

    showToast('Signed out of session', 'info');
    showLoginScreen();
}

function startBackgroundSync() {
    stopBackgroundSync();
}

function stopBackgroundSync() {
    syncIntervals.forEach(id => clearInterval(id));
    syncIntervals = [];
}
