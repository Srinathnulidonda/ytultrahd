from flask import Flask, request, jsonify, send_file, Response
from flask_cors import CORS
import yt_dlp
import os
import json
import uuid
import threading
import time
from datetime import datetime
import tempfile
import shutil
from urllib.parse import urlparse, parse_qs
import re

app = Flask(__name__)
CORS(app, origins=["*"], allow_headers=["Content-Type"], methods=["GET", "POST", "OPTIONS"])

# Store download progress
download_progress = {}

class DownloadProgress:
    def __init__(self, download_id):
        self.download_id = download_id
        self.status = 'preparing'
        self.progress = 0
        self.speed = '0 B/s'
        self.eta = 'Unknown'
        self.size = '0 B'
        self.title = ''
        self.thumbnail = ''
        self.error = None
        self.file_path = None
        self.filename = ''

    def update(self, d):
        if d['status'] == 'downloading':
            self.status = 'downloading'
            self.progress = d.get('_percent_str', '0%').replace('%', '')
            self.speed = d.get('_speed_str', '0 B/s')
            self.eta = d.get('_eta_str', 'Unknown')
            self.size = d.get('_total_bytes_str', '0 B')
        elif d['status'] == 'finished':
            self.status = 'processing'
            self.progress = 100

def extract_video_id(url):
    """Extract video ID from YouTube URL"""
    patterns = [
        r'(?:youtube\.com\/watch\?v=|youtu\.be\/|youtube\.com\/embed\/)([^&\n?#]+)',
        r'youtube\.com\/shorts\/([^&\n?#]+)'
    ]
    
    for pattern in patterns:
        match = re.search(pattern, url)
        if match:
            return match.group(1)
    
    parsed = urlparse(url)
    if parsed.hostname in ('www.youtube.com', 'youtube.com', 'm.youtube.com'):
        query = parse_qs(parsed.query)
        if 'v' in query:
            return query['v'][0]
    
    return None

@app.route('/api/health', methods=['GET'])
def health_check():
    return jsonify({
        'status': 'ok',
        'timestamp': datetime.now().isoformat(),
        'service': 'YouTube Downloader API'
    })

@app.route('/api/info', methods=['POST'])
def get_video_info():
    try:
        data = request.get_json()
        url = data.get('url')
        
        if not url:
            return jsonify({'error': 'URL is required'}), 400
        
        ydl_opts = {
            'quiet': True,
            'no_warnings': True,
            'extract_flat': False,
            'skip_download': True,
        }
        
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=False)
            
            # Extract available formats
            formats = []
            audio_formats = []
            
            for f in info.get('formats', []):
                if f.get('vcodec') != 'none' and f.get('acodec') == 'none':
                    # Video only format
                    height = f.get('height', 0)
                    if height >= 1080:  # Only show HD and above
                        formats.append({
                            'format_id': f['format_id'],
                            'resolution': f"{height}p",
                            'height': height,
                            'fps': f.get('fps', 30),
                            'filesize': f.get('filesize', 0),
                            'filesize_approx': f.get('filesize_approx', 0),
                            'vcodec': f.get('vcodec', 'unknown'),
                            'ext': f.get('ext', 'mp4')
                        })
                elif f.get('acodec') != 'none' and f.get('vcodec') == 'none':
                    # Audio only format
                    audio_formats.append({
                        'format_id': f['format_id'],
                        'abr': f.get('abr', 0),
                        'acodec': f.get('acodec', 'unknown'),
                        'filesize': f.get('filesize', 0),
                        'filesize_approx': f.get('filesize_approx', 0),
                        'ext': f.get('ext', 'webm')
                    })
            
            # Sort formats by quality
            formats.sort(key=lambda x: x['height'], reverse=True)
            audio_formats.sort(key=lambda x: x['abr'], reverse=True)
            
            # Get best formats
            best_video = formats[0] if formats else None
            best_audio = audio_formats[0] if audio_formats else None
            
            return jsonify({
                'title': info.get('title', 'Unknown'),
                'thumbnail': info.get('thumbnail', ''),
                'duration': info.get('duration', 0),
                'uploader': info.get('uploader', 'Unknown'),
                'view_count': info.get('view_count', 0),
                'video_formats': formats[:10],  # Limit to top 10
                'audio_formats': audio_formats[:5],  # Limit to top 5
                'best_video': best_video,
                'best_audio': best_audio,
                'video_id': extract_video_id(url)
            })
            
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/api/download', methods=['POST'])
def download_video():
    try:
        data = request.get_json()
        url = data.get('url')
        quality = data.get('quality', 'best')
        audio_quality = data.get('audio_quality', 'best')
        
        if not url:
            return jsonify({'error': 'URL is required'}), 400
        
        download_id = str(uuid.uuid4())
        progress_tracker = DownloadProgress(download_id)
        download_progress[download_id] = progress_tracker
        
        # Start download in background
        thread = threading.Thread(
            target=perform_download,
            args=(url, quality, audio_quality, progress_tracker)
        )
        thread.start()
        
        return jsonify({
            'download_id': download_id,
            'status': 'started'
        })
        
    except Exception as e:
        return jsonify({'error': str(e)}), 500

def perform_download(url, quality, audio_quality, progress_tracker):
    temp_dir = tempfile.mkdtemp()
    
    try:
        def progress_hook(d):
            progress_tracker.update(d)
        
        # Build format string based on quality selection
        if quality == 'best':
            format_string = 'bestvideo[ext=mp4]+bestaudio[ext=m4a]/best[ext=mp4]/best'
        elif quality == '8k':
            format_string = 'bestvideo[height<=4320]+bestaudio/best'
        elif quality == '4k':
            format_string = 'bestvideo[height<=2160]+bestaudio/best'
        elif quality == '2k':
            format_string = 'bestvideo[height<=1440]+bestaudio/best'
        elif quality == '1080p':
            format_string = 'bestvideo[height<=1080]+bestaudio/best'
        else:
            # Custom format selection
            format_string = f'{quality}+{audio_quality}'
        
        output_template = os.path.join(temp_dir, '%(title).200B.%(ext)s')
        
        ydl_opts = {
            'format': format_string,
            'outtmpl': output_template,
            'progress_hooks': [progress_hook],
            'quiet': True,
            'no_warnings': True,
            'merge_output_format': 'mp4',
            'postprocessors': [{
                'key': 'FFmpegVideoConvertor',
                'preferedformat': 'mp4',
            }],
            'prefer_ffmpeg': True,
            'keepvideo': False,
            'http_chunk_size': 10485760,  # 10MB chunks
        }
        
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=True)
            progress_tracker.title = info.get('title', 'Unknown')
            progress_tracker.thumbnail = info.get('thumbnail', '')
            
            # Find the downloaded file
            for file in os.listdir(temp_dir):
                if file.endswith(('.mp4', '.webm', '.mkv')):
                    progress_tracker.file_path = os.path.join(temp_dir, file)
                    progress_tracker.filename = file
                    break
        
        progress_tracker.status = 'completed'
        
    except Exception as e:
        progress_tracker.status = 'error'
        progress_tracker.error = str(e)
        if os.path.exists(temp_dir):
            shutil.rmtree(temp_dir)

@app.route('/api/progress/<download_id>', methods=['GET'])
def get_progress(download_id):
    if download_id not in download_progress:
        return jsonify({'error': 'Download not found'}), 404
    
    progress = download_progress[download_id]
    
    return jsonify({
        'status': progress.status,
        'progress': progress.progress,
        'speed': progress.speed,
        'eta': progress.eta,
        'size': progress.size,
        'title': progress.title,
        'thumbnail': progress.thumbnail,
        'error': progress.error,
        'filename': progress.filename
    })

@app.route('/api/download/<download_id>/file', methods=['GET'])
def download_file(download_id):
    if download_id not in download_progress:
        return jsonify({'error': 'Download not found'}), 404
    
    progress = download_progress[download_id]
    
    if progress.status != 'completed' or not progress.file_path:
        return jsonify({'error': 'Download not completed'}), 400
    
    try:
        def generate():
            with open(progress.file_path, 'rb') as f:
                while True:
                    data = f.read(4096)
                    if not data:
                        break
                    yield data
            
            # Cleanup after sending
            temp_dir = os.path.dirname(progress.file_path)
            if os.path.exists(temp_dir) and temp_dir.startswith(tempfile.gettempdir()):
                shutil.rmtree(temp_dir)
            del download_progress[download_id]
        
        response = Response(generate(), mimetype='video/mp4')
        response.headers['Content-Disposition'] = f'attachment; filename="{progress.filename}"'
        return response
        
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/api/formats', methods=['GET'])
def get_supported_formats():
    return jsonify({
        'video_qualities': [
            {'id': 'best', 'label': 'Best Quality', 'description': 'Highest available quality'},
            {'id': '8k', 'label': '8K (4320p)', 'description': 'Ultra HD 8K'},
            {'id': '4k', 'label': '4K (2160p)', 'description': 'Ultra HD 4K'},
            {'id': '2k', 'label': '2K (1440p)', 'description': 'Quad HD'},
            {'id': '1080p', 'label': '1080p', 'description': 'Full HD'},
        ],
        'audio_qualities': [
            {'id': 'best', 'label': 'Best Audio', 'description': 'Highest quality audio'},
            {'id': '320k', 'label': '320 kbps', 'description': 'High quality MP3'},
            {'id': '256k', 'label': '256 kbps', 'description': 'Standard quality'},
            {'id': '128k', 'label': '128 kbps', 'description': 'Lower quality'},
        ]
    })

@app.errorhandler(404)
def not_found(e):
    return jsonify({'error': 'Endpoint not found'}), 404

@app.errorhandler(500)
def server_error(e):
    return jsonify({'error': 'Internal server error'}), 500

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port, debug=False)