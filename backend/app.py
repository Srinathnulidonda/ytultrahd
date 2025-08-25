import os
import json
import time
import asyncio
import threading
import tempfile
import hashlib
import multiprocessing
from datetime import datetime
from concurrent.futures import ThreadPoolExecutor
from functools import lru_cache, wraps
from collections import defaultdict
import gc
import traceback

from flask import Flask, request, jsonify, send_file, Response, g
from flask_cors import CORS
from werkzeug.middleware.proxy_fix import ProxyFix
import yt_dlp
import logging

# Render Free Tier Configuration
CPU_COUNT = max(1, multiprocessing.cpu_count() // 2)
MAX_WORKERS = min(6, CPU_COUNT * 2)
DOWNLOAD_WORKERS = 3
CHUNK_SIZE = 512 * 1024  # 512KB
MAX_CONCURRENT_DOWNLOADS = 3
MAX_FILE_SIZE = 800 * 1024 * 1024  # 800MB for safety
TEMP_DIR = os.path.join(tempfile.gettempdir(), 'yt_render')
CACHE_DURATION = 600  # 10 minutes
FILE_RETENTION_TIME = 1800  # 30 minutes

# Ensure temp directory exists
os.makedirs(TEMP_DIR, exist_ok=True)

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# Suppress yt-dlp logs
logging.getLogger('yt_dlp').setLevel(logging.ERROR)

app = Flask(__name__)

# Enhanced CORS for Render
CORS(app, 
     resources={
         r"/api/*": {
             "origins": "*",
             "methods": ["GET", "POST", "OPTIONS"],
             "allow_headers": ["Content-Type", "Accept", "Authorization"]
         }
     })

app.wsgi_app = ProxyFix(app.wsgi_app, x_for=1, x_proto=1)

# Global structures
executor = ThreadPoolExecutor(max_workers=MAX_WORKERS)
download_status = {}
active_downloads = {}
simple_cache = {}
performance_metrics = {
    'total_requests': 0,
    'errors': 0,
    'successful_downloads': 0,
    'start_time': time.time()
}

class SimpleProgressHook:
    """Simplified progress tracking"""
    def __init__(self, download_id):
        self.download_id = download_id
        self.last_update = 0
        
    def __call__(self, d):
        current_time = time.time()
        
        # Update every 3 seconds
        if current_time - self.last_update < 3.0:
            return
            
        self.last_update = current_time
        
        try:
            if self.download_id not in download_status:
                return
                
            if d['status'] == 'downloading':
                total = d.get('total_bytes') or d.get('total_bytes_estimate', 0)
                downloaded = d.get('downloaded_bytes', 0)
                
                if total > 0:
                    progress = (downloaded / total) * 100
                    download_status[self.download_id].update({
                        'status': 'downloading',
                        'progress': round(progress, 1),
                        'speed': d.get('speed', 0),
                        'downloaded_bytes': downloaded,
                        'total_bytes': total
                    })
                    
            elif d['status'] == 'finished':
                download_status[self.download_id].update({
                    'status': 'processing',
                    'progress': 90,
                    'message': 'Processing download...'
                })
                
        except Exception as e:
            logger.error(f"Progress hook error: {e}")

def safe_json_response(data, status_code=200):
    """Safe JSON response with error handling"""
    try:
        return jsonify(data), status_code
    except Exception as e:
        logger.error(f"JSON response error: {e}")
        return jsonify({'error': 'Response formatting error'}), 500

def validate_url(url):
    """Basic URL validation"""
    if not url or not isinstance(url, str):
        return False
    
    url = url.strip()
    
    # Basic URL patterns
    valid_patterns = [
        'youtube.com/watch',
        'youtu.be/',
        'm.youtube.com/watch',
        'youtube.com/shorts/',
        'youtube.com/embed/'
    ]
    
    return any(pattern in url.lower() for pattern in valid_patterns)

def get_safe_ydl_opts(quality, download_id):
    """Safe yt-dlp options for Render"""
    timestamp = int(time.time())
    output_path = os.path.join(TEMP_DIR, f'download_{download_id}_{timestamp}.%(ext)s')
    
    # Very conservative options
    opts = {
        'outtmpl': output_path,
        'format': 'best[height<=720][filesize<400M]/best[height<=480]',  # Conservative format
        'merge_output_format': 'mp4',
        'concurrent_fragment_downloads': 1,  # Single thread
        'retries': 1,
        'fragment_retries': 1,
        'socket_timeout': 30,
        'keep_fragments': False,
        'writeinfojson': False,
        'writesubtitles': False,
        'writethumbnail': False,
        'quiet': False,  # Keep logs for debugging
        'no_warnings': False,
        'progress_hooks': [SimpleProgressHook(download_id)],
        'http_headers': {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
        }
    }
    
    # Quality-specific adjustments
    if quality == 'audio':
        opts['format'] = 'bestaudio[abr<=128]/bestaudio'
        opts['postprocessors'] = [{
            'key': 'FFmpegExtractAudio',
            'preferredcodec': 'mp3',
            'preferredquality': '128'
        }]
    elif quality == '480p':
        opts['format'] = 'best[height<=480][filesize<200M]'
    elif quality == '720p':
        opts['format'] = 'best[height<=720][filesize<400M]'
    
    return opts

def extract_video_info(url):
    """Extract video information safely"""
    try:
        ydl_opts = {
            'quiet': False,
            'no_warnings': False,
            'skip_download': True,
            'socket_timeout': 20,
            'extractor_args': {
                'youtube': {
                    'player_client': ['web']
                }
            }
        }
        
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=False)
            
        return {
            'title': (info.get('title', '') or 'Unknown Title')[:80],
            'duration': info.get('duration', 0),
            'uploader': (info.get('uploader', '') or 'Unknown')[:50],
            'view_count': info.get('view_count', 0),
            'thumbnail': info.get('thumbnail', ''),
            'id': info.get('id', ''),
            'description': (info.get('description', '') or '')[:200],
            'available_qualities': ['720p', '480p', '360p', 'audio']
        }
        
    except Exception as e:
        logger.error(f"Info extraction error: {e}")
        raise Exception(f"Failed to extract video info: {str(e)[:100]}")

def perform_download(url, quality, download_id):
    """Perform the actual download"""
    try:
        logger.info(f"Starting download {download_id} for URL: {url[:50]}...")
        
        # Initialize status
        download_status[download_id] = {
            'status': 'starting',
            'progress': 0,
            'start_time': time.time(),
            'message': 'Initializing download...',
            'quality': quality
        }
        
        # Get download options
        opts = get_safe_ydl_opts(quality, download_id)
        
        # Update status
        download_status[download_id]['status'] = 'downloading'
        download_status[download_id]['message'] = 'Downloading video...'
        
        # Perform download
        with yt_dlp.YoutubeDL(opts) as ydl:
            ydl.download([url])
        
        # Find downloaded file
        prefix = f'download_{download_id}_'
        downloaded_file = None
        
        for filename in os.listdir(TEMP_DIR):
            if filename.startswith(prefix) and not filename.endswith(('.part', '.info.json')):
                downloaded_file = os.path.join(TEMP_DIR, filename)
                break
        
        if not downloaded_file or not os.path.exists(downloaded_file):
            raise Exception("Download completed but file not found")
        
        # Check file size
        file_size = os.path.getsize(downloaded_file)
        if file_size > MAX_FILE_SIZE:
            os.remove(downloaded_file)
            raise Exception(f'File too large: {file_size / (1024**2):.1f}MB')
        
        # Success
        end_time = time.time()
        download_time = end_time - download_status[download_id]['start_time']
        
        download_status[download_id].update({
            'status': 'completed',
            'progress': 100,
            'message': 'Download completed successfully!',
            'file_path': downloaded_file,
            'file_size': file_size,
            'filename': os.path.basename(downloaded_file),
            'download_time': round(download_time, 2),
            'completion_time': end_time
        })
        
        performance_metrics['successful_downloads'] += 1
        logger.info(f"Download {download_id} completed successfully")
        
        return downloaded_file
        
    except Exception as e:
        error_msg = str(e)[:200]
        logger.error(f"Download {download_id} failed: {error_msg}")
        
        download_status[download_id] = {
            'status': 'error',
            'message': error_msg,
            'error_time': time.time(),
            'progress': 0
        }
        
        performance_metrics['errors'] += 1
        raise

def cleanup_files():
    """Clean up old files"""
    try:
        current_time = time.time()
        cleaned = 0
        
        if os.path.exists(TEMP_DIR):
            for filename in os.listdir(TEMP_DIR):
                if filename.startswith('download_'):
                    file_path = os.path.join(TEMP_DIR, filename)
                    try:
                        if current_time - os.path.getctime(file_path) > FILE_RETENTION_TIME:
                            os.remove(file_path)
                            cleaned += 1
                    except Exception:
                        pass
        
        # Clean old download status
        expired_downloads = []
        for download_id, status in download_status.items():
            if current_time - status.get('start_time', current_time) > FILE_RETENTION_TIME:
                expired_downloads.append(download_id)
        
        for download_id in expired_downloads:
            download_status.pop(download_id, None)
            active_downloads.pop(download_id, None)
        
        if cleaned > 0:
            logger.info(f"Cleaned up {cleaned} files")
            gc.collect()
            
    except Exception as e:
        logger.error(f"Cleanup error: {e}")

def start_cleanup_thread():
    """Start background cleanup"""
    def cleanup_worker():
        while True:
            try:
                cleanup_files()
                time.sleep(600)  # Every 10 minutes
            except Exception as e:
                logger.error(f"Cleanup thread error: {e}")
                time.sleep(300)
    
    cleanup_thread = threading.Thread(target=cleanup_worker, daemon=True)
    cleanup_thread.start()
    logger.info("Cleanup thread started")

# API Routes
@app.route('/')
def index():
    uptime = time.time() - performance_metrics['start_time']
    return safe_json_response({
        'name': 'YouTube Downloader - Render Edition',
        'version': '1.0.1',
        'status': 'operational',
        'uptime_minutes': round(uptime / 60, 1),
        'stats': {
            'total_requests': performance_metrics['total_requests'],
            'successful_downloads': performance_metrics['successful_downloads'],
            'errors': performance_metrics['errors'],
            'active_downloads': len([s for s in download_status.values() 
                                   if s.get('status') == 'downloading']),
            'max_concurrent': MAX_CONCURRENT_DOWNLOADS
        },
        'supported_qualities': ['720p', '480p', '360p', 'audio']
    })

@app.route('/api/health')
def health():
    return safe_json_response({
        'status': 'healthy',
        'timestamp': int(time.time()),
        'active_downloads': len(active_downloads),
        'total_files': len([f for f in os.listdir(TEMP_DIR) if f.startswith('download_')]),
        'memory_usage': f"{len(download_status)} statuses"
    })

@app.route('/api/info', methods=['POST', 'OPTIONS'])
def get_info():
    if request.method == 'OPTIONS':
        return '', 200
        
    performance_metrics['total_requests'] += 1
    start_time = time.time()
    
    try:
        # Parse request data
        try:
            if request.is_json:
                data = request.get_json()
            else:
                data = request.form.to_dict()
        except Exception as e:
            logger.error(f"Request parsing error: {e}")
            return safe_json_response({
                'success': False, 
                'error': 'Invalid request format'
            }, 400)
        
        if not data:
            return safe_json_response({
                'success': False, 
                'error': 'No data provided'
            }, 400)
        
        url = data.get('url')
        if not url:
            return safe_json_response({
                'success': False, 
                'error': 'URL is required'
            }, 400)
        
        url = str(url).strip()
        
        # Validate URL
        if not validate_url(url):
            return safe_json_response({
                'success': False, 
                'error': 'Invalid YouTube URL'
            }, 400)
        
        # Check cache
        cache_key = hashlib.md5(url.encode()).hexdigest()[:12]
        if cache_key in simple_cache:
            cached_data, cache_time = simple_cache[cache_key]
            if time.time() - cache_time < CACHE_DURATION:
                return safe_json_response({
                    'success': True,
                    'data': cached_data,
                    'cached': True,
                    'response_time_ms': round((time.time() - start_time) * 1000, 1)
                })
        
        # Extract info
        info = extract_video_info(url)
        
        # Cache the result
        simple_cache[cache_key] = (info, time.time())
        
        # Limit cache size
        if len(simple_cache) > 100:
            oldest_key = min(simple_cache.keys(), 
                           key=lambda k: simple_cache[k][1])
            del simple_cache[oldest_key]
        
        return safe_json_response({
            'success': True,
            'data': info,
            'cached': False,
            'response_time_ms': round((time.time() - start_time) * 1000, 1)
        })
        
    except Exception as e:
        logger.error(f"Info extraction error: {e}\n{traceback.format_exc()}")
        performance_metrics['errors'] += 1
        return safe_json_response({
            'success': False,
            'error': str(e)[:150],
            'response_time_ms': round((time.time() - start_time) * 1000, 1)
        }, 400)

@app.route('/api/download', methods=['POST', 'OPTIONS'])
def start_download():
    if request.method == 'OPTIONS':
        return '', 200
        
    try:
        # Parse request
        try:
            if request.is_json:
                data = request.get_json()
            else:
                data = request.form.to_dict()
        except Exception:
            return safe_json_response({
                'success': False, 
                'error': 'Invalid request format'
            }, 400)
        
        if not data:
            return safe_json_response({
                'success': False, 
                'error': 'No data provided'
            }, 400)
        
        url = data.get('url')
        if not url:
            return safe_json_response({
                'success': False, 
                'error': 'URL is required'
            }, 400)
        
        url = str(url).strip()
        quality = data.get('quality', '720p')
        
        # Validate inputs
        if not validate_url(url):
            return safe_json_response({
                'success': False, 
                'error': 'Invalid YouTube URL'
            }, 400)
        
        if quality not in ['720p', '480p', '360p', 'audio']:
            quality = '720p'
        
        # Check capacity
        active_count = len([s for s in download_status.values() 
                          if s.get('status') in ['downloading', 'starting']])
        if active_count >= MAX_CONCURRENT_DOWNLOADS:
            return safe_json_response({
                'success': False, 
                'error': f'Server busy. Active downloads: {active_count}',
                'retry_after': 60
            }, 429)
        
        # Generate download ID
        download_id = f"dl_{int(time.time() * 1000)}"
        
        # Start download in background
        def download_worker():
            try:
                perform_download(url, quality, download_id)
            except Exception as e:
                logger.error(f"Download worker error: {e}")
        
        thread = threading.Thread(target=download_worker, daemon=True)
        thread.start()
        active_downloads[download_id] = thread
        
        return safe_json_response({
            'success': True,
            'download_id': download_id,
            'message': 'Download started',
            'quality': quality,
            'estimated_time': '1-5 minutes'
        })
        
    except Exception as e:
        logger.error(f"Start download error: {e}\n{traceback.format_exc()}")
        return safe_json_response({
            'success': False,
            'error': str(e)[:150]
        }, 400)

@app.route('/api/status/<download_id>')
def get_status(download_id):
    try:
        if download_id not in download_status:
            return safe_json_response({
                'success': False, 
                'error': 'Download not found'
            }, 404)
        
        status = download_status[download_id].copy()
        
        # Add computed fields
        if 'start_time' in status:
            elapsed = time.time() - status['start_time']
            status['elapsed_seconds'] = round(elapsed, 1)
            
            # Calculate ETA
            if status.get('progress', 0) > 5 and elapsed > 10:
                estimated_total = elapsed / (status['progress'] / 100)
                status['eta_seconds'] = round(max(0, estimated_total - elapsed), 1)
        
        # Remove sensitive data
        status.pop('file_path', None)
        
        # Format file size
        if 'file_size' in status:
            status['file_size_mb'] = round(status['file_size'] / (1024**2), 2)
        
        return safe_json_response({
            'success': True,
            'status': status
        })
        
    except Exception as e:
        logger.error(f"Status check error: {e}")
        return safe_json_response({
            'success': False,
            'error': 'Status check failed'
        }, 500)

@app.route('/api/file/<download_id>')
def download_file(download_id):
    try:
        if download_id not in download_status:
            return safe_json_response({'error': 'Download not found'}, 404)
        
        status = download_status[download_id]
        if status.get('status') != 'completed':
            return safe_json_response({
                'error': f'Download not ready. Status: {status.get("status", "unknown")}'
            }, 400)
        
        file_path = status.get('file_path')
        if not file_path or not os.path.exists(file_path):
            return safe_json_response({'error': 'File not available'}, 404)
        
        filename = status.get('filename', f'video_{download_id}.mp4')
        
        return send_file(
            file_path,
            as_attachment=True,
            download_name=filename,
            mimetype='application/octet-stream'
        )
        
    except Exception as e:
        logger.error(f"File download error: {e}")
        return safe_json_response({'error': 'File download failed'}, 500)

# Error handlers
@app.errorhandler(404)
def not_found(e):
    return safe_json_response({'error': 'Endpoint not found'}, 404)

@app.errorhandler(405)
def method_not_allowed(e):
    return safe_json_response({'error': 'Method not allowed'}, 405)

@app.errorhandler(500)
def internal_error(e):
    logger.error(f"Internal server error: {e}")
    return safe_json_response({'error': 'Internal server error'}, 500)

@app.before_request
def log_request():
    logger.info(f"{request.method} {request.path} - {request.remote_addr}")

@app.after_request
def after_request(response):
    response.headers['Access-Control-Allow-Origin'] = '*'
    response.headers['Access-Control-Allow-Methods'] = 'GET, POST, OPTIONS'
    response.headers['Access-Control-Allow-Headers'] = 'Content-Type, Accept, Authorization'
    return response

if __name__ == '__main__':
    # Start cleanup thread
    start_cleanup_thread()
    
    port = int(os.environ.get('PORT', 5000))
    
    logger.info(f"""
🚀 YouTube Downloader Starting...
Port: {port}
Max Downloads: {MAX_CONCURRENT_DOWNLOADS}
Temp Dir: {TEMP_DIR}
    """)
    
    app.run(
        host='0.0.0.0',
        port=port,
        debug=False,
        threaded=True
    )