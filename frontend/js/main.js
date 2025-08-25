/**
 * YT Ultra HD - Main Application Logic
 * Handles video analysis, download initiation, and UI coordination
 */

class YTUltraHD {
    constructor() {
        this.api = new APIClient();
        this.preloader = new PreloaderManager();
        this.ui = new UIManager();
        this.currentVideoInfo = null;
        this.currentDownloadId = null;
        this.downloadCheckInterval = null;
        this.analytics = window.Analytics || {};

        this.init();
    }

    init() {
        console.log('🚀 YT Ultra HD initialized');
        this.bindEvents();
        this.setupFormValidation();
        this.checkURLParams();
        this.updatePerformanceMetrics();
    }

    bindEvents() {
        // Video URL analysis
        const analyzeBtn = document.getElementById('analyzeBtn');
        const videoUrlInput = document.getElementById('videoUrl');

        if (analyzeBtn) {
            analyzeBtn.addEventListener('click', () => this.analyzeVideo());
        }

        if (videoUrlInput) {
            // Auto-analyze on paste with debounce
            let pasteTimeout;
            videoUrlInput.addEventListener('paste', (e) => {
                clearTimeout(pasteTimeout);
                pasteTimeout = setTimeout(() => {
                    const url = e.target.value.trim();
                    if (this.isValidYouTubeURL(url)) {
                        this.analyzeVideo();
                    }
                }, 500);
            });

            // Enter key support
            videoUrlInput.addEventListener('keypress', (e) => {
                if (e.key === 'Enter') {
                    e.preventDefault();
                    this.analyzeVideo();
                }
            });

            // URL validation on input
            videoUrlInput.addEventListener('input', (e) => {
                this.validateURL(e.target.value);
            });
        }

        // Navbar scroll effect
        this.setupNavbarScroll();

        // Smooth scrolling for anchor links
        this.setupSmoothScrolling();

        // Performance monitoring
        this.setupPerformanceMonitoring();
    }

    async analyzeVideo() {
        const urlInput = document.getElementById('videoUrl');
        const url = urlInput?.value.trim();

        if (!url) {
            this.ui.showAlert('Please enter a YouTube URL', 'warning');
            urlInput?.focus();
            return;
        }

        if (!this.isValidYouTubeURL(url)) {
            this.ui.showAlert('Please enter a valid YouTube URL', 'error');
            urlInput?.focus();
            return;
        }

        try {
            // Track analytics
            this.analytics.track?.('video_analysis_started', { url });

            // Show loading state
            this.setAnalyzeButtonState(true);
            this.preloader.showVideoInfoSkeleton();

            // Analyze video
            console.log('🔍 Analyzing video:', url);
            const response = await this.api.getVideoInfo(url);

            if (response.success) {
                this.currentVideoInfo = response.data;
                this.renderVideoInfo(response.data);
                this.showVideoInfoSection();

                // Track success
                this.analytics.track?.('video_analysis_success', {
                    video_id: response.data.id,
                    title: response.data.title,
                    duration: response.data.duration,
                    cached: response.cached
                });

                // Auto-scroll to video info
                setTimeout(() => {
                    document.getElementById('videoInfoSection')?.scrollIntoView({
                        behavior: 'smooth',
                        block: 'start'
                    });
                }, 300);

            } else {
                throw new Error(response.error || 'Failed to analyze video');
            }

        } catch (error) {
            console.error('❌ Video analysis failed:', error);
            this.ui.showAlert(`Analysis failed: ${error.message}`, 'error');
            this.hideVideoInfoSection();

            // Track error
            this.analytics.track?.('video_analysis_error', {
                error: error.message,
                url
            });

        } finally {
            this.setAnalyzeButtonState(false);
            this.preloader.hideVideoInfoSkeleton();
        }
    }

    renderVideoInfo(videoData) {
        const container = document.getElementById('videoInfoCard');
        if (!container) return;

        // Format duration
        const duration = this.formatDuration(videoData.duration);
        const viewCount = this.formatNumber(videoData.view_count);
        const uploadDate = this.formatDate(videoData.upload_date);

        // Generate quality options
        const qualityOptions = this.generateQualityOptions(videoData.formats);

        container.innerHTML = `
            <div class="row">
                <div class="col-md-4 mb-3">
                    <img src="${videoData.thumbnail}" 
                         alt="${this.escapeHtml(videoData.title)}" 
                         class="video-thumbnail"
                         loading="lazy"
                         onerror="this.src='/assets/video-placeholder.jpg'">
                </div>
                <div class="col-md-8">
                    <h3 class="video-title">${this.escapeHtml(videoData.title)}</h3>
                    <div class="video-meta">
                        <span class="video-meta-item">
                            <i class="fas fa-user"></i>
                            <span>${this.escapeHtml(videoData.uploader)}</span>
                        </span>
                        <span class="video-meta-item">
                            <i class="fas fa-clock"></i>
                            <span>${duration}</span>
                        </span>
                        <span class="video-meta-item">
                            <i class="fas fa-eye"></i>
                            <span>${viewCount} views</span>
                        </span>
                        <span class="video-meta-item">
                            <i class="fas fa-calendar"></i>
                            <span>${uploadDate}</span>
                        </span>
                    </div>
                    <p class="text-muted">${this.escapeHtml(videoData.description)}</p>
                </div>
            </div>
            
            <div class="quality-selector">
                <h5 class="mb-3">Select Quality & Format:</h5>
                <div class="quality-options" id="qualityOptions">
                    ${qualityOptions}
                </div>
            </div>
            
            <div class="d-flex gap-3 flex-wrap">
                <button class="btn btn-primary btn-lg" id="downloadBtn" disabled>
                    <i class="fas fa-download me-2"></i>
                    Download Video
                </button>
                <button class="btn btn-outline-primary btn-lg" id="downloadAudioBtn">
                    <i class="fas fa-music me-2"></i>
                    Download Audio (MP3)
                </button>
                <button class="btn btn-outline-secondary btn-lg" onclick="ytUltraHD.shareVideo()">
                    <i class="fas fa-share me-2"></i>
                    Share
                </button>
            </div>
        `;

        // Add structured data for the video
        this.addVideoStructuredData(videoData);

        // Bind download events
        this.bindDownloadEvents();

        // Bind quality selection
        this.bindQualitySelection();
    }

    generateQualityOptions(formats) {
        if (!formats || formats.length === 0) {
            return `
                <div class="quality-option selected" data-quality="best">
                    <strong>Best Quality</strong>
                    <small>Auto-select best available</small>
                </div>
            `;
        }

        let options = '';
        const defaultQualities = ['4k', '1080p', '720p', '480p'];

        // Add preset quality options
        defaultQualities.forEach(quality => {
            const format = formats.find(f => {
                if (quality === '4k') return f.height >= 2160;
                if (quality === '1080p') return f.height === 1080;
                if (quality === '720p') return f.height === 720;
                if (quality === '480p') return f.height === 480;
                return false;
            });

            if (format || quality === '1080p') { // Always show 1080p as fallback
                const isSelected = quality === '1080p' ? 'selected' : '';
                const fileSize = format?.filesize ? this.formatFileSize(format.filesize) : '';
                const fps = format?.fps ? `${format.fps}fps` : '';

                options += `
                    <div class="quality-option ${isSelected}" data-quality="${quality}">
                        <strong>${quality.toUpperCase()}</strong>
                        <small>${fps} ${fileSize}</small>
                    </div>
                `;
            }
        });

        // Add audio option
        options += `
            <div class="quality-option" data-quality="audio">
                <strong>MP3 Audio</strong>
                <small>High Quality</small>
            </div>
        `;

        return options;
    }

    bindQualitySelection() {
        const qualityOptions = document.querySelectorAll('.quality-option');
        const downloadBtn = document.getElementById('downloadBtn');

        qualityOptions.forEach(option => {
            option.addEventListener('click', () => {
                // Remove previous selections
                qualityOptions.forEach(opt => opt.classList.remove('selected'));

                // Select current option
                option.classList.add('selected');

                // Enable download button
                if (downloadBtn) {
                    downloadBtn.disabled = false;
                }

                // Update button text based on selection
                const quality = option.dataset.quality;
                if (downloadBtn) {
                    if (quality === 'audio') {
                        downloadBtn.innerHTML = `
                            <i class="fas fa-music me-2"></i>
                            Download MP3 Audio
                        `;
                    } else {
                        downloadBtn.innerHTML = `
                            <i class="fas fa-download me-2"></i>
                            Download ${quality.toUpperCase()} Video
                        `;
                    }
                }
            });
        });
    }

    bindDownloadEvents() {
        const downloadBtn = document.getElementById('downloadBtn');
        const downloadAudioBtn = document.getElementById('downloadAudioBtn');

        if (downloadBtn) {
            downloadBtn.addEventListener('click', () => this.startDownload());
        }

        if (downloadAudioBtn) {
            downloadAudioBtn.addEventListener('click', () => this.startDownload('audio'));
        }
    }

    async startDownload(forceQuality = null) {
        if (!this.currentVideoInfo) {
            this.ui.showAlert('Please analyze a video first', 'warning');
            return;
        }

        // Get selected quality
        let quality = forceQuality;
        if (!quality) {
            const selectedOption = document.querySelector('.quality-option.selected');
            quality = selectedOption?.dataset.quality || 'best';
        }

        try {
            // Track download start
            this.analytics.track?.('download_started', {
                video_id: this.currentVideoInfo.id,
                quality: quality,
                title: this.currentVideoInfo.title
            });

            // Show loading state
            this.ui.showAlert('Starting download...', 'info');
            this.showDownloadSection();

            // Start download
            console.log('📥 Starting download:', quality);
            const response = await this.api.startDownload(
                document.getElementById('videoUrl').value.trim(),
                quality
            );

            if (response.success) {
                this.currentDownloadId = response.download_id;
                this.ui.showAlert('Download started successfully!', 'success');

                // Start monitoring progress
                this.startDownloadMonitoring();

                // Scroll to download section
                setTimeout(() => {
                    document.getElementById('downloadSection')?.scrollIntoView({
                        behavior: 'smooth',
                        block: 'start'
                    });
                }, 300);

            } else {
                throw new Error(response.error || 'Failed to start download');
            }

        } catch (error) {
            console.error('❌ Download failed:', error);
            this.ui.showAlert(`Download failed: ${error.message}`, 'error');

            // Track error
            this.analytics.track?.('download_error', {
                error: error.message,
                video_id: this.currentVideoInfo?.id,
                quality: quality
            });
        }
    }

    startDownloadMonitoring() {
        if (!this.currentDownloadId) return;

        // Clear any existing interval
        if (this.downloadCheckInterval) {
            clearInterval(this.downloadCheckInterval);
        }

        // Check status every 2 seconds
        this.downloadCheckInterval = setInterval(async () => {
            try {
                const status = await this.api.getDownloadStatus(this.currentDownloadId);

                if (status.success) {
                    this.updateDownloadProgress(status.status);

                    // Stop monitoring if completed or failed
                    if (status.status.status === 'completed' || status.status.status === 'error') {
                        clearInterval(this.downloadCheckInterval);
                        this.downloadCheckInterval = null;

                        if (status.status.status === 'completed') {
                            this.handleDownloadComplete(status.status);
                        } else {
                            this.handleDownloadError(status.status);
                        }
                    }
                }

            } catch (error) {
                console.error('Status check failed:', error);
                // Don't stop monitoring for network errors
            }
        }, 2000);
    }

    updateDownloadProgress(status) {
        const container = document.getElementById('downloadProgress');
        if (!container) return;

        const progress = status.progress || 0;
        const statusText = this.getStatusText(status.status);
        const speedText = status.speed_human || '';
        const etaText = status.eta_seconds ? this.formatDuration(status.eta_seconds) : '';
        const elapsedText = status.elapsed_seconds ? this.formatDuration(status.elapsed_seconds) : '';

        container.innerHTML = `
            <div class="d-flex justify-content-between align-items-center mb-3">
                <h5 class="mb-0">Download Progress</h5>
                <span class="status-indicator status-${status.status}">${statusText}</span>
            </div>
            
            <div class="progress mb-3" style="height: 12px;">
                <div class="progress-bar" role="progressbar" 
                     style="width: ${progress}%" 
                     aria-valuenow="${progress}" 
                     aria-valuemin="0" 
                     aria-valuemax="100">
                </div>
            </div>
            
            <div class="progress-info">
                <span><strong>${progress.toFixed(1)}%</strong> Complete</span>
                <span>${speedText}</span>
            </div>
            
            <div class="download-stats">
                <div class="stat-item">
                    <span class="stat-value">${speedText}</span>
                    <span class="stat-label">Speed</span>
                </div>
                <div class="stat-item">
                    <span class="stat-value">${etaText || '--'}</span>
                    <span class="stat-label">ETA</span>
                </div>
                <div class="stat-item">
                    <span class="stat-value">${elapsedText || '--'}</span>
                    <span class="stat-label">Elapsed</span>
                </div>
                <div class="stat-item">
                    <span class="stat-value">${this.formatFileSize(status.downloaded_bytes || 0)}</span>
                    <span class="stat-label">Downloaded</span>
                </div>
            </div>
        `;
    }

    handleDownloadComplete(status) {
        const container = document.getElementById('downloadProgress');
        if (!container) return;

        const fileName = status.filename || 'video.mp4';
        const fileSize = this.formatFileSize(status.file_size || 0);
        const downloadTime = this.formatDuration(status.download_time || 0);
        const avgSpeed = status.avg_speed ? this.formatSpeed(status.avg_speed) : '';

        container.innerHTML = `
            <div class="text-center">
                <div class="mb-4">
                    <i class="fas fa-check-circle text-success" style="font-size: 4rem;"></i>
                </div>
                <h4 class="text-success mb-3">Download Complete!</h4>
                <p class="text-muted mb-4">Your video has been downloaded successfully.</p>
                
                <div class="download-stats mb-4">
                    <div class="stat-item">
                        <span class="stat-value">${fileSize}</span>
                        <span class="stat-label">File Size</span>
                    </div>
                    <div class="stat-item">
                        <span class="stat-value">${downloadTime}</span>
                        <span class="stat-label">Download Time</span>
                    </div>
                    <div class="stat-item">
                        <span class="stat-value">${avgSpeed}</span>
                        <span class="stat-label">Avg Speed</span>
                    </div>
                </div>
                
                <div class="d-flex gap-3 justify-content-center flex-wrap">
                    <a href="/api/file/${this.currentDownloadId}" 
                       class="btn btn-success btn-lg" 
                       download="${fileName}">
                        <i class="fas fa-download me-2"></i>
                        Download File (${fileSize})
                    </a>
                    <button class="btn btn-outline-primary btn-lg" onclick="ytUltraHD.downloadAnother()">
                        <i class="fas fa-plus me-2"></i>
                        Download Another
                    </button>
                </div>
            </div>
        `;

        // Track completion
        this.analytics.track?.('download_completed', {
            video_id: this.currentVideoInfo?.id,
            file_size: status.file_size,
            download_time: status.download_time,
            avg_speed: status.avg_speed
        });

        // Show success notification
        this.ui.showAlert('Download completed successfully!', 'success');
    }

    handleDownloadError(status) {
        const container = document.getElementById('downloadProgress');
        if (!container) return;

        container.innerHTML = `
            <div class="text-center">
                <div class="mb-4">
                    <i class="fas fa-exclamation-circle text-danger" style="font-size: 4rem;"></i>
                </div>
                <h4 class="text-danger mb-3">Download Failed</h4>
                <p class="text-muted mb-4">${this.escapeHtml(status.message || 'An error occurred during download.')}</p>
                
                <div class="d-flex gap-3 justify-content-center flex-wrap">
                    <button class="btn btn-primary btn-lg" onclick="ytUltraHD.retryDownload()">
                        <i class="fas fa-redo me-2"></i>
                        Retry Download
                    </button>
                    <button class="btn btn-outline-secondary btn-lg" onclick="ytUltraHD.downloadAnother()">
                        <i class="fas fa-plus me-2"></i>
                        Try Another Video
                    </button>
                </div>
            </div>
        `;

        // Show error notification
        this.ui.showAlert('Download failed. Please try again.', 'error');
    }

    // Utility Methods
    downloadAnother() {
        // Reset state
        this.currentVideoInfo = null;
        this.currentDownloadId = null;

        // Clear forms and sections
        document.getElementById('videoUrl').value = '';
        this.hideVideoInfoSection();
        this.hideDownloadSection();

        // Focus on URL input
        document.getElementById('videoUrl').focus();

        // Scroll to top
        document.getElementById('hero').scrollIntoView({
            behavior: 'smooth',
            block: 'start'
        });
    }

    retryDownload() {
        if (this.currentVideoInfo) {
            this.hideDownloadSection();
            this.startDownload();
        } else {
            this.downloadAnother();
        }
    }

    shareVideo() {
        if (!this.currentVideoInfo) return;

        const shareData = {
            title: `Download: ${this.currentVideoInfo.title}`,
            text: `Download this video in HD quality using YT Ultra HD`,
            url: window.location.href
        };

        if (navigator.share) {
            navigator.share(shareData).catch(console.error);
        } else {
            // Fallback to clipboard
            navigator.clipboard.writeText(shareData.url).then(() => {
                this.ui.showAlert('Link copied to clipboard!', 'success');
            }).catch(() => {
                this.ui.showAlert('Share feature not supported', 'info');
            });
        }
    }

    // UI State Management
    setAnalyzeButtonState(loading) {
        const btn = document.getElementById('analyzeBtn');
        const text = document.getElementById('analyzeText');
        const spinner = document.getElementById('analyzeSpinner');

        if (!btn) return;

        if (loading) {
            btn.disabled = true;
            text.textContent = 'Analyzing...';
            spinner.classList.remove('d-none');
        } else {
            btn.disabled = false;
            text.textContent = 'Analyze Video';
            spinner.classList.add('d-none');
        }
    }

    showVideoInfoSection() {
        const section = document.getElementById('videoInfoSection');
        if (section) {
            section.style.display = 'block';
            section.classList.add('fade-in');
        }
    }

    hideVideoInfoSection() {
        const section = document.getElementById('videoInfoSection');
        if (section) {
            section.style.display = 'none';
        }
    }

    showDownloadSection() {
        const section = document.getElementById('downloadSection');
        if (section) {
            section.style.display = 'block';
            section.classList.add('fade-in');
        }
    }

    hideDownloadSection() {
        const section = document.getElementById('downloadSection');
        if (section) {
            section.style.display = 'none';
        }
    }

    // Validation Methods
    isValidYouTubeURL(url) {
        const patterns = [
            /^https?:\/\/(www\.)?(youtube\.com\/watch\?v=|youtu\.be\/|youtube\.com\/embed\/|youtube\.com\/v\/)/,
            /^https?:\/\/(www\.)?youtube\.com\/playlist\?list=/,
            /^https?:\/\/(www\.)?youtube\.com\/shorts\//
        ];

        return patterns.some(pattern => pattern.test(url));
    }

    validateURL(url) {
        const input = document.getElementById('videoUrl');
        if (!input) return;

        if (url && !this.isValidYouTubeURL(url)) {
            input.classList.add('is-invalid');
        } else {
            input.classList.remove('is-invalid');
        }
    }

    setupFormValidation() {
        const form = document.querySelector('form');
        if (form) {
            form.addEventListener('submit', (e) => {
                e.preventDefault();
                this.analyzeVideo();
            });
        }
    }

    checkURLParams() {
        const urlParams = new URLSearchParams(window.location.search);
        const videoUrl = urlParams.get('url') || urlParams.get('v');

        if (videoUrl && this.isValidYouTubeURL(videoUrl)) {
            document.getElementById('videoUrl').value = videoUrl;
            // Auto-analyze after a short delay
            setTimeout(() => this.analyzeVideo(), 1000);
        }
    }

    // Helper Methods
    formatDuration(seconds) {
        if (!seconds || seconds === 0) return '--';

        const hours = Math.floor(seconds / 3600);
        const minutes = Math.floor((seconds % 3600) / 60);
        const secs = Math.floor(seconds % 60);

        if (hours > 0) {
            return `${hours}:${minutes.toString().padStart(2, '0')}:${secs.toString().padStart(2, '0')}`;
        }
        return `${minutes}:${secs.toString().padStart(2, '0')}`;
    }

    formatNumber(num) {
        if (!num) return '0';
        if (num >= 1000000000) return (num / 1000000000).toFixed(1) + 'B';
        if (num >= 1000000) return (num / 1000000).toFixed(1) + 'M';
        if (num >= 1000) return (num / 1000).toFixed(1) + 'K';
        return num.toString();
    }

    formatFileSize(bytes) {
        if (!bytes || bytes === 0) return '0 B';

        const k = 1024;
        const sizes = ['B', 'KB', 'MB', 'GB', 'TB'];
        const i = Math.floor(Math.log(bytes) / Math.log(k));

        return parseFloat((bytes / Math.pow(k, i)).toFixed(1)) + ' ' + sizes[i];
    }

    formatSpeed(bytesPerSecond) {
        return this.formatFileSize(bytesPerSecond) + '/s';
    }

    formatDate(dateString) {
        if (!dateString) return 'Unknown';

        // Handle YYYYMMDD format
        if (dateString.length === 8) {
            const year = dateString.substring(0, 4);
            const month = dateString.substring(4, 6);
            const day = dateString.substring(6, 8);
            const date = new Date(`${year}-${month}-${day}`);
            return date.toLocaleDateString();
        }

        return new Date(dateString).toLocaleDateString();
    }

    getStatusText(status) {
        const statusMap = {
            'waiting': 'Waiting',
            'starting': 'Starting',
            'downloading': 'Downloading',
            'finalizing': 'Finalizing',
            'completed': 'Completed',
            'error': 'Error'
        };

        return statusMap[status] || status;
    }

    escapeHtml(text) {
        const div = document.createElement('div');
        div.textContent = text;
        return div.innerHTML;
    }

    addVideoStructuredData(videoData) {
        // Remove existing structured data
        const existingScript = document.querySelector('script[type="application/ld+json"][data-video]');
        if (existingScript) {
            existingScript.remove();
        }

        // Add new structured data
        const structuredData = {
            "@context": "https://schema.org",
            "@type": "VideoObject",
            "name": videoData.title,
            "description": videoData.description,
            "thumbnailUrl": videoData.thumbnail,
            "uploadDate": videoData.upload_date,
            "duration": `PT${videoData.duration}S`,
            "author": {
                "@type": "Person",
                "name": videoData.uploader
            },
            "interactionStatistic": {
                "@type": "InteractionCounter",
                "interactionType": { "@type": "WatchAction" },
                "userInteractionCount": videoData.view_count
            }
        };

        const script = document.createElement('script');
        script.type = 'application/ld+json';
        script.setAttribute('data-video', 'true');
        script.textContent = JSON.stringify(structuredData);
        document.head.appendChild(script);
    }

    // Enhanced UI Methods
    setupNavbarScroll() {
        const navbar = document.getElementById('navbar');
        if (!navbar) return;

        let lastScroll = 0;
        window.addEventListener('scroll', () => {
            const currentScroll = window.pageYOffset;

            if (currentScroll > 100) {
                navbar.classList.add('scrolled');
            } else {
                navbar.classList.remove('scrolled');
            }

            lastScroll = currentScroll;
        }, { passive: true });
    }

    setupSmoothScrolling() {
        document.querySelectorAll('a[href^="#"]').forEach(anchor => {
            anchor.addEventListener('click', function (e) {
                e.preventDefault();
                const target = document.querySelector(this.getAttribute('href'));
                if (target) {
                    target.scrollIntoView({
                        behavior: 'smooth',
                        block: 'start'
                    });
                }
            });
        });
    }

    setupPerformanceMonitoring() {
        // Monitor performance metrics
        if ('PerformanceObserver' in window) {
            const observer = new PerformanceObserver((list) => {
                for (const entry of list.getEntries()) {
                    if (entry.entryType === 'navigation') {
                        this.analytics.track?.('page_performance', {
                            loadTime: entry.loadEventEnd - entry.loadEventStart,
                            domContentLoaded: entry.domContentLoadedEventEnd - entry.domContentLoadedEventStart,
                            firstContentfulPaint: entry.loadEventEnd
                        });
                    }
                }
            });

            observer.observe({ entryTypes: ['navigation'] });
        }
    }

    updatePerformanceMetrics() {
        // Update performance metrics in the UI
        if (window.performance && window.performance.memory) {
            const memory = window.performance.memory;
            console.log(`Memory usage: ${(memory.usedJSHeapSize / 1048576).toFixed(2)} MB`);
        }
    }
}

// Initialize application when DOM is ready
document.addEventListener('DOMContentLoaded', () => {
    window.ytUltraHD = new YTUltraHD();
});

// Export for global access
window.YTUltraHD = YTUltraHD;