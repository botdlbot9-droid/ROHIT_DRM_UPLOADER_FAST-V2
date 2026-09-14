# modules/pwthor_handler.py
"""
PWThor Pro Ultra DRM Engine for Telegram Bot.
Extracts DRM protected streams from pwthor.live, downloads & decrypts using N_m3u8DL-RE + mp4decrypt,
downloads PDFs via DragoAPI, and uploads directly to Telegram with live progress tracking.
"""

import os
import re
import sys
import json
import time
import html
import shutil
import asyncio
import requests
import subprocess
from typing import Tuple, List, Optional, Dict, Any

from pyrogram import Client
from pyrogram.types import Message, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton
from pyrogram.errors import FloodWait

try:
    from vars import PWTHOR_AUTH_TOKEN, PWTHOR_CONFIG_FILE, THUMBNAILS
except ImportError:
    PWTHOR_AUTH_TOKEN = "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJtb2JpbGUiOiI2MDc0OTA0OTg2ODAiLCJuYW1lIjoiUFdUaG9yIFVzZXIgNzMyODk5M2UiLCJyYW5kb21JZCI6IjczMjg5OTNlLTk1NTctNGExZS05NzIyLTMyNWUxNTEzMjEzMyIsImF1dGhUeXBlIjoiZGlyZWN0X2xvZ2luIiwiZGlyZWN0TG9naW4iOnRydWUsImlhdCI6MTc4NTg5NTI0OSwiZXhwIjoxNzkzNjcxMjQ5fQ.HaE0LWC3csez4jYlQSTh286_5HRqNQQI28Ipgdxw6iU"
    PWTHOR_CONFIG_FILE = "pwthor_config.json"
    THUMBNAILS = []

DOWNLOAD_DIR = os.path.abspath("downloads")
os.makedirs(DOWNLOAD_DIR, exist_ok=True)

USER_AGENT = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"

# ============================================================
#  1. AUTH TOKEN MANAGEMENT (Persistent Config)
# ============================================================
def get_pwthor_token() -> str:
    """Returns the current active PWThor Auth Token."""
    if os.path.exists(PWTHOR_CONFIG_FILE):
        try:
            with open(PWTHOR_CONFIG_FILE, 'r', encoding='utf-8') as f:
                data = json.load(f)
                token = data.get("auth_token")
                if token and token.strip():
                    return token.strip()
        except Exception:
            pass
    return os.environ.get("PWTHOR_AUTH_TOKEN", PWTHOR_AUTH_TOKEN).strip()


def set_pwthor_token(token: str) -> bool:
    """Saves a new PWThor Auth Token permanently."""
    try:
        data = {}
        if os.path.exists(PWTHOR_CONFIG_FILE):
            try:
                with open(PWTHOR_CONFIG_FILE, 'r', encoding='utf-8') as f:
                    data = json.load(f)
            except Exception:
                data = {}
        data["auth_token"] = token.strip()
        with open(PWTHOR_CONFIG_FILE, 'w', encoding='utf-8') as f:
            json.dump(data, f, indent=2)
        return True
    except Exception as e:
        print(f"⚠️ Failed to save PWThor token: {e}")
        return False


# ============================================================
#  2. BINARY RESOLUTION (N_m3u8DL-RE, mp4decrypt, ffmpeg)
# ============================================================
def find_binary(name: str) -> Optional[str]:
    """Find executable in project root or system PATH."""
    exe_name = f"{name}.exe" if os.name == 'nt' else name
    
    # Check current directory & app directory
    base_dirs = [
        os.path.abspath("."),
        os.path.dirname(os.path.abspath(__file__)),
        os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    ]
    for d in base_dirs:
        candidate = os.path.join(d, exe_name)
        if os.path.exists(candidate):
            return os.path.abspath(candidate)
        candidate_raw = os.path.join(d, name)
        if os.path.exists(candidate_raw):
            return os.path.abspath(candidate_raw)

    return shutil.which(name) or shutil.which(exe_name)


# ============================================================
#  3. JSON STRUCTURE DETECTION & PARSING
# ============================================================
def is_pwthor_json(data: Any) -> bool:
    """
    Detects if the provided JSON structure belongs to a PWThor manifest.
    PWThor JSON has batch/batch.name and subjects containing topics with lectures/notes.
    """
    if not isinstance(data, dict):
        return False
    
    # Rule 1: Must not be RareStudy
    domain = str(data.get('domain') or data.get('base_url') or '').lower()
    if 'rarestudy' in domain or 'testuk' in domain:
        return False

    # Rule 2: Check for PWThor batch and subjects
    has_batch = 'batch' in data or 'batchId' in data or 'batch_id' in data
    has_subjects = 'subjects' in data and isinstance(data.get('subjects'), list)
    
    if has_subjects and len(data['subjects']) > 0:
        first_sub = data['subjects'][0]
        if isinstance(first_sub, dict):
            # Check for PWThor specific keys: subject, subjectId, topics
            if 'topics' in first_sub or 'subjectId' in first_sub or 'subject' in first_sub:
                return True

    return has_batch and has_subjects


def parse_pwthor_course(course_data: dict) -> Tuple[str, str, List[Dict[str, Any]], List[Dict[str, Any]]]:
    """
    Parses PWThor manifest JSON and returns:
    (batch_id, batch_name, video_items, note_items)
    """
    batch_info = course_data.get('batch') or {}
    if isinstance(batch_info, dict):
        batch_id = str(batch_info.get('id') or batch_info.get('_id') or 'pw_batch').strip()
        batch_name = str(batch_info.get('name') or 'PWThor Course').strip()
    else:
        batch_id = str(course_data.get('batchId') or course_data.get('batch_id') or 'pw_batch').strip()
        batch_name = str(course_data.get('name') or 'PWThor Course').strip()

    batch_name = "".join(c for c in batch_name if c.isalnum() or c in " -_()[]").strip() or "PWThor Course"

    video_items = []
    note_items = []
    seen_videos = set()
    seen_notes = set()

    subjects = course_data.get('subjects') or []
    for s_idx, subject in enumerate(subjects):
        if not isinstance(subject, dict):
            continue
        subj_name = str(subject.get('subject') or f"Subject {s_idx+1}").strip()
        subj_id = str(subject.get('subjectId') or subject.get('id') or subject.get('_id') or '').strip()

        topics = subject.get('topics') or []
        for t_idx, topic in enumerate(topics):
            if not isinstance(topic, dict):
                continue
            topic_name = str(topic.get('name') or topic.get('title') or f"Topic {t_idx+1}").strip()

            # Lectures
            lectures = topic.get('lectures') or []
            for lec in lectures:
                if not isinstance(lec, dict):
                    continue
                v_id = str(lec.get('videoId') or lec.get('video_id') or lec.get('id') or '').strip()
                title = str(lec.get('title') or lec.get('name') or 'Lecture').strip()
                duration = str(lec.get('duration') or '').strip()

                if v_id and v_id not in seen_videos:
                    seen_videos.add(v_id)
                    video_items.append({
                        'kind': 'video',
                        'batch_id': batch_id,
                        'subject_id': subj_id,
                        'video_id': v_id,
                        'title': title,
                        'subject': subj_name,
                        'topic': topic_name,
                        'duration': duration
                    })

            # Notes
            notes = topic.get('notes') or topic.get('documents') or []
            for note in notes:
                if not isinstance(note, dict):
                    continue
                name = str(note.get('name') or note.get('title') or 'Notes').strip()
                url = str(note.get('url') or note.get('link') or '').strip()

                if url and url != "https://static.pw.live/" and url not in seen_notes:
                    seen_notes.add(url)
                    note_items.append({
                        'kind': 'pdf',
                        'url': url,
                        'title': name,
                        'subject': subj_name,
                        'topic': topic_name
                    })

    return batch_id, batch_name, video_items, note_items


# ============================================================
#  4. PWTHOR STREAM & CLEARKEY EXTRACTION
# ============================================================
def extract_pwthor_stream_sync(batch_id: str, subject_id: str, video_id: str, auth_token: str) -> dict:
    """
    Synchronously calls pwthor.live /watch and /api/get-video-url
    to retrieve MPD stream URL and all Video/Audio ClearKeys.
    """
    session = requests.Session()
    session.cookies.set("auth_token", auth_token)
    session.headers.update({
        "accept": "*/*",
        "accept-language": "en-GB,en-US",
        "sec-fetch-dest": "empty",
        "sec-fetch-mode": "cors",
        "sec-fetch-site": "same-origin",
        "user-agent": USER_AGENT
    })

    try:
        # Step 1: Trigger watch endpoint to populate user session
        watch_url = f"https://pwthor.live/watch?batchId={batch_id}&SubjectId={subject_id}&ChildId={video_id}&Type=penpencilvdo&VideoUrl=&isLocked=true"
        session.get(watch_url, timeout=20)

        # Step 2: Query the video URL API
        api_resp = session.get("https://pwthor.live/api/get-video-url", timeout=20)
        if api_resp.status_code != 200:
            return {'status': 'error', 'message': f"PWThor API HTTP {api_resp.status_code}"}

        resp_json = api_resp.json()
        if not resp_json.get('success'):
            return {'status': 'error', 'message': resp_json.get('message', 'PWThor API returned success: false')}

        api_data = resp_json.get('data') or {}
        mpd_url = api_data.get('url')
        if not mpd_url or not mpd_url.startswith('http'):
            return {'status': 'error', 'message': 'No valid MPD URL returned by PWThor API'}

        # Step 3: Parse ClearKeys (Handles all variations: string, dict, list)
        parsed_keys = []
        raw_keys = api_data.get('clearKeys') or api_data.get('keys') or api_data.get('key') or []

        if isinstance(raw_keys, str):
            if ":" in raw_keys:
                parsed_keys.append(raw_keys.strip())
        elif isinstance(raw_keys, dict):
            for kid, kval in raw_keys.items():
                parsed_keys.append(f"{str(kid).strip()}:{str(kval).strip()}")
        elif isinstance(raw_keys, list):
            for item_k in raw_keys:
                if isinstance(item_k, str):
                    if ":" in item_k:
                        parsed_keys.append(item_k.strip())
                elif isinstance(item_k, dict):
                    kid = item_k.get('keyId') or item_k.get('kid') or item_k.get('kId') or item_k.get('id')
                    kval = item_k.get('key') or item_k.get('k') or item_k.get('value')
                    if kid and kval:
                        parsed_keys.append(f"{str(kid).strip()}:{str(kval).strip()}")

        # Check audio keys as well
        audio_raw_keys = api_data.get('audioKeys') or api_data.get('audioClearKeys') or []
        if isinstance(audio_raw_keys, list):
            for ak in audio_raw_keys:
                if isinstance(ak, str) and ":" in ak and ak.strip() not in parsed_keys:
                    parsed_keys.append(ak.strip())
                elif isinstance(ak, dict):
                    ak_id = ak.get('keyId') or ak.get('kid')
                    ak_val = ak.get('key') or ak.get('k')
                    if ak_id and ak_val and f"{ak_id}:{ak_val}" not in parsed_keys:
                        parsed_keys.append(f"{ak_id}:{ak_val}")

        return {
            'status': 'success',
            'mpd_url': mpd_url,
            'keys': parsed_keys
        }

    except Exception as e:
        return {'status': 'error', 'message': str(e)}


async def async_extract_pwthor_stream(batch_id: str, subject_id: str, video_id: str, auth_token: str) -> dict:
    """Async wrapper around extract_pwthor_stream_sync."""
    loop = asyncio.get_event_loop()
    return await loop.run_in_executor(None, extract_pwthor_stream_sync, batch_id, subject_id, video_id, auth_token)


# ============================================================
#  5. VIDEO DOWNLOAD ENGINE (N_m3u8DL-RE + mp4decrypt + ffmpeg)
# ============================================================
async def async_download_pwthor_video(
    mpd_url: str,
    drm_keys: List[str],
    title: str,
    quality: str = "720",
    threads: int = 16,
    save_dir: str = DOWNLOAD_DIR
) -> Tuple[bool, str, Optional[str]]:
    """
    Downloads and decrypts PW video via N_m3u8DL-RE.
    Verifies audio stream muxing using ffmpeg.
    """
    os.makedirs(save_dir, exist_ok=True)
    clean_title = re.sub(r'[\\/*?:"<>|]', "", title).strip() or f"pw_video_{int(time.time())}"
    target_video = os.path.join(save_dir, f"{clean_title}.mp4")

    n_bin = find_binary("N_m3u8DL-RE") or "N_m3u8DL-RE"
    ffmpeg_bin = find_binary("ffmpeg")
    mp4dec_bin = find_binary("mp4decrypt")

    # Build N_m3u8DL-RE command line
    cmd = [
        n_bin,
        mpd_url,
        "-H", f"User-Agent: {USER_AGENT}",
        "-H", "Origin: https://pwthor.live",
        "--select-video", f"res=.*{quality}.*:for=best",
        "--select-audio", "for=best",
        "-M", "format=mp4",
        "--thread-count", str(threads),
        "--download-retry-count", "5",
        "--check-segments-count", "false",
        "--no-log",
        "--del-after-done",
        "--append-url-params",
        "--save-dir", save_dir,
        "--save-name", clean_title
    ]

    if ffmpeg_bin:
        cmd.extend(["--ffmpeg-binary-path", ffmpeg_bin])
    if mp4dec_bin:
        cmd.extend(["--decryption-binary-path", mp4dec_bin])
    for k in drm_keys:
        cmd.extend(["--key", k])

    print(f"🚀 Running N_m3u8DL-RE for {clean_title} ({quality}p, {len(drm_keys)} keys)...")

    try:
        proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.STDOUT
        )
        stdout, _ = await asyncio.wait_for(proc.communicate(), timeout=1800)
        out_text = stdout.decode('utf-8', errors='ignore') if stdout else ""

        # Check if output file was created
        if os.path.exists(target_video) and os.path.getsize(target_video) > 100000:
            # Check audio mux safety: ensure the file has audio, merge if detached
            if ffmpeg_bin:
                try:
                    dir_items = os.listdir(save_dir)
                    audio_files = [f for f in dir_items if f.startswith(clean_title) and any(f.lower().endswith(ext) for ext in ['.m4a', '.aac', '.audio.mp4', '_audio.mp4'])]
                    
                    probe_cmd = [ffmpeg_bin, "-i", target_video]
                    probe_p = await asyncio.create_subprocess_exec(
                        *probe_cmd, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE
                    )
                    _, probe_err = await probe_p.communicate()
                    has_audio = "Audio:" in probe_err.decode('utf-8', errors='ignore')

                    if not has_audio and audio_files:
                        audio_path = os.path.join(save_dir, audio_files[0])
                        temp_out = os.path.join(save_dir, f"{clean_title}_muxed.mp4")
                        merge_cmd = [
                            ffmpeg_bin, "-y",
                            "-i", target_video,
                            "-i", audio_path,
                            "-c:v", "copy",
                            "-c:a", "copy",
                            "-movflags", "+faststart",
                            temp_out
                        ]
                        merge_p = await asyncio.create_subprocess_exec(*merge_cmd, stdout=asyncio.subprocess.DEVNULL, stderr=asyncio.subprocess.DEVNULL)
                        await merge_p.communicate()
                        if os.path.exists(temp_out) and os.path.getsize(temp_out) > 1000:
                            try: os.remove(target_video)
                            except: pass
                            try: os.remove(audio_path)
                            except: pass
                            os.replace(temp_out, target_video)
                    elif has_audio and audio_files:
                        # Clean leftover audio tracks
                        for af in audio_files:
                            try: os.remove(os.path.join(save_dir, af))
                            except: pass
                except Exception as e_mux:
                    print(f"⚠️ Audio check warning: {e_mux}")

            return True, "Success", target_video

        # Check alternate extensions (.mkv, .ts)
        for ext in ['.mkv', '.ts']:
            alt_f = os.path.join(save_dir, f"{clean_title}{ext}")
            if os.path.exists(alt_f) and os.path.getsize(alt_f) > 100000:
                # Remux to mp4 if ffmpeg available
                if ffmpeg_bin:
                    remux_cmd = [ffmpeg_bin, "-y", "-i", alt_f, "-c", "copy", "-movflags", "+faststart", target_video]
                    remux_p = await asyncio.create_subprocess_exec(*remux_cmd, stdout=asyncio.subprocess.DEVNULL, stderr=asyncio.subprocess.DEVNULL)
                    await remux_p.communicate()
                    if os.path.exists(target_video):
                        try: os.remove(alt_f)
                        except: pass
                        return True, "Success", target_video
                return True, "Success", alt_f

        err_sample = out_text[-400:].strip() if out_text else "No output"
        return False, f"N_m3u8DL-RE completed without output file: {err_sample}", None

    except asyncio.TimeoutError:
        return False, "Download timed out after 30 minutes", None
    except Exception as e:
        return False, str(e), None


# ============================================================
#  6. PDF DOWNLOAD ENGINE (DragoAPI + Direct Fallback)
# ============================================================
def download_pwthor_pdf_sync(raw_url: str, title: str, save_dir: str = DOWNLOAD_DIR) -> Tuple[bool, str, Optional[str]]:
    """
    Downloads PDF via DragoAPI proxy or direct connection.
    """
    os.makedirs(save_dir, exist_ok=True)
    clean_title = re.sub(r'[\\/*?:"<>|]', "", title).strip() or f"notes_{int(time.time())}"
    pdf_path = os.path.join(save_dir, f"{clean_title}.pdf")

    session = requests.Session()
    session.headers.update({"user-agent": USER_AGENT})

    # Route through DragoAPI
    if raw_url.startswith("https://dragoapi.vercel.app/pdf/"):
        drago_url = raw_url
    else:
        drago_url = f"https://dragoapi.vercel.app/pdf/{raw_url}"

    pdf_req = None
    try:
        pdf_req = session.get(drago_url, stream=True, timeout=45, allow_redirects=True)
        if pdf_req.status_code == 200:
            content_type = pdf_req.headers.get('content-type', '').lower()
            if 'application/json' in content_type:
                try:
                    j_data = pdf_req.json()
                    resolved = j_data.get('url') or j_data.get('pdf') or j_data.get('link') or (j_data.get('data', {}) if isinstance(j_data.get('data'), dict) else {}).get('url')
                    if resolved:
                        pdf_req = session.get(resolved, stream=True, timeout=40, allow_redirects=True)
                except Exception:
                    pass
        elif pdf_req.status_code != 200:
            pdf_req = session.get(raw_url, stream=True, timeout=30, allow_redirects=True)
    except Exception:
        try:
            pdf_req = session.get(raw_url, stream=True, timeout=30, allow_redirects=True)
        except Exception as e:
            return False, f"Direct PDF request failed: {e}", None

    if pdf_req and pdf_req.status_code == 200:
        try:
            with open(pdf_path, 'wb') as f:
                for chunk in pdf_req.iter_content(chunk_size=1048576):
                    if chunk:
                        f.write(chunk)
            if os.path.exists(pdf_path) and os.path.getsize(pdf_path) > 500:
                return True, "Success", pdf_path
            return False, "PDF file was empty or corrupted", None
        except Exception as e:
            return False, f"PDF write error: {e}", None
    else:
        code = pdf_req.status_code if pdf_req else "No response"
        return False, f"PDF download failed with HTTP {code}", None


async def async_download_pwthor_pdf(raw_url: str, title: str, save_dir: str = DOWNLOAD_DIR) -> Tuple[bool, str, Optional[str]]:
    """Async wrapper for download_pwthor_pdf_sync."""
    loop = asyncio.get_event_loop()
    return await loop.run_in_executor(None, download_pwthor_pdf_sync, raw_url, title, save_dir)


# ============================================================
#  7. METADATA & THUMBNAIL GENERATOR
# ============================================================
async def get_video_metadata(file_path: str) -> Tuple[int, int, int]:
    """Returns (duration_seconds, width, height) using ffprobe."""
    ffprobe_bin = find_binary("ffprobe")
    if not ffprobe_bin or not os.path.exists(file_path):
        return 0, 1280, 720

    cmd = [
        ffprobe_bin,
        "-v", "error",
        "-show_entries", "format=duration:stream=width,height",
        "-of", "json",
        file_path
    ]
    try:
        proc = await asyncio.create_subprocess_exec(
            *cmd, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE
        )
        stdout, _ = await proc.communicate()
        data = json.loads(stdout.decode('utf-8'))
        
        duration = int(float(data.get('format', {}).get('duration', 0)))
        width = 1280
        height = 720
        streams = data.get('streams', [])
        for s in streams:
            if 'width' in s and 'height' in s:
                width = int(s['width'])
                height = int(s['height'])
                break
        return duration, width, height
    except Exception:
        return 0, 1280, 720


async def generate_thumbnail(video_path: str, thumb_path: str, duration: int = 0) -> Optional[str]:
    """Generates a JPG thumbnail from the video using ffmpeg."""
    ffmpeg_bin = find_binary("ffmpeg")
    if not ffmpeg_bin or not os.path.exists(video_path):
        return None

    # Pick frame at 10% of video or 5 seconds in
    seek_time = max(5, int(duration * 0.10)) if duration > 10 else 1
    cmd = [
        ffmpeg_bin, "-y",
        "-ss", str(seek_time),
        "-i", video_path,
        "-vframes", "1",
        "-q:v", "2",
        thumb_path
    ]
    try:
        proc = await asyncio.create_subprocess_exec(
            *cmd, stdout=asyncio.subprocess.DEVNULL, stderr=asyncio.subprocess.DEVNULL
        )
        await proc.communicate()
        if os.path.exists(thumb_path) and os.path.getsize(thumb_path) > 1000:
            return thumb_path
    except Exception:
        pass
    return None


def format_size_readable(size_bytes: int) -> str:
    """Format bytes into human-readable string."""
    if not size_bytes:
        return "0 MB"
    for unit in ['B', 'KB', 'MB', 'GB']:
        if size_bytes < 1024.0:
            return f"{size_bytes:.1f} {unit}"
        size_bytes /= 1024.0
    return f"{size_bytes:.1f} GB"


def format_duration_readable(seconds: int) -> str:
    """Format seconds into HH:MM:SS."""
    if not seconds or seconds <= 0:
        return "N/A"
    hrs = seconds // 3600
    mins = (seconds % 3600) // 60
    secs = seconds % 60
    if hrs > 0:
        return f"{hrs:02d}:{mins:02d}:{secs:02d}"
    return f"{mins:02d}:{secs:02d}"


def render_progress_bar(percent: float, bar_len: int = 10) -> str:
    """Render a graphical progress bar."""
    filled = int((percent / 100) * bar_len)
    filled = max(0, min(filled, bar_len))
    return "▰" * filled + "▱" * (bar_len - filled)


# ============================================================
#  8. TELEGRAM DASHBOARD & CAPTION DESIGN
# ============================================================
def render_pwthor_dashboard(
    batch_name: str,
    channel_id: Any,
    quality: str,
    total_items: int,
    current_idx: int,
    current_title: str,
    status_text: str,
    success_count: int,
    fail_count: int,
    upload_extra: str = ""
) -> str:
    """Renders a live Master Dashboard card for Telegram."""
    pct = (current_idx / total_items) * 100 if total_items > 0 else 0
    p_bar = render_progress_bar(pct, 12)
    safe_title = html.escape(str(current_title)[:42])
    safe_batch = html.escape(str(batch_name)[:32])

    dash = (
        "╔══════════════════════════════════╗\n"
        "   ⚡ <b>PWTHOR ULTRA UPLOADER</b> ⚡\n"
        "╚══════════════════════════════════╝\n\n"
        f"🎯 <b>Batch:</b> <code>{safe_batch}</code>\n"
        f"📺 <b>Target Res:</b> <code>{quality}p HD</code>\n"
        f"📢 <b>Target:</b> <code>{channel_id}</code>\n"
        f"📊 <b>Progress:</b> <code>[{p_bar}] {pct:.1f}%</code>\n"
        f"🔢 <b>Queue:</b> <code>{current_idx} / {total_items}</code>\n"
        f"✅ <b>Done:</b> <code>{success_count}</code>  |  ❌ <b>Failed:</b> <code>{fail_count}</code>\n\n"
        f"▶️ <b>Current Task:</b>\n"
        f"<i>{safe_title}</i>\n\n"
        f"🔄 <b>Status:</b> {status_text}\n"
    )
    if upload_extra:
        dash += f"{upload_extra}\n"
    dash += "\n⚡ <i>Engine: N_m3u8DL-RE 100x Turbo | PWThor Live API</i>"
    return dash


def format_video_caption(
    index: int,
    total: int,
    title: str,
    batch_name: str,
    subject: str,
    duration_str: str,
    file_size_str: str,
    quality: str
) -> str:
    """Boxed card caption for uploaded Telegram videos."""
    return (
        f"╭───⌯ 🎬 <b>{html.escape(str(title))}</b> ⌯───╮\n"
        f"│\n"
        f"├ 📚 <b>Batch :</b> {html.escape(str(batch_name))}\n"
        f"├ 📖 <b>Subject :</b> {html.escape(str(subject))}\n"
        f"├ 📺 <b>Quality :</b> {quality}p HD\n"
        f"├ ⏱️ <b>Duration :</b> {duration_str}\n"
        f"├ 📦 <b>File Size :</b> {file_size_str}\n"
        f"├ 🔢 <b>Part :</b> {index} of {total}\n"
        f"│\n"
        f"╰──────────────────────────╯\n"
        f"⚡ <i>Uploaded via PWThor DRM Uploader Bot</i>"
    )


def format_pdf_caption(
    index: int,
    total: int,
    title: str,
    batch_name: str,
    subject: str,
    file_size_str: str
) -> str:
    """Boxed card caption for uploaded Telegram PDF notes."""
    return (
        f"╭───⌯ 📄 <b>{html.escape(str(title))}</b> ⌯───╮\n"
        f"│\n"
        f"├ 📚 <b>Batch :</b> {html.escape(str(batch_name))}\n"
        f"├ 📖 <b>Subject :</b> {html.escape(str(subject))}\n"
        f"├ 📑 <b>Type :</b> PDF Lecture Notes\n"
        f"├ 📦 <b>File Size :</b> {file_size_str}\n"
        f"├ 🔢 <b>Item :</b> {index} of {total}\n"
        f"│\n"
        f"╰──────────────────────────╯\n"
        f"⚡ <i>Uploaded via PWThor DRM Uploader Bot</i>"
    )


# ============================================================
#  9. MAIN PROCESS COURSE AND UPLOAD WORKFLOW
# ============================================================
async def process_pwthor_and_upload(
    client: Client,
    message: Message,
    json_path: str,
    quality: str = "720",
    channel_id: Optional[int] = None,
    content_filter: str = "all", # 'all', 'videos_only', 'pdfs_only'
    custom_auth_token: Optional[str] = None
):
    """
    Complete workflow:
    1. Parse PWThor JSON
    2. Filter content (videos / PDFs / all)
    3. Loop items, extract DRM via PWThor API, download, upload to Telegram
    4. Provide live dashboard updates throughout execution
    """
    channel_id = channel_id or message.chat.id
    status_msg = await message.reply_text("🔍 **Parsing PWThor Manifest JSON...**")

    auth_token = custom_auth_token or get_pwthor_token()
    if not auth_token:
        await status_msg.edit_text("❌ **PWThor Auth Token missing!** Set it using `/setpwtoken <token>` first.")
        return

    try:
        with open(json_path, 'r', encoding='utf-8') as f:
            course_data = json.load(f)

        batch_id, batch_name, video_items, note_items = parse_pwthor_course(course_data)

        # Apply content filter
        if content_filter == 'videos_only':
            items = video_items
        elif content_filter == 'pdfs_only':
            items = note_items
        else:
            items = video_items + note_items

        if not items:
            await status_msg.edit_text("❌ **No matching videos or notes found in the provided JSON!**")
            return

        total_items = len(items)
        v_count = sum(1 for x in items if x['kind'] == 'video')
        p_count = sum(1 for x in items if x['kind'] == 'pdf')

        # State tracking (Skip already uploaded items)
        safe_batch_dir_name = re.sub(r'[\\/*?:"<>|]', "", batch_name).strip() or "PW_Batch"
        state_file = os.path.join(DOWNLOAD_DIR, f"pw_state_{batch_id}.json")
        downloaded_state = []
        if os.path.exists(state_file):
            try:
                with open(state_file, 'r', encoding='utf-8') as sf:
                    downloaded_state = json.load(sf)
            except Exception:
                downloaded_state = []

        # Send target channel banner
        try:
            safe_b_name = html.escape(str(batch_name))
            banner = (
                f"╭───⌯ 📚 <b>NEW PWTHOR BATCH STARTED</b> ⌯───╮\n"
                f"│\n"
                f"├ 🎯 <b>Batch :</b> {safe_b_name}\n"
                f"├ 📺 <b>Resolution :</b> {quality}p HD\n"
                f"├ 📽️ <b>Videos :</b> {v_count}\n"
                f"├ 📄 <b>Notes / PDFs :</b> {p_count}\n"
                f"├ 📦 <b>Total Queue :</b> {total_items} items\n"
                f"│\n"
                f"╰──────────────────────────╯"
            )
            await client.send_message(chat_id=channel_id, text=banner)
        except Exception as eb:
            print(f"⚠️ Channel banner note: {eb}")

        # Render Dashboard
        dash_text = render_pwthor_dashboard(
            batch_name=batch_name,
            channel_id=channel_id,
            quality=quality,
            total_items=total_items,
            current_idx=1,
            current_title=items[0]['title'],
            status_text="🚀 <b>Starting PWThor Engine...</b>",
            success_count=0,
            fail_count=0
        )
        dashboard_msg = await status_msg.edit_text(dash_text)

        success_count = 0
        fail_count = 0

        for idx, item in enumerate(items, start=1):
            kind = item['kind']
            title = item['title']
            subject = item.get('subject', 'General')
            item_unique_id = item.get('video_id') or item.get('url') or title

            # Check if previously downloaded/uploaded
            if item_unique_id in downloaded_state:
                print(f"⏩ Skipping already completed item: {title}")
                success_count += 1
                continue

            try:
                # ------------------- A. VIDEO ITEM -------------------
                if kind == 'video':
                    v_id = item['video_id']
                    s_id = item['subject_id']
                    b_id = item['batch_id']

                    # 1. Extraction
                    up_dash = render_pwthor_dashboard(
                        batch_name=batch_name,
                        channel_id=channel_id,
                        quality=quality,
                        total_items=total_items,
                        current_idx=idx,
                        current_title=f"🎥 {title}",
                        status_text="🔑 <b>Extracting MPD & Decryption Keys...</b>",
                        success_count=success_count,
                        fail_count=fail_count
                    )
                    try: await dashboard_msg.edit_text(up_dash)
                    except Exception: pass

                    extract_res = await async_extract_pwthor_stream(b_id, s_id, v_id, auth_token)
                    if extract_res.get('status') != 'success':
                        raise Exception(extract_res.get('message', 'Stream extraction failed'))

                    mpd_url = extract_res['mpd_url']
                    drm_keys = extract_res.get('keys') or []

                    # 2. Download via N_m3u8DL-RE
                    up_dash = render_pwthor_dashboard(
                        batch_name=batch_name,
                        channel_id=channel_id,
                        quality=quality,
                        total_items=total_items,
                        current_idx=idx,
                        current_title=f"🎥 {title}",
                        status_text=f"⬇️ <b>Downloading ({quality}p, {len(drm_keys)} Keys)...</b>",
                        success_count=success_count,
                        fail_count=fail_count
                    )
                    try: await dashboard_msg.edit_text(up_dash)
                    except Exception: pass

                    ok, msg, downloaded_file = await async_download_pwthor_video(
                        mpd_url=mpd_url,
                        drm_keys=drm_keys,
                        title=title,
                        quality=quality,
                        threads=16,
                        save_dir=DOWNLOAD_DIR
                    )

                    if not ok or not downloaded_file or not os.path.exists(downloaded_file):
                        raise Exception(f"Download failed: {msg}")

                    # 3. Metadata & Thumbnail
                    duration, width, height = await get_video_metadata(downloaded_file)
                    file_size = os.path.getsize(downloaded_file)
                    thumb_target = os.path.join(DOWNLOAD_DIR, f"thumb_{int(time.time())}.jpg")
                    thumb_path = await generate_thumbnail(downloaded_file, thumb_target, duration=duration)

                    # 4. Upload to Telegram
                    last_edit_time = [0]
                    async def upload_progress(curr, tot):
                        now = time.time()
                        if now - last_edit_time[0] >= 4.0:
                            last_edit_time[0] = now
                            pct = (curr / tot) * 100 if tot > 0 else 0
                            sp_bar = render_progress_bar(pct, 10)
                            up_status = f"⬆️ <b>Uploading to Telegram...</b> <code>{pct:.1f}%</code>"
                            up_extra = f"📦 <code>[{sp_bar}]</code> {format_size_readable(curr)} / {format_size_readable(tot)}"
                            p_dash = render_pwthor_dashboard(
                                batch_name=batch_name,
                                channel_id=channel_id,
                                quality=quality,
                                total_items=total_items,
                                current_idx=idx,
                                current_title=f"🎥 {title}",
                                status_text=up_status,
                                success_count=success_count,
                                fail_count=fail_count,
                                upload_extra=up_extra
                            )
                            try: await dashboard_msg.edit_text(p_dash)
                            except Exception: pass

                    v_caption = format_video_caption(
                        index=idx,
                        total=total_items,
                        title=title,
                        batch_name=batch_name,
                        subject=subject,
                        duration_str=format_duration_readable(duration),
                        file_size_str=format_size_readable(file_size),
                        quality=quality
                    )

                    # Upload Video with retries
                    uploaded = False
                    for attempt in range(3):
                        try:
                            await client.send_video(
                                chat_id=channel_id,
                                video=downloaded_file,
                                caption=v_caption,
                                duration=duration,
                                width=width,
                                height=height,
                                thumb=thumb_path,
                                supports_streaming=True,
                                progress=upload_progress
                            )
                            uploaded = True
                            break
                        except FloodWait as e:
                            print(f"⏳ FloodWait: waiting {e.value} seconds...")
                            await asyncio.sleep(e.value)
                        except Exception as e_up:
                            print(f"⚠️ Video upload attempt {attempt+1} failed: {e_up}")
                            await asyncio.sleep(3)

                    # Cleanup video and thumbnail
                    try:
                        if os.path.exists(downloaded_file): os.remove(downloaded_file)
                        if thumb_path and os.path.exists(thumb_path): os.remove(thumb_path)
                    except Exception: pass

                    if not uploaded:
                        raise Exception("Failed to upload video to Telegram after 3 attempts")

                # ------------------- B. PDF ITEM -------------------
                elif kind == 'pdf':
                    pdf_url = item['url']

                    up_dash = render_pwthor_dashboard(
                        batch_name=batch_name,
                        channel_id=channel_id,
                        quality=quality,
                        total_items=total_items,
                        current_idx=idx,
                        current_title=f"📄 {title}",
                        status_text="⬇️ <b>Pulling PDF via DragoAPI Turbo...</b>",
                        success_count=success_count,
                        fail_count=fail_count
                    )
                    try: await dashboard_msg.edit_text(up_dash)
                    except Exception: pass

                    ok, msg, downloaded_pdf = await async_download_pwthor_pdf(
                        raw_url=pdf_url,
                        title=title,
                        save_dir=DOWNLOAD_DIR
                    )

                    if not ok or not downloaded_pdf or not os.path.exists(downloaded_pdf):
                        raise Exception(f"PDF download failed: {msg}")

                    pdf_size = os.path.getsize(downloaded_pdf)
                    pdf_caption = format_pdf_caption(
                        index=idx,
                        total=total_items,
                        title=title,
                        batch_name=batch_name,
                        subject=subject,
                        file_size_str=format_size_readable(pdf_size)
                    )

                    # Upload PDF document
                    uploaded = False
                    for attempt in range(3):
                        try:
                            await client.send_document(
                                chat_id=channel_id,
                                document=downloaded_pdf,
                                caption=pdf_caption
                            )
                            uploaded = True
                            break
                        except FloodWait as e:
                            await asyncio.sleep(e.value)
                        except Exception as e_up:
                            print(f"⚠️ PDF upload attempt {attempt+1} failed: {e_up}")
                            await asyncio.sleep(3)

                    # Cleanup PDF
                    try:
                        if os.path.exists(downloaded_pdf): os.remove(downloaded_pdf)
                    except Exception: pass

                    if not uploaded:
                        raise Exception("Failed to upload PDF after 3 attempts")

                # Record success & checkpoint
                success_count += 1
                downloaded_state.append(item_unique_id)
                try:
                    with open(state_file, 'w', encoding='utf-8') as sf:
                        json.dump(downloaded_state, sf)
                except Exception: pass

            except Exception as e_item:
                fail_count += 1
                print(f"❌ Item #{idx} ({kind} - {title}) failed: {e_item}")

        # Completion Announcement
        fin_text = (
            "╔══════════════════════════════════╗\n"
            "   🎉 <b>PWTHOR BATCH COMPLETED!</b> 🎉\n"
            "╚══════════════════════════════════╝\n\n"
            f"📚 <b>Batch :</b> <code>{html.escape(batch_name)}</code>\n"
            f"✅ <b>Successfully Uploaded :</b> <code>{success_count} / {total_items}</code>\n"
            f"❌ <b>Failed Items :</b> <code>{fail_count}</code>\n"
            f"📢 <b>Target Channel :</b> <code>{channel_id}</code>\n\n"
            f"⚡ <i>All videos and notes have been delivered to your channel.</i>"
        )
        try:
            await dashboard_msg.edit_text(fin_text)
            await client.send_message(chat_id=channel_id, text=fin_text)
        except Exception:
            pass

    except Exception as e:
        print(f"❌ Fatal PWThor processing error: {e}")
        try:
            await status_msg.edit_text(f"❌ **Fatal Engine Error:** `{e}`")
        except Exception:
            pass
    finally:
        # Remove temporary json file
        try:
            if os.path.exists(json_path):
                os.remove(json_path)
        except Exception:
            pass
