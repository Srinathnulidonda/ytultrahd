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
import random

app = Flask(__name__)
CORS(app, origins=["*"], allow_headers=["Content-Type"], methods=["GET", "POST", "OPTIONS"])

# Store download progress
download_progress = {}

# User agents to rotate
USER_AGENTS = [
    'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
    'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/119.0.0.0 Safari/537.36',
    'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
    'Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
    'Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:120.0) Gecko/20100101 Firefox/120.0',
    'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.1 Safari/605.1.15'
]

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

def get_base_ydl_opts():
    """Get base yt-dlp options with anti-bot measures"""
    opts = {
        'quiet': True,
        'no_warnings': True,
        'no_color': True,
        'user_agent': random.choice(USER_AGENTS),
        'referer': 'https://www.youtube.com/',
        'http_headers': {
            'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8',
            'Accept-Language': 'en-US,en;q=0.5',
            'Accept-Encoding': 'gzip, deflate, br',
            'DNT': '1',
            'Connection': 'keep-alive',
            'Upgrade-Insecure-Requests': '1',
            'Sec-Fetch-Dest': 'document',
            'Sec-Fetch-Mode': 'navigate',
            'Sec-Fetch-Site': 'none',
            'Sec-Fetch-User': '?1',
            'Cache-Control': 'max-age=0'
        },
        'sleep_interval': 1,
        'max_sleep_interval': 3,
        'sleep_interval_requests': 1,
        'sleep_interval_subtitles': 1,
        'retries': 5,
        'fragment_retries': 5,
        'skip_unavailable_fragments': True,
        'ignoreerrors': False,
        'abort_on_unavailable_fragments': False,
        'keep_fragments': False,
        'concurrent_fragment_downloads': 1,
        'buffersize': 1024,
        'http_chunk_size': 10485760,
        'throttledratelimit': 100000,  # 100 KB/s minimum
        'ratelimit': 10000000,  # 10 MB/s maximum
        'extractor_args': {
            'youtube': {
                'player_client': ['android', 'web'],
                'player_skip': ['webpage', 'configs', 'js'],
                'skip': ['hls', 'dash', 'translated_subs'],
                'max_comments': 0,
                'max_comment_depth': 0
            }
        },
        'postprocessor_args': {
            'ffmpeg': ['-loglevel', 'error', '-hide_banner']
        }
    }
    
    # Check if cookies file exists
    if os.path.exists('cookies.txt'):
        opts['cookiefile'] = 'cookies.txt'
    else:
        # Try to use cookies from browser
        try:
            # Try Chrome first
            opts['cookiesfrombrowser'] = ('chrome',)
        except:
            try:
                # Fall back to Firefox
                opts['cookiesfrombrowser'] = ('firefox',)
            except:
                # If all fails, try Edge
                try:
                    opts['cookiesfrombrowser'] = ('edge',)
                except:
                    pass
    
    return opts

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
        
        # Add small random delay to avoid detection
        time.sleep(random.uniform(0.5, 1.5))
        
        ydl_opts = get_base_ydl_opts()
        ydl_opts.update({
            'extract_flat': False,
            'skip_download': True,
            'getcomments': False,
            'writesubtitles': False,
            'writeautomaticsub': False,
            'subtitleslangs': [],
        })
        
        try:
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                info = ydl.extract_info(url, download=False)
                
                # Extract available formats
                formats = []
                audio_formats = []
                
                for f in info.get('formats', []):
                    if f.get('format_note') == 'storyboard':
                        continue
                        
                    if f.get('vcodec') != 'none' and f.get('acodec') == 'none':
                        # Video only format
                        height = f.get('height', 0)
                        if height >= 720:  # Show 720p and above
                            formats.append({
                                'format_id': f['format_id'],
                                'resolution': f"{height}p",
                                'height': height,
                                'fps': f.get('fps', 30),
                                'filesize': f.get('filesize', 0),
                                'filesize_approx': f.get('filesize_approx', 0),
                                'vcodec': f.get('vcodec', 'unknown'),
                                'ext': f.get('ext', 'mp4'),
                                'format_note': f.get('format_note', '')
                            })
                    elif f.get('acodec') != 'none' and f.get('vcodec') == 'none':
                        # Audio only format
                        audio_formats.append({
                            'format_id': f['format_id'],
                            'abr': f.get('abr', 0),
                            'asr': f.get('asr', 44100),
                            'acodec': f.get('acodec', 'unknown'),
                            'filesize': f.get('filesize', 0),
                            'filesize_approx': f.get('filesize_approx', 0),
                            'ext': f.get('ext', 'webm'),
                            'format_note': f.get('format_note', '')
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
                    'upload_date': info.get('upload_date', ''),
                    'description': info.get('description', '')[:500],  # Limit description length
                    'video_formats': formats[:10],  # Limit to top 10
                    'audio_formats': audio_formats[:5],  # Limit to top 5
                    'best_video': best_video,
                    'best_audio': best_audio,
                    'video_id': extract_video_id(url),
                    'webpage_url': info.get('webpage_url', url)
                })
        except yt_dlp.utils.ExtractorError as e:
            error_msg = str(e)
            if 'Sign in to confirm' in error_msg:
                return jsonify({
                    'error': 'YouTube requires authentication. Please try again later or use a different video.',
                    'details': 'Bot detection triggered. Consider using cookies or waiting before retrying.'
                }), 403
            return jsonify({'error': error_msg}), 400
            
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
        thread.daemon = True
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
        # Add random delay
        time.sleep(random.uniform(1, 2))
        
        def progress_hook(d):
            progress_tracker.update(d)
        
        # Build format string based on quality selection
        if quality == 'best':
            format_string = 'bestvideo[ext=mp4]+bestaudio[ext=m4a]/best[ext=mp4]/best'
        elif quality == '8k':
            format_string = 'bestvideo[height<=4320][ext=mp4]+bestaudio[ext=m4a]/bestvideo[height<=4320]+bestaudio/best'
        elif quality == '4k':
            format_string = 'bestvideo[height<=2160][ext=mp4]+bestaudio[ext=m4a]/bestvideo[height<=2160]+bestaudio/best'
        elif quality == '2k':
            format_string = 'bestvideo[height<=1440][ext=mp4]+bestaudio[ext=m4a]/bestvideo[height<=1440]+bestaudio/best'
        elif quality == '1080p':
            format_string = 'bestvideo[height<=1080][ext=mp4]+bestaudio[ext=m4a]/bestvideo[height<=1080]+bestaudio/best'
        elif quality == '720p':
            format_string = 'bestvideo[height<=720][ext=mp4]+bestaudio[ext=m4a]/bestvideo[height<=720]+bestaudio/best'
        else:
            # Custom format selection
            format_string = f'{quality}+{audio_quality}'
        
        output_template = os.path.join(temp_dir, '%(title).200B.%(ext)s')
        
        ydl_opts = get_base_ydl_opts()
        ydl_opts.update({
            'format': format_string,
            'outtmpl': output_template,
            'progress_hooks': [progress_hook],
            'merge_output_format': 'mp4',
            'postprocessors': [{
                'key': 'FFmpegVideoConvertor',
                'preferedformat': 'mp4',
            }],
            'prefer_ffmpeg': True,
            'keepvideo': False,
            'writeinfojson': False,
            'writethumbnail': False,
            'writesubtitles': False,
            'writeautomaticsub': False,
            'subtitleslangs': [],
            'matchtitle': None,
            'rejecttitle': None,
            'logger': None,
            'logtostderr': False,
            'consoletitle': False,
            'nopart': False,
            'updatetime': False,
            'writedescription': False,
            'writeannotations': False,
            'writecomments': False,
            'getcomments': False,
        })
        
        try:
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                info = ydl.extract_info(url, download=True)
                progress_tracker.title = info.get('title', 'Unknown')
                progress_tracker.thumbnail = info.get('thumbnail', '')
                
                # Find the downloaded file
                for file in os.listdir(temp_dir):
                    if file.endswith(('.mp4', '.webm', '.mkv', '.mov', '.avi')):
                        progress_tracker.file_path = os.path.join(temp_dir, file)
                        progress_tracker.filename = file
                        break
                
                if not progress_tracker.file_path:
                    raise Exception("Downloaded file not found")
                    
                progress_tracker.status = 'completed'
                
        except yt_dlp.utils.ExtractorError as e:
            error_msg = str(e)
            if 'Sign in to confirm' in error_msg:
                progress_tracker.error = 'YouTube requires authentication. Please try again later.'
            else:
                progress_tracker.error = error_msg
            progress_tracker.status = 'error'
            
    except Exception as e:
        progress_tracker.status = 'error'
        progress_tracker.error = str(e)
    finally:
        # Clean up on error
        if progress_tracker.status == 'error' and os.path.exists(temp_dir):
            try:
                shutil.rmtree(temp_dir)
            except:
                pass

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
                try:
                    shutil.rmtree(temp_dir)
                except:
                    pass
            
            # Remove from progress tracking
            if download_id in download_progress:
                del download_progress[download_id]
        
        response = Response(generate(), mimetype='video/mp4')
        response.headers['Content-Disposition'] = f'attachment; filename="{progress.filename}"'
        response.headers['Content-Type'] = 'video/mp4'
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
            {'id': '720p', 'label': '720p', 'description': 'HD'},
        ],
        'audio_qualities': [
            {'id': 'best', 'label': 'Best Audio', 'description': 'Highest quality audio'},
            {'id': '320k', 'label': '320 kbps', 'description': 'High quality MP3'},
            {'id': '256k', 'label': '256 kbps', 'description': 'Standard quality'},
            {'id': '128k', 'label': '128 kbps', 'description': 'Lower quality'},
        ]
    })

@app.route('/api/cleanup', methods=['POST'])
def cleanup_old_downloads():
    """Clean up old downloads and temporary files"""
    try:
        # Remove completed downloads older than 1 hour
        current_time = time.time()
        to_remove = []
        
        for download_id, progress in download_progress.items():
            if progress.status == 'completed' and progress.file_path:
                file_age = current_time - os.path.getmtime(progress.file_path)
                if file_age > 3600:  # 1 hour
                    to_remove.append(download_id)
                    temp_dir = os.path.dirname(progress.file_path)
                    if os.path.exists(temp_dir):
                        shutil.rmtree(temp_dir)
        
        for download_id in to_remove:
            del download_progress[download_id]
        
        return jsonify({
            'status': 'ok',
            'cleaned': len(to_remove)
        })
        
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.errorhandler(404)
def not_found(e):
    return jsonify({'error': 'Endpoint not found'}), 404

@app.errorhandler(500)
def server_error(e):
    return jsonify({'error': 'Internal server error'}), 500

# Cleanup thread
def periodic_cleanup():
    while True:
        time.sleep(3600)  # Run every hour
        try:
            current_time = time.time()
            to_remove = []
            
            for download_id, progress in list(download_progress.items()):
                if progress.status in ['completed', 'error'] and hasattr(progress, 'file_path'):
                    if progress.file_path and os.path.exists(progress.file_path):
                        file_age = current_time - os.path.getmtime(progress.file_path)
                        if file_age > 3600:  # 1 hour
                            to_remove.append(download_id)
                            temp_dir = os.path.dirname(progress.file_path)
                            if os.path.exists(temp_dir):
                                try:
                                    shutil.rmtree(temp_dir)
                                except:
                                    pass
            
            for download_id in to_remove:
                if download_id in download_progress:
                    del download_progress[download_id]
        except:
            pass

# Start cleanup thread
cleanup_thread = threading.Thread(target=periodic_cleanup)
cleanup_thread.daemon = True
cleanup_thread.start()

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port, debug=False)