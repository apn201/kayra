#!/usr/bin/env python3
"""Screenshots of the panel and the 16:9 cover, with headless Edge or Chrome. Needs the panel running.

    python tools/dev_server.py &      then
    python tools/screens.py           writes docs/img/*.png
"""
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "docs" / "img"
URL = sys.argv[1] if len(sys.argv) > 1 else "http://localhost:8201"
SHOTS = {"home": (1600, 1000), "ai": (1600, 1200), "curve": (1600, 1100), "setup": (1600, 1200),
         "doc": (1600, 1400), "box": (1600, 1300), "notebook": (1600, 1200), "live": (1600, 1000)}
CANDIDATES = [r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
              r"C:\Program Files\Google\Chrome\Application\chrome.exe", "msedge", "google-chrome", "chromium"]


def browser() -> str:
    for c in CANDIDATES:
        if Path(c).is_file() or shutil.which(c):
            return c
    raise SystemExit("No Edge or Chrome found for headless screenshots.")


def shot(exe: str, url: str, path: Path, w: int, h: int) -> None:
    subprocess.run([exe, "--headless=new", "--disable-gpu", "--hide-scrollbars", f"--window-size={w},{h}",
                    "--virtual-time-budget=12000", f"--screenshot={path}", url],
                   capture_output=True, timeout=120)
    print(path.relative_to(ROOT), "ok" if path.is_file() else "FAILED")


if __name__ == "__main__":
    exe = browser()
    OUT.mkdir(parents=True, exist_ok=True)
    shot(exe, f"{URL}/cover.html", OUT / "cover.png", 1920, 1080)
    for name, (w, h) in SHOTS.items():
        shot(exe, f"{URL}/?shot=1#{name}", OUT / f"{name}.png", w, h)
