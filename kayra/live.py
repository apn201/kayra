"""Live state for the panel: outdoor now from FMI, rooms now from Home Assistant, prediction from the
fitted loop model. Read-only on both sides.

Used by tools/serve.py (`/api/state`). Labels, never blurred:
    LIVE            outdoor and rooms read now
    LIVE OUTDOOR    outdoor read now; rooms from the recorded replay (no HA_URL/HA_TOKEN, or HA unreachable)
    REPLAY          nothing live could be read

Every live hour is appended to data/live/live_<date>.jsonl, so live points build up on the curve.
Prediction = steady state of the building model fitted to each loop (artifacts/real.json, "simple"),
the same arithmetic as the panel's curve screen.
"""

from __future__ import annotations

import json
import os
import time
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta, timezone
from pathlib import Path

from .client import _env_file, _ssl
from .load import ROOMS

ROOT = Path(__file__).resolve().parent.parent
ART = ROOT / "artifacts"
LIVE_DIR = ROOT / "data" / "live"
FMI = "https://opendata.fmi.fi/wfs"
FMISID = 101191
CACHE_S = 300
_cache: dict = {}


def _env() -> dict:
    return {**_env_file(), **os.environ}


def fmi_now() -> tuple[datetime, float] | None:
    """Latest 10-minute air temperature at Utti."""
    end = datetime.now(timezone.utc).replace(second=0, microsecond=0)
    q = urllib.parse.urlencode({"service": "WFS", "version": "2.0.0", "request": "getFeature",
                                "storedquery_id": "fmi::observations::weather::simple", "fmisid": FMISID,
                                "starttime": (end - timedelta(hours=2)).strftime("%Y-%m-%dT%H:%M:%SZ"),
                                "endtime": end.strftime("%Y-%m-%dT%H:%M:%SZ"), "parameters": "t2m"})
    try:
        with urllib.request.urlopen(f"{FMI}?{q}", timeout=20, context=_ssl()) as r:
            root = ET.fromstring(r.read())
    except Exception:
        return None
    ns = {"BsWfs": "http://xml.fmi.fi/schema/wfs/2.0"}
    best = None
    for el in root.iterfind(".//BsWfs:BsWfsElement", ns):
        try:
            v = float(el.findtext("BsWfs:ParameterValue", namespaces=ns))
        except (TypeError, ValueError):
            continue
        if v != v:
            continue
        t = datetime.strptime(el.findtext("BsWfs:Time", namespaces=ns), "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
        if best is None or t > best[0]:
            best = (t, v)
    return best


def ha_now() -> dict | None:
    """Room temperature and humidity now, from HA's REST API. Skips unavailable states, never float()s them."""
    e = _env()
    url, token = e.get("HA_URL", "").rstrip("/"), e.get("HA_TOKEN", "")
    if not url or not token:
        return None
    out = {}
    for room, (t_ent, h_ent) in ROOMS.items():
        vals = {}
        for key, ent in (("measured_c", t_ent), ("rh", h_ent)):
            req = urllib.request.Request(f"{url}/api/states/{ent.replace('sensor_', 'sensor.', 1)}",
                                         headers={"Authorization": f"Bearer {token}"})
            try:
                with urllib.request.urlopen(req, timeout=10, context=_ssl() if url.startswith("https") else None) as r:
                    st = json.loads(r.read().decode("utf-8")).get("state")
                vals[key] = None if st in (None, "", "unknown", "unavailable") else round(float(st), 2)
            except Exception:
                vals[key] = None
        out[room] = vals
    return out if any(v["measured_c"] is not None for v in out.values()) else None


def _curve(theta: dict, to: float):
    return None if to >= theta["cutoff"] else theta["level"] + theta["slope"] * to


def _steady(b: dict, theta: dict, to: float) -> float:
    free = to + b["g0"] / b["a"]
    S = _curve(theta, to)
    if S is None:
        return free
    heated = (b["a"] * to + b["h"] * S + b["g0"]) / (b["a"] + b["h"])
    return heated if S > heated else free


def _replay_row() -> dict:
    rows = json.loads((ART / "replay.json").read_text(encoding="utf-8"))["rows"]
    return rows[int(time.time() // 2) % len(rows)]


def state() -> dict:
    now = time.time()
    if _cache.get("t", 0) > now - CACHE_S:
        return _cache["s"]
    real = json.loads((ART / "real.json").read_text(encoding="utf-8"))
    out = fmi_now()
    rooms = ha_now()
    if out is None:
        s = {"data": "REPLAY", "row": _replay_row()}
    else:
        t, to = out
        base = rooms or _replay_row()
        row = {"t": t.isoformat(), "outdoor_c": round(to, 1)}
        for lid, L in (real.get("simple") or {}).items():
            for r in L["rooms"]:
                src = base.get(r) or {}
                row[r] = {"measured_c": src.get("measured_c"), "rh": src.get("rh"),
                          "predicted_c": round(_steady(L["building_rooms"][r], L["theta"], to), 2),
                          "supply_c": None if _curve(L["theta"], to) is None else round(_curve(L["theta"], to), 1),
                          "loop": lid}
        s = {"data": "LIVE" if rooms else "LIVE OUTDOOR", "row": row,
             "note": None if rooms else "rooms from the recorded replay: no Home Assistant access from this host"}
        _log(s)
    _cache.update(t=now, s=s)
    return s


def _log(s: dict) -> None:
    LIVE_DIR.mkdir(parents=True, exist_ok=True)
    hour = s["row"]["t"][:13]
    f = LIVE_DIR / f"live_{hour[:10]}.jsonl"
    if f.is_file() and any(json.loads(l)["row"]["t"][:13] == hour for l in f.read_text(encoding="utf-8").splitlines() if l):
        return  # one row per hour
    with open(f, "a", encoding="utf-8") as fh:
        fh.write(json.dumps(s, ensure_ascii=False) + "\n")


def history(days: int = 30) -> list[dict]:
    """Logged live hours, newest last - shown as points on the curve screen."""
    if not LIVE_DIR.is_dir():
        return []
    rows = []
    for f in sorted(LIVE_DIR.glob("live_*.jsonl"))[-days:]:
        rows += [json.loads(l) for l in f.read_text(encoding="utf-8").splitlines() if l]
    return rows


if __name__ == "__main__":
    print(json.dumps(state(), indent=1))
