# Käyrä

Käyrä works out what an undocumented controller is doing from the data a site already logs. No vendor, no manual, no bump test.

Test bench is a real district heating substation (Ouman EH-203, two heating loops) on a real building in Kouvola. Home Assistant room sensors in, FMI outdoor temperature in. The controller is never touched.

AMD Developer Hackathon ACT III, Track 1 Intelligent Industry.

## State on 2026-10-17

AMD Developer Cloud was unavailable on the last build day. So this version runs like this:

- The fitter runs on CPU (PyTorch). It is the same code that runs on ROCm, the device is picked at runtime. The GPU benchmark row says NOT MEASURED until it is run on the droplet. No estimate is given.
- The language model runs on OpenRouter as a stand-in endpoint, using DeepSeek-V4.1-Flash, which is also on the AMD token factory list. The panel shows it as STAND-IN (not AMD). Swapping is one block in `.env` plus `python tools/llm_check.py`, see [docs/AMD_SWAP.md](docs/AMD_SWAP.md).
- Room data ends 2026-10-03 (the last Home Assistant export). Outdoor data runs to today. The heating season since then is in Home Assistant and needs `tools/pull_ha.py` on the LAN.

## Run it

Python 3.11+.

```
python -m venv .venv
.venv\Scripts\pip install -r requirements.txt
.venv\Scripts\python -m kayra.run all          # real house, synthetic benchmark, CPU timing (about 30 min on a laptop)
.venv\Scripts\python -m kayra.run real --quick # smoke test, under a minute
.venv\Scripts\python -m kayra.run simple         # refresh only the home-screen curve fit, no model calls
.venv\Scripts\python tools\dev_server.py        # panel on http://localhost:8201
```

No keys needed for the fitter or the panel. Without a model configured, the hypothesis loop uses hand-written stand-in programs from `kayra/standin/` and labels them so everywhere.

To use a model, copy `.env.example` to `.env` and fill the `KAYRA_LLM_*` lines.

## How it works

The building per room, per hour:

```
T[t+1] = T + a*(T_out - T) + h*max(S - T, 0) + gains(hour)
```

`S` is the supply temperature the controller stack asks for. Käyrä never sees it. It sees outdoor in and room out, so the controller has to be identified through the building.

Every hypothesis about the controller is a short program in a small structure language (`kayra/dsl.py`). For example a weather curve with summer cutoff:

```
where(ema(T_out, tau) < cutoff, level + slope * T_out, OFF)
```

The language has no numeric literals. Every number is a typed parameter and the fitter finds the value. This is how "no number came from the language model" still holds when the model writes code.

- `kayra/search.py` fits each program: cross-entropy search over thousands of parameter sets, all simulated together as tensors over 72-hour windows of history, scored on held-out weeks. Building loss comes from the summer, when the heating is off.
- `kayra/structures/` is the seed catalogue S0-S7: free-floating, linear curve, clamped curve, curve with cutoff, PI on room, on/off thermostat, curve with room feedback, curve with night setback.
- `kayra/hypothesize.py` is the loop. The model reads what the best program fails to explain and proposes new programs. They go through the same validator and fitter as the catalogue. Everything lands in a lab notebook.
- `kayra/baseline_search.py` is the non-LLM baseline: random grammar edits with the same operators and the same budget.
- `kayra/context.py` is the site-context arm. The model reads the operator notes (`config/site.json`) and the controller's menu labels (`config/menu_labels.md`, labels only, never values) and turns each into a complete control law for a named room or loop. Every one is fitted and scored against the best program found without that context. From labels like "Outdoor temperature delay", "Autumn drying", "Max limit" and "Min limit" it writes the controller's documented setpoint structure as a program. A fitter cannot read a menu.
- `kayra/writeup.py` has the model write the as-found specification from the computed evidence, with a short summary in Finnish for the technician on site. Every line goes through the guardrails.
- `tools/llm_check.py` scores the endpoint's models on these tasks, graded by code, and recommends one for programs and one for prose.
- `kayra/explain.py` lets the model write the diagnosis and pick the next observation. Every line is checked by `guardrails.py` (ported from Virta): a line with a number that is not in the evidence is dropped.
- `kayra/reference.py` reads the Ouman panel readings. They are reference data for grading, and optional spot anchors, never product input.
- `config/site.json` is optional operator knowledge: which rooms sit on which heating loop. Rooms on one loop share one controller program in the fit, each room keeps its own building parameters. Here L1 is the downstairs radiators (fireplace room, TV room) and L2 the upstairs floor heating (kitchen). The TV room radiator has an analog thermostatic valve, almost closed, so room feedback there is a real mechanism to look for.
- `kayra/evaluate.py` is the only file that opens `data/manual/ouman_curve_setting.csv`, the configured curve. The fit is blind to it. The coding agent never saw its contents and did not run this script.

## Panel

`web/` is plain HTML, CSS and JS, no build step. The home screen is one heating loop at a time: room temperatures against outdoor (daily history and the replayed hour), the fitted weather curve with summer stop, and sliders to move the curve. The lines show where each room would settle under your curve, from the fitted building model, and the heat input change over the record. Fit puts it back. Advanced keys: In the box, Notebook, Spot readings, Model, Benchmark, Alert, Replacement (pending), Document. Status line shows data REPLAY, AMD status, model status, age of the last room reading and HA-ONLY or ANCHORED mode.

Hosting on Vercel: `python tools/build_web.py` copies the artifacts into `web/artifacts/`, then deploy the repo. `vercel.json` serves `web/` and `api/state.py`.

## Layout

```
kayra/       fitter, structure language, loop, explanations, evaluation
kayra/structures/   seed catalogue, one program per file
kayra/standin/      hand-written stand-in hypotheses (offline mode only)
kayra/prompts/      the frozen hypothesis prompt
tools/       fetch_fmi.py  pull_ha.py  dev_server.py  build_web.py  check_secrets.py  ident_check.py
api/         state.py (Vercel function)
web/         the panel
data/raw/    Home Assistant export 2026-10-03 (checksummed), FMI pulls
data/manual/ Ouman panel readings (reference), sealed configured curve
artifacts/   everything the panel shows, plus llm_archive.jsonl with every model call
docs/        demo script, slides outline, AMD swap, submission text drafts
```

## Limits

- Structure discovery is tested on synthetic cases built from the real building. Result on 2026-10-17: every arm (catalogue, grammar search, language model) found 1 of 6 by the pre-fixed checklist, 0 of 6 read strictly. On the real stack it is one data point.
- From Home Assistant alone the curve slope is identifiable and the level only loosely. Spot readings pin the level. Both modes are labelled.
- Controllers with an integrator (PI) are hard to identify from windows: the integrator state is not visible in room data that sits near setpoint. The synthetic benchmark shows this.
- Model prose: numbers are checked against the evidence, reasoning is not. The panel shows the computed diagnosis first and the model wording under it, labelled.
- Room coupling, the replacement controller and the live pusher from the house are not in this version.
- Winter is unobserved. No extrapolation below the observed outdoor range.
- Outdoor comes from FMI Utti, several km away. The controller's own sensor read 0.2 to 1.1 °C warmer than the Utti hour ending nearest each reading, six checks. An earlier hand comparison with a different hour choice got up to 2.1. The alignment is an assumption.
- An earlier automated data inventory (another agent, 2026-10-03) was fabricated. Every figure here was recomputed from files on disk.

Data: FMI open data, CC BY 4.0. Code: MIT.
