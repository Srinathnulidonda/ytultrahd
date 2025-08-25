// Advanced API Client with caching, retries, and error handling
class APIClient {
    constructor(baseURL) {
        this.baseURL = baseURL || (window.location.hostname === 'localhost'
            ? 'http://localhost:5000'
            : 'https://your-backend-api.com');
        this.cache = new Map();
        this.pendingRequests = new Map();
        this.retryAttempts = 3;
        this.retryDelay = 1000;
        this.timeout = 30000;
    }

    // Request with caching and deduplication
    async request(endpoint, options = {}) {
        const url = `${this.baseURL}${endpoint}`;
        const cacheKey = `${options.method || 'GET'}-${url}-${JSON.stringify(options.body)}`;

        // Check cache for GET requests
        if (options.method === 'GET' || !options.method) {
            const cached = this.getFromCache(cacheKey);
            if (cached) return cached;
        }

        // Deduplicate pending requests
        if (this.pendingRequests.has(cacheKey)) {
            return this.pendingRequests.get(cacheKey);
        }

        // Create request promise
        const requestPromise = this.makeRequest(url, options)
            .then(data => {
                // Cache successful GET responses
                if (options.method === 'GET' || !options.method) {
                    this.setCache(cacheKey, data, options.cacheDuration);
                }
                this.pendingRequests.delete(cacheKey);
                return data;
            })
            .catch(error => {
                this.pendingRequests.delete(cacheKey);
                throw error;
            });

        this.pendingRequests.set(cacheKey, requestPromise);
        return requestPromise;
    }

    // Make actual request with retries
    async makeRequest(url, options, attempt = 1) {
        const controller = new AbortController();
        const timeoutId = setTimeout(() => controller.abort(), this.timeout);

        try {
            const response = await fetch(url, {
                ...options,
                signal: controller.signal,
                headers: {
                    'Content-Type': 'application/json',
                    'Accept': 'application/json',
                    'X-Client-Version': '1.0.0',
                    ...options.headers
                }
            });

            clearTimeout(timeoutId);

            if (!response.ok) {
                const error = await this.parseError(response);
                throw new APIError(error.message, response.status, error);
            }

            const data = await response.json();
            return data;

        } catch (error) {
            clearTimeout(timeoutId);

            // Retry logic
            if (attempt < this.retryAttempts && this.shouldRetry(error)) {
                await this.delay(this.retryDelay * attempt);
                return this.makeRequest(url, options, attempt + 1);
            }

            throw error;
        }
    }

    // Parse error response
    async parseError(response) {
        try {
            const data = await response.json();
            return {
                message: data.error || data.message || `HTTP ${response.status}`,
                code: data.code || response.status,
                details: data
            };
        } catch {
            return {
                message: `HTTP ${response.status}: ${response.statusText}`,
                code: response.status
            };
        }
    }

    // Check if request should be retried
    shouldRetry(error) {
        if (error.name === 'AbortError') return false;
        if (error instanceof APIError) {
            return error.status >= 500 || error.status === 429;
        }
        return true;
    }

    // Cache management
    getFromCache(key) {
        const cached = this.cache.get(key);
        if (cached && cached.expires > Date.now()) {
            return cached.data;
        }
        this.cache.delete(key);
        return null;
    }

    setCache(key, data, duration = 300000) { // 5 minutes default
        this.cache.set(key, {
            data,
            expires: Date.now() + duration
        });

        // Limit cache size
        if (this.cache.size > 100) {
            const firstKey = this.cache.keys().next().value;
            this.cache.delete(firstKey);
        }
    }

    clearCache() {
        this.cache.clear();
    }

    // Utility methods
    delay(ms) {
        return new Promise(resolve => setTimeout(resolve, ms));
    }

    // API methods
    async getVideoInfo(url) {
        return this.request('/api/info', {
            method: 'POST',
            body: JSON.stringify({ url }),
            cacheDuration: 600000 // 10 minutes
        });
    }

    async startDownload(url, quality) {
        return this.request('/api/download', {
            method: 'POST',
            body: JSON.stringify({ url, quality })
        });
    }

    async getDownloadStatus(downloadId) {
        return this.request(`/api/status/${downloadId}`, {
            cacheDuration: 1000 // 1 second cache for status
        });
    }

    async getHealth() {
        return this.request('/api/health', {
            cacheDuration: 60000 // 1 minute
        });
    }

    async getStats() {
        return this.request('/api/stats', {
            cacheDuration: 30000 // 30 seconds
        });
    }
}

// Custom error class
class APIError extends Error {
    constructor(message, status, details) {
        super(message);
        this.name = 'APIError';
        this.status = status;
        this.details = details;
    }
}

// Export singleton instance
const apiClient = new APIClient();

// Browser global
if (typeof window !== 'undefined') {
    window.apiClient = apiClient;
}

// ES6 export
export default apiClient;