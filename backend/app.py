# backend/app.py
import os
import json
import time
import asyncio
import threading
import tempfile
import hashlib
import gzip
import io
import multiprocessing
from datetime import datetime, timedelta
from concurrent.futures import ThreadPoolExecutor, ProcessPoolExecutor, as_completed
from functools import lru_cache, wraps
from collections import defaultdict, deque
from queue import Queue, Empty
from pathlib import Path
import gc
import psutil

from flask import Flask, request, jsonify, send_file, Response, g
from flask_cors import CORS
from werkzeug.middleware.proxy_fix import ProxyFix
from werkzeug.serving import WSGIRequestHandler
import yt_dlp
import logging

# Ultra Performance Configuration
CPU_COUNT = multiprocessing.cpu_count()
MAX_WORKERS = min(64, CPU_COUNT * 8)  # Aggressive threading
MAX_PROCESSES = min(16, CPU_COUNT * 2)  # Process pool for CPU intensive tasks
DOWNLOAD_WORKERS = min(32, CPU_COUNT * 4)  # Dedicated download workers
CHUNK_SIZE = 2 * 1024 * 1024  # 2MB chunks for maximum speed
BUFFER_SIZE = 8 * 1024 * 1024  # 8MB buffer
MAX_CONCURRENT_DOWNLOADS = 100  # Support 100 concurrent downloads
MAX_FILE_SIZE = 10 * 1024 * 1024 * 1024  # 10GB limit
TEMP_DIR = os.path.join(tempfile.gettempdir(), 'yt_ultra')
CACHE_DIR = os.path.join(tempfile.gettempdir(), 'yt_cache_ultra')
REDIS_LIKE_CACHE = {}  # In-memory ultra-fast cache
FILE_RETENTION_TIME = 3600  # 1 hour retention
CACHE_DURATION = 1800  # 30 minutes cache

# Cookie Configuration - Change these based on your preference
USE_COOKIES = True  # Enable/disable cookie usage
COOKIES_BROWSER = 'firefox'  # Options: 'firefox', 'chrome', 'edge', 'safari', 'chromium', 'brave', 'opera', 'vivaldi'
COOKIES_FILE_PATH = None  # Set to '/path/to/cookies.txt' if you have a cookies file

# Create optimized directories
os.makedirs(TEMP_DIR, exist_ok=True)
os.makedirs(CACHE_DIR, exist_ok=True)

# Configure ultra-fast logging
logging.basicConfig(
    level=logging.WARNING,  # Minimal logging for speed
    format='%(levelname)s: %(message)s',
    handlers=[logging.StreamHandler()]
)
logger = logging.getLogger(__name__)
logging.getLogger('yt_dlp').setLevel(logging.CRITICAL)

app = Flask(__name__)
CORS(app, 
     origins="*",
     methods=["GET", "POST", "OPTIONS"],
     allow_headers=["Content-Type", "Authorization", "X-Requested-With"],
     supports_credentials=False,
     max_age=86400)  # Cache preflight for 24 hours

# Ultra performance middleware
app.wsgi_app = ProxyFix(app.wsgi_app, x_for=1, x_proto=1, x_host=1, x_prefix=1)

# Global ultra-fast data structures
executor = ThreadPoolExecutor(max_workers=MAX_WORKERS, thread_name_prefix='API')
process_executor = ProcessPoolExecutor(max_workers=MAX_PROCESSES)
download_executor = ThreadPoolExecutor(max_workers=DOWNLOAD_WORKERS, thread_name_prefix='DL')

# Ultra-fast in-memory storage
download_status = {}  # Main status store
download_queue = Queue(maxsize=MAX_CONCURRENT_DOWNLOADS * 2)  # Download queue
active_downloads = {}  # Active download tracking
user_requests = defaultdict(deque)  # Rate limiting per user
performance_metrics = {
    'total_requests': 0,
    'active_downloads': 0,
    'cache_hits': 0,
    'cache_misses': 0,
    'avg_response_time': 0,
    'peak_concurrent': 0
}

def get_cookie_options():
    """Get cookie options for yt-dlp to bypass bot detection"""
    cookie_opts = {}
    
    if not USE_COOKIES:
        return cookie_opts
    
    # Option 1: Use cookies file if provided and exists
    if COOKIES_FILE_PATH and os.path.exists(COOKIES_FILE_PATH):
        cookie_opts['cookiefile'] = COOKIES_FILE_PATH
        logger.info(f"Using cookies from file: {COOKIES_FILE_PATH}")
    
    # Option 2: Extract from browser
    elif COOKIES_BROWSER:
        try:
            # Try to extract cookies from the specified browser
            cookie_opts['cookiesfrombrowser'] = (COOKIES_BROWSER,)
            logger.info(f"Extracting cookies from browser: {COOKIES_BROWSER}")
        except Exception as e:
            logger.warning(f"Failed to extract cookies from {COOKIES_BROWSER}: {e}")
            # Try alternative browsers as fallback
            fallback_browsers = ['firefox', 'chrome', 'edge', 'safari']
            for browser in fallback_browsers:
                if browser != COOKIES_BROWSER:
                    try:
                        cookie_opts['cookiesfrombrowser'] = (browser,)
                        logger.info(f"Using fallback browser for cookies: {browser}")
                        break
                    except:
                        continue
    
    return cookie_opts

class UltraFastProgressHook:
    """Ultra-optimized progress hook with minimal CPU overhead"""
    __slots__ = ('download_id', 'last_update', 'update_count')
    
    def __init__(self, download_id):
        self.download_id = download_id
        self.last_update = 0
        self.update_count = 0
        
    def __call__(self, d):
        # Ultra-fast progress updates - only every 1s and every 10th call
        current_time = time.time()
        self.update_count += 1
        
        # Aggressive throttling for performance
        if (current_time - self.last_update < 1.0) and (self.update_count % 10 != 0):
            return
        
        self.last_update = current_time
        
        try:
            status = download_status.get(self.download_id)
            if not status:
                return
                
            if d['status'] == 'downloading':
                total = d.get('total_bytes') or d.get('total_bytes_estimate', 0)
                downloaded = d.get('downloaded_bytes', 0)
                
                progress = (downloaded / total * 100) if total > 0 else 0
                speed = d.get('speed', 0) or 0
                
                # Ultra-fast status update
                status.update({
                    'status': 'downloading',
                    'progress': round(progress, 1),
                    'speed': speed,
                    'eta': d.get('eta', 0),
                    'downloaded_bytes': downloaded,
                    'total_bytes': total
                })
                
                # Update global metrics
                performance_metrics['active_downloads'] = len([
                    s for s in download_status.values() 
                    if s.get('status') == 'downloading'
                ])
                
            elif d['status'] == 'finished':
                status.update({
                    'status': 'finalizing',
                    'progress': 98,
                    'message': 'Finalizing...'
                })
                
        except Exception:
            pass  # Ignore errors for maximum speed

def ultra_gzip_response(f):
    """Ultra-fast response compression"""
    @wraps(f)
    def decorated(*args, **kwargs):
        result = f(*args, **kwargs)
        
        # Quick response size check
        if isinstance(result, tuple):
            data, status_code = result
        else:
            data, status_code = result, 200
            
        if isinstance(data, dict):
            json_str = json.dumps(data, separators=(',', ':'))
            
            # Only compress large responses
            if len(json_str) > 512 and 'gzip' in request.headers.get('Accept-Encoding', ''):
                compressed = gzip.compress(json_str.encode(), compresslevel=1)  # Fast compression
                response = Response(compressed, status=status_code, mimetype='application/json')
                response.headers.update({
                    'Content-Encoding': 'gzip',
                    'Content-Length': len(compressed),
                    'Cache-Control': 'public, max-age=300'  # 5 minute cache
                })
                return response
            
            return jsonify(data), status_code
        return result
    return decorated

@lru_cache(maxsize=10000)
def get_ultra_cache_key(url: str) -> str:
    """Ultra-fast cache key generation"""
    return hashlib.md5(url.encode()).hexdigest()[:16]  # Shorter hash for speed

def get_redis_like_cache(key: str):
    """Ultra-fast in-memory cache (Redis-like)"""
    if key in REDIS_LIKE_CACHE:
        data, timestamp = REDIS_LIKE_CACHE[key]
        if time.time() - timestamp < CACHE_DURATION:
            performance_metrics['cache_hits'] += 1
            return data
        else:
            del REDIS_LIKE_CACHE[key]  # Auto cleanup expired
    
    performance_metrics['cache_misses'] += 1
    return None

def set_redis_like_cache(key: str, data):
    """Ultra-fast cache storage"""
    REDIS_LIKE_CACHE[key] = (data, time.time())
    
    # Prevent memory bloat - keep only latest 1000 entries
    if len(REDIS_LIKE_CACHE) > 1000:
        oldest_keys = sorted(REDIS_LIKE_CACHE.keys(), 
                           key=lambda k: REDIS_LIKE_CACHE[k][1])[:100]
        for old_key in oldest_keys:
            del REDIS_LIKE_CACHE[old_key]

def get_ultra_optimized_ydl_opts(quality: str, download_id: str) -> dict:
    """Ultra-optimized yt-dlp configuration for maximum speed with cookie support"""
    timestamp = int(time.time())
    output_path = os.path.join(TEMP_DIR, f'ultra_{download_id}_{timestamp}.%(ext)s')
    
    # Ultra-performance base configuration
    opts = {
        'outtmpl': output_path,
        'format_sort': ['res:2160', 'fps:60', 'vcodec:av01', 'acodec:opus', 'source'],
        'merge_output_format': 'mp4',
        'concurrent_fragment_downloads': min(16, MAX_WORKERS // 4),  # Balanced concurrency
        'http_chunk_size': CHUNK_SIZE,
        'buffersize': BUFFER_SIZE,
        'retries': 3,  # Slightly more retries for reliability
        'fragment_retries': 3,
        'socket_timeout': 30,
        'keep_fragments': False,  # Don't keep fragments
        'writeinfojson': False,
        'writesubtitles': False,
        'writeautomaticsub': False,
        'writethumbnail': False,
        'writedescription': False,
        'ignoreerrors': False,
        'no_warnings': True,
        'quiet': True,
        'progress_hooks': [UltraFastProgressHook(download_id)],
        'http_headers': {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
            'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,image/apng,*/*;q=0.8',
            'Accept-Language': 'en-US,en;q=0.9',
            'Accept-Encoding': 'gzip, deflate, br',
            'DNT': '1',
            'Connection': 'keep-alive',
            'Upgrade-Insecure-Requests': '1',
            'Sec-Fetch-Dest': 'document',
            'Sec-Fetch-Mode': 'navigate',
            'Sec-Fetch-Site': 'none',
            'Sec-Fetch-User': '?1',
            'Cache-Control': 'max-age=0',
        },
        'extractor_args': {
            'youtube': {
                'player_client': ['android', 'web'],  # Use multiple clients for reliability
                'player_skip': ['webpage', 'configs'],
                'skip': ['dash', 'hls']  # Skip slower formats
            }
        }
    }
    
    # Add cookie options for authentication
    cookie_opts = get_cookie_options()
    opts.update(cookie_opts)
    
    # Ultra-fast format selection
    format_map = {
        'best': 'bestvideo[height<=2160][fps<=60]+bestaudio[abr>=128]/best[height<=2160]',
        '4k': 'bestvideo[height=2160][fps<=60]+bestaudio[abr>=192]/bestvideo[height<=2160]+bestaudio',
        '1080p': 'bestvideo[height=1080][fps<=60]+bestaudio[abr>=128]/best[height<=1080]',
        '720p': 'bestvideo[height=720]+bestaudio[abr>=96]/best[height<=720]',
        '480p': 'bestvideo[height=480]+bestaudio/best[height<=480]',
        'audio': 'bestaudio[abr>=192]/bestaudio[abr>=128]/bestaudio'
    }
    
    opts['format'] = format_map.get(quality, format_map['best'])
    
    if quality == 'audio':
        opts['postprocessors'] = [{
            'key': 'FFmpegExtractAudio',
            'preferredcodec': 'mp3',
            'preferredquality': '320'
        }]
    
    return opts

def ultra_extract_info(url: str) -> dict:
    """Ultra-fast info extraction with cookie support"""
    ydl_opts = {
        'quiet': True,
        'no_warnings': True,
        'extract_flat': False,
        'force_json': True,
        'skip_download': True,
        'extractor_args': {
            'youtube': {
                'player_client': ['android', 'web'],  # Use multiple clients
                'player_skip': ['webpage', 'configs', 'initial_data']
            }
        },
        'http_headers': {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
            'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,image/apng,*/*;q=0.8',
            'Accept-Language': 'en-US,en;q=0.9',
            'Accept-Encoding': 'gzip, deflate, br',
            'DNT': '1',
            'Connection': 'keep-alive',
            'Upgrade-Insecure-Requests': '1',
        }
    }
    
    # Add cookie options for authentication
    cookie_opts = get_cookie_options()
    ydl_opts.update(cookie_opts)
    
    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
        return ydl.extract_info(url, download=False)

def process_info_ultra_fast(info: dict) -> dict:
    """Ultra-fast info processing with minimal overhead"""
    # Only extract essential data
    processed = {
        'title': (info.get('title', '') or 'Unknown')[:80],
        'duration': info.get('duration', 0),
        'uploader': (info.get('uploader', '') or 'Unknown')[:30],
        'view_count': info.get('view_count', 0),
        'upload_date': info.get('upload_date', ''),
        'thumbnail': info.get('thumbnail', ''),
        'id': info.get('id', ''),
        'description': (info.get('description', '') or '')[:200] + '...'
    }
    
    # Ultra-fast format processing - only top qualities
    if 'formats' in info and info['formats']:
        quality_formats = []
        seen_heights = set()
        
        # Sort by quality and take only unique heights
        sorted_formats = sorted(
            [f for f in info['formats'] if f.get('height')], 
            key=lambda x: x.get('height', 0), 
            reverse=True
        )
        
        for fmt in sorted_formats[:8]:  # Only top 8 formats
            height = fmt.get('height', 0)
            if height not in seen_heights and height >= 240:
                seen_heights.add(height)
                quality_formats.append({
                    'height': height,
                    'fps': fmt.get('fps', 0),
                    'ext': fmt.get('ext', 'mp4'),
                    'filesize': fmt.get('filesize', 0)
                })
        
        processed['formats'] = quality_formats[:5]  # Max 5 formats
    else:
        processed['formats'] = []
    
    return processed

async def ultra_download_async(url: str, quality: str, download_id: str):
    """Ultra-fast asynchronous download with maximum concurrency"""
    loop = asyncio.get_event_loop()
    
    def download_worker():
        try:
            # Initialize ultra-fast status
            download_status[download_id] = {
                'status': 'starting',
                'progress': 0,
                'start_time': time.time(),
                'message': 'Initializing ultra-fast download...'
            }
            
            opts = get_ultra_optimized_ydl_opts(quality, download_id)
            
            # Update to downloading
            download_status[download_id]['status'] = 'downloading'
            download_status[download_id]['message'] = 'Ultra-fast download in progress...'
            
            # Execute download with maximum performance
            with yt_dlp.YoutubeDL(opts) as ydl:
                ydl.download([url])
            
            # Find downloaded file ultra-fast
            prefix = f'ultra_{download_id}_'
            downloaded_file = None
            
            for file in os.listdir(TEMP_DIR):
                if file.startswith(prefix) and not file.endswith(('.part', '.info.json')):
                    downloaded_file = os.path.join(TEMP_DIR, file)
                    break
            
            if not downloaded_file or not os.path.exists(downloaded_file):
                raise Exception("Download completed but file not found")
            
            file_size = os.path.getsize(downloaded_file)
            
            if file_size > MAX_FILE_SIZE:
                os.remove(downloaded_file)
                raise Exception(f'File exceeds limit: {file_size / (1024**3):.1f}GB')
            
            # Success status
            end_time = time.time()
            download_time = end_time - download_status[download_id]['start_time']
            avg_speed = file_size / download_time if download_time > 0 else 0
            
            download_status[download_id] = {
                'status': 'completed',
                'progress': 100,
                'message': 'Ultra-fast download completed!',
                'file_path': downloaded_file,
                'file_size': file_size,
                'filename': os.path.basename(downloaded_file),
                'download_time': download_time,
                'avg_speed': avg_speed,
                'completion_time': end_time
            }
            
            return downloaded_file
            
        except Exception as e:
            error_msg = str(e)
            # Provide helpful error messages for common issues
            if 'Sign in to confirm' in error_msg:
                error_msg = "YouTube requires authentication. Please check cookie configuration."
            elif '429' in error_msg:
                error_msg = "Too many requests. Please try again later."
            elif 'Video unavailable' in error_msg:
                error_msg = "This video is unavailable or private."
            
            download_status[download_id] = {
                'status': 'error',
                'message': error_msg[:150],
                'error_time': time.time()
            }
            raise
    
    return await loop.run_in_executor(download_executor, download_worker)

def ultra_cleanup():
    """Ultra-fast cleanup with minimal system impact"""
    try:
        current_time = time.time()
        cleaned = 0
        
        # Clean temp files
        for file in os.listdir(TEMP_DIR):
            if file.startswith('ultra_'):
                file_path = os.path.join(TEMP_DIR, file)
                try:
                    if current_time - os.path.getctime(file_path) > FILE_RETENTION_TIME:
                        os.remove(file_path)
                        cleaned += 1
                except:
                    pass
        
        # Clean old download status (keep only last 1000)
        if len(download_status) > 1000:
            old_downloads = sorted(download_status.items(), 
                                 key=lambda x: x[1].get('start_time', 0))[:200]
            for download_id, _ in old_downloads:
                # Remove old file if exists
                if 'file_path' in download_status[download_id]:
                    try:
                        file_path = download_status[download_id]['file_path']
                        if os.path.exists(file_path):
                            os.remove(file_path)
                    except:
                        pass
                del download_status[download_id]
        
        # Force garbage collection for memory optimization
        if cleaned > 10:
            gc.collect()
            
    except Exception:
        pass

def start_ultra_cleanup_thread():
    """Ultra-fast cleanup thread"""
    def cleanup_worker():
        while True:
            try:
                ultra_cleanup()
                time.sleep(900)  # Every 15 minutes
            except Exception:
                time.sleep(300)  # Wait 5 minutes on error
    
    thread = threading.Thread(target=cleanup_worker, daemon=True)
    thread.start()

# Performance monitoring
def update_performance_metrics():
    """Update performance metrics"""
    performance_metrics['total_requests'] += 1
    current_active = len([s for s in download_status.values() if s.get('status') == 'downloading'])
    performance_metrics['peak_concurrent'] = max(performance_metrics['peak_concurrent'], current_active)

# Ultra-fast API routes
@app.route('/')
@ultra_gzip_response
def index():
    cookie_status = "Enabled" if USE_COOKIES else "Disabled"
    cookie_method = f"Browser: {COOKIES_BROWSER}" if COOKIES_BROWSER and not COOKIES_FILE_PATH else "File"
    
    return {
        'name': 'YT Downloader Ultra Pro',
        'version': '3.0',
        'status': 'ultra-operational',
        'cookie_auth': {
            'status': cookie_status,
            'method': cookie_method
        },
        'performance': {
            'max_concurrent_downloads': MAX_CONCURRENT_DOWNLOADS,
            'max_workers': MAX_WORKERS,
            'chunk_size_mb': CHUNK_SIZE // (1024**2),
            'buffer_size_mb': BUFFER_SIZE // (1024**2),
            'active_downloads': len([s for s in download_status.values() if s.get('status') == 'downloading']),
            'cache_hit_rate': f"{(performance_metrics['cache_hits'] / max(performance_metrics['cache_hits'] + performance_metrics['cache_misses'], 1) * 100):.1f}%",
            'total_requests': performance_metrics['total_requests'],
            'peak_concurrent': performance_metrics['peak_concurrent']
        },
        'features': [
            'Ultra-fast API responses (<50ms)',
            'Superfast downloads up to 4K',
            'Massive concurrent user support (100+)',
            'Advanced download acceleration',
            'In-memory ultra-cache',
            'Multi-threaded processing',
            'YouTube authentication bypass'
        ]
    }

@app.route('/api/health')
@ultra_gzip_response
def health():
    cpu_percent = psutil.cpu_percent()
    memory_percent = psutil.virtual_memory().percent
    
    return {
        'status': 'ultra-healthy',
        'timestamp': int(time.time()),
        'cookie_auth': USE_COOKIES,
        'system': {
            'cpu_usage': f"{cpu_percent:.1f}%",
            'memory_usage': f"{memory_percent:.1f}%",
            'active_downloads': len([s for s in download_status.values() if s.get('status') == 'downloading']),
            'total_downloads': len(download_status),
            'cache_size': len(REDIS_LIKE_CACHE)
        },
        'performance': performance_metrics
    }

@app.route('/api/info', methods=['POST'])
@ultra_gzip_response
def get_info():
    start_time = time.time()
    update_performance_metrics()
    
    try:
        data = request.get_json(force=True, silent=True)
        if not data or 'url' not in data:
            return {'success': False, 'error': 'URL required'}, 400
        
        url = data['url'].strip()
        cache_key = get_ultra_cache_key(url)
        
        # Ultra-fast cache check
        cached = get_redis_like_cache(cache_key)
        if cached:
            response_time = (time.time() - start_time) * 1000
            return {
                'success': True,
                'data': cached,
                'cached': True,
                'response_time_ms': round(response_time, 1)
            }
        
        # Extract info in thread pool for non-blocking
        future = executor.submit(ultra_extract_info, url)
        info = future.result(timeout=15)  # 15s timeout for cookie auth
        
        processed = process_info_ultra_fast(info)
        set_redis_like_cache(cache_key, processed)
        
        response_time = (time.time() - start_time) * 1000
        return {
            'success': True,
            'data': processed,
            'cached': False,
            'response_time_ms': round(response_time, 1)
        }
        
    except Exception as e:
        error_msg = str(e)
        if 'Sign in to confirm' in error_msg:
            error_msg = "YouTube requires authentication. Cookie configuration may be needed."
        
        return {
            'success': False,
            'error': error_msg[:100],
            'response_time_ms': round((time.time() - start_time) * 1000, 1)
        }, 400

@app.route('/api/download', methods=['POST'])
@ultra_gzip_response
def start_download():
    start_time = time.time()
    update_performance_metrics()
    
    try:
        data = request.get_json(force=True, silent=True)
        if not data or 'url' not in data:
            return {'success': False, 'error': 'URL required'}, 400
        
        # Check if we're at capacity
        active_count = len([s for s in download_status.values() if s.get('status') == 'downloading'])
        if active_count >= MAX_CONCURRENT_DOWNLOADS:
            return {
                'success': False, 
                'error': f'Server at capacity. Active downloads: {active_count}/{MAX_CONCURRENT_DOWNLOADS}',
                'retry_after': 30
            }, 429
        
        url = data['url'].strip()
        quality = data.get('quality', 'best')
        download_id = f"{int(time.time() * 1000000)}"  # Microsecond precision
        
        # Start ultra-fast background download
        def download_starter():
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            try:
                loop.run_until_complete(ultra_download_async(url, quality, download_id))
            except Exception as e:
                logger.error(f"Download error for {download_id}: {e}")
            finally:
                loop.close()
        
        thread = threading.Thread(target=download_starter, daemon=True)
        thread.start()
        active_downloads[download_id] = thread
        
        response_time = (time.time() - start_time) * 1000
        return {
            'success': True,
            'download_id': download_id,
            'message': 'Ultra-fast download initiated',
            'estimated_start': '<5 seconds',
            'response_time_ms': round(response_time, 1)
        }
        
    except Exception as e:
        return {
            'success': False,
            'error': str(e)[:100],
            'response_time_ms': round((time.time() - start_time) * 1000, 1)
        }, 400

@app.route('/api/status/<download_id>')
@ultra_gzip_response
def get_status(download_id):
    if download_id not in download_status:
        return {'success': False, 'error': 'Download not found'}, 404
    
    status = download_status[download_id].copy()
    
    # Add computed fields
    if 'start_time' in status:
        elapsed = time.time() - status['start_time']
        status['elapsed_seconds'] = round(elapsed, 1)
        
        # Calculate ETA and speed metrics
        if status.get('progress', 0) > 5 and elapsed > 5:  # After 5% and 5 seconds
            estimated_total = elapsed / (status['progress'] / 100)
            status['estimated_total_time'] = round(estimated_total, 1)
            status['eta_seconds'] = round(max(0, estimated_total - elapsed), 1)
    
    # Remove sensitive data
    status.pop('file_path', None)
    
    # Add speed in different units
    if 'speed' in status and status['speed']:
        speed_bps = status['speed']
        status['speed_mbps'] = round(speed_bps * 8 / (1024**2), 2)
        status['speed_human'] = f"{round(speed_bps / (1024**2), 1)} MB/s"
    
    return {
        'success': True,
        'status': status
    }

@app.route('/api/file/<download_id>')
def download_file(download_id):
    if download_id not in download_status:
        return jsonify({'error': 'Download not found'}), 404
    
    status = download_status[download_id]
    if status.get('status') != 'completed':
        return jsonify({'error': 'Download not ready'}), 400
    
    file_path = status.get('file_path')
    if not file_path or not os.path.exists(file_path):
        return jsonify({'error': 'File not available'}), 404
    
    try:
        # Ultra-fast file streaming
        def ultra_stream():
            with open(file_path, 'rb') as f:
                while True:
                    chunk = f.read(CHUNK_SIZE)
                    if not chunk:
                        break
                    yield chunk
        
        filename = status.get('filename', f'video_{download_id}.mp4')
        file_size = status.get('file_size', os.path.getsize(file_path))
        
        return Response(
            ultra_stream(),
            headers={
                'Content-Disposition': f'attachment; filename="{filename}"',
                'Content-Type': 'application/octet-stream',
                'Content-Length': str(file_size),
                'Accept-Ranges': 'bytes',
                'Cache-Control': 'no-cache, must-revalidate',
                'X-Accel-Buffering': 'no'  # Nginx optimization
            }
        )
    except Exception as e:
        return jsonify({'error': 'Streaming failed'}), 500

# Performance middleware
@app.before_request
def before_request():
    g.start_time = time.time()

@app.after_request
def after_request(response):
    if hasattr(g, 'start_time'):
        duration_ms = (time.time() - g.start_time) * 1000
        response.headers['X-Response-Time'] = f'{duration_ms:.1f}ms'
        
        # Update average response time
        current_avg = performance_metrics.get('avg_response_time', 0)
        total_requests = performance_metrics.get('total_requests', 1)
        new_avg = ((current_avg * (total_requests - 1)) + duration_ms) / total_requests
        performance_metrics['avg_response_time'] = round(new_avg, 2)
    
    # Ultra-performance headers
    response.headers.update({
        'X-Content-Type-Options': 'nosniff',
        'X-Frame-Options': 'DENY',
        'X-XSS-Protection': '1; mode=block',
        'Cache-Control': 'public, max-age=300',
        'Server': 'YT-Ultra/3.0'
    })
    
    return response

# Error handlers
@app.errorhandler(404)
def not_found(e):
    return jsonify({'error': 'Endpoint not found', 'code': 404}), 404

@app.errorhandler(429)
def rate_limit_exceeded(e):
    return jsonify({'error': 'Rate limit exceeded', 'code': 429}), 429

@app.errorhandler(500)
def internal_error(e):
    return jsonify({'error': 'Internal server error', 'code': 500}), 500

if __name__ == '__main__':
    # Start ultra-fast cleanup
    start_ultra_cleanup_thread()
    
    # Ultra-performance WSGI configuration
    WSGIRequestHandler.protocol_version = "HTTP/1.1"
    
    # Production settings
    port = int(os.environ.get('PORT', 5000))
    
    # Display configuration
    print(f"""
🚀 YT Downloader Ultra Pro Starting...
📊 Max Workers: {MAX_WORKERS}
⚡ Max Concurrent Downloads: {MAX_CONCURRENT_DOWNLOADS}  
🎯 Chunk Size: {CHUNK_SIZE // (1024**2)}MB
💾 Buffer Size: {BUFFER_SIZE // (1024**2)}MB
🔥 Ultra-Performance Mode: ENABLED
🍪 Cookie Authentication: {USE_COOKIES}
🌐 Cookie Browser: {COOKIES_BROWSER if USE_COOKIES else 'N/A'}
📁 Cookie File: {'Configured' if COOKIES_FILE_PATH else 'Not Set'}

⚠️  Cookie Configuration:
   - To use cookies from browser: Set COOKIES_BROWSER = 'firefox' (or chrome/edge)
   - To use cookies file: Set COOKIES_FILE_PATH = '/path/to/cookies.txt'
   - To disable cookies: Set USE_COOKIES = False
    """)
    
    app.run(
        host='0.0.0.0',
        port=port,
        debug=False,
        threaded=True,
        use_reloader=False,
        use_debugger=False,
        processes=1  # Single process with many threads for optimal performance
    )