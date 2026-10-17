#!/usr/bin/env python3
"""AMD benchmark: every chat model on the AMD token factory, on Käyrä's own tasks, graded by code.

    python tools/amd_bench.py                 all chat models, 2 repeats
    python tools/amd_bench.py --repeats 3 --models DeepSeek-V4.1-Flash Qwen3.8-27B

Tasks (same as tools/llm_check.py, from kayra's real prompts):
  programs   hypothesis programs from an evidence packet -> structure-language validator
  operator   plain-language operator note -> one program that must use T_room
  prose      three sentences from a numbers packet -> guardrails (every number must be in the packet)

Per model: share of valid programs, operator pass rate, grounded prose share, median latency,
completion tokens per second, cost per call (from the API's own usage), and a combined score.
Also, from artifacts/llm_archive.jsonl: the same model on AMD vs the OpenRouter fallback, latency
side by side. Writes artifacts/amd_bench.json. Models run in parallel; the API allows 20 requests
a minute per user, so calls are paced.
"""
from __future__ import annotations

import argparse
import concurrent.futures as cf
import json
import statistics
import sys
import threading
import time
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from kayra import client, guardrails  # noqa: E402
from kayra.hypothesize import PROMPT  # noqa: E402
import importlib.util  # noqa: E402

_spec = importlib.util.spec_from_file_location("llm_check", ROOT / "tools" / "llm_check.py")
lc = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(lc)

CHAT = ["DeepSeek-V4.1-Flash", "DeepSeek-V4-Flash", "Qwen3.8-27B", "Qwen3.8-Flash-Next", "GLM-5.3-Flash",
        "Gemma-4-31B-IT", "MiMo-V2.6-Flash", "MiniCPM5-2B"]
_pace = threading.Lock()
_last = [0.0]


def call(cfg, model, system, user):
    with _pace:  # at most one request start every 3.2 s across threads: under 20 a minute
        wait = _last[0] + 3.2 - time.time()
        if wait > 0:
            time.sleep(wait)
        _last[0] = time.time()
    body = json.dumps({"model": model, "max_tokens": 8000, "temperature": 0.4,
                       "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}]}).encode()
    req = urllib.request.Request(cfg["base_url"] + "/chat/completions", data=body, method="POST",
                                 headers={"Content-Type": "application/json", "Authorization": f"Bearer {cfg['api_key']}"})
    t = time.time()
    for attempt in range(3):
        try:
            with urllib.request.urlopen(req, timeout=300, context=client._ssl()) as r:
                d = json.loads(r.read())
                left = r.headers.get("x-ratelimit-remaining-user-daily-usd")
            dt = time.time() - t
            m = (d.get("choices") or [{}])[0].get("message") or {}
            u = d.get("usage") or {}
            text = (m.get("content") or "").strip() or (m.get("reasoning_content") or m.get("reasoning") or "")
            client._archive({"t": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(t)), "purpose": "amd bench", "role": "bench",
                             "backend": "amd", "label": "", "base_url": cfg["base_url"], "model": d.get("model", model),
                             "prompt_hash": client.prompt_hash(system, user), "system": system, "user": user,
                             "content": m.get("content") or "", "reasoning_content": "", "usage": u, "latency_s": round(dt, 2)})
            return {"ok": True, "text": text, "s": round(dt, 1), "tokens": u.get("completion_tokens") or 0,
                    "cost": float(u.get("cost") or 0), "left": left}
        except urllib.error.HTTPError as e:
            if e.code in (429, 502, 503, 504) and attempt < 2:
                time.sleep(20 * (attempt + 1))
                continue
            return {"ok": False, "error": f"HTTP {e.code}", "s": round(time.time() - t, 1)}
        except Exception as e:  # timeout
            if attempt < 2:
                continue
            return {"ok": False, "error": type(e).__name__, "s": round(time.time() - t, 1)}


def bench_model(cfg, model, repeats):
    runs = []
    for i in range(repeats):
        for task, (system, user) in {
            "programs": (PROMPT, "Round 1.\n\n```json\n" + json.dumps(lc.EVIDENCE, indent=1) + "\n```"),
            "operator": (PROMPT, lc.OPERATOR_NOTE + "\n\nReturn a JSON array with one program."),
            "prose": ("Write for a maintenance engineer. Use only numbers from the packet, copied exactly. "
                      "Return JSON {\"lines\": [three sentences]}.", json.dumps(lc.PROSE_PACKET)),
        }.items():
            r = call(cfg, model, system, user)
            row = {"task": task, "rep": i, **{k: v for k, v in r.items() if k != "text"}}
            if r["ok"]:
                if task == "programs":
                    g = lc.grade_programs(r["text"])
                    row |= {"returned": g["returned"], "valid": g["valid"]}
                elif task == "operator":
                    g = lc.grade_programs(r["text"])
                    props = client.extract_json(r["text"]) or []
                    exprs = [p.get("expr", "") for p in (props if isinstance(props, list) else [props]) if isinstance(p, dict)]
                    row |= {"pass": bool(g["valid"] and any("T_room" in e for e in exprs))}
                else:
                    ans = client.extract_json(r["text"])
                    lines = ans.get("lines", []) if isinstance(ans, dict) else []
                    known = guardrails.known_numbers(lc.PROSE_PACKET)
                    known |= {k.lstrip("-") for k in known}
                    bad = [l for l in lines if guardrails.ungrounded_numbers(str(l), known)]
                    row |= {"lines": len(lines), "grounded": len(lines) - len(bad)}
            runs.append(row)
            print(model, task, i, {k: v for k, v in row.items() if k not in ("task", "rep")}, flush=True)
    return summarise(model, runs)


def summarise(model, runs):
    ok = [r for r in runs if r["ok"]]
    prog = [r for r in ok if r["task"] == "programs"]
    oper = [r for r in ok if r["task"] == "operator"]
    pros = [r for r in ok if r["task"] == "prose"]
    valid_share = sum(r["valid"] for r in prog) / max(1, sum(max(r["returned"], 1) for r in prog)) if prog else 0
    oper_rate = sum(r["pass"] for r in oper) / len(oper) if oper else 0
    prose_rate = sum(r["grounded"] for r in pros) / max(1, sum(max(r["lines"], 1) for r in pros)) if pros else 0
    lat = [r["s"] for r in ok]
    tps = [r["tokens"] / r["s"] for r in ok if r["s"] > 0 and r["tokens"]]
    return {"model": model, "calls": len(runs), "failed": len(runs) - len(ok),
            "valid_program_share": round(valid_share, 2), "operator_pass_rate": round(oper_rate, 2),
            "grounded_prose_share": round(prose_rate, 2),
            "score": round((valid_share + oper_rate + prose_rate) / 3 * (len(ok) / max(1, len(runs))), 3),
            "median_latency_s": round(statistics.median(lat), 1) if lat else None,
            "median_tokens_per_s": round(statistics.median(tps), 1) if tps else None,
            "cost_usd_per_call": round(sum(r["cost"] for r in ok) / len(ok), 6) if ok else None,
            "runs": runs}


def amd_vs_fallback():
    """Same model, two endpoints, from the archive: latency of real Käyrä calls."""
    rows = [json.loads(l) for l in (ROOT / "artifacts" / "llm_archive.jsonl").read_text(encoding="utf-8").splitlines() if l]
    out = {}
    for be in ("amd", "fallback"):
        lat = [r["latency_s"] for r in rows if r.get("backend") == be and r.get("role") != "bench"
               and "deepseek-v4.1-flash" in str(r.get("model", "")).lower() and r.get("latency_s")]
        if lat:
            out[be] = {"calls": len(lat), "median_latency_s": round(statistics.median(lat), 1)}
    return out


def from_log(path: Path) -> list:
    """Rebuild results from a run log (one line per call). Used when slow models are cut short:
    their missing calls are counted as not completed, never guessed."""
    import ast
    runs: dict = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        parts = line.split(" ", 3)
        if len(parts) == 4 and parts[0] in CHAT and parts[1] in ("programs", "operator", "prose"):
            runs.setdefault(parts[0], []).append({"task": parts[1], "rep": int(parts[2]), **ast.literal_eval(parts[3])})
    return [summarise(m, r) for m, r in runs.items()]


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--models", nargs="*", default=CHAT)
    ap.add_argument("--repeats", type=int, default=2)
    ap.add_argument("--from-log", help="summarise an interrupted run from its log")
    a = ap.parse_args()
    cfg = client.config()
    if cfg["backend"] != "amd":
        raise SystemExit("KAYRA_LLM_BACKEND must be amd for the AMD benchmark.")
    t0 = time.time()
    if a.from_log:
        res = from_log(Path(a.from_log))
        expected = 3 * a.repeats
        for r in res:
            r["not_completed"] = expected - r["calls"]
    else:
        with cf.ThreadPoolExecutor(len(a.models)) as ex:
            res = list(ex.map(lambda m: bench_model(cfg, m, a.repeats), a.models))
    res.sort(key=lambda r: (-r["score"], r["median_latency_s"] or 999))
    out = {"generated_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()), "endpoint": "AMD token factory",
           "base_url": cfg["base_url"], "repeats": a.repeats,
           "wall_s": "about 1500 (stopped: two models were still timing out)" if a.from_log else round(time.time() - t0, 1),
           "note": "Qwen3.8-27B and GLM-5.3-Flash timed out on the programs task (3 tries x 300 s); the run was stopped and their remaining calls are counted as not completed." if a.from_log else None,
           "tasks": ["programs (validator)", "operator note -> program (validator + T_room)", "prose (guardrails)"],
           "models": res, "same_model_amd_vs_fallback": amd_vs_fallback(),
           "pick": {"code": max(res, key=lambda r: (r["valid_program_share"] + r["operator_pass_rate"], -(r["median_latency_s"] or 999)))["model"],
                    "text": max(res, key=lambda r: (r["grounded_prose_share"], -(r["median_latency_s"] or 999)))["model"]}}
    (ROOT / "artifacts" / "amd_bench.json").write_text(json.dumps(out, indent=1), encoding="utf-8")
    print(json.dumps({k: out[k] for k in ("wall_s", "pick", "same_model_amd_vs_fallback")}, indent=1))
    for r in res:
        print(f"{r['model']:24} score {r['score']:.2f}  programs {r['valid_program_share']:.2f}  operator {r['operator_pass_rate']:.2f}  "
              f"prose {r['grounded_prose_share']:.2f}  {r['median_latency_s']} s  {r['median_tokens_per_s']} tok/s  ${r['cost_usd_per_call']}/call  failed {r['failed']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
