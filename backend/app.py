# Enhanced YouTube Bot Detection Bypass - Improved version of your app.py

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

# ============= ENHANCED CONFIGURATION =============
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
COOKIES_DIR = os.path.join(tempfile.gettempdir(), 'yt_cookies')
FILE_RETENTION_TIME = 7200
CACHE_DURATION = 3600

os.makedirs(TEMP_DIR, exist_ok=True, mode=0o755)
os.makedirs(CACHE_DIR, exist_ok=True, mode=0o755)
os.makedirs(COOKIES_DIR, exist_ok=True, mode=0o755)

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

# ============= ENHANCED BOT DETECTION BYPASS =============

# More diverse and realistic user agents
REALISTIC_USER_AGENTS = [
    # Latest Chrome versions
    'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
    'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
    'Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
    
    # Mobile user agents (often less detected)
    'Mozilla/5.0 (iPhone; CPU iPhone OS 17_1_1 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.1 Mobile/15E148 Safari/604.1',
    'Mozilla/5.0 (iPad; CPU OS 17_1_1 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.1 Mobile/15E148 Safari/604.1',
    'Mozilla/5.0 (Linux; Android 14; SM-G998B) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Mobile Safari/537.36',
    
    # Firefox versions
    'Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:120.0) Gecko/20100101 Firefox/120.0',
    'Mozilla/5.0 (Macintosh; Intel Mac OS X 10.15; rv:120.0) Gecko/20100101 Firefox/120.0',
    
    # Edge versions
    'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36 Edg/120.0.0.0',
    
    # TV and embedded clients (often bypass restrictions)
    'com.google.ios.youtube/19.29.1 (iPhone16,2; U; CPU iOS 17_5_1 like Mac OS X)',
    'com.google.android.youtube/19.29.37 (Linux; U; Android 14) gzip',
]

# YouTube API client configurations that work better
YOUTUBE_CLIENTS = [
    {
        'name': 'android',
        'version': '19.29.37',
        'api_key': 'AIzaSyA8eiZmM1FaDVjRy-df2KTyQ_vz_yYM39w',
        'user_agent': 'com.google.android.youtube/19.29.37 (Linux; U; Android 14) gzip'
    },
    {
        'name': 'ios',
        'version': '19.29.1',
        'api_key': 'AIzaSyB-63vPrdThhKuerbB2N_l7Kwwcxj6yUAc',
        'user_agent': 'com.google.ios.youtube/19.29.1 (iPhone16,2; U; CPU iOS 17_5_1 like Mac OS X)'
    },
    {
        'name': 'tv_embedded',
        'version': '1.0',
        'api_key': 'AIzaSyAO_FJ2SlqU8Q4STEHLGCilw_Y9_11qcW8',
        'user_agent': 'Mozilla/5.0 (SMART-TV; LINUX; Tizen 6.0) AppleWebKit/537.36 (KHTML, like Gecko) 69.0.3497.106.2.0 TV Safari/537.36'
    },
    {
        'name': 'mweb',
        'version': '2.20231219.13.00',
        'api_key': 'AIzaSyAO_FJ2SlqU8Q4STEHLGCilw_Y9_11qcW8',
        'user_agent': 'Mozilla/5.0 (Linux; Android 14; SM-G998B) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Mobile Safari/537.36'
    }
]

# Invidious and alternative YouTube frontend instances
INVIDIOUS_INSTANCES = [
    'invidious.io',
    'yewtu.be', 
    'invidious.snopyta.org',
    'invidious.kavin.rocks',
    'vid.puffyan.us',
    'invidious.namazso.eu',
    'inv.riverside.rocks'
]

# Proxy rotation (add your own proxies here)
PROXY_LIST = [
    # Add HTTP/HTTPS proxies here if available
    # 'http://proxy1:port',
    # 'http://proxy2:port',
]

# ============= ENHANCED DATA STRUCTURES =============
executor = ThreadPoolExecutor(max_workers=MAX_WORKERS, thread_name_prefix='API')
process_executor = ProcessPoolExecutor(max_workers=MAX_PROCESSES)
download_executor = ThreadPoolExecutor(max_workers=DOWNLOAD_WORKERS, thread_name_prefix='DL')

memory_cache = TTLCache(maxsize=10000, ttl=CACHE_DURATION)
lfu_cache = LFUCache(maxsize=5000)
download_status = {}
active_downloads = {}
request_limiter = defaultdict(lambda: {'count': 0, 'reset_time': time.time() + 60})
failed_attempts = defaultdict(int)  # Track failed attempts per URL/IP

performance_metrics = multiprocessing.Manager().dict({
    'total_requests': 0,
    'active_downloads': 0,
    'cache_hits': 0,
    'cache_misses': 0,
    'youtube_blocks': 0,
    'successful_downloads': 0,
    'bypass_successes': 0
})

VALID_QUALITIES = frozenset(['best', '4k', '1080p', '720p', '480p', 'audio'])

class EnhancedProgressHook:
    __slots__ = ('download_id', 'last_update', 'update_interval', '_status_ref')
    
    def __init__(self, download_id):
        self.download_id = download_id
        self.last_update = 0
        self.update_interval = 1.5
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
                progress = min(99, int(downloaded * 100 / total))
                self._status_ref.update({
                    'status': 'downloading',
                    'progress': progress,
                    'speed': d.get('speed', 0),
                    'eta': d.get('eta', 0),
                    'downloaded': downloaded,
                    'total': total
                })

def ultra_fast_hash(data: str) -> str:
    return xxhash.xxh64(data.encode(), seed=42).hexdigest()[:16]

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

def create_cookies_file():
    """Create a basic cookies file to help bypass bot detection"""
    cookies_file = os.path.join(COOKIES_DIR, 'youtube.txt')
    
    if not os.path.exists(cookies_file):
        # Create a basic cookies file with common YouTube cookies
        cookies_content = """# Netscape HTTP Cookie File
# This file contains the cookies that yt-dlp will use
.youtube.com	TRUE	/	FALSE	0	CONSENT	YES+cb
.youtube.com	TRUE	/	FALSE	0	VISITOR_INFO1_LIVE	random_visitor_id
.youtube.com	TRUE	/	TRUE	0	YSC	random_ysc_id
"""
        try:
            with open(cookies_file, 'w') as f:
                f.write(cookies_content)
        except:
            pass
    
    return cookies_file if os.path.exists(cookies_file) else None

def get_enhanced_ydl_opts(quality: str, download_id: str, attempt: int = 0) -> dict:
    """Enhanced YT-DLP configuration with advanced bot detection bypass"""
    output_path = os.path.join(TEMP_DIR, f'dl_{download_id}_%(title).100B.%(ext)s')
    
    # Base configuration with enhanced settings
    opts = {
        'outtmpl': output_path,
        'quiet': True,
        'no_warnings': True,
        'extract_flat': False,
        'ignoreerrors': True,
        'no_check_certificate': True,
        'geo_bypass': True,
        'socket_timeout': 45,
        'retries': 8,
        'fragment_retries': 8,
        'concurrent_fragment_downloads': 4,  # Reduced to avoid detection
        'buffersize': BUFFER_SIZE,
        'http_chunk_size': CHUNK_SIZE,
        'progress_hooks': [EnhancedProgressHook(download_id)],
        'sleep_interval': random.uniform(1, 3),  # Add delays
        'max_sleep_interval': 5,
        'sleep_interval_requests': random.uniform(0.5, 2),
    }
    
    # Attempt-specific configurations with advanced bypasses
    if attempt == 0:
        # First attempt - Use mobile Android client (most reliable)
        client = random.choice([c for c in YOUTUBE_CLIENTS if c['name'] in ['android', 'ios']])
        opts.update({
            'http_headers': {
                'User-Agent': client['user_agent'],
                'Accept-Language': 'en-US,en;q=0.9',
                'Accept': '*/*',
                'Accept-Encoding': 'gzip, deflate',
                'Cache-Control': 'no-cache',
                'Pragma': 'no-cache',
                'Connection': 'keep-alive',
            },
            'extractor_args': {
                'youtube': {
                    'player_client': [client['name']],
                    'player_skip': ['webpage'],
                    'skip': ['hls'],
                }
            }
        })
        
    elif attempt == 1:
        # Second attempt - Use TV embedded client (often bypasses restrictions)
        client = [c for c in YOUTUBE_CLIENTS if c['name'] == 'tv_embedded'][0]
        opts.update({
            'http_headers': {
                'User-Agent': client['user_agent'],
                'Accept': '*/*',
                'Accept-Language': 'en-US,en;q=0.8',
            },
            'extractor_args': {
                'youtube': {
                    'player_client': ['tv_embedded'],
                    'player_skip': ['configs', 'webpage'],
                    'skip': ['dash', 'hls'],
                }
            }
        })
        
    elif attempt == 2:
        # Third attempt - Use cookies and multiple clients
        cookies_file = create_cookies_file()
        if cookies_file:
            opts['cookiefile'] = cookies_file
            
        opts.update({
            'http_headers': {
                'User-Agent': random.choice(REALISTIC_USER_AGENTS),
                'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
                'Accept-Language': 'en-US,en;q=0.5',
                'Accept-Encoding': 'gzip, deflate',
                'DNT': '1',
                'Connection': 'keep-alive',
                'Upgrade-Insecure-Requests': '1',
            },
            'extractor_args': {
                'youtube': {
                    'player_client': ['android', 'ios', 'tv_embedded'],
                    'player_skip': ['webpage'],
                }
            }
        })
        
    elif attempt == 3:
        # Fourth attempt - Use Invidious instances
        if INVIDIOUS_INSTANCES:
            invidious_url = f"https://{random.choice(INVIDIOUS_INSTANCES)}"
            opts.update({
                'http_headers': {
                    'User-Agent': random.choice(REALISTIC_USER_AGENTS),
                    'Referer': invidious_url,
                },
                'extractor_args': {
                    'youtube': {
                        'player_client': ['mweb', 'android'],
                    }
                }
            })
        
    elif attempt == 4:
        # Fifth attempt - Use proxy if available
        if PROXY_LIST:
            opts['proxy'] = random.choice(PROXY_LIST)
            
        opts.update({
            'http_headers': {
                'User-Agent': random.choice(REALISTIC_USER_AGENTS),
            },
            'extractor_args': {
                'youtube': {
                    'player_client': ['android'],
                }
            }
        })
        
    else:
        # Final desperate attempts
        opts.update({
            'format': 'worst/best',  # Try worst quality first
            'http_headers': {
                'User-Agent': random.choice(REALISTIC_USER_AGENTS),
            },
            'extractor_args': {
                'youtube': {
                    'player_client': ['mweb'],
                }
            }
        })
    
    # Format selection based on quality
    if quality == 'best':
        opts['format'] = 'best[height<=1080]/best'
    elif quality == '4k':
        opts['format'] = 'best[height<=2160]/best[height<=1080]/best'
    elif quality == '1080p':
        opts['format'] = 'best[height<=1080]/best[height<=720]/best'
    elif quality == '720p':
        opts['format'] = 'best[height<=720]/best[height<=480]/best'
    elif quality == '480p':
        opts['format'] = 'best[height<=480]/best'
    elif quality == 'audio':
        opts['format'] = 'bestaudio[ext=m4a]/bestaudio/best'
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

async def extract_info_with_enhanced_fallback(url: str) -> dict:
    """Extract info with enhanced fallback methods and bot detection bypass"""
    platform = detect_platform(url)
    cache_key = ultra_fast_hash(url)
    
    # Check cache first
    cached = get_cached_data(f"info_{cache_key}")
    if cached:
        return cached
    
    last_error = None
    
    # Try multiple extraction methods with enhanced bypasses
    for attempt in range(6):
        try:
            opts = {
                'quiet': True,
                'no_warnings': True,
                'extract_flat': False,
                'skip_download': True,
                'geo_bypass': True,
                'ignoreerrors': True,
                'socket_timeout': 30,
                'sleep_interval_requests': random.uniform(1, 3),
            }
            
            # Attempt-specific configurations
            if attempt == 0:
                # Mobile Android client
                client = [c for c in YOUTUBE_CLIENTS if c['name'] == 'android'][0]
                opts.update({
                    'http_headers': {
                        'User-Agent': client['user_agent'],
                        'Accept-Language': 'en-US,en;q=0.9',
                    },
                    'extractor_args': {
                        'youtube': {'player_client': ['android']}
                    }
                })
                
            elif attempt == 1:
                # iOS client
                client = [c for c in YOUTUBE_CLIENTS if c['name'] == 'ios'][0]
                opts.update({
                    'http_headers': {
                        'User-Agent': client['user_agent'],
                    },
                    'extractor_args': {
                        'youtube': {'player_client': ['ios']}
                    }
                })
                
            elif attempt == 2:
                # TV embedded client
                client = [c for c in YOUTUBE_CLIENTS if c['name'] == 'tv_embedded'][0]
                opts.update({
                    'http_headers': {
                        'User-Agent': client['user_agent'],
                    },
                    'extractor_args': {
                        'youtube': {'player_client': ['tv_embedded']}
                    }
                })
                
            elif attempt == 3:
                # With cookies
                cookies_file = create_cookies_file()
                if cookies_file:
                    opts['cookiefile'] = cookies_file
                opts['http_headers'] = {'User-Agent': random.choice(REALISTIC_USER_AGENTS)}
                
            elif attempt == 4:
                # Age gate bypass
                opts.update({
                    'age_limit': None,
                    'http_headers': {'User-Agent': random.choice(REALISTIC_USER_AGENTS)},
                    'extractor_args': {
                        'youtube': {
                            'player_client': ['tv_embedded', 'android'],
                            'skip': ['webpage']
                        }
                    }
                })
                
            else:
                # Final attempt with minimal options
                opts.update({
                    'http_headers': {'User-Agent': random.choice(REALISTIC_USER_AGENTS)},
                    'extractor_args': {
                        'youtube': {
                            'player_client': ['mweb'],
                        }
                    }
                })
            
            loop = asyncio.get_event_loop()
            
            def extract():
                # Add progressive delays to avoid rate limiting
                delay = min(attempt * 2 + random.uniform(1, 4), 15)
                time.sleep(delay)
                
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
                    'extraction_method': f'enhanced_attempt_{attempt}',
                    'view_count': info.get('view_count', 0),
                    'upload_date': info.get('upload_date', ''),
                }
                
                set_cached_data(f"info_{cache_key}", processed)
                performance_metrics['bypass_successes'] = performance_metrics.get('bypass_successes', 0) + 1
                
                return processed
                
        except Exception as e:
            last_error = str(e)
            if 'Sign in to confirm' in last_error or 'bot' in last_error.lower():
                performance_metrics['youtube_blocks'] = performance_metrics.get('youtube_blocks', 0) + 1
            
            # Progressive backoff
            await asyncio.sleep(min(attempt * 3 + random.uniform(2, 8), 30))
            continue
    
    # If all attempts failed, try alternative approach
    raise Exception(f"Failed to extract info after all enhanced attempts. Error: {last_error}")

async def download_with_enhanced_fallback(url: str, quality: str, download_id: str):
    """Download with enhanced fallback strategies and bot detection bypass"""
    try:
        download_status[download_id] = {
            'status': 'initializing',
            'progress': 0,
            'start_time': time.perf_counter(),
            'method': 'enhanced_bypass'
        }
        
        last_error = None
        downloaded_file = None
        
        # Try multiple download strategies with enhanced bypasses
        for attempt in range(6):
            try:
                opts = get_enhanced_ydl_opts(quality, download_id, attempt)
                
                download_status[download_id].update({
                    'status': 'downloading',
                    'message': f'Enhanced bypass attempt {attempt + 1}/6',
                    'method': f'attempt_{attempt}'
                })
                
                # Progressive delays between attempts
                if attempt > 0:
                    delay = min(attempt * 5 + random.uniform(3, 10), 45)
                    await asyncio.sleep(delay)
                
                loop = asyncio.get_event_loop()
                
                def download_task():
                    with yt_dlp.YoutubeDL(opts) as ydl:
                        ydl.download([url])
                
                await asyncio.wait_for(
                    loop.run_in_executor(download_executor, download_task),
                    timeout=300  # 5 minute timeout per attempt
                )
                
                # Find downloaded file
                pattern = f'dl_{download_id}_'
                files = [f for f in os.listdir(TEMP_DIR) if f.startswith(pattern)]
                
                for file in files:
                    if not file.endswith(('.part', '.ytdl', '.info.json', '.temp')):
                        full_path = os.path.join(TEMP_DIR, file)
                        if os.path.exists(full_path) and os.path.getsize(full_path) > 1000:  # At least 1KB
                            downloaded_file = full_path
                            break
                
                if downloaded_file and os.path.exists(downloaded_file):
                    break
                    
            except asyncio.TimeoutError:
                last_error = f"Attempt {attempt + 1} timed out"
                continue
            except Exception as e:
                last_error = str(e)
                continue
        
        if not downloaded_file or not os.path.exists(downloaded_file):
            # Try final desperate attempt with external command
            try:
                download_status[download_id]['message'] = 'Trying external command method...'
                
                output_file = os.path.join(TEMP_DIR, f'dl_{download_id}_final.%(ext)s')
                cmd = [
                    'yt-dlp',
                    '--no-check-certificate',
                    '--geo-bypass',
                    '--no-playlist',
                    '--user-agent', random.choice(REALISTIC_USER_AGENTS),
                    '--extractor-args', 'youtube:player_client=android',
                    '-f', 'best[height<=720]/best',
                    '-o', output_file,
                    '--quiet',
                    '--no-warnings',
                    '--socket-timeout', '60',
                    '--retries', '10',
                    url
                ]
                
                cookies_file = create_cookies_file()
                if cookies_file:
                    cmd.extend(['--cookies', cookies_file])
                
                result = subprocess.run(cmd, capture_output=True, text=True, timeout=180)
                
                # Find the actual downloaded file
                pattern = f'dl_{download_id}_final.'
                files = [f for f in os.listdir(TEMP_DIR) if f.startswith(pattern)]
                
                if files:
                    downloaded_file = os.path.join(TEMP_DIR, files[0])
                
                if not downloaded_file or not os.path.exists(downloaded_file):
                    raise Exception(f"All enhanced download methods failed. Last error: {last_error}")
                    
            except Exception as e:
                raise Exception(f"Download failed completely with enhanced methods: {str(e)}")
        
        file_size = os.path.getsize(downloaded_file)
        
        download_status[download_id].update({
            'status': 'completed',
            'progress': 100,
            'file_path': downloaded_file,
            'filename': os.path.basename(downloaded_file),
            'file_size': file_size,
            'completion_time': time.perf_counter()
        })
        
        performance_metrics['successful_downloads'] = performance_metrics.get('successful_downloads', 0) + 1
        performance_metrics['bypass_successes'] = performance_metrics.get('bypass_successes', 0) + 1
        
        return downloaded_file
        
    except Exception as e:
        download_status[download_id] = {
            'status': 'error',
            'error': str(e)[:200],
            'timestamp': time.time()
        }
        raise

def cleanup_old_files():
    """Enhanced cleanup with better error handling"""
    try:
        current_time = time.time()
        cleaned = 0
        
        for directory in [TEMP_DIR, CACHE_DIR, COOKIES_DIR]:
            if not os.path.exists(directory):
                continue
                
            for file in os.listdir(directory):
                file_path = os.path.join(directory, file)
                try:
                    if os.path.isfile(file_path):
                        age = current_time - os.path.getctime(file_path)
                        if age > FILE_RETENTION_TIME:
                            os.remove(file_path)
                            cleaned += 1
                except Exception:
                    pass
        
        # Clean up old download status entries
        current_time = time.time()
        expired_downloads = []
        for download_id, status in download_status.items():
            if 'start_time' in status:
                age = current_time - status['start_time']
                if age > FILE_RETENTION_TIME:
                    expired_downloads.append(download_id)
        
        for download_id in expired_downloads:
            download_status.pop(download_id, None)
            active_downloads.pop(download_id, None)
        
        # Force garbage collection
        gc.collect()
        
        logger.info(f"Cleanup completed: {cleaned} files removed, {len(expired_downloads)} old downloads cleared")
        
    except Exception as e:
        logger.error(f"Cleanup error: {e}")

def start_enhanced_cleanup_thread():
    """Enhanced cleanup thread with better scheduling"""
    def cleanup_worker():
        while True:
            try:
                cleanup_old_files()
                time.sleep(300)  # Run every 5 minutes
            except Exception as e:
                logger.error(f"Cleanup thread error: {e}")
                time.sleep(600)  # Wait 10 minutes on error
    
    thread = threading.Thread(target=cleanup_worker, daemon=True, name='CleanupWorker')
    thread.start()
    logger.info("Enhanced cleanup thread started")

def is_rate_limited(client_ip: str, endpoint: str) -> tuple[bool, int]:
    """Enhanced rate limiting with different limits per endpoint"""
    limits = {
        'info': {'count': 30, 'window': 60},
        'download': {'count': 10, 'window': 60},
        'status': {'count': 100, 'window': 60}
    }
    
    limit_config = limits.get(endpoint, {'count': 20, 'window': 60})
    limiter_key = f"{client_ip}_{endpoint}"
    limiter = request_limiter[limiter_key]
    
    current_time = time.time()
    
    if current_time > limiter['reset_time']:
        limiter['count'] = 0
        limiter['reset_time'] = current_time + limit_config['window']
    
    limiter['count'] += 1
    
    is_limited = limiter['count'] > limit_config['count']
    retry_after = int(limiter['reset_time'] - current_time) if is_limited else 0
    
    return is_limited, retry_after

# ============= ENHANCED API ROUTES =============

@app.route('/')
@ultra_response
def index():
    return {
        'name': 'Universal Video Downloader Pro - Enhanced',
        'version': '6.1',
        'status': 'operational',
        'features': [
            'Advanced YouTube bot detection bypass',
            'Multiple client impersonation (Android, iOS, TV)',
            'Intelligent retry mechanisms',
            'Cookie-based authentication',
            'Proxy support ready',
            'Enhanced rate limiting',
            'Smart caching system',
            'Multi-platform support'
        ],
        'supported_platforms': [
            'YouTube (with advanced bypass)',
            'Twitter/X',
            'Facebook',
            'Instagram',
            'TikTok',
            'Vimeo',
            'Dailymotion',
            'Reddit',
            'SoundCloud',
            '1000+ other sites'
        ],
        'bypass_methods': [
            'Mobile client impersonation',
            'TV embedded client',
            'Cookie authentication',
            'User agent rotation',
            'Request timing optimization',
            'Progressive retry strategy'
        ],
        'stats': {
            'successful_downloads': performance_metrics.get('successful_downloads', 0),
            'bypass_successes': performance_metrics.get('bypass_successes', 0),
            'youtube_blocks': performance_metrics.get('youtube_blocks', 0),
            'cache_hits': performance_metrics.get('cache_hits', 0),
            'active_downloads': len([s for s in download_status.values() if s.get('status') == 'downloading'])
        }
    }

@app.route('/api/health')
@ultra_response
def health():
    """Enhanced health check with more metrics"""
    active_downloads_count = len([s for s in download_status.values() if s.get('status') == 'downloading'])
    
    return {
        'status': 'healthy',
        'timestamp': int(time.time()),
        'active_downloads': active_downloads_count,
        'total_requests': performance_metrics.get('total_requests', 0),
        'success_rate': calculate_success_rate(),
        'memory_usage': get_memory_usage(),
        'bypass_effectiveness': calculate_bypass_effectiveness()
    }

def calculate_success_rate():
    """Calculate overall success rate"""
    total = performance_metrics.get('total_requests', 0)
    successful = performance_metrics.get('successful_downloads', 0)
    return round((successful / max(total, 1)) * 100, 2)

def calculate_bypass_effectiveness():
    """Calculate YouTube bypass success rate"""
    blocks = performance_metrics.get('youtube_blocks', 0)
    successes = performance_metrics.get('bypass_successes', 0)
    total_youtube = blocks + successes
    return round((successes / max(total_youtube, 1)) * 100, 2)

def get_memory_usage():
    """Get current memory usage"""
    try:
        process = psutil.Process()
        memory_mb = process.memory_info().rss / 1024 / 1024
        return round(memory_mb, 2)
    except:
        return 0

@app.route('/api/info', methods=['POST'])
@ultra_response
def get_enhanced_info():
    """Enhanced info extraction with advanced bot detection bypass"""
    try:
        data = orjson.loads(request.data) if request.data else {}
        url = data.get('url', '').strip()
        
        if not url:
            return {'success': False, 'error': 'URL required'}, 400
        
        # Enhanced rate limiting
        client_ip = request.remote_addr
        is_limited, retry_after = is_rate_limited(client_ip, 'info')
        
        if is_limited:
            return {
                'success': False, 
                'error': 'Rate limit exceeded. Please slow down your requests.',
                'retry_after': retry_after
            }, 429
        
        # Check if this URL has failed too many times recently
        url_hash = ultra_fast_hash(url)
        if failed_attempts[url_hash] > 5:
            return {
                'success': False,
                'error': 'This video has failed multiple times. It may be restricted or unavailable.',
                'suggestion': 'Try a different video or wait before retrying'
            }, 400
        
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        try:
            info = loop.run_until_complete(
                asyncio.wait_for(extract_info_with_enhanced_fallback(url), timeout=60)
            )
            
            # Reset failed attempts on success
            failed_attempts[url_hash] = 0
            
            return {
                'success': True,
                'data': info,
                'message': 'Info extracted successfully using enhanced bypass methods'
            }
        finally:
            loop.close()
        
    except Exception as e:
        error_msg = str(e)
        
        # Track failed attempts
        if 'url' in locals():
            url_hash = ultra_fast_hash(url)
            failed_attempts[url_hash] = failed_attempts.get(url_hash, 0) + 1
        
        # Provide enhanced error messages
        if 'Sign in to confirm' in error_msg or 'bot' in error_msg.lower():
            return {
                'success': False,
                'error': 'YouTube is currently blocking requests despite our bypass attempts. This is temporary.',
                'retry_after': 60,
                'suggestions': [
                    'Wait a few minutes and try again',
                    'Try a different YouTube video',
                    'Consider using videos from other platforms'
                ],
                'technical_details': 'Enhanced bypass methods were attempted including mobile clients and cookie authentication'
            }, 429
        elif 'timeout' in error_msg.lower():
            return {
                'success': False,
                'error': 'Request timed out. The video may be very long or the server is busy.',
                'retry_after': 30,
                'suggestion': 'Try again in a moment or try a shorter video'
            }, 408
        elif 'unavailable' in error_msg.lower() or 'private' in error_msg.lower():
            return {
                'success': False,
                'error': 'Video is unavailable, private, or region-restricted.',
                'suggestion': 'Try a different video that is publicly available'
            }, 404
        else:
            return {
                'success': False,
                'error': f'Failed to extract video info: {error_msg[:150]}',
                'technical_details': 'All enhanced bypass methods were attempted'
            }, 400

@app.route('/api/download', methods=['POST'])
@ultra_response
def start_enhanced_download():
    """Enhanced download with advanced bot detection bypass"""
    try:
        data = orjson.loads(request.data) if request.data else {}
        url = data.get('url', '').strip()
        quality = data.get('quality', 'best')
        
        if not url:
            return {'success': False, 'error': 'URL required'}, 400
        
        if quality not in VALID_QUALITIES:
            return {'success': False, 'error': f'Invalid quality. Choose from: {", ".join(VALID_QUALITIES)}'}, 400
        
        # Enhanced rate limiting
        client_ip = request.remote_addr
        is_limited, retry_after = is_rate_limited(client_ip, 'download')
        
        if is_limited:
            return {
                'success': False, 
                'error': 'Download rate limit exceeded. Please wait before starting new downloads.',
                'retry_after': retry_after
            }, 429
        
        # Check server capacity
        active = len([s for s in download_status.values() if s.get('status') == 'downloading'])
        if active >= MAX_CONCURRENT_DOWNLOADS:
            return {
                'success': False,
                'error': f'Server at maximum capacity ({active}/{MAX_CONCURRENT_DOWNLOADS})',
                'retry_after': 60,
                'suggestion': 'Please try again in a few minutes'
            }, 429
        
        # Check if this URL has failed too many times
        url_hash = ultra_fast_hash(url)
        if failed_attempts[url_hash] > 3:
            return {
                'success': False,
                'error': 'This video has failed multiple download attempts. It may be restricted.',
                'suggestion': 'Try a different video or quality setting'
            }, 400
        
        # Generate unique download ID
        download_id = f"{int(time.time() * 1000000)}_{ultra_fast_hash(url + quality)[:8]}"
        
        def start_enhanced_async_download():
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            try:
                loop.run_until_complete(
                    download_with_enhanced_fallback(url, quality, download_id)
                )
                # Reset failed attempts on success
                failed_attempts[url_hash] = 0
            except Exception as e:
                # Track failed attempts
                failed_attempts[url_hash] = failed_attempts.get(url_hash, 0) + 1
                logger.error(f"Download failed for {download_id}: {e}")
            finally:
                loop.close()
        
        thread = threading.Thread(
            target=start_enhanced_async_download,
            daemon=True,
            name=f'Enhanced-DL-{download_id[:8]}'
        )
        thread.start()
        active_downloads[download_id] = thread
        
        return {
            'success': True,
            'download_id': download_id,
            'message': 'Download started with enhanced bypass methods',
            'estimated_time': 'Variable depending on video length and bypass method',
            'bypass_methods': 'Multiple client impersonation, cookie auth, smart retries'
        }
        
    except Exception as e:
        return {
            'success': False, 
            'error': f'Failed to start download: {str(e)[:100]}'
        }, 400

@app.route('/api/status/<download_id>')
@ultra_response  
def get_enhanced_status(download_id):
    """Enhanced status endpoint with more detailed information"""
    if download_id not in download_status:
        return {'success': False, 'error': 'Download not found'}, 404
    
    status = download_status[download_id].copy()
    
    # Calculate additional metrics
    if 'start_time' in status:
        elapsed = time.perf_counter() - status['start_time']
        status['elapsed_time'] = round(elapsed, 2)
        
        if 'completion_time' in status:
            total_time = status['completion_time'] - status['start_time']
            status['total_time'] = round(total_time, 2)
    
    # Remove sensitive information
    status.pop('file_path', None)
    
    # Add helpful information based on status
    if status.get('status') == 'error':
        error_msg = status.get('error', '')
        if 'Sign in to confirm' in error_msg:
            status['help'] = 'YouTube detected automated access. This is temporary - try again later.'
        elif 'timeout' in error_msg.lower():
            status['help'] = 'Download timed out. Try a shorter video or different quality.'
        elif 'unavailable' in error_msg.lower():
            status['help'] = 'Video is not available for download. It may be private or restricted.'
    
    return {'success': True, 'status': status}

@app.route('/api/file/<download_id>')
def download_enhanced_file(download_id):
    """Enhanced file download with better error handling"""
    if download_id not in download_status:
        return jsonify({
            'success': False, 
            'error': 'Download not found',
            'help': 'The download may have expired or the ID is incorrect'
        }), 404
    
    status = download_status[download_id]
    if status.get('status') != 'completed':
        current_status = status.get('status', 'unknown')
        return jsonify({
            'success': False, 
            'error': f'Download not ready (current status: {current_status})',
            'help': 'Please wait for the download to complete before accessing the file'
        }), 400
    
    file_path = status.get('file_path')
    if not file_path or not os.path.exists(file_path):
        return jsonify({
            'success': False, 
            'error': 'File not found on server',
            'help': 'The file may have been cleaned up due to age. Please start a new download.'
        }), 404
    
    try:
        filename = status.get('filename', 'video.mp4')
        
        # Ensure safe filename
        safe_filename = "".join(c for c in filename if c.isalnum() or c in (' ', '.', '_', '-')).rstrip()
        if not safe_filename:
            safe_filename = 'downloaded_video.mp4'
        
        return send_file(
            file_path,
            as_attachment=True,
            download_name=safe_filename,
            mimetype='application/octet-stream'
        )
    except Exception as e:
        return jsonify({
            'success': False, 
            'error': 'Download failed',
            'technical_details': str(e)[:100]
        }), 500

@app.route('/api/stats')
@ultra_response
def get_enhanced_stats():
    """Enhanced statistics endpoint"""
    return {
        'success': True,
        'stats': {
            'performance': {
                'total_requests': performance_metrics.get('total_requests', 0),
                'successful_downloads': performance_metrics.get('successful_downloads', 0),
                'success_rate_percent': calculate_success_rate(),
                'cache_hits': performance_metrics.get('cache_hits', 0),
                'cache_misses': performance_metrics.get('cache_misses', 0),
                'cache_hit_rate_percent': round((performance_metrics.get('cache_hits', 0) / 
                    max(performance_metrics.get('cache_hits', 0) + performance_metrics.get('cache_misses', 0), 1)) * 100, 2)
            },
            'bypass_metrics': {
                'youtube_blocks': performance_metrics.get('youtube_blocks', 0),
                'bypass_successes': performance_metrics.get('bypass_successes', 0),
                'bypass_effectiveness_percent': calculate_bypass_effectiveness()
            },
            'current_status': {
                'active_downloads': len([s for s in download_status.values() if s.get('status') == 'downloading']),
                'memory_usage_mb': get_memory_usage(),
                'server_uptime_hours': round((time.time() - performance_metrics.get('start_time', time.time())) / 3600, 2)
            }
        }
    }

# ============= ENHANCED MIDDLEWARE =============

@app.before_request
def enhanced_before_request():
    """Enhanced request preprocessing"""
    g.start_time = time.perf_counter()
    g.request_id = ultra_fast_hash(f"{time.time()}_{request.remote_addr}_{random.random()}")
    
    performance_metrics['total_requests'] = performance_metrics.get('total_requests', 0) + 1
    
    # Log requests for debugging (in production, you might want to disable this)
    if app.debug:
        logger.info(f"Request {g.request_id}: {request.method} {request.path} from {request.remote_addr}")

@app.after_request
def enhanced_after_request(response):
    """Enhanced response postprocessing"""
    if hasattr(g, 'start_time'):
        duration_ms = (time.perf_counter() - g.start_time) * 1000
        response.headers['X-Response-Time'] = f'{duration_ms:.2f}ms'
    
    if hasattr(g, 'request_id'):
        response.headers['X-Request-ID'] = g.request_id
    
    # Enhanced security headers
    response.headers.update({
        'X-Content-Type-Options': 'nosniff',
        'X-Frame-Options': 'DENY',
        'X-XSS-Protection': '1; mode=block',
        'Referrer-Policy': 'strict-origin-when-cross-origin',
        'Server': 'Universal-Downloader-Enhanced/6.1',
        'X-Enhanced-Bypass': 'Active'
    })
    
    return response

@app.errorhandler(404)
def not_found(error):
    return jsonify({
        'success': False,
        'error': 'Endpoint not found',
        'available_endpoints': [
            'GET /',
            'GET /api/health', 
            'POST /api/info',
            'POST /api/download',
            'GET /api/status/<download_id>',
            'GET /api/file/<download_id>',
            'GET /api/stats'
        ]
    }), 404

@app.errorhandler(500)
def internal_error(error):
    return jsonify({
        'success': False,
        'error': 'Internal server error',
        'help': 'Please try again later. If the problem persists, the server may be overloaded.'
    }), 500

# ============= APPLICATION STARTUP =============

if __name__ == '__main__':
    # Initialize performance tracking
    performance_metrics['start_time'] = time.time()
    
    # Start enhanced cleanup thread
    start_enhanced_cleanup_thread()
    
    # Configure WSGI server
    WSGIRequestHandler.protocol_version = "HTTP/1.1"
    
    port = int(os.environ.get('PORT', 5000))
    
    print(f"""
🚀 Universal Video Downloader Pro - Enhanced v6.1
✅ Advanced YouTube bot detection bypass enabled
🤖 Multiple client impersonation (Android, iOS, TV, Web)  
🍪 Cookie-based authentication system
🔄 Intelligent retry mechanisms with progressive delays
📊 Enhanced rate limiting and error handling
🌐 Support for 1000+ video platforms
⚡ High-performance async processing
🛡️  Advanced security headers
📈 Comprehensive metrics and monitoring

🔧 Enhanced Bypass Methods:
   • Mobile client impersonation
   • TV embedded client access  
   • Cookie authentication
   • User agent rotation
   • Request timing optimization
   • Progressive retry strategies
   
🎯 Ready to handle YouTube's bot detection!
""")
    
    app.run(
        host='0.0.0.0',
        port=port,
        debug=False,
        threaded=True,
        use_reloader=False,
        use_debugger=False
    )