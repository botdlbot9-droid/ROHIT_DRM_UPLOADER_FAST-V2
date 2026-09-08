# modules/course_handler.py
import asyncio
import json
import os
import time
import re
import glob
import shutil
import html
import aiohttp
import requests
import urllib.parse
from math import ceil
from typing import Tuple, List, Optional, Dict, Any
from pyrogram import Client
from pyrogram.types import Message
from pyrogram.errors import FloodWait

try:
    from db import db
except ImportError:
    try:
        from ..db import db
    except ImportError:
        db = None


def safe_db_add_video(video_id: str, data: dict):
    try:
        if db and hasattr(db, 'add_video'):
            db.add_video(video_id, data)
    except Exception:
        pass


def safe_db_update_video_status(video_id: str, status: str, file_path: str = None):
    try:
        if db and hasattr(db, 'update_video_status'):
            db.update_video_status(video_id, status, file_path)
    except Exception:
        pass


def safe_db_mark_video_completed(video_id: str):
    try:
        if db and hasattr(db, 'mark_video_completed'):
            db.mark_video_completed(video_id)
    except Exception:
        pass

try:
    import cloudscraper
except ImportError:
    cloudscraper = None

try:
    from modules.decryption_utils import decrypt_auth_string
except (ImportError, ValueError):
    from decryption_utils import decrypt_auth_string

# Maximum retries for each video
MAX_RETRIES = 5


# ============================================================
#  ⚡ SAFE ASYNC PROCESS RUNNER (Compatible with Python 3.8 - 3.12+)
# ============================================================
async def run_subprocess_with_timeout(process: asyncio.subprocess.Process, timeout: int = 1800) -> tuple:
    """
    Safely wait for an asyncio subprocess with a timeout.
    Avoids TypeError: Process.communicate() got an unexpected keyword argument 'timeout'.
    """
    try:
        return await asyncio.wait_for(process.communicate(), timeout=timeout)
    except asyncio.TimeoutError:
        try:
            process.kill()
        except Exception:
            pass
        raise asyncio.TimeoutError(f"Process timed out after {timeout} seconds")


# ============================================================
#  🎨 UI HELPER FUNCTIONS
# ============================================================
def format_size_readable(size_bytes: int) -> str:
    """Format bytes into readable MB / GB string."""
    if not size_bytes:
        return "0 MB"
    for unit in ['B', 'KB', 'MB', 'GB', 'TB']:
        if size_bytes < 1024.0:
            return f"{size_bytes:.1f} {unit}"
        size_bytes /= 1024.0
    return f"{size_bytes:.1f} GB"


def format_duration_readable(seconds: int) -> str:
    """Format integer seconds into readable HH:MM:SS or MM:SS."""
    if not seconds or seconds <= 0:
        return "N/A"
    hrs = seconds // 3600
    mins = (seconds % 3600) // 60
    secs = seconds % 60
    if hrs > 0:
        return f"{hrs:02d}h {mins:02d}m {secs:02d}s"
    return f"{mins:02d}m {secs:02d}s"


def render_progress_bar(percent: float, bar_len: int = 12) -> str:
    """Render a clean graphical progress bar."""
    filled = int((percent / 100) * bar_len)
    filled = max(0, min(filled, bar_len))
    return "▰" * filled + "▱" * (bar_len - filled)


def render_dashboard(
    batch_name: str,
    channel_id: int,
    quality: str,
    total_videos: int,
    current_idx: int,
    current_title: str,
    status_text: str,
    success_count: int,
    fail_count: int,
    upload_extra: str = "",
    video_count: int = 0,
    pdf_count: int = 0,
    current_kind: str = "video"
) -> str:
    """Render the master live dashboard message."""
    percent = (current_idx / total_videos) * 100 if total_videos > 0 else 0
    p_bar = render_progress_bar(percent, 12)
    safe_title = html.escape(str(current_title)[:60])
    safe_batch = html.escape(str(batch_name))
    kind_icon = "🎬" if current_kind == "video" else "📄"
    kind_label = "Video" if current_kind == "video" else "Notes / PDF"

    counts_line = ""
    if video_count or pdf_count:
        counts_line = f"📽️ <b>MPD Streams:</b> <code>{video_count}</code>  |  📄 <b>PDFs:</b> <code>{pdf_count}</code>\n"

    dashboard = (
        "╔══════════════════════════════════╗\n"
        "   ⚡ <b>PW COURSE UPLOADER DASHBOARD</b> ⚡\n"
        "╚══════════════════════════════════╝\n\n"
        f"📚 <b>Batch:</b> <code>{safe_batch}</code>\n"
        f"🎯 <b>Target Channel:</b> <code>{channel_id}</code>\n"
        f"📺 <b>Target Resolution:</b> <code>{quality}p HD</code>\n"
        f"{counts_line}\n"
        f"{kind_icon} <b>Current {kind_label} [{current_idx}/{total_videos}]:</b>\n"
        f"<blockquote><b>{safe_title}</b></blockquote>\n\n"
        f"📊 <b>Course Progress:</b> <code>{percent:.1f}%</code>\n"
        f"<code>[{p_bar}]</code>\n\n"
        f"⚡ <b>Status:</b> {status_text}\n"
    )
    if upload_extra:
        dashboard += f"{upload_extra}\n"
        
    dashboard += (
        "\n━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
        f"🟢 <b>Completed:</b> {success_count}  |  "
        f"🔴 <b>Failed:</b> {fail_count}  |  "
        f"⏳ <b>Remaining:</b> {total_videos - current_idx}\n"
        "━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
    )
    return dashboard


def format_channel_caption(
    index: int,
    title: str,
    batch_name: str,
    quality: str,
    duration_sec: int,
    file_size_bytes: int,
    part_suffix: str = ""
) -> str:
    """Creates a beautiful, professional boxed card for the channel post."""
    dur_str = format_duration_readable(duration_sec)
    size_str = format_size_readable(file_size_bytes)
    safe_title = html.escape(str(title))
    safe_batch = html.escape(str(batch_name))
    caption = (
        f"╭───⌯ 🎬 <b>LECTURE #{str(index).zfill(3)}</b>{part_suffix} ⌯───╮\n"
        f"│\n"
        f"├ 📑 <b>Title :</b> {safe_title}\n"
        f"├ 📚 <b>Batch :</b> {safe_batch}\n"
        f"├ 📺 <b>Quality :</b> {quality}p HD\n"
        f"├ ⏱ <b>Duration :</b> {dur_str}\n"
        f"├ 📦 <b>Size :</b> {size_str}\n"
        f"│\n"
        f"╰──────────────────────────╯\n"
        f"⚡ <i>Uploaded via DRM Uploader Bot</i>"
    )
    return caption


def format_pdf_caption(
    index: int,
    title: str,
    batch_name: str,
    file_size_bytes: int = 0
) -> str:
    """Creates a beautiful, professional boxed card for PDF/Notes channel posts."""
    dur_or_size = format_size_readable(file_size_bytes) if file_size_bytes > 0 else "N/A"
    safe_title = html.escape(str(title))
    safe_batch = html.escape(str(batch_name))
    caption = (
        f"╭───⌯ 📄 <b>NOTES / PDF #{str(index).zfill(3)}</b> ⌯───╮\n"
        f"│\n"
        f"├ 📑 <b>Title :</b> {safe_title}\n"
        f"├ 📚 <b>Batch :</b> {safe_batch}\n"
        f"├ 📦 <b>Size :</b> {dur_or_size}\n"
        f"│\n"
        f"╰──────────────────────────╯\n"
        f"⚡ <i>Uploaded via DRM Uploader Bot</i>"
    )
    return caption



# ============================================================
#  🔑 VIDEO URL GENERATOR (With Fallback)
# ============================================================
async def generate_video_url(batch_id: str, video_id: str, token: str, random_id: str, quality: str = '720') -> str:
    """
    Generate video URL using PW Worker API with fallback endpoints.
    API: https://pw-vid-url.quiz-book.workers.dev/
    """
    if str(video_id).startswith('http://') or str(video_id).startswith('https://'):
        return str(video_id)

    batch_clean = str(batch_id).strip()
    video_clean = str(video_id).strip()

    endpoints = [
        f"https://pw-vid-url.quiz-book.workers.dev/?parentId={batch_clean}&childId={video_clean}&quality={quality}&token={token}&randomid={random_id}",
        f"https://pw-vid-url.quiz-book.workers.dev/?parentId={batch_clean}&childId={video_clean}&token={token}&randomid={random_id}",
        f"https://anonymouspwplayeer-2038df9c1dbd.herokuapp.com/pw?url=https://d1d34p8vz63oiq.cloudfront.net/{video_clean}/master.mpd&token={token}"
    ]

    print(f"📡 API Request: {endpoints[0][:150]}...")
    last_error = "Unknown error"

    for api_url in endpoints:
        for attempt in range(1, 3):
            try:
                timeout = aiohttp.ClientTimeout(total=20)
                async with aiohttp.ClientSession(timeout=timeout) as session:
                    async with session.get(api_url) as response:
                        print(f"📡 Response Status: {response.status}")
                        if response.status == 200:
                            try:
                                data = await response.json()
                                print(f"📡 API Response: {data}")
                                if isinstance(data, dict):
                                    v_url = data.get('url') or data.get('video_url') or data.get('stream_url')
                                    if v_url and str(v_url).startswith('http'):
                                        return str(v_url)
                                    else:
                                        last_error = data.get('error', 'No URL in API response')
                                elif isinstance(data, str) and data.startswith('http'):
                                    return data
                            except Exception:
                                raw_text = await response.text()
                                if raw_text and raw_text.startswith('http'):
                                    return raw_text.strip()
                        elif response.status == 429:
                            await asyncio.sleep(2)
                        else:
                            last_error = f"HTTP {response.status}"
            except asyncio.TimeoutError:
                last_error = "API request timeout"
                await asyncio.sleep(1)
            except Exception as e:
                last_error = str(e)
                await asyncio.sleep(1)

    raise Exception(f"API request failed after trying all endpoints: {last_error}")


# ============================================================
#  🔥 EXTRACT MASTER M3U8 URL FROM PLAYLIST
# ============================================================
def extract_master_m3u8_from_playlist(m3u8_content: str) -> Optional[str]:
    """
    Extract master.m3u8 URL from the M3U8 playlist content.
    It finds the enc.key URL and replaces 'hls/enc.key' with 'master.m3u8'
    """
    try:
        print("🔍 Extracting master.m3u8 URL from playlist...")

        # Method 1: Find enc.key URL from #EXT-X-KEY line
        key_pattern = r'URI="([^"]+enc\.key[^"]*)"'
        key_match = re.search(key_pattern, m3u8_content)

        if key_match:
            enc_key_url = key_match.group(1)
            print(f"🔑 Found enc.key URL: {enc_key_url[:100]}...")

            # Replace 'hls/enc.key' with 'master.m3u8'
            master_m3u8 = enc_key_url.replace('hls/enc.key', 'master.m3u8')
            print(f"✅ Generated master.m3u8: {master_m3u8[:100]}...")
            return master_m3u8

        # Method 2: Try to find any .m3u8 URL in the content
        m3u8_pattern = r'(https?://[^\s"\']+\.m3u8[^\s"\']*)'
        m3u8_match = re.search(m3u8_pattern, m3u8_content)

        if m3u8_match:
            m3u8_url = m3u8_match.group(1)
            print(f"✅ Found direct m3u8 URL: {m3u8_url[:100]}...")
            return m3u8_url

        # Method 3: Build from base URL
        domain_pattern = r'(https?://[^/]+)/([^/]+)/([^/]+)/hls/'
        domain_match = re.search(domain_pattern, m3u8_content)

        if domain_match:
            base_url = domain_match.group(1)
            folder1 = domain_match.group(2)
            folder2 = domain_match.group(3)
            master_url = f"{base_url}/{folder1}/{folder2}/master.m3u8"
            print(f"✅ Built master.m3u8: {master_url[:100]}...")
            return master_url

        print("⚠️ Could not extract master.m3u8 URL")
        return None

    except Exception as e:
        print(f"❌ Error extracting master.m3u8: {e}")
        return None


# ============================================================
#  🔥 GET PLAYLIST CONTENT AND EXTRACT MASTER M3U8
# ============================================================
async def get_master_m3u8_from_api(video_url: str) -> str:
    """
    Fetch the M3U8 playlist and extract the master.m3u8 URL
    """
    try:
        if not video_url or not str(video_url).startswith('http'):
            return video_url

        print(f"📥 Fetching playlist from: {video_url[:100]}...")

        timeout = aiohttp.ClientTimeout(total=20)
        async with aiohttp.ClientSession(timeout=timeout) as session:
            async with session.get(video_url) as response:
                if response.status == 200:
                    content = await response.text()
                    print(f"📄 Playlist content length: {len(content)} bytes")

                    # Extract master.m3u8 URL
                    master_url = extract_master_m3u8_from_playlist(content)

                    if master_url:
                        print(f"✅ Extracted master.m3u8: {master_url[:100]}...")
                        return master_url
                    else:
                        print("⚠️ Could not extract master.m3u8, using original URL")
                        return video_url
                else:
                    print(f"❌ Failed to fetch playlist: {response.status}")
                    return video_url

    except Exception as e:
        print(f"❌ Error fetching playlist: {e}")
        return video_url



# ============================================================
#  🎬 METADATA & SMART THUMBNAIL GENERATOR
# ============================================================
async def get_video_metadata(file_path: str):
    """
    Extract duration, width, height from video using ffprobe.
    """
    duration = 0
    width = 1280
    height = 720
    try:
        cmd = [
            'ffprobe',
            '-v', 'error',
            '-select_streams', 'v:0',
            '-show_entries', 'stream=width,height,duration:format=duration',
            '-of', 'default=noprint_wrappers=1:nokey=1',
            file_path
        ]
        process = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE
        )
        stdout, _ = await run_subprocess_with_timeout(process, timeout=20)
        if process.returncode == 0 and stdout:
            lines = [l.strip() for l in stdout.decode().splitlines() if l.strip()]
            for line in lines:
                if line == "N/A":
                    continue
                try:
                    val = float(line)
                    if val > duration:
                        duration = val
                except ValueError:
                    pass

            cmd_dim = [
                'ffprobe',
                '-v', 'error',
                '-select_streams', 'v:0',
                '-show_entries', 'stream=width,height',
                '-of', 'csv=s=x:p=0',
                file_path
            ]
            p_dim = await asyncio.create_subprocess_exec(
                *cmd_dim,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE
            )
            out_dim, _ = await run_subprocess_with_timeout(p_dim, timeout=10)
            if out_dim:
                dim_str = out_dim.decode().strip()
                if 'x' in dim_str:
                    w_s, h_s = dim_str.split('x', 1)
                    if w_s.isdigit() and h_s.isdigit():
                        width = int(w_s)
                        height = int(h_s)
    except Exception as e:
        print(f"⚠️ Error getting video metadata: {e}")

    return int(duration), width, height


async def generate_thumbnail(video_path: str, thumb_path: str, duration: int = 0) -> str:
    """
    Generate crisp lecture thumbnail at 15 seconds (or 15% of duration)
    to completely avoid intro black screens and show lecture slides!
    """
    try:
        if os.path.exists(thumb_path):
            os.remove(thumb_path)

        # Smart offset: at 15 seconds or 15% into lecture to capture chalkboard/slides
        if duration > 60:
            offset = 15
        elif duration > 10:
            offset = max(3, int(duration * 0.15))
        else:
            offset = 1

        offset_str = time.strftime('%H:%M:%S', time.gmtime(offset))

        cmd = [
            'ffmpeg', '-y',
            '-ss', offset_str,
            '-i', video_path,
            '-vframes', '1',
            '-q:v', '2',
            thumb_path
        ]
        proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.DEVNULL,
            stderr=asyncio.subprocess.DEVNULL
        )
        await run_subprocess_with_timeout(proc, timeout=25)

        if os.path.exists(thumb_path) and os.path.getsize(thumb_path) > 1000:
            return thumb_path

        # Fallback to 3 seconds if 15s offset failed
        cmd_fb = [
            'ffmpeg', '-y',
            '-ss', '00:00:03',
            '-i', video_path,
            '-vframes', '1',
            '-q:v', '2',
            thumb_path
        ]
        proc2 = await asyncio.create_subprocess_exec(
            *cmd_fb,
            stdout=asyncio.subprocess.DEVNULL,
            stderr=asyncio.subprocess.DEVNULL
        )
        await run_subprocess_with_timeout(proc2, timeout=20)

        if os.path.exists(thumb_path) and os.path.getsize(thumb_path) > 1000:
            return thumb_path

    except Exception as e:
        print(f"⚠️ Thumbnail generation error: {e}")
    return None


async def split_large_video_async(file_path: str, max_size_mb: int = 1950) -> List[str]:
    """
    Splits video files larger than max_size_mb into playable parts for Telegram.
    """
    size_bytes = os.path.getsize(file_path)
    max_bytes = max_size_mb * 1024 * 1024

    if size_bytes <= max_bytes:
        return [file_path]

    print(f"✂️ File size ({size_bytes / (1024*1024):.1f} MB) exceeds Telegram limit. Splitting...")
    duration, _, _ = await get_video_metadata(file_path)
    if duration <= 0:
        duration = 3600

    parts = ceil(size_bytes / max_bytes)
    part_duration = duration / parts
    base_name = file_path.rsplit(".", 1)[0]
    output_files = []

    for i in range(parts):
        output_file = f"{base_name}_part{i+1}.mp4"
        cmd = [
            "ffmpeg", "-y",
            "-i", file_path,
            "-ss", str(int(part_duration * i)),
            "-t", str(int(part_duration)),
            "-c", "copy",
            "-movflags", "+faststart",
            output_file
        ]
        proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.DEVNULL,
            stderr=asyncio.subprocess.DEVNULL
        )
        await run_subprocess_with_timeout(proc, timeout=600)
        if os.path.exists(output_file) and os.path.getsize(output_file) > 10000:
            output_files.append(output_file)

    if output_files:
        return output_files
    return [file_path]


# ============================================================
#  🛡️ ANTI-TRUNCATION VERIFICATION ENGINE
# ============================================================
async def verify_video_integrity(file_path: str) -> Tuple[bool, str]:
    """
    Anti-truncation integrity verification.
    Detects single-fragment downloads (e.g. 1.2 MB / 0s duration) and flags them as truncated.
    Returns (is_valid, reason).
    """
    try:
        if not os.path.exists(file_path):
            return False, "File does not exist"

        file_size = os.path.getsize(file_path)
        
        # 1. Reject microscopic files (< 100 KB)
        if file_size < 100000:
            return False, f"File too small ({file_size} bytes)"

        # 2. Extract codec and duration using ffprobe
        cmd = [
            'ffprobe',
            '-v', 'error',
            '-select_streams', 'v:0',
            '-show_entries', 'stream=codec_name,duration:format=duration',
            '-of', 'default=noprint_wrappers=1:nokey=1',
            file_path
        ]
        process = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE
        )
        stdout, stderr = await run_subprocess_with_timeout(process, timeout=25)

        detected_duration = 0.0
        has_codec = False

        if process.returncode == 0 and stdout:
            lines = [l.strip() for l in stdout.decode().splitlines() if l.strip()]
            for line in lines:
                if not line or line == "N/A":
                    continue
                try:
                    dur = float(line)
                    if dur > detected_duration:
                        detected_duration = dur
                except ValueError:
                    if len(line) >= 2:
                        has_codec = True

        # 3. TRUNCATION CHECK:
        # A single HLS segment is ~1.0 - 1.8 MB with duration ~6-10 seconds.
        # If file_size is < 3 MB AND duration is < 40 seconds, it's an aborted 1-segment download!
        if file_size < 3 * 1024 * 1024 and detected_duration < 40.0:
            return False, f"Truncated video detected (Size: {format_size_readable(file_size)}, Duration: {detected_duration:.1f}s)"

        # Normal lecture acceptance
        if (has_codec or detected_duration > 1) and file_size > 100000:
            return True, "Valid"

        # Fallback for large files
        if file_size > 5 * 1024 * 1024:
            return True, "Valid by file size"

        return False, "Unplayable stream"

    except Exception as e:
        print(f"⚠️ Video verification exception: {e}")
        if os.path.exists(file_path) and os.path.getsize(file_path) > 5 * 1024 * 1024:
            return True, "Accepted fallback"
        return False, str(e)


def find_downloaded_media(base_path: str):
    """Search for media files matching base_path with various video extensions."""
    directory = os.path.dirname(base_path) or "."
    prefix = os.path.basename(base_path)

    for ext in ['.mp4', '.mkv', '.webm', '.ts']:
        target = f"{base_path}{ext}"
        if os.path.exists(target) and os.path.getsize(target) > 100000:
            return target

    if os.path.exists(directory):
        for f in os.listdir(directory):
            if f.startswith(prefix) and not f.endswith(('.part', '.ytdl', '.aria2', '.jpg')):
                full_p = os.path.join(directory, f)
                if os.path.isfile(full_p) and os.path.getsize(full_p) > 100000:
                    return full_p

    return None


async def remux_to_mp4(input_path: str, output_path: str) -> str:
    """Remux non-mp4 video (mkv, webm, ts) to clean mp4 container."""
    if input_path.endswith('.mp4') and os.path.exists(input_path):
        return input_path

    cmd = [
        'ffmpeg', '-y',
        '-i', input_path,
        '-c', 'copy',
        '-movflags', '+faststart',
        output_path
    ]
    proc = await asyncio.create_subprocess_exec(
        *cmd,
        stdout=asyncio.subprocess.DEVNULL,
        stderr=asyncio.subprocess.DEVNULL
    )
    await run_subprocess_with_timeout(proc, timeout=300)

    if os.path.exists(output_path) and os.path.getsize(output_path) > 100000:
        if os.path.exists(input_path) and input_path != output_path:
            try:
                os.remove(input_path)
            except Exception:
                pass
        return output_path
    return input_path


# ============================================================
#  🔥 DOWNLOAD VIA ASMULTIVERSE API
# ============================================================
async def download_via_asmultiverse(video_url: str, name: str, quality: str = '720') -> Optional[str]:
    """
    Download video using asmultiverse API gateway with yt-dlp.
    Handles CloudFront DRM signed URLs seamlessly.
    Matches CMD: yt-dlp "https://download.asmultiverse.com/?Vurl=<raw_url>"
    """
    try:
        clean_url = str(video_url).strip()
        clean_name = str(name).strip()
        base_dir = os.path.dirname(clean_name)
        if base_dir:
            os.makedirs(base_dir, exist_ok=True)

        target_mp4 = f"{clean_name}.mp4"

        # Construct asmultiverse download URL with trailing slash before query parameter: /?Vurl=
        # In CMD screenshot, the raw CloudFront URL is passed directly in ?Vurl=
        download_url = f"https://download.asmultiverse.com/?Vurl={clean_url}"

        print(f"📥 Downloading via asmultiverse: {download_url[:120]}...")

        # Setup format selector: prefer requested quality, fallback to best
        if quality and str(quality).isdigit():
            format_selector = (
                f"bestvideo[height<={quality}]+bestaudio/"
                f"best[height<={quality}]/"
                f"b[height<={quality}]/"
                f"best"
            )
        else:
            format_selector = "best"

        # Standard clean yt-dlp command matching working CMD setup
        cmd = [
            'yt-dlp',
            '--no-check-certificate',
            '--no-cache-dir',
            '--retries', '50',
            '--fragment-retries', '50',
            '--concurrent-fragments', '5',
            '--merge-output-format', 'mp4',
            '-f', format_selector,
            '-o', f"{clean_name}.%(ext)s",
            download_url
        ]

        process = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE
        )
        stdout, stderr = await run_subprocess_with_timeout(process, timeout=1800)

        # 1. Search for downloaded file with standard extensions
        found_file = find_downloaded_media(clean_name)

        # 2. Resilient check: if generic title was produced (like 'generic video #master [master].mp4')
        if not found_file:
            candidates = [
                "generic video #master [master].mp4",
                "generic video #master [master].mkv",
                "generic video #master [master].ts"
            ]
            if base_dir:
                candidates.extend([os.path.join(base_dir, c) for c in candidates])
            for cand in candidates:
                if cand and os.path.exists(cand) and os.path.getsize(cand) > 100000:
                    try:
                        shutil.move(cand, target_mp4)
                        found_file = target_mp4
                        print(f"📦 Renamed generic video to: {target_mp4}")
                        break
                    except Exception as e:
                        print(f"⚠️ Could not rename {cand}: {e}")

        # 3. If file found, remux to mp4 and verify integrity
        if found_file and os.path.exists(found_file):
            final_file = await remux_to_mp4(found_file, target_mp4)
            is_valid, reason = await verify_video_integrity(final_file)
            if is_valid:
                file_size = os.path.getsize(final_file)
                print(f"✅ Downloaded via asmultiverse: {file_size} bytes ({format_size_readable(file_size)})")
                return final_file
            else:
                print(f"⚠️ asmultiverse video rejected: {reason}")
                try:
                    os.remove(final_file)
                except Exception:
                    pass

        # 4. Log detailed yt-dlp error output if failed
        err_msg = stderr.decode(errors='ignore').strip() if stderr else ""
        if err_msg:
            err_summary = "\n".join(err_msg.splitlines()[:3])
            print(f"⚠️ asmultiverse yt-dlp error (code {process.returncode}):\n{err_summary}")
        else:
            print(f"⚠️ asmultiverse yt-dlp exited with code {process.returncode} (no file produced)")

        return None

    except Exception as e:
        print(f"❌ asmultiverse download error: {e}")
        return None


# ============================================================
#  🔥 RESILIENT VIDEO DOWNLOAD ENGINE (PW + asmultiverse + yt-dlp + ffmpeg)
# ============================================================
async def download_pw_video(url: str, name: str, quality: str = '720', video_id: str = None) -> Optional[str]:
    """
    PW video downloader with master.m3u8 extraction, asmultiverse API support,
    optimized yt-dlp, and resilient ffmpeg stream remuxing.
    """
    try:
        print(f"🎬 Downloading PW video: {name}")
        print(f"🔗 URL: {url[:150]}...")
        print(f"📺 Quality: {quality}p")

        if not url or not str(url).startswith('http'):
            raise Exception(f"Invalid URL: {url}")

        if video_id:
            safe_db_update_video_status(video_id, 'downloading')

        base_dir = os.path.dirname(name)
        if base_dir:
            os.makedirs(base_dir, exist_ok=True)

        target_mp4 = f"{name}.mp4"

        # Clean existing files
        for ext in ['.mp4', '.mkv', '.webm', '.ts', '.part', '.ytdl']:
            if os.path.exists(f"{name}{ext}"):
                try:
                    os.remove(f"{name}{ext}")
                except Exception:
                    pass

        # ------------------------------------------------------------
        #  STEP 1: Get master.m3u8 from the playlist if applicable
        # ------------------------------------------------------------
        master_url = await get_master_m3u8_from_api(url)

        if master_url and master_url != url:
            print(f"✅ Using master.m3u8: {master_url[:100]}...")
            video_url_to_download = master_url
        else:
            print("🔄 Using original URL")
            video_url_to_download = url

        # ------------------------------------------------------------
        #  STEP 2: Try asmultiverse API first
        # ------------------------------------------------------------
        print("🔄 Trying asmultiverse API download...")
        try:
            result = await download_via_asmultiverse(video_url_to_download, name, quality=quality)
            if result and os.path.exists(result):
                if video_id:
                    safe_db_update_video_status(video_id, 'downloaded', result)
                return result

            # If master_url failed and we have an original URL, try asmultiverse with original URL
            if video_url_to_download != url:
                print("🔄 Retrying asmultiverse with original playlist URL...")
                result = await download_via_asmultiverse(url, name, quality=quality)
                if result and os.path.exists(result):
                    if video_id:
                        safe_db_update_video_status(video_id, 'downloaded', result)
                    return result
        except Exception as ex:
            print(f"⚠️ asmultiverse attempt error: {ex}")

        # ------------------------------------------------------------
        #  STEP 3: Optimized yt-dlp (Native HLS / DASH / MPD)
        # ------------------------------------------------------------
        print("🔄 Trying yt-dlp...")
        format_selector = (
            f"bestvideo[height<={quality}]+bestaudio/"
            f"best[height<={quality}]/"
            f"bestvideo+bestaudio/"
            f"best"
        )

        ytdlp_cmd = [
            'yt-dlp',
            '--no-check-certificate',
            '--no-warnings',
            '--no-cache-dir',
            '--ignore-errors',
            '--hls-use-mpegts',
            '--skip-unavailable-fragments',
            '--fragment-retries', '30',
            '--retries', '30',
            '--concurrent-fragments', '5',
            '--merge-output-format', 'mp4',
            '-f', format_selector,
            '-o', f"{name}.%(ext)s",
            video_url_to_download
        ]

        if 'classplus' in video_url_to_download or 'akamai' in video_url_to_download:
            ytdlp_cmd.extend(['--add-header', 'Referer:https://classplusapp.com/'])

        try:
            process = await asyncio.create_subprocess_exec(
                *ytdlp_cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE
            )
            stdout, stderr = await run_subprocess_with_timeout(process, timeout=1800)

            found_file = find_downloaded_media(name)
            if found_file and os.path.exists(found_file):
                final_file = await remux_to_mp4(found_file, target_mp4)
                is_valid, reason = await verify_video_integrity(final_file)
                if is_valid:
                    print(f"✅ yt-dlp successful: {os.path.getsize(final_file)} bytes")
                    if video_id:
                        safe_db_update_video_status(video_id, 'downloaded', final_file)
                    return final_file
                else:
                    print(f"⚠️ yt-dlp download incomplete: {reason}. Attempting ffmpeg...")
                    if os.path.exists(final_file):
                        try:
                            os.remove(final_file)
                        except Exception:
                            pass
        except asyncio.TimeoutError:
            print("⚠️ yt-dlp timeout. Falling back to ffmpeg...")
        except Exception as e:
            print(f"⚠️ yt-dlp error: {e}")

        # ------------------------------------------------------------
        #  STEP 4: Fallback to ffmpeg direct download
        # ------------------------------------------------------------
        print("🔄 Trying ffmpeg direct download...")
        ffmpeg_cmd = [
            'ffmpeg', '-y',
            '-user_agent', 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
            '-reconnect', '1',
            '-reconnect_streamed', '1',
            '-reconnect_delay_max', '5',
            '-err_detect', 'ignore_err',
            '-i', video_url_to_download,
            '-c', 'copy',
            '-bsf:a', 'aac_adtstoasc',
            '-movflags', '+faststart',
            '-max_muxing_queue_size', '9999',
            '-threads', '4',
            target_mp4
        ]

        try:
            process = await asyncio.create_subprocess_exec(
                *ffmpeg_cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE
            )
            stdout, stderr = await run_subprocess_with_timeout(process, timeout=1800)

            if os.path.exists(target_mp4) and os.path.getsize(target_mp4) > 100000:
                is_valid, reason = await verify_video_integrity(target_mp4)
                if is_valid:
                    print(f"✅ ffmpeg successful: {os.path.getsize(target_mp4)} bytes")
                    if video_id:
                        safe_db_update_video_status(video_id, 'downloaded', target_mp4)
                    return target_mp4
                else:
                    print(f"⚠️ ffmpeg result rejected: {reason}")
                    if os.path.exists(target_mp4):
                        try:
                            os.remove(target_mp4)
                        except Exception:
                            pass
        except Exception as ex:
            print(f"⚠️ ffmpeg error: {ex}")

        # ------------------------------------------------------------
        #  STEP 5: Fallback to aria2c (For raw mp4 binaries)
        # ------------------------------------------------------------
        if not ('.m3u8' in video_url_to_download or '.mpd' in video_url_to_download):
            aria2_cmd = [
                'aria2c',
                '-x', '8', '-s', '8', '-k', '1M', '-j', '4',
                '--check-certificate=false',
                '--summary-interval=0',
                '--console-log-level=error',
                '-d', base_dir or '.',
                '-o', f"{os.path.basename(name)}.mp4",
                video_url_to_download
            ]
            try:
                p_aria = await asyncio.create_subprocess_exec(
                    *aria2_cmd,
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.PIPE
                )
                await run_subprocess_with_timeout(p_aria, timeout=600)

                if os.path.exists(target_mp4) and os.path.getsize(target_mp4) > 100000:
                    is_valid, _ = await verify_video_integrity(target_mp4)
                    if is_valid:
                        if video_id:
                            safe_db_update_video_status(video_id, 'downloaded', target_mp4)
                        return target_mp4
            except Exception as e:
                print(f"⚠️ aria2c error: {e}")

        if video_id:
            safe_db_update_video_status(video_id, 'failed')
        return None

    except Exception as e:
        print(f"❌ Video download error: {e}")
        if video_id:
            safe_db_update_video_status(video_id, 'failed')
        return None


# ============================================================
#  🔥 DOWNLOAD & UPLOAD HANDLER WITH AUTO-QUALITY FALLBACK
# ============================================================
async def download_and_upload_video(
    video_url: str,
    dashboard_msg: Message,
    client: Client,
    quality: str,
    batch_name: str,
    channel_id: int,
    index: int,
    total_videos: int,
    title: str,
    batch_id: str = None,
    video_id: str = None,
    token: str = None,
    random_id: str = None,
    success_count: int = 0,
    fail_count: int = 0,
    video_count: int = 0,
    pdf_count: int = 0
):
    """
    Downloads and uploads a single video with anti-truncation protection,
    automatic resolution fallback, crystal-clear thumbnails, and live dashboard.
    """
    os.makedirs("temp_downloads", exist_ok=True)
    filename = f"temp_downloads/video_{int(time.time())}_{index}"
    current_url = video_url
    vid_key = video_id or f"idx_{index}"

    safe_db_add_video(vid_key, {
        'title': title,
        'batch_name': batch_name,
        'quality': quality,
        'index': index,
        'video_url': video_url
    })
    
    # Fallback qualities list if primary quality produces truncated 1.2MB file
    quality_ladder = [quality]
    for fb in ['480', '360', '720', '']:
        if fb not in quality_ladder:
            quality_ladder.append(fb)

    last_error = None

    for q_attempt_idx, active_q in enumerate(quality_ladder):
        downloaded_file = None
        thumb_path = None
        downloaded_files = []
        
        try:
            # Update Dashboard Status: Downloading
            status_text = f"⬇️ <b>Downloading Video ({active_q or 'default'}p HD)...</b>"
            dash_text = render_dashboard(
                batch_name=batch_name,
                channel_id=channel_id,
                quality=quality,
                total_videos=total_videos,
                current_idx=index,
                current_title=title,
                status_text=status_text,
                success_count=success_count,
                fail_count=fail_count,
                video_count=video_count,
                pdf_count=pdf_count,
                current_kind="video"
            )
            try:
                await dashboard_msg.edit_text(dash_text)
            except Exception:
                pass

            # If switching qualities on retry, obtain fresh URL for that quality
            if q_attempt_idx > 0 and batch_id and video_id and token and random_id:
                try:
                    current_url = await generate_video_url(batch_id, video_id, token, random_id, active_q)
                except Exception as ex:
                    print(f"⚠️ Quality switch URL error: {ex}")

            # Download Video
            downloaded_file = await download_pw_video(current_url, filename, active_q, video_id=vid_key)
            if not downloaded_file or not os.path.exists(downloaded_file):
                raise Exception("Download failed - no playable file produced")

            # Check for Truncation
            is_valid, reason = await verify_video_integrity(downloaded_file)
            if not is_valid:
                raise Exception(f"Video file rejected: {reason}")

            # Extract Duration & Dimensions
            duration, width, height = await get_video_metadata(downloaded_file)
            file_size = os.path.getsize(downloaded_file)

            # Check if video requires splitting for 2GB Telegram limit
            split_files = await split_large_video_async(downloaded_file, max_size_mb=1950)
            downloaded_files = split_files
            total_parts = len(split_files)

            # Upload each part
            for part_idx, part_file in enumerate(split_files, start=1):
                part_duration, part_w, part_h = await get_video_metadata(part_file)
                part_size = os.path.getsize(part_file)

                # Generate high-quality thumbnail (15s offset to avoid black screen)
                thumb_target = f"{filename}_thumb_{part_idx}.jpg"
                thumb_path = await generate_thumbnail(part_file, thumb_target, duration=part_duration)

                # Styled Card Caption
                part_suffix = f" [Part {part_idx}/{total_parts}]" if total_parts > 1 else ""
                caption = format_channel_caption(
                    index=index,
                    title=title,
                    batch_name=batch_name,
                    quality=active_q or quality,
                    duration_sec=part_duration,
                    file_size_bytes=part_size,
                    part_suffix=part_suffix
                )

                # Throttled live progress callback for dashboard
                last_edit_time = [0]

                async def upload_progress(current, total):
                    now = time.time()
                    if now - last_edit_time[0] >= 4.0:  # Update every 4s to avoid Telegram rate limit
                        last_edit_time[0] = now
                        pct = (current / total) * 100 if total > 0 else 0
                        sp_bar = render_progress_bar(pct, 10)
                        up_status = f"⬆️ <b>Uploading to Channel...</b> <code>{pct:.1f}%</code>"
                        up_extra = (
                            f"📦 <code>[{sp_bar}]</code> "
                            f"{format_size_readable(current)} / {format_size_readable(total)}"
                        )
                        d_text = render_dashboard(
                            batch_name=batch_name,
                            channel_id=channel_id,
                            quality=quality,
                            total_videos=total_videos,
                            current_idx=index,
                            current_title=title,
                            status_text=up_status,
                            success_count=success_count,
                            fail_count=fail_count,
                            upload_extra=up_extra,
                            video_count=video_count,
                            pdf_count=pdf_count,
                            current_kind="video"
                        )
                        try:
                            await dashboard_msg.edit_text(d_text)
                        except Exception:
                            pass

                # Upload to Channel with FloodWait Handling
                uploaded = False
                for up_try in range(3):
                    try:
                        await client.send_video(
                            chat_id=channel_id,
                            video=part_file,
                            caption=caption,
                            duration=part_duration,
                            width=part_w,
                            height=part_h,
                            thumb=thumb_path,
                            supports_streaming=True,
                            progress=upload_progress
                        )
                        uploaded = True
                        break
                    except FloodWait as fw:
                        print(f"⏳ FloodWait: Waiting {fw.value + 2}s...")
                        await asyncio.sleep(fw.value + 2)
                    except Exception as up_err:
                        print(f"⚠️ Upload try {up_try+1} failed: {up_err}")
                        await asyncio.sleep(3)

                if not uploaded:
                    raise Exception("Telegram send_video failed after 3 attempts")

            # Clean up temp files
            for f in downloaded_files:
                if os.path.exists(f):
                    try:
                        os.remove(f)
                    except Exception:
                        pass
            if thumb_path and os.path.exists(thumb_path):
                try:
                    os.remove(thumb_path)
                except Exception:
                    pass

            safe_db_update_video_status(vid_key, 'uploaded')
            safe_db_mark_video_completed(vid_key)
            return True

        except Exception as e:
            last_error = str(e)
            print(f"⚠️ Quality {active_q}p failed for {title}: {last_error}")

            # Clean failed attempt
            for f in downloaded_files:
                if os.path.exists(f):
                    try:
                        os.remove(f)
                    except Exception:
                        pass
            if thumb_path and os.path.exists(thumb_path):
                try:
                    os.remove(thumb_path)
                except Exception:
                    pass
            for junk in glob.glob(f"{filename}*"):
                try:
                    os.remove(junk)
                except Exception:
                    pass

            await asyncio.sleep(2)

    safe_db_update_video_status(vid_key, 'failed')

    raise Exception(f"All resolution attempts failed: {last_error}")


# ============================================================
#  📄 RESILIENT PDF DOWNLOAD & UPLOAD PIPELINE (Matching main.py)
# ============================================================
async def download_pdf_file(url: str, output_path: str) -> str:
    """
    Downloads PDF using the exact techniques from main.py with resilient multi-tier fallback:
    1. Direct Cloudscraper (handles cwmediabkt99 and Cloudflare/CloudFront protections)
    2. Drago API proxy (https://dragoapi.vercel.app/pdf/{url}) as used in main.py line 1248
    3. yt-dlp native download (-R 25 --fragment-retries 25) as used in main.py line 1342
    4. aiohttp async streaming download
    """
    clean_url = str(url).strip().replace(" ", "%20")
    if clean_url.startswith('"') and clean_url.endswith('"'):
        clean_url = clean_url[1:-1]

    # Candidate URLs to try
    urls_to_try = []
    
    if "cwmediabkt99" in clean_url:
        # cwmediabkt99 is Cloudflare/Classplus S3 bucket -> use cloudscraper directly first
        urls_to_try.append(clean_url)
    elif "dragoapi.vercel.app" in clean_url:
        urls_to_try.append(clean_url)
    else:
        # For PW links, main.py (line 1248) wraps with dragoapi proxy:
        urls_to_try.append(f"https://dragoapi.vercel.app/pdf/{clean_url}")
        urls_to_try.append(clean_url)

    # Tier 1 & 2: Try with Cloudscraper (matching main.py line 1316)
    if cloudscraper:
        for u in urls_to_try:
            try:
                scraper = cloudscraper.create_scraper()
                resp = await asyncio.get_event_loop().run_in_executor(
                    None,
                    lambda: scraper.get(u, timeout=35, allow_redirects=True)
                )
                if resp.status_code == 200 and len(resp.content) > 200:
                    with open(output_path, "wb") as f:
                        f.write(resp.content)
                    if os.path.exists(output_path) and os.path.getsize(output_path) > 200:
                        print(f"✅ Cloudscraper PDF download success: {os.path.getsize(output_path)} bytes")
                        return output_path
            except Exception as e:
                print(f"⚠️ Cloudscraper error for {u[:50]}: {e}")

    # Tier 3: yt-dlp download (matching main.py line 1342: yt-dlp -o "{name}.pdf" "{url}" -R 25 --fragment-retries 25)
    for u in [clean_url]:
        try:
            cmd = [
                'yt-dlp',
                '--no-check-certificate',
                '--no-warnings',
                '--no-cache-dir',
                '-R', '25',
                '--fragment-retries', '25',
                '-o', output_path,
                u
            ]
            process = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE
            )
            await run_subprocess_with_timeout(process, timeout=90)
            if os.path.exists(output_path) and os.path.getsize(output_path) > 200:
                print(f"✅ yt-dlp PDF download success: {os.path.getsize(output_path)} bytes")
                return output_path
        except Exception as e:
            print(f"⚠️ yt-dlp PDF error: {e}")

    # Tier 4: Direct aiohttp stream
    for u in urls_to_try:
        try:
            headers = {
                'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'
            }
            timeout = aiohttp.ClientTimeout(total=45)
            async with aiohttp.ClientSession(timeout=timeout, headers=headers) as session:
                async with session.get(u, allow_redirects=True) as resp:
                    if resp.status == 200:
                        with open(output_path, "wb") as f:
                            while True:
                                chunk = await resp.content.read(64 * 1024)
                                if not chunk:
                                    break
                                f.write(chunk)
                        if os.path.exists(output_path) and os.path.getsize(output_path) > 200:
                            print(f"✅ aiohttp PDF download success: {os.path.getsize(output_path)} bytes")
                            return output_path
        except Exception as e:
            print(f"⚠️ aiohttp PDF error for {u[:50]}: {e}")

    raise Exception(f"Failed to download PDF from all sources ({clean_url[:60]})")


async def download_and_upload_pdf(
    url: str,
    dashboard_msg: Message,
    client: Client,
    quality: str,
    batch_name: str,
    channel_id: int,
    index: int,
    total_items: int,
    title: str,
    success_count: int = 0,
    fail_count: int = 0,
    video_count: int = 0,
    pdf_count: int = 0
):
    """
    Downloads and uploads a PDF note/document to the target channel.
    Updates the live dashboard and sends a styled card caption.
    """
    os.makedirs("temp_downloads", exist_ok=True)
    clean_title = re.sub(r'[\\/*?:"<>|]', '', str(title))[:60].strip() or f"Notes_{index}"
    target_pdf = os.path.join("temp_downloads", f"{clean_title}_{int(time.time())}_{index}.pdf")

    try:
        # Update Dashboard: Downloading PDF
        status_text = "⬇️ <b>Downloading Notes / PDF...</b>"
        dash_text = render_dashboard(
            batch_name=batch_name,
            channel_id=channel_id,
            quality=quality,
            total_videos=total_items,
            current_idx=index,
            current_title=title,
            status_text=status_text,
            success_count=success_count,
            fail_count=fail_count,
            video_count=video_count,
            pdf_count=pdf_count,
            current_kind="pdf"
        )
        try:
            await dashboard_msg.edit_text(dash_text)
        except Exception:
            pass

        # Download the PDF
        downloaded = await download_pdf_file(url, target_pdf)
        if not downloaded or not os.path.exists(downloaded):
            raise Exception("PDF download produced no file")

        pdf_size = os.path.getsize(downloaded)

        # Format card caption
        caption = format_pdf_caption(
            index=index,
            title=title,
            batch_name=batch_name,
            file_size_bytes=pdf_size
        )

        # Update Dashboard: Uploading
        status_text = "⬆️ <b>Uploading PDF to Channel...</b>"
        dash_text = render_dashboard(
            batch_name=batch_name,
            channel_id=channel_id,
            quality=quality,
            total_videos=total_items,
            current_idx=index,
            current_title=title,
            status_text=status_text,
            success_count=success_count,
            fail_count=fail_count,
            video_count=video_count,
            pdf_count=pdf_count,
            current_kind="pdf"
        )
        try:
            await dashboard_msg.edit_text(dash_text)
        except Exception:
            pass

        # Upload to Telegram with FloodWait retry (matching main.py line 1323)
        uploaded = False
        for up_try in range(3):
            try:
                await client.send_document(
                    chat_id=channel_id,
                    document=downloaded,
                    caption=caption
                )
                uploaded = True
                break
            except FloodWait as fw:
                print(f"⏳ FloodWait: Waiting {fw.value + 2}s...")
                await asyncio.sleep(fw.value + 2)
            except Exception as up_err:
                print(f"⚠️ PDF upload attempt {up_try+1} failed: {up_err}")
                await asyncio.sleep(3)

        if not uploaded:
            raise Exception("Telegram send_document failed after 3 attempts")

        return True

    finally:
        # Clean up
        if os.path.exists(target_pdf):
            try:
                os.remove(target_pdf)
            except Exception:
                pass


# ============================================================
#  🔥 MAIN PROCESS COURSE AND UPLOAD WORKFLOW
# ============================================================
async def process_course_and_upload(
    client: Client,
    message: Message,
    json_path: str,
    auth_string: str,
    quality: str = '720',
    batch_name: str = "Unknown Batch",
    channel_id: int = None
):
    """
    Main workflow for /add_course command with flexible JSON parsing,
    full video + PDF notes handling, anti-truncation, live single dashboard,
    and styled channel cards.
    """
    try:
        # Step 1: Parse JSON
        with open(json_path, 'r', encoding='utf-8') as f:
            course_data = json.load(f)

        # Step 2: Decrypt Auth String
        try:
            auth_data = await decrypt_auth_string(auth_string)
            token = auth_data.get('token')
            random_id = auth_data.get('randomId')
        except Exception as e:
            await message.reply_text(f"❌ <b>Auth Decryption Failed:</b> {str(e)}")
            return

        if not token or not random_id:
            raise ValueError("Auth decryption failed: Missing token or randomId.")

        # Step 3: Extract Batch ID
        batch_id = (
            course_data.get('batch', {}).get('id')
            or course_data.get('batch', {}).get('_id')
            or course_data.get('batchId')
            or course_data.get('batch_id')
            or course_data.get('id')
            or course_data.get('_id')
        )
        if not batch_id:
            raise ValueError("JSON does not contain a valid batch ID.")

        # Step 4: Extract All Content (Videos and PDFs)
        content_items = []
        seen_keys = set()

        def add_item(item, default_kind=None, parent_title=""):
            if not isinstance(item, dict):
                return
            
            title = (
                item.get('title') 
                or item.get('topic') 
                or item.get('name') 
                or parent_title 
                or f"Item {len(content_items)+1}"
            ).strip()

            u_str = str(
                item.get('url') 
                or item.get('videoUrl') 
                or item.get('link') 
                or item.get('streamUrl') 
                or ''
            ).strip()

            v_id = (
                item.get('videoId') 
                or item.get('video_id') 
                or item.get('childId') 
                or item.get('id') 
                or item.get('_id')
            )
            if v_id and isinstance(v_id, dict):
                v_id = v_id.get('_id') or str(v_id)
            if v_id:
                v_id = str(v_id).strip()

            type_str = str(item.get('type') or '').upper()
            att_url = str(
                item.get('attachment') 
                or item.get('attachmentUrl') 
                or item.get('documentUrl') 
                or item.get('dpp_url') 
                or ''
            ).strip()

            # Check if this item itself is a PDF / Document / Note
            is_pdf_item = (
                default_kind == 'pdf'
                or '.pdf' in u_str.lower()
                or type_str in ['NOTES', 'PDF', 'DOCUMENT', 'ASSIGNMENT', 'DPP_PDF']
            )

            if is_pdf_item:
                target_url = u_str or att_url
                if target_url and target_url.startswith('http') and target_url not in seen_keys:
                    seen_keys.add(target_url)
                    content_items.append({
                        'kind': 'pdf',
                        'url': target_url,
                        'title': title
                    })
                return

            # Otherwise, check if this is a video
            if v_id or (u_str and (u_str.startswith('http') or any(k in u_str.lower() for k in ['.mpd', '.m3u8', '.mp4']))):
                dedup_key = v_id or u_str
                if dedup_key not in seen_keys:
                    seen_keys.add(dedup_key)
                    content_items.append({
                        'kind': 'video',
                        'video_id': v_id or u_str,
                        'direct_url': u_str if u_str.startswith('http') else None,
                        'title': title
                    })

                # Check if there is also an attached PDF note for this lecture
                if att_url and att_url.startswith('http') and ('.pdf' in att_url.lower() or 'cwmediabkt99' in att_url):
                    if att_url not in seen_keys:
                        seen_keys.add(att_url)
                        content_items.append({
                            'kind': 'pdf',
                            'url': att_url,
                            'title': f"{title} (Notes)"
                        })

        if 'subjects' in course_data and isinstance(course_data['subjects'], list):
            for subject in course_data['subjects']:
                for topic in subject.get('topics', []):
                    top_name = topic.get('name') or topic.get('title') or ""
                    for lecture in topic.get('lectures', []):
                        add_item(lecture, default_kind=None, parent_title=top_name)
                    for note in topic.get('notes', []):
                        add_item(note, default_kind='pdf', parent_title=top_name)
                    for doc in topic.get('documents', []):
                        add_item(doc, default_kind='pdf', parent_title=top_name)
                    for dpp in topic.get('dpps', []):
                        add_item(dpp, default_kind='pdf', parent_title=top_name)

        elif 'lectures' in course_data and isinstance(course_data['lectures'], list):
            for lecture in course_data['lectures']:
                add_item(lecture, default_kind=None)
            for note in course_data.get('notes', []):
                add_item(note, default_kind='pdf')
            for doc in course_data.get('documents', []):
                add_item(doc, default_kind='pdf')

        elif isinstance(course_data, list):
            for item in course_data:
                add_item(item, default_kind=None)

        video_count = sum(1 for x in content_items if x['kind'] == 'video')
        pdf_count = sum(1 for x in content_items if x['kind'] == 'pdf')
        total_items = len(content_items)

        if total_items == 0:
            await message.reply_text("⚠️ <b>No lectures or notes found in the provided JSON.</b>")
            return

        # Initialize Master Live Dashboard
        init_dash = render_dashboard(
            batch_name=batch_name,
            channel_id=channel_id,
            quality=quality,
            total_videos=total_items,
            current_idx=1,
            current_title=content_items[0]['title'],
            status_text="🚀 <b>Starting Course Uploader Engine...</b>",
            success_count=0,
            fail_count=0,
            video_count=video_count,
            pdf_count=pdf_count,
            current_kind=content_items[0]['kind']
        )
        dashboard_msg = await message.reply_text(init_dash)

        # Notify Target Channel with comprehensive banner
        try:
            safe_b_name = html.escape(str(batch_name))
            channel_banner = (
                f"╭───⌯ 📚 <b>NEW COURSE STARTED</b> ⌯───╮\n"
                f"│\n"
                f"├ 🎯 <b>Batch :</b> {safe_b_name}\n"
                f"├ 📺 <b>Quality :</b> {quality}p HD\n"
                f"├ 📽️ <b>MPD / Videos :</b> {video_count}\n"
                f"├ 📄 <b>Notes / PDFs :</b> {pdf_count}\n"
                f"├ 📦 <b>Total Items :</b> {total_items}\n"
                f"│\n"
                f"╰──────────────────────────╯"
            )
            await client.send_message(chat_id=channel_id, text=channel_banner)
        except Exception as e:
            print(f"⚠️ Could not send channel header: {e}")

        # Process each content item sequentially (Videos & PDFs)
        success_count = 0
        fail_count = 0
        failed_items = []
        start_time = time.time()

        for idx, item in enumerate(content_items, start=1):
            kind = item['kind']
            title = item['title']

            try:
                if kind == 'video':
                    video_id = item['video_id']
                    direct_url = item.get('direct_url')

                    # Obtain initial video URL
                    if direct_url and str(direct_url).startswith('http'):
                        video_url = direct_url
                    else:
                        video_url = await generate_video_url(batch_id, video_id, token, random_id, quality)

                    # Download and upload with anti-truncation & fallback
                    await download_and_upload_video(
                        video_url=video_url,
                        dashboard_msg=dashboard_msg,
                        client=client,
                        quality=quality,
                        batch_name=batch_name,
                        channel_id=channel_id,
                        index=idx,
                        total_videos=total_items,
                        title=title,
                        batch_id=batch_id,
                        video_id=video_id,
                        token=token,
                        random_id=random_id,
                        success_count=success_count,
                        fail_count=fail_count,
                        video_count=video_count,
                        pdf_count=pdf_count
                    )
                    success_count += 1

                elif kind == 'pdf':
                    pdf_url = item['url']

                    # Download and upload PDF notes/document
                    await download_and_upload_pdf(
                        url=pdf_url,
                        dashboard_msg=dashboard_msg,
                        client=client,
                        quality=quality,
                        batch_name=batch_name,
                        channel_id=channel_id,
                        index=idx,
                        total_items=total_items,
                        title=title,
                        success_count=success_count,
                        fail_count=fail_count,
                        video_count=video_count,
                        pdf_count=pdf_count
                    )
                    success_count += 1

            except Exception as e:
                fail_count += 1
                err_msg = str(e)[:45]
                failed_items.append(f"#{idx} [{kind.upper()}] - {html.escape(str(title)[:30])} - {html.escape(err_msg)}")
                print(f"❌ Item {idx} ({kind}) failed: {e}")

            # Update dashboard status after each item
            try:
                next_item = content_items[idx] if idx < total_items else None
                next_title = next_item['title'] if next_item else "Finalizing..."
                next_kind = next_item['kind'] if next_item else "video"
                dash_update = render_dashboard(
                    batch_name=batch_name,
                    channel_id=channel_id,
                    quality=quality,
                    total_videos=total_items,
                    current_idx=min(idx + 1, total_items),
                    current_title=next_title,
                    status_text="🔄 <b>Switching to next item...</b>",
                    success_count=success_count,
                    fail_count=fail_count,
                    video_count=video_count,
                    pdf_count=pdf_count,
                    current_kind=next_kind
                )
                await dashboard_msg.edit_text(dash_update)
            except Exception:
                pass

            await asyncio.sleep(2)

        # Elapsed time
        total_time_str = format_duration_readable(int(time.time() - start_time))

        # Final Celebration Summary Card
        safe_card_batch = html.escape(str(batch_name))
        final_card = (
            "╔══════════════════════════════════╗\n"
            "   🎉 <b>COURSE PROCESSING COMPLETE!</b> 🎉\n"
            "╚══════════════════════════════════╝\n\n"
            f"📚 <b>Batch:</b> <code>{safe_card_batch}</code>\n"
            f"🎯 <b>Channel:</b> <code>{channel_id}</code>\n"
            f"📺 <b>Quality:</b> <code>{quality}p HD</code>\n"
            f"⏱ <b>Total Time:</b> <code>{total_time_str}</code>\n\n"
            f"📊 <b>Results:</b>\n"
            f"├ 🟢 <b>Uploaded Successfully:</b> <b>{success_count}</b>\n"
            f"├ 🔴 <b>Failed:</b> <b>{fail_count}</b>\n"
            f"├ 📽️ <b>Total MPD / Videos:</b> <b>{video_count}</b>\n"
            f"├ 📄 <b>Total Notes / PDFs:</b> <b>{pdf_count}</b>\n"
            f"└ 📦 <b>Total Content:</b> <b>{total_items}</b>\n"
        )

        if failed_items:
            final_card += (
                f"\n⚠️ <b>Failed Items ({len(failed_items)}):</b>\n"
                + "\n".join(failed_items[:15])
            )

        final_card += "\n\n✨ <i>All tasks finished. Powered by DRM Uploader Fast-V2</i>"
        await message.reply_text(final_card)

    except Exception as e:
        await message.reply_text(f"❌ <b>Fatal Error:</b> {str(e)}")
    finally:
        # Clean JSON file
        if os.path.exists(json_path):
            try:
                os.remove(json_path)
            except Exception:
                pass
        # Clean temp directory
        try:
            if os.path.exists("temp_downloads"):
                shutil.rmtree("temp_downloads", ignore_errors=True)
        except Exception:
            pass
