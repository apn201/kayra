#!/usr/bin/env python3
"""Copy the artifacts the panel reads into web/artifacts/ for static hosting (Vercel).

Never copies the LLM archive's secrets - it has none; keys live only in .env - but
does skip logs. Run after `python -m kayra.run all`, before deploying.
"""
import shutil
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SRC, DST = ROOT / "artifacts", ROOT / "web" / "artifacts"
FILES = ["real.json", "synth.json", "benchmark.json", "replay.json", "explain.json", "readings.json", "points.json", "context.json", "writeup.json", "model_check.json",
         "document.md", "llm_archive.jsonl", "eval.json"]

DST.mkdir(parents=True, exist_ok=True)
for name in FILES:
    if (SRC / name).is_file():
        shutil.copy2(SRC / name, DST / name)
        print("copied", name)
