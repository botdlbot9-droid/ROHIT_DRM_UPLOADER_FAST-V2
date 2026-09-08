# modules/course_handler.py
import asyncio
import json
import os
import time
import requests
import re
import subprocess
import aiohttp
import aiofiles
from pyrogram import Client
from pyrogram.types import Message
from db import db

MAX_RETRIES = 5

# ============================================================
#  🔥 API URL GENERATOR
# ============================================================
async def generate_video_url(batch_id: str, video_id: str, token: str, random_id: str, quality: str = '720') -> str:
    """
    Generate video URL using PW API
    API: https://pw-vid-url.quiz-book.workers.dev/
    """
    api_url = f"https://pw-vid-url.quiz-book.workers.dev/?parentId={batch_id}&childId={video_id}&quality={quality}&token={token}&randomid={random_id}"
    print(f"📡 API Request: {api_url[:200]}...")
    
    try:
        response = requests.get(api_url, timeout=30)
        print(f"📡 Response Status: {response.status_code}")
        
        data = response.json()
        print(f"📡 API Response: {data}")
        
        if data.get('success') and data.get('url'):
            video_url = data.get('url')
            if video_url.startswith('http'):
                return video_url
            else:
                raise Exception(f"Invalid URL from API: {video_url}")
        else:
            error_msg = data.get('error', 'Unknown error')
            raise Exception(f"API error: {error_msg}")
            
    except requests.exceptions.Timeout:
        raise Exception("API request timeout")
    except requests.exceptions.ConnectionError:
        raise Exception("API connection failed")
    except Exception as e:
        raise Exception(f"API request failed: {str(e)}")

# ============================================================
#  🔥 EXTRACT MASTER M3U8 URL FROM PLAYLIST
# ============================================================
def extract_master_m3u8_from_playlist(m3u8_content: str) -> str:
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
        print(f"📥 Fetching playlist from: {video_url[:100]}...")
        
        async with aiohttp.ClientSession() as session:
            async with session.get(video_url, timeout=30) as response:
                if response.status == 200:
                    content = await response.text()
                    print(f"📄 Playlist content length: {len(content)} bytes")
                    
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
#  🔥 DOWNLOAD VIA ASMULTIVERSE API (FIXED - NO TIMEOUT)
# ============================================================
async def download_via_asmultiverse(video_url: str, name: str) -> str:
    """
    Download video using asmultiverse API
    """
    try:
        encoded_url = requests.utils.quote(video_url, safe='')
        download_url = f"https://download.asmultiverse.com?Vurl={encoded_url}"
        
        print(f"📥 Downloading via asmultiverse: {download_url[:100]}...")
        
        output_file = f"{name}.mp4"
        
        cmd = [
            'yt-dlp',
            '-f', 'best',
            '--merge-output-format', 'mp4',
            '--allow-unplayable-format',
            '--no-check-certificate',
            '--retries', '50',
            '--fragment-retries', '50',
            '--http-chunk-size', '10M',
            '--buffer-size', '32K',
            '--no-warnings',
            '-o', output_file,
            download_url
        ]
        
        process = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE
        )
        
        # ✅ FIX: No timeout in communicate()
        stdout, stderr = await process.communicate()
        
        if process.returncode == 0 and os.path.exists(output_file):
            file_size = os.path.getsize(output_file)
            if file_size > 100000:
                print(f"✅ Downloaded via asmultiverse: {file_size} bytes")
                return output_file
            else:
                os.remove(output_file)
        
        return None
        
    except Exception as e:
        print(f"❌ asmultiverse download error: {e}")
        return None

# ============================================================
#  🔥 DOWNLOAD WITH FFMPEG (FIXED - NO TIMEOUT)
# ============================================================
async def download_with_ffmpeg(video_url: str, name: str) -> str:
    """
    Download video using ffmpeg
    """
    try:
        print("🔄 Trying ffmpeg direct download...")
        
        ffmpeg_cmd = (
            f'ffmpeg -y '
            f'-user_agent "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36" '
            f'-reconnect 1 '
            f'-reconnect_streamed 1 '
            f'-reconnect_delay_max 5 '
            f'-i "{video_url}" '
            f'-c copy '
            f'-bsf:a aac_adtstoasc '
            f'-movflags +faststart '
            f'-err_detect ignore_err '
            f'-max_muxing_queue_size 9999 '
            f'-threads 4 '
            f'"{name}.mp4"'
        )
        
        process = await asyncio.create_subprocess_shell(
            ffmpeg_cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE
        )
        
        # ✅ FIX: No timeout in communicate()
        stdout, stderr = await process.communicate()
        
        if os.path.exists(f'{name}.mp4'):
            file_size = os.path.getsize(f'{name}.mp4')
            if file_size > 100000:
                is_valid = await verify_video_integrity(f'{name}.mp4')
                if is_valid:
                    print(f"✅ ffmpeg successful: {file_size} bytes")
                    return f'{name}.mp4'
                else:
                    os.remove(f'{name}.mp4')
            else:
                os.remove(f'{name}.mp4')
        
        return None
        
    except Exception as e:
        print(f"❌ ffmpeg download error: {e}")
        return None

# ============================================================
#  🔥 DOWNLOAD WITH YT-DLP (FIXED - NO TIMEOUT)
# ============================================================
async def download_with_ytdlp(video_url: str, name: str, quality: str = '720') -> str:
    """
    Download video using yt-dlp
    """
    try:
        print("🔄 Trying yt-dlp...")
        
        cmd = [
            'yt-dlp',
            '-f', f'bestvideo[height<={quality}]+bestaudio/best[height<={quality}]/best',
            '--merge-output-format', 'mp4',
            '--allow-unplayable-format',
            '--no-check-certificate',
            '--concurrent-fragments', '10',
            '--retries', '50',
            '--fragment-retries', '50',
            '--http-chunk-size', '5M',
            '--buffer-size', '32K',
            '--no-warnings',
            '--no-cache-dir',
            '--hls-prefer-ffmpeg',
            '--downloader', 'ffmpeg',
            '-o', f'{name}.mp4',
            video_url
        ]
        
        process = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE
        )
        
        # ✅ FIX: No timeout in communicate()
        stdout, stderr = await process.communicate()
        
        if process.returncode == 0 and os.path.exists(f'{name}.mp4'):
            file_size = os.path.getsize(f'{name}.mp4')
            if file_size > 100000:
                is_valid = await verify_video_integrity(f'{name}.mp4')
                if is_valid:
                    print(f"✅ yt-dlp successful: {file_size} bytes")
                    return f'{name}.mp4'
                else:
                    os.remove(f'{name}.mp4')
        
        return None
        
    except Exception as e:
        print(f"❌ yt-dlp download error: {e}")
        return None

# ============================================================
#  🔥 VIDEO INTEGRITY VERIFICATION
# ============================================================
async def verify_video_integrity(file_path: str) -> bool:
    """
    Verify if video is complete and playable using ffprobe.
    """
    try:
        cmd = [
            'ffprobe',
            '-v', 'error',
            '-show_entries', 'format=duration',
            '-of', 'default=noprint_wrappers=1:nokey=1',
            file_path
        ]
        
        process = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE
        )
        stdout, stderr = await process.communicate(timeout=30)
        
        if process.returncode == 0 and stdout:
            duration = float(stdout.decode().strip())
            if duration > 1:
                print(f"✅ Video verified: {duration:.2f} seconds")
                return True
        
        return False
        
    except Exception as e:
        print(f"⚠️ Video verification failed: {e}")
        return False

# ============================================================
#  🔥 MAIN DOWNLOAD FUNCTION (UPDATED)
# ============================================================
async def download_pw_video(video_id: str, url: str, name: str, quality: str = '720') -> str:
    """
    PW video downloader with master.m3u8 extraction and asmultiverse support.
    """
    try:
        print(f"🎬 Downloading PW video: {name}")
        print(f"🔗 URL: {url[:150]}...")
        print(f"📺 Quality: {quality}p")
        
        if not url or not url.startswith('http'):
            raise Exception(f"Invalid URL: {url}")
        
        db.update_video_status(video_id, 'downloading')
        
        # ============================================================
        #  STEP 1: Get master.m3u8 from the playlist
        # ============================================================
        master_url = await get_master_m3u8_from_api(url)
        
        if master_url and master_url != url:
            print(f"✅ Using master.m3u8: {master_url[:100]}...")
            video_url_to_download = master_url
        else:
            print(f"🔄 Using original URL")
            video_url_to_download = url
        
        # ============================================================
        #  STEP 2: Try asmultiverse API first
        # ============================================================
        print("🔄 Trying asmultiverse API download...")
        result = await download_via_asmultiverse(video_url_to_download, name)
        
        if result:
            db.update_video_status(video_id, 'downloaded', result)
            return result
        
        # ============================================================
        #  STEP 3: Fallback to ffmpeg direct download
        # ============================================================
        result = await download_with_ffmpeg(video_url_to_download, name)
        
        if result:
            db.update_video_status(video_id, 'downloaded', result)
            return result
        
        # ============================================================
        #  STEP 4: Fallback to yt-dlp
        # ============================================================
        result = await download_with_ytdlp(video_url_to_download, name, quality)
        
        if result:
            db.update_video_status(video_id, 'downloaded', result)
            return result
        
        db.update_video_status(video_id, 'failed')
        return None
        
    except Exception as e:
        print(f"❌ PW video download error: {e}")
        db.update_video_status(video_id, 'failed')
        return None

# ============================================================
#  🔥 DOWNLOAD AND UPLOAD WITH RETRY
# ============================================================
async def download_and_upload_video(video_url: str, message: Message, client: Client, quality: str, batch_name: str, channel_id: int, index: int, video_id: str, title: str):
    """
    Download video and upload to channel with retry.
    """
    os.makedirs("temp_downloads", exist_ok=True)
    filename = f"temp_downloads/video_{video_id}_{int(time.time())}"
    
    db.add_video(video_id, {
        'title': title,
        'batch_name': batch_name,
        'quality': quality,
        'index': index,
        'video_url': video_url
    })
    
    for attempt in range(1, MAX_RETRIES + 1):
        try:
            print(f"🔄 Attempt {attempt}/{MAX_RETRIES} for {title}")
            
            downloaded_file = await download_pw_video(video_id, video_url, filename, quality)
            
            if not downloaded_file or not os.path.exists(downloaded_file):
                raise Exception("Download failed or file not found")
            
            file_size = os.path.getsize(downloaded_file)
            if file_size < 100000:
                raise Exception(f"File too small: {file_size} bytes")
            
            is_valid = await verify_video_integrity(downloaded_file)
            if not is_valid:
                raise Exception("Video verification failed - corrupted file")
            
            caption = (
                f"<b>🏷️ Index :</b> {str(index).zfill(3)}\n\n"
                f"<b>📑 Title :</b> {title}\n\n"
                f"<blockquote>📚 Batch : {batch_name}</blockquote>\n\n"
                f"<b>📺 Quality :</b> {quality}p"
            )
            
            await client.send_video(
                chat_id=channel_id,
                video=downloaded_file,
                caption=caption,
                supports_streaming=True
            )
            
            db.update_video_status(video_id, 'uploaded')
            db.mark_video_completed(video_id)
            
            if os.path.exists(downloaded_file):
                os.remove(downloaded_file)
            
            print(f"✅ Upload successful for {title}")
            return True
            
        except Exception as e:
            print(f"❌ Attempt {attempt} failed for {title}: {str(e)}")
            
            if os.path.exists(f'{filename}.mp4'):
                os.remove(f'{filename}.mp4')
            
            if attempt == MAX_RETRIES:
                db.update_video_status(video_id, 'failed')
                raise Exception(f"Failed after {MAX_RETRIES} attempts: {str(e)}")
            
            wait_time = min(2 ** attempt + (attempt * 2), 60)
            print(f"⏳ Waiting {wait_time} seconds before retry...")
            await asyncio.sleep(wait_time)
    
    return False

# ============================================================
#  🔥 MAIN COURSE PROCESSING
# ============================================================
async def process_course_and_upload(client: Client, message: Message, json_path: str, auth_string: str, quality: str = '720', batch_name: str = "Unknown Batch", channel_id: int = None):
    """
    Main workflow with all features and database tracking.
    """
    
    await message.reply_text(f"🔄 Processing course data...\n📺 Quality: {quality}p\n📛 Batch: {batch_name}")
    
    try:
        with open(json_path, 'r', encoding='utf-8') as f:
            course_data = json.load(f)
        
        try:
            from .decryption_utils import decrypt_auth_string
            auth_data = await decrypt_auth_string(auth_string)
            token = auth_data.get('token')
            random_id = auth_data.get('randomId')
        except Exception as e:
            await message.reply_text(f"❌ Decryption failed: {str(e)}")
            return
        
        if not token or not random_id:
            raise ValueError("Auth decryption failed: Missing token or randomId.")
        
        batch_id = course_data.get('batch', {}).get('id')
        if not batch_id:
            raise ValueError("JSON does not contain 'batch.id'.")
        
        total_videos = 0
        video_list = []
        for subject in course_data.get('subjects', []):
            for topic in subject.get('topics', []):
                for lecture in topic.get('lectures', []):
                    if lecture.get('videoId'):
                        total_videos += 1
                        video_list.append({
                            'video_id': lecture.get('videoId'),
                            'title': lecture.get('title', f'Video {total_videos}')
                        })
        
        if total_videos == 0:
            await message.reply_text("⚠️ No videos found in the provided JSON.")
            return
        
        await message.reply_text(f"📽️ Found {total_videos} videos. Starting download and upload to channel `{channel_id}`...")
        
        success_count = 0
        fail_count = 0
        failed_videos = []
        
        for idx, video_info in enumerate(video_list, start=1):
            video_id = video_info['video_id']
            title = video_info['title']
            
            status_msg = await message.reply_text(f"🔄 Processing {idx}/{total_videos}: {title[:50]}...")
            
            try:
                video_url = await generate_video_url(batch_id, video_id, token, random_id, quality)
                
                await download_and_upload_video(
                    video_url, message, client, quality, 
                    batch_name, channel_id, idx, video_id, title
                )
                
                success_count += 1
                await status_msg.edit_text(f"✅ {idx}/{total_videos}: {title[:50]} - Success!")
                
            except Exception as e:
                fail_count += 1
                failed_videos.append(f"#{idx} - {title[:30]}... - {str(e)[:30]}")
                await status_msg.edit_text(f"❌ {idx}/{total_videos}: {title[:50]} - Failed: {str(e)[:50]}")
            
            await asyncio.sleep(2)
        
        summary = (
            f"✅ **Process Complete!**\n\n"
            f"📚 Batch: {batch_name}\n"
            f"📺 Quality: {quality}p\n"
            f"📢 Channel: `{channel_id}`\n\n"
            f"✅ Success: {success_count}\n"
            f"❌ Failed: {fail_count}\n"
            f"📊 Total: {total_videos}"
        )
        
        if failed_videos:
            summary += f"\n\n**❌ Failed Videos:**\n" + "\n".join(failed_videos[:10])
        
        await message.reply_text(summary)
        
    except Exception as e:
        await message.reply_text(f"❌ An error occurred: {str(e)}")
    finally:
        if os.path.exists(json_path):
            os.remove(json_path)
