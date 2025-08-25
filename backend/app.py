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
from werkzeug.wsgi import FileWrapper
import yt_dlp
import logging
import aiofiles
import orjson
from cachetools import TTLCache, LFUCache
import xxhash

# Install uvloop for maximum async performance
asyncio.set_event_loop_policy(uvloop.EventLoopPolicy())

# ============= ULTRA PERFORMANCE CONFIGURATION =============
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

# Create directories
os.makedirs(TEMP_DIR, exist_ok=True, mode=0o755)
os.makedirs(CACHE_DIR, exist_ok=True, mode=0o755)

# Configure minimal logging
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

# ============= ANTI-BOT DETECTION CONFIGURATION =============
USER_AGENTS = [
    'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
    'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/119.0.0.0 Safari/537.36',
    'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
    'Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
    'Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:109.0) Gecko/20100101 Firefox/121.0',
    'Mozilla/5.0 (Macintosh; Intel Mac OS X 14.1) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.1 Safari/605.1.15',
]

ANDROID_USER_AGENTS = [
    'com.google.android.youtube/17.31.35 (Linux; U; Android 11) gzip',
    'com.google.android.youtube/18.01.34 (Linux; U; Android 12) gzip',
    'com.google.android.youtube/17.36.4 (Linux; U; Android 13) gzip',
]

# Rate limiting per IP
request_limiter = defaultdict(lambda: {'count': 0, 'reset_time': time.time() + 60})

# ============= DATA STRUCTURES =============
executor = ThreadPoolExecutor(
    max_workers=MAX_WORKERS, 
    thread_name_prefix='API',
    initializer=lambda: gc.disable()
)
process_executor = ProcessPoolExecutor(
    max_workers=MAX_PROCESSES,
    initializer=lambda: gc.disable()
)
download_executor = ThreadPoolExecutor(
    max_workers=DOWNLOAD_WORKERS,
    thread_name_prefix='DL',
    initializer=lambda: gc.disable()
)

memory_cache = TTLCache(maxsize=10000, ttl=CACHE_DURATION)
lfu_cache = LFUCache(maxsize=5000)
download_status = {}
active_downloads = {}
download_locks = defaultdict(threading.Lock)

performance_metrics = multiprocessing.Manager().dict({
    'total_requests': 0,
    'active_downloads': 0,
    'cache_hits': 0,
    'cache_misses': 0,
    'avg_response_time': 0,
    'peak_concurrent': 0,
    'total_bytes_served': 0,
    'fastest_download_mbps': 0
})

VALID_QUALITIES = frozenset(['best', '4k', '1080p', '720p', '480p', 'audio'])

class UltraFastProgressHook:
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
        
        status_val = d['status']
        if status_val == 'downloading':
            total = d.get('total_bytes') or d.get('total_bytes_estimate', 0)
            downloaded = d.get('downloaded_bytes', 0)
            
            if total > 0:
                self._status_ref.update({
                    'status': 'downloading',
                    'progress': min(99, int(downloaded * 100 / total)),
                    'speed': d.get('speed', 0),
                    'eta': d.get('eta', 0)
                })

def get_random_user_agent(is_mobile=False):
    """Get random user agent to avoid detection"""
    if is_mobile:
        return random.choice(ANDROID_USER_AGENTS)
    return random.choice(USER_AGENTS)

def get_anti_bot_headers():
    """Generate headers to avoid bot detection"""
    return {
        'User-Agent': get_random_user_agent(),
        'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8',
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
    }

def ultra_fast_hash(data: str) -> str:
    return xxhash.xxh64(data.encode(), seed=0).hexdigest()[:16]

def ultra_compress(data: bytes, level: int = 1) -> bytes:
    try:
        import zstandard as zstd
        cctx = zstd.ZstdCompressor(level=level, threads=-1)
        return cctx.compress(data)
    except ImportError:
        return gzip.compress(data, compresslevel=level)

def ultra_response(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        accept_encoding = request.headers.get('Accept-Encoding', '')
        
        result = f(*args, **kwargs)
        
        if isinstance(result, tuple):
            data, status_code = result
        else:
            data, status_code = result, 200
        
        if isinstance(data, dict):
            json_bytes = orjson.dumps(data)
            
            if len(json_bytes) > 1024 and 'gzip' in accept_encoding:
                compressed = ultra_compress(json_bytes)
                
                response = Response(compressed, status=status_code, mimetype='application/json')
                response.headers.update({
                    'Content-Encoding': 'gzip',
                    'Vary': 'Accept-Encoding',
                    'Cache-Control': 'public, max-age=600, stale-while-revalidate=30',
                    'X-Cache': 'HIT' if hasattr(g, 'cache_hit') else 'MISS'
                })
                return response
            
            response = Response(json_bytes, status=status_code, mimetype='application/json')
            response.headers['Cache-Control'] = 'public, max-age=600'
            return response
            
        return result
    return decorated

def get_cached_data(key: str) -> Optional[Any]:
    if key in memory_cache:
        performance_metrics['cache_hits'] += 1
        g.cache_hit = True
        return memory_cache[key]
    
    if key in lfu_cache:
        performance_metrics['cache_hits'] += 1
        g.cache_hit = True
        data = lfu_cache[key]
        memory_cache[key] = data
        return data
    
    cache_file = os.path.join(CACHE_DIR, f"{key}.cache")
    if os.path.exists(cache_file):
        try:
            with open(cache_file, 'rb') as f:
                data = pickle.load(f)
            memory_cache[key] = data
            performance_metrics['cache_hits'] += 1
            g.cache_hit = True
            return data
        except:
            pass
    
    performance_metrics['cache_misses'] += 1
    return None

def set_cached_data(key: str, data: Any):
    memory_cache[key] = data
    lfu_cache[key] = data
    
    def write_disk_cache():
        try:
            cache_file = os.path.join(CACHE_DIR, f"{key}.cache")
            with open(cache_file, 'wb') as f:
                pickle.dump(data, f, protocol=pickle.HIGHEST_PROTOCOL)
        except:
            pass
    
    executor.submit(write_disk_cache)

def get_ultra_ydl_opts(quality: str, download_id: str, use_android=False, attempt=0) -> dict:
    """Enhanced yt-dlp configuration with anti-bot measures"""
    output_path = os.path.join(TEMP_DIR, f'ultra_{download_id}_%(title).100B.%(ext)s')
    
    # Base configuration with anti-bot measures
    opts = {
        'outtmpl': output_path,
        'concurrent_fragment_downloads': 16,
        'http_chunk_size': CHUNK_SIZE,
        'buffersize': BUFFER_SIZE,
        'retries': 10,
        'fragment_retries': 10,
        'skip_unavailable_fragments': True,
        'socket_timeout': 30,
        'keepvideo': False,
        'noprogress': False,
        'progress_hooks': [UltraFastProgressHook(download_id)],
        'quiet': True,
        'no_warnings': True,
        'ignoreerrors': False,
        'geo_bypass': True,
        'geo_bypass_country': 'US',
        'nocheckcertificate': True,
        'prefer_insecure': True,
        'age_limit': None,
        'http_headers': get_anti_bot_headers() if not use_android else {
            'User-Agent': get_random_user_agent(is_mobile=True)
        },
        'sleep_interval': random.uniform(0.5, 2.0),  # Random delay
        'max_sleep_interval': 5,
        'sleep_interval_requests': random.uniform(0.5, 1.5),
    }
    
    # Add extractor arguments based on attempt
    if use_android or attempt > 0:
        # Use Android client which is less likely to be blocked
        opts['extractor_args'] = {
            'youtube': {
                'player_client': ['android', 'android_embedded', 'android_music', 'android_creator'],
                'player_skip': ['webpage', 'configs', 'js'],
                'skip': ['hls', 'dash', 'translated_subs'],
                'get_po_token': True,  # Get proof of origin token
            }
        }
    else:
        # Try web client first
        opts['extractor_args'] = {
            'youtube': {
                'player_client': ['web', 'web_embedded', 'web_music', 'web_creator', 'android'],
                'player_skip': ['configs', 'js'],
                'skip': ['hls', 'dash', 'translated_subs'],
                'get_po_token': True,
            }
        }
    
    # Add cookies if available (you can implement cookie loading here)
    cookies_file = os.path.join(TEMP_DIR, 'cookies.txt')
    if os.path.exists(cookies_file):
        opts['cookiefile'] = cookies_file
    
    # Format selection
    if quality == 'best':
        opts['format'] = 'bestvideo[height<=2160]+bestaudio/best[height<=2160]/best'
    elif quality == '4k':
        opts['format'] = 'bestvideo[height=2160]+bestaudio/bestvideo[height<=2160]+bestaudio/best'
    elif quality == '1080p':
        opts['format'] = 'bestvideo[height<=1080]+bestaudio/best[height<=1080]/best'
    elif quality == '720p':
        opts['format'] = 'bestvideo[height<=720]+bestaudio/best[height<=720]/best'
    elif quality == '480p':
        opts['format'] = 'bestvideo[height<=480]+bestaudio/best[height<=480]/best'
    elif quality == 'audio':
        opts['format'] = 'bestaudio/best'
        opts['postprocessors'] = [{
            'key': 'FFmpegExtractAudio',
            'preferredcodec': 'mp3',
            'preferredquality': '320'
        }]
    else:
        opts['format'] = 'best'
    
    return opts

async def ultra_extract_info_async(url: str, attempt=0) -> dict:
    """Enhanced info extraction with fallback strategies"""
    cache_key = ultra_fast_hash(url)
    cached = get_cached_data(f"info_{cache_key}")
    if cached:
        return cached
    
    # Try different extraction strategies
    strategies = [
        {'use_android': False, 'client': 'web'},
        {'use_android': True, 'client': 'android'},
        {'use_android': True, 'client': 'android_embedded'},
    ]
    
    last_error = None
    for i, strategy in enumerate(strategies):
        try:
            ydl_opts = {
                'quiet': True,
                'no_warnings': True,
                'extract_flat': False,
                'skip_download': True,
                'geo_bypass': True,
                'geo_bypass_country': 'US',
                'socket_timeout': 20,
                'http_headers': get_anti_bot_headers() if not strategy['use_android'] else {
                    'User-Agent': get_random_user_agent(is_mobile=True)
                },
                'extractor_args': {
                    'youtube': {
                        'player_client': [strategy['client']],
                        'player_skip': ['webpage', 'configs', 'js'],
                        'get_po_token': True,
                    }
                }
            }
            
            # Add cookies if available
            cookies_file = os.path.join(TEMP_DIR, 'cookies.txt')
            if os.path.exists(cookies_file):
                ydl_opts['cookiefile'] = cookies_file
            
            loop = asyncio.get_event_loop()
            
            def extract():
                # Add random delay to avoid rate limiting
                time.sleep(random.uniform(0.5, 2.0))
                with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                    return ydl.extract_info(url, download=False)
            
            info = await loop.run_in_executor(executor, extract)
            
            # Process and cache
            processed = {
                'title': info.get('title', 'Unknown')[:100],
                'duration': info.get('duration', 0),
                'uploader': info.get('uploader', 'Unknown')[:50],
                'view_count': info.get('view_count', 0),
                'thumbnail': info.get('thumbnail', ''),
                'description': (info.get('description', '') or '')[:300]
            }
            
            if 'formats' in info:
                heights = set()
                for fmt in info.get('formats', []):
                    if fmt.get('height'):
                        heights.add(fmt['height'])
                processed['available_qualities'] = sorted(heights, reverse=True)[:6]
            
            set_cached_data(f"info_{cache_key}", processed)
            return processed
            
        except Exception as e:
            last_error = str(e)
            if i < len(strategies) - 1:
                # Wait before trying next strategy
                await asyncio.sleep(random.uniform(1, 3))
                continue
            else:
                raise Exception(f"All extraction strategies failed. Last error: {last_error}")

async def ultra_download_file_async(url: str, quality: str, download_id: str):
    """Enhanced download with multiple fallback strategies"""
    try:
        download_status[download_id] = {
            'status': 'initializing',
            'progress': 0,
            'start_time': time.perf_counter(),
            'url': url,
            'quality': quality
        }
        
        # Try different download strategies
        strategies = [
            {'use_android': False, 'attempt': 0},
            {'use_android': True, 'attempt': 1},
            {'use_android': True, 'attempt': 2},
        ]
        
        last_error = None
        downloaded_file = None
        
        for strategy in strategies:
            try:
                opts = get_ultra_ydl_opts(
                    quality, 
                    download_id, 
                    use_android=strategy['use_android'],
                    attempt=strategy['attempt']
                )
                
                download_status[download_id]['status'] = 'downloading'
                download_status[download_id]['message'] = f'Attempt {strategy["attempt"] + 1}/3'
                
                # Add random delay to avoid detection
                await asyncio.sleep(random.uniform(1, 3))
                
                loop = asyncio.get_event_loop()
                
                def download_task():
                    with yt_dlp.YoutubeDL(opts) as ydl:
                        ydl.download([url])
                
                await loop.run_in_executor(download_executor, download_task)
                
                # Find downloaded file
                pattern = f'ultra_{download_id}_'
                files = [f for f in os.listdir(TEMP_DIR) if f.startswith(pattern)]
                
                for file in files:
                    if not file.endswith(('.part', '.ytdl', '.info.json', '.temp')):
                        downloaded_file = os.path.join(TEMP_DIR, file)
                        break
                
                if downloaded_file and os.path.exists(downloaded_file):
                    break
                    
            except Exception as e:
                last_error = str(e)
                if 'Sign in to confirm' in str(e) or 'bot' in str(e).lower():
                    # Wait longer if bot detection
                    await asyncio.sleep(random.uniform(5, 10))
                continue
        
        if not downloaded_file or not os.path.exists(downloaded_file):
            raise Exception(f"Download failed after all attempts. Last error: {last_error}")
        
        file_size = os.path.getsize(downloaded_file)
        
        end_time = time.perf_counter()
        duration = end_time - download_status[download_id]['start_time']
        avg_speed_mbps = (file_size * 8) / (duration * 1024 * 1024) if duration > 0 else 0
        
        download_status[download_id].update({
            'status': 'completed',
            'progress': 100,
            'file_path': downloaded_file,
            'filename': os.path.basename(downloaded_file),
            'file_size': file_size,
            'duration': round(duration, 2),
            'avg_speed_mbps': round(avg_speed_mbps, 2),
            'completion_time': time.time()
        })
        
        performance_metrics['total_bytes_served'] += file_size
        
        return downloaded_file
        
    except Exception as e:
        download_status[download_id] = {
            'status': 'error',
            'error': str(e)[:200],
            'timestamp': time.time()
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
        
        for file in os.listdir(CACHE_DIR):
            file_path = os.path.join(CACHE_DIR, file)
            try:
                if current_time - os.path.getctime(file_path) > CACHE_DURATION:
                    os.remove(file_path)
            except:
                pass
        
        if len(download_status) > 1000:
            sorted_downloads = sorted(
                download_status.items(),
                key=lambda x: x[1].get('start_time', 0)
            )
            
            for download_id, _ in sorted_downloads[:200]:
                if download_id in download_status:
                    status = download_status[download_id]
                    if 'file_path' in status:
                        try:
                            os.remove(status['file_path'])
                        except:
                            pass
                    del download_status[download_id]
        
        gc.collect()
        
    except Exception:
        pass

def start_cleanup_thread():
    def cleanup_worker():
        while True:
            try:
                cleanup_old_files()
                time.sleep(600)
            except:
                time.sleep(300)
    
    thread = threading.Thread(target=cleanup_worker, daemon=True, name='Cleanup')
    thread.start()

# ============= API ROUTES =============

@app.route('/')
@ultra_response
def index():
    return {
        'name': 'YT Downloader Ultra Pro Max',
        'version': '5.0',
        'status': 'operational',
        'performance': {
            'max_concurrent': MAX_CONCURRENT_DOWNLOADS,
            'active_downloads': len([s for s in download_status.values() if s.get('status') == 'downloading']),
            'total_requests': performance_metrics.get('total_requests', 0),
            'cache_hit_rate': f"{(performance_metrics.get('cache_hits', 0) / max(1, performance_metrics.get('cache_hits', 0) + performance_metrics.get('cache_misses', 0)) * 100):.1f}%",
        },
        'features': [
            'Anti-bot detection bypass',
            'Multiple extraction strategies',
            'Automatic fallback mechanisms',
            'Smart rate limiting',
            'Cookie support',
            'Android client emulation'
        ]
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
    start = time.perf_counter()
    
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
        if limiter['count'] > 30:  # 30 requests per minute
            return {'success': False, 'error': 'Rate limit exceeded', 'retry_after': 60}, 429
        
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        try:
            info = loop.run_until_complete(
                asyncio.wait_for(ultra_extract_info_async(url), timeout=30)
            )
        finally:
            loop.close()
        
        response_time = (time.perf_counter() - start) * 1000
        
        return {
            'success': True,
            'data': info,
            'response_time_ms': round(response_time, 2)
        }
        
    except asyncio.TimeoutError:
        return {'success': False, 'error': 'Request timeout'}, 408
    except Exception as e:
        error_msg = str(e)
        if 'Sign in to confirm' in error_msg or 'bot' in error_msg.lower():
            return {
                'success': False, 
                'error': 'YouTube requires verification. Please try again in a few moments.',
                'retry_after': 30
            }, 429
        return {'success': False, 'error': error_msg[:100]}, 400

@app.route('/api/download', methods=['POST'])
@ultra_response
def start_download():
    start = time.perf_counter()
    
    try:
        data = orjson.loads(request.data) if request.data else {}
        url = data.get('url', '').strip()
        quality = data.get('quality', 'best')
        
        if not url:
            return {'success': False, 'error': 'URL required'}, 400
        
        if quality not in VALID_QUALITIES:
            quality = 'best'
        
        # Rate limiting
        client_ip = request.remote_addr
        limiter = request_limiter[client_ip]
        current_time = time.time()
        
        if current_time > limiter['reset_time']:
            limiter['count'] = 0
            limiter['reset_time'] = current_time + 60
        
        limiter['count'] += 1
        if limiter['count'] > 10:  # 10 downloads per minute
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
                    ultra_download_file_async(url, quality, download_id)
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
        
        response_time = (time.perf_counter() - start) * 1000
        
        return {
            'success': True,
            'download_id': download_id,
            'message': 'Download started',
            'response_time_ms': round(response_time, 2)
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
    
    if status.get('status') == 'downloading' and 'start_time' in status:
        elapsed = time.perf_counter() - status['start_time']
        if status.get('progress', 0) > 0:
            estimated_total = elapsed / (status['progress'] / 100)
            status['eta_seconds'] = max(0, int(estimated_total - elapsed))
    
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
        range_header = request.headers.get('Range')
        file_size = os.path.getsize(file_path)
        
        if range_header:
            byte_start = 0
            byte_end = file_size - 1
            
            if range_header.startswith('bytes='):
                byte_range = range_header[6:].split('-')
                if byte_range[0]:
                    byte_start = int(byte_range[0])
                if byte_range[1]:
                    byte_end = int(byte_range[1])
            
            def generate():
                with open(file_path, 'rb') as f:
                    f.seek(byte_start)
                    remaining = byte_end - byte_start + 1
                    
                    while remaining > 0:
                        chunk_size = min(CHUNK_SIZE, remaining)
                        chunk = f.read(chunk_size)
                        if not chunk:
                            break
                        remaining -= len(chunk)
                        yield chunk
            
            response = Response(
                stream_with_context(generate()),
                status=206,
                mimetype='application/octet-stream',
                headers={
                    'Content-Range': f'bytes {byte_start}-{byte_end}/{file_size}',
                    'Accept-Ranges': 'bytes',
                    'Content-Length': str(byte_end - byte_start + 1),
                    'Content-Disposition': f'attachment; filename="{status.get("filename", "video.mp4")}"'
                }
            )
            return response
        
        else:
            def stream_file():
                with open(file_path, 'rb') as f:
                    if file_size > 50 * 1024 * 1024:
                        with mmap.mmap(f.fileno(), 0, access=mmap.ACCESS_READ) as mmapped:
                            offset = 0
                            while offset < file_size:
                                chunk = mmapped[offset:offset + CHUNK_SIZE]
                                if not chunk:
                                    break
                                offset += len(chunk)
                                yield chunk
                    else:
                        while True:
                            chunk = f.read(CHUNK_SIZE)
                            if not chunk:
                                break
                            yield chunk
            
            return Response(
                stream_with_context(stream_file()),
                mimetype='application/octet-stream',
                headers={
                    'Content-Disposition': f'attachment; filename="{status.get("filename", "video.mp4")}"',
                    'Content-Length': str(file_size),
                    'Accept-Ranges': 'bytes',
                    'Cache-Control': 'public, max-age=3600',
                    'X-Accel-Buffering': 'no'
                }
            )
            
    except Exception as e:
        return jsonify({'error': 'Stream failed'}), 500

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
        'Server': 'YT-Ultra-Pro/5.0',
        'Keep-Alive': 'timeout=5, max=100'
    })
    
    return response

if __name__ == '__main__':
    start_cleanup_thread()
    WSGIRequestHandler.protocol_version = "HTTP/1.1"
    
    port = int(os.environ.get('PORT', 5000))
    
    print(f"""
🚀 YT Downloader Ultra Pro Max v5.0
⚡ Anti-Bot Detection: ENABLED
📊 Workers: {MAX_WORKERS} threads
🔥 Max Concurrent: {MAX_CONCURRENT_DOWNLOADS} downloads
✨ Features: Multiple fallback strategies, Rate limiting, Cookie support
    """)
    
    app.run(
        host='0.0.0.0',
        port=port,
        debug=False,
        threaded=True,
        use_reloader=False,
        use_debugger=False
    )