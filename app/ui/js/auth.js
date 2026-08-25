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
                    showMainDashboard(data.username || 'admin');
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

function showMainDashboard(username) {
    const loginScreen = document.getElementById('login-screen-view');
    const mainDashboard = document.getElementById('main-dashboard-view');
    const adminUserBadge = document.getElementById('navbar-admin-user');

    if (loginScreen) loginScreen.classList.add('hidden');
    if (mainDashboard) mainDashboard.classList.remove('hidden');
    if (adminUserBadge) adminUserBadge.innerText = username || 'Admin';

    startBackgroundSync();
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
            if (remember) {
                localStorage.setItem('hpc_admin_session', data.token);
                localStorage.setItem('hpc_admin_username', data.username);
            } else {
                sessionStorage.setItem('hpc_admin_session', data.token);
                sessionStorage.setItem('hpc_admin_username', data.username);
            }
            adminToken = data.token;
            showToast(`Signed in successfully as ${data.username}`, 'success');
            showMainDashboard(data.username);
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
    sessionStorage.removeItem('hpc_admin_session');
    sessionStorage.removeItem('hpc_admin_username');
    adminToken = '';

    showToast('Signed out of admin session', 'info');
    showLoginScreen();
}

function startBackgroundSync() {
    stopBackgroundSync();
    // Auto-polling disabled per user request: manual refresh only
}

function stopBackgroundSync() {
    syncIntervals.forEach(id => clearInterval(id));
    syncIntervals = [];
}
