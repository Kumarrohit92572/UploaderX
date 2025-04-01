import os
import yt_dlp
from config import DOWNLOAD_DIR
import time
import asyncio
from urllib.parse import urlparse
import requests
import re
import logging
from datetime import datetime
import sys
import subprocess
import shutil
from pathlib import Path

# Configure modern terminal logging with cleaner format
class ColoredFormatter(logging.Formatter):
    """Custom formatter with colors"""
    grey = "\x1b[38;21m"
    blue = "\x1b[38;5;39m"
    yellow = "\x1b[38;5;226m"
    red = "\x1b[38;5;196m"
    green = "\x1b[38;5;40m"
    bold_red = "\x1b[31;1m"
    reset = "\x1b[0m"

    FORMATS = {
        logging.DEBUG: grey + "%(asctime)s [DEBUG] %(message)s" + reset,
        logging.INFO: blue + "%(asctime)s [INFO] %(message)s" + reset,
        logging.WARNING: yellow + "%(asctime)s [WARNING] %(message)s" + reset,
        logging.ERROR: red + "%(asctime)s [ERROR] %(message)s" + reset,
        logging.CRITICAL: bold_red + "%(asctime)s [CRITICAL] %(message)s" + reset
    }

    def format(self, record):
        log_fmt = self.FORMATS.get(record.levelno)
        formatter = logging.Formatter(log_fmt, datefmt='%H:%M:%S')
        return formatter.format(record)

# Setup logger with clean output
logger = logging.getLogger("URLUploader")
logger.setLevel(logging.INFO)
logger.handlers = []  # Clear any existing handlers

# Create console handler with custom formatter
console_handler = logging.StreamHandler(sys.stdout)
console_handler.setFormatter(ColoredFormatter())
logger.addHandler(console_handler)

def format_bytes(bytes_val):
    """Format bytes to human readable string"""
    if bytes_val is None:
        return "0B"
    
    try:
        bytes_val = float(bytes_val)
        for unit in ['', 'Ki', 'Mi', 'Gi', 'Ti', 'Pi', 'Ei', 'Zi']:
            if abs(bytes_val) < 1024.0:
                return f"{bytes_val:3.1f}{unit}B"
            bytes_val /= 1024.0
        return f"{bytes_val:.1f}YiB"
    except:
        return "0B"

def format_time(seconds):
    """Format seconds to MM:SS"""
    if seconds is None or seconds < 0:
        return "--:--"
    
    try:
        minutes, seconds = divmod(int(seconds), 60)
        hours, minutes = divmod(minutes, 60)
        if hours > 0:
            return f"{hours:02d}:{minutes:02d}:{seconds:02d}"
        else:
            return f"{minutes:02d}:{seconds:02d}"
    except:
        return "--:--"

class VideoInfo:
    """Class to store video metadata"""
    def __init__(self):
        self.width = 0
        self.height = 0
        self.duration = 0
        self.thumbnail = None
        self.title = ""
        self.format = ""

class Downloader:
    def __init__(self, url: str, filename: str, progress_callback=None):
        self.url = url
        self.filename = filename
        self.progress_callback = progress_callback
        self.downloaded_path = None
        self.file_size = 0
        self.start_time = time.time()
        self.last_downloaded = 0
        self.last_time = time.time()
        self.speed = 0
        self.eta = 0
        self.decryption_key = None
        self.last_update_time = 0
        self.update_interval = 1  # Update UI every 1 second to keep it responsive
        self.video_info = VideoInfo()
        self.download_started = False
        
        # Check if URL contains decryption key
        if '*' in url:
            self.url, self.decryption_key = url.split('*', 1)
            logger.info(f"🔐 Detected encrypted video URL with key: {self.decryption_key[:3]}***")

    def decrypt_vid_data(self, vid_data, key):
        """Decrypt video data using XOR with key"""
        data_length = len(vid_data)
        key_length = len(key)
        max_length = min(data_length, 28)
        for index in range(max_length):
            current_byte = vid_data[index]
            if index < key_length:
                decrypted_byte = current_byte ^ ord(key[index])
            else:
                decrypted_byte = current_byte ^ index
            vid_data[index] = decrypted_byte
        return vid_data

    def get_file_extension(self):
        parsed_url = urlparse(self.url)
        path = parsed_url.path.lower()
        
        # Handle encrypted video URLs
        if self.decryption_key:
            # Extract original extension from URL
            ext_match = re.search(r'\.(mkv|mp4|avi|mov|wmv|flv|webm)(?:\*|$)', self.url.lower())
            if ext_match:
                return f".{ext_match.group(1)}"
            return '.mkv'  # Default for encrypted videos
        
        # Keep original extension for videos
        if any(path.endswith(ext) for ext in ['.mkv', '.mp4', '.avi', '.mov', '.wmv', '.flv', '.webm']):
            ext = os.path.splitext(path)[1].lower()
            return ext if ext else '.mkv'
        
        return '.mkv'  # Default to .mkv

    async def send_initial_progress(self):
        """Send initial progress update to ensure UI is responsive"""
        if self.progress_callback:
            try:
                # Send initial progress with dummy values
                await self.progress_callback(0, 0, 0, 0, 0, self.filename)
            except Exception as e:
                logger.error(f"Error sending initial progress: {e}")

    def progress_hook(self, d):
        """Progress hook for yt-dlp that follows exact yt-dlp output format"""
        try:
            # First progress update - mark download as started
            if not self.download_started:
                self.download_started = True
                logger.info(f"🚀 Starting download: {self.filename}")
                # Force an immediate update for better UX
                self.last_update_time = 0
            
            if d['status'] == 'downloading':
                # Get progress data directly from yt-dlp
                downloaded = d.get('downloaded_bytes', 0)
                total = d.get('total_bytes') or d.get('total_bytes_estimate', 0)
                speed = d.get('speed', 0)
                eta = d.get('eta', 0)
                filename = d.get('filename', '')
                
                # Calculate progress percentage
                if total:
                    progress = (downloaded / total) * 100
                else:
                    progress = 0
                    
                # Store video info if available
                if 'info_dict' in d:
                    info_dict = d.get('info_dict', {})
                    self.video_info.width = info_dict.get('width', 0)
                    self.video_info.height = info_dict.get('height', 0)
                    self.video_info.duration = info_dict.get('duration', 0)
                    self.video_info.title = info_dict.get('title', '')
                    self.video_info.format = info_dict.get('format', '')
                    
                # Format status message exactly like yt-dlp
                status = f"[download] {progress:5.1f}% of {format_bytes(total)} at {format_bytes(speed)}/s ETA {format_time(eta)}"
                logger.info(status)
                
                # Throttle UI updates to avoid Telegram rate limiting
                current_time = time.time()
                if (current_time - self.last_update_time) >= self.update_interval:
                    self.last_update_time = current_time
                    
                    # Call the progress callback if it exists
                    if self.progress_callback:
                        try:
                            loop = asyncio.get_event_loop()
                            if loop.is_running():
                                loop.create_task(self.progress_callback(progress, speed, total, downloaded, eta, filename))
                            else:
                                loop.run_until_complete(self.progress_callback(progress, speed, total, downloaded, eta, filename))
                        except Exception as e:
                            logger.error(f"Progress callback error: {e}")
                            
                    # Update tracking variables
                    self.last_downloaded = downloaded
                    self.last_time = current_time
            
            elif d['status'] == 'finished':
                logger.info(f"✅ Download finished: {d.get('filename', 'unknown')}")
                
                # Store video info if available
                if 'info_dict' in d:
                    info_dict = d.get('info_dict', {})
                    self.video_info.width = info_dict.get('width', 0)
                    self.video_info.height = info_dict.get('height', 0)
                    self.video_info.duration = info_dict.get('duration', 0)
                    self.video_info.title = info_dict.get('title', '')
                    self.video_info.format = info_dict.get('format', '')
                    
                # Final progress update
                if self.progress_callback:
                    try:
                        loop = asyncio.get_event_loop()
                        filename = d.get('filename', '')
                        if loop.is_running():
                            loop.create_task(self.progress_callback(100, 0, self.last_downloaded, self.last_downloaded, 0, filename))
                        else:
                            loop.run_until_complete(self.progress_callback(100, 0, self.last_downloaded, self.last_downloaded, 0, filename))
                    except Exception as e:
                        logger.error(f"Progress callback error: {e}")
        except Exception as e:
            logger.error(f"Error in progress_hook: {e}")

    def extract_video_metadata(self, video_path):
        """Extract video metadata including dimensions and duration"""
        try:
            # First try yt-dlp method to extract metadata
            ydl_opts = {
                'skip_download': True,
                'quiet': True,
                'no_warnings': True,
            }
            
            if os.path.exists(video_path):
                # Try to get video dimensions using ffprobe if available
                try:
                    cmd = [
                        'ffprobe', '-v', 'error', '-select_streams', 'v:0',
                        '-show_entries', 'stream=width,height,duration',
                        '-of', 'csv=p=0', video_path
                    ]
                    result = subprocess.run(cmd, capture_output=True, text=True)
                    if result.returncode == 0 and result.stdout.strip():
                        dimensions = result.stdout.strip().split(',')
                        if len(dimensions) >= 3:
                            self.video_info.width = int(float(dimensions[0]))
                            self.video_info.height = int(float(dimensions[1]))
                            self.video_info.duration = int(float(dimensions[2]))
                            logger.info(f"📊 Video metadata: {self.video_info.width}x{self.video_info.height}, {self.video_info.duration}s")
                except Exception as e:
                    logger.warning(f"Cannot extract video metadata with ffprobe: {e}")
            
            # Generate thumbnail if not already set
            if not self.video_info.thumbnail:
                thumbnail_path = f"{os.path.splitext(video_path)[0]}_thumb.jpg"
                try:
                    cmd = [
                        'ffmpeg', '-y', '-i', video_path, '-ss', '00:00:05', '-vframes', '1',
                        '-vf', 'scale=320:-1', thumbnail_path
                    ]
                    subprocess.run(cmd, capture_output=True)
                    if os.path.exists(thumbnail_path) and os.path.getsize(thumbnail_path) > 0:
                        self.video_info.thumbnail = thumbnail_path
                        logger.info(f"🖼️ Thumbnail generated: {thumbnail_path}")
                except Exception as e:
                    logger.warning(f"Cannot generate thumbnail: {e}")
                    
            # Use default values if we couldn't extract metadata
            if self.video_info.width == 0 or self.video_info.height == 0:
                self.video_info.width = 1280  # Default to HD resolution
                self.video_info.height = 720
            
            if self.video_info.duration == 0:
                self.video_info.duration = 60  # Default duration
                
            return True
        except Exception as e:
            logger.error(f"Failed to extract video metadata: {e}")
            return False

    async def download(self):
        """Download a file from URL with progress reporting"""
        try:
            # Send initial progress update immediately
            await self.send_initial_progress()
            
            if not os.path.exists(DOWNLOAD_DIR):
                os.makedirs(DOWNLOAD_DIR)
                logger.info(f"📁 Created download directory: {DOWNLOAD_DIR}")

            file_extension = self.get_file_extension()
            output_path = os.path.join(DOWNLOAD_DIR, f"{self.filename}{file_extension}")
            temp_path = os.path.join(DOWNLOAD_DIR, f"{self.filename}_temp{file_extension}")

            # Clean any existing files
            for path in [output_path, temp_path]:
                if os.path.exists(path):
                    os.remove(path)

            # Special handling for encrypted videos
            if self.decryption_key:
                try:
                    logger.info(f"🔐 Starting encrypted video download: {self.filename}")
                    
                    # Use yt-dlp for faster downloads with optimal settings
                    ydl_opts = {
                        'format': 'best/bestvideo+bestaudio',
                        'outtmpl': temp_path,
                        'progress_hooks': [self.progress_hook],
                        'quiet': True,
                        'noprogress': False,
                        'no_warnings': True,
                        'extract_flat': False,
                        'nocheckcertificate': True,
                        'ignoreerrors': True,
                        'no_color': True,
                        'prefer_insecure': True,
                        'allow_unplayable_formats': True,
                        'concurrent_fragments': 5,
                        'buffersize': 32768,
                        'http_chunk_size': 10485760,
                        'retries': 10,
                        'fragment_retries': 10,
                        'file_access_retries': 10,
                        'extractor_retries': 10,
                        'socket_timeout': 30,
                        'writeinfojson': True,  # Write info json for metadata
                    }

                    # Download first with yt-dlp
                    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                        info_dict = ydl.extract_info(self.url, download=True)
                        downloaded_filename = ydl.prepare_filename(info_dict)
                        
                        # Extract video metadata from info_dict
                        if info_dict:
                            self.video_info.width = info_dict.get('width', 0)
                            self.video_info.height = info_dict.get('height', 0)
                            self.video_info.duration = info_dict.get('duration', 0) 
                            self.video_info.title = info_dict.get('title', self.filename)
                            self.video_info.format = info_dict.get('format', '')
                            
                            # Extract thumbnail if available
                            thumbnail_url = info_dict.get('thumbnail')
                            if thumbnail_url:
                                thumbnail_path = f"{os.path.splitext(temp_path)[0]}_thumb.jpg"
                                try:
                                    # Download thumbnail
                                    r = requests.get(thumbnail_url, stream=True)
                                    if r.status_code == 200:
                                        with open(thumbnail_path, 'wb') as f:
                                            r.raw.decode_content = True
                                            shutil.copyfileobj(r.raw, f)
                                        if os.path.exists(thumbnail_path) and os.path.getsize(thumbnail_path) > 0:
                                            self.video_info.thumbnail = thumbnail_path
                                            logger.info(f"🖼️ Thumbnail downloaded: {thumbnail_path}")
                                except Exception as e:
                                    logger.warning(f"Cannot download thumbnail: {e}")
                    
                    if os.path.exists(temp_path):
                        logger.info("🔐 Starting decryption process")
                        
                        try:
                            # Read and decrypt the file
                            with open(temp_path, 'rb') as encrypted_file:
                                encrypted_data = encrypted_file.read()
                                
                                # Only decrypt first 28 bytes
                                header_data = list(encrypted_data[:28])
                                decrypted_header = self.decrypt_vid_data(header_data, self.decryption_key)
                                
                                # Write decrypted data
                                with open(output_path, 'wb') as decrypted_file:
                                    decrypted_file.write(bytes(decrypted_header))  # Write decrypted header
                                    decrypted_file.write(encrypted_data[28:])    # Write rest of the file as is
                            
                            # Remove temp file
                            if os.path.exists(temp_path):
                                os.remove(temp_path)
                                
                            logger.info(f"✅ Decryption completed: {output_path}")
                            
                            # Extract video metadata if not already available
                            if self.video_info.width == 0 or self.video_info.height == 0:
                                self.extract_video_metadata(output_path)
                            
                            if os.path.exists(output_path) and os.path.getsize(output_path) > 0:
                                # Get proper media info for the file
                                return True, output_path, self.video_info
                            else:
                                logger.error("❌ Decryption failed - file is empty or does not exist")
                                return False, "Decryption failed - file is empty or does not exist", None
                        except Exception as e:
                            logger.error(f"❌ Decryption error: {str(e)}")
                            # If decryption fails, try to return the undecrypted file
                            if os.path.exists(temp_path) and os.path.getsize(temp_path) > 0:
                                os.rename(temp_path, output_path)
                                # Extract video metadata
                                self.extract_video_metadata(output_path)
                                return True, output_path, self.video_info
                            return False, f"Decryption error: {str(e)}", None
                    else:
                        logger.error("❌ Download failed - temp file does not exist")
                        return False, "Download failed - temp file does not exist", None
                        
                except Exception as e:
                    logger.error(f"❌ Error processing encrypted video: {str(e)}")
                    return False, f"Error processing encrypted video: {str(e)}", None
            
            # Normal download for non-encrypted files
            else:
                ydl_opts = {
                    'format': 'best/bestvideo+bestaudio',
                    'outtmpl': output_path,
                    'progress_hooks': [self.progress_hook],
                    'quiet': True,
                    'noprogress': False,
                    'no_warnings': True,
                    'extract_flat': False,
                    'nocheckcertificate': True,
                    'ignoreerrors': True,
                    'no_color': True,
                    'prefer_insecure': True,
                    'allow_unplayable_formats': True,
                    'concurrent_fragments': 5,
                    'buffersize': 32768,
                    'http_chunk_size': 10485760,
                    'retries': 10,
                    'fragment_retries': 10,
                    'file_access_retries': 10,
                    'extractor_retries': 10,
                    'socket_timeout': 30,
                    'writeinfojson': True,  # Write info json for metadata
                }

                with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                    try:
                        logger.info(f"🚀 Starting download: {self.filename}")
                        info_dict = ydl.extract_info(self.url, download=True)
                        
                        # Extract video metadata from info_dict
                        if info_dict:
                            self.video_info.width = info_dict.get('width', 0)
                            self.video_info.height = info_dict.get('height', 0)
                            self.video_info.duration = info_dict.get('duration', 0) 
                            self.video_info.title = info_dict.get('title', self.filename)
                            self.video_info.format = info_dict.get('format', '')
                            
                            # Extract thumbnail if available
                            thumbnail_url = info_dict.get('thumbnail')
                            if thumbnail_url:
                                thumbnail_path = f"{os.path.splitext(output_path)[0]}_thumb.jpg"
                                try:
                                    # Download thumbnail
                                    r = requests.get(thumbnail_url, stream=True)
                                    if r.status_code == 200:
                                        with open(thumbnail_path, 'wb') as f:
                                            r.raw.decode_content = True
                                            shutil.copyfileobj(r.raw, f)
                                        if os.path.exists(thumbnail_path) and os.path.getsize(thumbnail_path) > 0:
                                            self.video_info.thumbnail = thumbnail_path
                                            logger.info(f"🖼️ Thumbnail downloaded: {thumbnail_path}")
                                except Exception as e:
                                    logger.warning(f"Cannot download thumbnail: {e}")
                        
                        if os.path.exists(output_path) and os.path.getsize(output_path) > 0:
                            logger.info(f"✅ Download completed: {output_path}")
                            
                            # Extract video metadata if not already available
                            if self.video_info.width == 0 or self.video_info.height == 0:
                                self.extract_video_metadata(output_path)
                                
                            return True, output_path, self.video_info
                        else:
                            logger.error("❌ Download failed - file is empty or does not exist")
                            return False, "Download failed - file is empty or does not exist", None
                    except Exception as e:
                        logger.error(f"❌ Download error: {str(e)}")
                        return False, str(e), None

        except Exception as e:
            logger.error(f"❌ General error: {str(e)}")
            return False, str(e), None 