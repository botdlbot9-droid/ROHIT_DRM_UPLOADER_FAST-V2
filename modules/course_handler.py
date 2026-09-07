# modules/course_handler.py
import asyncio
import json
import os
import time
import requests
import subprocess
import re
from pyrogram import Client
from pyrogram.types import Message

async def generate_video_url(batch_id: str, video_id: str, token: str, random_id: str, quality: str = '360') -> str:
    """
    PW Video URL Generator - Same as HTML Dashboard
    API: https://pw-vid-url.quiz-book.workers.dev/
    """
    # Build API URL exactly like HTML dashboard
    api_url = f"https://pw-vid-url.quiz-book.workers.dev/?parentId={batch_id}&childId={video_id}&quality={quality}&token={token}&randomid={random_id}"
    
    print(f"📡 API Request: {api_url[:200]}...")
    
    try:
        response = requests.get(api_url, timeout=30)
        print(f"📡 Response Status: {response.status_code}")
        
        # Parse JSON response
        data = response.json()
        print(f"📡 API Response: {data}")
        
        # Check response format (same as HTML dashboard)
        if data.get('success') and data.get('url'):
            video_url = data.get('url')
            print(f"✅ API Success: {video_url}")
            
            # Validate URL
            if not video_url.startswith('http'):
                raise Exception(f"Invalid URL from API: {video_url}")
            
            return video_url
        else:
            error_msg = data.get('error', 'Unknown error')
            raise Exception(f"API error: {error_msg}")
            
    except requests.exceptions.Timeout:
        raise Exception("API request timeout")
    except requests.exceptions.ConnectionError:
        raise Exception("API connection failed")
    except Exception as e:
        raise Exception(f"API request failed: {str(e)}")


async def download_pw_video(url: str, name: str, quality: str = '360') -> str:
    """
    Download PW video from M3U8 URL using yt-dlp
    """
    try:
        print(f"🎬 Downloading PW video: {name}")
        print(f"🔗 URL: {url}")
        
        # ============================================================
        #  METHOD 1: yt-dlp with optimal settings
        # ============================================================
        cmd = [
            'yt-dlp',
            '-f', 'best',
            '--merge-output-format', 'mp4',
            '--allow-unplayable-format',
            '--no-check-certificate',
            '--concurrent-fragments', '10',
            '--retries', '25',
            '--fragment-retries', '25',
            '--http-chunk-size', '10M',
            '--buffer-size', '16K',
            '-o', f'{name}.mp4',
            url
        ]
        
        process = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE
        )
        stdout, stderr = await process.communicate()
        
        if process.returncode == 0:
            if os.path.exists(f'{name}.mp4'):
                file_size = os.path.getsize(f'{name}.mp4')
                if file_size > 1000:
                    print(f"✅ Download successful: {file_size} bytes")
                    return f'{name}.mp4'
        
        # ============================================================
        #  METHOD 2: ffmpeg fallback
        # ============================================================
        print("🔄 Trying ffmpeg fallback...")
        ffmpeg_cmd = f'ffmpeg -y -i "{url}" -c copy -bsf:a aac_adtstoasc -movflags +faststart "{name}.mp4"'
        process = await asyncio.create_subprocess_shell(ffmpeg_cmd)
        await process.wait()
        
        if os.path.exists(f'{name}.mp4'):
            file_size = os.path.getsize(f'{name}.mp4')
            if file_size > 1000:
                print(f"✅ ffmpeg download successful: {file_size} bytes")
                return f'{name}.mp4'
        
        # ============================================================
        #  METHOD 3: wget fallback
        # ============================================================
        print("🔄 Trying wget fallback...")
        wget_cmd = f'wget -O "{name}.mp4" --timeout=300 --tries=3 "{url}"'
        process = await asyncio.create_subprocess_shell(wget_cmd)
        await process.wait()
        
        if os.path.exists(f'{name}.mp4'):
            file_size = os.path.getsize(f'{name}.mp4')
            if file_size > 1000:
                print(f"✅ wget download successful: {file_size} bytes")
                return f'{name}.mp4'
        
        raise Exception("All download methods failed")
        
    except Exception as e:
        print(f"❌ Download error: {e}")
        return None


async def download_and_upload_video(video_url: str, message: Message, client: Client, quality: str = '360'):
    """
    Download video from URL and upload to Telegram
    """
    os.makedirs("temp_downloads", exist_ok=True)
    filename = f"temp_downloads/video_{int(time.time())}"
    
    try:
        # Download video
        downloaded_file = await download_pw_video(video_url, filename, quality)
        
        if not downloaded_file or not os.path.exists(downloaded_file):
            raise Exception("Download failed")
        
        # Upload to Telegram
        await client.send_video(
            chat_id=message.chat.id,
            video=downloaded_file,
            caption=f"✅ **Video Downloaded!**\nQuality: {quality}",
            supports_streaming=True
        )
        
        # Cleanup
        if os.path.exists(downloaded_file):
            os.remove(downloaded_file)
            
    except Exception as e:
        raise Exception(f"Download or upload failed: {str(e)}")
    finally:
        # Cleanup any remaining files
        for ext in ['.mp4', '.mkv', '.webm', '.ts']:
            if os.path.exists(f'{filename}{ext}'):
                os.remove(f'{filename}{ext}')


async def process_course_and_upload(client: Client, message: Message, json_path: str, auth_string: str):
    """
    Main workflow: Parses JSON, decrypts auth, extracts video IDs, and uploads videos.
    """
    await message.reply_text("🔄 Processing course data and decrypting authentication...")
    
    try:
        # 1. Parse JSON
        with open(json_path, 'r', encoding='utf-8') as f:
            course_data = json.load(f)
        
        # 2. Decrypt Auth String
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
        
        # 3. Extract Batch ID
        batch_id = course_data.get('batch', {}).get('id')
        if not batch_id:
            raise ValueError("JSON does not contain 'batch.id'.")
        
        # 4. Count total videos
        total_videos = 0
        for subject in course_data.get('subjects', []):
            for topic in subject.get('topics', []):
                for lecture in topic.get('lectures', []):
                    if lecture.get('videoId'):
                        total_videos += 1
        
        if total_videos == 0:
            await message.reply_text("⚠️ No videos found in the provided JSON.")
            return
        
        await message.reply_text(f"📽️ Found {total_videos} videos. Starting download and upload...")
        
        # 5. Process each video
        video_count = 0
        for subject in course_data.get('subjects', []):
            for topic in subject.get('topics', []):
                for lecture in topic.get('lectures', []):
                    video_id = lecture.get('videoId')
                    if not video_id:
                        continue
                    
                    video_count += 1
                    title = lecture.get('title', video_id)
                    await message.reply_text(f"🔄 Processing video {video_count}/{total_videos}: {title}")
                    
                    try:
                        # Generate URL using API
                        video_url = await generate_video_url(
                            batch_id, video_id, token, random_id, quality='360'
                        )
                        
                        # Download and upload
                        await download_and_upload_video(video_url, message, client, quality='360')
                        
                    except Exception as e:
                        await message.reply_text(f"❌ Error with video {video_id}: {str(e)}")
                    
                    # Delay to avoid rate limits
                    await asyncio.sleep(2)
        
        await message.reply_text(f"✅ **Process Complete!** Processed {total_videos} videos.")
        
    except Exception as e:
        await message.reply_text(f"❌ An error occurred: {str(e)}")
    finally:
        if os.path.exists(json_path):
            os.remove(json_path)
