# modules/rarestudy_handler.py
import ast
import asyncio
import html
import json
import os
import re
import shutil
import time
from pathlib import Path
from typing import Dict, Any, List, Optional, Tuple

import aiohttp
import requests
import urllib3
from pyrogram import Client
from pyrogram.types import Message
from pyrogram.errors import FloodWait

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

# ==============================================================================
# 1. CONFIGURATION & HEADERS (rarestudy.testuk.org)
# ==============================================================================
DOWNLOAD_DIR = os.path.abspath("downloads")
os.makedirs(DOWNLOAD_DIR, exist_ok=True)

BASE_DOMAIN = "https://rarestudy.testuk.org"
USER_AGENT = "Mozilla/5.0 (Linux; Android 10; K) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/137.0.0.0 Mobile Safari/537.36"
HEADERS_FILE = os.path.abspath("rarestudy_headers.json")

# Factory default headers provided by user
DEFAULT_HTML_HEADERS = {
    'accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8,application/signed-exchange;v=b3;q=0.7',
    'accept-language': 'en-US,en;q=0.9',
    'authority': 'rarestudy.testuk.org',
    'cookie': 'cf_clearance=QqQJXkf2u63mMo16bJ3phLTR2O_7FxSdsdJEvA23fSI-1789054440-1.2.1.1-gQpmM85.HFb12YBbOKBupV9wDPiQpVwD5JFE0zFGehcMlKAan92zemcPGTGdTcMPlfwg2QfITEL.qWs38h_McUofdkohejgYmBoOqFrXl_TInkaqPkO75b8J1VBu7k80HBuDb5Fw7k0jjUX0xFhXaoTzGu5THUEVr39kQ4eDV7qzFtB_zUnNO5Z4_ZXvDPpLk.hz7FySvCcb3vU5uHMB_emOv0_xovjkH5zL0PMJz1V8OHo4R1rnSVObfHFj00o8twNbSkWGTJb9Dd_ELWXu3a3BBq0Us2Mmb4oxdCG9_w9IMacWLwYS0_Gmk.V7kfFFKnWa7yizsuj5fIEHW2Yx0xAOSr7NIM76.WIpd6wdTXc; session_expiry=1789141151296; favourite_batches=%5B%226a86a154bad6bc80e1acdd85%22%5D; session=.eJwFwdtugjAAANB_6fNIiogZvqGCUKloqrD60gBrC5tciwU1-_ed8was40OdNbwZwXocHvwDDIoprlTVNmANNNYX7-Qt96_eJ8uiJY-2pVeItJ1I0xJWEDxTd6Vo2W72JOrvdbRzRFXYXYduKSWirGH8WTFunbJ-PERdv9oeTTYR85YL8wgZMmBSJq8zdBf5BI1fPiQbeqFZyP0id3z7Wx4W2p7SkZDYSUJkxZXQjH9JbZmuEgYOn8ij85naRkDRLsUzdnw4yx-J6zvcXsHfP27cS94.aqLPyQ.lM7zyLZ6PiImuslH4DSNeWmO1Dc',
    'referer': 'https://rarestudy.testuk.org/stream?batchId=67fbe8415ce253f88c3345f7&subjectId=68e9f2e7a7dc8d81be47c28d&chapterId=691c878a0ec6774c93998a71&batchName=CA%20Foundation%20Sampurna%20May%202026&subjectName=Accounting&chapterName=Trial%20Balance§ion=videos',
    'sec-ch-ua': '"Chromium";v="137", "Not/A)Brand";v="24"',
    'sec-ch-ua-mobile': '?1',
    'sec-ch-ua-platform': '"Android"',
    'sec-fetch-dest': 'document',
    'sec-fetch-mode': 'navigate',
    'sec-fetch-site': 'same-origin',
    'sec-fetch-user': '?1',
    'upgrade-insecure-requests': '1',
    'user-agent': USER_AGENT
}

DEFAULT_API_HEADERS = {
    'accept': '*/*',
    'accept-language': 'en-US,en;q=0.9',
    'authority': 'rarestudy.testuk.org',
    'cookie': 'cf_clearance=QqQJXkf2u63mMo16bJ3phLTR2O_7FxSdsdJEvA23fSI-1789054440-1.2.1.1-gQpmM85.HFb12YBbOKBupV9wDPiQpVwD5JFE0zFGehcMlKAan92zemcPGTGdTcMPlfwg2QfITEL.qWs38h_McUofdkohejgYmBoOqFrXl_TInkaqPkO75b8J1VBu7k80HBuDb5Fw7k0jjUX0xFhXaoTzGu5THUEVr39kQ4eDV7qzFtB_zUnNO5Z4_ZXvDPpLk.hz7FySvCcb3vU5uHMB_emOv0_xovjkH5zL0PMJz1V8OHo4R1rnSVObfHFj00o8twNbSkWGTJb9Dd_ELWXu3a3BBq0Us2Mmb4oxdCG9_w9IMacWLwYS0_Gmk.V7kfFFKnWa7yizsuj5fIEHW2Yx0xAOSr7NIM76.WIpd6wdTXc; session_expiry=1789141151296; favourite_batches=%5B%226a86a154bad6bc80e1acdd85%22%5D; session=.eJwFwdtugjAAANB_6fNIiogZvqGCUKloqrD60gBrC5tciwU1-_ed8was40OdNbwZwXocHvwDDIoprlTVNmANNNYX7-Qt96_eJ8uiJY-2pVeItJ1I0xJWEDxTd6Vo2W72JOrvdbRzRFXYXYduKSWirGH8WTFunbJ-PERdv9oeTTYR85YL8wgZMmBSJq8zdBf5BI1fPiQbeqFZyP0id3z7Wx4W2p7SkZDYSUJkxZXQjH9JbZmuEgYOn8ij85naRkDRLsUzdnw4yx-J6zvcXsHfP27cS94.aqLP1A.DYxT3CZOfxu54GSzU23ZjuIOZRk',
    'referer': 'https://rarestudy.testuk.org/schedule-details?batchId=67fbe8415ce253f88c3345f7&subjectId=68e9f2e7a7dc8d81be47c28d&scheduleId=6915ca73a41f41f96c97bb2a&tap=video',
    'sec-ch-ua': '"Chromium";v="137", "Not/A)Brand";v="24"',
    'sec-ch-ua-mobile': '?1',
    'sec-ch-ua-platform': '"Android"',
    'sec-fetch-dest': 'empty',
    'sec-fetch-mode': 'cors',
    'sec-fetch-site': 'same-origin',
    'user-agent': USER_AGENT
}

HTML_HEADERS = DEFAULT_HTML_HEADERS.copy()
API_HEADERS = DEFAULT_API_HEADERS.copy()

try:
    from vars import RARESTUDY_PROXY
except ImportError:
    RARESTUDY_PROXY = os.environ.get("RARESTUDY_PROXY", "").strip()

ACTIVE_PROXY = RARESTUDY_PROXY


def load_saved_headers():
    """Loads saved headers and proxy from rarestudy_headers.json if available."""
    global HTML_HEADERS, API_HEADERS, ACTIVE_PROXY
    if os.path.exists(HEADERS_FILE):
        try:
            with open(HEADERS_FILE, "r", encoding="utf-8") as f:
                saved = json.load(f)
                if isinstance(saved, dict):
                    if "HTML_HEADERS" in saved and isinstance(saved["HTML_HEADERS"], dict):
                        HTML_HEADERS = saved["HTML_HEADERS"]
                    if "API_HEADERS" in saved and isinstance(saved["API_HEADERS"], dict):
                        API_HEADERS = saved["API_HEADERS"]
                    if "PROXY" in saved and saved["PROXY"]:
                        ACTIVE_PROXY = str(saved["PROXY"]).strip()
        except Exception as e:
            print(f"⚠️ Error loading saved headers: {e}")


def save_headers(html_h: dict, api_h: dict, proxy: str = None):
    """Saves headers and proxy to rarestudy_headers.json for persistence."""
    global ACTIVE_PROXY
    if proxy is not None:
        ACTIVE_PROXY = str(proxy).strip()
    try:
        with open(HEADERS_FILE, "w", encoding="utf-8") as f:
            json.dump({
                "HTML_HEADERS": html_h,
                "API_HEADERS": api_h,
                "PROXY": ACTIVE_PROXY
            }, f, indent=2)
    except Exception as e:
        print(f"⚠️ Error saving headers: {e}")


def set_rarestudy_headers(html_headers: dict = None, api_headers: dict = None, cookie: str = None, referer: str = None) -> Tuple[dict, dict]:
    """Updates active headers in memory and saves to disk."""
    global HTML_HEADERS, API_HEADERS

    if html_headers and isinstance(html_headers, dict):
        HTML_HEADERS.update(html_headers)
    if api_headers and isinstance(api_headers, dict):
        API_HEADERS.update(api_headers)

    if cookie and cookie.strip():
        c_val = cookie.strip()
        HTML_HEADERS['cookie'] = c_val
        API_HEADERS['cookie'] = c_val

    if referer and referer.strip():
        r_val = referer.strip()
        HTML_HEADERS['referer'] = r_val
        API_HEADERS['referer'] = r_val

    save_headers(HTML_HEADERS, API_HEADERS)
    return HTML_HEADERS, API_HEADERS


def get_rarestudy_headers() -> Tuple[dict, dict]:
    """Returns the current active (HTML_HEADERS, API_HEADERS)."""
    return HTML_HEADERS, API_HEADERS


def reset_rarestudy_headers() -> Tuple[dict, dict]:
    """Resets headers back to default."""
    global HTML_HEADERS, API_HEADERS
    HTML_HEADERS = DEFAULT_HTML_HEADERS.copy()
    API_HEADERS = DEFAULT_API_HEADERS.copy()
    save_headers(HTML_HEADERS, API_HEADERS, proxy=ACTIVE_PROXY)
    return HTML_HEADERS, API_HEADERS


def set_rarestudy_proxy(proxy_url: str) -> str:
    """Updates active proxy/VPN URL in memory and saves to disk."""
    global ACTIVE_PROXY
    ACTIVE_PROXY = str(proxy_url or "").strip()
    save_headers(HTML_HEADERS, API_HEADERS, proxy=ACTIVE_PROXY)
    return ACTIVE_PROXY


def get_rarestudy_proxy() -> str:
    """Returns the current active proxy URL."""
    return ACTIVE_PROXY


def reset_rarestudy_proxy() -> str:
    """Clears the active proxy, reverting to direct network."""
    global ACTIVE_PROXY
    ACTIVE_PROXY = ""
    save_headers(HTML_HEADERS, API_HEADERS, proxy="")
    return ""


def parse_header_input(text: str) -> Tuple[Optional[dict], Optional[dict], Optional[str]]:
    """
    Parses user input from Telegram:
    - Raw cookie string
    - Python snippet: HTML_HEADERS = { ... } API_HEADERS = { ... }
    - JSON dictionary
    Returns (html_headers_dict, api_headers_dict, cookie_str)
    """
    text = text.strip()

    # 1. Python variable assignment format
    if "HTML_HEADERS" in text or "API_HEADERS" in text:
        html_dict = None
        api_dict = None
        
        html_match = re.search(r'HTML_HEADERS\s*=\s*(\{.*?\})(?=\s*(?:API_HEADERS|$))', text, re.DOTALL)
        if html_match:
            try:
                html_dict = ast.literal_eval(html_match.group(1))
            except Exception:
                try:
                    html_dict = json.loads(html_match.group(1).replace("'", '"'))
                except Exception:
                    pass

        api_match = re.search(r'API_HEADERS\s*=\s*(\{.*?\})', text, re.DOTALL)
        if api_match:
            try:
                api_dict = ast.literal_eval(api_match.group(1))
            except Exception:
                try:
                    api_dict = json.loads(api_match.group(1).replace("'", '"'))
                except Exception:
                    pass

        if html_dict or api_dict:
            return html_dict, api_dict, None

    # 2. JSON / Python Dict format
    if text.startswith("{") and text.endswith("}"):
        try:
            parsed = json.loads(text)
            if "HTML_HEADERS" in parsed or "API_HEADERS" in parsed:
                return parsed.get("HTML_HEADERS"), parsed.get("API_HEADERS"), None
            if "accept" in parsed or "cookie" in parsed:
                return parsed, parsed, parsed.get("cookie")
        except Exception:
            try:
                parsed = ast.literal_eval(text)
                if isinstance(parsed, dict):
                    if "HTML_HEADERS" in parsed or "API_HEADERS" in parsed:
                        return parsed.get("HTML_HEADERS"), parsed.get("API_HEADERS"), None
                    return parsed, parsed, parsed.get("cookie")
            except Exception:
                pass

    # 3. Raw cookie string
    if "cf_clearance" in text or "session=" in text or ";" in text or "=" in text:
        return None, None, text

    return None, None, None


# Automatically load persistent headers on startup
load_saved_headers()


# ==============================================================================
# 2. JSON PARSER & DETECTION LOGIC
# ==============================================================================
def is_rarestudy_json(json_data: Any) -> bool:
    """Detects if a parsed JSON belongs to RareStudy / TestUK format."""
    if not isinstance(json_data, dict):
        if isinstance(json_data, list) and len(json_data) > 0 and isinstance(json_data[0], dict):
            sample = json_data[0]
            if sample.get('videoId') and (sample.get('subjectId') or sample.get('batchId') or sample.get('scheduleId')):
                return True
        return False

    raw_str = json.dumps(json_data).lower()
    if 'rarestudy' in raw_str or 'testuk' in raw_str:
        return True

    # Check for characteristic structure: subjects -> topics -> lectures with videoId
    if 'subjects' in json_data and isinstance(json_data['subjects'], list):
        for s in json_data['subjects']:
            if isinstance(s, dict) and 'subjectId' in s and 'topics' in s:
                return True

    # Check for scheduleId or tap=video patterns
    if 'scheduleId' in raw_str or 'schedule-details' in raw_str:
        return True

    return False


def parse_rarestudy_course(json_data: Any) -> Tuple[str, str, List[Dict[str, Any]]]:
    """
    Parses RareStudy course JSON.
    Returns (batch_id, batch_name, lectures_list)
    """
    batch_id = "67fbe8415ce253f88c3345f7"
    batch_name = "RareStudy Course Batch"

    if isinstance(json_data, dict):
        batch_obj = json_data.get('batch')
        if isinstance(batch_obj, dict):
            batch_id = batch_obj.get('id') or batch_obj.get('_id') or batch_id
            batch_name = batch_obj.get('name') or batch_obj.get('title') or batch_name
        elif json_data.get('batchId'):
            batch_id = json_data.get('batchId')
        elif json_data.get('batch_id'):
            batch_id = json_data.get('batch_id')

        if json_data.get('batchName'):
            batch_name = json_data.get('batchName')
        elif json_data.get('name'):
            batch_name = json_data.get('name')

    lectures = []
    seen_ids = set()

    def add_lecture(b_id, s_id, v_id, title, subj_name):
        if not v_id:
            return
        v_id_str = str(v_id).strip()
        if v_id_str in seen_ids:
            return
        seen_ids.add(v_id_str)
        lectures.append({
            'batchId': str(b_id or batch_id),
            'subjectId': str(s_id or ''),
            'videoId': v_id_str,
            'scheduleId': v_id_str,
            'title': str(title or f"Lecture_{v_id_str}").strip(),
            'subject': str(subj_name or "General").strip()
        })

    if isinstance(json_data, dict):
        if 'subjects' in json_data and isinstance(json_data['subjects'], list):
            for subj in json_data['subjects']:
                if not isinstance(subj, dict):
                    continue
                s_id = subj.get('subjectId') or subj.get('id') or subj.get('_id') or ''
                s_name = subj.get('subject') or subj.get('name') or subj.get('title') or "Subject"

                topics = subj.get('topics') or []
                if isinstance(topics, list):
                    for top in topics:
                        if not isinstance(top, dict):
                            continue
                        lecs = top.get('lectures') or top.get('videos') or []
                        if isinstance(lecs, list):
                            for lec in lecs:
                                if isinstance(lec, dict):
                                    v_id = lec.get('videoId') or lec.get('scheduleId') or lec.get('id')
                                    title = lec.get('title') or lec.get('name') or top.get('title')
                                    add_lecture(batch_id, s_id, v_id, title, s_name)

        elif 'lectures' in json_data and isinstance(json_data['lectures'], list):
            for lec in json_data['lectures']:
                if isinstance(lec, dict):
                    add_lecture(
                        lec.get('batchId') or batch_id,
                        lec.get('subjectId') or '',
                        lec.get('videoId') or lec.get('scheduleId') or lec.get('id'),
                        lec.get('title') or lec.get('name'),
                        lec.get('subject') or "General"
                    )

    elif isinstance(json_data, list):
        for item in json_data:
            if isinstance(item, dict):
                add_lecture(
                    item.get('batchId') or batch_id,
                    item.get('subjectId') or '',
                    item.get('videoId') or item.get('scheduleId') or item.get('id'),
                    item.get('title') or item.get('name'),
                    item.get('subject') or "General"
                )

    return batch_id, batch_name, lectures


# ==============================================================================
# 3. EXTRACTION LOGIC (MEDIA_TOKEN & DRM KEYS)
# ==============================================================================
def process_video_extraction(batch_id: str, subject_id: str, schedule_id: str, title: str = "video", custom_cookie: str = None, proxy: str = None) -> Dict[str, Any]:
    """
    Synchronous extraction for web API.
    Fetches HTML -> extracts MEDIA_TOKEN -> queries DASH API -> returns MPD URL & DRM Key.
    Supports HTTP, HTTPS, and SOCKS5 proxies.
    """
    current_html = HTML_HEADERS.copy()
    current_api = API_HEADERS.copy()
    use_proxy = proxy if proxy is not None else ACTIVE_PROXY

    if custom_cookie and custom_cookie.strip():
        current_html['cookie'] = custom_cookie.strip()
        current_api['cookie'] = custom_cookie.strip()

    clean_title = re.sub(r'[\\/*?:"<>|]', "", title).strip() or "video"
    html_url = f"{BASE_DOMAIN}/schedule-details?batchId={batch_id}&subjectId={subject_id}&scheduleId={schedule_id}&tap=video"

    proxies = {"http": use_proxy, "https": use_proxy} if use_proxy else None

    try:
        r1 = requests.get(html_url, headers=current_html, verify=False, timeout=20, proxies=proxies)
        if r1.status_code != 200:
            return {"status": "error", "message": f"HTML Error: HTTP {r1.status_code}", "title": clean_title}

        match = re.search(r'MEDIA_TOKEN\s*=\s*["\']([^"\']+)["\']', r1.text)
        if not match:
            return {"status": "error", "message": "MEDIA_TOKEN nahi mila (Session expired ya Cookies update karein)", "title": clean_title}

        media_token = match.group(1)

        api_url = f"{BASE_DOMAIN}/v1/videos/video-url-details?mediaToken={media_token}&videoContainerType=DASH"
        r2 = requests.get(api_url, headers=current_api, verify=False, timeout=20, proxies=proxies)

        if r2.status_code != 200:
            return {"status": "error", "message": f"API Error: HTTP {r2.status_code}", "title": clean_title}

        res_json = r2.json()
        data = res_json.get('data', {})
        mpd_url = data.get('url')
        keys = data.get('keys', [])
        drm_key = keys[0] if keys else None

        if not mpd_url or not drm_key:
            return {"status": "error", "message": "API response did not contain MPD URL or DRM Key", "title": clean_title}

        _, cmd_display = build_download_cmd(mpd_url, drm_key, clean_title, proxy=use_proxy)

        return {
            "status": "success",
            "title": clean_title,
            "mpd_url": mpd_url,
            "key": drm_key,
            "cmd": cmd_display
        }
    except Exception as e:
        return {"status": "error", "message": str(e), "title": clean_title}


async def async_extract_video_details(batch_id: str, subject_id: str, schedule_id: str, title: str = "video", custom_cookie: str = None, proxy: str = None) -> Dict[str, Any]:
    """
    Asynchronous extraction for Pyrogram bot and async pipelines.
    Supports HTTP/HTTPS and SOCKS5 proxies safely.
    """
    use_proxy = proxy if proxy is not None else ACTIVE_PROXY

    # When proxy is configured (HTTP or SOCKS5), run extraction via thread
    # because PySocks + requests supports socks5/http proxies seamlessly.
    if use_proxy:
        return await asyncio.to_thread(
            process_video_extraction,
            batch_id=batch_id,
            subject_id=subject_id,
            schedule_id=schedule_id,
            title=title,
            custom_cookie=custom_cookie,
            proxy=use_proxy
        )

    current_html = HTML_HEADERS.copy()
    current_api = API_HEADERS.copy()

    if custom_cookie and custom_cookie.strip():
        current_html['cookie'] = custom_cookie.strip()
        current_api['cookie'] = custom_cookie.strip()

    clean_title = re.sub(r'[\\/*?:"<>|]', "", title).strip() or "video"
    html_url = f"{BASE_DOMAIN}/schedule-details?batchId={batch_id}&subjectId={subject_id}&scheduleId={schedule_id}&tap=video"

    timeout = aiohttp.ClientTimeout(total=20)
    connector = aiohttp.TCPConnector(ssl=False)

    try:
        async with aiohttp.ClientSession(headers=current_html, connector=connector, timeout=timeout) as session:
            async with session.get(html_url) as resp:
                if resp.status != 200:
                    return {"status": "error", "message": f"HTML status: {resp.status}", "title": clean_title}
                text = await resp.text()

        match = re.search(r'MEDIA_TOKEN\s*=\s*["\']([^"\']+)["\']', text)
        if not match:
            return {"status": "error", "message": "MEDIA_TOKEN nahi mila (Cookies check karein)", "title": clean_title}

        media_token = match.group(1)

        api_url = f"{BASE_DOMAIN}/v1/videos/video-url-details?mediaToken={media_token}&videoContainerType=DASH"
        async with aiohttp.ClientSession(headers=current_api, connector=connector, timeout=timeout) as session:
            async with session.get(api_url) as resp:
                if resp.status != 200:
                    return {"status": "error", "message": f"API status: {resp.status}", "title": clean_title}
                res_json = await resp.json()

        data = res_json.get('data', {})
        mpd_url = data.get('url')
        keys = data.get('keys', [])
        drm_key = keys[0] if keys else None

        if not mpd_url or not drm_key:
            return {"status": "error", "message": "MPD URL ya DRM Key response me nahi mili", "title": clean_title}

        cmd_list, cmd_display = build_download_cmd(mpd_url, drm_key, clean_title, proxy=use_proxy)

        return {
            "status": "success",
            "title": clean_title,
            "mpd_url": mpd_url,
            "key": drm_key,
            "cmd_list": cmd_list,
            "cmd": cmd_display
        }
    except Exception as e:
        return await asyncio.to_thread(
            process_video_extraction,
            batch_id=batch_id,
            subject_id=subject_id,
            schedule_id=schedule_id,
            title=title,
            custom_cookie=custom_cookie,
            proxy=use_proxy
        )


# ==============================================================================
# 4. DOWNLOAD ENGINE (N_m3u8DL-RE + mp4decrypt + yt-dlp fallback)
# ==============================================================================
def find_binary(name: str) -> Optional[str]:
    """Finds binary in current directory or system PATH."""
    exe_name = f"{name}.exe" if os.name == 'nt' else name
    if os.path.exists(exe_name):
        return os.path.abspath(exe_name)
    if os.path.exists(name):
        return os.path.abspath(name)
    which_path = shutil.which(name) or shutil.which(exe_name)
    return which_path


def build_download_cmd(mpd_url: str, drm_key: str, title: str, save_dir: str = None, proxy: str = None) -> Tuple[List[str], str]:
    save_path = save_dir or DOWNLOAD_DIR
    clean_title = re.sub(r'[\\/*?:"<>|]', "", title).strip() or "video"
    use_proxy = proxy if proxy is not None else ACTIVE_PROXY

    n_bin = find_binary("N_m3u8DL-RE") or "N_m3u8DL-RE"
    mp4dec_bin = find_binary("mp4decrypt")

    cmd_list = [
        n_bin,
        mpd_url,
        "--key", drm_key,
        "-H", f"User-Agent: {USER_AGENT}",
        "-H", f"Referer: {BASE_DOMAIN}/",
        "-H", f"Origin: {BASE_DOMAIN}",
        "--save-name", clean_title,
        "--save-dir", save_path,
        "-M", "format=mp4",
        "--auto-select"
    ]

    if use_proxy:
        cmd_list.extend(["--custom-proxy", use_proxy])

    if mp4dec_bin:
        cmd_list.extend(["--decryption-binary-path", mp4dec_bin])

    cmd_str = f'{n_bin} "{mpd_url}" --key "{drm_key}" -H "User-Agent: {USER_AGENT}" -H "Referer: {BASE_DOMAIN}/" -H "Origin: {BASE_DOMAIN}" --save-name "{clean_title}" --save-dir "{save_path}" -M format=mp4 --auto-select'
    if use_proxy:
        cmd_str += f' --custom-proxy "{use_proxy}"'
    if mp4dec_bin:
        cmd_str += f' --decryption-binary-path "{mp4dec_bin}"'

    return cmd_list, cmd_str


async def async_download_video(mpd_url: str, drm_key: str, title: str, save_dir: str = None, proxy: str = None) -> Tuple[bool, str, Optional[str]]:
    """
    Downloads and decrypts RareStudy video asynchronously.
    Returns (success, message, file_path).
    Supports HTTP/HTTPS and SOCKS5 proxy via N_m3u8DL-RE and yt-dlp.
    """
    target_dir = save_dir or DOWNLOAD_DIR
    os.makedirs(target_dir, exist_ok=True)
    clean_title = re.sub(r'[\\/*?:"<>|]', "", title).strip() or "video"
    target_mp4 = os.path.join(target_dir, f"{clean_title}.mp4")
    use_proxy = proxy if proxy is not None else ACTIVE_PROXY

    # If already downloaded and valid, return it
    if os.path.exists(target_mp4) and os.path.getsize(target_mp4) > 100000:
        return True, "Already downloaded", target_mp4

    cmd_list, _ = build_download_cmd(mpd_url, drm_key, clean_title, save_dir=target_dir, proxy=use_proxy)

    # 1. Primary: N_m3u8DL-RE
    n_bin = find_binary("N_m3u8DL-RE")
    if n_bin:
        try:
            cmd_list[0] = n_bin
            proc = await asyncio.create_subprocess_exec(
                *cmd_list,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE
            )
            try:
                stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=1800)
            except asyncio.TimeoutError:
                proc.kill()
                return False, "Download timed out after 30 minutes", None

            # Check if target file was produced
            if os.path.exists(target_mp4) and os.path.getsize(target_mp4) > 100000:
                return True, "Download Successful", target_mp4

            # Look for any matching video file in save_dir
            for f in os.listdir(target_dir):
                if f.startswith(clean_title) and f.endswith(('.mp4', '.mkv')):
                    full_p = os.path.join(target_dir, f)
                    if os.path.getsize(full_p) > 100000:
                        return True, "Download Successful", full_p

            err_detail = stderr.decode('utf-8', errors='ignore')[-300:] if stderr else "Unknown error"
            return False, f"N_m3u8DL-RE finished without valid output: {err_detail}", None

        except Exception as e:
            print(f"⚠️ N_m3u8DL-RE error: {e}")

    # 2. Fallback: yt-dlp + mp4decrypt (if N_m3u8DL-RE not present)
    try:
        mp4dec = find_binary("mp4decrypt")
        temp_work = os.path.join(target_dir, f"temp_{int(time.time())}")
        os.makedirs(temp_work, exist_ok=True)

        ytdlp_cmd = [
            'yt-dlp',
            '-o', f"{temp_work}/raw.%(ext)s",
            '--allow-unplayable-format',
            '--no-check-certificate',
            '--add-header', f"User-Agent:{USER_AGENT}",
            '--add-header', f"Referer:{BASE_DOMAIN}/",
            '--add-header', f"Origin:{BASE_DOMAIN}",
            mpd_url
        ]
        if use_proxy:
            ytdlp_cmd.extend(['--proxy', use_proxy])

        p1 = await asyncio.create_subprocess_exec(*ytdlp_cmd, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE)
        await asyncio.wait_for(p1.communicate(), timeout=1200)

        # Decrypt raw files if mp4decrypt exists
        if mp4dec and drm_key:
            for item in Path(temp_work).iterdir():
                if item.suffix == ".mp4":
                    dec_cmd = [mp4dec, "--key", drm_key, str(item), target_mp4]
                    p_dec = await asyncio.create_subprocess_exec(*dec_cmd, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE)
                    await asyncio.wait_for(p_dec.communicate(), timeout=300)
                    if os.path.exists(target_mp4) and os.path.getsize(target_mp4) > 100000:
                        shutil.rmtree(temp_work, ignore_errors=True)
                        return True, "Downloaded & Decrypted via yt-dlp + mp4decrypt", target_mp4

        shutil.rmtree(temp_work, ignore_errors=True)
    except Exception as ex:
        print(f"⚠️ Fallback error: {ex}")

    return False, "N_m3u8DL-RE.exe nahi mila! Is script wale folder me N_m3u8DL-RE.exe rakhein.", None


# ==============================================================================
# 5. TELEGRAM BOT PIPELINE: AUTO-PROCESS & UPLOAD
# ==============================================================================
def render_progress_bar(percent: float, bar_len: int = 12) -> str:
    filled = int((percent / 100) * bar_len)
    filled = max(0, min(filled, bar_len))
    return "▰" * filled + "▱" * (bar_len - filled)


def format_size_readable(size_bytes: int) -> str:
    if not size_bytes:
        return "0 MB"
    for unit in ['B', 'KB', 'MB', 'GB', 'TB']:
        if size_bytes < 1024.0:
            return f"{size_bytes:.1f} {unit}"
        size_bytes /= 1024.0
    return f"{size_bytes:.1f} GB"


def format_duration_readable(seconds: int) -> str:
    if not seconds or seconds <= 0:
        return "N/A"
    hrs = seconds // 3600
    mins = (seconds % 3600) // 60
    secs = seconds % 60
    if hrs > 0:
        return f"{hrs:02d}h {mins:02d}m {secs:02d}s"
    return f"{mins:02d}m {secs:02d}s"


async def get_video_metadata(file_path: str) -> Tuple[int, int, int]:
    duration = 0
    width = 1280
    height = 720
    try:
        cmd = [
            'ffprobe', '-v', 'error',
            '-select_streams', 'v:0',
            '-show_entries', 'stream=width,height,duration:format=duration',
            '-of', 'default=noprint_wrappers=1:nokey=1',
            file_path
        ]
        proc = await asyncio.create_subprocess_exec(*cmd, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE)
        out, _ = await asyncio.wait_for(proc.communicate(), timeout=20)
        if proc.returncode == 0 and out:
            lines = [l.strip() for l in out.decode().splitlines() if l.strip()]
            for line in lines:
                try:
                    val = float(line)
                    if val > duration:
                        duration = val
                except ValueError:
                    pass

        cmd_dim = [
            'ffprobe', '-v', 'error',
            '-select_streams', 'v:0',
            '-show_entries', 'stream=width,height',
            '-of', 'csv=s=x:p=0',
            file_path
        ]
        p_dim = await asyncio.create_subprocess_exec(*cmd_dim, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE)
        out_dim, _ = await asyncio.wait_for(p_dim.communicate(), timeout=10)
        if out_dim:
            dim_str = out_dim.decode().strip()
            if 'x' in dim_str:
                w_s, h_s = dim_str.split('x', 1)
                if w_s.isdigit() and h_s.isdigit():
                    width = int(w_s)
                    height = int(h_s)
    except Exception:
        pass

    return int(duration), width, height


async def generate_thumbnail(video_path: str, thumb_path: str, duration: int = 0) -> Optional[str]:
    try:
        if os.path.exists(thumb_path):
            os.remove(thumb_path)
        offset = 15 if duration > 60 else (max(3, int(duration * 0.15)) if duration > 10 else 1)
        offset_str = time.strftime('%H:%M:%S', time.gmtime(offset))

        cmd = [
            'ffmpeg', '-y',
            '-ss', offset_str,
            '-i', video_path,
            '-vframes', '1',
            '-q:v', '2',
            thumb_path
        ]
        proc = await asyncio.create_subprocess_exec(*cmd, stdout=asyncio.subprocess.DEVNULL, stderr=asyncio.subprocess.DEVNULL)
        await asyncio.wait_for(proc.communicate(), timeout=25)
        if os.path.exists(thumb_path) and os.path.getsize(thumb_path) > 1000:
            return thumb_path
    except Exception:
        pass
    return None


def render_rarestudy_dashboard(
    batch_name: str,
    channel_id: int,
    total_videos: int,
    current_idx: int,
    current_title: str,
    status_text: str,
    success_count: int,
    fail_count: int,
    upload_extra: str = ""
) -> str:
    percent = (current_idx / total_videos) * 100 if total_videos > 0 else 0
    p_bar = render_progress_bar(percent, 12)
    safe_title = html.escape(str(current_title)[:55])
    safe_batch = html.escape(str(batch_name))

    dashboard = (
        "╔══════════════════════════════════╗\n"
        "   ⚡ <b>RARESTUDY DRM UPLOADER</b> ⚡\n"
        "╚══════════════════════════════════╝\n\n"
        f"📚 <b>Batch:</b> <code>{safe_batch}</code>\n"
        f"📢 <b>Target:</b> <code>{channel_id}</code>\n"
        f"📊 <b>Progress:</b> <code>[{p_bar}]</code> <b>{percent:.1f}%</b>\n"
        f"🔢 <b>Current:</b> <code>{current_idx}</code> / <code>{total_videos}</code>\n"
        f"🎬 <b>Title:</b> <i>{safe_title}</i>\n"
        f"📈 <b>Success:</b> <code>{success_count}</code>  |  ❌ <b>Failed:</b> <code>{fail_count}</code>\n"
    )

    if ACTIVE_PROXY:
        p_show = ACTIVE_PROXY
        if '@' in p_show:
            p_show = p_show.split('@')[-1]
        dashboard += f"🛡️ <b>VPN/Proxy:</b> <code>{html.escape(p_show)}</code>\n"

    dashboard += f"\n{status_text}\n"
    if upload_extra:
        dashboard += f"{upload_extra}\n"

    dashboard += (
        "\n━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
        "⚡ <i>RareStudy Fast DRM Decryption Engine</i>"
    )
    return dashboard


async def process_rarestudy_and_upload(
    client: Client,
    message: Message,
    json_path: str,
    custom_cookie: Optional[str] = None,
    channel_id: Optional[int] = None
):
    """
    Main entry point for Telegram bot: Parses RareStudy JSON, extracts DRM streams,
    downloads via N_m3u8DL-RE, and uploads each video to Telegram.
    """
    channel_id = channel_id or message.chat.id
    status_msg = await message.reply_text("🔍 **Parsing RareStudy Course JSON...**")

    try:
        with open(json_path, 'r', encoding='utf-8') as f:
            course_data = json.load(f)

        batch_id, batch_name, lectures = parse_rarestudy_course(course_data)

        if not lectures:
            await status_msg.edit_text("❌ **No videos found in RareStudy JSON!**")
            return

        total_videos = len(lectures)
        dash_text = render_rarestudy_dashboard(
            batch_name=batch_name,
            channel_id=channel_id,
            total_videos=total_videos,
            current_idx=1,
            current_title=lectures[0]['title'],
            status_text="🚀 <b>Starting RareStudy DRM Engine...</b>",
            success_count=0,
            fail_count=0
        )
        dashboard_msg = await status_msg.edit_text(dash_text)

        # Notify Target Channel
        try:
            safe_b_name = html.escape(str(batch_name))
            channel_banner = (
                f"╭───⌯ 📚 <b>RARESTUDY BATCH STARTED</b> ⌯───╮\n"
                f"│\n"
                f"├ 🎯 <b>Batch :</b> {safe_b_name}\n"
                f"├ 📽️ <b>Total Lectures :</b> {total_videos}\n"
                f"├ 🌐 <b>Domain :</b> rarestudy.testuk.org\n"
                f"│\n"
                f"╰──────────────────────────╯"
            )
            await client.send_message(chat_id=channel_id, text=channel_banner)
        except Exception as e:
            print(f"⚠️ Channel banner error: {e}")

        success_count = 0
        fail_count = 0

        for idx, lec in enumerate(lectures, start=1):
            title = lec['title']
            subject = lec['subject']
            s_id = lec['subjectId']
            v_id = lec['videoId']
            b_id = lec['batchId']

            # Step 1: Extract DRM Stream Details
            try:
                up_dash = render_rarestudy_dashboard(
                    batch_name=batch_name,
                    channel_id=channel_id,
                    total_videos=total_videos,
                    current_idx=idx,
                    current_title=f"[{subject}] {title}",
                    status_text="🔑 <b>Fetching MEDIA_TOKEN & DRM Keys...</b>",
                    success_count=success_count,
                    fail_count=fail_count
                )
                try:
                    await dashboard_msg.edit_text(up_dash)
                except Exception:
                    pass

                extract_res = await async_extract_video_details(
                    batch_id=b_id,
                    subject_id=s_id,
                    schedule_id=v_id,
                    title=title,
                    custom_cookie=custom_cookie
                )

                if extract_res.get('status') != 'success':
                    raise Exception(extract_res.get('message', 'Extraction failed'))

                mpd_url = extract_res['mpd_url']
                drm_key = extract_res['key']

                # Step 2: Download Video via N_m3u8DL-RE
                up_dash = render_rarestudy_dashboard(
                    batch_name=batch_name,
                    channel_id=channel_id,
                    total_videos=total_videos,
                    current_idx=idx,
                    current_title=f"[{subject}] {title}",
                    status_text="⬇️ <b>Downloading Video (N_m3u8DL-RE)...</b>",
                    success_count=success_count,
                    fail_count=fail_count
                )
                try:
                    await dashboard_msg.edit_text(up_dash)
                except Exception:
                    pass

                ok, msg, downloaded_file = await async_download_video(mpd_url, drm_key, title)
                if not ok or not downloaded_file or not os.path.exists(downloaded_file):
                    raise Exception(f"Download failed: {msg}")

                # Step 3: Metadata & Thumbnail
                duration, width, height = await get_video_metadata(downloaded_file)
                file_size = os.path.getsize(downloaded_file)
                thumb_target = os.path.join(DOWNLOAD_DIR, f"thumb_{int(time.time())}.jpg")
                thumb_path = await generate_thumbnail(downloaded_file, thumb_target, duration=duration)

                # Step 4: Upload to Telegram Channel
                last_edit_time = [0]
                async def upload_progress(curr, tot):
                    now = time.time()
                    if now - last_edit_time[0] >= 4.0:
                        last_edit_time[0] = now
                        pct = (curr / tot) * 100 if tot > 0 else 0
                        sp_bar = render_progress_bar(pct, 10)
                        up_status = f"⬆️ <b>Uploading to Channel...</b> <code>{pct:.1f}%</code>"
                        up_extra = f"📦 <code>[{sp_bar}]</code> {format_size_readable(curr)} / {format_size_readable(tot)}"
                        dash_p = render_rarestudy_dashboard(
                            batch_name=batch_name,
                            channel_id=channel_id,
                            total_videos=total_videos,
                            current_idx=idx,
                            current_title=f"[{subject}] {title}",
                            status_text=up_status,
                            success_count=success_count,
                            fail_count=fail_count,
                            upload_extra=up_extra
                        )
                        try:
                            await dashboard_msg.edit_text(dash_p)
                        except Exception:
                            pass

                caption = (
                    f"╭───⌯ 🎬 <b>{html.escape(str(title))}</b> ⌯───╮\n"
                    f"│\n"
                    f"├ 📚 <b>Batch :</b> {html.escape(str(batch_name))}\n"
                    f"├ 📖 <b>Subject :</b> {html.escape(str(subject))}\n"
                    f"├ ⏱️ <b>Duration :</b> {format_duration_readable(duration)}\n"
                    f"├ 📦 <b>File Size :</b> {format_size_readable(file_size)}\n"
                    f"├ 🔢 <b>Part :</b> {idx} of {total_videos}\n"
                    f"│\n"
                    f"╰──────────────────────────╯"
                )

                # Send Video with retries
                uploaded = False
                for attempt in range(3):
                    try:
                        await client.send_video(
                            chat_id=channel_id,
                            video=downloaded_file,
                            caption=caption,
                            duration=duration,
                            width=width,
                            height=height,
                            thumb=thumb_path,
                            supports_streaming=True,
                            progress=upload_progress
                        )
                        uploaded = True
                        break
                    except FloodWait as fw:
                        await asyncio.sleep(fw.value + 2)
                    except Exception as ex:
                        print(f"⚠️ Upload attempt {attempt+1} failed: {ex}")
                        await asyncio.sleep(3)

                if not uploaded:
                    raise Exception("Failed to upload video to Telegram after 3 attempts")

                success_count += 1

                # Clean up local thumbnail and temp files (keep download in DOWNLOAD_DIR if needed or remove)
                if thumb_path and os.path.exists(thumb_path):
                    try:
                        os.remove(thumb_path)
                    except Exception:
                        pass

            except Exception as e:
                fail_count += 1
                print(f"❌ RareStudy Lecture {idx} failed: {e}")

        # Final Dashboard Summary
        final_dash = (
            "╔══════════════════════════════════╗\n"
            "   ✅ <b>RARESTUDY UPLOAD FINISHED</b>\n"
            "╚══════════════════════════════════╝\n\n"
            f"📚 <b>Batch:</b> <code>{html.escape(str(batch_name))}</code>\n"
            f"🎬 <b>Total Processed:</b> <code>{total_videos}</code>\n"
            f"✅ <b>Successfully Uploaded:</b> <code>{success_count}</code>\n"
            f"❌ <b>Failed:</b> <code>{fail_count}</code>\n\n"
            f"📁 <i>Downloads preserved in: {DOWNLOAD_DIR}</i>"
        )
        try:
            await dashboard_msg.edit_text(final_dash)
        except Exception:
            pass

    except Exception as e:
        await message.reply_text(f"❌ **Fatal Error in RareStudy Pipeline:**\n`{str(e)}`")
    finally:
        if os.path.exists(json_path):
            try:
                os.remove(json_path)
            except Exception:
                pass
