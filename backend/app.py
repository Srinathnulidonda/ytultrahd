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
    'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.1 Safari/605.1.15',
    'Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.0 Mobile/15E148 Safari/604.1',
    'Mozilla/5.0 (iPad; CPU OS 17_0 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.0 Mobile/15E148 Safari/604.1'
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
    """Get base yt-dlp options with enhanced anti-bot measures"""
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
            'Cache-Control': 'max-age=0',
            'X-YouTube-Client-Name': '1',
            'X-YouTube-Client-Version': '2.20231213.04.00'
        },
        'sleep_interval': 3,
        'max_sleep_interval': 6,
        'sleep_interval_requests': 2,
        'sleep_interval_subtitles': 1,
        'retries': 15,
        'fragment_retries': 15,
        'skip_unavailable_fragments': True,
        'ignoreerrors': False,
        'abort_on_unavailable_fragments': False,
        'keep_fragments': False,
        'concurrent_fragment_downloads': 1,
        'buffersize': 1024,
        'http_chunk_size': 10485760,
        'extractor_args': {
            'youtube': {
                'player_client': ['ios', 'android', 'web', 'tv_embed', 'mediaconnect'],
                'player_skip': ['configs'],
                'skip': ['translated_subs'],
                'max_comments': 0,
                'max_comment_depth': 0,
                'innertube_host': 'youtubei.googleapis.com',
                'innertube_key': 'AIzaSyAO_FJ2SlqU8Q4STEHLGCilw_Y9_11qcW8'
            }
        },
        'postprocessor_args': {
            'ffmpeg': ['-loglevel', 'error', '-hide_banner']
        }
    }
    
    # Only use cookies file if it exists
    if os.path.exists('cookies.txt'):
        opts['cookiefile'] = 'cookies.txt'
    
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

@app.route('/', methods=['GET'])
def root():
    return jsonify({
        'service': 'YouTube Downloader API',
        'version': '1.0.0',
        'status': 'running',
        'endpoints': {
            'health': '/api/health',
            'info': '/api/info',
            'download': '/api/download',
            'formats': '/api/formats'
        }
    })

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
        
        # Add random delay to avoid detection
        time.sleep(random.uniform(2, 4))
        
        # Multiple extraction strategies with different configurations
        strategies = [
            # Strategy 1: iOS client (often works best)
            {
                'extractor_args': {
                    'youtube': {
                        'player_client': ['ios'],
                        'skip': ['webpage', 'configs'],
                        'player_skip': ['js', 'configs', 'webpage']
                    }
                }
            },
            # Strategy 2: Android client
            {
                'extractor_args': {
                    'youtube': {
                        'player_client': ['android'],
                        'skip': ['webpage'],
                        'player_skip': ['js', 'configs']
                    }
                }
            },
            # Strategy 3: TV Embed client
            {
                'extractor_args': {
                    'youtube': {
                        'player_client': ['tv_embed'],
                        'skip': ['webpage', 'configs']
                    }
                }
            },
            # Strategy 4: MediaConnect client
            {
                'extractor_args': {
                    'youtube': {
                        'player_client': ['mediaconnect'],
                        'skip': ['webpage']
                    }
                }
            },
            # Strategy 5: Web client with bypass
            {
                'extractor_args': {
                    'youtube': {
                        'player_client': ['web'],
                        'bypass_age_gate': True,
                        'skip': ['configs']
                    }
                }
            }
        ]
        
        last_error = None
        for i, strategy in enumerate(strategies):
            try:
                print(f"Trying strategy {i+1}/{len(strategies)}")
                
                ydl_opts = get_base_ydl_opts()
                ydl_opts.update({
                    'extract_flat': False,
                    'skip_download': True,
                    'getcomments': False,
                    'writesubtitles': False,
                    'writeautomaticsub': False,
                    'subtitleslangs': [],
                })
                ydl_opts.update(strategy)
                
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
                            if height >= 360:  # Show 360p and above
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
                        'description': info.get('description', '')[:500],
                        'video_formats': formats[:10],
                        'audio_formats': audio_formats[:5],
                        'best_video': best_video,
                        'best_audio': best_audio,
                        'video_id': extract_video_id(url),
                        'webpage_url': info.get('webpage_url', url),
                        'strategy_used': i + 1
                    })
                    
            except Exception as e:
                last_error = str(e)
                print(f"Strategy {i+1} failed: {last_error}")
                if i < len(strategies) - 1:
                    time.sleep(random.uniform(1, 3))  # Wait before trying next strategy
                continue
                
        # If all strategies failed
        if 'Sign in to confirm' in str(last_error) or 'bot' in str(last_error).lower():
            return jsonify({
                'error': 'YouTube has detected automated access. This video may be restricted.',
                'details': 'Try again later, use cookies.txt file, or try a different video.',
                'suggestions': [
                    'Create a cookies.txt file from your browser',
                    'Wait a few minutes before trying again',
                    'Try a different video URL',
                    'Check if the video is age-restricted or private'
                ]
            }), 403
        elif 'Failed to extract' in str(last_error):
            return jsonify({
                'error': 'Unable to extract video information from YouTube.',
                'details': 'YouTube may have updated their systems. Try updating yt-dlp or try again later.',
                'suggestions': [
                    'Update yt-dlp: pip install --upgrade yt-dlp',
                    'Try again in a few minutes',
                    'Check if the video URL is correct',
                    'Verify the video is publicly accessible'
                ]
            }), 503
        
        return jsonify({
            'error': 'Video extraction failed',
            'details': str(last_error),
            'suggestions': ['Try a different video URL', 'Check if video is publicly accessible']
        }), 400
            
    except Exception as e:
        return jsonify({
            'error': 'Server error during video extraction',
            'details': str(e)
        }), 500

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
        time.sleep(random.uniform(2, 5))
        
        def progress_hook(d):
            progress_tracker.update(d)
        
        # Build format string based on quality selection
        if quality == 'best':
            format_string = 'best[ext=mp4]/best'
        elif quality == '8k':
            format_string = 'bestvideo[height<=4320]+bestaudio/best'
        elif quality == '4k':
            format_string = 'bestvideo[height<=2160]+bestaudio/best'
        elif quality == '2k':
            format_string = 'bestvideo[height<=1440]+bestaudio/best'
        elif quality == '1080p':
            format_string = 'bestvideo[height<=1080]+bestaudio/best'
        elif quality == '720p':
            format_string = 'bestvideo[height<=720]+bestaudio/best'
        elif quality == '480p':
            format_string = 'bestvideo[height<=480]+bestaudio/best'
        elif quality == '360p':
            format_string = 'bestvideo[height<=360]+bestaudio/best'
        else:
            format_string = f'{quality}+{audio_quality}'
        
        output_template = os.path.join(temp_dir, '%(title).200B.%(ext)s')
        
        # Try the same strategies as info extraction
        strategies = [
            {'extractor_args': {'youtube': {'player_client': ['ios']}}},
            {'extractor_args': {'youtube': {'player_client': ['android']}}},
            {'extractor_args': {'youtube': {'player_client': ['tv_embed']}}},
            {'extractor_args': {'youtube': {'player_client': ['web']}}},
        ]
        
        for i, strategy in enumerate(strategies):
            try:
                print(f"Download strategy {i+1}/{len(strategies)}")
                
                ydl_opts = get_base_ydl_opts()
                ydl_opts.update({
                    'format': format_string,
                    'outtmpl': output_template,
                    'progress_hooks': [progress_hook],
                    'merge_output_format': 'mp4',
                    'prefer_ffmpeg': True,
                    'keepvideo': False,
                    'writeinfojson': False,
                    'writethumbnail': False,
                    'writesubtitles': False,
                    'writeautomaticsub': False,
                    'subtitleslangs': [],
                    'getcomments': False,
                })
                ydl_opts.update(strategy)
                
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
                    return  # Success
                    
            except Exception as e:
                print(f"Download strategy {i+1} failed: {str(e)}")
                if i < len(strategies) - 1:
                    time.sleep(random.uniform(1, 3))
                    continue
                else:
                    progress_tracker.error = f'All download strategies failed. Last error: {str(e)}'
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
            {'id': '480p', 'label': '480p', 'description': 'SD'},
            {'id': '360p', 'label': '360p', 'description': 'Low'},
        ],
        'audio_qualities': [
            {'id': 'best', 'label': 'Best Audio', 'description': 'Highest quality audio'},
            {'id': '320k', 'label': '320 kbps', 'description': 'High quality MP3'},
            {'id': '256k', 'label': '256 kbps', 'description': 'Standard quality'},
            {'id': '128k', 'label': '128 kbps', 'description': 'Lower quality'},
        ]
    })

@app.route('/api/test', methods=['GET'])
def test_endpoint():
    """Test endpoint to verify yt-dlp is working"""
    try:
        # Test with a simple video
        test_url = "https://www.youtube.com/watch?v=jNQXAC9IVRw"  # "Me at the zoo" - first YouTube video
        
        ydl_opts = get_base_ydl_opts()
        ydl_opts.update({
            'skip_download': True,
            'quiet': True,
            'extractor_args': {'youtube': {'player_client': ['ios']}}
        })
        
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(test_url, download=False)
            
        return jsonify({
            'status': 'success',
            'message': 'yt-dlp is working correctly',
            'test_video': info.get('title', 'Unknown'),
            'formats_available': len(info.get('formats', []))
        })
        
    except Exception as e:
        return jsonify({
            'status': 'error',
            'message': 'yt-dlp test failed',
            'error': str(e)
        }), 500

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