// API Configuration
const API_BASE = window.location.hostname === 'localhost'
    ? 'http://localhost:5000'
    : 'https://ytultrahd.onrender.com';

// Global state
const state = {
    currentDownloadId: null,
    downloadHistory: JSON.parse(localStorage.getItem('downloadHistory') || '[]'),
    statusCheckInterval: null
};

// DOM elements
const elements = {
    form: document.getElementById('downloadForm'),
    urlInput: document.getElementById('urlInput'),
    pasteBtn: document.getElementById('pasteBtn'),
    qualitySection: document.getElementById('qualitySection'),
    downloadBtn: document.getElementById('downloadBtn'),
    videoInfo: document.getElementById('videoInfo'),
    progressSection: document.getElementById('progressSection'),
    progressBar: document.getElementById('progressBar'),
    progressPercent: document.getElementById('progressPercent'),
    downloadSpeed: document.getElementById('downloadSpeed'),
    downloadEta: document.getElementById('downloadEta'),
    errorAlert: document.getElementById('errorAlert'),
    errorMessage: document.getElementById('errorMessage')
};

// Initialize
document.addEventListener('DOMContentLoaded', () => {
    initializeEventListeners();
    checkAPIHealth();
});

// Event Listeners
function initializeEventListeners() {
    elements.form.addEventListener('submit', handleFormSubmit);
    elements.pasteBtn.addEventListener('click', handlePaste);
    elements.urlInput.addEventListener('input', handleUrlInput);

    // History button
    const historyBtn = document.getElementById('historyBtn');
    if (historyBtn) {
        historyBtn.addEventListener('click', showHistory);
    }
}

// API Functions
async function apiRequest(endpoint, options = {}) {
    try {
        const response = await fetch(`${API_BASE}${endpoint}`, {
            ...options,
            headers: {
                'Content-Type': 'application/json',
                ...options.headers
            }
        });

        const data = await response.json();

        if (!response.ok) {
            throw new Error(data.error || `HTTP ${response.status}`);
        }

        return data;
    } catch (error) {
        console.error('API Error:', error);
        throw error;
    }
}

async function checkAPIHealth() {
    try {
        const health = await apiRequest('/api/health');
        console.log('API Health:', health);
    } catch (error) {
        showError('Unable to connect to server. Please try again later.');
    }
}

// Form Handling
async function handleFormSubmit(e) {
    e.preventDefault();

    const url = elements.urlInput.value.trim();
    if (!isValidYouTubeUrl(url)) {
        showError('Please enter a valid YouTube URL');
        return;
    }

    hideError();

    // If video info not loaded, fetch it first
    if (elements.videoInfo.classList.contains('d-none')) {
        await fetchVideoInfo(url);
    } else {
        // Start download
        const quality = document.querySelector('input[name="quality"]:checked').value;
        await startDownload(url, quality);
    }
}

async function handlePaste() {
    try {
        const text = await navigator.clipboard.readText();
        elements.urlInput.value = text;
        handleUrlInput();
    } catch (error) {
        // Fallback for browsers that don't support clipboard API
        elements.urlInput.focus();
        document.execCommand('paste');
    }
}

function handleUrlInput() {
    const url = elements.urlInput.value.trim();
    if (isValidYouTubeUrl(url)) {
        elements.downloadBtn.textContent = 'Get Video Info';
        elements.qualitySection.classList.add('d-none');
        elements.videoInfo.classList.add('d-none');
    }
}

// Video Info
async function fetchVideoInfo(url) {
    showLoading();

    try {
        const response = await apiRequest('/api/info', {
            method: 'POST',
            body: JSON.stringify({ url })
        });

        if (response.success) {
            displayVideoInfo(response.data);
            elements.qualitySection.classList.remove('d-none');
            elements.downloadBtn.innerHTML = `
                <svg width="24" height="24" fill="currentColor" class="me-2">
                    <path d="M19 9h-4V3H9v6H5l7 7 7-7zM5 18v2h14v-2H5z"/>
                </svg>
                Start Download
            `;
        } else {
            showError(response.error || 'Failed to fetch video info');
        }
    } catch (error) {
        showError('Failed to fetch video info. Please try again.');
    } finally {
        hideLoading();
    }
}

function displayVideoInfo(info) {
    const html = `
        <div class="video-info-card">
            <div class="row g-3">
                <div class="col-md-4">
                    <img src="${info.thumbnail}" 
                         alt="${escapeHtml(info.title)}" 
                         class="img-fluid rounded"
                         loading="lazy">
                </div>
                <div class="col-md-8">
                    <h5 class="fw-semibold mb-2">${escapeHtml(info.title)}</h5>
                    <p class="text-muted mb-2">
                        <small>
                            By ${escapeHtml(info.uploader)} • 
                            ${formatDuration(info.duration)} • 
                            ${formatNumber(info.view_count)} views
                        </small>
                    </p>
                    <p class="text-muted small mb-0">${escapeHtml(info.description)}</p>
                </div>
            </div>
        </div>
    `;

    elements.videoInfo.innerHTML = html;
    elements.videoInfo.classList.remove('d-none');
}

// Download Functions
async function startDownload(url, quality) {
    try {
        elements.downloadBtn.disabled = true;
        elements.progressSection.classList.remove('d-none');
        resetProgress();

        const response = await apiRequest('/api/download', {
            method: 'POST',
            body: JSON.stringify({ url, quality })
        });

        if (response.success) {
            state.currentDownloadId = response.download_id;
            showToast('Download started!', 'success');

            // Start checking status
            checkDownloadStatus();
            state.statusCheckInterval = setInterval(checkDownloadStatus, 1000);

            // Add to history
            addToHistory({
                id: response.download_id,
                url,
                quality,
                timestamp: Date.now(),
                title: elements.videoInfo.querySelector('h5')?.textContent || 'Unknown'
            });
        } else {
            showError(response.error || 'Failed to start download');
            elements.downloadBtn.disabled = false;
        }
    } catch (error) {
        showError('Failed to start download. Please try again.');
        elements.downloadBtn.disabled = false;
        elements.progressSection.classList.add('d-none');
    }
}

async function checkDownloadStatus() {
    if (!state.currentDownloadId) return;

    try {
        const response = await apiRequest(`/api/status/${state.currentDownloadId}`);

        if (response.success) {
            const status = response.status;

            switch (status.status) {
                case 'downloading':
                    updateProgress(status);
                    break;

                case 'completed':
                    clearInterval(state.statusCheckInterval);
                    completeDownload();
                    break;

                case 'error':
                    clearInterval(state.statusCheckInterval);
                    showError(status.message || 'Download failed');
                    resetDownloadState();
                    break;
            }
        }
    } catch (error) {
        console.error('Status check failed:', error);
    }
}

function updateProgress(status) {
    const progress = status.progress || 0;
    elements.progressBar.style.width = `${progress}%`;
    elements.progressPercent.textContent = `${Math.round(progress)}%`;

    if (status.speed_human) {
        elements.downloadSpeed.textContent = status.speed_human;
    }

    if (status.eta_seconds) {
        elements.downloadEta.textContent = `ETA: ${formatTime(status.eta_seconds)}`;
    }
}

async function completeDownload() {
    elements.progressBar.style.width = '100%';
    elements.progressPercent.textContent = '100%';
    elements.downloadEta.textContent = 'Complete!';

    showToast('Download completed!', 'success');

    // Auto download file
    setTimeout(() => {
        window.location.href = `${API_BASE}/api/file/${state.currentDownloadId}`;
        resetDownloadState();
    }, 1000);
}

// UI Functions
function showLoading() {
    elements.videoInfo.innerHTML = `
        <div class="skeleton-thumbnail"></div>
        <div class="skeleton skeleton-title"></div>
        <div class="skeleton skeleton-text"></div>
        <div class="skeleton skeleton-text" style="width: 80%"></div>
    `;
    elements.videoInfo.classList.remove('d-none');
}

function hideLoading() {
    // Loading is replaced by actual content
}

function showError(message) {
    elements.errorMessage.textContent = message;
    elements.errorAlert.classList.remove('d-none');
}

function hideError() {
    elements.errorAlert.classList.add('d-none');
}

function resetProgress() {
    elements.progressBar.style.width = '0%';
    elements.progressPercent.textContent = '0%';
    elements.downloadSpeed.textContent = '0 MB/s';
    elements.downloadEta.textContent = 'Calculating...';
}

function resetDownloadState() {
    state.currentDownloadId = null;
    elements.downloadBtn.disabled = false;
    elements.progressSection.classList.add('d-none');
    clearInterval(state.statusCheckInterval);
}

function showToast(message, type = 'info') {
    const toast = document.getElementById('toast');
    const toastBody = toast.querySelector('.toast-body');

    toastBody.textContent = message;
    toast.classList.remove('text-bg-danger', 'text-bg-success', 'text-bg-warning');

    if (type === 'error') toast.classList.add('text-bg-danger');
    else if (type === 'success') toast.classList.add('text-bg-success');
    else if (type === 'warning') toast.classList.add('text-bg-warning');

    const bsToast = new bootstrap.Toast(toast);
    bsToast.show();
}

// History Functions
function addToHistory(download) {
    state.downloadHistory.unshift(download);
    if (state.downloadHistory.length > 50) {
        state.downloadHistory = state.downloadHistory.slice(0, 50);
    }
    localStorage.setItem('downloadHistory', JSON.stringify(state.downloadHistory));
}

function showHistory(e) {
    e.preventDefault();
    // Implement history modal
    showToast('History feature coming soon!', 'info');
}

// Utility Functions
function isValidYouTubeUrl(url) {
    const patterns = [
        /^https?:\/\/(www\.)?youtube\.com\/watch\?v=[\w-]+/,
        /^https?:\/\/youtu\.be\/[\w-]+/,
        /^https?:\/\/(www\.)?youtube\.com\/embed\/[\w-]+/,
        /^https?:\/\/m\.youtube\.com\/watch\?v=[\w-]+/
    ];

    return patterns.some(pattern => pattern.test(url));
}

function escapeHtml(text) {
    const div = document.createElement('div');
    div.textContent = text;
    return div.innerHTML;
}

function formatDuration(seconds) {
    if (!seconds) return '0:00';

    const hours = Math.floor(seconds / 3600);
    const minutes = Math.floor((seconds % 3600) / 60);
    const secs = seconds % 60;

    if (hours > 0) {
        return `${hours}:${minutes.toString().padStart(2, '0')}:${secs.toString().padStart(2, '0')}`;
    }
    return `${minutes}:${secs.toString().padStart(2, '0')}`;
}

function formatNumber(num) {
    if (!num) return '0';
    if (num >= 1000000) return `${(num / 1000000).toFixed(1)}M`;
    if (num >= 1000) return `${(num / 1000).toFixed(1)}K`;
    return num.toString();
}

function formatTime(seconds) {
    if (seconds < 60) return `${Math.round(seconds)}s`;
    if (seconds < 3600) return `${Math.round(seconds / 60)}m`;
    return `${Math.round(seconds / 3600)}h`;
}