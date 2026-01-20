// JavaScript functionality for the log viewer
class LogViewer {
    constructor() {
        this.autoScroll = false;
        this.autoRefresh = false;
        this.refreshInterval = null;
        this.init();
    }

    init() {
        this.bindEvents();
        this.initAutoRefresh();
        this.initKeyboardShortcuts();
    }

    bindEvents() {
        // Auto-scroll toggle
        const autoScrollBtn = document.getElementById('auto-scroll-btn');
        if (autoScrollBtn) {
            autoScrollBtn.addEventListener('click', () => this.toggleAutoScroll());
        }

        // Scroll to bottom button
        const scrollBottomBtn = document.getElementById('scroll-bottom-btn');
        if (scrollBottomBtn) {
            scrollBottomBtn.addEventListener('click', () => this.scrollToBottom());
        }

        // Filter form auto-submit on change
        const filterForm = document.getElementById('filter-form');
        if (filterForm) {
            const selects = filterForm.querySelectorAll('select');
            selects.forEach(select => {
                select.addEventListener('change', () => {
                    filterForm.submit();
                });
            });
        }

        // Search input with debounce
        const searchInput = document.getElementById('search-input');
        if (searchInput) {
            let timeout;
            searchInput.addEventListener('input', (e) => {
                clearTimeout(timeout);
                timeout = setTimeout(() => {
                    this.performSearch(e.target.value);
                }, 500);
            });
        }
    }

    initAutoRefresh() {
        // Check if auto-refresh is enabled from URL params
        const urlParams = new URLSearchParams(window.location.search);
        this.autoRefresh = urlParams.get('auto_refresh') === 'true';
        
        if (this.autoRefresh) {
            this.startAutoRefresh();
        }
    }

    initKeyboardShortcuts() {
        document.addEventListener('keydown', (e) => {
            // Ctrl/Cmd + R for refresh
            if ((e.ctrlKey || e.metaKey) && e.key === 'r') {
                e.preventDefault();
                window.location.reload();
            }

            // End key to scroll to bottom
            if (e.key === 'End') {
                e.preventDefault();
                this.scrollToBottom();
            }

            // Home key to scroll to top
            if (e.key === 'Home') {
                e.preventDefault();
                this.scrollToTop();
            }

            // Escape to clear search
            if (e.key === 'Escape') {
                const searchInput = document.getElementById('search-input');
                if (searchInput && searchInput.value) {
                    searchInput.value = '';
                    searchInput.form.submit();
                }
            }
        });
    }

    toggleAutoScroll() {
        this.autoScroll = !this.autoScroll;
        const btn = document.getElementById('auto-scroll-btn');
        if (btn) {
            btn.textContent = this.autoScroll ? 'Disable Auto Scroll' : 'Enable Auto Scroll';
        }
    }

    scrollToBottom() {
        const container = document.querySelector('.log-container');
        if (container) {
            container.scrollTop = container.scrollHeight;
        }
    }

    scrollToTop() {
        const container = document.querySelector('.log-container');
        if (container) {
            container.scrollTop = 0;
        }
    }

    startAutoRefresh() {
        if (this.refreshInterval) return;
        
        this.refreshInterval = setInterval(() => {
            window.location.reload();
        }, 5000); // Refresh every 5 seconds

        // Show auto-refresh indicator
        this.showAutoRefreshIndicator();
    }

    stopAutoRefresh() {
        if (this.refreshInterval) {
            clearInterval(this.refreshInterval);
            this.refreshInterval = null;
        }
        this.hideAutoRefreshIndicator();
    }

    showAutoRefreshIndicator() {
        const indicator = document.createElement('div');
        indicator.id = 'auto-refresh-indicator';
        indicator.className = 'auto-refresh-indicator';
        indicator.innerHTML = `
            <div class="auto-refresh-dot"></div>
            Auto Refresh Active
        `;
        
        // Position it in the top right corner
        indicator.style.cssText = `
            position: fixed;
            top: 1rem;
            right: 1rem;
            z-index: 1000;
        `;
        
        document.body.appendChild(indicator);
    }

    hideAutoRefreshIndicator() {
        const indicator = document.getElementById('auto-refresh-indicator');
        if (indicator) {
            indicator.remove();
        }
    }

    performSearch(searchTerm) {
        // This would typically update the URL and reload with search params
        const form = document.getElementById('filter-form');
        if (form) {
            const searchInput = form.querySelector('input[name="search"]');
            if (searchInput) {
                searchInput.value = searchTerm;
                form.submit();
            }
        }
    }

    highlightSearchTerms(searchTerm) {
        if (!searchTerm) return;

        const logEntries = document.querySelectorAll('.log-entry .log-message');
        logEntries.forEach(entry => {
            const text = entry.textContent;
            const regex = new RegExp(`(${searchTerm})`, 'gi');
            entry.innerHTML = text.replace(regex, '<span class="search-highlight">$1</span>');
        });
    }
}

// Utility functions
function formatTimestamp(timestamp) {
    const date = new Date(timestamp);
    return date.toLocaleString();
}

function formatFileSize(bytes) {
    if (bytes === 0) return '0 B';
    const k = 1024;
    const sizes = ['B', 'KB', 'MB', 'GB'];
    const i = Math.floor(Math.log(bytes) / Math.log(k));
    return parseFloat((bytes / Math.pow(k, i)).toFixed(2)) + ' ' + sizes[i];
}

function copyToClipboard(text) {
    navigator.clipboard.writeText(text).then(() => {
        showNotification('Copied to clipboard!', 'success');
    }).catch(() => {
        showNotification('Failed to copy to clipboard', 'error');
    });
}

function showNotification(message, type = 'info') {
    const notification = document.createElement('div');
    notification.className = `notification notification-${type}`;
    notification.textContent = message;
    
    notification.style.cssText = `
        position: fixed;
        top: 1rem;
        left: 50%;
        transform: translateX(-50%);
        background: ${type === 'error' ? '#ef4444' : type === 'success' ? '#10b981' : '#3b82f6'};
        color: white;
        padding: 0.75rem 1.5rem;
        border-radius: 0.5rem;
        z-index: 1000;
        box-shadow: 0 4px 6px -1px rgba(0, 0, 0, 0.1);
    `;
    
    document.body.appendChild(notification);
    
    setTimeout(() => {
        notification.remove();
    }, 3000);
}

// Initialize the log viewer when the page loads
document.addEventListener('DOMContentLoaded', () => {
    window.logViewer = new LogViewer();
});

// Export for use in other scripts
window.LogViewer = LogViewer;