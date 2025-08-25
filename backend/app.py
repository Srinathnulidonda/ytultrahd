import os
import json
import time
import tempfile
import subprocess
import threading
from datetime import datetime, timedelta
from flask import Flask, request, jsonify, send_file, render_template_string
from flask_cors import CORS
from werkzeug.utils import secure_filename
import yt_dlp
import logging

app = Flask(__name__)
CORS(app)

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Configuration
TEMP_DIR = tempfile.gettempdir()
MAX_FILE_SIZE = 2 * 1024 * 1024 * 1024  # 2GB limit for Render
CLEANUP_INTERVAL = 3600  # 1 hour
FILE_RETENTION_TIME = 7200  # 2 hours

# Global variables for tracking downloads
download_status = {}
file_cleanup_thread = None

class ProgressHook:
    def __init__(self, download_id):
        self.download_id = download_id
        
    def __call__(self, d):
        if d['status'] == 'downloading':
            total_bytes = d.get('total_bytes', 0) or d.get('total_bytes_estimate', 0)
            downloaded_bytes = d.get('downloaded_bytes', 0)
            
            if total_bytes > 0:
                percentage = (downloaded_bytes / total_bytes) * 100
            else:
                percentage = 0
                
            speed = d.get('speed', 0) or 0
            eta = d.get('eta', 0) or 0
            
            download_status[self.download_id].update({
                'status': 'downloading',
                'progress': round(percentage, 1),
                'downloaded_bytes': downloaded_bytes,
                'total_bytes': total_bytes,
                'speed': speed,
                'eta': eta,
                'filename': d.get('filename', ''),
            })
            
        elif d['status'] == 'finished':
            download_status[self.download_id].update({
                'status': 'processing',
                'progress': 100,
                'message': 'Processing and merging files...'
            })

def cleanup_old_files():
    """Clean up old downloaded files"""
    try:
        current_time = time.time()
        for root, dirs, files in os.walk(TEMP_DIR):
            for file in files:
                if file.startswith('yt_download_'):
                    file_path = os.path.join(root, file)
                    if os.path.exists(file_path):
                        file_age = current_time - os.path.getctime(file_path)
                        if file_age > FILE_RETENTION_TIME:
                            try:
                                os.remove(file_path)
                                logger.info(f"Cleaned up old file: {file_path}")
                            except Exception as e:
                                logger.error(f"Error cleaning up file {file_path}: {e}")
    except Exception as e:
        logger.error(f"Error in cleanup_old_files: {e}")

def start_cleanup_thread():
    """Start the file cleanup thread"""
    def cleanup_worker():
        while True:
            cleanup_old_files()
            time.sleep(CLEANUP_INTERVAL)
    
    global file_cleanup_thread
    if file_cleanup_thread is None or not file_cleanup_thread.is_alive():
        file_cleanup_thread = threading.Thread(target=cleanup_worker, daemon=True)
        file_cleanup_thread.start()

def get_video_info(url):
    """Extract video information without downloading"""
    ydl_opts = {
        'quiet': True,
        'no_warnings': True,
        'extract_flat': False,
    }
    
    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=False)
            
            # Get available formats
            formats = []
            if 'formats' in info:
                for f in info['formats']:
                    if f.get('vcodec') != 'none' or f.get('acodec') != 'none':
                        format_info = {
                            'format_id': f.get('format_id', ''),
                            'ext': f.get('ext', ''),
                            'resolution': f.get('resolution', 'audio only'),
                            'fps': f.get('fps', 0),
                            'vcodec': f.get('vcodec', 'none'),
                            'acodec': f.get('acodec', 'none'),
                            'filesize': f.get('filesize', 0),
                            'quality': f.get('quality', 0),
                            'height': f.get('height', 0),
                            'width': f.get('width', 0),
                        }
                        formats.append(format_info)
            
            return {
                'title': info.get('title', 'Unknown'),
                'duration': info.get('duration', 0),
                'uploader': info.get('uploader', 'Unknown'),
                'view_count': info.get('view_count', 0),
                'upload_date': info.get('upload_date', ''),
                'description': info.get('description', '')[:500] + '...' if info.get('description') else '',
                'thumbnail': info.get('thumbnail', ''),
                'formats': formats,
                'webpage_url': info.get('webpage_url', url)
            }
    except Exception as e:
        logger.error(f"Error extracting video info: {e}")
        raise

def download_video(url, quality='best', download_id=None):
    """Download video with specified quality"""
    if download_id is None:
        download_id = str(int(time.time()))
    
    # Initialize download status
    download_status[download_id] = {
        'status': 'starting',
        'progress': 0,
        'message': 'Initializing download...',
        'start_time': time.time()
    }
    
    try:
        # Create unique filename
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        output_template = os.path.join(TEMP_DIR, f'yt_download_{download_id}_{timestamp}.%(ext)s')
        
        # Configure yt-dlp options based on quality
        ydl_opts = {
            'outtmpl': output_template,
            'progress_hooks': [ProgressHook(download_id)],
            'merge_output_format': 'mp4',
            'writeinfojson': True,
            'writesubtitles': False,
            'writeautomaticsub': False,
            'ignoreerrors': False,
        }
        
        # Quality selection
        if quality == 'best':
            ydl_opts['format'] = 'bestvideo[height<=2160]+bestaudio/best'
        elif quality == '4k':
            ydl_opts['format'] = 'bestvideo[height<=2160]+bestaudio/bestvideo[height<=1440]+bestaudio/best'
        elif quality == '1080p':
            ydl_opts['format'] = 'bestvideo[height<=1080]+bestaudio/best'
        elif quality == '720p':
            ydl_opts['format'] = 'bestvideo[height<=720]+bestaudio/best'
        elif quality == '480p':
            ydl_opts['format'] = 'bestvideo[height<=480]+bestaudio/best'
        elif quality == 'audio':
            ydl_opts['format'] = 'bestaudio/best'
            ydl_opts['postprocessors'] = [{
                'key': 'FFmpegExtractAudio',
                'preferredcodec': 'mp3',
                'preferredquality': '320',
            }]
        else:
            ydl_opts['format'] = quality
        
        download_status[download_id]['status'] = 'downloading'
        download_status[download_id]['message'] = 'Starting download...'
        
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            ydl.download([url])
        
        # Find the downloaded file
        downloaded_files = []
        for file in os.listdir(TEMP_DIR):
            if file.startswith(f'yt_download_{download_id}_{timestamp}') and not file.endswith('.info.json'):
                downloaded_files.append(os.path.join(TEMP_DIR, file))
        
        if downloaded_files:
            file_path = downloaded_files[0]
            file_size = os.path.getsize(file_path)
            
            # Check file size limit
            if file_size > MAX_FILE_SIZE:
                os.remove(file_path)
                download_status[download_id] = {
                    'status': 'error',
                    'message': f'File too large ({file_size / (1024*1024):.1f}MB). Maximum allowed: {MAX_FILE_SIZE / (1024*1024):.1f}MB'
                }
                return None
            
            download_status[download_id] = {
                'status': 'completed',
                'progress': 100,
                'message': 'Download completed successfully!',
                'file_path': file_path,
                'file_size': file_size,
                'filename': os.path.basename(file_path)
            }
            
            return file_path
        else:
            download_status[download_id] = {
                'status': 'error',
                'message': 'Download completed but file not found'
            }
            return None
            
    except Exception as e:
        logger.error(f"Download error for {download_id}: {e}")
        download_status[download_id] = {
            'status': 'error',
            'message': f'Download failed: {str(e)}'
        }
        return None

@app.route('/')
def index():
    return jsonify({
        'message': 'YouTube Video Downloader API',
        'version': '1.0',
        'endpoints': {
            'info': '/api/info',
            'download': '/api/download',
            'status': '/api/status/<download_id>',
            'file': '/api/file/<download_id>'
        }
    })

@app.route('/api/info', methods=['POST'])
def get_info():
    """Get video information"""
    try:
        data = request.get_json()
        if not data or 'url' not in data:
            return jsonify({'error': 'URL is required'}), 400
        
        url = data['url']
        info = get_video_info(url)
        
        return jsonify({
            'success': True,
            'data': info
        })
        
    except Exception as e:
        logger.error(f"Info extraction error: {e}")
        return jsonify({
            'success': False,
            'error': str(e)
        }), 400

@app.route('/api/download', methods=['POST'])
def start_download():
    """Start video download"""
    try:
        data = request.get_json()
        if not data or 'url' not in data:
            return jsonify({'error': 'URL is required'}), 400
        
        url = data['url']
        quality = data.get('quality', 'best')
        download_id = str(int(time.time() * 1000))  # More unique ID
        
        # Start download in background thread
        def download_thread():
            download_video(url, quality, download_id)
        
        thread = threading.Thread(target=download_thread)
        thread.daemon = True
        thread.start()
        
        return jsonify({
            'success': True,
            'download_id': download_id,
            'message': 'Download started'
        })
        
    except Exception as e:
        logger.error(f"Download start error: {e}")
        return jsonify({
            'success': False,
            'error': str(e)
        }), 400

@app.route('/api/status/<download_id>')
def get_download_status(download_id):
    """Get download status"""
    if download_id in download_status:
        status = download_status[download_id].copy()
        
        # Add time elapsed
        if 'start_time' in status:
            status['elapsed_time'] = int(time.time() - status['start_time'])
        
        # Remove sensitive information
        if 'file_path' in status:
            del status['file_path']
            
        return jsonify({
            'success': True,
            'status': status
        })
    else:
        return jsonify({
            'success': False,
            'error': 'Download ID not found'
        }), 404

@app.route('/api/file/<download_id>')
def download_file(download_id):
    """Download the completed file"""
    if download_id not in download_status:
        return jsonify({'error': 'Download ID not found'}), 404
    
    status = download_status[download_id]
    
    if status['status'] != 'completed':
        return jsonify({'error': 'Download not completed'}), 400
    
    if 'file_path' not in status or not os.path.exists(status['file_path']):
        return jsonify({'error': 'File not found'}), 404
    
    try:
        return send_file(
            status['file_path'],
            as_attachment=True,
            download_name=status['filename']
        )
    except Exception as e:
        logger.error(f"File download error: {e}")
        return jsonify({'error': 'File download failed'}), 500

@app.route('/api/cleanup', methods=['POST'])
def manual_cleanup():
    """Manual cleanup endpoint"""
    try:
        cleanup_old_files()
        return jsonify({
            'success': True,
            'message': 'Cleanup completed'
        })
    except Exception as e:
        return jsonify({
            'success': False,
            'error': str(e)
        }), 500

@app.errorhandler(404)
def not_found(error):
    return jsonify({'error': 'Endpoint not found'}), 404

@app.errorhandler(500)
def internal_error(error):
    return jsonify({'error': 'Internal server error'}), 500

if __name__ == '__main__':
    # Start cleanup thread
    start_cleanup_thread()
    
    # Run the app
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port, debug=False)