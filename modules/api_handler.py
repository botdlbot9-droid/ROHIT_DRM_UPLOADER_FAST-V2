# modules/api_handler.py
import requests
import json
from typing import Dict, Optional

API_ENDPOINT = "https://pdablu-api.newdrm4.workers.dev/"

def generate_video_url_from_api(batch_id: str, subject_id: str, child_id: str, video_id: str, access_token: str, refresh_token: str = "", cookie: str = "") -> Optional[str]:
    """
    StudyPanda API se video URL generate karega
    """
    try:
        # Build API URL
        api_url = f"{API_ENDPOINT}?batchId={batch_id}&subjectId={subject_id}&childId={child_id}&videoId={video_id}&accessToken={access_token}"
        
        if refresh_token:
            api_url += f"&refreshToken={refresh_token}"
        if cookie:
            api_url += f"&cookie={cookie}"
        
        print(f"📡 API Request: {api_url[:200]}...")
        
        response = requests.get(api_url, timeout=30)
        print(f"📡 Response Status: {response.status_code}")
        
        data = response.json()
        print(f"📡 API Response: {data}")
        
        if data.get('success') and data.get('url'):
            return data.get('url')
        else:
            print(f"❌ API Error: {data.get('error', 'Unknown error')}")
            return None
            
    except Exception as e:
        print(f"❌ API request failed: {str(e)}")
        return None

def get_video_url_with_retry(batch_id: str, subject_id: str, child_id: str, video_id: str, access_token: str, max_retries: int = 3) -> Optional[str]:
    """
    API call with retry logic
    """
    for attempt in range(1, max_retries + 1):
        print(f"🔄 Attempt {attempt}/{max_retries}")
        result = generate_video_url_from_api(batch_id, subject_id, child_id, video_id, access_token)
        if result:
            return result
        time.sleep(2 ** attempt)  # Exponential backoff
    return None
