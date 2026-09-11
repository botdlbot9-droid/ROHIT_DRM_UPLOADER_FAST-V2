from flask import Flask, request, jsonify, render_template_string
from urllib.parse import urlparse, parse_qs
import os
import re
import shutil
import subprocess
import requests
import urllib3

try:
    from modules.rarestudy_handler import (
        DOWNLOAD_DIR,
        BASE_DOMAIN,
        USER_AGENT,
        HTML_HEADERS,
        API_HEADERS,
        process_video_extraction,
        build_download_cmd,
        find_binary,
        get_rarestudy_proxy,
        set_rarestudy_proxy
    )
except ImportError:
    DOWNLOAD_DIR = os.path.abspath("downloads")
    BASE_DOMAIN = "https://rarestudy.testuk.org"
    USER_AGENT = "Mozilla/5.0 (Linux; Android 10; K) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/137.0.0.0 Mobile Safari/537.36"
    HTML_HEADERS = {'user-agent': USER_AGENT}
    API_HEADERS = {'user-agent': USER_AGENT}

    def find_binary(name: str):
        exe_name = f"{name}.exe" if os.name == 'nt' else name
        if os.path.exists(exe_name):
            return os.path.abspath(exe_name)
        return shutil.which(name) or shutil.which(exe_name)

    def build_download_cmd(mpd_url, drm_key, title):
        clean_title = re.sub(r'[\\/*?:"<>|]', "", title).strip() or "video"
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
            "--save-dir", DOWNLOAD_DIR,
            "-M", "format=mp4",
            "--auto-select"
        ]
        if mp4dec_bin:
            cmd_list.extend(["--decryption-binary-path", mp4dec_bin])

        cmd_str = f'{n_bin} "{mpd_url}" --key "{drm_key}" -H "User-Agent: {USER_AGENT}" -H "Referer: {BASE_DOMAIN}/" -H "Origin: {BASE_DOMAIN}" --save-name "{clean_title}" --save-dir "{DOWNLOAD_DIR}" -M format=mp4 --auto-select'
        if mp4dec_bin:
            cmd_str += f' --decryption-binary-path "{mp4dec_bin}"'
        return cmd_list, cmd_str

    def process_video_extraction(batch_id, subject_id, schedule_id, title="video", custom_cookie=None):
        return {"status": "error", "message": "Handler module not loaded"}

try:
    from vars import PORT
except ImportError:
    PORT = int(os.environ.get("PORT", 8000))

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
os.makedirs(DOWNLOAD_DIR, exist_ok=True)

app = Flask(__name__)


# ==============================================================================
# DOWNLOAD RUNNER
# ==============================================================================
def run_download_process(cmd_list):
    try:
        # Check binary existence
        n_bin = cmd_list[0]
        resolved = find_binary(n_bin)
        if resolved:
            cmd_list[0] = resolved

        subprocess.run(cmd_list, check=True)
        return True, "Download Successful"
    except subprocess.CalledProcessError as e:
        return False, f"Download failed (Exit code: {e.returncode})"
    except FileNotFoundError:
        return False, "N_m3u8DL-RE.exe nahi mila! Is script wale folder me rakhein ya PATH me add karein."
    except Exception as e:
        return False, str(e)


# ==============================================================================
# API ROUTES
# ==============================================================================
@app.route('/api/extract-single', methods=['POST'])
def api_extract_single():
    body = request.get_json(silent=True) or {}
    item = body.get('item', {})
    cookie = body.get('cookie', '')

    batch_id = item.get('batchId') or item.get('parentId')
    subject_id = item.get('subjectId')
    schedule_id = item.get('videoId') or item.get('scheduleId')
    title = item.get('title') or "video"

    if not (batch_id and subject_id and schedule_id):
        return jsonify({"status": "error", "message": "Missing batchId, subjectId, or videoId", "title": title}), 400

    result = process_video_extraction(batch_id, subject_id, schedule_id, title=title, custom_cookie=cookie)
    return jsonify(result)


@app.route('/api/download-now', methods=['POST'])
def api_download_now():
    body = request.get_json(silent=True) or {}
    mpd_url = body.get('mpd_url')
    drm_key = body.get('key')
    title = body.get('title', 'video')

    if not (mpd_url and drm_key):
        return jsonify({"status": "error", "message": "Missing MPD URL or DRM Key"}), 400

    cmd_list, _ = build_download_cmd(mpd_url, drm_key, title)
    success, msg = run_download_process(cmd_list)

    if success:
        return jsonify({"status": "success", "message": f"Successfully downloaded: {title}.mp4"})
    else:
        return jsonify({"status": "error", "message": msg}), 500


@app.route('/api/proxy', methods=['GET', 'POST'])
def api_proxy():
    if request.method == 'POST':
        data = request.get_json(silent=True) or {}
        new_proxy = data.get('proxy', '').strip()
        set_rarestudy_proxy(new_proxy)
        return jsonify({"status": "success", "proxy": new_proxy})
    return jsonify({"proxy": get_rarestudy_proxy()})


# ==============================================================================
# UI FRONTEND
# ==============================================================================
HTML_PAGE = """
<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>RareStudy Downloader (TestUK)</title>
  <script src="https://cdn.tailwindcss.com"></script>
  <link rel="stylesheet" href="https://cdnjs.cloudflare.com/ajax/libs/font-awesome/6.4.0/css/all.min.css">
  <style>
    body { background-color: #0f172a; color: #f8fafc; font-family: system-ui, -apple-system, sans-serif; }
    .glass-card { background: rgba(30, 41, 59, 0.75); backdrop-filter: blur(12px); border: 1px solid rgba(255, 255, 255, 0.08); }
  </style>
</head>
<body class="min-h-screen p-4 md:p-8 flex flex-col items-center">

  <div class="w-full max-w-4xl space-y-6">
    
    <!-- HEADER -->
    <div class="flex flex-col md:flex-row items-center justify-between border-b border-slate-800 pb-5 gap-3">
      <div>
        <h1 class="text-3xl font-black bg-gradient-to-r from-blue-400 via-indigo-400 to-purple-500 bg-clip-text text-transparent">
          <i class="fa-solid fa-cloud-arrow-down mr-2"></i>RareStudy Downloader
        </h1>
        <p class="text-slate-400 text-sm mt-1">Domain: <span class="text-indigo-400 font-mono">rarestudy.testuk.org</span> (Fast DRM Engine)</p>
      </div>
      <div class="flex items-center gap-2 text-xs bg-indigo-500/10 text-indigo-300 border border-indigo-500/20 px-3 py-1.5 rounded-full">
        <i class="fa-solid fa-folder-open text-amber-400"></i> Saves to: /downloads
      </div>
    </div>

    <!-- COOKIE SETTING -->
    <div class="glass-card rounded-2xl p-4">
      <div class="flex items-center justify-between cursor-pointer" onclick="document.getElementById('cookie-box').classList.toggle('hidden')">
        <div class="text-sm font-medium flex items-center gap-2">
          <i class="fa-solid fa-cookie text-amber-400"></i> Custom Cookies (Optional: Default cookies pre-configured)
        </div>
        <i class="fa-solid fa-chevron-down text-slate-400 text-xs"></i>
      </div>
      <div id="cookie-box" class="hidden mt-3 pt-3 border-t border-slate-700/50">
        <textarea id="cookie-input" rows="2" class="w-full bg-slate-900 border border-slate-700 rounded-xl p-3 text-xs text-slate-200 focus:outline-none focus:border-indigo-500 font-mono" placeholder="Paste updated cookies if session expired..."></textarea>
      </div>
    </div>

    <!-- MAIN CARD -->
    <div class="glass-card rounded-2xl p-6 space-y-5">
      <div class="border-2 border-dashed border-slate-700 hover:border-indigo-500 rounded-2xl p-8 text-center cursor-pointer transition-colors bg-slate-900/50" onclick="document.getElementById('file-input').click()">
        <input type="file" id="file-input" accept=".json" class="hidden" onchange="handleFile(event)">
        <i class="fa-solid fa-file-code text-4xl text-indigo-400 mb-3"></i>
        <p class="text-slate-200 font-medium">Click karein ya apni Course <span class="text-indigo-400 font-mono font-bold">.json</span> file yahan drag karein</p>
        <p class="text-slate-400 text-xs mt-1">Automatic subject & lecture detection</p>
      </div>

      <div id="file-info" class="hidden space-y-3 bg-slate-900/90 p-4 rounded-xl border border-slate-800 text-sm">
        <div class="flex items-center justify-between">
          <span class="font-bold text-slate-200" id="batch-title">Course Batch</span>
          <span id="total-videos-badge" class="text-xs bg-indigo-500/20 text-indigo-300 font-mono px-2.5 py-1 rounded-full"></span>
        </div>
        <div class="flex items-center gap-3 pt-2 border-t border-slate-800">
          <label class="text-xs text-slate-400 whitespace-nowrap">Filter Subject:</label>
          <select id="subject-filter" onchange="applySubjectFilter()" class="w-full bg-slate-800 border border-slate-700 rounded-lg p-2 text-xs text-slate-200 focus:outline-none focus:border-indigo-500">
            <option value="ALL">All Subjects</option>
          </select>
        </div>
      </div>

      <button id="start-btn" onclick="startExtraction()" class="w-full bg-gradient-to-r from-indigo-500 to-purple-600 hover:from-indigo-600 hover:to-purple-700 text-white font-semibold py-3.5 px-6 rounded-xl shadow-lg transition-all flex items-center justify-center gap-2">
        <i class="fa-solid fa-key"></i>
        <span id="btn-label">Extract All Streams & Keys</span>
      </button>

      <div id="prog-box" class="hidden space-y-2 pt-2">
        <div class="flex justify-between text-xs text-slate-400">
          <span id="prog-text">Extracting links...</span>
          <span id="prog-num" class="font-mono">0 / 0</span>
        </div>
        <div class="w-full bg-slate-800 rounded-full h-2.5 overflow-hidden">
          <div id="prog-bar" class="bg-indigo-500 h-2.5 rounded-full transition-all duration-200" style="width: 0%"></div>
        </div>
      </div>
    </div>

    <!-- RESULTS -->
    <div id="results-box" class="hidden space-y-4">
      <div class="flex items-center justify-between flex-wrap gap-2">
        <h2 class="text-lg font-bold text-slate-200 flex items-center gap-2">
          <i class="fa-solid fa-list-check text-indigo-400"></i> Extracted Videos
        </h2>
        <div class="flex flex-wrap gap-2">
          <button onclick="downloadAllDirectly()" id="btn-download-all" class="text-xs bg-gradient-to-r from-emerald-500 to-teal-600 hover:from-emerald-600 hover:to-teal-700 text-white px-3.5 py-2 rounded-lg font-bold flex items-center gap-1.5 shadow">
            <i class="fa-solid fa-download"></i> ⚡ Download All to PC
          </button>
          <button onclick="downloadBat()" class="text-xs bg-slate-800 hover:bg-slate-700 text-slate-200 px-3 py-2 rounded-lg font-medium flex items-center gap-1.5 border border-slate-700">
            <i class="fa-solid fa-terminal"></i> Get .BAT Script
          </button>
        </div>
      </div>
      <div id="cards-container" class="space-y-3"></div>
    </div>

  </div>

  <script>
    let allExtractedLectures = [];
    let activeLecturesList = [];
    let results = [];

    function handleFile(e) {
      const file = e.target.files[0];
      if (!file) return;

      const reader = new FileReader();
      reader.onload = function(evt) {
        try {
          const json = JSON.parse(evt.target.result);
          parseCourseJSON(json);
        } catch(err) {
          alert("Invalid JSON: " + err.message);
        }
      };
      reader.readAsText(file);
    }

    function parseCourseJSON(data) {
      allExtractedLectures = [];
      const subjectsMap = {};

      let batchId = (data.batch && (data.batch.id || data.batch._id)) || data.batchId || "67fbe8415ce253f88c3345f7";
      let batchName = (data.batch && data.batch.name) || data.batchName || "Course Batch";

      if (data.subjects && Array.isArray(data.subjects)) {
        data.subjects.forEach(subj => {
          const subjectId = subj.subjectId || subj.id || subj._id;
          const subjectName = subj.subject || subj.name || "Subject";
          subjectsMap[subjectName] = 0;

          if (subj.topics && Array.isArray(subj.topics)) {
            subj.topics.forEach(top => {
              const lecs = top.lectures || top.videos || [];
              if (Array.isArray(lecs)) {
                lecs.forEach(lec => {
                  const vId = lec.videoId || lec.scheduleId || lec.id;
                  if (vId) {
                    allExtractedLectures.push({
                      batchId: batchId,
                      subjectId: subjectId,
                      videoId: vId,
                      title: lec.title || lec.name || `Lecture_${vId}`,
                      subject: subjectName
                    });
                    subjectsMap[subjectName]++;
                  }
                });
              }
            });
          }
        });
      } else if (Array.isArray(data)) {
        data.forEach(item => {
          const vId = item.videoId || item.scheduleId || item.id;
          if (vId) {
            allExtractedLectures.push({
              batchId: item.batchId || batchId,
              subjectId: item.subjectId || '',
              videoId: vId,
              title: item.title || `Lecture_${vId}`,
              subject: item.subject || 'General'
            });
          }
        });
      }

      const filterSelect = document.getElementById('subject-filter');
      filterSelect.innerHTML = `<option value="ALL">All Subjects (${allExtractedLectures.length} Videos)</option>`;
      for (const [sName, count] of Object.entries(subjectsMap)) {
        filterSelect.innerHTML += `<option value="${sName}">${sName} (${count} Videos)</option>`;
      }

      document.getElementById('batch-title').innerText = batchName;
      document.getElementById('total-videos-badge').innerText = `${allExtractedLectures.length} Lectures Found`;
      document.getElementById('file-info').classList.remove('hidden');

      applySubjectFilter();
    }

    function applySubjectFilter() {
      const selected = document.getElementById('subject-filter').value;
      if (selected === "ALL") {
        activeLecturesList = [...allExtractedLectures];
      } else {
        activeLecturesList = allExtractedLectures.filter(x => x.subject === selected);
      }
      document.getElementById('btn-label').innerText = `Extract (${activeLecturesList.length} Videos)`;
    }

    async function startExtraction() {
      if (!activeLecturesList.length) return alert("Pehle JSON file upload karein!");

      const cookie = document.getElementById('cookie-input').value.trim();
      const progBox = document.getElementById('prog-box');
      const progBar = document.getElementById('prog-bar');
      const progNum = document.getElementById('prog-num');
      const progText = document.getElementById('prog-text');
      const resBox = document.getElementById('results-box');
      const container = document.getElementById('cards-container');
      const startBtn = document.getElementById('start-btn');

      container.innerHTML = "";
      results = [];
      resBox.classList.remove('hidden');
      progBox.classList.remove('hidden');
      startBtn.disabled = true;
      startBtn.classList.add('opacity-50');

      const total = activeLecturesList.length;

      for (let i = 0; i < total; i++) {
        const itm = activeLecturesList[i];
        progNum.innerText = `${i+1} / ${total}`;
        progText.innerText = `[${itm.subject}] ${itm.title}`;
        progBar.style.width = `${((i+1)/total)*100}%`;

        try {
          const resp = await fetch('/api/extract-single', {
            method: 'POST',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({ item: itm, cookie: cookie })
          });
          const data = await resp.json();
          results.push(data);
          addCard(data, i);
        } catch(err) {
          const fail = { status: 'error', title: itm.title, message: err.message };
          results.push(fail);
          addCard(fail, i);
        }
      }

      progText.innerText = "All streams extracted!";
      startBtn.disabled = false;
      startBtn.classList.remove('opacity-50');
    }

    function addCard(res, idx) {
      const c = document.getElementById('cards-container');
      const div = document.createElement('div');
      div.className = "glass-card p-4 rounded-xl space-y-2.5";
      div.id = `card-${idx}`;

      if (res.status === 'success') {
        div.innerHTML = `
          <div class="flex items-center justify-between flex-wrap gap-2">
            <span class="font-semibold text-slate-100">${res.title}</span>
            <div class="flex items-center gap-2">
              <button onclick="downloadSingle(${idx})" id="dl-btn-${idx}" class="text-xs bg-emerald-600 hover:bg-emerald-500 text-white px-3 py-1 rounded-lg font-bold flex items-center gap-1 shadow">
                <i class="fa-solid fa-download"></i> Download Now
              </button>
              <span class="text-xs bg-indigo-500/20 text-indigo-300 px-2 py-0.5 rounded">Ready</span>
            </div>
          </div>
          <div class="space-y-1.5 text-xs font-mono">
            <div class="bg-slate-900 p-2 rounded flex justify-between">
              <span class="truncate text-slate-400"><b>KEY:</b> ${res.key}</span>
              <button onclick="navigator.clipboard.writeText('${res.key}')" class="text-indigo-400 ml-2">Copy</button>
            </div>
            <div class="bg-slate-900 p-2 rounded flex justify-between">
              <span class="truncate text-slate-400"><b>CMD:</b> ${res.cmd}</span>
              <button onclick="navigator.clipboard.writeText(\`${res.cmd}\`)" class="text-indigo-400 ml-2">Copy CMD</button>
            </div>
          </div>
          <div id="dl-status-${idx}" class="text-xs font-medium hidden"></div>
        `;
      } else {
        div.innerHTML = `
          <div class="flex items-center justify-between">
            <span class="font-semibold text-slate-300">${res.title}</span>
            <span class="text-xs bg-rose-500/20 text-rose-400 px-2 py-0.5 rounded">Failed</span>
          </div>
          <p class="text-xs text-rose-300 font-mono">${res.message}</p>
        `;
      }
      c.appendChild(div);
    }

    async function downloadSingle(idx) {
      const item = results[idx];
      const btn = document.getElementById(`dl-btn-${idx}`);
      const status = document.getElementById(`dl-status-${idx}`);

      btn.disabled = true;
      btn.innerHTML = `<i class="fa-solid fa-spinner fa-spin"></i> Downloading...`;
      status.classList.remove('hidden');
      status.innerHTML = `<span class="text-amber-400"><i class="fa-solid fa-spinner fa-spin mr-1"></i> Downloading via N_m3u8DL-RE + mp4decrypt...</span>`;

      try {
        const resp = await fetch('/api/download-now', {
          method: 'POST',
          headers: {'Content-Type': 'application/json'},
          body: JSON.stringify({ mpd_url: item.mpd_url, key: item.key, title: item.title })
        });
        const d = await resp.json();

        if (d.status === 'success') {
          btn.className = "text-xs bg-slate-700 text-slate-400 px-3 py-1 rounded-lg cursor-not-allowed";
          btn.innerHTML = `<i class="fa-solid fa-check"></i> Downloaded`;
          status.innerHTML = `<span class="text-emerald-400"><i class="fa-solid fa-circle-check mr-1"></i> Saved: /downloads/${item.title}.mp4</span>`;
        } else {
          btn.disabled = false;
          btn.innerHTML = `<i class="fa-solid fa-rotate-right"></i> Retry`;
          status.innerHTML = `<span class="text-rose-400"><i class="fa-solid fa-triangle-exclamation mr-1"></i> Error: ${d.message}</span>`;
        }
      } catch(err) {
        btn.disabled = false;
        btn.innerHTML = `<i class="fa-solid fa-rotate-right"></i> Retry`;
        status.innerHTML = `<span class="text-rose-400">Request Error: ${err.message}</span>`;
      }
    }

    async function downloadAllDirectly() {
      const valid = results.map((r, i) => ({ ...r, index: i })).filter(r => r.status === 'success');
      if (!valid.length) return alert("Pehle streams extract karein!");

      const btn = document.getElementById('btn-download-all');
      btn.disabled = true;
      btn.classList.add('opacity-50');

      for (let item of valid) {
        await downloadSingle(item.index);
      }

      btn.disabled = false;
      btn.classList.remove('opacity-50');
      alert("All selected videos downloaded successfully!");
    }

    function downloadBat() {
      const cmds = results.filter(r => r.status === 'success').map(r => r.cmd);
      if (!cmds.length) return alert("Koi command nahi mila!");
      const content = "@echo off\\r\\nchcp 65001 > nul\\r\\necho Starting DRM Downloads with TestUK Headers...\\r\\n\\r\\n" + cmds.join("\\r\\n\\r\\n") + "\\r\\n\\r\\necho All Downloads Finished!\\r\\npause";
      const blob = new Blob([content], { type: 'text/plain' });
      const a = document.createElement('a');
      a.href = URL.createObjectURL(blob);
      a.download = "download_all_testuk.bat";
      a.click();
    }
  </script>
</body>
</html>
"""

@app.route('/')
def index():
    return render_template_string(HTML_PAGE)

if __name__ == '__main__':
    print("=" * 65)
    print("🚀 RareStudy Downloader Running (rarestudy.testuk.org)")
    print(f"📁 Downloads Folder: {DOWNLOAD_DIR}")
    print(f"👉 Browser me open karein: http://localhost:{PORT}")
    print("=" * 65)
    app.run(host='0.0.0.0', port=PORT)
