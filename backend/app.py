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
from concurrent.futures import ThreadPoolExecutor, as_completed
from functools import lru_cache, wraps
from collections import defaultdict, deque
from queue import Queue, Empty
import gc
import weakref

from flask import Flask, request, jsonify, send_file, Response, g
from flask_cors import CORS
from werkzeug.middleware.proxy_fix import ProxyFix
import yt_dlp
import logging

# Render Free Tier Optimizations
CPU_COUNT = max(1, multiprocessing.cpu_count() // 2)  # Conservative CPU usage
MAX_WORKERS = min(8, CPU_COUNT * 2)  # Limited for 512MB RAM
MAX_PROCESSES = 2  # Very limited process pool
DOWNLOAD_WORKERS = min(4, CPU_COUNT)  # Conservative download workers
CHUNK_SIZE = 512 * 1024  # 512KB chunks (smaller for limited RAM)
BUFFER_SIZE = 2 * 1024 * 1024  # 2MB buffer (reduced)
MAX_CONCURRENT_DOWNLOADS = 5  # Limited concurrent downloads
MAX_FILE_SIZE = 1024 * 1024 * 1024  # 1GB limit (Render free tier friendly)
TEMP_DIR = os.path.join(tempfile.gettempdir(), 'yt_render')
CACHE_DURATION = 600  # 10 minutes cache (shorter for memory)
FILE_RETENTION_TIME = 1800  # 30 minutes retention
MAX_CACHE_SIZE = 100  # Limit cache size

# Create directories
os.makedirs(TEMP_DIR, exist_ok=True)

# Optimized logging for Render
logging.basicConfig(
    level=logging.INFO,  # Keep some logs for debugging on Render
    format='%(asctime)s %(levelname)s: %(message)s',
    handlers=[logging.StreamHandler()]
)
logger = logging.getLogger(__name__)
logging.getLogger('yt_dlp').setLevel(logging.ERROR)

app = Flask(__name__)

# CORS configuration for Render
CORS(app, 
     origins=["*"],  # Render often needs flexible CORS
     methods=["GET", "POST", "OPTIONS"],
     allow_headers=["Content-Type", "Authorization", "X-Requested-With"],
     supports_credentials=False)

app.wsgi_app = ProxyFix(app.wsgi_app, x_for=1, x_proto=1)

# Memory-conscious global structures
executor = ThreadPoolExecutor(max_workers=MAX_WORKERS, thread_name_prefix='API')
download_status = weakref.WeakValueDictionary()  # Auto-cleanup when no references
download_queue = Queue(maxsize=MAX_CONCURRENT_DOWNLOADS)
active_downloads = {}
performance_metrics = {
    'total_requests': 0,
    'active_downloads': 0,
    'cache_hits': 0,
    'cache_misses': 0,
    'start_time': time.time()
}

# Simple in-memory cache with size limit
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
        # Remove oldest items if cache is full
        if len(self.cache) >= self.max_size:
            oldest_keys = sorted(self.access_times.keys(), 
                               key=lambda k: self.access_times[k])[:self.max_size//4]
            for old_key in oldest_keys:
                self.cache.pop(old_key, None)
                self.access_times.pop(old_key, None)
        
        self.cache[key] = (data, time.time())
        self.access_times[key] = time.time()

memory_cache = LimitedCache()

class Status:
    """Lightweight status object"""
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
    """Memory-efficient progress hook for Render"""
    def __init__(self, download_id):
        self.download_id = download_id
        self.last_update = 0
        self.update_count = 0
        
    def __call__(self, d):
        current_time = time.time()
        self.update_count += 1
        
        # Update every 2 seconds or every 20th call
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

@lru_cache(maxsize=1000)  # Smaller cache for memory efficiency
def get_cache_key(url: str) -> str:
    """Generate cache key"""
    return hashlib.md5(url.encode()).hexdigest()[:12]

def get_render_optimized_ydl_opts(quality: str, download_id: str) -> dict:
    """Render-optimized yt-dlp configuration"""
    timestamp = int(time.time())
    output_path = os.path.join(TEMP_DIR, f'render_{download_id}_{timestamp}.%(ext)s')
    
    # Conservative options for Render's limited resources
    opts = {
        'outtmpl': output_path,
        'format_sort': ['res:1080', 'fps:30', 'source'],  # Lower quality preference
        'merge_output_format': 'mp4',
        'concurrent_fragment_downloads': 2,  # Very conservative
        'http_chunk_size': CHUNK_SIZE,
        'buffersize': BUFFER_SIZE,
        'retries': 1,  # Fewer retries
        'fragment_retries': 1,
        'socket_timeout': 20,
        'keep_fragments': False,
        'writeinfojson': False,
        'writesubtitles': False,
        'writeautomaticsub': False,
        'writethumbnail': False,
        'writedescription': False,
        'ignoreerrors': True,  # Continue on errors
        'no_warnings': True,
        'quiet': False,  # Keep some output for Render logs
        'progress_hooks': [RenderProgressHook(download_id)],
        'extractor_args': {
            'youtube': {
                'player_client': ['web'],  # Most reliable client
                'skip': ['dash']  # Skip complex formats
            }
        }
    }
    
    # Render-friendly format selection
    format_map = {
        'best': 'best[height<=1080][filesize<500M]/best[height<=720]',
        '1080p': 'best[height<=1080][filesize<500M]',
        '720p': 'best[height<=720][filesize<300M]',
        '480p': 'best[height<=480][filesize<200M]',
        'audio': 'bestaudio[abr<=192]/bestaudio'
    }
    
    opts['format'] = format_map.get(quality, format_map['720p'])  # Default to 720p
    
    if quality == 'audio':
        opts['postprocessors'] = [{
            'key': 'FFmpegExtractAudio',
            'preferredcodec': 'mp3',
            'preferredquality': '192'  # Lower quality for faster processing
        }]
    
    return opts

def extract_info_render_friendly(url: str) -> dict:
    """Memory-efficient info extraction"""
    ydl_opts = {
        'quiet': False,  # Some output for Render logs
        'no_warnings': True,
        'extract_flat': False,
        'skip_download': True,
        'socket_timeout': 15,
        'extractor_args': {
            'youtube': {
                'player_client': ['web']
            }
        }
    }
    
    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
        return ydl.extract_info(url, download=False)

def process_info_efficiently(info: dict) -> dict:
    """Memory-efficient info processing"""
    processed = {
        'title': (info.get('title', '') or 'Unknown')[:60],  # Shorter titles
        'duration': info.get('duration', 0),
        'uploader': (info.get('uploader', '') or 'Unknown')[:25],
        'view_count': info.get('view_count', 0),
        'thumbnail': info.get('thumbnail', ''),
        'id': info.get('id', ''),
        'description': (info.get('description', '') or '')[:150] + '...'
    }
    
    # Simplified format processing
    if 'formats' in info and info['formats']:
        heights = []
        for fmt in info['formats']:
            height = fmt.get('height', 0)
            if height and height >= 240 and height not in heights:
                heights.append(height)
        
        heights.sort(reverse=True)
        processed['available_qualities'] = heights[:4]  # Max 4 qualities
    else:
        processed['available_qualities'] = [720, 480, 360]  # Default options
    
    return processed

async def download_with_render_limits(url: str, quality: str, download_id: str):
    """Download optimized for Render's limitations"""
    loop = asyncio.get_event_loop()
    
    def download_worker():
        try:
            status_obj = Status(download_id)
            active_downloads[download_id] = status_obj
            
            status_obj.update(
                status='starting',
                message='Initializing download...'
            )
            
            opts = get_render_optimized_ydl_opts(quality, download_id)
            
            status_obj.update(
                status='downloading',
                message='Download in progress...'
            )
            
            # Download with timeout
            with yt_dlp.YoutubeDL(opts) as ydl:
                ydl.download([url])
            
            # Find downloaded file
            prefix = f'render_{download_id}_'
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
                    message=str(e)[:100],
                    error_time=time.time()
                )
            raise
    
    return await loop.run_in_executor(executor, download_worker)

def cleanup_render_friendly():
    """Render-friendly cleanup"""
    try:
        current_time = time.time()
        cleaned = 0
        
        # Clean temp files
        if os.path.exists(TEMP_DIR):
            for file in os.listdir(TEMP_DIR):
                if file.startswith('render_'):
                    file_path = os.path.join(TEMP_DIR, file)
                    try:
                        if current_time - os.path.getctime(file_path) > FILE_RETENTION_TIME:
                            os.remove(file_path)
                            cleaned += 1
                            if cleaned > 5:  # Limit cleanup per run
                                break
                    except:
                        pass
        
        # Clean old downloads (keep only last 50)
        if len(active_downloads) > 50:
            old_downloads = list(active_downloads.keys())[:10]
            for download_id in old_downloads:
                if download_id in active_downloads:
                    status_obj = active_downloads[download_id]
                    if status_obj.get('file_path'):
                        try:
                            os.remove(status_obj.get('file_path'))
                        except:
                            pass
                    del active_downloads[download_id]
        
        # Force garbage collection
        if cleaned > 0:
            gc.collect()
            
        logger.info(f"Cleaned {cleaned} files")
        
    except Exception as e:
        logger.error(f"Cleanup error: {e}")

def start_cleanup_thread():
    """Start background cleanup"""
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

# API Routes
@app.route('/')
def index():
    uptime = time.time() - performance_metrics['start_time']
    return jsonify({
        'name': 'YouTube Downloader - Render Edition',
        'version': '1.0',
        'status': 'operational',
        'uptime_seconds': round(uptime, 1),
        'info': {
            'active_downloads': len([d for d in active_downloads.values() 
                                   if d.get('status') == 'downloading']),
            'max_concurrent': MAX_CONCURRENT_DOWNLOADS,
            'max_file_size_gb': MAX_FILE_SIZE / (1024**3),
            'total_requests': performance_metrics['total_requests'],
            'cache_size': len(memory_cache.cache)
        },
        'features': [
            'Render-optimized performance',
            'Memory-efficient processing',
            'Auto-cleanup system',
            'Limited concurrent downloads'
        ]
    })

@app.route('/api/health')
def health():
    return jsonify({
        'status': 'healthy',
        'timestamp': int(time.time()),
        'metrics': performance_metrics,
        'active_downloads': len(active_downloads),
        'temp_files': len([f for f in os.listdir(TEMP_DIR) if f.startswith('render_')])
    })

@app.route('/api/info', methods=['POST'])
def get_info():
    start_time = time.time()
    performance_metrics['total_requests'] += 1
    
    try:
        data = request.get_json()
        if not data or 'url' not in data:
            return jsonify({'success': False, 'error': 'URL required'}), 400
        
        url = data['url'].strip()
        cache_key = get_cache_key(url)
        
        # Check cache
        cached = memory_cache.get(cache_key)
        if cached:
            performance_metrics['cache_hits'] += 1
            return jsonify({
                'success': True,
                'data': cached,
                'cached': True,
                'response_time_ms': round((time.time() - start_time) * 1000, 1)
            })
        
        performance_metrics['cache_misses'] += 1
        
        # Extract info
        info = extract_info_render_friendly(url)
        processed = process_info_efficiently(info)
        memory_cache.set(cache_key, processed)
        
        return jsonify({
            'success': True,
            'data': processed,
            'cached': False,
            'response_time_ms': round((time.time() - start_time) * 1000, 1)
        })
        
    except Exception as e:
        logger.error(f"Info extraction error: {e}")
        return jsonify({
            'success': False,
            'error': str(e)[:100],
            'response_time_ms': round((time.time() - start_time) * 1000, 1)
        }), 400

@app.route('/api/download', methods=['POST'])
def start_download():
    try:
        data = request.get_json()
        if not data or 'url' not in data:
            return jsonify({'success': False, 'error': 'URL required'}), 400
        
        # Check capacity
        active_count = len([d for d in active_downloads.values() 
                          if d.get('status') in ['downloading', 'starting']])
        if active_count >= MAX_CONCURRENT_DOWNLOADS:
            return jsonify({
                'success': False, 
                'error': f'Server at capacity. Try again later.',
                'active_downloads': active_count,
                'max_concurrent': MAX_CONCURRENT_DOWNLOADS
            }), 429
        
        url = data['url'].strip()
        quality = data.get('quality', '720p')  # Default to 720p for Render
        download_id = f"render_{int(time.time() * 1000)}"
        
        # Start download in background
        def download_starter():
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            try:
                loop.run_until_complete(download_with_render_limits(url, quality, download_id))
            except Exception as e:
                logger.error(f"Download starter error: {e}")
            finally:
                loop.close()
        
        thread = threading.Thread(target=download_starter, daemon=True)
        thread.start()
        
        return jsonify({
            'success': True,
            'download_id': download_id,
            'message': 'Download started',
            'estimated_start': '<10 seconds',
            'quality': quality
        })
        
    except Exception as e:
        logger.error(f"Start download error: {e}")
        return jsonify({
            'success': False,
            'error': str(e)[:100]
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

# Error handlers
@app.errorhandler(404)
def not_found(e):
    return jsonify({'error': 'Not found'}), 404

@app.errorhandler(500)
def internal_error(e):
    logger.error(f"Internal error: {e}")
    return jsonify({'error': 'Internal server error'}), 500

@app.before_request
def before_request():
    g.start_time = time.time()

@app.after_request
def after_request(response):
    if hasattr(g, 'start_time'):
        duration = (time.time() - g.start_time) * 1000
        response.headers['X-Response-Time'] = f'{duration:.1f}ms'
    
    return response

if __name__ == '__main__':
    # Start cleanup thread
    start_cleanup_thread()
    
    port = int(os.environ.get('PORT', 5000))
    
    logger.info(f"""
🚀 YouTube Downloader - Render Edition
📊 Max Workers: {MAX_WORKERS}
⚡ Max Concurrent Downloads: {MAX_CONCURRENT_DOWNLOADS}
💾 Max File Size: {MAX_FILE_SIZE // (1024**3)}GB
🔧 Render Optimized: YES
    """)
    
    app.run(
        host='0.0.0.0',
        port=port,
        debug=False,
        threaded=True
    )