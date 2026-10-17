#!/usr/bin/env python3
"""The panel server: serves web/ and artifacts/, answers /api/state live (or from replay). No build step.

    python tools/dev_server.py                     http://localhost:8201, live where possible
    python tools/dev_server.py 8201 --host 0.0.0.0 for a deployment behind a proxy or tunnel
    python tools/dev_server.py --replay            replay only, no network calls

/api/state   kayra.live.state(): LIVE (FMI + Home Assistant), LIVE OUTDOOR (FMI only), or REPLAY
/api/live    logged live hours (data/live/*.jsonl) for the curve screen
Read-only everywhere. Home Assistant is reached only if HA_URL and HA_TOKEN are in .env.
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
WEB, ART = ROOT / "web", ROOT / "artifacts"
REPLAY_ONLY = False


def replay_state() -> dict:
    rows = json.loads((ART / "replay.json").read_text(encoding="utf-8"))["rows"]
    i = int(time.time() // 2) % len(rows)  # one recorded hour every 2 s, same for every viewer
    return {"data": "REPLAY", "index": i, "row": rows[i], "rows": len(rows)}


def state() -> dict:
    if REPLAY_ONLY:
        return replay_state()
    try:
        from kayra import live
        return live.state()
    except Exception as exc:  # live is a bonus; the panel must never go dark
        s = replay_state()
        s["note"] = f"live unavailable: {type(exc).__name__}"
        return s


def history() -> list:
    if REPLAY_ONLY:
        return []
    try:
        from kayra import live
        return live.history()
    except Exception:
        return []


class H(SimpleHTTPRequestHandler):
    def translate_path(self, path):
        p = path.split("?", 1)[0]
        if p.startswith("/artifacts/"):
            return str(ART / p[len("/artifacts/"):])
        return str(WEB / (p.lstrip("/") or "index.html"))

    def _json(self, obj):
        body = json.dumps(obj).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        if self.path.startswith("/api/state"):
            return self._json(state())
        if self.path.startswith("/api/live"):
            return self._json(history())
        super().do_GET()

    def end_headers(self):
        self.send_header("Cache-Control", "no-store")  # always the latest panel and artifacts
        super().end_headers()

    def log_message(self, *a):
        pass


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("port", nargs="?", type=int, default=8201)
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--replay", action="store_true")
    a = ap.parse_args()
    REPLAY_ONLY = a.replay
    print(f"Käyrä panel on http://{a.host}:{a.port}  ({'replay only' if a.replay else 'live where possible'})")
    ThreadingHTTPServer((a.host, a.port), H).serve_forever()
