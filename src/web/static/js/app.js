/**
 * Podcastwise Web UI - Common JavaScript
 */

// Global utility functions
window.escapeHtml = function(text) {
    if (!text) return '';
    const div = document.createElement('div');
    div.textContent = text;
    return div.innerHTML;
};

// Format date helper
window.formatDate = function(dateStr) {
    if (!dateStr) return '-';
    try {
        return new Date(dateStr).toLocaleDateString();
    } catch {
        return dateStr;
    }
};

// Format duration helper
window.formatDuration = function(seconds) {
    if (!seconds || seconds <= 0) return '-';
    const mins = Math.floor(seconds / 60);
    const hours = Math.floor(mins / 60);
    const remainingMins = mins % 60;

    if (hours > 0) {
        return `${hours}h ${remainingMins}m`;
    }
    return `${mins}m`;
};

// Toast notifications
window.showToast = function(message, type = 'info') {
    const container = document.getElementById('toast-container') || createToastContainer();

    const toast = document.createElement('div');
    toast.className = `toast toast-${type}`;
    toast.textContent = message;

    container.appendChild(toast);

    // Auto remove after 3 seconds
    setTimeout(() => {
        toast.classList.add('toast-fade');
        setTimeout(() => toast.remove(), 300);
    }, 3000);
};

function createToastContainer() {
    const container = document.createElement('div');
    container.id = 'toast-container';
    container.style.cssText = `
        position: fixed;
        top: 80px;
        right: 20px;
        z-index: 300;
        display: flex;
        flex-direction: column;
        gap: 8px;
    `;
    document.body.appendChild(container);
    return container;
}

// Add toast styles dynamically
const toastStyles = document.createElement('style');
toastStyles.textContent = `
    .toast {
        padding: 12px 20px;
        border-radius: 8px;
        color: white;
        font-weight: 500;
        animation: slideIn 0.3s ease;
    }
    .toast-success { background: #4ade80; color: #1a1a2e; }
    .toast-error { background: #f87171; }
    .toast-warning { background: #fbbf24; color: #1a1a2e; }
    .toast-info { background: #60a5fa; }
    .toast-fade { opacity: 0; transition: opacity 0.3s; }
    @keyframes slideIn {
        from { transform: translateX(100%); opacity: 0; }
        to { transform: translateX(0); opacity: 1; }
    }
`;
document.head.appendChild(toastStyles);
