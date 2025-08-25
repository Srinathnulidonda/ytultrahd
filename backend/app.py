import os
import json
import time
import asyncio
import threading
import tempfile
import hashlib
import multiprocessing
import random
from datetime import datetime, timedelta
from concurrent.futures import ThreadPoolExecutor, TimeoutError
from functools import lru_cache, wraps
from collections import defaultdict, deque
from queue import Queue, Empty
import gc
import weakref
from base64 import b64decode
import signal

from flask import Flask, request, jsonify, send_file, Response, g
from flask_cors import CORS
from werkzeug.middleware.proxy_fix import ProxyFix
import yt_dlp
import logging

# =========================
# Render Free Tier Settings
# =========================
CPU_COUNT = max(1, multiprocessing.cpu_count() // 2)
MAX_WORKERS = min(8, CPU_COUNT * 2)
MAX_PROCESSES = 2
DOWNLOAD_WORKERS = min(4, CPU_COUNT)
CHUNK_SIZE = 512 * 1024
BUFFER_SIZE = 2 * 1024 * 1024
MAX_CONCURRENT_DOWNLOADS = 2  # Reduced for free tier
MAX_FILE_SIZE = 1024 * 1024 * 1024
TEMP_DIR = os.path.join(tempfile.gettempdir(), 'yt_render')
CACHE_DURATION = 600
FILE_RETENTION_TIME = 1800
MAX_CACHE_SIZE = 100

# Rate limiting to avoid bot detection
RATE_LIMIT_DELAY = 2  # seconds between requests
last_request_time = 0
request_count = 0

# Env overrides / extras
FORCE_IPV4 = os.environ.get('YTDLP_FORCE_IPV4', '1') == '1'
DEFAULT_HL = os.environ.get('YTDLP_HL', 'en')
DEFAULT_GL = os.environ.get('YTDLP_GL', 'US')
ENV_COOKIES_B64 = os.environ.get('YTDLP_COOKIES_B64')  # base64 Netscape cookies.txt
ENV_PROXY = os.environ.get('YTDLP_PROXY')  # e.g., http://user:pass@host:port

os.makedirs(TEMP_DIR, exist_ok=True)

# =========================
# Logging
# =========================
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[logging.StreamHandler()]
)
logger = logging.getLogger('app')
logging.getLogger('yt_dlp').setLevel(logging.WARNING)
logger.info(f"Render $PORT env is: {os.environ.get('PORT')}")

# =========================
# Flask App
# =========================
app = Flask(__name__)
CORS(app, origins=["*"], methods=["GET", "POST", "OPTIONS"])
app.wsgi_app = ProxyFix(app.wsgi_app, x_for=1, x_proto=1)

# =========================
# Globals
# =========================
executor = ThreadPoolExecutor(max_workers=MAX_WORKERS, thread_name_prefix='API')
download_status = weakref.WeakValueDictionary()
active_downloads = {}
performance_metrics = {
    'total_requests': 0,
    'successful_extractions': 0,
    'failed_extractions': 0,
    'bot_detections': 0,
    'start_time': time.time()
}

# User agents rotation for bot avoidance
USER_AGENTS = [
    'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
    'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
    'Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
    'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Edge/120.0.0.0 Safari/537.36',
    'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.0 Safari/605.1.15',
    'Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:121.0) Gecko/20100101 Firefox/121.0'
]

def get_random_user_agent():
    return random.choice(USER_AGENTS)

# =========================
# Timeout handler
# =========================
class TimeoutException(Exception):
    pass

def timeout_handler(func, timeout_duration=60):
    """Decorator to add timeout to functions"""
    @wraps(func)
    def wrapper(*args, **kwargs):
        def target():
            return func(*args, **kwargs)
        
        future = executor.submit(target)
        try:
            return future.result(timeout=timeout_duration)
        except TimeoutError:
            future.cancel()
            raise TimeoutException(f"Operation timed out after {timeout_duration} seconds")
    
    return wrapper

# =========================
# Cache
# =========================
class LimitedCache:
    def __init__(self, max_size=MAX_CACHE_SIZE):
        self.cache = {}
        self.max_size = max_size
        self.access_times = {}
    
    def get(self, key):
        if key in self.cache:
            data, timestamp = self.cache[key]
            if time.time() - timestamp < CACHE_DURATION:
                self.access_times[key] = time.time()
                return data
            else:
                del self.cache[key]
                self.access_times.pop(key, None)
        return None
    
    def set(self, key, data):
        if len(self.cache) >= self.max_size:
            oldest_keys = sorted(self.access_times.keys(), 
                               key=lambda k: self.access_times[k])[:self.max_size//4]
            for old_key in oldest_keys:
                self.cache.pop(old_key, None)
                self.access_times.pop(old_key, None)
        
        self.cache[key] = (data, time.time())
        self.access_times[key] = time.time()

memory_cache = LimitedCache()

# =========================
# Status Tracking
# =========================
class Status:
    def __init__(self, download_id):
        self.download_id = download_id
        self.data = {
            'status': 'initializing',
            'progress': 0,
            'start_time': time.time()
        }
    
    def update(self, **kwargs):
        self.data.update(kwargs)
    
    def get(self, key, default=None):
        return self.data.get(key, default)
    
    def copy(self):
        return self.data.copy()

class RenderProgressHook:
    def __init__(self, download_id):
        self.download_id = download_id
        self.last_update = 0
        self.update_count = 0
        
    def __call__(self, d):
        current_time = time.time()
        self.update_count += 1
        
        if (current_time - self.last_update < 2.0) and (self.update_count % 20 != 0):
            return
        
        self.last_update = current_time
        
        try:
            if self.download_id in active_downloads:
                status_obj = active_downloads[self.download_id]
                
                if d['status'] == 'downloading':
                    total = d.get('total_bytes') or d.get('total_bytes_estimate', 0)
                    downloaded = d.get('downloaded_bytes', 0)
                    progress = (downloaded / total * 100) if total > 0 else 0
                    
                    status_obj.update(
                        status='downloading',
                        progress=round(progress, 1),
                        speed=d.get('speed', 0),
                        eta=d.get('eta', 0),
                        downloaded_bytes=downloaded,
                        total_bytes=total
                    )
                    
                elif d['status'] == 'finished':
                    status_obj.update(
                        status='finalizing',
                        progress=95,
                        message='Processing...'
                    )
                    
        except Exception as e:
            logger.error(f"Progress update error: {e}")

@lru_cache(maxsize=1000)
def get_cache_key(url: str) -> str:
    return hashlib.md5(url.encode()).hexdigest()[:12]

# =========================
# Rate Limiting
# =========================
def apply_rate_limiting():
    """Apply rate limiting to avoid bot detection"""
    global last_request_time, request_count
    
    current_time = time.time()
    
    # Reset counter every hour
    if current_time - last_request_time > 3600:
        request_count = 0
    
    # Apply delay between requests
    if current_time - last_request_time < RATE_LIMIT_DELAY:
        sleep_time = RATE_LIMIT_DELAY - (current_time - last_request_time)
        time.sleep(sleep_time)
    
    request_count += 1
    last_request_time = time.time()
    
    # Add extra delay if too many requests
    if request_count > 20:  # After 20 requests, add random delay
        time.sleep(random.uniform(1, 3))

# =========================
# Cookies / Proxy helpers
# =========================
def _materialize_cookiefile_from_b64(b64txt: str, label: str = 'user') -> str | None:
    if not b64txt:
        return None
    try:
        text = b64decode(b64txt).decode('utf-8', 'ignore')
        path = os.path.join(TEMP_DIR, f'cookies_{label}_{int(time.time())}.txt')
        with open(path, 'w', encoding='utf-8', newline='\n') as f:
            f.write(text)
        return path
    except Exception as e:
        logger.warning(f'Failed to decode cookies b64: {e}')
        return None

def _collect_request_extras(data: dict) -> dict:
    extras = {}

    # Cookies precedence: request cookies_b64 -> env cookies -> none
    cookiefile = None
    if data.get('cookies_b64'):
        cookiefile = _materialize_cookiefile_from_b64(data['cookies_b64'], 'req')
    elif ENV_COOKIES_B64:
        cookiefile = _materialize_cookiefile_from_b64(ENV_COOKIES_B64, 'env')
    if cookiefile:
        extras['cookiefile'] = cookiefile

    # Optional raw Cookie header string
    if data.get('cookie_header'):
        extras['cookie_header'] = data['cookie_header']

    # Proxy precedence: request -> env -> none
    proxy = data.get('proxy') or ENV_PROXY
    if proxy:
        extras['proxy'] = proxy

    # Locale tuning
    extras['hl'] = data.get('hl', DEFAULT_HL)
    extras['gl'] = data.get('gl', DEFAULT_GL)
    return extras

# =========================
# yt-dlp Options
# =========================
def get_anti_bot_ydl_opts(cookiefile=None, proxy=None, cookie_header=None, hl='en', gl='US') -> dict:
    """Get yt-dlp options designed to avoid bot detection"""
    user_agent = get_random_user_agent()
    headers = {
        'User-Agent': user_agent,
        'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
        'Accept-Language': f'{hl}-{gl},{hl};q=0.8',
        'Accept-Encoding': 'gzip, deflate',
        'DNT': '1',
        'Connection': 'keep-alive',
        'Upgrade-Insecure-Requests': '1',
        'Sec-Fetch-Dest': 'document',
        'Sec-Fetch-Mode': 'navigate',
        'Sec-Fetch-Site': 'none',
        'Cache-Control': 'max-age=0'
    }
    if cookie_header:
        headers['Cookie'] = cookie_header
    
    opts = {
        'quiet': False,
        'no_warnings': False,  # Keep warnings for debugging
        'extract_flat': False,
        'skip_download': True,
        'socket_timeout': 20,  # Reduced from 30
        'http_headers': headers,
        'noplaylist': True,
        'geo_bypass': True,
        'extractor_retries': 1,  # Reduced from 2
        # Reduced sleep intervals to avoid timeouts
        'sleep_interval_requests': random.uniform(0.5, 1.5),  # Reduced from 1.5-3.5
        'max_sleep_interval': 2,  # Reduced from 6
        'http_chunk_size': random.randint(16384, 65536),
        'retries': 2,  # Reduced from 3
        'fragment_retries': 2,  # Reduced from 3
        'ignoreerrors': True,
        'extractor_args': {
            'youtube': {
                'player_client': ['web', 'android'],  # Removed ios to speed up
                'player_skip': ['webpage', 'configs'],  # Skip more to speed up
                'skip': ['dash', 'hls'],  # Skip more formats
                'max_comments': [0],
                'comment_sort': ['top'],
                'max_comment_depth': 1,
                'lang': [hl],
                'geo_bypass_country': [gl],
            }
        },
    }

    if FORCE_IPV4:
        opts['source_address'] = '0.0.0.0'

    if cookiefile:
        opts['cookiefile'] = cookiefile
    if proxy:
        opts['proxy'] = proxy

    return opts

# =========================
# Extraction logic
# =========================
def extract_with_strategy(url: str, opts: dict) -> dict:
    """Extract with specific strategy"""
    with yt_dlp.YoutubeDL(opts) as ydl:
        return ydl.extract_info(url, download=False)

def extract_info_with_fallbacks(url: str, extras: dict | None = None) -> dict:
    """Extract info with multiple fallback strategies"""
    apply_rate_limiting()
    extras = extras or {}

    base = get_anti_bot_ydl_opts(
        cookiefile=extras.get('cookiefile'),
        proxy=extras.get('proxy'),
        cookie_header=extras.get('cookie_header'),
        hl=extras.get('hl', 'en'),
        gl=extras.get('gl', 'US')
    )
    
    # Reduced strategies to avoid timeout
    strategies = [
        # Strategy 1: Standard extraction with anti-bot measures
        lambda: extract_with_strategy(url, {**base}),
        
        # Strategy 2: Mobile client preference (faster)
        lambda: extract_with_strategy(url, {
            **base,
            'extractor_args': {
                'youtube': {
                    'player_client': ['android'],  # Android only for speed
                    'player_skip': ['webpage', 'configs', 'js'],
                    'lang': [extras.get('hl', 'en')],
                    'geo_bypass_country': [extras.get('gl', 'US')],
                }
            }
        }),
        
        # Strategy 3: Web embedded (if cookies provided)
        lambda: extract_with_strategy(url, {
            **base,
            'extractor_args': {
                'youtube': {
                    'player_client': ['web_embedded'],
                    'lang': [extras.get('hl', 'en')],
                    'geo_bypass_country': [extras.get('gl', 'US')],
                }
            }
        }) if extras.get('cookiefile') else None,
    ]
    
    # Filter out None strategies
    strategies = [s for s in strategies if s is not None]
    
    last_error = None
    start_time = time.time()
    
    for i, strategy in enumerate(strategies, 1):
        # Check if we're approaching timeout
        if time.time() - start_time > 50:  # Leave 10s buffer
            raise TimeoutException("Extraction taking too long, please try again")
            
        try:
            logger.info(f"Trying extraction strategy {i}/{len(strategies)}")
            result = strategy()
            if result:
                performance_metrics['successful_extractions'] += 1
                logger.info(f"Strategy {i} succeeded")
                return result
        except Exception as e:
            last_error = e
            error_msg = str(e).lower()
            
            # Check for bot detection
            if any(phrase in error_msg for phrase in ['bot', 'sign in', 'captcha', '429', 'too many requests']):
                performance_metrics['bot_detections'] += 1
                logger.warning(f"Bot detection in strategy {i}: {str(e)[:120]}")
                # Shorter delay to avoid timeout
                time.sleep(random.uniform(2, 3))
            else:
                logger.warning(f"Strategy {i} failed: {str(e)[:120]}")
                time.sleep(0.5)  # Very short delay
    
    performance_metrics['failed_extractions'] += 1
    raise Exception(f"All extraction strategies failed. Last error: {str(last_error)[:150]}")

def process_info_safely(info: dict) -> dict:
    """Safely process extracted info"""
    try:
        processed = {
            'title': (info.get('title', '') or info.get('display_title', '') or 'Unknown Title')[:80],
            'duration': info.get('duration', 0) or 0,
            'uploader': (info.get('uploader', '') or info.get('channel', '') or 'Unknown')[:30],
            'view_count': info.get('view_count', 0) or 0,
            'thumbnail': info.get('thumbnail', '') or '',
            'id': info.get('id', '') or info.get('display_id', ''),
            'description': ((info.get('description', '') or '')[:150] + '...') if info.get('description') else 'No description available',
            'upload_date': info.get('upload_date', '') or '',
            'webpage_url': info.get('webpage_url', '') or '',
            'extractor': info.get('extractor', 'youtube')
        }
        
        # Process available formats more safely
        available_qualities = []
        if 'formats' in info and info['formats']:
            heights = set()
            for fmt in info['formats']:
                height = fmt.get('height', 0)
                if height and height >= 144 and height <= 2160:  # Valid video heights
                    heights.add(height)
            
            available_qualities = sorted(list(heights), reverse=True)[:6]  # Max 6 qualities
        
        # Add default qualities if none found
        if not available_qualities:
            available_qualities = [720, 480, 360, 240]
        
        processed['available_qualities'] = available_qualities
        
        # Add audio availability
        has_audio = any(fmt.get('acodec', 'none') != 'none' for fmt in info.get('formats', []))
        processed['has_audio'] = has_audio
        
        return processed
        
    except Exception as e:
        logger.error(f"Error processing info: {e}")
        # Return minimal safe info
        return {
            'title': 'Video Title Unavailable',
            'duration': 0,
            'uploader': 'Unknown',
            'view_count': 0,
            'thumbnail': '',
            'id': info.get('id', 'unknown'),
            'description': 'Description unavailable',
            'available_qualities': [720, 480, 360],
            'has_audio': True,
            'extractor': 'youtube'
        }

# =========================
# Download logic
# =========================
def get_download_opts(quality: str, download_id: str, extras: dict | None = None) -> dict:
    """Get download options with anti-bot measures"""
    extras = extras or {}
    timestamp = int(time.time())
    output_path = os.path.join(TEMP_DIR, f'render_{download_id}_{timestamp}.%(ext)s')
    
    base_opts = get_anti_bot_ydl_opts(
        cookiefile=extras.get('cookiefile'),
        proxy=extras.get('proxy'),
        cookie_header=extras.get('cookie_header'),
        hl=extras.get('hl', 'en'),
        gl=extras.get('gl', 'US')
    )
    
    opts = {
        **base_opts,
        'outtmpl': output_path,
        'format_sort': ['res:1080', 'fps:30', 'source'],
        'merge_output_format': 'mp4',
        'concurrent_fragment_downloads': 2,
        'http_chunk_size': CHUNK_SIZE,
        'buffersize': BUFFER_SIZE,
        'keep_fragments': False,
        'writeinfojson': False,
        'writesubtitles': False,
        'writeautomaticsub': False,
        'writethumbnail': False,
        'writedescription': False,
        'skip_download': False,  # We want to download now
        'progress_hooks': [RenderProgressHook(download_id)],
    }
    
    # Quality-specific format selection
    format_map = {
        'best': 'best[height<=1080][filesize<800M]/best[height<=720]',
        '1080p': 'best[height<=1080][filesize<800M]',
        '720p': 'best[height<=720][filesize<500M]',
        '480p': 'best[height<=480][filesize<300M]',
        '360p': 'best[height<=360][filesize<200M]',
        'audio': 'bestaudio[abr<=192]/bestaudio'
    }
    
    opts['format'] = format_map.get(quality, format_map['720p'])
    
    if quality == 'audio':
        opts['postprocessors'] = [{
            'key': 'FFmpegExtractAudio',
            'preferredcodec': 'mp3',
            'preferredquality': '192'
        }]
    
    return opts

async def download_with_render_limits(url: str, quality: str, download_id: str, extras: dict | None = None):
    """Download with anti-bot measures"""
    loop = asyncio.get_event_loop()
    
    def download_worker():
        try:
            status_obj = Status(download_id)
            active_downloads[download_id] = status_obj
            
            status_obj.update(
                status='starting',
                message='Initializing download...'
            )
            
            # Apply rate limiting before download
            apply_rate_limiting()
            
            opts = get_download_opts(quality, download_id, extras)
            
            status_obj.update(
                status='downloading',
                message='Download in progress...'
            )
            
            with yt_dlp.YoutubeDL(opts) as ydl:
                ydl.download([url])
            
            # Find downloaded file
            prefix = f'render_{download_id}_'
            downloaded_file = None
            
            for file in os.listdir(TEMP_DIR):
                if file.startswith(prefix) and not file.endswith(('.part', '.info.json', '.temp')):
                    downloaded_file = os.path.join(TEMP_DIR, file)
                    break
            
            if not downloaded_file or not os.path.exists(downloaded_file):
                raise Exception("Download completed but file not found")
            
            file_size = os.path.getsize(downloaded_file)
            
            if file_size > MAX_FILE_SIZE:
                os.remove(downloaded_file)
                raise Exception(f'File too large: {file_size / (1024**3):.1f}GB')
            
            # Success
            end_time = time.time()
            download_time = end_time - status_obj.get('start_time')
            
            status_obj.update(
                status='completed',
                progress=100,
                message='Download completed!',
                file_path=downloaded_file,
                file_size=file_size,
                filename=os.path.basename(downloaded_file),
                download_time=download_time,
                completion_time=end_time
            )
            
            return downloaded_file
            
        except Exception as e:
            logger.error(f"Download error: {e}")
            status_obj = active_downloads.get(download_id)
            if status_obj:
                status_obj.update(
                    status='error',
                    message=str(e)[:150],
                    error_time=time.time()
                )
            raise
    
    return await loop.run_in_executor(executor, download_worker)

# =========================
# Cleanup
# =========================
def cleanup_render_friendly():
    """Enhanced cleanup"""
    try:
        current_time = time.time()
        cleaned = 0
        
        if os.path.exists(TEMP_DIR):
            for file in os.listdir(TEMP_DIR):
                if file.startswith(('render_', 'cookies_')):
                    file_path = os.path.join(TEMP_DIR, file)
                    try:
                        if current_time - os.path.getctime(file_path) > FILE_RETENTION_TIME:
                            os.remove(file_path)
                            cleaned += 1
                            if cleaned > 10:  # Limit cleanup per run
                                break
                    except Exception:
                        pass
        
        # Clean old downloads
        if len(active_downloads) > 30:
            old_downloads = list(active_downloads.keys())[:10]
            for download_id in old_downloads:
                if download_id in active_downloads:
                    status_obj = active_downloads[download_id]
                    if status_obj.get('file_path'):
                        try:
                            os.remove(status_obj.get('file_path'))
                        except Exception:
                            pass
                    del active_downloads[download_id]
        
        if cleaned > 0:
            gc.collect()
            logger.info(f"Cleaned {cleaned} files")
            
    except Exception as e:
        logger.error(f"Cleanup error: {e}")

def start_cleanup_thread():
    def cleanup_worker():
        while True:
            try:
                cleanup_render_friendly()
                time.sleep(600)  # Every 10 minutes
            except Exception as e:
                logger.error(f"Cleanup thread error: {e}")
                time.sleep(300)
    
    thread = threading.Thread(target=cleanup_worker, daemon=True)
    thread.start()

# Start background tasks lazily on first request (Flask 3.x-safe)
_bg_lock = threading.Lock()
_bg_started = False
def ensure_bg_started():
    global _bg_started
    if not _bg_started:
        with _bg_lock:
            if not _bg_started:
                start_cleanup_thread()
                _bg_started = True
                logger.info("Background cleanup thread started")

# =========================
# API Routes
# =========================
@app.route('/')
def index():
    uptime = time.time() - performance_metrics['start_time']
    success_rate = 0
    total_extractions = performance_metrics['successful_extractions'] + performance_metrics['failed_extractions']
    if total_extractions > 0:
        success_rate = (performance_metrics['successful_extractions'] / total_extractions) * 100
    
    return jsonify({
        'name': 'YouTube Downloader - Render Anti-Bot Edition',
        'version': '2.0',
        'status': 'operational',
        'uptime_seconds': round(uptime, 1),
        'anti_bot_features': [
            'Multiple extraction strategies',
            'User-agent rotation',
            'Rate limiting',
            'Fallback mechanisms',
            'Mobile client support',
            'Cookie/Proxy support'
        ],
        'stats': {
            'total_requests': performance_metrics['total_requests'],
            'successful_extractions': performance_metrics['successful_extractions'],
            'failed_extractions': performance_metrics['failed_extractions'],
            'bot_detections': performance_metrics['bot_detections'],
            'success_rate': f"{success_rate:.1f}%",
            'active_downloads': len([d for d in active_downloads.values() 
                                   if d.get('status') in ['downloading', 'starting']]),
            'cache_size': len(memory_cache.cache)
        }
    })

@app.route('/api/health')
def health():
    return jsonify({
        'status': 'healthy',
        'timestamp': int(time.time()),
        'metrics': performance_metrics,
        'active_downloads': len(active_downloads),
        'temp_files': len([f for f in os.listdir(TEMP_DIR) if f.startswith(('render_', 'cookies_'))])
    })

@app.route('/api/info', methods=['POST'])
def get_info():
    start_time = time.time()
    performance_metrics['total_requests'] += 1
    
    try:
        data = request.get_json() or {}
        if 'url' not in data:
            return jsonify({'success': False, 'error': 'URL required'}), 400
        
        url = data['url'].strip()
        extras = _collect_request_extras(data)

        # Include locale in cache key so we don't mix locales
        cache_key = get_cache_key(url + json.dumps({'hl': extras.get('hl'), 'gl': extras.get('gl')}, sort_keys=True))
        
        # Check cache first
        cached = memory_cache.get(cache_key)
        if cached:
            return jsonify({
                'success': True,
                'data': cached,
                'cached': True,
                'response_time_ms': round((time.time() - start_time) * 1000, 1)
            })
        
        # Extract with timeout protection
        try:
            logger.info(f"Extracting info for: {url[:50]}...")
            info = timeout_handler(extract_info_with_fallbacks, timeout_duration=60)(url, extras=extras)
            processed = process_info_safely(info)
            
            # Cache successful extraction
            memory_cache.set(cache_key, processed)
            
            return jsonify({
                'success': True,
                'data': processed,
                'cached': False,
                'response_time_ms': round((time.time() - start_time) * 1000, 1)
            })
        except TimeoutException as e:
            logger.warning(f"Extraction timeout: {e}")
            return jsonify({
                'success': False,
                'error': 'Request timed out. Please try again.',
                'suggestion': 'The server is busy or YouTube is rate limiting. Try providing cookies or wait a moment.',
                'response_time_ms': round((time.time() - start_time) * 1000, 1)
            }), 504
        
    except Exception as e:
        logger.error(f"Info extraction failed: {str(e)[:200]}")
        return jsonify({
            'success': False,
            'error': str(e)[:200],
            'suggestion': 'Provide browser cookies (cookies.txt base64) or try again later.',
            'response_time_ms': round((time.time() - start_time) * 1000, 1)
        }), 400

@app.route('/api/download', methods=['POST'])
def start_download():
    try:
        data = request.get_json() or {}
        if not data or 'url' not in data:
            return jsonify({'success': False, 'error': 'URL required'}), 400
        
        # Check capacity
        active_count = len([d for d in active_downloads.values() 
                          if d.get('status') in ['downloading', 'starting']])
        if active_count >= MAX_CONCURRENT_DOWNLOADS:
            return jsonify({
                'success': False, 
                'error': 'Server busy. Please try again in a few minutes.',
                'active_downloads': active_count,
                'max_concurrent': MAX_CONCURRENT_DOWNLOADS,
                'retry_after': 60
            }), 429
        
        url = data['url'].strip()
        quality = data.get('quality', '720p')
        download_id = f"render_{int(time.time() * 1000)}"
        extras = _collect_request_extras(data)
        
        # Start download
        def download_starter():
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            try:
                loop.run_until_complete(download_with_render_limits(url, quality, download_id, extras))
            except Exception as e:
                logger.error(f"Download failed: {e}")
            finally:
                loop.close()
        
        thread = threading.Thread(target=download_starter, daemon=True)
        thread.start()
        
        return jsonify({
            'success': True,
            'download_id': download_id,
            'message': 'Download started with anti-bot protection',
            'quality': quality,
            'estimated_start': '<15 seconds'
        })
        
    except Exception as e:
        logger.error(f"Start download error: {e}")
        return jsonify({
            'success': False,
            'error': str(e)[:150]
        }), 400

@app.route('/api/status/<download_id>')
def get_status(download_id):
    if download_id not in active_downloads:
        return jsonify({'success': False, 'error': 'Download not found'}), 404
    
    status_obj = active_downloads[download_id]
    status = status_obj.copy()
    
    # Add computed fields
    if 'start_time' in status:
        elapsed = time.time() - status['start_time']
        status['elapsed_seconds'] = round(elapsed, 1)
        
        if status.get('progress', 0) > 10 and elapsed > 10:
            estimated_total = elapsed / (status['progress'] / 100)
            status['eta_seconds'] = round(max(0, estimated_total - elapsed), 1)
    
    # Remove sensitive data
    status.pop('file_path', None)
    
    # Format speed
    if 'speed' in status and status['speed']:
        speed_mbps = status['speed'] * 8 / (1024**2)
        status['speed_mbps'] = round(speed_mbps, 2)
    
    return jsonify({
        'success': True,
        'status': status
    })

@app.route('/api/file/<download_id>')
def download_file(download_id):
    if download_id not in active_downloads:
        return jsonify({'error': 'Download not found'}), 404
    
    status_obj = active_downloads[download_id]
    if status_obj.get('status') != 'completed':
        return jsonify({'error': 'Download not ready'}), 400
    
    file_path = status_obj.get('file_path')
    if not file_path or not os.path.exists(file_path):
        return jsonify({'error': 'File not available'}), 404
    
    try:
        filename = status_obj.get('filename', f'video_{download_id}.mp4')
        
        return send_file(
            file_path,
            as_attachment=True,
            download_name=filename,
            mimetype='application/octet-stream'
        )
    except Exception as e:
        logger.error(f"File download error: {e}")
        return jsonify({'error': 'File download failed'}), 500

# =========================
# Error handlers
# =========================
@app.errorhandler(404)
def not_found(e):
    return jsonify({'error': 'Not found'}), 404

@app.errorhandler(429)
def rate_limit_exceeded(e):
    return jsonify({
        'error': 'Rate limit exceeded',
        'message': 'Too many requests. Please wait before trying again.',
        'retry_after': 60
    }), 429

@app.errorhandler(500)
def internal_error(e):
    logger.error(f"Internal error: {e}")
    return jsonify({'error': 'Internal server error'}), 500

# =========================
# Request timing / headers
# =========================
@app.before_request
def before_request():
    # Start background tasks lazily at first request
    ensure_bg_started()
    g.start_time = time.time()

@app.after_request
def after_request(response):
    if hasattr(g, 'start_time'):
        duration = (time.time() - g.start_time) * 1000
        response.headers['X-Response-Time'] = f'{duration:.1f}ms'
    
    # Add anti-bot headers
    response.headers.update({
        'X-Robots-Tag': 'noindex, nofollow',
        'Cache-Control': 'no-cache, no-store, must-revalidate',
        'Pragma': 'no-cache',
        'Expires': '0'
    })
    
    return response

# =========================
# Entrypoint (for local runs)
# =========================
if __name__ == '__main__':
    # For local development: start background thread immediately
    ensure_bg_started()
    port = int(os.environ.get('PORT', 5000))
    
    logger.info(f"""
🚀 YouTube Downloader - Anti-Bot Edition
🛡️  Multiple extraction strategies enabled
🔄 User-agent rotation active
🍪 Cookies: {'env-provided' if ENV_COOKIES_B64 else 'none by default'}
🧭 Proxy: {'set via env' if ENV_PROXY else 'none'}
🌐 Locale: {DEFAULT_HL}-{DEFAULT_GL} | IPv4: {FORCE_IPV4}
📊 Rate limiting: {RATE_LIMIT_DELAY}s between requests
💾 Cache enabled: {MAX_CACHE_SIZE} entries
🧹 Auto-cleanup: {FILE_RETENTION_TIME}s retention
⚡ Max workers: {MAX_WORKERS}
🔗 Max concurrent downloads: {MAX_CONCURRENT_DOWNLOADS}

Server starting on port {port}...
    """)
    
    try:
        app.run(
            host='0.0.0.0',
            port=port,
            debug=False,
            threaded=True,
            use_reloader=False
        )
    except KeyboardInterrupt:
        logger.info("Shutting down gracefully...")
    except Exception as e:
        logger.error(f"Server error: {e}")
    finally:
        # Cleanup on shutdown
        logger.info("Performing final cleanup...")
        cleanup_render_friendly()
        executor.shutdown(wait=True)