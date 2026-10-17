"""Run everything and write artifacts/*.json. Same command on a laptop CPU and on an AMD GPU.

    python -m kayra.run real        real house, HA-only + anchored, notebook, replay
    python -m kayra.run synth       synthetic benchmark, arms A / B / (C when a model is configured)
    python -m kayra.run bench       CPU vs GPU timing of an identical search
    python -m kayra.run all

Options: --device cpu|cuda (default: cuda if present), --quick (small budget, for a smoke test).
Every artifact records the device, the LLM status and the budget it ran with.
"""

from __future__ import annotations

import argparse
import json
import math
import time
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import torch

from . import client, hypothesize, load, reference, rules, search, synth

ROOT = Path(__file__).resolve().parent.parent
ART = ROOT / "artifacts"
STANDIN = Path(__file__).resolve().parent / "standin" / "real_rounds.json"
SITE = ROOT / "config" / "site.json"


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _write(name: str, obj) -> None:
    ART.mkdir(exist_ok=True)
    tmp = ART / (name + ".tmp")
    tmp.write_text(json.dumps(obj, indent=1, ensure_ascii=False, default=_jsonable), encoding="utf-8")
    tmp.replace(ART / name)
    print(f"wrote artifacts/{name}")


def _jsonable(x):
    if isinstance(x, (np.floating, np.integer)):
        return x.item()
    if isinstance(x, np.ndarray):
        return x.tolist()
    if isinstance(x, float) and math.isnan(x):
        return None
    raise TypeError(type(x))


def _proposer(cfg):
    if cfg["backend"] in ("amd", "other", "archive"):
        return hypothesize.LLMProposer(cfg), client.status(cfg)
    return hypothesize.StandinProposer(STANDIN), "OFFLINE - stand-in proposals (hand-written)"


def _meta(device, budget, llm_status):
    return {"generated_utc": _now(), "device": search.hardware(device), "budget": budget, "llm": llm_status}


def _prediction_series(problem: search.Problem, res: dict, ahead: int = 24) -> dict:
    """Continuous 1-24 h ahead prediction: each window predicts its first day from the measured start."""
    b = {k: torch.tensor([v], device=problem.device) for k, v in res["best_b"].items()}
    th = {k: torch.tensor([v], device=problem.device) for k, v in res["best_theta"].items()}
    pred, sup = problem.simulate(res["prog"], th, b, record_supply=True)
    out = {}
    for w, s in enumerate(problem.win.starts):
        for k in range(ahead):
            i = int(s) + 1 + k
            out[i] = (float(pred[0, w, k]), float(sup[0, w, k]) if not torch.isnan(sup[0, w, k]) else None,
                      bool(problem.win.held[w]))
    return out


# ---------------------------------------------------------------------------- real

def real(device: str, quick: bool) -> dict:
    n, iters = (512, 4) if quick else (2048, 6)
    cfg = client.config()
    proposer, llm_status = _proposer(cfg)
    f = load.load()
    catalogue = search.load_catalogue()
    rooms = {}
    preds = {}
    priors = {}
    for room in f.rooms:
        t0 = time.perf_counter()
        prior = priors[room] = search.summer_prior(f, room, device, n=n, iters=iters)
        p = search.Problem(f, room, device, season="cold", building=prior["bounds"])
        loop = hypothesize.run(p, catalogue, proposer, rounds=2 if quick else 5, n=n, iters=iters)
        best_id = loop["ranked"][0]["id"]
        res = {r["prog"].id: r for r in loop["results"]}
        best = res[best_id]
        # the best structure that actually is a curve (has T_out) - the curve screen needs one
        curve_id = next(r["id"] for r in loop["ranked"] if "T_out" in loop["specs"][r["id"]]["expr"])
        rooms[room] = {
            "windows_cold": int(len(p.win.starts)), "windows_held_out": int(p.win.held.sum()),
            "summer_prior": {"time_constant_h": prior["time_constant_h"], "windows": prior["windows"],
                             "rmse_held_c": round(prior["rmse_held_c"], 3)},
            "ranked": loop["ranked"], "notebook": loop["notebook"],
            "best": {"id": best_id, "expr": loop["specs"][best_id]["expr"],
                     "theta": best["best_theta"], "building": best["best_b"],
                     "time_constant_h": round(1 / best["best_b"]["a"], 1)},
            "curve": {"id": curve_id, "expr": loop["specs"][curve_id]["expr"],
                      "band": search.population_curve(p, res[curve_id])},
            "residual": search.residual_report(p, best),
            "fits": loop["fits"], "wall_s": round(time.perf_counter() - t0, 1),
            "median_c": round(p.median, 2),
        }
        preds[room] = _prediction_series(p, best)
        print(f"{room}: best {best_id}, curve {curve_id}, {rooms[room]['wall_s']} s")

    # loop groups from operator site knowledge: rooms on one loop share one controller program
    site = json.loads(SITE.read_text(encoding="utf-8")) if SITE.is_file() else {"loops": {}}
    loops = {}
    for lid, L in site.get("loops", {}).items():
        members = [r for r in L["rooms"] if r in f.rooms]
        if len(members) < 2:
            loops[lid] = {"name": L["name"], "rooms": members, "operator_notes": L.get("operator_notes", ""),
                          "same_as_room": members[0] if members else None}
            continue
        t0 = time.perf_counter()
        p = search.Problem(f, members, device, season="cold", building=[priors[r]["bounds"] for r in members])
        loop = hypothesize.run(p, catalogue, proposer, rounds=2 if quick else 5, n=n, iters=iters)
        res = {r["prog"].id: r for r in loop["results"]}
        best_id = loop["ranked"][0]["id"]
        best = res[best_id]
        curve_id = next(r["id"] for r in loop["ranked"] if "T_out" in loop["specs"][r["id"]]["expr"])
        hs = [x["h"] for x in best["best_b_rooms"]]
        loops[lid] = {
            "name": L["name"], "rooms": members, "operator_notes": L.get("operator_notes", ""),
            "windows_cold": int(len(p.win.starts)), "windows_held_out": int(p.win.held.sum()),
            "ranked": loop["ranked"], "notebook": loop["notebook"],
            "best": {"id": best_id, "expr": loop["specs"][best_id]["expr"], "theta": best["best_theta"],
                     "building_rooms": dict(zip(members, best["best_b_rooms"]))},
            # direct heating coupling per room, as a share of the loop's total - the TV room check
            "heating_share": {r: round(h / sum(hs), 3) for r, h in zip(members, hs)},
            "held_rmse_rooms": dict(zip(members, best["held_rmse_rooms"])),
            "held_rmse_rooms_fitted_alone": {r: rooms[r]["ranked"][0]["rmse_held_c"] for r in members},
            "curve": {"id": curve_id, "expr": loop["specs"][curve_id]["expr"],
                      "bands": {r: search.population_curve(p, res[curve_id], room=i) for i, r in enumerate(members)}},
            "residual": search.residual_report(p, best),
            "fits": loop["fits"], "wall_s": round(time.perf_counter() - t0, 1),
        }
        print(f"loop {lid}: best {best_id}, share {loops[lid]['heating_share']}, {loops[lid]['wall_s']} s")

    simple = simple_view(f, device, n, iters, priors, site, catalogue)

    # anchored mode: k spot readings of panel loop L1 pin the curve level. Which floor L1 serves is
    # unknown, so the readings are tried on every room group. The group whose own room data stay
    # consistent with the L1 curve (smallest rise in held-out room error once anchored) is the
    # data's answer to "which floor is L1". Reported with its margin; never assumed.
    s1 = next(s for s in catalogue if s["id"] == "S1")
    n_l1 = len([r for r in reference.readings() if r["l1_supply_c"] is not None])
    anchored_by_group, loop_match = {}, {}
    for gid, L in site.get("loops", {}).items():
        g_rooms = [r for r in L["rooms"] if r in f.rooms]
        if not g_rooms:
            continue
        pf = search.Problem(f, g_rooms if len(g_rooms) > 1 else g_rooms[0], device, season="cold",
                            building=[priors[r]["bounds"] for r in g_rooms])
        rows = []
        for k in range(0, min(5, n_l1)):
            anc, rest = reference.anchors(k)
            r = search.search(pf, s1, n=n, iters=iters, anchors=anc, seed=7)
            band = search.population_curve(pf, r)
            b, th = search.best_tensors(pf, r)
            grid = sorted({x["outdoor_controller_c"] for x in rest})
            cur = search.steady_curve(pf, r["prog"], th, b, grid=grid)[0].cpu().numpy()
            errs = [float(cur[grid.index(x["outdoor_controller_c"])] - x["l1_supply_c"]) for x in rest]
            i5 = band["grid_c"].index(4)
            width = (band["p95"][i5] - band["p05"][i5]) if band["p95"][i5] is not None else None
            rows.append({"k": k, "mode": "HA-ONLY" if k == 0 else f"ANCHORED k={k}", "band": band,
                         "scored_on": len(rest),
                         "rmse_vs_panel_l1_c": round(float(np.sqrt(np.mean(np.square(errs)))), 2) if errs else None,
                         "band_width_at_4c": round(width, 2) if width is not None else None,
                         "room_rmse_held_c": round(math.sqrt(r["held_mse"]), 3),
                         "theta": r["best_theta"]})
            print(f"anchored {gid} k={k}: rmse vs panel {rows[-1]['rmse_vs_panel_l1_c']}, room {rows[-1]['room_rmse_held_c']}")
        anchored_by_group[gid] = {"rooms": g_rooms, "name": L["name"], "rows": rows}
        loop_match[gid] = round(rows[-1]["room_rmse_held_c"] - rows[0]["room_rmse_held_c"], 3)
    best_g = min(loop_match, key=loop_match.get)
    margin = round(sorted(loop_match.values())[1] - loop_match[best_g], 3) if len(loop_match) > 1 else None
    anchored = anchored_by_group[best_g]["rows"]
    a_rooms, a_loop = anchored_by_group[best_g]["rooms"], "L1"
    l1_floor = {"room_error_rise_when_anchored_c": loop_match, "best_group": best_g,
                "best_group_name": anchored_by_group[best_g]["name"], "margin_c": margin,
                "verdict": (f"L1 panel readings fit {anchored_by_group[best_g]['name']} best; margin {margin} C of room error"
                            + (" - weak, treat as unresolved" if margin is not None and margin < 0.02 else ""))}
    print("L1 floor:", l1_floor["verdict"])

    # replay for the Live screen: last 21 days with room data, hour by hour
    last = max(i for i in range(len(f)) if not np.isnan(f.rooms["tv"][i]))
    first = max(0, last - 21 * 24)
    replay = []
    for i in range(first, last + 1):
        row = {"t": f.t[i].isoformat(), "outdoor_c": round(float(f.t_out[i]), 1)}
        for room in f.rooms:
            m = f.rooms[room][i]
            pr = preds[room].get(i)
            row[room] = {"measured_c": None if np.isnan(m) else round(float(m), 2),
                         "predicted_c": round(pr[0], 2) if pr else None,
                         "supply_c": round(pr[1], 1) if pr and pr[1] is not None else None,
                         "rh": None if np.isnan(f.humidity[room][i]) else round(float(f.humidity[room][i]), 1)}
        replay.append(row)
    alerts = rules.scan(replay, list(f.rooms))

    out = {
        "meta": _meta(device, {"candidates_per_iter": n, "iters": iters}, llm_status),
        "data": load.summary(f),
        "rooms": rooms,
        "loops": loops,
        "simple": simple,
        "site": site,
        "anchored_fireplace": anchored,   # key kept for the panel; the room is in anchored_rooms
        "anchored_rooms": a_rooms, "anchored_loop": a_loop,
        "anchored_by_group": anchored_by_group, "l1_floor": l1_floor,
        "operator": [reference.operator_l2_belief(), reference.operator_tv_people(f)],
        "controller_vs_fmi": reference.controller_vs_fmi(f),
        "alerts": alerts,
    }
    out["meta"]["llm"] = client.status(cfg)          # at the end: includes the AMD / fallback mix
    out["meta"]["llm_calls"] = dict(client.STATS)
    _write("real.json", out)
    # panel readings for the curve chart, in the same order anchors() takes them (reference data)
    _write("readings.json", [{"t": r["timestamp_local"], "out": r["outdoor_controller_c"], "l1": r["l1_supply_c"],
                               "l2": r["l2_supply_c"]} for r in reference.readings()
                              if r["l1_supply_c"] is not None and r["outdoor_controller_c"] is not None])
    _write("replay.json", {"meta": out["meta"], "source": "REPLAY of recorded Home Assistant history",
                           "rows": replay})
    return out


def simple_view(f, device, n, iters, priors, site, catalogue) -> dict:
    """Simple view: one adjustable curve per loop (weather curve + summer stop, S3), fitted on
    ALL windows so the stop is seen, and compared with no control (S0) on the same windows.
    The panel moves level/slope/stop and predicts each room's steady state from the fitted
    building parameters. Also writes points.json (daily means) for the scatter."""
    s3 = next(s for s in catalogue if s["id"] == "S3")
    s0 = next(s for s in catalogue if s["id"] == "S0")
    simple = {}
    for lid, L in site.get("loops", {}).items():
        members = [r for r in L["rooms"] if r in f.rooms]
        if not members:
            continue
        p = search.Problem(f, members, device, season="all", building=[priors[r]["bounds"] for r in members])
        r = search.search(p, s3, n=n, iters=iters, seed=3)
        r0 = search.search(p, s0, n=n, iters=iters, seed=3)
        ranked = search.rank([r, r0], p)
        vs = {x["id"]: x for x in ranked}
        simple[lid] = {"name": L["name"], "rooms": members, "program": s3["expr"], "theta": r["best_theta"],
                       "building_rooms": dict(zip(members, r["best_b_rooms"])),
                       "held_rmse_rooms": dict(zip(members, r["held_rmse_rooms"])),
                       "vs_no_control": {"windows": int(len(p.win.starts)), "held_out": int(p.win.held.sum()),
                                         "S3": vs["S3"], "S0": vs["S0"]}}
        print(f"simple {lid}: {r['best_theta']}  S3 vs S0 delta_bic {vs['S0']['bic'] - vs['S3']['bic']:.1f}")
    days = {}
    for i, t in enumerate(f.t):
        days.setdefault(load.helsinki(t).date().isoformat(), []).append(i)
    pts = []
    for d, ix in sorted(days.items()):
        row = {"d": d, "out": round(float(np.nanmean(f.t_out[ix])), 2)}
        for room in f.rooms:
            v = f.rooms[room][ix]
            row[room] = round(float(np.nanmean(v)), 2) if np.isfinite(v).sum() >= 18 else None
        pts.append(row)
    _write("points.json", {"what": "daily means: FMI Utti outdoor, Home Assistant rooms", "days": pts})
    return simple


def simple_only(device: str, quick: bool) -> None:
    """Refresh only the simple view inside an existing real.json (no model calls)."""
    n, iters = (512, 4) if quick else (2048, 6)
    real_path = ART / "real.json"
    out = json.loads(real_path.read_text(encoding="utf-8"))
    f = load.load()
    site = json.loads(SITE.read_text(encoding="utf-8"))
    rooms = sorted({r for L in site["loops"].values() for r in L["rooms"] if r in f.rooms})
    priors = {r: search.summer_prior(f, r, device, n=n, iters=iters) for r in rooms}
    out["simple"] = simple_view(f, device, n, iters, priors, site, search.load_catalogue())
    out["site"] = site
    _write("real.json", out)


# --------------------------------------------------------------------------- synth

def synthetic(device: str, quick: bool) -> dict:
    n, iters = (512, 4) if quick else (2048, 8)
    rounds = 2 if quick else 3
    cfg = client.config()
    f = load.load()
    prior = search.summer_prior(f, "fireplace", device, n=n, iters=iters)
    building = dict(prior["summer_fit"])
    building["h"] = 0.003  # fixed test value: puts the synthetic room near 22 °C under the test curves
    catalogue = search.load_catalogue()
    cases = []
    for cid, case in (list(synth.HIDDEN.items())[:2] if quick else synth.HIDDEN.items()):
        g = synth.make_case(f, building, cid, resid_sd=0.02, seed=1)
        p = search.Problem(g, "fireplace", device, season="all", building=prior["bounds"])
        seed = [search.search(p, s, n=n, iters=iters) for s in catalogue]
        arms = {}
        a_rank = search.rank(seed, p)
        arms["A"] = _arm_summary(cid, a_rank, {r["prog"].id: r["spec"] for r in seed}, sum(r["evals"] for r in seed))
        b = hypothesize.run(p, catalogue, hypothesize.BaselineProposer(seed=11), rounds=rounds, n=n, iters=iters,
                            seed_results=seed)
        arms["B"] = _arm_summary(cid, b["ranked"], b["specs"], b["fits"]) | {"notebook": b["notebook"]}
        if cfg["backend"] in ("amd", "other", "archive"):
            c = hypothesize.run(p, catalogue, hypothesize.LLMProposer(cfg), rounds=rounds, n=n, iters=iters,
                                seed_results=seed)
            arms["C"] = _arm_summary(cid, c["ranked"], c["specs"], c["fits"]) | {"notebook": c["notebook"],
                                                                                "llm": client.status(cfg)}
        else:
            arms["C"] = {"status": "NOT RUN - language model endpoint unavailable. Stand-in proposals are "
                                   "deliberately not used here: the developer wrote the hidden controllers."}
        T = g.rooms["fireplace"]
        cases.append({"id": cid, "hidden": case["what"], "checklist": case["checklist"],
                      "room_range_c": [round(float(np.nanmin(T)), 1), round(float(np.nanmax(T)), 1)],
                      "arms": arms})
        print(cid, {k: (v.get("best"), v.get("right_mechanism")) for k, v in arms.items()})
    out = {"meta": _meta(device, {"candidates_per_iter": n, "iters": iters, "rounds": rounds}, client.status(cfg)),
           "label": "SYNTHETIC - real outdoor history and fitted real building, hidden test controllers",
           "building": building, "cases": cases}
    out["meta"]["llm"] = client.status(cfg)
    out["meta"]["llm_calls"] = dict(client.STATS)
    _write("synth.json", out)
    return out


def _arm_summary(cid, ranked, specs, fits):
    best = ranked[0]
    return {"best": best["id"], "expr": specs[best["id"]]["expr"], "rmse_held_c": best["rmse_held_c"],
            "right_mechanism": synth.right_mechanism(cid, specs[best["id"]]["expr"]),
            "fits": int(fits), "ranked": ranked[:6]}


# --------------------------------------------------------------------------- bench

def bench(quick: bool) -> dict:
    f = load.load()
    catalogue = search.load_catalogue()
    n, iters = (1024, 2) if quick else (4096, 3)
    runs = []
    configs = [("cpu", 1), ("cpu", torch.get_num_threads())]
    if torch.cuda.is_available():
        configs.append(("cuda", torch.get_num_threads()))
    default_threads = torch.get_num_threads()
    for dev, threads in configs:
        torch.set_num_threads(threads)
        p = search.Problem(f, "fireplace", dev, season="all")
        search.search(p, catalogue[1], n=256, iters=1)  # warm-up
        t0 = time.perf_counter()
        total = 0
        for s in catalogue:
            r = search.search(p, s, n=n, iters=iters)
            total += r["evals"]
        wall = time.perf_counter() - t0
        sims = total * len(p.win.starts) * search.WINDOW
        runs.append({"device": dev, "threads": threads, "hardware": search.hardware(dev),
                     "programs": len(catalogue), "candidates": total, "windows": int(len(p.win.starts)),
                     "wall_s": round(wall, 2), "candidates_per_s": round(total / wall, 1),
                     "room_hours_simulated_per_s": round(sims / wall)})
        print(runs[-1])
    torch.set_num_threads(default_threads)
    out = {"meta": {"generated_utc": _now()}, "what": "identical catalogue search, fireplace room, all windows",
           "runs": runs}
    if not torch.cuda.is_available():
        out["gpu"] = {"status": "NOT MEASURED - no AMD GPU was available for this build. The fitter is PyTorch and picks a "
                                "ROCm device when one exists; no estimate is given. The AMD workload in this version is "
                                "inference on the AMD token factory (tools/amd_bench.py)."}
    _write("benchmark.json", out)
    return out


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("what", choices=["real", "synth", "bench", "simple", "ai", "all"])
    ap.add_argument("--device", default=None)
    ap.add_argument("--quick", action="store_true")
    a = ap.parse_args()
    dev = a.device or search.device_auto()
    if a.what in ("real", "all"):
        real(dev, a.quick)
    if a.what in ("synth", "all"):
        synthetic(dev, a.quick)
    if a.what in ("bench", "all"):
        bench(a.quick)
    if a.what == "simple":
        simple_only(dev, a.quick)
    from . import client, context, document, explain, writeup
    if a.what in ("real", "ai", "all"):
        explain.build()
    if a.what in ("ai", "all") and client.config()["backend"] in ("amd", "other", "archive"):
        context.build(dev)   # site notes and menu labels -> programs, fitted
        writeup.build()      # as-found specification, guardrailed, with Finnish summary
    document.build()


if __name__ == "__main__":
    main()
