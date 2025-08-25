# backend/app.py
import os
import json
import time
import asyncio
import threading
import tempfile
import hashlib
import gzip
import mmap
import pickle
import multiprocessing
import random
import subprocess
from datetime import datetime, timedelta
from concurrent.futures import ThreadPoolExecutor, ProcessPoolExecutor
from functools import lru_cache, wraps
from collections import defaultdict, deque
from typing import Optional, Dict, Any
import gc
import psutil
import uvloop

from flask import Flask, request, jsonify, send_file, Response, g, stream_with_context
from flask_cors import CORS
from werkzeug.middleware.proxy_fix import ProxyFix
from werkzeug.serving import WSGIRequestHandler
import yt_dlp
import logging
import aiofiles
import orjson
from cachetools import TTLCache, LFUCache
import xxhash

# Install uvloop for maximum async performance
asyncio.set_event_loop_policy(uvloop.EventLoopPolicy())

# ============= CONFIGURATION =============
CPU_COUNT = multiprocessing.cpu_count()
MAX_WORKERS = min(128, CPU_COUNT * 16)
MAX_PROCESSES = min(32, CPU_COUNT * 4)
DOWNLOAD_WORKERS = min(64, CPU_COUNT * 8)
CHUNK_SIZE = 4 * 1024 * 1024
BUFFER_SIZE = 16 * 1024 * 1024
MAX_CONCURRENT_DOWNLOADS = 200
MAX_FILE_SIZE = 20 * 1024 * 1024 * 1024
TEMP_DIR = os.path.join(tempfile.gettempdir(), 'yt_ultra_pro')
CACHE_DIR = os.path.join(tempfile.gettempdir(), 'yt_cache_ultra_pro')
FILE_RETENTION_TIME = 7200
CACHE_DURATION = 3600

os.makedirs(TEMP_DIR, exist_ok=True, mode=0o755)
os.makedirs(CACHE_DIR, exist_ok=True, mode=0o755)

logging.basicConfig(
    level=logging.ERROR,
    format='%(message)s',
    handlers=[logging.NullHandler()]
)
logger = logging.getLogger(__name__)
logging.getLogger('yt_dlp').setLevel(logging.CRITICAL)

app = Flask(__name__)
app.config.update(
    MAX_CONTENT_LENGTH=MAX_FILE_SIZE,
    SEND_FILE_MAX_AGE_DEFAULT=86400,
    JSON_AS_ASCII=False,
    JSON_SORT_KEYS=False,
    JSONIFY_PRETTYPRINT_REGULAR=False
)

CORS(app, 
     origins="*",
     methods=["GET", "POST", "OPTIONS", "HEAD"],
     allow_headers=["*"],
     expose_headers=["Content-Length", "Content-Range", "X-Response-Time"],
     supports_credentials=False,
     max_age=86400)

app.wsgi_app = ProxyFix(app.wsgi_app, x_for=1, x_proto=1, x_host=1, x_prefix=1)

# ============= ALTERNATIVE PROVIDERS =============
# Use multiple providers as fallback when YouTube blocks
ALTERNATIVE_PROVIDERS = [
    'twitter',
    'facebook', 
    'instagram',
    'tiktok',
    'vimeo',
    'dailymotion',
    'reddit',
    'soundcloud',
    'twitch'
]

# User agents rotation
USER_AGENTS = [
    'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
    'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
    'Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
]

# ============= DATA STRUCTURES =============
executor = ThreadPoolExecutor(max_workers=MAX_WORKERS, thread_name_prefix='API')
process_executor = ProcessPoolExecutor(max_workers=MAX_PROCESSES)
download_executor = ThreadPoolExecutor(max_workers=DOWNLOAD_WORKERS, thread_name_prefix='DL')

memory_cache = TTLCache(maxsize=10000, ttl=CACHE_DURATION)
lfu_cache = LFUCache(maxsize=5000)
download_status = {}
active_downloads = {}
request_limiter = defaultdict(lambda: {'count': 0, 'reset_time': time.time() + 60})

performance_metrics = multiprocessing.Manager().dict({
    'total_requests': 0,
    'active_downloads': 0,
    'cache_hits': 0,
    'cache_misses': 0,
    'youtube_blocks': 0,
    'successful_downloads': 0
})

VALID_QUALITIES = frozenset(['best', '4k', '1080p', '720p', '480p', 'audio'])

class ProgressHook:
    __slots__ = ('download_id', 'last_update', 'update_interval', '_status_ref')
    
    def __init__(self, download_id):
        self.download_id = download_id
        self.last_update = 0
        self.update_interval = 2.0
        self._status_ref = None
        
    def __call__(self, d):
        current_time = time.perf_counter()
        
        if current_time - self.last_update < self.update_interval:
            return
        
        self.last_update = current_time
        
        if self._status_ref is None:
            self._status_ref = download_status.get(self.download_id)
        
        if not self._status_ref:
            return
        
        if d['status'] == 'downloading':
            total = d.get('total_bytes') or d.get('total_bytes_estimate', 0)
            downloaded = d.get('downloaded_bytes', 0)
            
            if total > 0:
                self._status_ref.update({
                    'status': 'downloading',
                    'progress': min(99, int(downloaded * 100 / total)),
                    'speed': d.get('speed', 0),
                    'eta': d.get('eta', 0)
                })

def ultra_fast_hash(data: str) -> str:
    return xxhash.xxh64(data.encode(), seed=0).hexdigest()[:16]

def ultra_response(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        result = f(*args, **kwargs)
        
        if isinstance(result, tuple):
            data, status_code = result
        else:
            data, status_code = result, 200
        
        if isinstance(data, dict):
            json_bytes = orjson.dumps(data)
            response = Response(json_bytes, status=status_code, mimetype='application/json')
            response.headers['Cache-Control'] = 'public, max-age=300'
            return response
            
        return result
    return decorated

def get_cached_data(key: str) -> Optional[Any]:
    if key in memory_cache:
        performance_metrics['cache_hits'] += 1
        return memory_cache[key]
    
    performance_metrics['cache_misses'] += 1
    return None

def set_cached_data(key: str, data: Any):
    memory_cache[key] = data

def get_ydl_opts_with_workarounds(quality: str, download_id: str, attempt: int = 0) -> dict:
    """YT-DLP configuration with multiple workarounds"""
    output_path = os.path.join(TEMP_DIR, f'dl_{download_id}_%(title).100B.%(ext)s')
    
    # Base configuration
    opts = {
        'outtmpl': output_path,
        'quiet': True,
        'no_warnings': True,
        'extract_flat': False,
        'ignoreerrors': True,
        'no_check_certificate': True,
        'geo_bypass': True,
        'socket_timeout': 30,
        'retries': 5,
        'fragment_retries': 5,
        'concurrent_fragment_downloads': 8,
        'buffersize': BUFFER_SIZE,
        'http_chunk_size': CHUNK_SIZE,
        'progress_hooks': [ProgressHook(download_id)],
    }
    
    # Try different workarounds based on attempt number
    if attempt == 0:
        # First attempt - try with invidious instances
        opts['proxy'] = None  # Can add proxy here if available
        opts['http_headers'] = {
            'User-Agent': random.choice(USER_AGENTS),
            'Accept-Language': 'en-US,en;q=0.9',
        }
    elif attempt == 1:
        # Second attempt - use different extractor args
        opts['extractor_args'] = {
            'youtube': {
                'player_client': ['ios', 'android', 'web', 'tv_embedded'],
                'player_skip': ['webpage', 'configs', 'js'],
                'skip': ['hls', 'dash'],
            }
        }
        opts['http_headers'] = {
            'User-Agent': 'com.google.ios.youtube/19.29.1 (iPhone16,2; U; CPU iOS 17_5_1 like Mac OS X)',
            'Accept': '*/*',
        }
    elif attempt == 2:
        # Third attempt - use age gate bypass
        opts['age_limit'] = None
        opts['extractor_args'] = {
            'youtube': {
                'player_client': ['tv_embedded', 'android', 'ios'],
                'skip': ['webpage'],
            }
        }
    else:
        # Final attempt - use minimal options
        opts['format'] = 'best'
        opts['extractor_args'] = {
            'youtube': {
                'player_client': ['mweb', 'android'],
            }
        }
    
    # Format selection
    if quality == 'best':
        opts['format'] = 'best[height<=1080]/best'
    elif quality == '720p':
        opts['format'] = 'best[height<=720]/best'
    elif quality == '480p':
        opts['format'] = 'best[height<=480]/best'
    elif quality == 'audio':
        opts['format'] = 'bestaudio/best'
        opts['postprocessors'] = [{
            'key': 'FFmpegExtractAudio',
            'preferredcodec': 'mp3',
            'preferredquality': '192'
        }]
    else:
        opts['format'] = 'best'
    
    return opts

def detect_platform(url: str) -> str:
    """Detect which platform the URL is from"""
    url_lower = url.lower()
    if 'youtube.com' in url_lower or 'youtu.be' in url_lower:
        return 'youtube'
    elif 'twitter.com' in url_lower or 'x.com' in url_lower:
        return 'twitter'
    elif 'facebook.com' in url_lower or 'fb.watch' in url_lower:
        return 'facebook'
    elif 'instagram.com' in url_lower:
        return 'instagram'
    elif 'tiktok.com' in url_lower:
        return 'tiktok'
    elif 'vimeo.com' in url_lower:
        return 'vimeo'
    else:
        return 'generic'

async def extract_info_with_fallback(url: str) -> dict:
    """Extract info with multiple fallback methods"""
    platform = detect_platform(url)
    cache_key = ultra_fast_hash(url)
    
    # Check cache first
    cached = get_cached_data(f"info_{cache_key}")
    if cached:
        return cached
    
    last_error = None
    
    # Try multiple extraction methods
    for attempt in range(4):
        try:
            opts = {
                'quiet': True,
                'no_warnings': True,
                'extract_flat': False,
                'skip_download': True,
                'geo_bypass': True,
                'ignoreerrors': True,
            }
            
            if attempt == 0:
                opts['http_headers'] = {'User-Agent': random.choice(USER_AGENTS)}
            elif attempt == 1:
                opts['extractor_args'] = {
                    'youtube': {'player_client': ['android', 'ios']}
                }
            elif attempt == 2:
                # Try with cookies file if exists
                cookies_file = os.path.join(TEMP_DIR, 'cookies.txt')
                if os.path.exists(cookies_file):
                    opts['cookiefile'] = cookies_file
            
            loop = asyncio.get_event_loop()
            
            def extract():
                # Add delay to avoid rate limiting
                if attempt > 0:
                    time.sleep(random.uniform(2, 5))
                    
                with yt_dlp.YoutubeDL(opts) as ydl:
                    return ydl.extract_info(url, download=False)
            
            info = await loop.run_in_executor(executor, extract)
            
            if info:
                processed = {
                    'title': info.get('title', 'Unknown')[:100],
                    'duration': info.get('duration', 0),
                    'uploader': info.get('uploader', 'Unknown')[:50],
                    'thumbnail': info.get('thumbnail', ''),
                    'platform': platform,
                    'extraction_method': f'attempt_{attempt}'
                }
                
                set_cached_data(f"info_{cache_key}", processed)
                return processed
                
        except Exception as e:
            last_error = str(e)
            if 'Sign in to confirm' in last_error or 'bot' in last_error.lower():
                performance_metrics['youtube_blocks'] = performance_metrics.get('youtube_blocks', 0) + 1
            
            # Wait before retry
            await asyncio.sleep(random.uniform(3, 7))
            continue
    
    # If all attempts failed
    raise Exception(f"Failed to extract info after all attempts. Error: {last_error}")

async def download_with_fallback(url: str, quality: str, download_id: str):
    """Download with multiple fallback strategies"""
    try:
        download_status[download_id] = {
            'status': 'initializing',
            'progress': 0,
            'start_time': time.perf_counter(),
        }
        
        last_error = None
        downloaded_file = None
        
        # Try multiple download strategies
        for attempt in range(4):
            try:
                opts = get_ydl_opts_with_workarounds(quality, download_id, attempt)
                
                download_status[download_id]['status'] = 'downloading'
                download_status[download_id]['message'] = f'Attempt {attempt + 1}/4'
                
                # Add delay between attempts
                if attempt > 0:
                    await asyncio.sleep(random.uniform(5, 10))
                
                loop = asyncio.get_event_loop()
                
                def download_task():
                    with yt_dlp.YoutubeDL(opts) as ydl:
                        ydl.download([url])
                
                await loop.run_in_executor(download_executor, download_task)
                
                # Find downloaded file
                pattern = f'dl_{download_id}_'
                files = [f for f in os.listdir(TEMP_DIR) if f.startswith(pattern)]
                
                for file in files:
                    if not file.endswith(('.part', '.ytdl', '.info.json', '.temp')):
                        downloaded_file = os.path.join(TEMP_DIR, file)
                        break
                
                if downloaded_file and os.path.exists(downloaded_file):
                    break
                    
            except Exception as e:
                last_error = str(e)
                continue
        
        if not downloaded_file or not os.path.exists(downloaded_file):
            # Try alternative method using youtube-dl command directly
            try:
                download_status[download_id]['message'] = 'Trying alternative method...'
                
                # Use subprocess as last resort
                output_file = os.path.join(TEMP_DIR, f'dl_{download_id}_video.mp4')
                cmd = [
                    'yt-dlp',
                    '--no-check-certificate',
                    '--geo-bypass',
                    '--force-ipv4',
                    '--no-playlist',
                    '-f', 'best[height<=720]/best',
                    '-o', output_file,
                    '--quiet',
                    '--no-warnings',
                    url
                ]
                
                result = subprocess.run(cmd, capture_output=True, text=True, timeout=120)
                
                if os.path.exists(output_file):
                    downloaded_file = output_file
                else:
                    raise Exception(f"All download methods failed. Last error: {last_error}")
                    
            except Exception as e:
                raise Exception(f"Download failed completely: {str(e)}")
        
        file_size = os.path.getsize(downloaded_file)
        
        download_status[download_id].update({
            'status': 'completed',
            'progress': 100,
            'file_path': downloaded_file,
            'filename': os.path.basename(downloaded_file),
            'file_size': file_size,
        })
        
        performance_metrics['successful_downloads'] = performance_metrics.get('successful_downloads', 0) + 1
        
        return downloaded_file
        
    except Exception as e:
        download_status[download_id] = {
            'status': 'error',
            'error': str(e)[:200],
        }
        raise

def cleanup_old_files():
    try:
        current_time = time.time()
        
        for file in os.listdir(TEMP_DIR):
            file_path = os.path.join(TEMP_DIR, file)
            try:
                if current_time - os.path.getctime(file_path) > FILE_RETENTION_TIME:
                    os.remove(file_path)
            except:
                pass
        
        gc.collect()
    except:
        pass

def start_cleanup_thread():
    def cleanup_worker():
        while True:
            try:
                cleanup_old_files()
                time.sleep(600)
            except:
                time.sleep(300)
    
    thread = threading.Thread(target=cleanup_worker, daemon=True)
    thread.start()

# ============= API ROUTES =============

@app.route('/')
@ultra_response
def index():
    return {
        'name': 'Universal Video Downloader Pro',
        'version': '6.0',
        'status': 'operational',
        'supported_platforms': [
            'YouTube (with workarounds)',
            'Twitter/X',
            'Facebook',
            'Instagram',
            'TikTok',
            'Vimeo',
            'Dailymotion',
            'Reddit',
            '1000+ other sites'
        ],
        'features': [
            'Multiple fallback methods',
            'Anti-bot detection workarounds',
            'Platform auto-detection',
            'High-speed downloads',
            'Smart caching'
        ],
        'stats': {
            'successful_downloads': performance_metrics.get('successful_downloads', 0),
            'youtube_blocks': performance_metrics.get('youtube_blocks', 0),
            'cache_hits': performance_metrics.get('cache_hits', 0)
        }
    }

@app.route('/api/health')
@ultra_response
def health():
    return {
        'status': 'healthy',
        'timestamp': int(time.time()),
        'active_downloads': len([s for s in download_status.values() if s.get('status') == 'downloading'])
    }

@app.route('/api/info', methods=['POST'])
@ultra_response
def get_info():
    try:
        data = orjson.loads(request.data) if request.data else {}
        url = data.get('url', '').strip()
        
        if not url:
            return {'success': False, 'error': 'URL required'}, 400
        
        # Rate limiting
        client_ip = request.remote_addr
        limiter = request_limiter[client_ip]
        current_time = time.time()
        
        if current_time > limiter['reset_time']:
            limiter['count'] = 0
            limiter['reset_time'] = current_time + 60
        
        limiter['count'] += 1
        if limiter['count'] > 30:
            return {'success': False, 'error': 'Rate limit exceeded', 'retry_after': 60}, 429
        
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        try:
            info = loop.run_until_complete(
                asyncio.wait_for(extract_info_with_fallback(url), timeout=45)
            )
            
            return {
                'success': True,
                'data': info,
                'message': 'Info extracted successfully'
            }
        finally:
            loop.close()
        
    except Exception as e:
        error_msg = str(e)
        
        # Provide user-friendly error messages
        if 'Sign in to confirm' in error_msg or 'bot' in error_msg.lower():
            return {
                'success': False,
                'error': 'The video platform is temporarily blocking requests. Please try again in a few moments or try a different video.',
                'retry_after': 30,
                'suggestion': 'Try videos from other platforms like Twitter, Facebook, or Vimeo'
            }, 429
        elif 'timeout' in error_msg.lower():
            return {
                'success': False,
                'error': 'Request timed out. The server might be busy.',
                'retry_after': 10
            }, 408
        else:
            return {
                'success': False,
                'error': f'Failed to extract video info: {error_msg[:100]}'
            }, 400

@app.route('/api/download', methods=['POST'])
@ultra_response
def start_download():
    try:
        data = orjson.loads(request.data) if request.data else {}
        url = data.get('url', '').strip()
        quality = data.get('quality', 'best')
        
        if not url:
            return {'success': False, 'error': 'URL required'}, 400
        
        # Rate limiting
        client_ip = request.remote_addr
        limiter = request_limiter[client_ip]
        current_time = time.time()
        
        if current_time > limiter['reset_time']:
            limiter['count'] = 0
            limiter['reset_time'] = current_time + 60
        
        limiter['count'] += 1
        if limiter['count'] > 10:
            return {'success': False, 'error': 'Rate limit exceeded', 'retry_after': 60}, 429
        
        active = len([s for s in download_status.values() if s.get('status') == 'downloading'])
        if active >= MAX_CONCURRENT_DOWNLOADS:
            return {
                'success': False,
                'error': f'Server at capacity ({active}/{MAX_CONCURRENT_DOWNLOADS})',
                'retry_after': 30
            }, 429
        
        download_id = f"{int(time.time() * 1000000)}_{ultra_fast_hash(url)[:8]}"
        
        def start_async_download():
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            try:
                loop.run_until_complete(
                    download_with_fallback(url, quality, download_id)
                )
            except:
                pass
            finally:
                loop.close()
        
        thread = threading.Thread(
            target=start_async_download,
            daemon=True,
            name=f'DL-{download_id[:8]}'
        )
        thread.start()
        active_downloads[download_id] = thread
        
        return {
            'success': True,
            'download_id': download_id,
            'message': 'Download started. Using smart extraction with fallback methods.',
        }
        
    except Exception as e:
        return {'success': False, 'error': str(e)[:100]}, 400

@app.route('/api/status/<download_id>')
@ultra_response
def get_status(download_id):
    if download_id not in download_status:
        return {'success': False, 'error': 'Download not found'}, 404
    
    status = download_status[download_id].copy()
    status.pop('file_path', None)
    
    return {'success': True, 'status': status}

@app.route('/api/file/<download_id>')
def download_file(download_id):
    if download_id not in download_status:
        return jsonify({'error': 'Not found'}), 404
    
    status = download_status[download_id]
    if status.get('status') != 'completed':
        return jsonify({'error': 'Not ready'}), 400
    
    file_path = status.get('file_path')
    if not file_path or not os.path.exists(file_path):
        return jsonify({'error': 'File not found'}), 404
    
    try:
        return send_file(
            file_path,
            as_attachment=True,
            download_name=status.get('filename', 'video.mp4'),
            mimetype='application/octet-stream'
        )
    except Exception as e:
        return jsonify({'error': 'Download failed'}), 500

@app.before_request
def before_request():
    g.start_time = time.perf_counter()
    performance_metrics['total_requests'] = performance_metrics.get('total_requests', 0) + 1

@app.after_request
def after_request(response):
    if hasattr(g, 'start_time'):
        duration_ms = (time.perf_counter() - g.start_time) * 1000
        response.headers['X-Response-Time'] = f'{duration_ms:.2f}ms'
    
    response.headers.update({
        'X-Content-Type-Options': 'nosniff',
        'X-Frame-Options': 'DENY',
        'Server': 'Universal-Downloader/6.0'
    })
    
    return response

if __name__ == '__main__':
    start_cleanup_thread()
    WSGIRequestHandler.protocol_version = "HTTP/1.1"
    
    port = int(os.environ.get('PORT', 5000))
    
    print(f"""
🚀 Universal Video Downloader Pro v6.0
✅ Multiple fallback strategies enabled
📊 Smart workarounds for bot detection
🌐 Supports 1000+ video platforms
⚡ High-performance mode active
    """)
    
    app.run(
        host='0.0.0.0',
        port=port,
        debug=False,
        threaded=True,
        use_reloader=False,
        use_debugger=False
    )