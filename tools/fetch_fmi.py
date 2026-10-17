#!/usr/bin/env python3
"""Fetch hourly outdoor observations from FMI open data.

Standalone. Standard library only. No API key - FMI open data is public.

Source: Finnish Meteorological Institute, WFS stored query
        fmi::observations::weather::hourly::simple
Licence of the data: CC BY 4.0. Credit FMI in the report.

Usage:
    python fetch_fmi.py                          # default station and window
    python fetch_fmi.py --fmisid 101194          # another station
    python fetch_fmi.py --start 2026-04-13T19:00:00Z --end 2026-10-03T10:00:00Z
    python fetch_fmi.py --stations               # list the Kouvola candidates

Output: CSV with one row per hour, UTC timestamps, same timestamp format
as the Home Assistant exports so the two join without conversion.

The hour label follows FMI: the value stamped 12:00Z is the mean of
11:00-12:00Z. Home Assistant long-term statistics stamp the START of the
hour. The --ha-align flag (default on) shifts FMI timestamps back one hour
so both sources label an hour by its start. The raw FMI stamp is kept in
its own column either way.
"""
from __future__ import annotations

import argparse
import csv
import sys
import time
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta, timezone

WFS = "https://opendata.fmi.fi/wfs"
QUERY = "fmi::observations::weather::hourly::simple"

# FMI names. TA = air temperature, RH = relative humidity, WS = wind speed.
# PRA = precipitation amount. All hourly.
PARAMS = ["TA_PT1H_AVG", "TA_PT1H_MIN", "TA_PT1H_MAX", "RH_PT1H_AVG", "WS_PT1H_AVG", "PRA_PT1H_ACC"]
COLS = {
    "TA_PT1H_AVG": "temp_mean",
    "TA_PT1H_MIN": "temp_min",
    "TA_PT1H_MAX": "temp_max",
    "RH_PT1H_AVG": "rh_mean",
    "WS_PT1H_AVG": "wind_mean",
    "PRA_PT1H_ACC": "precip_mm",
}

# Kouvola-area stations. Pick the one nearest the building and say which in the report.
STATIONS = {
    101191: "Kouvola Utti lentoasema",
    101189: "Kouvola Utti Lentoportintie",
    101194: "Kouvola Anjala",
}

DEFAULT_FMISID = 101191
DEFAULT_START = "2026-04-13T19:00:00Z"   # first row of the HA hourly export
DEFAULT_END = "2026-10-03T10:00:00Z"     # last row of the HA hourly export

CHUNK = timedelta(days=7)   # FMI caps hourly queries at 744 h; stay well under
NS = {"wfs": "http://www.opengis.net/wfs/2.0", "BsWfs": "http://xml.fmi.fi/schema/wfs/2.0"}


def parse_ts(s: str) -> datetime:
    return datetime.strptime(s, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)


def fetch_chunk(fmisid: int, start: datetime, end: datetime, retries: int = 4) -> dict[datetime, dict[str, float]]:
    q = urllib.parse.urlencode({
        "service": "WFS",
        "version": "2.0.0",
        "request": "getFeature",
        "storedquery_id": QUERY,
        "fmisid": fmisid,
        "starttime": start.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "endtime": end.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "parameters": ",".join(PARAMS),
    })
    url = f"{WFS}?{q}"
    last: Exception | None = None
    for attempt in range(retries):
        try:
            with urllib.request.urlopen(url, timeout=60) as r:
                body = r.read()
            break
        except Exception as e:  # network hiccup or rate limit: back off, retry
            last = e
            time.sleep(2 ** attempt)
    else:
        raise RuntimeError(f"FMI request failed after {retries} tries: {last}\n{url}")

    root = ET.fromstring(body)
    out: dict[datetime, dict[str, float]] = {}
    for el in root.iterfind(".//BsWfs:BsWfsElement", NS):
        t = parse_ts(el.findtext("BsWfs:Time", namespaces=NS))
        name = el.findtext("BsWfs:ParameterName", namespaces=NS)
        raw = el.findtext("BsWfs:ParameterValue", namespaces=NS)
        try:
            val = float(raw)
        except (TypeError, ValueError):
            continue
        if val != val:  # NaN: FMI's way of saying no observation
            continue
        out.setdefault(t, {})[name] = val
    return out


def fetch(fmisid: int, start: datetime, end: datetime) -> dict[datetime, dict[str, float]]:
    data: dict[datetime, dict[str, float]] = {}
    cur = start
    while cur <= end:
        nxt = min(cur + CHUNK, end)
        got = fetch_chunk(fmisid, cur, nxt)
        data.update(got)
        print(f"  {cur:%Y-%m-%d} .. {nxt:%Y-%m-%d}  {len(got)} hours", file=sys.stderr)
        if nxt >= end:
            break
        cur = nxt + timedelta(hours=1)
        time.sleep(0.3)  # be polite
    return data


def main() -> int:
    ap = argparse.ArgumentParser(description="Fetch hourly FMI observations to CSV.")
    ap.add_argument("--fmisid", type=int, default=DEFAULT_FMISID)
    ap.add_argument("--start", default=DEFAULT_START, help="UTC, e.g. 2026-04-13T19:00:00Z (HA hour-start label)")
    ap.add_argument("--end", default=DEFAULT_END)
    ap.add_argument("--out", default=None, help="output CSV path")
    ap.add_argument("--no-ha-align", action="store_true", help="keep FMI hour-end labels as the primary timestamp")
    ap.add_argument("--stations", action="store_true", help="list known Kouvola stations and exit")
    a = ap.parse_args()

    if a.stations:
        for k, v in STATIONS.items():
            print(k, v)
        return 0

    align = not a.no_ha_align
    start, end = parse_ts(a.start), parse_ts(a.end)
    shift = timedelta(hours=1) if align else timedelta(0)
    # Ask FMI for the hour-end stamps that correspond to the wanted hour-start labels.
    data = fetch(a.fmisid, start + shift, end + shift)

    out = a.out or f"fmi_hourly_{a.fmisid}_{start:%Y%m%d}_{end:%Y%m%d}.csv"
    expected = int((end - start) / timedelta(hours=1)) + 1
    missing = 0
    with open(out, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["timestamp_utc", "fmi_timestamp_utc", "fmisid"] + [COLS[p] for p in PARAMS])
        t = start
        while t <= end:
            fmi_t = t + shift
            row = data.get(fmi_t, {})
            if "TA_PT1H_AVG" not in row:
                missing += 1
            w.writerow([t.isoformat(), fmi_t.isoformat(), a.fmisid] + [row.get(p, "") for p in PARAMS])
            t += timedelta(hours=1)

    name = STATIONS.get(a.fmisid, "unknown station")
    print(f"station  {a.fmisid} {name}")
    print(f"window   {start.isoformat()} .. {end.isoformat()}  ({'HA hour-start' if align else 'FMI hour-end'} labels)")
    print(f"rows     {expected} expected, {expected - missing} with temperature, {missing} missing")
    print(f"written  {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
