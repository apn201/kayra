"""The hypothesis loop: propose programs, fit them on the device, score, keep a lab notebook.

Proposers, all returning programs in the same structure language and all going
through the same validator and fitter:
    llm        the language model (client.py). Arm C. Archived.
    standin    hand-written programs from kayra/standin/*.json, used ONLY while
               the AMD endpoint is down, for the real-data demo. Labelled
               "stand-in (hand-written)" in every artifact and on every screen.
               Never used in the synthetic benchmark - the developer wrote the
               hidden controllers, so stand-in proposals there would be a leak.
    baseline   grammar expansion (baseline_search.py). Arm B.

The prompt (prompts/hypothesize_v2.md) is frozen: changing it means rerunning
every arm. v2 (2026-10-17) adds month() to the language; artifacts made with v1
are from before that and must be rerun.
"""

from __future__ import annotations

import json
import random
from pathlib import Path

from . import baseline_search, client, dsl, search

HERE = Path(__file__).resolve().parent
PROMPT = (HERE / "prompts" / "hypothesize_v2.md").read_text(encoding="utf-8")
GRAMMAR = PROMPT.split("You get:")[0]


def _brief(rank_rows: list[dict], specs: dict) -> list[dict]:
    return [{"id": r["id"], "expr": specs[r["id"]]["expr"], "params": specs[r["id"]]["params"],
             "rmse_held_c": r["rmse_held_c"], "delta_bic": r["delta_bic"], "source": r["source"]}
            for r in rank_rows]


class LLMProposer:
    label = "language model"

    def __init__(self, cfg=None):
        self.cfg = cfg or client.config()

    def __call__(self, ranked, specs, residual, notebook, n, round_no):
        packet = {"ranked_programs": _brief(ranked, specs)[:8], "residual_report": residual,
                  "notebook": [{k: e.get(k) for k in ("id", "expr", "verdict", "rmse_held_c")} for e in notebook]}
        user = "Round {}.\n\n```json\n{}\n```".format(round_no, json.dumps(packet, indent=1))
        rep = client.chat(PROMPT, user, purpose=f"hypothesize round {round_no}", cfg=self.cfg)
        props = self._parse(rep, round_no, "")[:n]
        # rejects go back to the model once, with the validator's reason (BUILD.md, loop step 4)
        rejects = []
        for p in props:
            try:
                dsl.validate(p)
            except dsl.Rejected as exc:
                rejects.append({"id": p["id"], "params": p.get("params"), "expr": p.get("expr"), "reason": str(exc)})
        if rejects:
            fix = ("The validator rejected these programs. Return corrected versions as a JSON array in the same "
                   "format, one per rejected program, or none if a mechanism cannot be written in the language. "
                   "Remember: no numeric literals, declare every parameter you use, use every parameter you declare."
                   "\n\n```json\n{}\n```".format(json.dumps(rejects, indent=1)))
            try:
                rep2 = client.chat(PROMPT, user + "\n\n" + fix, purpose=f"repair round {round_no}", cfg=self.cfg)
                for p in self._parse(rep2, round_no, "r")[:len(rejects)]:
                    p["mechanism"] = (p.get("mechanism") or "") + " (repaired after validator rejection)"
                    props.append(p)
            except client.LLMError:
                pass
        return props

    def _parse(self, rep, round_no, tag):
        props = client.extract_json(rep.text) or []
        if isinstance(props, dict):
            props = props.get("programs") or [props]
        out = []
        for i, p in enumerate(p for p in props if isinstance(p, dict)):
            p["proposed_id"] = p.get("id")
            p["id"] = f"M{round_no}.{i + 1}{tag}"  # model ids never collide with catalogue or synthetic names
            p["source"] = ("model (AMD)" if rep.backend == "amd" else
                           f"model ({(self.cfg.get('fallback') or {}).get('label', 'fallback')})" if rep.backend == "fallback"
                           else f"model ({client.status(self.cfg)})")
            p["prompt_hash"] = rep.prompt_hash
            out.append(p)
        return out


class StandinProposer:
    """Hand-written stand-ins for the model, one list per round. Labelled, never hidden."""
    label = "stand-in (hand-written)"

    def __init__(self, path: Path):
        self.rounds = json.loads(path.read_text(encoding="utf-8"))["rounds"]

    def __call__(self, ranked, specs, residual, notebook, n, round_no):
        if round_no > len(self.rounds):
            return []
        return [p | {"source": self.label} for p in self.rounds[round_no - 1][:n]]


class BaselineProposer:
    label = "baseline-grammar"

    def __init__(self, seed=0):
        self.rng = random.Random(seed)
        self.seen: set[str] = set()

    def __call__(self, ranked, specs, residual, notebook, n, round_no):
        self.seen |= {s["expr"] for s in specs.values()}
        return baseline_search.propose([specs[r["id"]] for r in ranked], n, self.rng, self.seen)


def run(problem: search.Problem, seed_specs: list[dict], proposer, rounds: int = 5, per_round: int = 4,
        n: int = 1536, iters: int = 6, noise_band: float = 2.0, seed_results=None, patience: int = 2) -> dict:
    results = list(seed_results or [search.search(problem, s, n=n, iters=iters) for s in seed_specs])
    specs = {r["prog"].id: r["spec"] for r in results}
    ranked = search.rank(results, problem)
    notebook = [{"round": 0, "id": r["id"], "source": r["source"], "expr": specs[r["id"]]["expr"],
                 "mechanism": specs[r["id"]].get("name", ""), "rmse_held_c": r["rmse_held_c"],
                 "delta_bic": r["delta_bic"], "verdict": "seed"} for r in ranked]
    fits = sum(r["evals"] for r in results)
    stale = 0
    for rnd in range(1, rounds + 1):
        best_bic = ranked[0]["bic"]
        best = next(r for r in results if r["prog"].id == ranked[0]["id"])
        residual = search.residual_report(problem, best)
        try:
            props = proposer(ranked, specs, residual, notebook, per_round, rnd)
        except client.LLMError as exc:
            notebook.append({"round": rnd, "id": "-", "source": proposer.label, "verdict": f"proposer failed: {exc}"})
            break
        if not props:
            break
        new = []
        for i, p in enumerate(props):
            pid = str(p.get("id") or f"R{rnd}.{i + 1}")
            if pid in specs:
                pid = f"{pid}.r{rnd}"
            p = dict(p, id=pid)
            entry = {"round": rnd, "id": pid, "source": p.get("source"), "expr": p.get("expr"),
                     "params": p.get("params"), "mechanism": p.get("mechanism") or p.get("name", ""),
                     "targets": p.get("targets", ""), "refute": p.get("refute", "")}
            try:
                dsl.validate(p)
            except dsl.Rejected as exc:
                entry["verdict"] = f"rejected by validator: {exc}"
                notebook.append(entry)
                continue
            r = search.search(problem, p, n=n, iters=iters, seed=rnd * 100 + i)
            fits += r["evals"]
            results.append(r)
            specs[pid] = p
            new.append((entry, r))
        ranked = search.rank(results, problem)
        by_id = {x["id"]: x for x in ranked}
        for entry, r in new:
            row = by_id[entry["id"]]
            entry.update(rmse_held_c=row["rmse_held_c"], delta_bic=row["delta_bic"],
                         verdict=("new best" if row["delta_bic"] == 0 and row["bic"] < best_bic - noise_band
                                  else "survives (within noise of best)" if row["delta_bic"] < noise_band
                                  else "refuted (worse than best by more than the noise band)"))
            notebook.append(entry)
        if ranked[0]["bic"] > best_bic - noise_band:
            stale += 1
            if stale >= patience:
                notebook.append({"round": rnd, "id": "-", "source": "loop",
                                 "verdict": f"stop: {patience} rounds without a program improving the held-out score by more than the noise band"})
                break
        else:
            stale = 0
    return {"ranked": ranked, "notebook": notebook, "results": results, "specs": specs, "fits": fits}
