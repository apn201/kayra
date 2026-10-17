"""Batched parameter search: every program x thousands of parameter sets x windows, as tensors.

Building, per room, per hour (BUILD.md, Identifiability):

    T[t+1] = T + a*(T_out - T) + h*max(S - T, 0) + g0 + g1*cos(2*pi*(hour - phi)/24)

S is the supply the program asks for. The product never sees S; it sees T_out
in and the room out. Score = simulation error over 48-hour windows started
from the measured room temperature. Weeks are split 3:1 into fit and held-out;
everything reported is on held-out weeks.

Search: cross-entropy method in the unit cube. Each iteration samples N
candidates, simulates all of them over all windows in one batched loop, keeps
the elite, refits a Gaussian. Embarrassingly parallel, which is why it runs on
the GPU: device "cuda" (what ROCm presents as) when present, else CPU.
"""

from __future__ import annotations

import json
import math
import time
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import torch

from . import dsl
from .load import Frame

STRUCT_DIR = Path(__file__).resolve().parent / "structures"
WINDOW = 72
BURN = 48   # hours the controller runs on MEASURED room temperature before each window,
            # so integrators, filters and hysteresis start in a realistic state
STRIDE = 24
# Building parameter bounds - generic, wide. (lo, hi, log-scale?)
BUILDING = {
    "a": (1e-4, 0.1, True),      # loss to outdoor per hour (time constant 10 h .. 10000 h)
    "h": (1e-4, 0.2, True),      # heating coupling per hour per °C of supply over room
    "g0": (-0.3, 0.3, False),    # constant gain, °C/h
    "g1": (0.0, 0.3, False),     # daily gain amplitude, °C/h
    "phi": (0.0, 24.0, False),   # daily gain peak, local hour
}
CURVE_GRID = list(range(-10, 21, 2))


def device_auto() -> str:
    return "cuda" if torch.cuda.is_available() else "cpu"


def hardware(device: str) -> dict:
    info = {"device": device, "torch": torch.__version__,
            "hip": getattr(torch.version, "hip", None), "cuda": torch.version.cuda,
            "threads": torch.get_num_threads()}
    if device == "cuda":
        info["gpu"] = torch.cuda.get_device_name(0)
    else:
        import platform
        info["cpu"] = platform.processor() or platform.machine()
    return info


def load_catalogue() -> list[dict]:
    return [json.loads(p.read_text(encoding="utf-8")) | {"source": "catalogue"}
            for p in sorted(STRUCT_DIR.glob("S*.json"))]


@dataclass
class Windows:
    starts: np.ndarray       # (W,) index of window start
    held: np.ndarray         # (W,) bool, held-out week
    T0: np.ndarray           # (W,) measured room at start
    meas: np.ndarray         # (W, WINDOW) measured room at steps 1..WINDOW
    burn: np.ndarray         # (W, BURN) measured room over the BURN hours before the start


SEASONS = {"all": (-99, 99), "cold": (-99, 12.0), "warm": (15.0, 99)}


def make_windows(f: Frame, room: str, season: str = "all") -> Windows:
    """Windows by mean outdoor over the window: 'cold' = heating plausible, 'warm' = free-float."""
    lo, hi = SEASONS[season]
    T = f.rooms[room]
    n = len(f)
    starts, held = [], []
    # start at local midnight so every window sees the same clock
    first = int(np.flatnonzero(f.hour_local == 0)[0])
    while first < BURN:
        first += 24
    for s in range(first, n - WINDOW - 1, STRIDE):
        seg = T[s - BURN:s + WINDOW + 1]
        if np.isnan(seg).any() or np.isnan(f.t_out[s:s + WINDOW + 1]).any():
            continue
        if not lo <= float(np.mean(f.t_out[s:s + WINDOW + 1])) < hi:
            continue
        starts.append(s)
        held.append(((s - first) // (24 * 7)) % 4 == 3)
    starts = np.array(starts)
    return Windows(starts, np.array(held), T[starts], np.stack([T[s + 1:s + WINDOW + 1] for s in starts]),
                   np.stack([T[s - BURN:s] for s in starts]))


class Problem:
    """One room - or a group of rooms on one heating loop - on one device. Reused across programs.

    A group shares ONE controller program (one set of program parameters) and gives
    every room its own building parameters. Rooms are stacked along the window axis,
    so the group is still a single batched simulation.
    """

    def __init__(self, f: Frame, room, device: str = "cpu", season: str = "all", building=None):
        self.rooms = [room] if isinstance(room, str) else list(room)
        self.room = self.rooms[0]
        self.f, self.device, self.season = f, device, season
        R = len(self.rooms)
        if building is None or isinstance(building, dict):
            self.buildings = [dict(building or BUILDING) for _ in range(R)]
        else:
            self.buildings = [dict(x) for x in building]
        self.building = self.buildings[0]
        parts = []
        for r in self.rooms:
            w = make_windows(f, r, season)
            if len(w.starts) < 8 or w.held.sum() < 2:
                raise ValueError(f"{r}/{season}: only {len(w.starts)} windows - not enough data")
            parts.append(w)
        self.win = Windows(np.concatenate([w.starts for w in parts]), np.concatenate([w.held for w in parts]),
                           np.concatenate([w.T0 for w in parts]), np.concatenate([w.meas for w in parts]),
                           np.concatenate([w.burn for w in parts]))
        self.room_idx_np = np.concatenate([np.full(len(w.starts), i) for i, w in enumerate(parts)])
        self.room_idx = torch.as_tensor(self.room_idx_np, device=device)
        t_out = np.nan_to_num(f.t_out, nan=float(np.nanmean(f.t_out)))
        self.inputs_all = dsl.Inputs(t_out, f.hour_local, f.weekday_local, self.win.starts, device,
                                     month=getattr(f, "month_local", None))
        self.T0 = torch.as_tensor(self.win.T0, dtype=torch.float32, device=device)
        self.meas = torch.as_tensor(self.win.meas, dtype=torch.float32, device=device)
        self.burn = torch.as_tensor(self.win.burn, dtype=torch.float32, device=device)
        self.held = torch.as_tensor(self.win.held, device=device)
        self.medians = [float(np.nanmedian(f.rooms[r])) for r in self.rooms]
        self.median = self.medians[0]

    def simulate(self, prog: dsl.Program, theta: dict, b: dict, inputs=None, T0=None, steps=WINDOW,
                 record_supply=False, burn=True, room: int = 0):
        own = inputs is None
        inputs = inputs or self.inputs_all
        T0 = self.T0 if T0 is None else T0
        N = next(iter(b.values())).shape[0]
        W = inputs.starts.shape[0]
        comp = dsl.Compiled(prog, theta)
        ctx = dsl.StepContext(inputs)
        if own and burn:
            # burn-in: the controller sees the measured room; its output is discarded
            Tm = self.burn[:, 0].reshape(1, -1).expand(N, W).clone()
            comp.reset(N, W, ctx.at(-BURN, Tm))
            for j in range(BURN):
                comp.fn(ctx.at(j - BURN, self.burn[:, j].reshape(1, -1).expand(N, W)))
        else:
            comp.reset(N, W, ctx.at(0, T0.reshape(1, -1).expand(N, W)))
        T = T0.reshape(1, -1).expand(N, W).clone()
        # building parameters (N, R) -> (N, W): every window takes the column of its own room
        ridx = self.room_idx if own else torch.full((W,), room, device=self.device, dtype=torch.long)
        cols = {k: b[k].reshape(N, -1) for k in ("a", "h", "g0", "g1", "phi")}
        a, h, g0, g1, phi = (v[:, ridx] if v.shape[1] > 1 else v for v in cols.values())
        out = torch.empty(N, W, steps, device=self.device)
        sup = torch.empty(N, W, steps, device=self.device) if record_supply else None
        two_pi = 2 * math.pi
        for k in range(steps):
            ctx.at(k, T)
            S = comp.fn(ctx)
            if S.dim() < 2 or S.shape != T.shape:
                S = S.expand_as(T)
            heat = h * torch.clamp(S - T, min=0.0)
            T = T + a * (ctx.t_out_now - T) + heat + g0 + g1 * torch.cos(two_pi * (ctx.hour_now - phi) / 24)
            out[:, :, k] = T
            if record_supply:
                sup[:, :, k] = torch.where(S > dsl.OFF_VALUE / 2, S, torch.full_like(S, float("nan")))
        return out, sup

    def held_by_room(self, pred: torch.Tensor) -> list[float]:
        """Held-out MSE per room for one candidate: pred (1, W, K)."""
        per_w = ((pred[0] - self.meas) ** 2).mean(dim=1)
        return [float(per_w[(self.room_idx == i) & self.held].mean()) for i in range(len(self.rooms))]

    def mse(self, pred: torch.Tensor) -> tuple[torch.Tensor, torch.Tensor]:
        err = (pred - self.meas.unsqueeze(0)) ** 2           # (N,W,K)
        per_w = err.mean(dim=2)                              # (N,W)
        fit = per_w[:, ~self.held].mean(dim=1)
        held = per_w[:, self.held].mean(dim=1)
        return fit, held


# ---------------------------------------------------------------- parameter map

def summer_prior(f: Frame, room: str, device: str = "cpu", n: int = 1536, iters: int = 6) -> dict:
    """Stage 1: free-float fit on warm windows (heating off, no controller in the way).
    Returns building bounds for stage 2: loss `a` within a factor of 3 of the summer
    estimate. Gains stay free - sun and ventilation differ between seasons."""
    p = Problem(f, room, device, season="warm")
    s0 = json.loads((STRUCT_DIR / "S0.json").read_text(encoding="utf-8"))
    r = search(p, s0, n=n, iters=iters)
    a = r["best_b"]["a"]
    bounds = dict(BUILDING)
    bounds["a"] = (max(BUILDING["a"][0], a / 3), min(BUILDING["a"][1], a * 3), True)
    return {"bounds": bounds, "summer_fit": r["best_b"], "rmse_held_c": math.sqrt(r["held_mse"]),
            "windows": int(len(p.win.starts)), "time_constant_h": round(1 / a, 1)}


def _from_unit(prog: dsl.Program, u: torch.Tensor, buildings=None) -> tuple[dict, dict]:
    """Unit cube -> parameters. Layout: [room0 building | room1 building | ... | program].
    Building values come out as (N, R)."""
    if buildings is None or isinstance(buildings, dict):
        buildings = [buildings or BUILDING]
    R, nb = len(buildings), len(BUILDING)
    b, th = {}, {}
    for i, name in enumerate(BUILDING):
        cols = []
        for r, bounds in enumerate(buildings):
            lo, hi, log = bounds[name]
            x = u[:, r * nb + i]
            cols.append(torch.exp(math.log(lo) + x * (math.log(hi) - math.log(lo))) if log else lo + x * (hi - lo))
        b[name] = torch.stack(cols, dim=1)
    for j, (name, typ) in enumerate(prog.params.items()):
        lo, hi = dsl.PARAM_TYPES[typ]
        th[name] = lo + u[:, R * nb + j] * (hi - lo)
    return b, th


def _unbatch(d: dict, i: int, col: int | None = None) -> dict:
    return {k: float(v[i] if col is None else v[i, col]) for k, v in d.items()}


def search(problem: Problem, spec: dict, n: int = 1536, iters: int = 6, elite_frac: float = 0.06,
           seed: int = 0, anchors=None) -> dict:
    """CEM over building + program parameters. Returns the best candidate and a weighted population.

    anchors: optional (t_out_controller, supply, sigma) arrays - spot readings of the
    controller's output. Adds a penalty for the steady-state curve missing them.
    Anchored runs are labelled as such by the caller.
    """
    prog = dsl.validate(spec)
    dev = problem.device
    R = len(problem.rooms)
    d = R * len(BUILDING) + prog.k
    gen = torch.Generator(device="cpu").manual_seed(seed)
    mean = torch.full((d,), 0.5)
    std = torch.full((d,), 0.5)
    n_elite = max(8, int(n * elite_frac))
    best = None
    pop_u = pop_score = pop_held = None
    t0 = time.perf_counter()
    evals = 0
    refine = max(2, iters // 2)  # local stage: shrinking Gaussian around the best so far
    for it in range(iters + refine):
        if it == 0:
            u = torch.rand(n, d, generator=gen)
        elif it < iters:
            u = (mean + std * torch.randn(n, d, generator=gen)).clamp(0, 1)
        else:
            scale = 0.05 * 0.5 ** (it - iters)
            u = (best[1] + scale * torch.randn(n, d, generator=gen)).clamp(0, 1)
            u[0] = best[1]
        u = u.to(dev)
        b, th = _from_unit(prog, u, problem.buildings)
        pred, _ = problem.simulate(prog, th, b)
        fit, held = problem.mse(pred)
        score = fit.clone()
        if anchors is not None:
            score = score + _anchor_penalty(problem, prog, th, b, anchors, fit)
        score = torch.nan_to_num(score, nan=1e9, posinf=1e9)
        evals += n
        order = torch.argsort(score)
        el = u[order[:n_elite]].cpu()
        mean, std = el.mean(0), el.std(0).clamp(min=0.01)
        if best is None or score[order[0]] < best[0]:
            best = (float(score[order[0]]), u[order[0]].cpu(), float(fit[order[0]]), float(held[order[0]]))
        pop_u, pop_score, pop_held, pop_fit = u.cpu(), score.cpu(), held.cpu(), fit.cpu()
    if dev == "cuda":
        torch.cuda.synchronize()
    wall = time.perf_counter() - t0

    # population weights: Gaussian likelihood relative to the best, effective sample = fit days
    n_eff = int((~problem.held).sum().item()) * WINDOW / 24
    if anchors is not None:
        pop_score = torch.nan_to_num(pop_score, nan=1e9)
    s_min = float(pop_score.min())
    w = torch.exp(-0.5 * n_eff * (pop_score / s_min - 1)).double()
    w = w / w.sum()
    bu = best[1].reshape(1, -1).to(dev)
    bb, bth = _from_unit(prog, bu, problem.buildings)
    rooms_b = [_unbatch(bb, 0, r) for r in range(R)]
    bpred, _ = problem.simulate(prog, bth, bb)
    return {
        "prog": prog, "spec": spec,
        "best_b": rooms_b[0], "best_b_rooms": rooms_b, "best_theta": _unbatch(bth, 0),
        "held_rmse_rooms": [round(math.sqrt(x), 3) for x in problem.held_by_room(bpred)],
        "fit_mse": best[2], "held_mse": best[3],
        "pop_u": pop_u, "pop_w": w, "evals": evals, "wall_s": wall,
    }


# ------------------------------------------------------------ steady-state curve

def steady_curve(problem: Problem, prog: dsl.Program, theta: dict, b: dict, grid=CURVE_GRID, hours=240,
                 room: int = 0):
    """What the identified law asks for at constant outdoor, in closed loop: (N, G) supply °C.

    Constant outdoor per grid point, building simulated from the room's as-found
    median, mean supply over the last day. NaN where the law asks for no heat.
    """
    G = len(grid)
    seg = hours + 1
    t_out = np.concatenate([np.full(seg, g, float) for g in grid])
    hour = np.tile(np.arange(seg) % 24, G)
    wd = np.full(seg * G, 2)
    starts = np.arange(G) * seg
    inp = dsl.Inputs(t_out, hour, wd, starts, problem.device)
    T0 = torch.full((G,), problem.medians[room], device=problem.device)
    _, sup = problem.simulate(prog, theta, b, inputs=inp, T0=T0, steps=hours, record_supply=True, room=room)
    tail = sup[:, :, -24:]
    on = (~torch.isnan(tail)).float().mean(dim=2)
    val = torch.nanmean(tail, dim=2)
    return torch.where(on > 0.5, val, torch.full_like(val, float("nan")))


def _anchor_penalty(problem, prog, th, b, anchors, fit):
    t_ctrl, supply, sigma = anchors
    grid = sorted(set(float(x) for x in t_ctrl))
    curve = steady_curve(problem, prog, th, b, grid=grid, hours=120)  # (N, G)
    idx = torch.as_tensor([grid.index(float(x)) for x in t_ctrl], device=problem.device)
    pred = curve[:, idx]
    r = torch.as_tensor(np.asarray(supply, float), dtype=torch.float32, device=problem.device)
    chi2 = torch.nan_to_num(((pred - r) / sigma) ** 2, nan=100.0).sum(dim=1)
    # Weighting: a spot reading observes the controller output directly, while the
    # room record sees it only through h*S, where level and h trade off. So the
    # room record counts as ONE block here (its mean error), not as n_eff days.
    # Stated in the document; anchored mode is labelled everywhere.
    noise = fit.min().detach()
    return noise * chi2


def population_curve(problem: Problem, res: dict, k: int = 256, room: int = 0) -> dict:
    """Weighted band of the steady-state curve over the top-k population members."""
    w = res["pop_w"]
    top = torch.argsort(w, descending=True)[:k]
    u = res["pop_u"][top].to(problem.device)
    b, th = _from_unit(res["prog"], u, problem.buildings)
    curve = steady_curve(problem, res["prog"], th, b, room=room).cpu().double().numpy()  # (k, G)
    ww = w[top].numpy()
    ww = ww / ww.sum()
    bands = {"grid_c": CURVE_GRID, "p05": [], "p50": [], "p95": [], "heat_on_share": []}
    for g in range(curve.shape[1]):
        col = curve[:, g]
        on = ~np.isnan(col)
        share = float(ww[on].sum())
        bands["heat_on_share"].append(round(share, 3))
        if share < 0.5:
            for q in ("p05", "p50", "p95"):
                bands[q].append(None)
            continue
        c, cw = col[on], ww[on] / ww[on].sum()
        o = np.argsort(c)
        cdf = np.cumsum(cw[o])
        for q, p in (("p05", 0.05), ("p50", 0.5), ("p95", 0.95)):
            bands[q].append(round(float(c[o][np.searchsorted(cdf, p).clip(0, len(c) - 1)]), 2))
    return bands


def best_tensors(problem: Problem, res: dict) -> tuple[dict, dict]:
    rb = res.get("best_b_rooms") or [res["best_b"]]
    b = {k: torch.tensor([[x[k] for x in rb]], device=problem.device) for k in BUILDING}
    th = {k: torch.tensor([v], device=problem.device) for k, v in res["best_theta"].items()}
    return b, th


def residual_report(problem: Problem, res: dict, room: int | None = None) -> dict:
    """What the best program fails to explain - the language model's input. Numbers only.
    For a loop group without `room`: one report per room."""
    if room is None and len(problem.rooms) > 1:
        return {"loop_rooms": {problem.rooms[i]: residual_report(problem, res, i) for i in range(len(problem.rooms))}}
    room = room or 0
    prog = res["prog"]
    b, th = best_tensors(problem, res)
    pred, sup = problem.simulate(prog, th, b, record_supply=True)
    sel = problem.room_idx_np == room
    r = (pred[0] - problem.meas).cpu().numpy()[sel]                    # (W,K)
    sup = sup[:, sel]
    st = problem.win.starts[sel]
    idx = st[:, None] + np.arange(1, WINDOW + 1)[None, :]
    f = problem.f
    hour = f.hour_local[idx]
    tout = f.t_out[idx]
    wd = f.weekday_local[idx]
    month = np.array([[f.t[i].month for i in row] for row in idx])
    held = problem.win.held[sel][:, None].repeat(WINDOW, 1)
    hum = f.humidity[problem.rooms[room]][idx]

    def by(key, vals):
        out = {}
        for v in np.unique(vals):
            m = vals == v
            out[str(int(v))] = round(float(r[m].mean()), 3)
        return out

    band = np.digitize(tout, [0, 5, 10, 15, 20])
    labels = ["<0", "0-5", "5-10", "10-15", "15-20", ">20"]
    heat_on = (~np.isnan(sup[0].cpu().numpy())).mean()
    ok = ~np.isnan(hum)
    return {
        "room": problem.rooms[room], "program": prog.id,
        "rmse_held_c": (res.get("held_rmse_rooms") or [round(math.sqrt(res["held_mse"]), 3)])[room],
        "mean_by_local_hour": by("hour", hour),
        "mean_by_month": by("month", month),
        "mean_by_outdoor_band": {labels[i]: round(float(r[band == i].mean()), 3) for i in np.unique(band)},
        "weekend_minus_weekday": round(float(r[wd >= 5].mean() - r[wd < 5].mean()), 3),
        "mean_by_weekday": by("weekday", wd),
        "night_00_06_weekday_minus_weekend": round(float(r[(hour < 6) & (wd < 5)].mean() - r[(hour < 6) & (wd >= 5)].mean()), 3),
        "corr_with_outdoor": round(float(np.corrcoef(r.ravel(), tout.ravel())[0, 1]), 3),
        "corr_with_humidity": round(float(np.corrcoef(r[ok], hum[ok])[0, 1]), 3) if ok.sum() > 10 else None,
        "heat_on_share_of_hours": round(float(heat_on), 3),
        "held_out_hours": int(held.sum()),
    }


def rank(results: list[dict], problem: Problem) -> list[dict]:
    """BIC-style ranking on held-out error. n_eff = held-out days, because hours in a
    window are not independent. Ties (delta < 2) are flagged as ties."""
    n_eff = int(problem.held.sum().item()) * WINDOW / 24
    rows = []
    for r in results:
        k = len(problem.rooms) * len(BUILDING) + r["prog"].k
        bic = n_eff * math.log(max(r["held_mse"], 1e-9)) + k * math.log(n_eff)
        rows.append({"id": r["prog"].id, "name": r["spec"].get("name", ""), "source": r["spec"].get("source"),
                     "k": k, "rmse_fit_c": round(math.sqrt(r["fit_mse"]), 3),
                     "rmse_held_c": round(math.sqrt(r["held_mse"]), 3), "bic": round(bic, 2),
                     "evals": r["evals"], "wall_s": round(r["wall_s"], 2)})
    rows.sort(key=lambda x: x["bic"])
    b0 = rows[0]["bic"]
    z = sum(math.exp(-0.5 * (x["bic"] - b0)) for x in rows)
    for x in rows:
        x["delta_bic"] = round(x["bic"] - b0, 2)
        x["prob"] = round(math.exp(-0.5 * (x["bic"] - b0)) / z, 4)
        x["tie_with_best"] = x["delta_bic"] < 2 and x is not rows[0]
    return rows
