/**
 * YT Ultra HD - Service Worker
 * Offline support and intelligent caching for maximum performance
 */

const CACHE_NAME = 'yt-ultra-hd-v1.0.0';
const STATIC_CACHE = 'yt-static-v1';
const DYNAMIC_CACHE = 'yt-dynamic-v1';
const API_CACHE = 'yt-api-v1';

// Backend URL
const BACKEND_URL = 'https://ytultrahd.onrender.com';

// Files to cache immediately
const STATIC_ASSETS = [
    '/',
    '/index.html',
    '/about',
    '/contact',
    '/terms',
    '/privacy',
    '/css/critical.css',
    '/css/main.css',
    '/css/components.css',
    '/css/animations.css',
    '/css/responsive.css',
    '/css/print.css',
    '/js/main.js',
    '/js/api.js',
    '/js/theme.js',
    '/js/preloader.js',
    '/js/ui.js',
    '/js/analytics.js',
    '/js/i18n.js',
    '/manifest.json',
    '/favicon.svg',
    '/favicon.png',
    '/apple-touch-icon.png',
    'https://cdn.jsdelivr.net/npm/bootstrap@5.3.2/dist/css/bootstrap.min.css',
    'https://cdn.jsdelivr.net/npm/bootstrap@5.3.2/dist/js/bootstrap.bundle.min.js',
    'https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700;800&display=swap'
];

// API endpoints to cache
const CACHEABLE_API_ENDPOINTS = [
    '/api/health',
    '/api/info'
];

// Cache duration in milliseconds
const CACHE_DURATION = {
    static: 24 * 60 * 60 * 1000,      // 24 hours
    dynamic: 60 * 60 * 1000,          // 1 hour
    api: 10 * 60 * 1000,              // 10 minutes
    health: 30 * 1000                 // 30 seconds
};

// Install event - Cache static assets
self.addEventListener('install', event => {
    console.log('🔧 Service Worker installing...');

    event.waitUntil(
        Promise.all([
            // Cache static assets
            caches.open(STATIC_CACHE).then(cache => {
                console.log('📦 Caching static assets');
                return cache.addAll(STATIC_ASSETS.map(url => {
                    return new Request(url, { cache: 'reload' });
                }));
            }),

            // Initialize other caches
            caches.open(DYNAMIC_CACHE),
            caches.open(API_CACHE)
        ]).then(() => {
            console.log('✅ Service Worker installed successfully');
            // Force activation of new service worker
            return self.skipWaiting();
        }).catch(error => {
            console.error('❌ Service Worker installation failed:', error);
        })
    );
});

// Activate event - Clean up old caches
self.addEventListener('activate', event => {
    console.log('🚀 Service Worker activating...');

    event.waitUntil(
        Promise.all([
            // Take control of all clients
            self.clients.claim(),

            // Clean up old caches
            caches.keys().then(cacheNames => {
                const deletePromises = cacheNames
                    .filter(cacheName => {
                        return cacheName !== STATIC_CACHE &&
                            cacheName !== DYNAMIC_CACHE &&
                            cacheName !== API_CACHE &&
                            cacheName.startsWith('yt-');
                    })
                    .map(cacheName => {
                        console.log('🗑️ Deleting old cache:', cacheName);
                        return caches.delete(cacheName);
                    });

                return Promise.all(deletePromises);
            })
        ]).then(() => {
            console.log('✅ Service Worker activated successfully');
        })
    );
});

// Fetch event - Intelligent caching strategy
self.addEventListener('fetch', event => {
    const requestURL = new URL(event.request.url);

    // Skip non-GET requests
    if (event.request.method !== 'GET') {
        return;
    }

    // Handle different types of requests
    if (requestURL.origin === self.location.origin) {
        // Same-origin requests
        event.respondWith(handleSameOriginRequest(event.request));
    } else if (requestURL.origin === BACKEND_URL) {
        // Backend API requests
        event.respondWith(handleAPIRequest(event.request));
    } else if (requestURL.origin === 'https://cdn.jsdelivr.net' ||
        requestURL.origin === 'https://fonts.googleapis.com' ||
        requestURL.origin === 'https://fonts.gstatic.com') {
        // External CDN requests
        event.respondWith(handleCDNRequest(event.request));
    }
});

// Handle same-origin requests (HTML, CSS, JS)
async function handleSameOriginRequest(request) {
    const url = new URL(request.url);

    try {
        // Check static cache first
        const staticCache = await caches.open(STATIC_CACHE);
        let cachedResponse = await staticCache.match(request);

        if (cachedResponse && await isCacheValid(cachedResponse, CACHE_DURATION.static)) {
            console.log('📦 Serving from static cache:', url.pathname);
            return cachedResponse;
        }

        // Check dynamic cache
        const dynamicCache = await caches.open(DYNAMIC_CACHE);
        cachedResponse = await dynamicCache.match(request);

        if (cachedResponse && await isCacheValid(cachedResponse, CACHE_DURATION.dynamic)) {
            console.log('📦 Serving from dynamic cache:', url.pathname);
            // Update cache in background
            updateCacheInBackground(request, dynamicCache);
            return cachedResponse;
        }

        // Fetch from network
        console.log('🌐 Fetching from network:', url.pathname);
        const networkResponse = await fetch(request);

        if (networkResponse && networkResponse.status === 200) {
            // Cache successful responses
            const responseClone = networkResponse.clone();

            if (isStaticAsset(url.pathname)) {
                staticCache.put(request, responseClone);
            } else {
                dynamicCache.put(request, responseClone);
            }
        }

        return networkResponse;

    } catch (error) {
        console.error('❌ Request failed:', url.pathname, error);

        // Return cached version if available
        const cache = await caches.open(DYNAMIC_CACHE);
        const cachedResponse = await cache.match(request);

        if (cachedResponse) {
            console.log('📦 Serving stale cache due to network error:', url.pathname);
            return cachedResponse;
        }

        // Return offline page for HTML requests
        if (request.headers.get('accept')?.includes('text/html')) {
            return createOfflinePage();
        }

        throw error;
    }
}

// Handle backend API requests with intelligent caching
async function handleAPIRequest(request) {
    const url = new URL(request.url);
    const endpoint = url.pathname;

    try {
        // Special handling for different API endpoints
        if (endpoint === '/api/health') {
            return handleHealthRequest(request);
        } else if (endpoint === '/api/info') {
            return handleInfoRequest(request);
        } else if (endpoint.startsWith('/api/status/')) {
            return handleStatusRequest(request);
        } else if (endpoint.startsWith('/api/download')) {
            return handleDownloadRequest(request);
        } else if (endpoint.startsWith('/api/file/')) {
            return handleFileRequest(request);
        }

        // Default: network-first with cache fallback
        return handleDefaultAPIRequest(request);

    } catch (error) {
        console.error('❌ API request failed:', endpoint, error);

        // Return cached version if available
        const cache = await caches.open(API_CACHE);
        const cachedResponse = await cache.match(request);

        if (cachedResponse) {
            console.log('📦 Serving cached API response:', endpoint);
            return cachedResponse;
        }

        // Return error response
        return new Response(JSON.stringify({
            success: false,
            error: 'Service temporarily unavailable',
            cached: false,
            offline: true
        }), {
            status: 503,
            headers: { 'Content-Type': 'application/json' }
        });
    }
}

// Handle health endpoint with short cache
async function handleHealthRequest(request) {
    const cache = await caches.open(API_CACHE);
    const cachedResponse = await cache.match(request);

    // Use cached response if less than 30 seconds old
    if (cachedResponse && await isCacheValid(cachedResponse, CACHE_DURATION.health)) {
        console.log('📦 Serving cached health status');
        return cachedResponse;
    }

    // Fetch fresh health status
    const networkResponse = await fetch(request);

    if (networkResponse && networkResponse.status === 200) {
        cache.put(request, networkResponse.clone());
        console.log('🌐 Fresh health status cached');
    }

    return networkResponse;
}

// Handle video info requests with smart caching
async function handleInfoRequest(request) {
    const cache = await caches.open(API_CACHE);
    const cachedResponse = await cache.match(request);

    // Use cached response if less than 10 minutes old
    if (cachedResponse && await isCacheValid(cachedResponse, CACHE_DURATION.api)) {
        console.log('📦 Serving cached video info');
        // Update cache in background
        updateCacheInBackground(request, cache);
        return cachedResponse;
    }

    // Fetch fresh video info
    const networkResponse = await fetch(request);

    if (networkResponse && networkResponse.status === 200) {
        cache.put(request, networkResponse.clone());
        console.log('🌐 Fresh video info cached');
    }

    return networkResponse;
}

// Handle status requests (no caching for real-time data)
async function handleStatusRequest(request) {
    console.log('🌐 Fetching real-time status (no cache)');
    return fetch(request);
}

// Handle download requests (no caching)
async function handleDownloadRequest(request) {
    console.log('🌐 Starting download (no cache)');
    return fetch(request);
}

// Handle file downloads (no caching due to size)
async function handleFileRequest(request) {
    console.log('🌐 Streaming file download (no cache)');
    return fetch(request);
}

// Handle default API requests
async function handleDefaultAPIRequest(request) {
    const networkResponse = await fetch(request);

    // Cache successful responses
    if (networkResponse && networkResponse.status === 200) {
        const cache = await caches.open(API_CACHE);
        cache.put(request, networkResponse.clone());
    }

    return networkResponse;
}

// Handle CDN requests with long-term caching
async function handleCDNRequest(request) {
    const cache = await caches.open(STATIC_CACHE);

    try {
        const cachedResponse = await cache.match(request);

        if (cachedResponse) {
            console.log('📦 Serving from CDN cache:', request.url);
            return cachedResponse;
        }

        // Fetch from CDN
        const networkResponse = await fetch(request);

        if (networkResponse && networkResponse.status === 200) {
            cache.put(request, networkResponse.clone());
            console.log('🌐 CDN resource cached:', request.url);
        }

        return networkResponse;

    } catch (error) {
        console.error('❌ CDN request failed:', request.url, error);

        // Return cached version if available
        const cachedResponse = await cache.match(request);
        if (cachedResponse) {
            return cachedResponse;
        }

        throw error;
    }
}

// Update cache in background
function updateCacheInBackground(request, cache) {
    // Don't await this - run in background
    fetch(request).then(response => {
        if (response && response.status === 200) {
            cache.put(request, response.clone());
            console.log('🔄 Background cache update:', request.url);
        }
    }).catch(error => {
        console.log('🔄 Background update failed:', request.url, error.message);
    });
}

// Check if cached response is still valid
async function isCacheValid(response, maxAge) {
    const dateHeader = response.headers.get('date');
    if (!dateHeader) return false;

    const responseDate = new Date(dateHeader);
    const age = Date.now() - responseDate.getTime();

    return age < maxAge;
}

// Check if URL is a static asset
function isStaticAsset(pathname) {
    return pathname.startsWith('/css/') ||
        pathname.startsWith('/js/') ||
        pathname.startsWith('/assets/') ||
        pathname.endsWith('.css') ||
        pathname.endsWith('.js') ||
        pathname.endsWith('.svg') ||
        pathname.endsWith('.png') ||
        pathname.endsWith('.jpg') ||
        pathname.endsWith('.ico') ||
        pathname.endsWith('.webp') ||
        pathname.endsWith('.avif');
}

// Create offline page
function createOfflinePage() {
    const offlineHTML = `
        <!DOCTYPE html>
        <html lang="en" data-theme="light">
        <head>
            <meta charset="UTF-8">
            <meta name="viewport" content="width=device-width, initial-scale=1.0">
            <title>Offline - YT Ultra HD</title>
            <style>
                body {
                    font-family: system-ui, -apple-system, sans-serif;
                    display: flex;
                    align-items: center;
                    justify-content: center;
                    min-height: 100vh;
                    margin: 0;
                    background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
                    color: white;
                    text-align: center;
                }
                .offline-container {
                    max-width: 500px;
                    padding: 2rem;
                }
                .offline-icon {
                    font-size: 4rem;
                    margin-bottom: 1rem;
                }
                h1 {
                    font-size: 2rem;
                    margin-bottom: 1rem;
                }
                p {
                    font-size: 1.1rem;
                    margin-bottom: 2rem;
                    opacity: 0.9;
                }
                .retry-btn {
                    background: white;
                    color: #667eea;
                    border: none;
                    padding: 0.75rem 2rem;
                    border-radius: 0.5rem;
                    font-size: 1rem;
                    font-weight: 600;
                    cursor: pointer;
                    transition: transform 0.2s ease;
                }
                .retry-btn:hover {
                    transform: translateY(-2px);
                }
            </style>
        </head>
        <body>
            <div class="offline-container">
                <div class="offline-icon">📱</div>
                <h1>You're Offline</h1>
                <p>YT Ultra HD is not available right now. Please check your internet connection and try again.</p>
                <button class="retry-btn" onclick="window.location.reload()">
                    Try Again
                </button>
            </div>
        </body>
        </html>
    `;

    return new Response(offlineHTML, {
        status: 200,
        headers: { 'Content-Type': 'text/html' }
    });
}

// Handle background sync (if supported)
self.addEventListener('sync', event => {
    console.log('🔄 Background sync triggered:', event.tag);

    if (event.tag === 'background-cache-update') {
        event.waitUntil(updateCriticalCaches());
    }
});

// Update critical caches in background
async function updateCriticalCaches() {
    try {
        console.log('🔄 Updating critical caches...');

        // Update health status
        const healthResponse = await fetch(`${BACKEND_URL}/api/health`);
        if (healthResponse.ok) {
            const cache = await caches.open(API_CACHE);
            cache.put('/api/health', healthResponse);
            console.log('✅ Health cache updated');
        }

    } catch (error) {
        console.error('❌ Background cache update failed:', error);
    }
}

// Handle push notifications (if implemented later)
self.addEventListener('push', event => {
    if (event.data) {
        const options = {
            body: event.data.text(),
            icon: '/icon-192x192.png',
            badge: '/icon-72x72.png',
            tag: 'yt-ultra-hd-notification',
            requireInteraction: false,
            silent: false
        };

        event.waitUntil(
            self.registration.showNotification('YT Ultra HD', options)
        );
    }
});

// Handle notification clicks
self.addEventListener('notificationclick', event => {
    event.notification.close();

    event.waitUntil(
        self.clients.openWindow('/')
    );
});

// Performance monitoring
self.addEventListener('message', event => {
    if (event.data && event.data.type === 'CACHE_STATS') {
        getCacheStats().then(stats => {
            event.ports[0].postMessage(stats);
        });
    }
});

// Get cache statistics
async function getCacheStats() {
    const cacheNames = await caches.keys();
    const stats = {
        caches: cacheNames.length,
        static: 0,
        dynamic: 0,
        api: 0
    };

    for (const cacheName of cacheNames) {
        const cache = await caches.open(cacheName);
        const keys = await cache.keys();

        if (cacheName === STATIC_CACHE) {
            stats.static = keys.length;
        } else if (cacheName === DYNAMIC_CACHE) {
            stats.dynamic = keys.length;
        } else if (cacheName === API_CACHE) {
            stats.api = keys.length;
        }
    }

    return stats;
}

console.log('🚀 YT Ultra HD Service Worker loaded');