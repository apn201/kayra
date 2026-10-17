"""Vercel function: GET /api/state.

This version serves the recorded replay only, labelled REPLAY: one recorded hour
every 2 seconds, the same hour for every viewer. When the house pusher is
deployed it will POST to /api/push and this function will serve the latest
push while it is under 15 minutes old, falling back to replay otherwise.
"""
from http.server import BaseHTTPRequestHandler
import json
import time
from pathlib import Path

REPLAY = Path(__file__).resolve().parent.parent / "web" / "artifacts" / "replay.json"


class handler(BaseHTTPRequestHandler):
    def do_GET(self):
        rows = json.loads(REPLAY.read_text(encoding="utf-8"))["rows"]
        i = int(time.time() // 2) % len(rows)
        body = json.dumps({"data": "REPLAY", "index": i, "row": rows[i], "rows": len(rows)}).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)
