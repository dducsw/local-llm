// ==============================================================================
// ROLE-BASED ACCESS CONTROL (RBAC)
// 2-Role System: Admin (full CRUD & Slurm) and Viewer (Read-only + Chat)
// ==============================================================================

function getCurrentRole() {
    return localStorage.getItem('hpc_user_role') || sessionStorage.getItem('hpc_user_role') || 'viewer';
}

function isAdmin() {
    return getCurrentRole() === 'admin';
}

function isViewer() {
    return getCurrentRole() === 'viewer';
}

function applyRolePermissions(role) {
    const currentRole = (role || getCurrentRole()).toLowerCase();
    
    // Store role in active storage
    if (localStorage.getItem('hpc_admin_session')) {
        localStorage.setItem('hpc_user_role', currentRole);
    } else {
        sessionStorage.setItem('hpc_user_role', currentRole);
    }

    // 1. Update Navbar Role Badge
    const roleBadge = document.getElementById('navbar-role-badge');
    const roleBadgeText = document.getElementById('navbar-role-text');
    const userInitial = document.getElementById('navbar-user-initial');
    const username = localStorage.getItem('hpc_admin_username') || sessionStorage.getItem('hpc_admin_username') || currentRole;

    if (userInitial && username) {
        userInitial.innerText = username.charAt(0).toUpperCase();
    }

    if (roleBadge) {
        if (currentRole === 'admin') {
            roleBadge.className = 'px-2.5 py-1 rounded-full text-[10px] font-mono font-bold uppercase tracking-wider bg-neon-500/20 text-neon-600 dark:text-neon-400 border border-neon-500/40 shadow-glow-neon-sm flex items-center gap-1.5 shrink-0';
            if (roleBadgeText) roleBadgeText.innerText = 'ADMIN';
        } else {
            roleBadge.className = 'px-2.5 py-1 rounded-full text-[10px] font-mono font-bold uppercase tracking-wider bg-amber-500/20 text-amber-600 dark:text-amber-400 border border-amber-500/40 flex items-center gap-1.5 shrink-0';
            if (roleBadgeText) roleBadgeText.innerText = 'VIEWER';
        }
    }

    // 2. Slurm Tab Access Control (Hidden entirely for Viewer)
    const slurmNavTabs = document.querySelectorAll('[data-nav-tab="slurm"]');
    slurmNavTabs.forEach(el => {
        if (currentRole === 'admin') {
            el.classList.remove('hidden');
        } else {
            el.classList.add('hidden');
        }
    });

    // If viewer is currently looking at slurm view, switch to telemetry
    const slurmView = document.getElementById('view-slurm');
    if (currentRole !== 'admin' && slurmView && !slurmView.classList.contains('hidden')) {
        switchTab('telemetry');
    }

    // 3. Admin-only UI Elements (Buttons, Forms, Modals)
    const adminElements = document.querySelectorAll('[data-admin-only="true"]');
    adminElements.forEach(el => {
        if (currentRole === 'admin') {
            el.classList.remove('hidden');
        } else {
            el.classList.add('hidden');
        }
    });

    // 4. Adjust Keys Table layout (expand to full width when form is hidden for viewer)
    const keysTableCol = document.getElementById('keys-table-column');
    if (keysTableCol) {
        if (currentRole === 'admin') {
            keysTableCol.className = 'lg:col-span-7 space-y-4';
        } else {
            keysTableCol.className = 'lg:col-span-12 space-y-4';
        }
    }

    // 5. Viewer Banner Notices
    const viewerNotice = document.getElementById('viewer-readonly-notice');
    if (viewerNotice) {
        if (currentRole === 'viewer') {
            viewerNotice.classList.remove('hidden');
        } else {
            viewerNotice.classList.add('hidden');
        }
    }

    if (window.lucide) lucide.createIcons();
}
