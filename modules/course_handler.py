# modules/course_handler.py
import asyncio
import json
import os
import time
import re
import glob
import shutil
import aiohttp
import subprocess
from math import ceil
from pathlib import Path
from pyrogram import Client
from pyrogram.types import Message
from pyrogram.errors import FloodWait, RPCError

# Maximum retries for each video
MAX_RETRIES = 3


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
    upload_extra: str = ""
) -> str:
    """Render the master live dashboard message."""
    percent = (current_idx / total_videos) * 100 if total_videos > 0 else 0
    p_bar = render_progress_bar(percent, 12)
    
    dashboard = (
        "╔══════════════════════════════════╗\n"
        "   ⚡ <b>PW COURSE UPLOADER DASHBOARD</b> ⚡\n"
        "╚══════════════════════════════════╝\n\n"
        f"📚 <b>Batch:</b> <code>{batch_name}</code>\n"
        f"🎯 <b>Target Channel:</b> <code>{channel_id}</code>\n"
        f"📺 <b>Target Resolution:</b> <code>{quality}p HD</code>\n\n"
        f"🎬 <b>Current Video [{current_idx}/{total_videos}]:</b>\n"
        f"<blockquote><b>{current_title[:60]}</b></blockquote>\n\n"
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
    caption = (
        f"╭───⌯ 🎬 <b>LECTURE #{str(index).zfill(3)}</b>{part_suffix} ⌯───╮\n"
        f"│\n"
        f"├ 📑 <b>Title :</b> {title}\n"
        f"├ 📚 <b>Batch :</b> {batch_name}\n"
        f"├ 📺 <b>Quality :</b> {quality}p HD\n"
        f"├ ⏱ <b>Duration :</b> {dur_str}\n"
        f"├ 📦 <b>Size :</b> {size_str}\n"
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
    Generate video URL using PW Worker API with automatic quality fallback and retries.
    API: https://pw-vid-url.quiz-book.workers.dev/
    """
    if str(video_id).startswith('http://') or str(video_id).startswith('https://'):
        return str(video_id)

    # Order of qualities to try
    qualities_to_try = [quality]
    for q in ['720', '480', '360', '240', '']:
        if q not in qualities_to_try:
            qualities_to_try.append(q)

    last_error = "Unknown error"

    for current_q in qualities_to_try:
        q_param = f"&quality={current_q}" if current_q else ""
        api_url = f"https://pw-vid-url.quiz-book.workers.dev/?parentId={batch_id}&childId={video_id}{q_param}&token={token}&randomid={random_id}"

        for attempt in range(1, 3):
            try:
                timeout = aiohttp.ClientTimeout(total=25)
                async with aiohttp.ClientSession(timeout=timeout) as session:
                    async with session.get(api_url) as response:
                        if response.status == 200:
                            data = await response.json()
                            if data.get('success') and data.get('url'):
                                v_url = data.get('url')
                                if v_url.startswith('http'):
                                    return v_url
                            elif data.get('url') and str(data.get('url')).startswith('http'):
                                return data.get('url')
                            else:
                                last_error = data.get('error', 'No URL in API response')
                                break
                        elif response.status == 429:
                            await asyncio.sleep(3)
                        else:
                            last_error = f"HTTP {response.status}"
            except asyncio.TimeoutError:
                last_error = "API request timeout"
                await asyncio.sleep(1)
            except Exception as e:
                last_error = str(e)
                await asyncio.sleep(1)

    raise Exception(f"API request failed after trying all qualities: {last_error}")


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
        stdout, _ = await process.communicate(timeout=20)
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
            out_dim, _ = await p_dim.communicate(timeout=10)
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
        await proc.communicate(timeout=25)

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
        await proc2.communicate(timeout=20)

        if os.path.exists(thumb_path) and os.path.getsize(thumb_path) > 1000:
            return thumb_path

    except Exception as e:
        print(f"⚠️ Thumbnail generation error: {e}")
    return None


async def split_large_video_async(file_path: str, max_size_mb: int = 1950) -> list:
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
        await proc.communicate()
        if os.path.exists(output_file) and os.path.getsize(output_file) > 10000:
            output_files.append(output_file)

    if output_files:
        return output_files
    return [file_path]


# ============================================================
#  🛡️ ANTI-TRUNCATION VERIFICATION ENGINE
# ============================================================
async def verify_video_integrity(file_path: str) -> tuple[bool, str]:
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
        stdout, stderr = await process.communicate(timeout=25)

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
    await proc.communicate()

    if os.path.exists(output_path) and os.path.getsize(output_path) > 100000:
        if os.path.exists(input_path) and input_path != output_path:
            try:
                os.remove(input_path)
            except Exception:
                pass
        return output_path
    return input_path


# ============================================================
#  🔥 RESILIENT VIDEO DOWNLOAD ENGINE
# ============================================================
async def download_pw_video(url: str, name: str, quality: str = '720') -> str:
    """
    Downloads PW video using multi-tiered engine.
    Ensures complete downloads and prevents 1-segment truncations.
    """
    try:
        if not url or not str(url).startswith('http'):
            raise Exception(f"Invalid URL: {url}")

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
        #  TIER 1: OPTIMIZED YT-DLP (Native HLS / DASH)
        # ------------------------------------------------------------
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
            '--hls-use-mpegts',                 # Handle HLS TS packets seamlessly
            '--skip-unavailable-fragments',     # Do NOT abort on missing fragment
            '--fragment-retries', '30',
            '--retries', '30',
            '--concurrent-fragments', '5',
            '--http-chunk-size', '10M',
            '--merge-output-format', 'mp4',
            '-f', format_selector,
            '-o', f"{name}.%(ext)s",
            url
        ]

        if 'classplus' in url or 'akamai' in url:
            ytdlp_cmd.extend(['--add-header', 'Referer:https://classplusapp.com/'])

        try:
            process = await asyncio.create_subprocess_exec(
                *ytdlp_cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE
            )
            await process.communicate(timeout=1800)

            found_file = find_downloaded_media(name)
            if found_file and os.path.exists(found_file):
                final_file = await remux_to_mp4(found_file, target_mp4)
                is_valid, reason = await verify_video_integrity(final_file)
                if is_valid:
                    print(f"✅ yt-dlp successful: {os.path.getsize(final_file)} bytes")
                    return final_file
                else:
                    print(f"⚠️ yt-dlp download incomplete: {reason}. Attempting Tier 2...")
                    if os.path.exists(final_file):
                        os.remove(final_file)
        except asyncio.TimeoutError:
            print("⚠️ yt-dlp timeout. Falling back to ffmpeg...")
        except Exception as e:
            print(f"⚠️ yt-dlp error: {e}")

        # ------------------------------------------------------------
        #  TIER 2: FFMPEG STREAM REMUX (Direct M3U8 Master Handler)
        # ------------------------------------------------------------
        ffmpeg_cmd = [
            'ffmpeg', '-y',
            '-user_agent', 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
            '-reconnect', '1',
            '-reconnect_streamed', '1',
            '-reconnect_delay_max', '10',
            '-err_detect', 'ignore_err',
            '-i', url,
            '-c', 'copy',
            '-movflags', '+faststart',
            '-max_muxing_queue_size', '9999',
            target_mp4
        ]

        try:
            process = await asyncio.create_subprocess_exec(
                *ffmpeg_cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE
            )
            await process.communicate(timeout=1800)

            if os.path.exists(target_mp4) and os.path.getsize(target_mp4) > 100000:
                is_valid, reason = await verify_video_integrity(target_mp4)
                if is_valid:
                    print(f"✅ ffmpeg stream successful: {os.path.getsize(target_mp4)} bytes")
                    return target_mp4
                else:
                    print(f"⚠️ ffmpeg stream incomplete: {reason}")
                    if os.path.exists(target_mp4):
                        os.remove(target_mp4)
        except Exception as e:
            print(f"⚠️ ffmpeg stream error: {e}")

        # ------------------------------------------------------------
        #  TIER 3: ARIA2C DIRECT DOWNLOAD (For raw mp4 binaries)
        # ------------------------------------------------------------
        if not ('.m3u8' in url or '.mpd' in url):
            aria2_cmd = [
                'aria2c',
                '-x', '8', '-s', '8', '-k', '1M', '-j', '4',
                '--check-certificate=false',
                '--summary-interval=0',
                '--console-log-level=error',
                '-d', base_dir or '.',
                '-o', f"{os.path.basename(name)}.mp4",
                url
            ]
            try:
                p_aria = await asyncio.create_subprocess_exec(
                    *aria2_cmd,
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.PIPE
                )
                await p_aria.communicate(timeout=600)

                if os.path.exists(target_mp4) and os.path.getsize(target_mp4) > 100000:
                    is_valid, _ = await verify_video_integrity(target_mp4)
                    if is_valid:
                        return target_mp4
            except Exception as e:
                print(f"⚠️ aria2c error: {e}")

        return None

    except Exception as e:
        print(f"❌ Video download error: {e}")
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
    fail_count: int = 0
):
    """
    Downloads and uploads a single video with anti-truncation protection,
    automatic resolution fallback, crystal-clear thumbnails, and live dashboard.
    """
    os.makedirs("temp_downloads", exist_ok=True)
    filename = f"temp_downloads/video_{int(time.time())}_{index}"
    current_url = video_url
    
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
                fail_count=fail_count
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
            downloaded_file = await download_pw_video(current_url, filename, active_q)
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
                            upload_extra=up_extra
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

    raise Exception(f"All resolution attempts failed: {last_error}")


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
    anti-truncation, quality fallback, live single dashboard, and styled channel cards.
    """
    try:
        # Step 1: Parse JSON
        with open(json_path, 'r', encoding='utf-8') as f:
            course_data = json.load(f)

        # Step 2: Decrypt Auth String
        try:
            from .decryption_utils import decrypt_auth_string
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

        # Step 4: Extract Video List
        video_list = []

        if 'subjects' in course_data and isinstance(course_data['subjects'], list):
            for subject in course_data['subjects']:
                for topic in subject.get('topics', []):
                    for lecture in topic.get('lectures', []):
                        v_id = (
                            lecture.get('videoId')
                            or lecture.get('video_id')
                            or lecture.get('childId')
                            or lecture.get('id')
                            or lecture.get('_id')
                        )
                        direct_url = (
                            lecture.get('url')
                            or lecture.get('videoUrl')
                            or lecture.get('link')
                            or lecture.get('streamUrl')
                        )
                        if v_id or direct_url:
                            video_list.append({
                                'video_id': v_id or direct_url,
                                'direct_url': direct_url if (direct_url and str(direct_url).startswith('http')) else None,
                                'title': lecture.get('title') or lecture.get('topic') or lecture.get('name') or f"Lecture {len(video_list)+1}"
                            })

        elif 'lectures' in course_data and isinstance(course_data['lectures'], list):
            for lecture in course_data['lectures']:
                v_id = (
                    lecture.get('videoId')
                    or lecture.get('video_id')
                    or lecture.get('childId')
                    or lecture.get('id')
                )
                direct_url = lecture.get('url') or lecture.get('videoUrl') or lecture.get('link')
                if v_id or direct_url:
                    video_list.append({
                        'video_id': v_id or direct_url,
                        'direct_url': direct_url if (direct_url and str(direct_url).startswith('http')) else None,
                        'title': lecture.get('title') or lecture.get('name') or f"Lecture {len(video_list)+1}"
                    })

        elif isinstance(course_data, list):
            for item in course_data:
                v_id = item.get('videoId') or item.get('video_id') or item.get('childId') or item.get('id')
                direct_url = item.get('url') or item.get('videoUrl') or item.get('link')
                if v_id or direct_url:
                    video_list.append({
                        'video_id': v_id or direct_url,
                        'direct_url': direct_url if (direct_url and str(direct_url).startswith('http')) else None,
                        'title': item.get('title') or item.get('name') or f"Lecture {len(video_list)+1}"
                    })

        total_videos = len(video_list)
        if total_videos == 0:
            await message.reply_text("⚠️ <b>No lectures found in the provided JSON.</b>")
            return

        # Initialize Master Live Dashboard
        init_dash = render_dashboard(
            batch_name=batch_name,
            channel_id=channel_id,
            quality=quality,
            total_videos=total_videos,
            current_idx=1,
            current_title=video_list[0]['title'],
            status_text="🚀 <b>Starting Course Uploader Engine...</b>",
            success_count=0,
            fail_count=0
        )
        dashboard_msg = await message.reply_text(init_dash)

        # Notify Target Channel
        try:
            channel_banner = (
                f"╭───⌯ 📚 <b>NEW COURSE STARTED</b> ⌯───╮\n"
                f"│\n"
                f"├ 🎯 <b>Batch :</b> {batch_name}\n"
                f"├ 📺 <b>Quality :</b> {quality}p HD\n"
                f"├ 📽️ <b>Total Lectures :</b> {total_videos}\n"
                f"│\n"
                f"╰──────────────────────────╯"
            )
            await client.send_message(chat_id=channel_id, text=channel_banner)
        except Exception as e:
            print(f"⚠️ Could not send channel header: {e}")

        # Process each video sequentially
        success_count = 0
        fail_count = 0
        failed_videos = []
        start_time = time.time()

        for idx, video_info in enumerate(video_list, start=1):
            video_id = video_info['video_id']
            direct_url = video_info.get('direct_url')
            title = video_info['title']

            try:
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
                    total_videos=total_videos,
                    title=title,
                    batch_id=batch_id,
                    video_id=video_id,
                    token=token,
                    random_id=random_id,
                    success_count=success_count,
                    fail_count=fail_count
                )

                success_count += 1

            except Exception as e:
                fail_count += 1
                err_msg = str(e)[:45]
                failed_videos.append(f"#{idx} - {title[:30]} - {err_msg}")
                print(f"❌ Lecture {idx} failed: {e}")

            # Update dashboard status after each lecture
            try:
                next_title = video_list[idx]['title'] if idx < total_videos else "Finalizing..."
                dash_update = render_dashboard(
                    batch_name=batch_name,
                    channel_id=channel_id,
                    quality=quality,
                    total_videos=total_videos,
                    current_idx=min(idx + 1, total_videos),
                    current_title=next_title,
                    status_text="🔄 <b>Switching to next lecture...</b>",
                    success_count=success_count,
                    fail_count=fail_count
                )
                await dashboard_msg.edit_text(dash_update)
            except Exception:
                pass

            await asyncio.sleep(2)

        # Elapsed time
        total_time_str = format_duration_readable(int(time.time() - start_time))

        # Final Celebration Summary Card
        final_card = (
            "╔══════════════════════════════════╗\n"
            "   🎉 <b>COURSE PROCESSING COMPLETE!</b> 🎉\n"
            "╚══════════════════════════════════╝\n\n"
            f"📚 <b>Batch:</b> <code>{batch_name}</code>\n"
            f"🎯 <b>Channel:</b> <code>{channel_id}</code>\n"
            f"📺 <b>Quality:</b> <code>{quality}p HD</code>\n"
            f"⏱ <b>Total Time:</b> <code>{total_time_str}</code>\n\n"
            f"📊 <b>Results:</b>\n"
            f"├ 🟢 <b>Uploaded Successfully:</b> <b>{success_count}</b>\n"
            f"├ 🔴 <b>Failed:</b> <b>{fail_count}</b>\n"
            f"└ 📽️ <b>Total Lectures:</b> <b>{total_videos}</b>\n"
        )

        if failed_videos:
            final_card += (
                f"\n⚠️ <b>Failed Lectures ({len(failed_videos)}):</b>\n"
                + "\n".join(failed_videos[:15])
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
