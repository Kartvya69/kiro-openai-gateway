// Kiro Gateway - Premium Dashboard UI
// Modern, refined JavaScript with smooth interactions

const API_BASE = '';

// State
let sessionToken = localStorage.getItem('sessionToken');
let authPollingInterval = null;

// DOM Elements
const loginPage = document.getElementById('login-page');
const appContainer = document.getElementById('app');
const dashboard = document.getElementById('dashboard');
const loginForm = document.getElementById('login-form');
const loginError = document.getElementById('login-error');
const logoutBtn = document.getElementById('logout-btn');
const addAccountBtn = document.getElementById('add-account-btn');
const accountsList = document.getElementById('accounts-list');
const modal = document.getElementById('modal');

// Mobile elements
const mobileMenuToggle = document.getElementById('mobile-menu-toggle');
const sidebar = document.getElementById('sidebar');
const sidebarOverlay = document.getElementById('sidebar-overlay');

// Stats elements
const statAccounts = document.getElementById('stat-accounts');
const statHealthy = document.getElementById('stat-healthy');
const statRequests = document.getElementById('stat-requests');
const accountCount = document.getElementById('account-count');

// Initialize
document.addEventListener('DOMContentLoaded', () => {
    if (sessionToken) {
        // Immediately show dashboard if we have a token (optimistic)
        showDashboardImmediate();
        // Then verify session in background
        checkSession();
    } else {
        showLogin();
    }
    
    // Event listeners
    loginForm?.addEventListener('submit', handleLogin);
    logoutBtn?.addEventListener('click', handleLogout);
    addAccountBtn?.addEventListener('click', showAddAccountModal);
    
    // Mobile menu toggle
    mobileMenuToggle?.addEventListener('click', toggleMobileMenu);
    sidebarOverlay?.addEventListener('click', closeMobileMenu);
    
    // Close mobile menu when nav item clicked
    document.querySelectorAll('.nav-item').forEach(item => {
        item.addEventListener('click', closeMobileMenu);
    });
    
    // Close modal on overlay click
    modal?.addEventListener('click', (e) => {
        if (e.target === modal) closeModal();
    });
    
    // Escape key closes modal
    document.addEventListener('keydown', (e) => {
        if (e.key === 'Escape') closeModal();
    });
});

// Mobile Menu Functions
function toggleMobileMenu() {
    const isOpen = sidebar?.classList.toggle('open');
    mobileMenuToggle?.classList.toggle('active', isOpen);
    sidebarOverlay?.classList.toggle('active', isOpen);
    document.body.style.overflow = isOpen ? 'hidden' : '';
}

function closeMobileMenu() {
    sidebar?.classList.remove('open');
    mobileMenuToggle?.classList.remove('active');
    sidebarOverlay?.classList.remove('active');
    document.body.style.overflow = '';
}

// API Helper
async function api(endpoint, options = {}) {
    const headers = {
        'Content-Type': 'application/json',
        ...options.headers,
    };
    
    if (sessionToken) {
        headers['X-Session-Token'] = sessionToken;
    }
    
    const response = await fetch(`${API_BASE}${endpoint}`, {
        ...options,
        headers,
    });
    
    if (response.status === 401) {
        localStorage.removeItem('sessionToken');
        sessionToken = null;
        showLogin();
        throw new Error('Session expired');
    }
    
    return response;
}

// Check if session is valid
async function checkSession() {
    try {
        const response = await api('/ui/accounts');
        if (response.ok) {
            // Session valid - load data (dashboard already shown)
            loadAccounts();
            loadStats();
            connectLogStream();
        } else {
            showLogin();
        }
    } catch (e) {
        showLogin();
    }
}

// Show/Hide Pages
function showLogin() {
    loginPage.style.display = 'flex';
    appContainer.classList.remove('active');
    dashboard.classList.remove('active');
    document.getElementById('secret-key')?.focus();
}

function showDashboardImmediate() {
    // Show dashboard immediately without loading data (optimistic UI)
    loginPage.style.display = 'none';
    appContainer.classList.add('active');
    dashboard.classList.add('active');
}

function showDashboard() {
    loginPage.style.display = 'none';
    appContainer.classList.add('active');
    dashboard.classList.add('active');
    loadAccounts();
    loadStats();
    connectLogStream();
    startCreditsAutoRefresh();
    startAccountsAutoRefresh();
    startTokenAutoRefresh();
}

// Login Handler
async function handleLogin(e) {
    e.preventDefault();
    
    const secretKey = document.getElementById('secret-key').value;
    const submitBtn = loginForm.querySelector('button[type="submit"]');
    
    loginError.textContent = '';
    submitBtn.disabled = true;
    submitBtn.innerHTML = '<span class="spinner" style="width:20px;height:20px;border-width:2px;"></span>';
    
    try {
        const response = await fetch(`${API_BASE}/ui/login`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ secret_key: secretKey }),
        });
        
        const data = await response.json();
        
        if (data.success) {
            sessionToken = data.session_token;
            localStorage.setItem('sessionToken', sessionToken);
            showDashboard();
        } else {
            loginError.textContent = data.message || 'Invalid secret key';
        }
    } catch (e) {
        loginError.textContent = 'Connection error. Please try again.';
    } finally {
        submitBtn.disabled = false;
        submitBtn.innerHTML = 'Sign In';
    }
}

// Logout Handler
async function handleLogout() {
    try {
        await api('/ui/logout', { method: 'POST' });
    } catch (e) {
        // Ignore errors
    }
    
    disconnectLogStream();
    stopCreditsAutoRefresh();
    stopAccountsAutoRefresh();
    stopTokenAutoRefresh();
    localStorage.removeItem('sessionToken');
    sessionToken = null;
    showLogin();
}

// Load Accounts
async function loadAccounts() {
    try {
        const response = await api('/ui/accounts');
        const data = await response.json();
        
        renderAccounts(data.accounts);
        if (accountCount) {
            accountCount.textContent = data.accounts.length;
        }
    } catch (e) {
        console.error('Failed to load accounts:', e);
    }
}

// Load Stats
async function loadStats() {
    try {
        const response = await api('/ui/stats');
        const data = await response.json();
        
        animateNumber(statAccounts, data.total_accounts);
        animateNumber(statHealthy, data.healthy_accounts);
        animateNumber(statRequests, data.total_requests);
    } catch (e) {
        console.error('Failed to load stats:', e);
    }
}

// Animate number counting
function animateNumber(element, target) {
    if (!element) return;
    
    const start = parseInt(element.textContent.replace(/,/g, '')) || 0;
    const duration = 500;
    const startTime = performance.now();
    
    function update(currentTime) {
        const elapsed = currentTime - startTime;
        const progress = Math.min(elapsed / duration, 1);
        const easeOut = 1 - Math.pow(1 - progress, 3);
        const current = Math.round(start + (target - start) * easeOut);
        element.textContent = formatNumber(current);
        
        if (progress < 1) {
            requestAnimationFrame(update);
        }
    }
    
    requestAnimationFrame(update);
}

// Format number with commas
function formatNumber(num) {
    return num.toString().replace(/\B(?=(\d{3})+(?!\d))/g, ',');
}

// Get provider icon
function getProviderIcon(provider, method) {
    const icons = {
        'Google': '🔵',
        'Github': '⚫',
        'AWS': '🟠',
        'builder-id': '🟠',
        'social': '🌐',
    };
    return icons[provider] || icons[method] || '🔑';
}

// Get status label
function getStatusLabel(status) {
    const labels = {
        'healthy': 'Active',
        'expiring_soon': 'Expiring Soon',
        'expired': 'Expired',
        'no_token': 'No Token',
        'inactive': 'Inactive',
    };
    return labels[status] || status;
}

// Render Accounts List (see enhanced version at bottom of file)

// Format relative time
function formatRelativeTime(isoString) {
    const date = new Date(isoString);
    const now = new Date();
    const diff = date - now;
    const hours = Math.floor(diff / (1000 * 60 * 60));
    const minutes = Math.floor((diff % (1000 * 60 * 60)) / (1000 * 60));
    
    if (diff < 0) return 'expired';
    if (hours > 24) return `in ${Math.floor(hours / 24)}d`;
    if (hours > 0) return `in ${hours}h`;
    if (minutes > 0) return `in ${minutes}m`;
    return 'soon';
}

// Escape HTML
function escapeHtml(text) {
    const div = document.createElement('div');
    div.textContent = text;
    return div.innerHTML;
}

// Delete Account
async function deleteAccount(accountId, accountName) {
    showModal('Remove Account', `
        <div class="result-state">
            <div class="icon">⚠️</div>
            <h3>Remove "${escapeHtml(accountName)}"?</h3>
            <p>This account will be removed from the gateway. You can add it again later.</p>
        </div>
    `, `
        <button class="btn btn-secondary" onclick="closeModal()">Cancel</button>
        <button class="btn btn-danger" onclick="confirmDeleteAccount(${accountId})">Remove Account</button>
    `);
}

async function confirmDeleteAccount(accountId) {
    const modalContent = document.getElementById('modal-content');
    modalContent.innerHTML = `
        <div class="loading">
            <div class="spinner"></div>
            <p>Removing account...</p>
        </div>
    `;
    
    try {
        const response = await api(`/ui/accounts/${accountId}`, {
            method: 'DELETE',
        });
        
        if (response.ok) {
            closeModal();
            loadAccounts();
            loadStats();
        } else {
            const data = await response.json();
            modalContent.innerHTML = `
                <div class="result-state error">
                    <div class="icon">❌</div>
                    <h3>Failed to remove</h3>
                    <p>${escapeHtml(data.detail || 'Unknown error')}</p>
                </div>
            `;
        }
    } catch (e) {
        modalContent.innerHTML = `
            <div class="result-state error">
                <div class="icon">❌</div>
                <h3>Connection Error</h3>
                <p>Failed to connect to the server.</p>
            </div>
        `;
    }
}

// Modal Functions
function showModal(title, content, actions = '') {
    const modalEl = document.getElementById('modal');
    modalEl.innerHTML = `
        <div class="modal">
            <div class="modal-header">
                <h2>${title}</h2>
            </div>
            <div class="modal-content" id="modal-content">
                ${content}
            </div>
            ${actions ? `<div class="modal-actions">${actions}</div>` : ''}
        </div>
    `;
    modalEl.classList.add('active');
}

function closeModal() {
    const modalEl = document.getElementById('modal');
    modalEl.classList.remove('active');
    if (authPollingInterval) {
        clearInterval(authPollingInterval);
        authPollingInterval = null;
    }
}

// Add Account Modal
function showAddAccountModal() {
    showModal('Add Account', `
        <p style="color: var(--text-secondary); margin-bottom: 20px;">Enter a name and choose how to authenticate with Kiro.</p>
        
        <div class="form-group">
            <label for="account-name">Account Name</label>
            <input type="text" id="account-name" placeholder="e.g., My Work Account" required autofocus>
        </div>
        
        <div class="auth-methods">
            <button class="auth-method-btn" onclick="startAuth('google')">
                <div class="icon google">G</div>
                <div class="text">
                    <div class="title">Google</div>
                    <div class="desc">Sign in with your Google account</div>
                </div>
                <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" style="opacity:0.5">
                    <polyline points="9 18 15 12 9 6"></polyline>
                </svg>
            </button>
            
            <button class="auth-method-btn" onclick="startAuth('github')">
                <div class="icon github">
                    <svg width="24" height="24" viewBox="0 0 24 24" fill="white">
                        <path d="M12 0c-6.626 0-12 5.373-12 12 0 5.302 3.438 9.8 8.207 11.387.599.111.793-.261.793-.577v-2.234c-3.338.726-4.033-1.416-4.033-1.416-.546-1.387-1.333-1.756-1.333-1.756-1.089-.745.083-.729.083-.729 1.205.084 1.839 1.237 1.839 1.237 1.07 1.834 2.807 1.304 3.492.997.107-.775.418-1.305.762-1.604-2.665-.305-5.467-1.334-5.467-5.931 0-1.311.469-2.381 1.236-3.221-.124-.303-.535-1.524.117-3.176 0 0 1.008-.322 3.301 1.23.957-.266 1.983-.399 3.003-.404 1.02.005 2.047.138 3.006.404 2.291-1.552 3.297-1.23 3.297-1.23.653 1.653.242 2.874.118 3.176.77.84 1.235 1.911 1.235 3.221 0 4.609-2.807 5.624-5.479 5.921.43.372.823 1.102.823 2.222v3.293c0 .319.192.694.801.576 4.765-1.589 8.199-6.086 8.199-11.386 0-6.627-5.373-12-12-12z"/>
                    </svg>
                </div>
                <div class="text">
                    <div class="title">GitHub</div>
                    <div class="desc">Sign in with your GitHub account</div>
                </div>
                <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" style="opacity:0.5">
                    <polyline points="9 18 15 12 9 6"></polyline>
                </svg>
            </button>
            
            <button class="auth-method-btn" onclick="startAuth('builder-id')">
                <div class="icon aws">
                    <svg width="24" height="24" viewBox="0 0 24 24" fill="white">
                        <path d="M12 2L2 7l10 5 10-5-10-5zM2 17l10 5 10-5M2 12l10 5 10-5"/>
                    </svg>
                </div>
                <div class="text">
                    <div class="title">AWS Builder ID</div>
                    <div class="desc">Sign in with device code flow</div>
                </div>
                <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" style="opacity:0.5">
                    <polyline points="9 18 15 12 9 6"></polyline>
                </svg>
            </button>
        </div>
    `, `
        <button class="btn btn-secondary" onclick="closeModal()">Cancel</button>
    `);
    
    setTimeout(() => document.getElementById('account-name')?.focus(), 100);
}

// Start Authentication
async function startAuth(method) {
    const accountName = document.getElementById('account-name')?.value || 'New Account';
    
    if (!accountName.trim()) {
        document.getElementById('account-name')?.focus();
        return;
    }
    
    const modalContent = document.getElementById('modal-content');
    modalContent.innerHTML = `
        <div class="loading">
            <div class="spinner"></div>
            <p>Initializing authentication...</p>
        </div>
    `;
    
    // Hide actions
    const modalActions = document.querySelector('.modal-actions');
    if (modalActions) modalActions.style.display = 'none';
    
    try {
        const response = await api('/ui/accounts/start-auth', {
            method: 'POST',
            body: JSON.stringify({
                name: accountName,
                method: method,
            }),
        });
        
        const data = await response.json();
        
        if (!data.success) {
            throw new Error(data.detail || 'Failed to start authentication');
        }
        
        if (method === 'builder-id') {
            showBuilderIdAuth(data);
        } else {
            showSocialAuth(data);
        }
        
    } catch (e) {
        modalContent.innerHTML = `
            <div class="result-state error">
                <div class="icon">❌</div>
                <h3>Authentication Failed</h3>
                <p>${escapeHtml(e.message)}</p>
            </div>
        `;
        if (modalActions) {
            modalActions.style.display = 'flex';
            modalActions.innerHTML = `
                <button class="btn btn-secondary" onclick="closeModal()">Close</button>
                <button class="btn btn-primary" onclick="showAddAccountModal()">Try Again</button>
            `;
        }
    }
}

// Show Social Auth (Google/GitHub)
function showSocialAuth(data) {
    const modalContent = document.getElementById('modal-content');
    modalContent.innerHTML = `
        <div style="text-align: center;">
            <div style="margin-bottom: 24px;">
                <div style="width: 80px; height: 80px; margin: 0 auto 16px; background: var(--accent-glow); border-radius: var(--radius-md); display: flex; align-items: center; justify-content: center; font-size: 40px;">
                    ${data.provider === 'Google' ? '🔵' : '⚫'}
                </div>
                <h3 style="font-family: 'Space Grotesk', sans-serif; margin-bottom: 8px;">Sign in with ${data.provider}</h3>
                <p style="color: var(--text-secondary); font-size: 0.9rem;">Click the button below to open the sign-in page</p>
            </div>
            
            <a href="${data.auth_url}" target="_blank" class="btn btn-primary" style="display: inline-flex; text-decoration: none; margin-bottom: 32px;">
                <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                    <path d="M18 13v6a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V8a2 2 0 0 1 2-2h6"></path>
                    <polyline points="15 3 21 3 21 9"></polyline>
                    <line x1="10" y1="14" x2="21" y2="3"></line>
                </svg>
                Open ${data.provider}
            </a>
            
            <div class="loading" style="padding: 24px;">
                <div class="spinner"></div>
                <p>Waiting for authentication...</p>
                <p style="font-size: 0.8rem; color: var(--text-muted); margin-top: 8px;">Complete sign-in in the new window</p>
            </div>
        </div>
    `;
    
    const modalActions = document.querySelector('.modal-actions');
    if (modalActions) {
        modalActions.style.display = 'flex';
        modalActions.innerHTML = `<button class="btn btn-secondary" onclick="cancelAuth()">Cancel</button>`;
    }
    
    waitForAuthCompletion();
}

// Show Builder ID Auth
function showBuilderIdAuth(data) {
    const modalContent = document.getElementById('modal-content');
    modalContent.innerHTML = `
        <div style="text-align: center;">
            <div style="margin-bottom: 24px;">
                <div style="width: 80px; height: 80px; margin: 0 auto 16px; background: linear-gradient(135deg, #ff9900, #ffb84d); border-radius: var(--radius-md); display: flex; align-items: center; justify-content: center;">
                    <svg width="40" height="40" viewBox="0 0 24 24" fill="white">
                        <path d="M12 2L2 7l10 5 10-5-10-5zM2 17l10 5 10-5M2 12l10 5 10-5"/>
                    </svg>
                </div>
                <h3 style="font-family: 'Space Grotesk', sans-serif; margin-bottom: 8px;">AWS Builder ID</h3>
                <p style="color: var(--text-secondary); font-size: 0.9rem;">Enter the code on the verification page</p>
            </div>
            
            <div style="background: var(--bg-glass); border: 1px solid var(--border-subtle); border-radius: var(--radius-md); padding: 24px; margin-bottom: 24px;">
                <div style="font-family: 'JetBrains Mono', monospace; font-size: 2rem; font-weight: 700; letter-spacing: 0.2em; color: var(--accent-primary); margin-bottom: 16px;">
                    ${data.user_code || 'N/A'}
                </div>
                <a href="${data.auth_url}" target="_blank" class="btn btn-primary btn-sm" style="text-decoration: none;">
                    <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                        <path d="M18 13v6a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V8a2 2 0 0 1 2-2h6"></path>
                        <polyline points="15 3 21 3 21 9"></polyline>
                        <line x1="10" y1="14" x2="21" y2="3"></line>
                    </svg>
                    Open Verification Page
                </a>
            </div>
            
            <div class="loading" style="padding: 16px;">
                <div class="spinner"></div>
                <p>Waiting for verification...</p>
            </div>
        </div>
    `;
    
    const modalActions = document.querySelector('.modal-actions');
    if (modalActions) {
        modalActions.style.display = 'flex';
        modalActions.innerHTML = `<button class="btn btn-secondary" onclick="cancelAuth()">Cancel</button>`;
    }
    
    waitForAuthCompletion();
}

// Wait for auth completion
async function waitForAuthCompletion() {
    const modalContent = document.getElementById('modal-content');
    
    try {
        const response = await api('/ui/accounts/complete-auth', {
            method: 'POST',
        });
        
        const data = await response.json();
        
        if (data.success) {
            modalContent.innerHTML = `
                <div class="result-state success">
                    <div class="icon">✅</div>
                    <h3>Account Added!</h3>
                    <p>${escapeHtml(data.account?.name || 'New account')} is now ready to use.</p>
                </div>
            `;
            
            const modalActions = document.querySelector('.modal-actions');
            if (modalActions) {
                modalActions.innerHTML = `
                    <button class="btn btn-primary" onclick="closeModal(); loadAccounts(); loadStats();">Done</button>
                `;
            }
        } else {
            throw new Error(data.detail || 'Authentication failed');
        }
    } catch (e) {
        modalContent.innerHTML = `
            <div class="result-state error">
                <div class="icon">❌</div>
                <h3>Authentication Failed</h3>
                <p>${escapeHtml(e.message)}</p>
            </div>
        `;
        
        const modalActions = document.querySelector('.modal-actions');
        if (modalActions) {
            modalActions.innerHTML = `
                <button class="btn btn-secondary" onclick="closeModal()">Close</button>
                <button class="btn btn-primary" onclick="showAddAccountModal()">Try Again</button>
            `;
        }
    }
}

// Cancel Auth
async function cancelAuth() {
    try {
        await api('/ui/accounts/cancel-auth', { method: 'POST' });
    } catch (e) {
        // Ignore
    }
    closeModal();
}

// Auto-refresh accounts every 30 seconds
let accountsAutoRefreshInterval = null;
const ACCOUNTS_REFRESH_INTERVAL = 30000; // 30 seconds

function startAccountsAutoRefresh() {
    if (accountsAutoRefreshInterval) return;
    
    // Refresh periodically
    accountsAutoRefreshInterval = setInterval(() => {
        if (dashboard.classList.contains('active')) {
            loadAccounts();
            loadStats();
        }
    }, ACCOUNTS_REFRESH_INTERVAL);
}

function stopAccountsAutoRefresh() {
    if (accountsAutoRefreshInterval) {
        clearInterval(accountsAutoRefreshInterval);
        accountsAutoRefreshInterval = null;
    }
}

// Auto-refresh tokens periodically (every 5 minutes)
let tokenAutoRefreshInterval = null;
const TOKEN_REFRESH_INTERVAL = 300000; // 5 minutes

function startTokenAutoRefresh() {
    if (tokenAutoRefreshInterval) return;
    
    // Refresh tokens periodically
    tokenAutoRefreshInterval = setInterval(async () => {
        try {
            const response = await api('/ui/accounts/refresh-all', { method: 'POST' });
            const data = await response.json();
            if (data.success && data.refreshed_count > 0) {
                console.log(`Auto-refreshed ${data.refreshed_count} tokens`);
                loadAccounts();
            }
        } catch (e) {
            console.error('Auto token refresh failed:', e);
        }
    }, TOKEN_REFRESH_INTERVAL);
}

function stopTokenAutoRefresh() {
    if (tokenAutoRefreshInterval) {
        clearInterval(tokenAutoRefreshInterval);
        tokenAutoRefreshInterval = null;
    }
}

// ============================================
// NAVIGATION
// ============================================

document.querySelectorAll('.nav-item').forEach(item => {
    item.addEventListener('click', (e) => {
        e.preventDefault();
        const section = item.dataset.section;
        
        // Update nav
        document.querySelectorAll('.nav-item').forEach(i => i.classList.remove('active'));
        item.classList.add('active');
        
        // Update sections
        document.querySelectorAll('.section').forEach(s => s.classList.remove('active'));
        document.getElementById(section)?.classList.add('active');
        
        // Load data for section
        if (section === 'usage') loadUsageStats();
        if (section === 'credits') loadCredits();
        if (section === 'accounts') loadAccounts();
        if (section === 'config') loadConfig();
        if (section === 'dashboard') { loadSystemInfo(); loadStats(); }
    });
});

// ============================================
// SYSTEM INFO
// ============================================

async function loadSystemInfo() {
    try {
        const response = await api('/ui/api/system');
        const data = await response.json();
        
        document.getElementById('app-version').textContent = `v${data.version}`;
        document.getElementById('sys-version').textContent = data.version;
        document.getElementById('sys-python').textContent = data.python_version;
        document.getElementById('sys-platform').textContent = data.platform;
        document.getElementById('sys-time').textContent = new Date(data.server_time).toLocaleTimeString();
        document.getElementById('sys-memory').textContent = `${data.memory.process_mb} MB / ${data.memory.percent}%`;
        document.getElementById('sys-cpu').textContent = `${data.cpu.percent}% (${data.cpu.cores} cores)`;
        document.getElementById('sys-pid').textContent = data.pid;
        document.getElementById('stat-uptime').textContent = data.uptime;
    } catch (e) {
        console.error('Failed to load system info:', e);
    }
}

// ============================================
// CONFIG MANAGEMENT
// ============================================

async function loadConfig() {
    try {
        const response = await api('/ui/api/config/raw');
        const data = await response.json();
        
        if (data.config) {
            // Populate form fields
            document.getElementById('cfg-proxy-key').value = data.config.proxy_api_key || '';
            document.getElementById('cfg-secret-key').value = data.config.secret_key || '';
            document.getElementById('cfg-creds-file').value = data.config.kiro_creds_file || '';
            document.getElementById('cfg-region').value = data.config.kiro_region || 'us-east-1';
            document.getElementById('cfg-log-level').value = data.config.log_level || 'INFO';
            document.getElementById('cfg-debug-mode').value = data.config.debug_mode || 'off';
            document.getElementById('cfg-first-token-timeout').value = data.config.first_token_timeout || 15;
            document.getElementById('cfg-streaming-timeout').value = data.config.streaming_read_timeout || 300;
            document.getElementById('cfg-max-retries').value = data.config.first_token_max_retries || 3;
            document.getElementById('cfg-tool-desc-length').value = data.config.tool_description_max_length || 10000;
        }
    } catch (e) {
        console.error('Failed to load config:', e);
    }
}

async function saveConfig() {
    const config = {
        proxy_api_key: document.getElementById('cfg-proxy-key').value,
        secret_key: document.getElementById('cfg-secret-key').value,
        kiro_creds_file: document.getElementById('cfg-creds-file').value,
        kiro_region: document.getElementById('cfg-region').value,
        log_level: document.getElementById('cfg-log-level').value,
        debug_mode: document.getElementById('cfg-debug-mode').value,
        first_token_timeout: parseInt(document.getElementById('cfg-first-token-timeout').value) || 15,
        streaming_read_timeout: parseInt(document.getElementById('cfg-streaming-timeout').value) || 300,
        first_token_max_retries: parseInt(document.getElementById('cfg-max-retries').value) || 3,
        tool_description_max_length: parseInt(document.getElementById('cfg-tool-desc-length').value) || 10000,
    };
    
    try {
        const response = await api('/ui/api/config', {
            method: 'POST',
            body: JSON.stringify({ config }),
        });
        
        const data = await response.json();
        if (data.success) {
            showToast('Configuration saved successfully', 'success');
        } else {
            showToast('Failed to save configuration', 'error');
        }
    } catch (e) {
        showToast('Error saving configuration: ' + e.message, 'error');
    }
}

// ============================================
// USAGE STATISTICS
// ============================================

async function loadUsageStats() {
    try {
        const response = await api('/ui/api/usage/summary');
        const data = await response.json();
        
        // Update overview cards
        animateNumber(document.getElementById('usage-total-requests'), data.total_requests);
        animateNumber(document.getElementById('usage-active-accounts'), data.active_accounts);
        animateNumber(document.getElementById('usage-healthy-accounts'), data.status_counts?.healthy || 0);
        
        // Update last updated
        document.getElementById('usage-last-updated').textContent = 
            `Last updated: ${new Date(data.last_updated).toLocaleTimeString()}`;
        
        // Render usage chart
        renderUsageChart(data.accounts, data.total_requests);
        
        // Render usage list
        renderUsageList(data.accounts);
        
    } catch (e) {
        console.error('Failed to load usage stats:', e);
    }
}

function renderUsageChart(accounts, totalRequests) {
    const container = document.getElementById('usage-chart');
    
    if (!accounts || accounts.length === 0) {
        container.innerHTML = `
            <div class="empty-state" style="padding: 40px;">
                <i class="fas fa-chart-pie" style="font-size: 48px; opacity: 0.5;"></i>
                <p style="margin-top: 16px;">No usage data available</p>
            </div>
        `;
        return;
    }
    
    container.innerHTML = accounts.map(account => `
        <div class="usage-bar-container">
            <div class="usage-bar-header">
                <div class="usage-bar-name">
                    <div class="provider-icon">${getProviderIcon(account.provider, account.auth_method)}</div>
                    <span>${escapeHtml(account.name)}</span>
                </div>
                <div class="usage-bar-stats">
                    <span class="usage-bar-count">${formatNumber(account.request_count)} requests</span>
                    <span class="usage-bar-percent">${account.percentage}%</span>
                </div>
            </div>
            <div class="usage-bar">
                <div class="usage-bar-fill ${account.is_active ? '' : 'inactive'}" style="width: ${account.percentage}%"></div>
            </div>
        </div>
    `).join('');
}

function renderUsageList(accounts) {
    const container = document.getElementById('usage-list');
    
    if (!accounts || accounts.length === 0) {
        container.innerHTML = `
            <div class="empty-state" style="padding: 40px;">
                <i class="fas fa-chart-bar" style="font-size: 48px; opacity: 0.5;"></i>
                <p style="margin-top: 16px;">No accounts to display</p>
            </div>
        `;
        return;
    }
    
    container.innerHTML = accounts.map(account => `
        <div class="usage-item">
            <div class="usage-item-info">
                <div class="usage-item-status ${account.status}"></div>
                <div>
                    <div class="usage-item-name">${escapeHtml(account.name)}</div>
                    <div class="usage-item-provider">${account.provider} ${account.is_active ? '' : '(inactive)'}</div>
                </div>
            </div>
            <div class="usage-item-stats">
                <div>
                    <div class="usage-item-count">${formatNumber(account.request_count)}</div>
                    <div class="usage-item-last">${account.last_used_at ? formatRelativeTime(account.last_used_at) : 'Never used'}</div>
                </div>
            </div>
        </div>
    `).join('');
}

// ============================================
// KIRO CREDITS
// ============================================

let creditsAutoRefreshInterval = null;
const CREDITS_REFRESH_INTERVAL = 60000; // Refresh every 60 seconds

function startCreditsAutoRefresh() {
    if (creditsAutoRefreshInterval) return;
    
    // Load immediately on start
    loadCredits();
    
    // Then refresh periodically
    creditsAutoRefreshInterval = setInterval(() => {
        // Only refresh if credits section is active
        const creditsSection = document.getElementById('credits');
        if (creditsSection && creditsSection.classList.contains('active')) {
            loadCredits();
        }
    }, CREDITS_REFRESH_INTERVAL);
}

function stopCreditsAutoRefresh() {
    if (creditsAutoRefreshInterval) {
        clearInterval(creditsAutoRefreshInterval);
        creditsAutoRefreshInterval = null;
    }
}

async function loadCredits() {
    try {
        const response = await api('/ui/api/credits');
        const data = await response.json();
        
        // Update overview cards
        animateNumber(document.getElementById('credits-remaining'), data.totals?.total_remaining || 0);
        animateNumber(document.getElementById('credits-used'), data.totals?.total_used || 0);
        document.getElementById('credits-percentage').textContent = `${data.totals?.percentage_used || 0}%`;
        
        // Update last updated
        document.getElementById('credits-last-updated').textContent = 
            `Last updated: ${new Date(data.last_updated).toLocaleTimeString()}`;
        
        // Render credits list
        renderCreditsList(data.accounts, data.errors);
        
    } catch (e) {
        console.error('Failed to load credits:', e);
        document.getElementById('credits-list').innerHTML = `
            <div class="empty-state" style="padding: 40px;">
                <i class="fas fa-exclamation-triangle" style="font-size: 48px; opacity: 0.5; color: var(--danger);"></i>
                <p style="margin-top: 16px;">Failed to load credits: ${escapeHtml(e.message)}</p>
            </div>
        `;
    }
}

function renderCreditsList(accounts, errors) {
    const container = document.getElementById('credits-list');
    
    if ((!accounts || accounts.length === 0) && (!errors || errors.length === 0)) {
        container.innerHTML = `
            <div class="empty-state" style="padding: 40px;">
                <i class="fas fa-coins" style="font-size: 48px; opacity: 0.5;"></i>
                <p style="margin-top: 16px;">No accounts with credits data</p>
            </div>
        `;
        return;
    }
    
    let html = '';
    
    // Render successful accounts
    if (accounts && accounts.length > 0) {
        html += accounts.map(account => {
            if (account.error) {
                return `
                    <div class="usage-item" style="border-left: 3px solid var(--warning);">
                        <div class="usage-item-info">
                            <div class="usage-item-status warning"></div>
                            <div>
                                <div class="usage-item-name">${escapeHtml(account.account_name)}</div>
                                <div class="usage-item-provider" style="color: var(--warning);">${escapeHtml(account.error)}</div>
                            </div>
                        </div>
                    </div>
                `;
            }
            
            const percentColor = account.percentage_used > 80 ? 'var(--danger)' : 
                                 account.percentage_used > 50 ? 'var(--warning)' : 'var(--success)';
            
            return `
                <div class="usage-item">
                    <div class="usage-item-info">
                        <div class="usage-item-status healthy"></div>
                        <div>
                            <div class="usage-item-name">${escapeHtml(account.account_name)}</div>
                            <div class="usage-item-provider">
                                ${account.subscription || 'Unknown Plan'}
                                ${account.email ? ` - ${escapeHtml(account.email)}` : ''}
                            </div>
                        </div>
                    </div>
                    <div class="usage-item-stats" style="text-align: right;">
                        <div>
                            <div class="usage-item-count" style="color: ${percentColor};">
                                ${formatNumber(account.remaining)} / ${formatNumber(account.usage_limit)}
                            </div>
                            <div class="usage-item-last">
                                ${account.percentage_used}% used
                                ${account.days_until_reset ? ` - Resets in ${account.days_until_reset} days` : ''}
                                ${account.bonus_remaining > 0 ? ` (+${formatNumber(account.bonus_remaining)} bonus)` : ''}
                            </div>
                        </div>
                    </div>
                </div>
            `;
        }).join('');
    }
    
    // Render errors
    if (errors && errors.length > 0) {
        html += errors.map(err => `
            <div class="usage-item" style="border-left: 3px solid var(--danger);">
                <div class="usage-item-info">
                    <div class="usage-item-status expired"></div>
                    <div>
                        <div class="usage-item-name">${escapeHtml(err.account_name)}</div>
                        <div class="usage-item-provider" style="color: var(--danger);">Error: ${escapeHtml(err.error)}</div>
                    </div>
                </div>
            </div>
        `).join('');
    }
    
    container.innerHTML = html;
}

// ============================================
// ENHANCED ACCOUNT MANAGEMENT
// ============================================

async function refreshAllTokens() {
    try {
        const response = await api('/ui/accounts/refresh-all', { method: 'POST' });
        const data = await response.json();
        
        if (data.success) {
            showToast(`Refreshed ${data.refreshed_count} tokens`, 'success');
            loadAccounts();
        } else {
            showToast('Failed to refresh tokens', 'error');
        }
    } catch (e) {
        showToast('Error refreshing tokens: ' + e.message, 'error');
    }
}

async function toggleAccount(accountId) {
    try {
        const response = await api(`/ui/accounts/${accountId}/toggle`, { method: 'POST' });
        const data = await response.json();
        
        if (data.success) {
            showToast(data.message, 'success');
            loadAccounts();
        } else {
            showToast('Failed to toggle account', 'error');
        }
    } catch (e) {
        showToast('Error: ' + e.message, 'error');
    }
}

async function refreshAccountToken(accountId) {
    try {
        const response = await api(`/ui/accounts/${accountId}/refresh`, { method: 'POST' });
        const data = await response.json();
        
        if (data.success) {
            showToast('Token refreshed successfully', 'success');
            loadAccounts();
        } else {
            showToast('Failed to refresh token', 'error');
        }
    } catch (e) {
        showToast('Error: ' + e.message, 'error');
    }
}

// Update renderAccounts to include more actions
function renderAccounts(accounts) {
    if (!accounts || accounts.length === 0) {
        accountsList.innerHTML = `
            <div class="empty-state">
                <div class="icon">🔐</div>
                <h3>No accounts yet</h3>
                <p>Add your first Kiro account to start using the gateway with load balancing.</p>
                <button class="btn btn-primary" onclick="showAddAccountModal()">
                    <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5">
                        <line x1="12" y1="5" x2="12" y2="19"></line>
                        <line x1="5" y1="12" x2="19" y2="12"></line>
                    </svg>
                    Add Account
                </button>
            </div>
        `;
        // Update stats
        document.getElementById('accounts-total').textContent = '0';
        document.getElementById('accounts-healthy').textContent = '0';
        document.getElementById('accounts-expiring').textContent = '0';
        document.getElementById('accounts-expired').textContent = '0';
        return;
    }
    
    // Update stats
    const healthy = accounts.filter(a => a.status === 'healthy').length;
    const expiring = accounts.filter(a => a.status === 'expiring_soon').length;
    const expired = accounts.filter(a => a.status === 'expired').length;
    
    document.getElementById('accounts-total').textContent = accounts.length;
    document.getElementById('accounts-healthy').textContent = healthy;
    document.getElementById('accounts-expiring').textContent = expiring;
    document.getElementById('accounts-expired').textContent = expired;
    
    accountsList.innerHTML = accounts.map((account, index) => `
        <div class="account-card" data-id="${account.id}" style="animation-delay: ${index * 0.05}s">
            <div class="account-info">
                <div class="account-status ${account.status}" title="${getStatusLabel(account.status)}"></div>
                <div class="account-avatar">${getProviderIcon(account.provider, account.auth_method)}</div>
                <div class="account-details">
                    <h3>${escapeHtml(account.name)}</h3>
                    <div class="meta">
                        <span>${account.provider || account.auth_method || 'Unknown'}</span>
                        <span class="dot"></span>
                        <span>${formatNumber(account.request_count)} requests</span>
                        ${account.expires_at ? `<span class="dot"></span><span>Expires ${formatRelativeTime(account.expires_at)}</span>` : ''}
                    </div>
                </div>
            </div>
            <div class="account-actions">
                <button class="btn btn-secondary btn-sm" onclick="refreshAccountToken(${account.id})" title="Refresh Token">
                    <i class="fas fa-sync-alt"></i>
                </button>
                <button class="btn btn-secondary btn-sm" onclick="toggleAccount(${account.id})" title="${account.is_active ? 'Deactivate' : 'Activate'}">
                    <i class="fas fa-${account.is_active ? 'pause' : 'play'}"></i>
                </button>
                <button class="btn btn-danger btn-sm" onclick="deleteAccount(${account.id}, '${escapeHtml(account.name)}')">
                    <i class="fas fa-trash"></i>
                </button>
            </div>
        </div>
    `).join('');
}

// ============================================
// LOG FILTERING
// ============================================

let currentLogFilter = 'all';
let currentLogSearch = '';

function filterLogs(level) {
    currentLogFilter = level;
    
    // Update button states
    document.querySelectorAll('.log-filter-btn').forEach(btn => {
        btn.classList.toggle('active', btn.dataset.level === level);
    });
    
    applyLogFilters();
}

function searchLogs(query) {
    currentLogSearch = query.toLowerCase();
    applyLogFilters();
}

function applyLogFilters() {
    const entries = document.querySelectorAll('#logs-container .log-entry');
    entries.forEach(entry => {
        const level = entry.querySelector('.log-level')?.textContent || '';
        const message = entry.querySelector('.log-message')?.textContent?.toLowerCase() || '';
        
        const matchesLevel = currentLogFilter === 'all' || level === currentLogFilter;
        const matchesSearch = !currentLogSearch || message.includes(currentLogSearch);
        
        entry.classList.toggle('hidden', !(matchesLevel && matchesSearch));
    });
}

function downloadLogs() {
    const entries = document.querySelectorAll('#logs-container .log-entry:not(.hidden)');
    let logText = '';
    
    entries.forEach(entry => {
        const time = entry.querySelector('.log-time')?.textContent || '';
        const level = entry.querySelector('.log-level')?.textContent || '';
        const message = entry.querySelector('.log-message')?.textContent || '';
        logText += `${time} [${level}] ${message}\n`;
    });
    
    const blob = new Blob([logText], { type: 'text/plain' });
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = `kiro-gateway-logs-${new Date().toISOString().split('T')[0]}.txt`;
    a.click();
    URL.revokeObjectURL(url);
}

let autoScroll = true;

function toggleAutoScroll() {
    autoScroll = !autoScroll;
    const btn = document.getElementById('toggle-autoscroll');
    btn.innerHTML = `<i class="fas fa-arrow-down"></i> Auto-scroll: ${autoScroll ? 'ON' : 'OFF'}`;
}

async function clearLogs() {
    try {
        await api('/ui/api/logs', { method: 'DELETE' });
        document.getElementById('logs-container').innerHTML = `
            <div class="log-entry info">
                <span class="log-time">${new Date().toLocaleTimeString()}</span>
                <span class="log-level">INFO</span>
                <span class="log-message">Logs cleared</span>
            </div>
        `;
    } catch (e) {
        console.error('Failed to clear logs:', e);
    }
}

// ============================================
// TOAST NOTIFICATIONS
// ============================================

function showToast(message, type = 'info') {
    const container = document.getElementById('toast-container');
    const toast = document.createElement('div');
    toast.className = `toast ${type}`;
    
    const icons = {
        success: 'fa-check-circle',
        error: 'fa-exclamation-circle',
        warning: 'fa-exclamation-triangle',
        info: 'fa-info-circle'
    };
    
    toast.innerHTML = `
        <i class="fas ${icons[type]} toast-icon"></i>
        <span class="toast-message">${escapeHtml(message)}</span>
    `;
    
    container.appendChild(toast);
    
    setTimeout(() => {
        toast.style.opacity = '0';
        setTimeout(() => toast.remove(), 300);
    }, 3000);
}

// ============================================
// LOG STREAMING (SSE)
// ============================================

let logEventSource = null;
let logReconnectAttempts = 0;
const MAX_RECONNECT_ATTEMPTS = 5;
const RECONNECT_DELAY = 3000;

function connectLogStream() {
    if (!sessionToken) return;
    
    // Close existing connection
    if (logEventSource) {
        logEventSource.close();
        logEventSource = null;
    }
    
    // Connect with token as query parameter (EventSource doesn't support headers)
    const url = `${API_BASE}/ui/api/logs/stream?token=${encodeURIComponent(sessionToken)}`;
    logEventSource = new EventSource(url);
    
    logEventSource.onopen = () => {
        logReconnectAttempts = 0;
        updateLogConnectionStatus('connected');
        console.log('Log stream connected');
    };
    
    logEventSource.onmessage = (event) => {
        try {
            // Parse the log entry (it's a Python dict string, need to handle it)
            let entry = event.data;
            // Convert Python dict format to JSON if needed
            if (entry.startsWith('{') && entry.includes("'")) {
                entry = entry.replace(/'/g, '"');
            }
            const logEntry = JSON.parse(entry);
            addLogToUI(logEntry);
        } catch (e) {
            // If parsing fails, just display raw data
            if (event.data && !event.data.startsWith(':')) {
                addLogToUI({
                    timestamp: new Date().toISOString(),
                    level: 'INFO',
                    message: event.data
                });
            }
        }
    };
    
    logEventSource.onerror = (error) => {
        console.error('Log stream error:', error);
        logEventSource.close();
        logEventSource = null;
        updateLogConnectionStatus('disconnected');
        
        // Attempt reconnection
        if (logReconnectAttempts < MAX_RECONNECT_ATTEMPTS && sessionToken) {
            logReconnectAttempts++;
            console.log(`Reconnecting log stream (attempt ${logReconnectAttempts}/${MAX_RECONNECT_ATTEMPTS})...`);
            setTimeout(connectLogStream, RECONNECT_DELAY);
        } else if (logReconnectAttempts >= MAX_RECONNECT_ATTEMPTS) {
            console.log('Max reconnect attempts reached, falling back to polling');
            startLogPolling();
        }
    };
}

function disconnectLogStream() {
    if (logEventSource) {
        logEventSource.close();
        logEventSource = null;
    }
    stopLogPolling();
}

function updateLogConnectionStatus(status) {
    const container = document.getElementById('logs-container');
    const statusIndicator = document.getElementById('log-connection-status');
    
    if (statusIndicator) {
        statusIndicator.className = `log-connection-status ${status}`;
        statusIndicator.title = status === 'connected' ? 'Connected to log stream' : 'Disconnected from log stream';
    }
}

function addLogToUI(logEntry) {
    const container = document.getElementById('logs-container');
    if (!container) return;
    
    // Remove "Connecting..." placeholder if present
    const placeholder = container.querySelector('.log-entry.info .log-message');
    if (placeholder && placeholder.textContent.includes('Connecting to log stream')) {
        container.innerHTML = '';
    }
    
    const time = logEntry.timestamp ? new Date(logEntry.timestamp).toLocaleTimeString() : new Date().toLocaleTimeString();
    const level = logEntry.level || 'INFO';
    const message = logEntry.message || '';
    
    const entry = document.createElement('div');
    entry.className = `log-entry ${level.toLowerCase()}`;
    entry.innerHTML = `
        <span class="log-time">${escapeHtml(time)}</span>
        <span class="log-level">${escapeHtml(level)}</span>
        <span class="log-message">${escapeHtml(message)}</span>
    `;
    
    // Apply current filters
    const matchesLevel = currentLogFilter === 'all' || level === currentLogFilter;
    const matchesSearch = !currentLogSearch || message.toLowerCase().includes(currentLogSearch);
    if (!(matchesLevel && matchesSearch)) {
        entry.classList.add('hidden');
    }
    
    container.appendChild(entry);
    
    // Limit entries to prevent memory issues
    while (container.children.length > 500) {
        container.removeChild(container.firstChild);
    }
    
    // Auto-scroll if enabled
    if (autoScroll) {
        container.scrollTop = container.scrollHeight;
    }
}

// Fallback polling for when SSE fails
let logPollingInterval = null;
let lastLogTimestamp = null;

function startLogPolling() {
    if (logPollingInterval) return;
    
    logPollingInterval = setInterval(async () => {
        try {
            const response = await api('/ui/api/logs');
            if (response.ok) {
                const data = await response.json();
                const logs = data.logs || [];
                
                // Only add new logs
                logs.forEach(log => {
                    if (!lastLogTimestamp || log.timestamp > lastLogTimestamp) {
                        addLogToUI(log);
                        lastLogTimestamp = log.timestamp;
                    }
                });
            }
        } catch (e) {
            console.error('Log polling error:', e);
        }
    }, 2000);
}

function stopLogPolling() {
    if (logPollingInterval) {
        clearInterval(logPollingInterval);
        logPollingInterval = null;
    }
}

// ============================================
// UTILITY FUNCTIONS
// ============================================

function copyToClipboard(text) {
    navigator.clipboard.writeText(text).then(() => {
        showToast('Copied to clipboard', 'success');
    }).catch(() => {
        showToast('Failed to copy', 'error');
    });
}

// Initial load on dashboard
if (sessionToken) {
    loadSystemInfo();
    loadStats();
    connectLogStream();
    startCreditsAutoRefresh();
    startAccountsAutoRefresh();
    startTokenAutoRefresh();
}
