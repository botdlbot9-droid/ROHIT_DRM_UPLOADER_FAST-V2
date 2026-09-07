# modules/course_handler.py
import asyncio
import json
import os
import time
import requests
import subprocess
from pyrogram import Client, filters
from pyrogram.types import Message
from .decryption_utils import decrypt_auth_string

async def generate_video_url(batch_id: str, video_id: str, token: str, random_id: str, quality: str = '720') -> str:
    """
    Calls the external API to generate a streamable video URL.
    """
    api_url = f"https://pw-vid-url.quiz-book.workers.dev/?parentId={batch_id}&childId={video_id}&quality={quality}&token={token}&randomid={random_id}"
    
    try:
        response = requests.get(api_url, timeout=30)
        data = response.json()
        if data.get('success'):
            return data.get('url')
        else:
            raise Exception(f"API Error: {data.get('error', 'Unknown error')}")
    except Exception as e:
        raise Exception(f"Failed to generate video URL: {str(e)}")

async def download_and_upload_video(video_url: str, message: Message, client: Client, quality: str = '720'):
    """
    Downloads a video from a URL using yt-dlp and uploads it to the Telegram chat.
    """
    filename = f"temp_downloads/video_{quality}_{int(time.time())}.mp4"
    os.makedirs("temp_downloads", exist_ok=True)
    
    # yt-dlp command to download and merge best quality
    cmd = [
        'yt-dlp',
        '-f', 'bestvideo+bestaudio',
        '--merge-output-format', 'mp4',
        '-o', filename,
        video_url
    ]
    
    try:
        # Run the download process
        process = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE
        )
        stdout, stderr = await process.communicate()
        
        if process.returncode != 0:
            raise Exception(f"yt-dlp download failed: {stderr.decode()}")
        
        # Upload the video to Telegram
        await client.send_video(
            chat_id=message.chat.id,
            video=filename,
            caption=f"✅ **Video Downloaded!**\nQuality: {quality}",
            supports_streaming=True
        )
        
    except Exception as e:
        raise Exception(f"Download or upload failed: {str(e)}")
    finally:
        # Clean up the temporary file
        if os.path.exists(filename):
            os.remove(filename)

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
            auth_data = await decrypt_auth_string(auth_string)
            token = auth_data.get('token')
            random_id = auth_data.get('randomId')
        except Exception as e:
            await message.reply_text(f"❌ Decryption failed: {str(e)}")
            return
        
        if not token or not random_id:
            raise ValueError("Auth decryption failed: Missing token or randomId.")
        
        # 3. Extract Batch ID and iterate through subjects/topics/lectures
        batch_id = course_data.get('batch', {}).get('id')
        if not batch_id:
            raise ValueError("JSON does not contain 'batch.id'.")
        
        video_count = 0
        total_videos = 0
        # Count total videos for progress
        for subject in course_data.get('subjects', []):
            for topic in subject.get('topics', []):
                for lecture in topic.get('lectures', []):
                    if lecture.get('videoId'):
                        total_videos += 1
        
        if total_videos == 0:
            await message.reply_text("⚠️ No videos found in the provided JSON.")
            return
        
        await message.reply_text(f"📽️ Found {total_videos} videos. Starting download and upload...")
        
        for subject in course_data.get('subjects', []):
            for topic in subject.get('topics', []):
                for lecture in topic.get('lectures', []):
                    video_id = lecture.get('videoId')
                    if not video_id:
                        continue
                    
                    video_count += 1
                    status_msg = f"🔄 Processing video {video_count}/{total_videos}: {lecture.get('title', video_id)}"
                    await message.reply_text(status_msg)
                    
                    try:
                        # Generate URL
                        video_url = await generate_video_url(batch_id, video_id, token, random_id)
                        # Download and upload
                        await download_and_upload_video(video_url, message, client)
                    except Exception as e:
                        await message.reply_text(f"❌ Error with video {video_id}: {str(e)}")
                    
                    # Delay to avoid rate limits
                    await asyncio.sleep(2)
        
        await message.reply_text(f"✅ **Process Complete!** Successfully processed {total_videos} videos.")
        
    except Exception as e:
        await message.reply_text(f"❌ An error occurred during processing: {str(e)}")
    finally:
        # Clean up the uploaded JSON file
        if os.path.exists(json_path):
            os.remove(json_path)
