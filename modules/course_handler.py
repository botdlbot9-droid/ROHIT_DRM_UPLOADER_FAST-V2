# modules/course_handler.py
import asyncio
import json
import os
import time
import requests
import re
import subprocess
from pyrogram import Client
from pyrogram.types import Message

# Maximum retries for each video
MAX_RETRIES = 5

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
#  🔥 IMPROVED: download_pw_video with segment handling
# ============================================================
async def download_pw_video(url: str, name: str, quality: str = '720') -> str:
    """
    Improved downloader with proper segment handling.
    """
    try:
        print(f"🎬 Downloading PW video: {name}")
        print(f"🔗 URL: {url[:150]}...")
        print(f"📺 Quality: {quality}p")
        
        if not url or not url.startswith('http'):
            raise Exception(f"Invalid URL: {url}")
        
        # ============================================================
        #  METHOD 1: ffmpeg direct download (MOST RELIABLE for m3u8)
        # ============================================================
        print("🔄 Trying ffmpeg direct download (most reliable)...")
        
        # ✅ IMPROVED: ffmpeg with complete segment handling
        ffmpeg_cmd = (
            f'ffmpeg -y '
            f'-user_agent "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36" '
            f'-reconnect 1 '
            f'-reconnect_streamed 1 '
            f'-reconnect_delay_max 5 '
            f'-i "{url}" '
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
        stdout, stderr = await process.communicate(timeout=600)  # 10 minutes
        
        # ✅ Check if download was successful
        if os.path.exists(f'{name}.mp4'):
            file_size = os.path.getsize(f'{name}.mp4')
            if file_size > 100000:  # At least 100KB
                is_valid = await verify_video_integrity(f'{name}.mp4')
                if is_valid:
                    print(f"✅ ffmpeg successful: {file_size} bytes")
                    return f'{name}.mp4'
                else:
                    print(f"⚠️ Video corrupted, removing...")
                    os.remove(f'{name}.mp4')
            else:
                print(f"⚠️ File too small: {file_size} bytes")
                os.remove(f'{name}.mp4')
        
        # ============================================================
        #  METHOD 2: yt-dlp with better segment handling
        # ============================================================
        print("🔄 Trying yt-dlp with segment handling...")
        
        cmd = [
            'yt-dlp',
            '-f', f'bestvideo[height<={quality}]+bestaudio/best[height<={quality}]/best',
            '--merge-output-format', 'mp4',
            '--allow-unplayable-format',
            '--no-check-certificate',
            '--concurrent-fragments', '5',  # ✅ Less concurrent for stability
            '--retries', '99',  # ✅ More retries
            '--fragment-retries', '99',  # ✅ More fragment retries
            '--http-chunk-size', '5M',  # ✅ Smaller chunk size
            '--buffer-size', '32K',
            '--no-warnings',
            '--no-cache-dir',
            '--force-generic-extractor',
            '--hls-prefer-ffmpeg',  # ✅ Use ffmpeg for HLS
            '--downloader', 'ffmpeg',  # ✅ Use ffmpeg as downloader
            '--abort-on-unavailable-fragment',  # ✅ Abort if fragment missing
            '--fragment-retries', '99',
            '--skip-unavailable-fragments',  # ✅ Skip missing fragments
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
            if file_size > 100000:
                is_valid = await verify_video_integrity(f'{name}.mp4')
                if is_valid:
                    print(f"✅ yt-dlp successful: {file_size} bytes")
                    return f'{name}.mp4'
                else:
                    os.remove(f'{name}.mp4')
        
        # ============================================================
        #  METHOD 3: Simple wget/curl (last resort)
        # ============================================================
        print("🔄 Trying wget fallback...")
        wget_cmd = f'wget -O "{name}.mp4" --timeout=300 --tries=10 --retry-connrefused "{url}"'
        process = await asyncio.create_subprocess_shell(wget_cmd)
        await process.wait()
        
        if os.path.exists(f'{name}.mp4'):
            file_size = os.path.getsize(f'{name}.mp4')
            if file_size > 100000:
                is_valid = await verify_video_integrity(f'{name}.mp4')
                if is_valid:
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
                file_size = os.path.getsize(f'{base_name}{ext}')
                if file_size > 100000:
                    is_valid = await verify_video_integrity(f'{base_name}{ext}')
                    if is_valid:
                        return f'{base_name}{ext}'
                    else:
                        os.remove(f'{base_name}{ext}')
        
        return None
        
    except Exception as e:
        print(f"❌ PW video download error: {e}")
        return None

# ============================================================
#  🔥 NEW: Verify video integrity using ffprobe
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
            if duration > 1:  # ✅ At least 1 second
                print(f"✅ Video verified: {duration:.2f} seconds")
                return True
        
        return False
        
    except Exception as e:
        print(f"⚠️ Video verification failed: {e}")
        return False

# ============================================================
#  🔥 IMPROVED: download_and_upload_video with retry
# ============================================================
async def download_and_upload_video(video_url: str, message: Message, client: Client, quality: str, batch_name: str, channel_id: int, index: int, title: str):
    """
    Download video and upload to channel with improved retry logic.
    """
    os.makedirs("temp_downloads", exist_ok=True)
    filename = f"temp_downloads/video_{int(time.time())}_{index}"
    
    for attempt in range(1, MAX_RETRIES + 1):
        try:
            print(f"🔄 Attempt {attempt}/{MAX_RETRIES} for {title}")
            
            # Download video with improved function
            downloaded_file = await download_pw_video(video_url, filename, quality)
            
            if not downloaded_file or not os.path.exists(downloaded_file):
                raise Exception("Download failed or file not found")
            
            # ✅ Verify file size
            file_size = os.path.getsize(downloaded_file)
            if file_size < 100000:  # Less than 100KB
                raise Exception(f"File too small: {file_size} bytes")
            
            # ✅ Verify video integrity again before upload
            is_valid = await verify_video_integrity(downloaded_file)
            if not is_valid:
                raise Exception("Video verification failed - corrupted file")
            
            # ✅ Prepare caption
            caption = (
                f"<b>🏷️ Index :</b> {str(index).zfill(3)}\n\n"
                f"<b>📑 Title :</b> {title}\n\n"
                f"<blockquote>📚 Batch : {batch_name}</blockquote>\n\n"
                f"<b>📺 Quality :</b> {quality}p"
            )
            
            # ✅ Upload to channel
            await client.send_video(
                chat_id=channel_id,
                video=downloaded_file,
                caption=caption,
                supports_streaming=True
            )
            
            # Cleanup
            if os.path.exists(downloaded_file):
                os.remove(downloaded_file)
            
            print(f"✅ Upload successful for {title}")
            return True
            
        except Exception as e:
            print(f"❌ Attempt {attempt} failed for {title}: {str(e)}")
            
            # ✅ Cleanup on failure
            if os.path.exists(f'{filename}.mp4'):
                os.remove(f'{filename}.mp4')
            
            if attempt == MAX_RETRIES:
                raise Exception(f"Failed after {MAX_RETRIES} attempts: {str(e)}")
            
            # ✅ Exponential backoff with jitter
            wait_time = min(2 ** attempt + (attempt * 2), 60)
            print(f"⏳ Waiting {wait_time} seconds before retry...")
            await asyncio.sleep(wait_time)
    
    return False

async def process_course_and_upload(client: Client, message: Message, json_path: str, auth_string: str, quality: str = '720', batch_name: str = "Unknown Batch", channel_id: int = None):
    """
    Main workflow with all features and improved error handling.
    """
    
    await message.reply_text(f"🔄 Processing course data...\n📺 Quality: {quality}p\n📛 Batch: {batch_name}")
    
    try:
        # Parse JSON
        with open(json_path, 'r', encoding='utf-8') as f:
            course_data = json.load(f)
        
        # Decrypt Auth
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
        
        # Extract Batch ID
        batch_id = course_data.get('batch', {}).get('id')
        if not batch_id:
            raise ValueError("JSON does not contain 'batch.id'.")
        
        # Count total videos
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
        
        # Process each video
        success_count = 0
        fail_count = 0
        failed_videos = []
        
        for idx, video_info in enumerate(video_list, start=1):
            video_id = video_info['video_id']
            title = video_info['title']
            
            status_msg = await message.reply_text(f"🔄 Processing {idx}/{total_videos}: {title[:50]}...")
            
            try:
                # Generate URL with current quality
                video_url = await generate_video_url(batch_id, video_id, token, random_id, quality)
                
                # Download and upload with retry
                await download_and_upload_video(
                    video_url, message, client, quality, 
                    batch_name, channel_id, idx, title
                )
                
                success_count += 1
                await status_msg.edit_text(f"✅ {idx}/{total_videos}: {title[:50]} - Success!")
                
            except Exception as e:
                fail_count += 1
                failed_videos.append(f"#{idx} - {title[:30]}... - {str(e)[:30]}")
                await status_msg.edit_text(f"❌ {idx}/{total_videos}: {title[:50]} - Failed: {str(e)[:50]}")
            
            # Delay between videos
            await asyncio.sleep(3)  # ✅ Increased delay
        
        # Final summary
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
