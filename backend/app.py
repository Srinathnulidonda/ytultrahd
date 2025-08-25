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
import requests

app = Flask(__name__)
CORS(app, origins=["*"], allow_headers=["Content-Type"], methods=["GET", "POST", "OPTIONS"])

# Store download progress
download_progress = {}

# Enhanced user agents pool
USER_AGENTS = [
    'Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.0 Mobile/15E148 Safari/604.1',
    'Mozilla/5.0 (iPad; CPU OS 17_0 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.0 Mobile/15E148 Safari/604.1',
    'Mozilla/5.0 (Linux; Android 13; SM-G991B) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Mobile Safari/537.36',
    'Mozilla/5.0 (Linux; Android 13; Pixel 7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Mobile Safari/537.36',
    'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
    'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
    'Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'
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

def get_aggressive_ydl_opts():
    """Get yt-dlp options with aggressive bypass techniques"""
    return {
        'quiet': True,
        'no_warnings': True,
        'no_color': True,
        'user_agent': random.choice(USER_AGENTS),
        'referer': 'https://www.youtube.com/',
        'http_headers': {
            'Accept': '*/*',
            'Accept-Language': 'en-US,en;q=0.5',
            'Accept-Encoding': 'gzip, deflate, br',
            'Origin': 'https://www.youtube.com',
            'DNT': '1',
            'Connection': 'keep-alive',
            'Sec-Fetch-Dest': 'empty',
            'Sec-Fetch-Mode': 'cors',
            'Sec-Fetch-Site': 'same-origin',
            'Pragma': 'no-cache',
            'Cache-Control': 'no-cache'
        },
        'sleep_interval': 5,
        'max_sleep_interval': 10,
        'sleep_interval_requests': 3,
        'retries': 20,
        'fragment_retries': 20,
        'skip_unavailable_fragments': True,
        'keep_fragments': False,
        'concurrent_fragment_downloads': 1,
        'http_chunk_size': 10485760,
        'socket_timeout': 60,
        'extractor_args': {
            'youtube': {
                'innertube_host': 'youtubei.googleapis.com',
                'innertube_key': None,
                'visitor_data': None,
                'po_token': None,
                'player_client': ['ios', 'android', 'tv_embed', 'mediaconnect'],
                'player_skip': ['webpage', 'configs', 'js'],
                'skip': ['hls', 'dash', 'translated_subs'],
                'comment_sort': 'top',
                'max_comments': 0,
                'max_comment_depth': 0
            }
        },
        'format_sort': [
            'res:1080',
            'fps:30',
            'codec:h264',
            'size',
            'br',
            'asr',
            'proto'
        ]
    }

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

def try_alternative_extraction(url):
    """Try alternative methods to get basic video info"""
    try:
        video_id = extract_video_id(url)
        if not video_id:
            return None
            
        # Try to get basic info from YouTube's oembed API
        oembed_url = f"https://www.youtube.com/oembed?url=https://www.youtube.com/watch?v={video_id}&format=json"
        
        headers = {
            'User-Agent': random.choice(USER_AGENTS),
            'Referer': 'https://www.youtube.com/'
        }
        
        response = requests.get(oembed_url, headers=headers, timeout=10)
        if response.status_code == 200:
            data = response.json()
            return {
                'title': data.get('title', 'Unknown'),
                'uploader': data.get('author_name', 'Unknown'),
                'thumbnail': data.get('thumbnail_url', ''),
                'duration': 0,  # Not available from oembed
                'view_count': 0,
                'video_id': video_id,
                'webpage_url': url,
                'formats_available': False,
                'fallback_method': 'oembed'
            }
    except:
        pass
    
    return None

@app.route('/', methods=['GET'])
def root():
    return jsonify({
        'service': 'YouTube Downloader API',
        'version': '2.0.0',
        'status': 'running',
        'note': 'Enhanced with aggressive bypass techniques',
        'endpoints': {
            'health': '/api/health',
            'info': '/api/info',
            'download': '/api/download',
            'formats': '/api/formats',
            'test': '/api/test'
        }
    })

@app.route('/api/health', methods=['GET'])
def health_check():
    return jsonify({
        'status': 'ok',
        'timestamp': datetime.now().isoformat(),
        'service': 'YouTube Downloader API Enhanced'
    })

@app.route('/api/info', methods=['POST'])
def get_video_info():
    try:
        data = request.get_json()
        url = data.get('url')
        
        if not url:
            return jsonify({'error': 'URL is required'}), 400
        
        # Random delay to avoid detection
        time.sleep(random.uniform(3, 6))
        
        # Try alternative extraction first
        alt_info = try_alternative_extraction(url)
        
        # Enhanced extraction strategies
        strategies = [
            # Strategy 1: Latest iOS client configuration
            {
                'extractor_args': {
                    'youtube': {
                        'player_client': ['ios'],
                        'player_skip': ['webpage', 'configs', 'js'],
                        'skip': ['hls', 'dash', 'translated_subs'],
                        'innertube_host': 'youtubei.googleapis.com',
                        'innertube_key': 'AIzaSyAO_FJ2SlqU8Q4STEHLGCilw_Y9_11qcW8'
                    }
                },
                'http_headers': {
                    'User-Agent': 'com.google.ios.youtube/19.29.1 (iPhone16,2; U; CPU iOS 17_5_1 like Mac OS X;)',
                    'X-YouTube-Client-Name': '5',
                    'X-YouTube-Client-Version': '19.29.1'
                }
            },
            # Strategy 2: Android TV client
            {
                'extractor_args': {
                    'youtube': {
                        'player_client': ['android_tv'],
                        'player_skip': ['configs', 'webpage'],
                        'skip': ['translated_subs']
                    }
                },
                'http_headers': {
                    'User-Agent': 'YouTubeAndroidTV/2.12.08',
                }
            },
            # Strategy 3: Web embed client
            {
                'extractor_args': {
                    'youtube': {
                        'player_client': ['web_embedded_player'],
                        'player_skip': ['js', 'configs'],
                        'skip': ['webpage']
                    }
                }
            },
            # Strategy 4: Media connect client
            {
                'extractor_args': {
                    'youtube': {
                        'player_client': ['mediaconnect'],
                        'player_skip': ['webpage'],
                        'bypass_age_gate': True
                    }
                }
            },
            # Strategy 5: TV embed with bypass
            {
                'extractor_args': {
                    'youtube': {
                        'player_client': ['tv_embed'],
                        'player_skip': ['configs', 'webpage'],
                        'bypass_age_gate': True,
                        'skip': ['hls', 'translated_subs']
                    }
                }
            }
        ]
        
        last_error = None
        for i, strategy in enumerate(strategies):
            try:
                print(f"Trying enhanced strategy {i+1}/{len(strategies)}")
                
                ydl_opts = get_aggressive_ydl_opts()
                ydl_opts.update({
                    'extract_flat': False,
                    'skip_download': True,
                    'getcomments': False,
                    'writesubtitles': False,
                    'writeautomaticsub': False,
                    'subtitleslangs': [],
                    'ignoreerrors': True,
                    'extract_flat': False
                })
                ydl_opts.update(strategy)
                
                with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                    info = ydl.extract_info(url, download=False)
                    
                    if not info:
                        continue
                    
                    # Extract available formats
                    formats = []
                    audio_formats = []
                    
                    for f in info.get('formats', []):
                        if f.get('format_note') == 'storyboard':
                            continue
                            
                        if f.get('vcodec') != 'none' and f.get('acodec') == 'none':
                            height = f.get('height', 0)
                            if height >= 240:
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
                    
                    formats.sort(key=lambda x: x['height'], reverse=True)
                    audio_formats.sort(key=lambda x: x['abr'], reverse=True)
                    
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
                        'video_formats': formats[:15],
                        'audio_formats': audio_formats[:8],
                        'best_video': best_video,
                        'best_audio': best_audio,
                        'video_id': extract_video_id(url),
                        'webpage_url': info.get('webpage_url', url),
                        'strategy_used': i + 1,
                        'formats_available': len(formats) > 0
                    })
                    
            except Exception as e:
                last_error = str(e)
                print(f"Enhanced strategy {i+1} failed: {last_error}")
                if i < len(strategies) - 1:
                    time.sleep(random.uniform(2, 4))
                continue
                
        # If all yt-dlp strategies failed, return alternative info if available
        if alt_info:
            alt_info['warning'] = 'Full extraction failed, showing limited info from alternative source'
            return jsonify(alt_info)
        
        # All methods failed
        return jsonify({
            'error': 'Complete extraction failure',
            'details': 'YouTube has blocked all extraction methods for this video',
            'last_error': str(last_error),
            'suggestions': [
                'This video may be region-locked or have enhanced protection',
                'Try updating yt-dlp: pip install --upgrade yt-dlp',
                'Create cookies.txt from your browser session',
                'Try again later as YouTube may have temporary restrictions',
                'Use a VPN if the video is region-locked'
            ]
        }), 503
            
    except Exception as e:
        return jsonify({
            'error': 'Server error during extraction',
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
        
        thread = threading.Thread(
            target=perform_aggressive_download,
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

def perform_aggressive_download(url, quality, audio_quality, progress_tracker):
    temp_dir = tempfile.mkdtemp()
    
    try:
        time.sleep(random.uniform(3, 6))
        
        def progress_hook(d):
            progress_tracker.update(d)
        
        # Format selection
        format_map = {
            'best': 'best[ext=mp4]/best',
            '8k': 'best[height<=4320][ext=mp4]/best[height<=4320]',
            '4k': 'best[height<=2160][ext=mp4]/best[height<=2160]',
            '2k': 'best[height<=1440][ext=mp4]/best[height<=1440]',
            '1080p': 'best[height<=1080][ext=mp4]/best[height<=1080]',
            '720p': 'best[height<=720][ext=mp4]/best[height<=720]',
            '480p': 'best[height<=480][ext=mp4]/best[height<=480]',
            '360p': 'best[height<=360][ext=mp4]/best[height<=360]',
            '240p': 'best[height<=240][ext=mp4]/best[height<=240]'
        }
        
        format_string = format_map.get(quality, 'best[ext=mp4]/best')
        output_template = os.path.join(temp_dir, '%(title).200B.%(ext)s')
        
        # Enhanced download strategies
        strategies = [
            {
                'extractor_args': {
                    'youtube': {
                        'player_client': ['ios'],
                        'player_skip': ['webpage', 'configs'],
                        'skip': ['hls', 'dash']
                    }
                },
                'http_headers': {
                    'User-Agent': 'com.google.ios.youtube/19.29.1 (iPhone16,2; U; CPU iOS 17_5_1 like Mac OS X;)'
                }
            },
            {
                'extractor_args': {
                    'youtube': {
                        'player_client': ['android_tv'],
                        'player_skip': ['configs']
                    }
                }
            },
            {
                'extractor_args': {
                    'youtube': {
                        'player_client': ['tv_embed'],
                        'bypass_age_gate': True
                    }
                }
            }
        ]
        
        for i, strategy in enumerate(strategies):
            try:
                print(f"Download strategy {i+1}/{len(strategies)}")
                
                ydl_opts = get_aggressive_ydl_opts()
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
                    'getcomments': False,
                    'ignoreerrors': True
                })
                ydl_opts.update(strategy)
                
                with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                    info = ydl.extract_info(url, download=True)
                    progress_tracker.title = info.get('title', 'Unknown')
                    progress_tracker.thumbnail = info.get('thumbnail', '')
                    
                    # Find downloaded file
                    for file in os.listdir(temp_dir):
                        if file.endswith(('.mp4', '.webm', '.mkv', '.mov', '.avi', '.m4a', '.mp3')):
                            progress_tracker.file_path = os.path.join(temp_dir, file)
                            progress_tracker.filename = file
                            break
                    
                    if progress_tracker.file_path:
                        progress_tracker.status = 'completed'
                        return
                        
            except Exception as e:
                print(f"Download strategy {i+1} failed: {str(e)}")
                if i < len(strategies) - 1:
                    time.sleep(random.uniform(2, 4))
                    continue
                    
        progress_tracker.error = 'All download strategies failed'
        progress_tracker.status = 'error'
                    
    except Exception as e:
        progress_tracker.status = 'error'
        progress_tracker.error = str(e)
    finally:
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
            
            temp_dir = os.path.dirname(progress.file_path)
            if os.path.exists(temp_dir) and temp_dir.startswith(tempfile.gettempdir()):
                try:
                    shutil.rmtree(temp_dir)
                except:
                    pass
            
            if download_id in download_progress:
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
            {'id': 'best', 'label': 'Best Available', 'description': 'Highest quality available'},
            {'id': '8k', 'label': '8K (4320p)', 'description': 'Ultra HD 8K'},
            {'id': '4k', 'label': '4K (2160p)', 'description': 'Ultra HD 4K'},
            {'id': '2k', 'label': '2K (1440p)', 'description': 'Quad HD'},
            {'id': '1080p', 'label': '1080p', 'description': 'Full HD'},
            {'id': '720p', 'label': '720p', 'description': 'HD'},
            {'id': '480p', 'label': '480p', 'description': 'SD'},
            {'id': '360p', 'label': '360p', 'description': 'Low'},
            {'id': '240p', 'label': '240p', 'description': 'Very Low'},
        ],
        'note': 'Enhanced with aggressive bypass techniques'
    })

@app.route('/api/test', methods=['GET'])
def test_endpoint():
    try:
        # Test basic functionality
        return jsonify({
            'status': 'success',
            'message': 'API is running with enhanced bypass techniques',
            'yt_dlp_version': yt_dlp.version.__version__,
            'timestamp': datetime.now().isoformat()
        })
    except Exception as e:
        return jsonify({
            'status': 'error',
            'error': str(e)
        }), 500

@app.errorhandler(404)
def not_found(e):
    return jsonify({'error': 'Endpoint not found'}), 404

@app.errorhandler(500)
def server_error(e):
    return jsonify({'error': 'Internal server error'}), 500

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port, debug=False)