#!/usr/bin/env python3
"""Pull hourly and 5-minute statistics straight from Home Assistant. Read-only.

Run on the LAN, with a long-lived token for Käyrä in .env:
    HA_URL=http://<ha-host>:8123
    HA_TOKEN=<long-lived token>

    python tools/pull_ha.py                       # 2026-10-03 to now
    python tools/pull_ha.py --start 2026-04-13

Writes data/raw/ha_<YYYYMMDD>/lts_hourly_<entity>.csv and sts_5min_<entity>.csv
in the same columns as the frozen 2026-10-03 export, plus SHA256SUMS.txt.
Never edits an older folder. kayra/load.py merges all ha_* folders, newest wins.

HA's REST API has no long-term statistics; the websocket API does
(recorder/statistics_during_period). Needs `pip install websocket-client`.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import os
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
def _entities() -> list[str]:
    """Every Home Assistant signal in config/process.json (outputs and aux)."""
    cfg = json.loads((ROOT / "config" / "process.json").read_text(encoding="utf-8"))
    return [x["tag"] for x in cfg["signals"] if x["source"] == "ha"]


ENTITIES = _entities()


def env() -> dict:
    e = {}
    f = ROOT / ".env"
    if f.is_file():
        for line in f.read_text(encoding="utf-8").splitlines():
            if "=" in line and not line.lstrip().startswith("#"):
                k, v = line.split("=", 1)
                e[k.strip()] = v.strip()
    return {k.upper(): v for k, v in {**e, **os.environ}.items()}  # HA_token and HA_TOKEN both work


def ts(v) -> str:
    if isinstance(v, (int, float)):  # newer HA: epoch milliseconds
        return datetime.fromtimestamp(v / 1000, timezone.utc).isoformat()
    return datetime.fromisoformat(str(v)).astimezone(timezone.utc).isoformat()


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--start", default="2026-10-03")
    ap.add_argument("--extra", nargs="*", default=[], help="more entity ids, e.g. the zigbee climate sensor")
    a = ap.parse_args()
    e = env()
    token = e.get("HA_TOKEN", "")
    urls = [u.rstrip("/") for u in (e.get("HA_URL", ""), e.get("HA_URL_EXT", "")) if u]
    if not urls or not token:
        raise SystemExit("Set HA_URL (LAN) and/or HA_URL_EXT (external) and HA_TOKEN in .env (token never printed).")
    import ssl
    import websocket  # websocket-client
    try:
        import certifi
        sslopt = {"ca_certs": certifi.where()}
    except ImportError:
        sslopt = {}
    ws = None
    for url in urls:  # LAN first, then the external URL
        try:
            ws = websocket.create_connection(url.replace("http", "ws", 1) + "/api/websocket", timeout=60, sslopt=sslopt)
            print(f"connected to {url.split('//')[1].split('/')[0]}")
            break
        except Exception as exc:
            print(f"could not connect to {url.split('//')[1].split('/')[0]}: {type(exc).__name__}")
    if ws is None:
        raise SystemExit("No Home Assistant URL reachable.")
    json.loads(ws.recv())
    ws.send(json.dumps({"type": "auth", "access_token": token}))
    if json.loads(ws.recv()).get("type") != "auth_ok":
        raise SystemExit("HA rejected the token.")
    start = datetime.fromisoformat(a.start).replace(tzinfo=timezone.utc).isoformat()
    out = ROOT / "data" / "raw" / f"ha_{datetime.now():%Y%m%d}"
    out.mkdir(parents=True, exist_ok=True)
    msg_id = 1
    for period, prefix in (("hour", "lts_hourly"), ("5minute", "sts_5min")):
        ws.send(json.dumps({"id": msg_id, "type": "recorder/statistics_during_period", "start_time": start,
                            "statistic_ids": ENTITIES + a.extra, "period": period, "types": ["mean", "min", "max"]}))
        res = json.loads(ws.recv())
        msg_id += 1
        if not res.get("success"):
            raise SystemExit(f"HA error: {res.get('error')}")
        for ent, rows in res["result"].items():
            f = out / f"{prefix}_{ent.replace('.', '_')}.csv"
            with open(f, "w", newline="", encoding="utf-8") as fh:
                w = csv.writer(fh)
                w.writerow(["timestamp_utc", "mean", "min", "max"])
                for r in rows:
                    w.writerow([ts(r["start"]), r.get("mean", ""), r.get("min", ""), r.get("max", "")])
            print(f"{f.relative_to(ROOT)}  {len(rows)} rows")
    ws.close()
    sums = [f"{hashlib.sha256(p.read_bytes()).hexdigest()}  {p.name}" for p in sorted(out.glob("*.csv"))]
    (out / "SHA256SUMS.txt").write_text("\n".join(sums) + "\n", encoding="utf-8")
    print(f"checksums written to {(out / 'SHA256SUMS.txt').relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
