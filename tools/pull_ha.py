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
ENTITIES = [
    "sensor.keittio_lampotila", "sensor.keittio_lampotila_3", "sensor.keittio_kosteus_2",
    "sensor.takkahuone_lampotila_2", "sensor.takkahuone_kosteus_2",
    "sensor.tv_huone_lampotila", "sensor.tv_huone_kosteus",
]


def env() -> dict:
    e = {}
    f = ROOT / ".env"
    if f.is_file():
        for line in f.read_text(encoding="utf-8").splitlines():
            if "=" in line and not line.lstrip().startswith("#"):
                k, v = line.split("=", 1)
                e[k.strip()] = v.strip()
    return {**e, **os.environ}


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
    url, token = e.get("HA_URL", "").rstrip("/"), e.get("HA_TOKEN", "")
    if not url or not token:
        raise SystemExit("Set HA_URL and HA_TOKEN in .env (token never printed).")
    import websocket  # websocket-client

    ws = websocket.create_connection(url.replace("http", "ws", 1) + "/api/websocket", timeout=60)
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
