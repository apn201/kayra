# Provenance: adapted from Apps/Virta, virta/nebius_client.py, 2026-10-17.
# Changes: standard library HTTP instead of the openai package (no extra
# dependency on the droplet, nothing that can drag a CUDA torch in through pip);
# base URL, key and model from KAYRA_LLM_* env vars, pointed at the vLLM endpoint
# on AMD Developer Cloud. Kept: the empty-`content` / `reasoning_content`
# fallback and last-complete-JSON-block extraction.
"""OpenAI-compatible chat client for the language model, plus the call archive.

Backends, chosen by KAYRA_LLM_BACKEND (or the caller):
    amd      vLLM on AMD Developer Cloud.               Status: ONLINE
    other    any other OpenAI-compatible endpoint.      Status: STAND-IN ENDPOINT (named)
    archive  replay recorded calls from artifacts/llm_archive.jsonl, matched by
             prompt hash. Never invents a reply: a miss is an error. Status: ARCHIVE
    none     no language model. Callers fall back to hand-written stand-ins,
             which are labelled as such everywhere. Status: OFFLINE

Every live call and its reply is appended to the archive, so a judge can read
exactly what the model was given and what it said.
"""

from __future__ import annotations

import hashlib
import json
import os
import time
import ssl
import urllib.error
import urllib.request
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
ARCHIVE = ROOT / "artifacts" / "llm_archive.jsonl"


def _env_file() -> dict:
    env = {}
    f = ROOT / ".env"
    if f.is_file():
        for line in f.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, v = line.split("=", 1)
                env[k.strip()] = v.strip().strip('"').strip("'")
    return env


def config() -> dict:
    env = {**_env_file(), **os.environ}
    return {
        "backend": env.get("KAYRA_LLM_BACKEND", "none"),
        "base_url": env.get("KAYRA_LLM_BASE_URL", "").rstrip("/"),
        "api_key": env.get("KAYRA_LLM_API_KEY", ""),
        "model": env.get("KAYRA_LLM_MODEL", ""),
        # optional split: one model writes programs, another writes prose
        "model_code": env.get("KAYRA_LLM_MODEL_CODE", "") or env.get("KAYRA_LLM_MODEL", ""),
        "model_text": env.get("KAYRA_LLM_MODEL_TEXT", "") or env.get("KAYRA_LLM_MODEL", ""),
        "temperature": float(env.get("KAYRA_LLM_TEMPERATURE", "0.4")),
        "label": env.get("KAYRA_LLM_LABEL", ""),
        "timeout_s": float(env.get("KAYRA_LLM_TIMEOUT_S", "240")),
        "max_tokens": int(env.get("KAYRA_LLM_MAX_TOKENS", "8000")),
        # fallback endpoint for when the primary (AMD) times out or is rate-limited
        "fallback": {
            "backend": "fallback",
            "base_url": env.get("KAYRA_LLM_FALLBACK_BASE_URL", "").rstrip("/"),
            "api_key": env.get("KAYRA_LLM_FALLBACK_API_KEY", ""),
            "model": env.get("KAYRA_LLM_FALLBACK_MODEL", ""),
            "label": env.get("KAYRA_LLM_FALLBACK_LABEL", "fallback, not AMD"),
        } if env.get("KAYRA_LLM_FALLBACK_BASE_URL") else None,
    }


# which endpoint actually answered, per process - goes into artifact metadata
STATS = {"amd": 0, "other": 0, "fallback": 0, "archive": 0}
_PRIMARY_DOWN_UNTIL = 0.0
_LAST_HEADERS: dict = {}


def list_models(cfg: dict | None = None) -> list[str]:
    """GET {base}/models - the ids the endpoint serves."""
    cfg = cfg or config()
    req = urllib.request.Request(cfg["base_url"] + "/models", headers={"Authorization": f"Bearer {cfg['api_key']}"})
    try:
        with urllib.request.urlopen(req, timeout=30, context=_ssl()) as r:
            data = json.loads(r.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        raise LLMError(f"HTTP {exc.code} from {cfg['base_url']}/models") from None
    except (urllib.error.URLError, TimeoutError) as exc:
        raise LLMError(f"could not reach {cfg['base_url']}: {exc}") from None
    return [m.get("id") for m in data.get("data", []) if m.get("id")]


def status(cfg: dict | None = None) -> str:
    cfg = cfg or config()
    base = {"amd": "ONLINE", "other": f"STAND-IN ENDPOINT ({cfg['label'] or 'not AMD'})",
            "archive": "ARCHIVE", "none": "OFFLINE"}.get(cfg["backend"], "OFFLINE")
    if cfg["backend"] == "amd" and STATS["fallback"]:
        base += f" (AMD {STATS['amd']} calls, {cfg['fallback']['label']} {STATS['fallback']} calls)"
    elif cfg["backend"] == "amd" and STATS["amd"]:
        base += f" (AMD {STATS['amd']} calls, no fallback)"
    return base


class LLMError(RuntimeError):
    pass


@dataclass
class Reply:
    text: str
    source: str           # content | reasoning_content | archive
    model: str
    backend: str
    prompt_hash: str
    usage: dict


def prompt_hash(system: str, user: str) -> str:
    return hashlib.sha256((system + "\x00" + user).encode("utf-8")).hexdigest()[:16]


def chat(system: str, user: str, *, purpose: str, cfg: dict | None = None, role: str = "code",
         model: str | None = None, _retry: bool = True) -> Reply:
    """One call to the primary endpoint; on timeout or rate limit, the fallback endpoint (labelled)."""
    global _PRIMARY_DOWN_UNTIL
    cfg = dict(cfg or config())
    fb = cfg.get("fallback")
    if cfg["backend"] == "amd":
        # AMD first, patiently: long reasoning calls take minutes and the API allows 20 requests a
        # minute per user. Measured 2026-10-18: a full hypothesis call costs about $0.0005-0.00075
        # of the $1 daily allowance, so time, not money, is the constraint.
        try:
            return _chat(system, user, purpose=purpose, cfg=dict(cfg, timeout_s=max(cfg["timeout_s"], 300)),
                         role=role, model=model, _retry=_retry, waits=[20, 40])
        except LLMError as exc:
            if not (fb and fb["base_url"]):
                raise
            why = str(exc)[:120]
        fcfg = dict(cfg, **fb, model_code=fb["model"], model_text=fb["model"])
        rep_ = _chat(system, user, purpose=f"{purpose} [fallback: {why}]", cfg=fcfg, role=role, model=fb["model"],
                     _retry=_retry, waits=[15, 30])
        return rep_
    return _chat(system, user, purpose=purpose, cfg=cfg, role=role, model=model, _retry=_retry)


def _chat(system: str, user: str, *, purpose: str, cfg: dict, role: str = "code",
          model: str | None = None, _retry: bool = True, waits: list | None = None) -> Reply:
    cfg = dict(cfg)
    cfg["model"] = model or cfg.get(f"model_{role}") or cfg["model"]
    ph = prompt_hash(system, user)
    if cfg["backend"] == "archive":
        STATS["archive"] += 1
        return _from_archive(ph)
    if cfg["backend"] not in ("amd", "other", "fallback"):
        raise LLMError("no language model configured (KAYRA_LLM_BACKEND=none)")
    if not cfg["base_url"] or not cfg["model"]:
        raise LLMError("KAYRA_LLM_BASE_URL and KAYRA_LLM_MODEL must be set")
    payload = {"model": cfg["model"], "max_tokens": cfg["max_tokens"], "temperature": cfg["temperature"],
               "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}]}
    if "openrouter.ai" in cfg["base_url"]:
        # cap the hidden reasoning so a reasoning model always gets to the answer
        payload["reasoning"] = {"max_tokens": int(os.environ.get("KAYRA_LLM_REASONING_MAX", "3000"))}
    body = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(cfg["base_url"] + "/chat/completions", data=body, method="POST",
                                 headers={"Content-Type": "application/json",
                                          "Authorization": f"Bearer {cfg['api_key']}"})
    t0 = time.time()
    waits = list(waits if waits is not None else [15, 30, 60, 90])  # back off on a shared endpoint, then give up
    while True:
        try:
            with urllib.request.urlopen(req, timeout=cfg["timeout_s"], context=_ssl()) as r:
                data = json.loads(r.read().decode("utf-8"))
                _LAST_HEADERS.clear()
                _LAST_HEADERS.update({k.lower(): v for k, v in r.headers.items() if "ratelimit" in k.lower()})
            break
        except urllib.error.HTTPError as exc:
            if exc.code in (429, 502, 503, 504) and waits:
                ra = exc.headers.get("Retry-After") if exc.headers else None
                time.sleep(float(ra) if ra and ra.replace(".", "").isdigit() else waits.pop(0))
                continue
            raise LLMError(f"HTTP {exc.code} from {cfg['base_url']}: {exc.read()[:500]!r}") from None
        except (urllib.error.URLError, TimeoutError) as exc:
            if waits:
                time.sleep(waits.pop(0))
                continue
            raise LLMError(f"could not reach {cfg['base_url']}: {exc}") from None
    msg = (data.get("choices") or [{}])[0].get("message") or {}
    content = (msg.get("content") or "").strip()
    reasoning = (msg.get("reasoning_content") or msg.get("reasoning") or "").strip()
    finish = (data.get("choices") or [{}])[0].get("finish_reason")
    if not content and finish == "length" and _retry:
        # a reasoning model spent the whole budget thinking: archive the cut-off call, then
        # retry once with double the budget and a request to answer directly
        _archive({"t": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(t0)), "purpose": purpose + " (cut off)",
                  "role": role, "backend": cfg["backend"], "label": cfg["label"], "base_url": cfg["base_url"],
                  "model": data.get("model", cfg["model"]), "prompt_hash": ph, "system": system, "user": user,
                  "content": "", "reasoning_content": reasoning[-2000:], "usage": data.get("usage") or {},
                  "latency_s": round(time.time() - t0, 2)})
        cfg["max_tokens"] *= 2
        return _chat(system, user + "\n\nKeep your reasoning short and give the final answer.", purpose=purpose,
                     cfg=cfg, role=role, model=cfg["model"], _retry=False, waits=waits)
    text, source = (content, "content") if content else (reasoning, "reasoning_content")
    if not text:
        raise LLMError(f"empty reply from {cfg['model']} (finish_reason {(data.get('choices') or [{}])[0].get('finish_reason')})")
    rep = Reply(text, source, data.get("model", cfg["model"]), cfg["backend"], ph, data.get("usage") or {})
    if cfg["backend"] == "amd":
        u = data.get("usage") or {}
        STATS["amd_cost_usd"] = round(STATS.get("amd_cost_usd", 0.0) + float(u.get("cost") or 0), 6)
        STATS["amd_completion_tokens"] = STATS.get("amd_completion_tokens", 0) + int(u.get("completion_tokens") or 0)
        if _LAST_HEADERS.get("x-ratelimit-remaining-user-daily-usd"):
            STATS["amd_daily_usd_left"] = float(_LAST_HEADERS["x-ratelimit-remaining-user-daily-usd"])
    STATS[cfg["backend"]] = STATS.get(cfg["backend"], 0) + 1
    _archive({"t": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(t0)), "purpose": purpose, "role": role,
              "backend": cfg["backend"], "label": cfg["label"], "base_url": cfg["base_url"],
              "model": rep.model, "prompt_hash": ph, "system": system, "user": user,
              "content": content, "reasoning_content": reasoning, "usage": rep.usage,
              "latency_s": round(time.time() - t0, 2)})
    return rep


def _ssl():
    """certifi's bundle when present: some Windows Pythons ship without usable roots."""
    try:
        import certifi
        return ssl.create_default_context(cafile=certifi.where())
    except ImportError:
        return ssl.create_default_context()


def _archive(rec: dict) -> None:
    ARCHIVE.parent.mkdir(parents=True, exist_ok=True)
    with open(ARCHIVE, "a", encoding="utf-8") as fh:
        fh.write(json.dumps(rec, ensure_ascii=False) + "\n")


def _from_archive(ph: str) -> Reply:
    if ARCHIVE.is_file():
        for line in reversed(ARCHIVE.read_text(encoding="utf-8").splitlines()):
            rec = json.loads(line)
            if rec.get("prompt_hash") == ph:
                text = rec.get("content") or rec.get("reasoning_content") or ""
                return Reply(text, "archive", rec.get("model", ""), "archive", ph, rec.get("usage") or {})
    raise LLMError(f"prompt {ph} not in the archive - the replay never invents a reply")


def extract_json(text: str):
    """The last complete JSON object or array in the text, or None."""
    cleaned = text.replace("```json", "```")
    dec = json.JSONDecoder()
    for start in sorted({i for i, ch in enumerate(cleaned) if ch in "[{"}, reverse=True):
        try:
            val, _ = dec.raw_decode(cleaned[start:])
        except json.JSONDecodeError:
            continue
        if isinstance(val, (list, dict)) and val:
            # widen to the outermost block that contains this one
            best = val
            for i in range(start - 1, -1, -1):
                if cleaned[i] in "[{":
                    try:
                        v2, end = dec.raw_decode(cleaned[i:])
                        if i + end > start:
                            best = v2
                    except json.JSONDecodeError:
                        pass
            return best
    return None
