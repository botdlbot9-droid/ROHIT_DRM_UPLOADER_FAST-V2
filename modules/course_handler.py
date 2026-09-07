# modules/course_handler.py
import asyncio
import json
import os
import time
import requests
import re
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
        
        # Parse JSON response
        data = response.json()
        print(f"📡 API Response: {data}")
        
        # Check response format
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

async def download_pw_video(url: str, name: str, quality: str = '720') -> str:
    """
    Specialized downloader for PW videos using direct m3u8 links.
    Downloads in 720p quality by default.
    """
    try:
        print(f"🎬 Downloading PW video: {name}")
        print(f"🔗 URL: {url[:150]}...")
        print(f"📺 Quality: {quality}p")
        
        if not url or not url.startswith('http'):
            raise Exception(f"Invalid URL: {url}")
        
        # ============================================================
        #  METHOD 1: yt-dlp with 720p preference
        # ============================================================
        format_options = [
            f'bestvideo[height<={quality}]+bestaudio/best[height<={quality}]/best',
            'bestvideo[height<=720]+bestaudio/best[height<=720]/best',
            'bestvideo+bestaudio',
            'best',
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
        #  Check for any downloaded file
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

async def download_and_upload_video(video_url: str, message: Message, client: Client, quality: str, batch_name: str, channel_id: int, index: int, title: str):
    """
    Download video and upload to channel with retry logic
    """
    os.makedirs("temp_downloads", exist_ok=True)
    filename = f"temp_downloads/video_{int(time.time())}_{index}"
    
    # Retry loop
    for attempt in range(1, MAX_RETRIES + 1):
        try:
            print(f"🔄 Attempt {attempt}/{MAX_RETRIES} for {title}")
            
            # Download video
            downloaded_file = await download_pw_video(video_url, filename, quality)
            
            if not downloaded_file or not os.path.exists(downloaded_file):
                raise Exception("Download failed")
            
            # Prepare caption with Index, Title, Batch Name, Quality
            caption = (
                f"<b>🏷️ Index :</b> {str(index).zfill(3)}\n\n"
                f"<b>📑 Title :</b> {title}\n\n"
                f"<blockquote>📚 Batch : {batch_name}</blockquote>\n\n"
                f"<b>📺 Quality :</b> {quality}p"
            )
            
            # Upload to channel
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
            return True  # Success
            
        except Exception as e:
            print(f"❌ Attempt {attempt} failed for {title}: {str(e)}")
            
            # If this was the last attempt, raise exception
            if attempt == MAX_RETRIES:
                raise Exception(f"Failed after {MAX_RETRIES} attempts: {str(e)}")
            
            # Wait before retry (exponential backoff)
            await asyncio.sleep(2 ** attempt)
    
    return False

async def process_course_and_upload(client: Client, message: Message, json_path: str, auth_string: str, quality: str = '720', batch_name: str = "Unknown Batch", channel_id: int = None):
    """
    Main workflow with all new features
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
                await status_msg.edit_text(f"❌ {idx}/{total_videos}: {title[:50]} - Failed: {str(e)[:50]}")
            
            # Delay between videos
            await asyncio.sleep(2)
        
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
        await message.reply_text(summary)
        
    except Exception as e:
        await message.reply_text(f"❌ An error occurred: {str(e)}")
    finally:
        if os.path.exists(json_path):
            os.remove(json_path)
