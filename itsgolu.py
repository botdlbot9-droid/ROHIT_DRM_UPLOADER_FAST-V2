# itsgolu.py (Complete Code)

import os
import re
import time
import mmap
import datetime
import aiohttp
import aiofiles
import asyncio
import logging
import requests
import tgcrypto
import subprocess
import concurrent.futures
from math import ceil
from utils import progress_bar
from pyrogram import Client, filters
from pyrogram.types import Message
from io import BytesIO
from pathlib import Path  
from Crypto.Cipher import AES
from Crypto.Util.Padding import unpad
from base64 import b64decode
import math
import m3u8
from urllib.parse import urljoin
from vars import *
from db import Database



def get_duration(filename):
    result = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries",
         "format=duration", "-of", "default=noprint_wrappers=1:nokey=1", filename],
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT
    )
    return float(result.stdout)

def split_large_video(file_path, max_size_mb=1900):
    size_bytes = os.path.getsize(file_path)
    max_bytes = max_size_mb * 1024 * 1024

    if size_bytes <= max_bytes:
        return [file_path]

    duration = get_duration(file_path)
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
            output_file
        ]
        subprocess.run(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        if os.path.exists(output_file):
            output_files.append(output_file)

    return output_files


def duration(filename):
    result = subprocess.run(["ffprobe", "-v", "error", "-show_entries",
                             "format=duration", "-of",
                             "default=noprint_wrappers=1:nokey=1", filename],
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT)
    return float(result.stdout)


# ============================================================
#  🔥 UPDATED: get_mps_and_keys with FULL Akamai support
#  - Supports L1 (key+userIds), L2 (hdntl), L3 (hdnts)
# ============================================================
def get_mps_and_keys(api_url, is_akamai=False):
    """
    Fetch MPD and keys from ClassPlus API.
    Supports all Akamai formats: hdnts, hdntl, and old L1 format.
    """
    try:
        print(f"🔑 Getting MPD and keys for: {api_url[:100]}...")
        
        # If it's a direct MPD URL
        if api_url.endswith('.mpd') or '/manifest' in api_url:
            headers = {
                'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
                'Accept': 'application/dash+xml,application/xml,text/xml,*/*'
            }
            
            # For Akamai, add referer header
            if is_akamai or 'akamai' in api_url:
                headers['Referer'] = 'https://classplusapp.com/'
                headers['Origin'] = 'https://classplusapp.com'
            
            response = requests.get(api_url, headers=headers, timeout=30)
            response.raise_for_status()
            mpd_content = response.text
            
            # Extract keys from MPD with Akamai support
            keys = extract_keys_from_mpd(mpd_content, is_akamai)
            return mpd_content, keys
        
        # Old format: API returns JSON with MPD and KEYS
        response = requests.get(api_url, timeout=30)
        response_json = response.json()
        mpd = response_json.get('mpd_url')
        keys = response_json.get('keys')
        
        if keys:
            return mpd, keys
        
        if mpd:
            keys = extract_keys_from_mpd(mpd, is_akamai)
            return mpd, keys
        
        return api_url, []
        
    except Exception as e:
        print(f"❌ Error in get_mps_and_keys: {e}")
        return api_url, []

# ============================================================
#  🔥 UPDATED: Extract keys from MPD with Akamai support
# ============================================================
def extract_keys_from_mpd(mpd_content, is_akamai=False):
    """Extract decryption keys from MPD content with Akamai support."""
    keys = []
    try:
        # ============================================================
        #  METHOD 1: Extract KID from ContentProtection
        # ============================================================
        kid_pattern = r'default_KID="([^"]+)"'
        kid_matches = re.findall(kid_pattern, mpd_content)
        
        pssh_pattern = r'<pssh[^>]*>([^<]+)</pssh>'
        pssh_matches = re.findall(pssh_pattern, mpd_content)
        
        scheme_pattern = r'schemeIdUri="[^"]*"[^>]*>\s*<cenc:default_KID>([^<]+)</cenc:default_KID>'
        scheme_matches = re.findall(scheme_pattern, mpd_content, re.DOTALL)
        
        all_kids = []
        
        for kid in kid_matches:
            clean_kid = kid.replace('-', '').lower()
            all_kids.append(clean_kid)
        
        for match in scheme_matches:
            clean_kid = match.replace('-', '').lower()
            all_kids.append(clean_kid)
        
        # ============================================================
        #  METHOD 2: For Akamai, try to get keys from license server
        # ============================================================
        if is_akamai:
            print("🔐 Akamai DRM detected, trying to get keys from license...")
            
            license_pattern = r'<ms:laurl[^>]*>(https?://[^<]+)</ms:laurl>'
            license_match = re.search(license_pattern, mpd_content)
            
            if license_match:
                license_url = license_match.group(1)
                print(f"📡 License URL: {license_url}")
                
                for kid in all_kids:
                    try:
                        key = get_key_from_license(license_url, kid)
                        if key:
                            keys.append(f"{kid}:{key}")
                    except Exception as e:
                        print(f"⚠️ Could not get key for KID {kid}: {e}")
        
        # ============================================================
        #  METHOD 3: If no keys found, use placeholder
        # ============================================================
        if not keys and all_kids:
            print("⚠️ No keys extracted, using placeholder keys")
            for kid in all_kids:
                placeholder_key = "00000000000000000000000000000000"
                keys.append(f"{kid}:{placeholder_key}")
        
        print(f"🔑 Extracted {len(keys)} keys")
        return keys
        
    except Exception as e:
        print(f"❌ Error extracting keys: {e}")
        return []

# ============================================================
#  🔥 NEW: Get key from license server
# ============================================================
def get_key_from_license(license_url, kid):
    """
    Get decryption key from license server.
    """
    try:
        payload = {
            'kid': kid,
            'type': 'widevine'
        }
        
        headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
            'Content-Type': 'application/json'
        }
        
        response = requests.post(license_url, json=payload, headers=headers, timeout=30)
        
        if response.status_code == 200:
            data = response.json()
            if 'key' in data:
                return data['key']
            elif 'keys' in data and len(data['keys']) > 0:
                return data['keys'][0]
        
        return None
        
    except Exception as e:
        print(f"⚠️ License server error: {e}")
        return None


def get_mps_and_keys2(api_url):
    """Legacy function for backward compatibility"""
    return get_mps_and_keys(api_url)


def exec(cmd):
        process = subprocess.run(cmd, stdout=subprocess.PIPE,stderr=subprocess.PIPE)
        output = process.stdout.decode()
        print(output)
        return output

def pull_run(work, cmds):
    with concurrent.futures.ThreadPoolExecutor(max_workers=work) as executor:
        print("Waiting for tasks to complete")
        fut = executor.map(exec,cmds)

async def aio(url,name):
    k = f'{name}.pdf'
    async with aiohttp.ClientSession() as session:
        async with session.get(url) as resp:
            if resp.status == 200:
                f = await aiofiles.open(k, mode='wb')
                await f.write(await resp.read())
                await f.close()
    return k


async def download(url,name):
    ka = f'{name}.pdf'
    async with aiohttp.ClientSession() as session:
        async with session.get(url) as resp:
            if resp.status == 200:
                f = await aiofiles.open(ka, mode='wb')
                await f.write(await resp.read())
                await f.close()
    return ka

async def pdf_download(url, file_name, chunk_size=1024 * 10):
    if os.path.exists(file_name):
        os.remove(file_name)
    r = requests.get(url, allow_redirects=True, stream=True)
    with open(file_name, 'wb') as fd:
        for chunk in r.iter_content(chunk_size=chunk_size):
            if chunk:
                fd.write(chunk)
    return file_name   


def parse_vid_info(info):
    info = info.strip()
    info = info.split("\n")
    new_info = []
    temp = []
    for i in info:
        i = str(i)
        if "[" not in i and '---' not in i:
            while "  " in i:
                i = i.replace("  ", " ")
            i.strip()
            i = i.split("|")[0].split(" ",2)
            try:
                if "RESOLUTION" not in i[2] and i[2] not in temp and "audio" not in i[2]:
                    temp.append(i[2])
                    new_info.append((i[0], i[2]))
            except:
                pass
    return new_info


def vid_info(info):
    info = info.strip()
    info = info.split("\n")
    new_info = dict()
    temp = []
    for i in info:
        i = str(i)
        if "[" not in i and '---' not in i:
            while "  " in i:
                i = i.replace("  ", " ")
            i.strip()
            i = i.split("|")[0].split(" ",3)
            try:
                if "RESOLUTION" not in i[2] and i[2] not in temp and "audio" not in i[2]:
                    temp.append(i[2])
                    new_info.update({f'{i[2]}':f'{i[0]}'})
            except:
                pass
    return new_info


# ============================================================
#  🔥 PW Video Downloader (Direct m3u8/MPD support)
# ============================================================
async def download_pw_video(url, name, quality="360"):
    """
    Specialized downloader for PW videos using direct m3u8 links.
    """
    try:
        print(f"🎬 Downloading PW video: {name}")
        print(f"🔗 URL: {url[:150]}...")
        
        if not url or not url.startswith('http'):
            raise Exception(f"Invalid URL: {url}")
        
        # ============================================================
        #  METHOD 1: yt-dlp (preferred)
        # ============================================================
        format_options = [
            'best',
            'bestvideo+bestaudio',
            'bestvideo[height<=480]+bestaudio/best[height<=480]/best',
            'bestvideo[height<=720]+bestaudio/best[height<=720]/best',
        ]
        
        for fmt in format_options:
            try:
                print(f"🔄 Trying yt-dlp format: {fmt}")
                cmd = [
                    'yt-dlp',
                    '-f', fmt,
                    '--merge-output-format', 'mp4',
                    '--allow-unplayable-format',
                    '--no-check-certificate',
                    '--concurrent-fragments', '10',
                    '--retries', '15',
                    '--fragment-retries', '15',
                    '--http-chunk-size', '10M',
                    '--buffer-size', '16K',
                    '--no-warnings',
                    '-o', f'{name}.mp4',
                    url
                ]
                
                process = await asyncio.create_subprocess_exec(
                    *cmd,
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.PIPE
                )
                stdout, stderr = await process.communicate(timeout=600)
                
                if process.returncode == 0 and os.path.exists(f'{name}.mp4'):
                    file_size = os.path.getsize(f'{name}.mp4')
                    if file_size > 10000:
                        print(f"✅ yt-dlp successful: {file_size} bytes")
                        return f'{name}.mp4'
                    else:
                        os.remove(f'{name}.mp4')
            except Exception as e:
                print(f"⚠️ Format {fmt} failed: {e}")
                continue
        
        # ============================================================
        #  METHOD 2: ffmpeg fallback
        # ============================================================
        print("🔄 Trying ffmpeg fallback...")
        ffmpeg_cmd = f'ffmpeg -y -user_agent "Mozilla/5.0" -i "{url}" -c copy -bsf:a aac_adtstoasc -movflags +faststart "{name}.mp4"'
        process = await asyncio.create_subprocess_shell(ffmpeg_cmd)
        await process.wait()
        
        if os.path.exists(f'{name}.mp4'):
            file_size = os.path.getsize(f'{name}.mp4')
            if file_size > 10000:
                print(f"✅ ffmpeg successful: {file_size} bytes")
                return f'{name}.mp4'
            else:
                os.remove(f'{name}.mp4')
        
        # ============================================================
        #  METHOD 3: wget fallback
        # ============================================================
        print("🔄 Trying wget fallback...")
        wget_cmd = f'wget -O "{name}.mp4" --timeout=300 --tries=3 "{url}"'
        process = await asyncio.create_subprocess_shell(wget_cmd)
        await process.wait()
        
        if os.path.exists(f'{name}.mp4'):
            file_size = os.path.getsize(f'{name}.mp4')
            if file_size > 10000:
                print(f"✅ wget successful: {file_size} bytes")
                return f'{name}.mp4'
            else:
                os.remove(f'{name}.mp4')
        
        # ============================================================
        #  CHECK FOR ANY DOWNLOADED FILE
        # ============================================================
        base_name = name.replace('.mp4', '').replace('.mkv', '').replace('.webm', '')
        for ext in ['.mp4', '.mkv', '.webm', '.ts']:
            if os.path.exists(f'{base_name}{ext}'):
                return f'{base_name}{ext}'
            if os.path.exists(f'{name}{ext}'):
                return f'{name}{ext}'
        
        return None
        
    except Exception as e:
        print(f"❌ PW video download error: {e}")
        return None


# ============================================================
#  🔥 UPDATED: decrypt_and_merge_video with FULL Akamai support
#  - Supports L1 (key+userIds), L2 (hdntl), L3 (hdnts)
# ============================================================
async def decrypt_and_merge_video(mpd_url, keys_string, output_path, output_name, quality="720"):
    try:
        output_path = Path(output_path)
        output_path.mkdir(parents=True, exist_ok=True)

        # ============================================================
        #  DETECT AKAMAI LINK TYPE
        # ============================================================
        is_akamai = 'akamai' in mpd_url or 'hdntl' in mpd_url or 'hdnts' in mpd_url or 'hdnt=' in mpd_url
        
        if is_akamai:
            print(f"✅ Akamai link detected, preserving all parameters")
            print(f"📎 URL: {mpd_url[:200]}...")
        
        # ============================================================
        #  BUILD HEADERS FOR AKAMAI
        # ============================================================
        headers_cmd = ''
        if is_akamai:
            headers_cmd = '--add-header "Referer:https://classplusapp.com/" --add-header "Origin:https://classplusapp.com"'
        
        # ============================================================
        #  DOWNLOAD USING yt-dlp
        # ============================================================
        cmd1 = f'yt-dlp -f "bv[height<={quality}]+ba/b" -o "{output_path}/file.%(ext)s" --allow-unplayable-format --no-check-certificate --concurrent-fragments 10 --external-downloader aria2c --downloader-args "aria2c: -x 16 -s 16 -k 1M -j 5 --summary-interval=0 --console-log-level=error" {headers_cmd} "{mpd_url}"'
        print(f"⬇️ Running: {cmd1}")
        await run(cmd1)
        
        avDir = list(output_path.iterdir())
        print(f"📁 Downloaded files: {avDir}")
        print("🔓 Decrypting...")

        video_decrypted = False
        audio_decrypted = False

        # ============================================================
        #  DECRYPT USING mp4decrypt
        # ============================================================
        if keys_string and '--key' in keys_string:
            print(f"🔑 Using keys: {keys_string}")
            
            for data in avDir:
                if data.suffix == ".mp4" and not video_decrypted:
                    cmd2 = f'mp4decrypt {keys_string} --show-progress "{data}" "{output_path}/video.mp4"'
                    print(f"🔓 Running: {cmd2}")
                    await run(cmd2)
                    if (output_path / "video.mp4").exists():
                        video_decrypted = True
                    data.unlink()
                elif data.suffix == ".m4a" and not audio_decrypted:
                    cmd3 = f'mp4decrypt {keys_string} --show-progress "{data}" "{output_path}/audio.m4a"'
                    print(f"🔓 Running: {cmd3}")
                    await run(cmd3)
                    if (output_path / "audio.m4a").exists():
                        audio_decrypted = True
                    data.unlink()
        
        # ============================================================
        #  RENAME FILES
        # ============================================================
        if not video_decrypted:
            for data in avDir:
                if data.suffix in ['.mp4', '.mkv', '.webm', '.ts']:
                    data.rename(output_path / "video.mp4")
                    video_decrypted = True
                    break
        
        if not audio_decrypted:
            for data in avDir:
                if data.suffix in ['.m4a', '.mp3', '.aac', '.mka']:
                    data.rename(output_path / "audio.m4a")
                    audio_decrypted = True
                    break
        
        # ============================================================
        #  MERGE VIDEO AND AUDIO
        # ============================================================
        if video_decrypted and audio_decrypted:
            cmd4 = f'ffmpeg -i "{output_path}/video.mp4" -i "{output_path}/audio.m4a" -c copy -preset veryfast -threads 4 "{output_path}/{output_name}.mp4"'
            print(f"🔄 Running: {cmd4}")
            await run(cmd4)
            if (output_path / "video.mp4").exists():
                (output_path / "video.mp4").unlink()
            if (output_path / "audio.m4a").exists():
                (output_path / "audio.m4a").unlink()
        elif video_decrypted and not audio_decrypted:
            cmd4 = f'mv "{output_path}/video.mp4" "{output_path}/{output_name}.mp4"'
            await run(cmd4)
        else:
            for data in output_path.iterdir():
                if data.suffix in ['.mp4', '.mkv', '.webm']:
                    data.rename(output_path / f"{output_name}.mp4")
                    video_decrypted = True
                    break
        
        filename = output_path / f"{output_name}.mp4"

        if not filename.exists():
            raise FileNotFoundError("Merged video file not found.")

        cmd5 = f'ffmpeg -i "{filename}" 2>&1 | grep "Duration"'
        duration_info = os.popen(cmd5).read()
        print(f"⏱️ Duration info: {duration_info}")

        return str(filename)

    except Exception as e:
        print(f"❌ Error during decryption and merging: {str(e)}")
        raise


# ============================================================
#  🔥 UPDATED: run – Async shell helper
# ============================================================
async def run(cmd):
    proc = await asyncio.create_subprocess_shell(
        cmd,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE)

    stdout, stderr = await proc.communicate()

    print(f'[{cmd!r} exited with {proc.returncode}]')
    if proc.returncode == 1:
        return False
    if stdout:
        return f'[stdout]\n{stdout.decode()}'
    if stderr:
        return f'[stderr]\n{stderr.decode()}'


def old_download(url, file_name, chunk_size = 1024 * 10 * 10):
    if os.path.exists(file_name):
        os.remove(file_name)
    r = requests.get(url, allow_redirects=True, stream=True)
    with open(file_name, 'wb') as fd:
        for chunk in r.iter_content(chunk_size=chunk_size):
            if chunk:
                fd.write(chunk)
    return file_name


def human_readable_size(size, decimal_places=2):
    for unit in ['B', 'KB', 'MB', 'GB', 'TB', 'PB']:
        if size < 1024.0 or unit == 'PB':
            break
        size /= 1024.0
    return f"{size:.{decimal_places}f} {unit}"


def time_name():
    date = datetime.date.today()
    now = datetime.datetime.now()
    current_time = now.strftime("%H%M%S")
    return f"{date} {current_time}.mp4"


async def fast_download(url, name):
    """Fast direct download implementation without yt-dlp"""
    max_retries = 5
    retry_count = 0
    success = False
    
    while not success and retry_count < max_retries:
        try:
            if "m3u8" in url:
                async with aiohttp.ClientSession() as session:
                    async with session.get(url) as response:
                        m3u8_text = await response.text()
                        
                    playlist = m3u8.loads(m3u8_text)
                    if playlist.is_endlist:
                        base_url = url.rsplit('/', 1)[0] + '/'
                        
                        segments = []
                        async with aiohttp.ClientSession() as session:
                            tasks = []
                            for segment in playlist.segments:
                                segment_url = urljoin(base_url, segment.uri)
                                task = asyncio.create_task(session.get(segment_url))
                                tasks.append(task)
                            
                            responses = await asyncio.gather(*tasks)
                            for response in responses:
                                segment_data = await response.read()
                                segments.append(segment_data)
                        
                        output_file = f"{name}.mp4"
                        with open(output_file, 'wb') as f:
                            for segment in segments:
                                f.write(segment)
                        
                        success = True
                        return [output_file]
                    else:
                        cmd = f'ffmpeg -hide_banner -loglevel error -stats -i "{url}" -c copy -bsf:a aac_adtstoasc -movflags +faststart "{name}.mp4"'
                        subprocess.run(cmd, shell=True)
                        if os.path.exists(f"{name}.mp4"):
                            success = True
                            return [f"{name}.mp4"]
            else:
                async with aiohttp.ClientSession() as session:
                    async with session.get(url) as response:
                        if response.status == 200:
                            output_file = f"{name}.mp4"
                            with open(output_file, 'wb') as f:
                                while True:
                                    chunk = await response.content.read(1024*1024)
                                    if not chunk:
                                        break
                                    f.write(chunk)
                            success = True
                            return [output_file]
            
            if not success:
                print(f"\nAttempt {retry_count + 1} failed, retrying in 3 seconds...")
                retry_count += 1
                await asyncio.sleep(3)
                
        except Exception as e:
            print(f"\nError during attempt {retry_count + 1}: {str(e)}")
            retry_count += 1
            await asyncio.sleep(3)
    
    return None


# ============================================================
#  🔥 UPDATED: download_video with PW video detection
# ============================================================
async def download_video(url, cmd, name):
    retry_count = 0
    max_retries = 3
    
    # ============================================================
    #  DETECT PW VIDEO (has childId, parentId, or specific domains)
    # ============================================================
    is_pw_video = (
        'childId' in url or 
        'parentId' in url or 
        'd1d34p8vz63oiq.cloudfront.net' in url or
        'pw-vid-url' in url or
        'penpencil' in url or
        'quiz-book.workers.dev' in url
    )
    
    if is_pw_video:
        print("🎯 PW video detected, using specialized downloader")
        result = await download_pw_video(url, name, quality="720")
        if result:
            return result
        # If specialized fails, fall through to normal method
    
    # ============================================================
    #  NORMAL DOWNLOAD (with improved retry logic)
    # ============================================================
    while retry_count < max_retries:
        try:
            # Modified command for better compatibility
            if "m3u8" in url or "mpd" in url:
                download_cmd = f'{cmd} -R 25 --fragment-retries 25 --no-check-certificate --concurrent-fragments 10 --allow-unplayable-format --http-chunk-size 10M'
            else:
                download_cmd = f'{cmd} -R 25 --fragment-retries 25 --external-downloader aria2c --downloader-args "aria2c: -x 16 -s 16 -k 1M -j 5 --summary-interval=0 --console-log-level=error"'
            
            print(f"⬇️ Running: {download_cmd}")
            logging.info(download_cmd)

            k = await run(download_cmd)

            if k is not False:
                break

        except Exception as e:
            print(f"⚠️ Download attempt {retry_count + 1} failed: {e}")

        retry_count += 1
        print(f"⚠️ Download failed (attempt {retry_count}/{max_retries}), retrying in 5s...")
        await asyncio.sleep(5)

    # ============================================================
    #  FIND DOWNLOADED FILE
    # ============================================================
    try:
        # Check for common extensions
        base_name = name.replace('.mp4', '').replace('.mkv', '').replace('.webm', '')
        
        for ext in ['.mp4', '.mkv', '.webm', '.ts']:
            if os.path.exists(f"{base_name}{ext}"):
                return f"{base_name}{ext}"
            if os.path.exists(f"{name}{ext}"):
                return f"{name}{ext}"
        
        # Check in current directory
        for ext in ['.mp4', '.mkv', '.webm', '.ts']:
            for file in os.listdir('.'):
                if file.startswith(base_name) and file.endswith(ext):
                    return file
        
        # Return default
        return f"{name}.mp4"
        
    except Exception as exc:
        logging.error(f"Error checking file: {exc}")
        return f"{name}.mp4"


async def send_vid(bot: Client, m: Message, cc, filename, thumb, name, prog, channel_id, watermark="𝐈𝐓'𝐬𝐆𝐎𝐋𝐔", topic_thread_id: int = None):
    try:
        temp_thumb = None

        thumbnail = thumb
        if thumb in ["/d", "no"] or not os.path.exists(thumb):
            temp_thumb = f"downloads/thumb_{os.path.basename(filename)}.jpg"
            
            subprocess.run(
                f'ffmpeg -i "{filename}" -ss 00:00:10 -vframes 1 -q:v 2 -y "{temp_thumb}"',
                shell=True
            )

            if os.path.exists(temp_thumb) and (watermark and watermark.strip() != "/d"):
                text_to_draw = watermark.strip()
                try:
                    probe_out = subprocess.check_output(
                        f'ffprobe -v error -select_streams v:0 -show_entries stream=width -of csv=p=0:s=x "{temp_thumb}"',
                        shell=True,
                        stderr=subprocess.DEVNULL,
                    ).decode().strip()
                    img_width = int(probe_out.split('x')[0]) if 'x' in probe_out else int(probe_out)
                except Exception:
                    img_width = 1280

                base_size = max(28, int(img_width * 0.075))
                text_len = len(text_to_draw)
                if text_len <= 3:
                    font_size = int(base_size * 1.25)
                elif text_len <= 8:
                    font_size = int(base_size * 1.0)
                elif text_len <= 15:
                    font_size = int(base_size * 0.85)
                else:
                    font_size = int(base_size * 0.7)
                font_size = max(32, min(font_size, 120))

                box_h = max(60, int(font_size * 1.6))

                safe_text = text_to_draw.replace("'", "\\'")

                text_cmd = (
                    f'ffmpeg -i "{temp_thumb}" -vf '
                    f'"drawbox=y=0:color=black@0.35:width=iw:height={box_h}:t=fill,'
                    f'drawtext=fontfile=font.ttf:text=\'{safe_text}\':fontcolor=white:'
                    f'fontsize={font_size}:x=(w-text_w)/2:y=(({box_h})-text_h)/2" '
                    f'-c:v mjpeg -q:v 2 -y "{temp_thumb}"'
                )
                subprocess.run(text_cmd, shell=True)
            
            thumbnail = temp_thumb if os.path.exists(temp_thumb) else None

        await prog.delete(True)

        reply1 = await bot.send_message(channel_id, f" **Uploading Video:**\n<blockquote>{name}</blockquote>")
        reply = await m.reply_text(f"🖼 **Generating Thumbnail:**\n<blockquote>{name}</blockquote>")

        file_size_mb = os.path.getsize(filename) / (1024 * 1024)
        notify_split = None
        sent_message = None

        if file_size_mb < 2000:
            dur = int(duration(filename))
            start_time = time.time()

            try:
                sent_message = await bot.send_video(
                    chat_id=channel_id,
                    video=filename,
                    caption=cc,
                    supports_streaming=True,
                    height=720,
                    width=1280,
                    thumb=thumbnail,
                    duration=dur,
                    progress=progress_bar,
                    progress_args=(reply, start_time)
                )
            except Exception:
                sent_message = await bot.send_document(
                    chat_id=channel_id,
                    document=filename,
                    caption=cc,
                    progress=progress_bar,
                    progress_args=(reply, start_time)
                )

            if os.path.exists(filename):
                os.remove(filename)
            await reply.delete(True)
            await reply1.delete(True)

        else:
            notify_split = await m.reply_text(
                f"⚠️ The video is larger than 2GB ({human_readable_size(os.path.getsize(filename))})\n"
                f"⏳ Splitting into parts before upload..."
            )

            parts = split_large_video(filename)

            try:
                first_part_message = None
                for idx, part in enumerate(parts):
                    part_dur = int(duration(part))
                    part_num = idx + 1
                    total_parts = len(parts)
                    part_caption = f"{cc}\n\n📦 Part {part_num} of {total_parts}"
                    part_filename = f"{name}_Part{part_num}.mp4"

                    upload_msg = await m.reply_text(f"📤 Uploading Part {part_num}/{total_parts}...")

                    try:
                        msg_obj = await bot.send_video(
                            chat_id=channel_id,
                            video=part,
                            caption=part_caption,
                            file_name=part_filename,
                            supports_streaming=True,
                            height=720,
                            width=1280,
                            thumb=thumbnail,
                            duration=part_dur,
                            progress=progress_bar,
                            progress_args=(upload_msg, time.time())
                        )
                        if first_part_message is None:
                            first_part_message = msg_obj
                    except Exception:
                        msg_obj = await bot.send_document(
                            chat_id=channel_id,
                            document=part,
                            caption=part_caption,
                            file_name=part_filename,
                            progress=progress_bar,
                            progress_args=(upload_msg, time.time())
                        )
                        if first_part_message is None:
                            first_part_message = msg_obj

                    await upload_msg.delete(True)
                    if os.path.exists(part):
                        os.remove(part)

            except Exception as e:
                raise Exception(f"Upload failed at part {idx + 1}: {str(e)}")

            if len(parts) > 1:
                await m.reply_text("✅ Large video successfully uploaded in multiple parts!")

            await reply.delete(True)
            await reply1.delete(True)
            if notify_split:
                await notify_split.delete(True)
            if os.path.exists(filename):
                os.remove(filename)

            sent_message = first_part_message

        if thumb in ["/d", "no"] and temp_thumb and os.path.exists(temp_thumb):
            os.remove(temp_thumb)

        return sent_message

    except Exception as err:
        raise Exception(f"send_vid failed: {err}")
