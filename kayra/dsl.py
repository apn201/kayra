"""The structure language: every controller hypothesis is one short expression.

Catalogue programs, language-model proposals and operator hypotheses all go
through this one file. One validator, one compiler, one code path.

A program is a dict:
    {"id": "S1", "params": {"level": "temp_c", "slope": "slope"},
     "expr": "level + slope * T_out"}

The expression returns the SUPPLY temperature the controller stack asks for,
in °C. The building model turns it into heat: h * max(supply - T_room, 0).
`OFF` means "no heat this hour".

Rules, enforced here and nowhere else:
- Parsed with `ast`, whitelist only. Anything else is rejected with a reason.
- No numeric literals. Every number is a declared parameter with a type, and
  the bounds come from PARAM_TYPES below, never from the program. This is how
  "no number came from the language model" survives the model writing code:
  the model writes shape, the search finds every value.
- Complexity cap: MAX_NODES nodes, MAX_PARAMS parameters.

Signals: T_out (FMI outdoor), T_room (the simulated room, a state), OFF.
Functions: hour_of_day(), weekday(), month().
(month() added 2026-10-17 after the model tried to write the controller's autumn-drying term with it.)
Operators: min max clip where lag ema hysteresis integral.

Compiled to batched torch ops: one program, N parameter sets, W windows, one
tensor job. Device is whatever the caller passes - "cuda" on ROCm, else "cpu".
"""

from __future__ import annotations

import ast
from dataclasses import dataclass

import torch

# Generic textbook ranges for building heating. Deliberately wide, and NOT
# narrowed using the Ouman readings (BUILD.md, The structure language).
PARAM_TYPES = {
    "temp_c": (-30.0, 90.0),
    "slope": (-5.0, 5.0),
    "hours": (1.0, 72.0),
    "gain": (0.0, 20.0),
    "fraction": (0.0, 1.0),
    "clock_h": (0.0, 24.0),
    "delta_c": (0.0, 30.0),
    "month_n": (1.0, 12.0),
}
SIGNALS = {"T_out", "T_room", "OFF"}
STATE_SIGNALS = {"T_room"}
FUNCS0 = {"hour_of_day", "weekday", "month"}
OPS = {"min": 2, "max": 2, "clip": 3, "where": 3, "lag": 2, "ema": 2, "hysteresis": 3, "integral": 2}
HOURS_ARG = {"lag": 1, "ema": 1, "integral": 1}  # operator -> index of its `hours` argument
MAX_NODES = 40
MAX_PARAMS = 6
OFF_VALUE = -1.0e4   # supply so low no heat flows; a code constant, not a program literal
WINDUP = 60.0        # integral anti-windup limit, °C·h/h - code constant
MAX_LAG = 72


class Rejected(ValueError):
    """A program the validator refused, with the reason in plain words."""


@dataclass
class Program:
    id: str
    params: dict[str, str]
    expr: str
    tree: ast.AST
    n_nodes: int

    @property
    def k(self) -> int:
        return len(self.params)


def validate(spec: dict) -> Program:
    if not isinstance(spec, dict):
        raise Rejected("a program must be a JSON object")
    pid = str(spec.get("id", "?"))
    raw = spec.get("params") or {}
    if not isinstance(raw, dict):
        raise Rejected("params must be an object of name: type")
    params = dict(raw)
    expr = spec.get("expr", "")
    if not isinstance(expr, str) or not expr.strip():
        raise Rejected("empty expression")
    expr = expr.strip()
    for name, typ in params.items():
        if not isinstance(name, str) or not isinstance(typ, str) or typ not in PARAM_TYPES:
            raise Rejected(f"parameter {name!r} has unknown type {typ!r}; known: {sorted(PARAM_TYPES)}")
        if name in SIGNALS or name in OPS or name in FUNCS0:
            raise Rejected(f"parameter name {name!r} shadows a signal or operator")
    if len(params) > MAX_PARAMS:
        raise Rejected(f"{len(params)} parameters, cap is {MAX_PARAMS}")
    try:
        tree = ast.parse(expr, mode="eval")
    except SyntaxError as exc:
        raise Rejected(f"syntax error: {exc.msg}") from None

    used: set[str] = set()
    count = 0

    def has_state(node) -> bool:
        return any(isinstance(n, ast.Name) and n.id in STATE_SIGNALS for n in ast.walk(node))

    def check(node) -> None:
        nonlocal count
        count += 1
        if isinstance(node, ast.Expression):
            return check(node.body)
        if isinstance(node, ast.Constant):
            raise Rejected(f"numeric literal {node.value!r}: every number must be a typed parameter")
        if isinstance(node, ast.Name):
            if node.id in SIGNALS:
                return
            if node.id in params:
                used.add(node.id)
                return
            raise Rejected(f"unknown name {node.id!r}")
        if isinstance(node, ast.BinOp):
            if not isinstance(node.op, (ast.Add, ast.Sub, ast.Mult, ast.Div, ast.BitAnd, ast.BitOr)):
                raise Rejected(f"operator {type(node.op).__name__} not allowed")
            check(node.left)
            check(node.right)
            return
        if isinstance(node, ast.UnaryOp):
            if not isinstance(node.op, ast.USub):
                raise Rejected(f"unary {type(node.op).__name__} not allowed")
            return check(node.operand)
        if isinstance(node, ast.Compare):
            if len(node.ops) != 1 or not isinstance(node.ops[0], (ast.Lt, ast.Gt, ast.LtE, ast.GtE)):
                raise Rejected("only single <, >, <=, >= comparisons")
            check(node.left)
            check(node.comparators[0])
            return
        if isinstance(node, ast.Call):
            if not isinstance(node.func, ast.Name) or node.keywords:
                raise Rejected("only plain calls to known operators")
            fn = node.func.id
            if fn in FUNCS0:
                if node.args:
                    raise Rejected(f"{fn}() takes no arguments")
                return
            if fn not in OPS:
                raise Rejected(f"unknown operator {fn!r}; known: {sorted(OPS)}")
            if len(node.args) != OPS[fn]:
                raise Rejected(f"{fn} takes {OPS[fn]} arguments, got {len(node.args)}")
            if fn in HOURS_ARG:
                h = node.args[HOURS_ARG[fn]]
                if not (isinstance(h, ast.Name) and params.get(h.id) == "hours"):
                    raise Rejected(f"{fn}: second argument must be a parameter of type 'hours'")
            if fn == "lag" and not (isinstance(node.args[0], ast.Name) and node.args[0].id == "T_out"):
                raise Rejected("lag takes T_out only; use ema or integral for anything else")
            for a in node.args:
                check(a)
            return
        raise Rejected(f"{type(node).__name__} not allowed")

    check(tree)
    if count > MAX_NODES:
        raise Rejected(f"{count} nodes, cap is {MAX_NODES}")
    unused = set(params) - used
    if unused:
        raise Rejected(f"declared but unused parameters: {sorted(unused)}")
    return Program(pid, params, expr, tree, count)


# --------------------------------------------------------------------- compiler

class Inputs:
    """Exogenous signals for a batch of windows, on one device.

    t_out: (T,) full series, so lag and ema warm up before each window.
    starts: (W,) start index of each window. hour/weekday: (T,) local clock.
    """

    def __init__(self, t_out, hour, weekday, starts, device="cpu", dtype=torch.float32, month=None):
        self.device, self.dtype = device, dtype
        self.t_out = torch.as_tensor(t_out, dtype=dtype, device=device)
        self.hour = torch.as_tensor(hour, dtype=dtype, device=device)
        self.weekday = torch.as_tensor(weekday, dtype=dtype, device=device)
        # local calendar month 1..12; 0 where unknown (steady-state curves), so month rules stay off
        self.month = torch.as_tensor(month if month is not None else [0] * len(t_out), dtype=dtype, device=device)
        self.starts = torch.as_tensor(starts, dtype=torch.long, device=device)
        self._ema = None

    def ema_table(self) -> torch.Tensor:
        """EMA of T_out for every integer time constant 1..MAX_LAG hours: (MAX_LAG+1, T)."""
        if self._ema is None:
            T = self.t_out.shape[0]
            alpha = 1.0 / torch.arange(1, MAX_LAG + 1, device=self.device, dtype=self.dtype)
            out = torch.empty(MAX_LAG + 1, T, device=self.device, dtype=self.dtype)
            m = self.t_out[0].repeat(MAX_LAG)
            for i in range(T):  # once per dataset, cached
                m = m + alpha * (self.t_out[i] - m)
                out[1:, i] = m
            out[0] = self.t_out
            self._ema = out
        return self._ema


class _Node:
    def reset(self, shape, ctx): ...
    def __call__(self, ctx): ...


def _hours_index(p: torch.Tensor) -> torch.Tensor:
    return p.round().clamp(1, MAX_LAG).long()


class Compiled:
    """A validated program bound to a parameter batch. Call `step(ctx)` once per hour."""

    def __init__(self, prog: Program, theta: dict[str, torch.Tensor]):
        self.prog = prog
        self.theta = {k: v.reshape(-1, 1) for k, v in theta.items()}  # (N,1)
        self.stateful: list[dict] = []
        self.fn = self._build(prog.tree.body)

    def reset(self, N: int, W: int, ctx) -> None:
        for s in self.stateful:
            s["init"](N, W, ctx)

    def _build(self, node):
        th = self.theta
        if isinstance(node, ast.Name):
            n = node.id
            if n == "T_out":
                return lambda c: c.t_out_now
            if n == "T_room":
                return lambda c: c.T_room
            if n == "OFF":
                return lambda c: torch.full_like(c.T_room, OFF_VALUE)
            v = th[n]
            return lambda c: v
        if isinstance(node, ast.UnaryOp):
            f = self._build(node.operand)
            return lambda c: -f(c)
        if isinstance(node, ast.BinOp):
            a, b = self._build(node.left), self._build(node.right)
            op = node.op
            if isinstance(op, ast.Add):
                return lambda c: a(c) + b(c)
            if isinstance(op, ast.Sub):
                return lambda c: a(c) - b(c)
            if isinstance(op, ast.Mult):
                return lambda c: a(c) * b(c)
            if isinstance(op, ast.Div):
                return lambda c: a(c) / torch.where(b(c).abs() < 1e-6, torch.full_like(b(c), 1e-6), b(c))
            if isinstance(op, ast.BitAnd):
                return lambda c: ((a(c) > 0.5) & (b(c) > 0.5)).to(c.dtype)
            if isinstance(op, ast.BitOr):
                return lambda c: ((a(c) > 0.5) | (b(c) > 0.5)).to(c.dtype)
        if isinstance(node, ast.Compare):
            a, b = self._build(node.left), self._build(node.comparators[0])
            op = node.ops[0]
            cmp = {ast.Lt: torch.lt, ast.Gt: torch.gt, ast.LtE: torch.le, ast.GtE: torch.ge}[type(op)]
            return lambda c: cmp(*torch.broadcast_tensors(a(c), b(c))).to(c.dtype)
        if isinstance(node, ast.Call):
            fn = node.func.id
            if fn == "hour_of_day":
                return lambda c: c.hour_now
            if fn == "weekday":
                return lambda c: c.weekday_now
            if fn == "month":
                return lambda c: c.month_now
            args = node.args
            if fn == "lag":
                L = _hours_index(th[args[1].id])  # (N,1)
                if isinstance(args[0], ast.Name) and args[0].id == "T_out":
                    return lambda c: c.inputs.t_out[(c.t_idx - L).clamp(min=0)]
                raise Rejected("lag of an expression: use lag(T_out, p)")
            if fn == "ema":
                hp = th[args[1].id]
                if isinstance(args[0], ast.Name) and args[0].id == "T_out":
                    L = _hours_index(hp)
                    return lambda c: c.inputs.ema_table()[L, c.t_idx]  # warm from the full series
                f = self._build(args[0])
                st = {}

                def init(N, W, c, st=st, f=f):
                    st["m"] = None

                def run(c, st=st, f=f, hp=hp):
                    x = f(c)
                    if st["m"] is None:
                        st["m"] = x.expand(c.T_room.shape).clone()
                    else:
                        st["m"] = st["m"] + (x - st["m"]) / hp.clamp(min=1.0)
                    return st["m"]

                self.stateful.append({"init": init})
                return run
            if fn == "integral":
                f, hp = self._build(args[0]), th[args[1].id]
                st = {}

                def init(N, W, c, st=st):
                    st["I"] = torch.zeros(N, W, device=c.device, dtype=c.dtype)

                def run(c, st=st, f=f, hp=hp):
                    st["I"] = (st["I"] + f(c) / hp.clamp(min=1.0)).clamp(-WINDUP, WINDUP)
                    return st["I"]

                self.stateful.append({"init": init})
                return run
            if fn == "hysteresis":
                f, lo_f, hi_f = (self._build(a) for a in args)
                st = {}

                def init(N, W, c, st=st):
                    st["s"] = None

                def run(c, st=st, f=f, lo_f=lo_f, hi_f=hi_f):
                    x, lo, hi = f(c), lo_f(c), hi_f(c)
                    lo, hi = torch.minimum(lo, hi), torch.maximum(lo, hi)
                    x, lo, hi = torch.broadcast_tensors(x, lo, hi)
                    if st["s"] is None:
                        st["s"] = x < (lo + hi) / 2
                    st["s"] = torch.where(x < lo, torch.ones_like(st["s"]), torch.where(x > hi, torch.zeros_like(st["s"]), st["s"]))
                    return st["s"].to(c.dtype)

                self.stateful.append({"init": init})
                return run
            fs = [self._build(a) for a in args]
            if fn == "min":
                return lambda c: torch.minimum(*torch.broadcast_tensors(fs[0](c), fs[1](c)))
            if fn == "max":
                return lambda c: torch.maximum(*torch.broadcast_tensors(fs[0](c), fs[1](c)))
            if fn == "clip":
                def clip(c):
                    x, lo, hi = torch.broadcast_tensors(fs[0](c), fs[1](c), fs[2](c))
                    return torch.minimum(torch.maximum(x, torch.minimum(lo, hi)), torch.maximum(lo, hi))
                return clip
            if fn == "where":
                return lambda c: torch.where(*torch.broadcast_tensors(fs[0](c) > 0.5, fs[1](c), fs[2](c)))
        raise Rejected(f"cannot compile {ast.dump(node)[:60]}")


class StepContext:
    """What a program sees at one hour of a batch of windows."""

    def __init__(self, inputs: Inputs):
        self.inputs = inputs
        self.device, self.dtype = inputs.device, inputs.dtype
        self.T_room = None
        self.t_idx = None

    def at(self, k: int, T_room: torch.Tensor) -> "StepContext":
        self.t_idx = self.inputs.starts + k                     # (W,)
        self.T_room = T_room                                    # (N,W)
        self.t_out_now = self.inputs.t_out[self.t_idx].unsqueeze(0)
        self.hour_now = self.inputs.hour[self.t_idx].unsqueeze(0)
        self.weekday_now = self.inputs.weekday[self.t_idx].unsqueeze(0)
        self.month_now = self.inputs.month[self.t_idx].unsqueeze(0)
        return self


def sample_params(prog: Program, n: int, gen: torch.Generator, device="cpu") -> dict[str, torch.Tensor]:
    out = {}
    for name, typ in prog.params.items():
        lo, hi = PARAM_TYPES[typ]
        out[name] = lo + (hi - lo) * torch.rand(n, generator=gen, device=device)
    return out
