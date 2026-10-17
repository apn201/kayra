"""Join Home Assistant room statistics and FMI outdoor temperature into one hourly frame.

Product input only: Home Assistant rooms plus FMI Utti outdoor. The Ouman panel
readings are reference data and are loaded by `reference.py`, never here. The
configured curve (`data/manual/ouman_curve_setting.csv`) is read by
`evaluate.py` and nothing else.

Sources, newest wins on overlapping hours:
    data/raw/ha_exports_20261003/lts_hourly_<entity>.csv   frozen snapshot
    data/raw/ha_<YYYYMMDD>/lts_hourly_<entity>.csv         later pulls (tools/pull_ha.py)
    data/raw/fmi*/fmi_hourly_101191.csv                    FMI Kouvola Utti

Gaps: FMI single or double missing hours are interpolated and flagged. Room gaps
stay NaN; windows that touch one are skipped by the search.
"""

from __future__ import annotations

import csv
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parent.parent
RAW = ROOT / "data" / "raw"

PROCESS = ROOT / "config" / "process.json"


def _signals() -> tuple[dict, dict]:
    """Outputs and their aux signals from config/process.json (what Käyrä watches).
    Returns ({output_id: (tag, humidity_tag)}, {aux_id: tag}) with tags in file-name form."""
    import json
    cfg = json.loads(PROCESS.read_text(encoding="utf-8"))
    sig = cfg["signals"]
    fname = lambda tag: tag.replace(".", "_", 1)
    outs, extra = {}, {}
    for s in sig:
        if s["role"] == "output" and s["source"] == "ha":
            rh = next((a["tag"] for a in sig if a.get("aux_of") == s["id"] and a.get("unit") == "%RH"), None)
            outs[s["id"]] = (fname(s["tag"]), fname(rh) if rh else None)
    for s in sig:
        if s["role"] == "aux" and s.get("unit") == "°C" and s["source"] == "ha":
            extra[s["id"]] = fname(s["tag"])
    return outs, extra


# output -> (temperature series, humidity series), from config/process.json. The kitchen has two
# temperature sensors at two heights; the second is carried as aux and never averaged.
ROOMS, EXTRA = _signals()
FMISID = 101191  # Kouvola Utti lentoasema


@dataclass
class Frame:
    t: list[datetime]                      # hour-start labels, UTC
    t_out: np.ndarray                      # FMI Utti, °C
    t_out_filled: np.ndarray               # bool, interpolated hour
    rooms: dict[str, np.ndarray]           # room -> temperature, °C
    humidity: dict[str, np.ndarray]        # room -> RH %
    extra: dict[str, np.ndarray] = field(default_factory=dict)
    hour_local: np.ndarray = None          # 0..23 Europe/Helsinki
    weekday_local: np.ndarray = None       # 0 = Monday
    month_local: np.ndarray = None         # 1..12
    sources: dict[str, str] = field(default_factory=dict)

    def __len__(self) -> int:
        return len(self.t)


def _parse_ts(s: str) -> datetime:
    return datetime.fromisoformat(s.replace("Z", "+00:00")).astimezone(timezone.utc)


def _last_sunday(year: int, month: int) -> datetime:
    d = datetime(year, month + 1, 1, tzinfo=timezone.utc) - timedelta(days=1) if month < 12 else datetime(year, 12, 31, tzinfo=timezone.utc)
    return d - timedelta(days=(d.weekday() + 1) % 7)


def helsinki(t: datetime) -> datetime:
    """UTC to Europe/Helsinki wall time. EU rule: DST from 01:00 UTC on the last
    Sunday of March to 01:00 UTC on the last Sunday of October. No tzdata needed."""
    start = _last_sunday(t.year, 3).replace(hour=1)
    end = _last_sunday(t.year, 10).replace(hour=1)
    return t + timedelta(hours=3 if start <= t < end else 2)


def _read_stats(name: str) -> tuple[dict[datetime, float], list[str]]:
    """All pulls of one HA entity, newest folder wins per hour."""
    # oldest pull first, so the newest wins per hour (ha_exports_20261003 sorts by its date too)
    folders = sorted((p for p in RAW.iterdir() if p.is_dir() and p.name.startswith("ha_")),
                     key=lambda p: p.name.replace("ha_exports_", "ha_"))
    values: dict[datetime, float] = {}
    used = []
    for folder in folders:
        f = folder / f"lts_hourly_{name}.csv"
        if not f.is_file():
            continue
        used.append(f.relative_to(ROOT).as_posix())
        with open(f, newline="", encoding="utf-8") as fh:
            for row in csv.DictReader(fh):
                m = row.get("mean", "")
                if m in ("", "unknown", "unavailable"):
                    continue
                values[_parse_ts(row["timestamp_utc"])] = float(m)
    return values, used


def _read_fmi() -> tuple[dict[datetime, float], str]:
    files = sorted(RAW.glob(f"fmi*/fmi_hourly_{FMISID}.csv"), key=lambda p: p.stat().st_size)
    if not files:
        raise SystemExit(f"No FMI file for {FMISID} under data/raw/fmi*/ - run tools/fetch_fmi.py")
    f = files[-1]  # the longest pull
    out: dict[datetime, float] = {}
    with open(f, newline="", encoding="utf-8") as fh:
        for row in csv.DictReader(fh):
            if row["temp_mean"] not in ("", "nan"):
                out[_parse_ts(row["timestamp_utc"])] = float(row["temp_mean"])
    return out, f.relative_to(ROOT).as_posix()


def load() -> Frame:
    fmi, fmi_src = _read_fmi()
    room_vals = {r: _read_stats(e[0]) for r, e in ROOMS.items()}
    hum_vals = {r: _read_stats(e[1]) if e[1] else ({}, []) for r, e in ROOMS.items()}
    extra_vals = {k: _read_stats(e) for k, e in EXTRA.items()}

    start = max(min(fmi), min(min(v[0]) for v in room_vals.values()))
    end = max(fmi)  # outdoor runs to now; rooms may stop earlier (NaN after)
    hours = int((end - start).total_seconds() // 3600) + 1
    t = [start + timedelta(hours=i) for i in range(hours)]

    t_out = np.array([fmi.get(x, np.nan) for x in t])
    filled = np.isnan(t_out)
    idx = np.arange(hours)
    ok = ~filled
    # interpolate only short gaps; longer ones stay NaN
    interp = np.interp(idx, idx[ok], t_out[ok])
    long_gap = np.zeros(hours, bool)
    i = 0
    while i < hours:
        if filled[i]:
            j = i
            while j < hours and filled[j]:
                j += 1
            if j - i > 2:
                long_gap[i:j] = True
            i = j
        else:
            i += 1
    t_out = np.where(filled & ~long_gap, interp, t_out)

    def series(vals):
        return np.array([vals.get(x, np.nan) for x in t])

    local = [helsinki(x) for x in t]
    sources = {"outdoor": fmi_src}
    for r, (vals, used) in room_vals.items():
        sources[r] = ", ".join(used)
    return Frame(
        t=t,
        t_out=t_out,
        t_out_filled=filled & ~long_gap,
        rooms={r: series(v[0]) for r, v in room_vals.items()},
        humidity={r: series(v[0]) for r, v in hum_vals.items()},
        extra={k: series(v[0]) for k, v in extra_vals.items()},
        hour_local=np.array([x.hour for x in local]),
        weekday_local=np.array([x.weekday() for x in local]),
        month_local=np.array([x.month for x in local]),
        sources=sources,
    )


def summary(f: Frame) -> dict:
    """Sample sizes and windows of every source - goes into the document as is."""
    def span(a):
        ok = np.flatnonzero(~np.isnan(a))
        if not len(ok):
            return None
        return {"first": f.t[ok[0]].isoformat(), "last": f.t[ok[-1]].isoformat(), "hours": int(len(ok))}

    return {
        "outdoor": {**span(f.t_out), "station": "FMI Kouvola Utti lentoasema (fmisid 101191)",
                    "interpolated_hours": int(f.t_out_filled.sum()),
                    "min_c": float(np.nanmin(f.t_out)), "max_c": float(np.nanmax(f.t_out)),
                    "file": f.sources["outdoor"]},
        "rooms": {r: {**(span(a) or {}), "file": f.sources[r]} for r, a in f.rooms.items()},
    }


if __name__ == "__main__":
    import json
    print(json.dumps(summary(load()), indent=2))
