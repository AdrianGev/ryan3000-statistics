import re
import json
import requests
import os
from http.server import HTTPServer, BaseHTTPRequestHandler
from urllib.parse import urlparse
import threading
import time

from dotenv import load_dotenv
load_dotenv()

API_KEY = os.getenv("YOUTUBE_API_KEY")
if not API_KEY:
    raise RuntimeError("Missing YOUTUBE_API_KEY")

CHANNEL_ID = "UCjXPeBJ0L57q7548RtW99Fg"
MAX_VIDEOS = 400

SUB_LINE_RE = re.compile(
    r"^\s*(?:current\s+)?(?:subs(?:cribers)?|subscribers)\s*[:=\-]\s*(.+?)\s*$",
    re.IGNORECASE | re.MULTILINE,
)

CHICK_LINE_RE = re.compile(
    r"^\s*(?:current\s+)?chickens?\s*[:=\-]\s*(.+?)\s*$",
    re.IGNORECASE | re.MULTILINE,
)

def yt_get(url, params):
    r = requests.get(url, params=params, timeout=20)
    r.raise_for_status()
    return r.json()

def get_uploads_playlist_id():
    data = yt_get(
        "https://www.googleapis.com/youtube/v3/channels",
        {"part": "contentDetails", "id": CHANNEL_ID, "key": API_KEY},
    )
    return data["items"][0]["contentDetails"]["relatedPlaylists"]["uploads"]

def get_playlist_video_ids(playlist_id):
    ids = []
    page_token = None
    while len(ids) < MAX_VIDEOS:
        data = yt_get(
            "https://www.googleapis.com/youtube/v3/playlistItems",
            {
                "part": "contentDetails",
                "playlistId": playlist_id,
                "maxResults": 50,
                "pageToken": page_token,
                "key": API_KEY,
            },
        )
        for it in data.get("items", []):
            ids.append(it["contentDetails"]["videoId"])
            if len(ids) >= MAX_VIDEOS:
                break
        page_token = data.get("nextPageToken")
        if not page_token:
            break
    return ids

def get_video_snippets(video_ids):
    rows = []
    for i in range(0, len(video_ids), 50):
        batch = video_ids[i : i + 50]
        data = yt_get(
            "https://www.googleapis.com/youtube/v3/videos",
            {"part": "snippet", "id": ",".join(batch), "key": API_KEY},
        )
        for v in data.get("items", []):
            snip = v.get("snippet", {})
            rows.append(
                {
                    "publishedAt": snip.get("publishedAt", ""),
                    "title": snip.get("title", ""),
                    "description": snip.get("description", ""),
                    "videoId": v.get("id", ""),
                }
            )
    rows.sort(key=lambda r: r["publishedAt"])
    return rows

def parse_count(raw: str):
    """
    handles edge cases:
      "214k" -> 214000
      "~110" -> 110
      "~110 (+10!)" -> 110
      "207k (+10!)" -> 207000
      "214.5k" -> 214500
      "1.2m" -> 1200000
      "12,345" -> 12345
    """
    if not raw:
        return None

    s = raw.strip().lower()

    # grab the first number looking token (optionally starting with ~ or ≈ or km/s as a joke)
    m = re.search(r"[~≈]?\s*\d[\d,]*\.?\d*\s*[km]?", s)
    if not m:
        return None

    token = m.group(0).replace(" ", "")
    token = token.lstrip("~≈")

    suffix = ""
    if token and token[-1] in ("k", "m"):
        suffix = token[-1]
        token = token[:-1]

    token = token.replace(",", "")

    try:
        val = float(token)
    except ValueError:
        return None

    if suffix == "k":
        val *= 1_000
    elif suffix == "m":
        val *= 1_000_000

    return int(round(val))

def extract_numbers(desc):
    subs = chicks = None

    sub_m = SUB_LINE_RE.search(desc)
    if sub_m:
        subs = parse_count(sub_m.group(1))

    chick_m = CHICK_LINE_RE.search(desc)
    if chick_m:
        chicks = parse_count(chick_m.group(1))

    return subs, chicks

def get_youtube_data():
    uploads = get_uploads_playlist_id()
    video_ids = get_playlist_video_ids(uploads)
    vids = get_video_snippets(video_ids)

    out = []
    day = 0

    for v in vids:
        subs, chicks = extract_numbers(v["description"])

        # skip videos that don't have the stats
        if subs is None and chicks is None:
            continue

        day += 1
        out.append(
            {
                "day": day,
                "publishedAt": v["publishedAt"],
                "title": v["title"],
                "videoId": v["videoId"],
                "subscribers": subs,
                "chickens": chicks,
            }
        )

    return out

class RequestHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        parsed_path = urlparse(self.path)
        
        if parsed_path.path == "/api/data":
            try:
                data = get_youtube_data()
                self.send_response(200)
                self.send_header('Content-Type', 'application/json')
                self.send_header('Access-Control-Allow-Origin', '*')
                self.end_headers()
                self.wfile.write(json.dumps(data).encode())
            except Exception as e:
                self.send_response(500)
                self.send_header('Content-Type', 'application/json')
                self.send_header('Access-Control-Allow-Origin', '*')
                self.end_headers()
                self.wfile.write(json.dumps({"error": str(e)}).encode())
        else:
            self.send_response(404)
            self.end_headers()

    def log_message(self, format, *args):
        # Suppress default logging
        pass

def run_server(port=8000):
    server = HTTPServer(('localhost', port), RequestHandler)
    print(f"Server running on http://localhost:{port}")
    print("API endpoint: http://localhost:8000/api/data")
    server.serve_forever()

if __name__ == "__main__":
    run_server()
