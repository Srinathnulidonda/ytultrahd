// Privacy-focused analytics module
class Analytics {
    constructor() {
        this.events = [];
        this.sessionId = this.generateSessionId();
        this.startTime = Date.now();
        this.pageViews = 0;

        // Initialize
        this.trackPageView();
        this.setupEventListeners();
        this.startHeartbeat();
    }

    generateSessionId() {
        return `${Date.now()}-${Math.random().toString(36).substr(2, 9)}`;
    }

    // Track page view
    trackPageView() {
        this.pageViews++;
        this.track('page_view', {
            path: window.location.pathname,
            referrer: document.referrer,
            screen: `${window.screen.width}x${window.screen.height}`,
            viewport: `${window.innerWidth}x${window.innerHeight}`,
            deviceType: this.getDeviceType()
        });
    }

    // Track custom events
    track(eventName, data = {}) {
        const event = {
            name: eventName,
            timestamp: Date.now(),
            sessionId: this.sessionId,
            data: {
                ...data,
                userAgent: navigator.userAgent,
                language: navigator.language,
                platform: navigator.platform
            }
        };

        this.events.push(event);

        // Send to backend if batch is full
        if (this.events.length >= 10) {
            this.flush();
        }
    }

    // Track user interactions
    setupEventListeners() {
        // Track download attempts
        document.addEventListener('download_started', (e) => {
            this.track('download_started', {
                url: e.detail.url,
                quality: e.detail.quality
            });
        });

        // Track download completions
        document.addEventListener('download_completed', (e) => {
            this.track('download_completed', {
                downloadId: e.detail.downloadId,
                duration: e.detail.duration,
                fileSize: e.detail.fileSize
            });
        });

        // Track errors
        window.addEventListener('error', (e) => {
            this.track('error', {
                message: e.message,
                source: e.filename,
                line: e.lineno,
                column: e.colno
            });
        });

        // Track performance metrics
        if ('PerformanceObserver' in window) {
            // Largest Contentful Paint
            try {
                const lcpObserver = new PerformanceObserver((list) => {
                    const entries = list.getEntries();
                    const lastEntry = entries[entries.length - 1];
                    this.track('performance_lcp', {
                        value: lastEntry.startTime,
                        element: lastEntry.element?.tagName
                    });
                });
                lcpObserver.observe({ entryTypes: ['largest-contentful-paint'] });
            } catch (e) { }

            // First Input Delay
            try {
                const fidObserver = new PerformanceObserver((list) => {
                    for (const entry of list.getEntries()) {
                        this.track('performance_fid', {
                            value: entry.processingStart - entry.startTime,
                            eventType: entry.name
                        });
                    }
                });
                fidObserver.observe({ entryTypes: ['first-input'] });
            } catch (e) { }
        }

        // Track time on page
        window.addEventListener('beforeunload', () => {
            const timeOnPage = Date.now() - this.startTime;
            this.track('page_unload', {
                timeOnPage,
                pageViews: this.pageViews,
                eventCount: this.events.length
            });
            this.flush();
        });
    }

    // Device detection
    getDeviceType() {
        const ua = navigator.userAgent;
        if (/tablet|ipad|playbook|silk/i.test(ua)) {
            return 'tablet';
        }
        if (/mobile|iphone|ipod|android|blackberry|opera|mini|windows\sce|palm|smartphone|iemobile/i.test(ua)) {
            return 'mobile';
        }
        return 'desktop';
    }

    // Send heartbeat to track active users
    startHeartbeat() {
        setInterval(() => {
            this.track('heartbeat', {
                activeTime: Date.now() - this.startTime,
                pageViews: this.pageViews
            });
        }, 30000); // Every 30 seconds
    }

    // Send events to backend
    async flush() {
        if (this.events.length === 0) return;

        const eventsToSend = [...this.events];
        this.events = [];

        try {
            // Replace with actual analytics endpoint
            if (window.apiClient) {
                await window.apiClient.request('/api/analytics', {
                    method: 'POST',
                    body: JSON.stringify({
                        sessionId: this.sessionId,
                        events: eventsToSend
                    })
                });
            }
        } catch (error) {
            // Re-add events if sending failed
            this.events = [...eventsToSend, ...this.events];
        }
    }

    // Public methods for manual tracking
    trackDownload(url, quality) {
        this.track('download_initiated', { url, quality });
    }

    trackError(error, context) {
        this.track('error_occurred', {
            error: error.message || error,
            context,
            stack: error.stack
        });
    }

    trackTiming(category, variable, time) {
        this.track('timing', { category, variable, time });
    }

    trackSearch(query) {
        this.track('search', { query });
    }
}

// Initialize analytics
const analytics = new Analytics();

// Export for use in other modules
if (typeof window !== 'undefined') {
    window.analytics = analytics;
}

export default analytics;