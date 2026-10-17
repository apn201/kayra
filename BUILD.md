# KÄYRÄ - build brief for Claude Code

Revised 2026-10-12, the morning of kick-off. This file is the spec. `kayra.md` and `kayra-handover.md` are history; where they disagree with this file, this file wins.

## Read this first

- Prior work is allowed. The Rule Book has no "must be started during the event" clause, only "original and MIT-compliant" and no plagiarism. Reusing Juha's own Virta code is fine. Keep provenance headers and an honest commit history - no backdating, no squashing to hide dates.
- Juha's dev tools live under his user directory on D:, not in default locations. If a tool is "missing", the path is wrong. Ask for the absolute path. Do not reinstall.
- Registration (lablab, AMD AI Developer Program, Discord) is Juha's to do by hand. Do not suggest community steps.
- Juha will not answer more questions about the hot-water side of the substation. Do not ask.

## The concept

Käyrä works out what an undocumented controller is doing - a weather curve, a PID loop, an on/off thermostat or something nobody wrote down - from the process data a site already logs. No vendor, no manual, no bump test, no downtime.

Pattern matching fits the model you give it. Käyrä's language model writes the models. It reads what the current best explanation fails to explain, proposes new control mechanisms as small programs, and the GPU fits and scores every one against months of history. The language model brings what a controls engineer brings - knowledge of what controllers actually do: weather compensation, outdoor filtering, night setback, valve saturation, local room feedback. The numerical layer decides which hypothesis survives. Live data keeps both going: parameters update every hour, and a residual that turns structured triggers a new round of hypotheses.

A real process rarely has one controller. It has a stack of them, added over decades, some fighting each other. Käyrä does not try to name every one - often that is impossible from process data, two loops fighting look like one strange loop. It identifies the process, the relationships between its variables, and the single equivalent control law that reproduces what the whole stack does. Then it picks one documented controller that could replace all of them - an off-the-shelf one where it fits, custom code only where nothing cheaper does - and tests it in simulation against the real history.

The output is the document the plant never had: an as-found specification of what the controllers jointly do, a map of the process, a replacement specification, and a lab notebook of every hypothesis tried and why it lived or died.

Test bench: a real district-heating substation controller (Ouman EH-203, two heating loops) on a real building in Kouvola, with real data. The building is a stand-in for a slow, multi-variable, disturbance-heavy process with an unknown controller - same problem shape as a process loop. It is not a house project dressed as a factory, and the copy never says "industrial process" where a judge could ask "which one?" and hear "my house".

The product's data source is Home Assistant only: room temperature and humidity sensors, plus outdoor temperature from a weather service (FMI). The Ouman panel readings and the configured curve are reference data for evaluation, not product input - with one optional exception, spot readings, below.

## Submission facts

From the event page and Rule Book, read 2026-10-03. Finnish time.

| | |
|---|---|
| Kick-off | Mon 12 Oct 2026, 18:00 |
| End of submissions | Sun 18 Oct 2026, 17:00 per the schedule; the enrolment page says "Online Build: 12-17 October". Plan to submit Sat 17 Oct. |
| Late manual submission | 6 hours after, only with a valid reason and prior approval |
| Demo platform | "Use Streamlit, Replit, or Vercel" - Vercel |
| Application URL | required, for interactive evaluation |
| Repo | public GitHub, MIT |
| Video | MP4 |
| Slides | PDF |
| Cover image | PNG or JPG, 16:9 |
| Text | title, short and long description (character limits apply), technology and category tags |
| Judging | application of technology, presentation, business value, originality |

"Application of technology" is defined as "how effectively the chosen model(s) are integrated into the solution". The language model must have a real job, and one that plain pattern matching could not do. See The language model's job.

## What the track brief asks for, and the answer

Track 1, Intelligent Industry: "Help factories spot problems earlier and operate better." It wants realistic industrial data, a useful alert, explanation, recommendation or action, a named user, a measurable improvement, and warns against "only a dashboard or presentation".

- User: the maintenance or automation engineer who inherited a control loop nobody documented.
- Problem: nobody dares retune it, nobody can tell a process upset from a control fault, and nobody can migrate it to a new system, because nobody knows what the controllers are supposed to do together. The usual fix is a bump test - step the process, watch the response - which costs production time and nerve. Käyrä does it passively from logged data.
- Not a dashboard: the output is a document - as-found specification, process map, replacement specification - plus a ranked diagnosis of what is in the box.
- Alert: drift from the identified behaviour, separated from ordinary disturbances.
- Recommendation: the cheapest controller that could replace the undocumented stack - off the shelf where it fits - with predicted effect tested in simulation; and the cheapest next observation that would resolve what the tool still does not know.
- Measurable: see Evaluation. All numbers come from data. No invented downtime or euro figures.
- Data: a live commercial controller on a real heating circuit. Say exactly what it is.

## Data

All raw files under `data/raw/`, read-only. Derived files under `data/derived/`, reproducible from a script.

### Home Assistant - the product's input

Existing export: `data/raw/ha_exports_20261003/`, verified 2026-10-03 by line count, first and last rows and gap scan, `SHA256SUMS.txt` alongside.

| Set | Rows each | Window (UTC) |
|---|---|---|
| Hourly long-term statistics `lts_hourly_*` | 4144 | 2026-04-13 19:00 to 2026-10-03 10:00 |
| 5-minute short-term statistics `sts_5min_*` | 4210 | 2026-09-19 01:15 to 2026-10-03 16:00 |
| Met.no template states | 312 | 2026-09-19 to 2026-10-03 |

Columns `timestamp_utc,mean,min,max`, timestamps label the start of the interval.

Use these seven:

| Entity | Room | Kind |
|---|---|---|
| `sensor.keittio_lampotila` | kitchen | temperature |
| `sensor.keittio_lampotila_3` | kitchen | temperature |
| `sensor.keittio_kosteus_2` | kitchen | humidity |
| `sensor.takkahuone_lampotila_2` | fireplace room | temperature |
| `sensor.takkahuone_kosteus_2` | fireplace room | humidity |
| `sensor.tv_huone_lampotila` | TV room | temperature |
| `sensor.tv_huone_kosteus` | TV room | humidity |

The rooms, per Juha:

| Room | Floor | Heat source |
|---|---|---|
| Kitchen | upstairs | floor heating (L2), plus warm air rising from downstairs through the open space and balcony |
| Fireplace room | downstairs | radiators (L1), plus the fireplace |
| TV room | downstairs | none - a small, isolated room with no radiator. Heated through walls and door from its neighbours, and by people |

The TV room is nearly a gift: a room with no heating of its own is a natural control for the coupling terms. Nearly, because it is small. On evenings with the TV on and two people in, sometimes with the door shut, it warms from the people, not from outdoor or the other rooms (Juha). In the large rooms one person's heat disappears; in this one it shows. So:
- Occupancy is a named disturbance for the TV room. Signature: evening temperature rise with humidity rising with it (people exhale water), no matching rise next door. If Home Assistant has a TV entity - a media player or a plug with power - use it as the occupancy signal; check the entity list in M1. Otherwise humidity carries it.
- A shut door changes the coupling and is not logged. Treat occupied evening hours as their own regime, or mask them.
- Fit the coupling terms on unoccupied hours - nights and daytime. That is where the TV room is a clean control.

Drop `sensor.indoor_max_temp` (it is `keittio_lampotila_3` under another name, equal in 99.6% of hours) and `sensor.temperature_average` (17-day hole, probably averaged two sensors that later died).

The two kitchen sensors are two devices: correlation 0.99, `_3` reads 1.46 °C warmer on average. One is on the ceiling, the other on the wall above a window (Juha). Which entity is which is not recorded: work it out from the data in M1 and state the evidence - the ceiling sensor should read warmer and smoother (stratification); the window sensor should show larger short swings, cold-glass dips on cold nights and sun spikes. The kitchen is upstairs on floor heating, so there is no radiator under that window. The ceiling sensor also catches warm air rising from the downstairs radiators. Two sensors at two heights, never averaged.

A portable Zigbee climate sensor joined on 2026-10-12: `sensor.zigbee_climate_sensor_*`, temperature and humidity (Juha; read the exact entity ids from the entity list in M1). Its history starts that day and nobody has said which room it is in. It can be carried around. Rules:
- Discover it from the entity list. Do not hardcode it. Room labels live in a small `sensors.yaml`; Juha fills in a room if he wants one.
- Unlabelled or just moved, it is an unplaced room: shown on the Process screen, left out of the coupling fit until it has a label or a stable segment.
- A move shows up as a step in its level and a break in its pattern against the neighbours. Detect it, cut the series there, and treat each stretch as its own virtual room. Never stitch two locations into one series.
- Zigbee battery sensors report on change, so spacing is irregular. Hold the last value and carry its age, as `align_phases` does in Virta. No interpolation.
- Not a replacement for the seven. It adds nothing to the evaluation unless it sits still for days.
- It is a free demo, though: carry it into a new spot during the live run and the model has to place the new room - lag, coupling, which neighbour it follows - from a few hours of data. That is "live data improves the model" shown with no slide needed. Optional, not on the critical path.

The product reads Home Assistant directly. No flat-file exports, no agent in between. The 2026-10-03 export stays as a frozen, checksummed snapshot: a test fixture, and the replay source for anyone without access to Juha's HA.

Two read paths, both read-only, both with a long-lived token from `.env`:
- `kayra/ha_client.py` - ported from `virta/ha_client.py`, plus `fetch_history` from `virta/history.py`. Standard-library REST: `/api/states/<id>` for live values, `/api/history/period` with `minimal_response` and `no_attributes` for recent history. Keep Virta's parsing discipline exactly: `unavailable`, `unknown` and empty states are skipped, never `float()`-ed; timestamps stay timezone-aware; history records state changes, so a gap means "value held", not "missing". This path only reaches back as far as the recorder keeps states. Drop Virta's `call_service`: Käyrä never writes to HA.
- `kayra/ha_stats.py` - new. HA's REST API does not expose long-term statistics; the websocket API does: authenticate, then `recorder/statistics_during_period` with `period: hour` (and `5minute` for the short-term table), `types: [mean, min, max]`. This is how the product gets months of hourly history straight from HA. One small dependency, `websocket-client`, pure Python, fine on the Pi.

Virta's rule was "the runtime reads; bulk exports go through OpenClaw". Käyrä drops the second half. A plant tool that needs someone to export CSVs by hand is not a product.

The snapshot stops on 2026-10-03, before the heating season got going and before any reference reading. First job at kick-off: read 2026-10-03 to now through both paths. Long-term hourly statistics are permanent. 5-minute data and raw states age out after the recorder's keep window - the last export held 14 days - so the 5-minute data around the reference readings (Oct 5-12) has to be read this week or it is gone. Cache each read under `data/raw/ha_<date>/` with checksums; never edit an old one.

Met.no states are a cross-check only, never a model input.

### Outdoor temperature - FMI

`tools/fetch_fmi.py` (standard library, no key, CC BY 4.0 - credit FMI in the report). Station: Kouvola Utti lentoasema, fmisid 101191, decided. Anjala (101194) stays as a sanity check only. 101189 returns no temperature.

`timestamp_utc` is shifted to the hour-start label to join the HA export; `fmi_timestamp_utc` keeps FMI's own hour-end stamp. That alignment is an assumption - verify it before trusting any lag under two hours. Eight missing hours at Utti, single or double gaps: interpolate and flag. Extend the fetcher with an incremental mode for the pusher.

Coverage 2026-04-13 to 2026-10-03: -1.6 to 28.8 °C, 818 hours below 10 °C, 15 below zero. Most of the window is summer with the heating off. That is useful, not wasted: see Identifiability.

### Reference data - the Ouman panel and the heat meter

Not product input. Juha read these by hand off the controller and the meter. They exist to grade the product.

`data/manual/ouman_readings.csv` - one row per panel reading. Columns: `timestamp_local, outdoor_controller_c, l1_supply_c, l1_setpoint_c, l2_supply_c, meter_mwh, time_known, note`. Nine rows so far; Juha keeps adding.

| Local time | Outdoor (controller) | L1 supply | L2 supply | Meter MWh |
|---|---|---|---|---|
| 2026-10-05, time unknown | 11 | 31 | 25 | - |
| 2026-10-05, time unknown | 12 | 29 | - | - |
| 2026-10-06 approx, time unknown | 9 | 33 (setpoint 32) | 26 | 63.693 |
| 2026-10-07 09:50 | 9 | 33 | 26 | 63.713 |
| 2026-10-08 09:33 | 4 | 37 | 28 | 63.766 |
| 2026-10-10 14:35 | 5 | 36 | 27 | 63.897 |
| 2026-10-11 13:20 | 6 | 35 | 28 | 63.977 |
| 2026-10-12 09:24 | 5 | 36 | 27 | 64.041 |
| 2026-10-12 12:51 | 6 | 35 | 27 | 64.051 |

Times are when the photo was sent, within minutes of the reading. Rows without a known time stay out of anything time-aligned. Display values are integers: treat each as plus or minus 0.5 °C.

`data/manual/ouman_curve_setting.csv` - the configured curve as the controller's own menu shows it. This is the answer key. The fitting code must never load it. Only `evaluate.py` reads it. Keep that visible in the code - a judge should be able to see the fit was blind. Juha fills this file himself from his photo; it is currently an empty template.

What the panel shows about the controller, from Juha's reading of its screens:
- The L1 setpoint is curve value plus an autumn-drying term plus an outdoor-delay term, clamped by max and min limits. Every correction term read zero on every visit, so every reading so far is a clean read of the curve.
- Two heating loops, both controlled by the Ouman, per Juha: upstairs floor heating and downstairs radiators. No thermostatic valves, no room thermostats - heating is 100% the Ouman. Rooms share air through a large open space and a balcony.
- Which loop is L1 and which L2 is inferred from temperature: L2 runs 25-28 °C, floor-heating territory, so L2 is the floor heating and L1 the radiators.
- How L2 relates to L1 is an open question, and a useful one. Juha's first belief: same curve as L1, with a flat reduction. After seeing the numbers he agreed: L1 and L2 have their own curves (2026-10-12, stated, not yet from the curve screen). The data agree. The gap L1 - L2 widens as it gets colder - 6 °C at 11 °C outdoor, 8-9 °C at 4-6 °C outdoor, about 0.43 °C more per degree colder (r = -0.90, eight paired readings). A constant offset fits at rms 1.09 °C against an expected 0.41 °C from integer display rounding alone (chi-square 57 on 7 degrees of freedom); L2 as a scaled-down L1, rising about half as fast, fits at rms 0.43. So the equivalent law is two curves on one outdoor input, which room data alone cannot separate from one curve per room group (S8). The L2 curve screen photo, when Juha takes it, is the answer key for this.
- Either way, this goes in the lab notebook as the first entry: an operator's belief about the controller, tested against the controller's own data. That is the product's whole point in miniature, and it happened by accident. Keep it.
- Domestic hot water is handled outside the Ouman. Not investigated further, by Juha's decision.
- Plumbing by sight: indirect substation. The primary side runs near 95-100 °C, the heat exchanger sits between, the Ouman controls the building side. One line in the as-found document.
- The hot-water thermometer is stuck. Not data.

Controller outdoor sensor vs FMI Utti, for the six readings with a known time:

| UTC | Controller | Utti, nearest complete hour | Offset |
|---|---|---|---|
| 2026-10-07 06:50 | 9 | 8.8 | +0.2 |
| 2026-10-08 06:33 | 4 | 1.9 | +2.1 |
| 2026-10-10 11:35 | 5 | 4.1 | +0.9 |
| 2026-10-11 10:20 | 6 | 4.9 | +1.1 |
| 2026-10-12 06:24 | 5 | 4.6 | +0.4 |
| 2026-10-12 09:51 | 6 | 5.8 (10-minute obs at 09:50) | +0.2 |

The controller reads warmer every time, +0.2 to +2.1 °C, six readings, widest after a fast overnight swing at the open airfield. Report the range and the likely cause. Do not turn six integer readings into a correction factor. Because the product uses FMI, the curve it identifies is the curve as seen from Utti; the evaluation has to carry this offset as uncertainty, not as a correction.

Heat meter (Kamstrup Multical 603, whole substation, includes hot water) between timed readings, against mean Utti temperature over the same interval:

| Interval (UTC) | Hours | kWh | Mean kW | Mean Utti °C |
|---|---|---|---|---|
| 10-07 06:50 to 10-08 06:33 | 23.7 | 53 | 2.23 | 7.3 |
| 10-08 06:33 to 10-10 11:35 | 53.0 | 131 | 2.47 | 8.3 |
| 10-10 11:35 to 10-11 10:20 | 22.8 | 80 | 3.52 | 3.9 |
| 10-11 10:20 to 10-12 06:24 | 20.1 | 64 | 3.19 | 5.1 |
| 10-12 06:24 to 10-12 09:51 | 3.5 | 10 | 2.9 | 5.2 |

Four full intervals, correlation -0.94, about 0.28 kW more per degree colder; the fifth is 3.5 hours and 10 kWh at 1 kWh resolution, so plus or minus 10 percent, and stays out of the fit. Hot water is in there and the meter tracks outdoor anyway. It is the independent check on the model's heat input: not in Home Assistant, so not product input, but a grader. Recompute as readings arrive; do not quote the slope as a building property off four points.

Privacy: Juha's photos include the installer's contact label and the meter's serial number. Neither goes in the repo, the video or the slides. Nor does the curve-setting photo.

## Identifiability - what Home Assistant alone can and cannot tell

This section decides what the product is allowed to claim. Get it right before writing the fit.

The building, per room, per hour:

```
T_in[t+1] = T_in + a_loss*(T_out_lagged - T_in) + on * h * (T_supply(T_out) - T_in) + gains(hour) + noise
```

The product never sees `T_supply`. It sees outdoor temperature in and room temperature out, with the building's thermal dynamics between them. So the controller has to be identified through the building. That is harder than fitting a curve, and the brief has to say so.

What makes it possible: the summer. With the heating off, the building floats free, and `a_loss` and the gain profile are identified with no controller in the way. Carry them into the heating season and what is left of the room temperature's behaviour belongs to the heating. In principle that recovers the curve's slope and level both: the heating coefficient shows up in how strongly room temperature pulls back toward the supply, and the slope shows up in how the heating responds to outdoor.

What makes it weak: room temperature only moves a degree or two, the sensors quantise at 0.1 °C, and gains differ between seasons (sun, ventilation, windows open in summer). A quick synthetic check (`tools/ident_check.py`, naive equation-error regression, 40 runs, simulated building with an arbitrary test curve) recovered the slope at -1.06 plus or minus 0.10 against a true -1.10, and the supply level at 5 °C outdoor at 36.2 plus or minus 2.5 against a true 40.5 - biased low by several degrees and wide. The test curve is deliberately unrelated to the real controller. The real fit will do better with simulation error over windows instead of one-step regression, but the shape of the result will hold.

So the product claims, in this order of confidence:
1. Structure: what kind of controller it is (see Structures).
2. Regime and cutoff: when the heating is on, and the outdoor threshold where it stops.
3. Lag and building time constants, per room.
4. Curve slope, with a band.
5. Curve level, with a wide band.

Spot readings, optional: a technician can always read a panel a few times. The product accepts manual readings of the controller's outputs. Each one pins a level and tightens a band. This is not cheating - it is the realistic industrial case. The deck chart: band width and error against the true curve at 0, 1, 2, 3... spot readings - on the synthetic cases, where the truth is known exactly, and on the real house for L1 against the sealed configured curve. Readings used as anchors are excluded from scoring that run.

Two loops on one input. This house runs two weather curves from the same outdoor sensor into rooms that share air. Both are functions of the same input, so their sum into any room is again one curve in outdoor temperature. From room data alone the two loops are not separable: Home Assistant sees one equivalent curve per room, and that is what HA-only mode reports. With spot readings of both loops, anchored mode fits each room's share of each loop - which loop heats which room, and how much. That is the relationship map, and the honest version of "replace many controllers with one". Say it plainly.

Default mode is Home Assistant only. The anchored mode is labelled as such everywhere it appears.

## Structures - what might be in the box

The point is not to assume a weather curve and fit it. The identifier competes candidate structures and lets the data choose.

### The structure language

Every controller hypothesis is a short program in a restricted expression language, `kayra/dsl.py`. The hand-written catalogue below and everything the language model proposes are written in the same language and go through the same evaluator. One code path. If the model loop slips, nothing else breaks.

- Parsed with Python's `ast`, whitelist only: arithmetic, comparisons, `min`, `max`, `clip`, `where`, and a fixed set of operators - `lag(x, p)`, `ema(x, p)`, `hysteresis(x, lo, hi)`, `integral(e, p)` with anti-windup, `hour_of_day()`, `weekday()`.
- Signals: outdoor temperature, each room's temperature and humidity, the room mean, the regime flag from the previous hour. Nothing else exists.
- No numeric literals. Every number is a parameter, declared with a type - `temp_c`, `slope`, `hours`, `gain`, `fraction`. Bounds come from a fixed table per type in the code, never from the program. The table is generic - wide, textbook ranges for building heating - and must not be narrowed using the reference readings in this brief. Those readings are for anchored mode and evaluation only. This is how the no-invented-numbers rule survives the model writing code: the model writes shape, the GPU finds every value.
- Complexity cap: maximum nodes and parameters per program.
- Compiled to batched torch ops, so a program and thousands of parameter sets run as one tensor job.
- Output of a program: heating effort per hour - one shared effort, optionally with a per-room modifier - which drives the building model. A program describes what all the controllers do together, as seen from the process. It is not required to separate them.

### Seed catalogue

Hand-written programs in `kayra/structures/`, one file each:

| Id | Structure | What gives it away |
|---|---|---|
| S0 | No control (free-floating) | room tracks outdoor fully |
| S1 | Weather curve, linear | room keeps a steady-state dependence on outdoor; disturbances not rejected |
| S2 | Weather curve, piecewise with min/max clamps | as S1, bends at the ends |
| S3 | S1 or S2 plus summer cutoff on smoothed outdoor | heating stops above a threshold |
| S4 | PI control on room temperature | room holds setpoint regardless of outdoor; integral action removes offsets; disturbances rejected over hours |
| S5 | On/off thermostat with hysteresis | sawtooth in the 5-minute data, cycle period depends on load |
| S6 | Curve plus local proportional room feedback | partial disturbance rejection - what thermostatic radiator valves on top of a weather curve look like; a cascade |
| S7 | Curve plus night setback | daily step in heating, not explained by gains |
| S8 | Two curves on the same outdoor input, per-room shares | indistinguishable from one equivalent curve on room data alone; separable only with spot readings of both loops |

On this house, Juha states there are no thermostatic valves and no room feedback. So S4 and S6 winning on the real data would be false positives - a free honesty check. Report it either way.

Each program plus its parameters is one candidate. Score every candidate by simulation error over 48-hour windows started from the measured state, on held-out weeks, with a complexity penalty (BIC). Report the ranked list with scores, not just the winner. A structure that wins by a hair is a tie, and the document says so.

The deterministic layer also produces, for the best program, a residual report - what it fails to explain: periodicities, correlation with each signal, by room, by regime, by outdoor band, around disturbance events - and for the top two, a discrimination map: the conditions where their predictions differ most. These are the language model's inputs.

Disturbances, as named rules in the style of `virta/scoring.py`, not fitted weights:
- temperature up, humidity up: cooking or shower. Disturbance.
- temperature down, humidity down: window open. Disturbance.
- fireplace room up sharply, humidity down: fire. Mask, do not smooth.
- TV room up in the evening, humidity up, no rise next door: people. Mask for the coupling fit, keep for the occupancy profile.
- persistent residual across all rooms with nothing in humidity: the heating is not doing what the identified structure says. Drift. That is the alert.

## Many controllers - the process map, the equivalent law, the replacement

This house runs a small stack: one Ouman with two weather curves, L1 to the downstairs radiators and L2 to the upstairs floor heating, both from the same outdoor sensor, into rooms that share air through an open space and a balcony. Hot water on its own, outside the Ouman. Home Assistant sees none of it, only rooms. Good - that is what a plant historian looks like too. And it is a genuine case of two controllers that cannot be told apart from the process side: the tool has to say so, report the equivalent, and use spot readings to split it.

### Process map - `kayra/process.py`

The building model gains coupling between rooms: `k_ij * (T_j - T_i)` for each pair, kept only where BIC supports it. The fitted model is then read out as a map: for each room, which inputs move it (outdoor, heating effort, neighbouring rooms, humidity-flagged events), with gain, lag and band, and which links the data could not support. Expect strong coupling here: open space and a balcony. In anchored mode the map also carries each room's share of L1 and L2.

Expectations, written down before any fit and committed, so the map can be graded rather than admired:
- Kitchen (upstairs): mostly L2, plus a coupling link from the downstairs rooms.
- Fireplace room (downstairs): mostly L1, plus fireplace events.
- TV room (downstairs, no radiator): direct heating share close to zero; everything through coupling, plus an evening occupancy gain.
If the map disagrees, the report says where and by how much. A TV room with a large direct heating share means the model is wrong, not the house. Shown as a screen and a section of the document. The language model writes the explanation; the numbers are the fit's.

### Equivalent law

The winning program is, by construction, the single control law that reproduces what the whole stack does as seen from the rooms. Where an individual controller does leave a distinct signature - a sawtooth in one room's 5-minute data, disturbance rejection in one room and not the others - the notebook records it as a finding. Attributing behaviour to individual controllers is a bonus, never a requirement, and never claimed beyond what the residuals show.

### Replacement - `kayra/replace.py`

One controller that could replace the stack. Juha's rule: a ready-to-run commercial controller first, a custom PLC program only when nothing cheaper fits.

Tiers, cheapest first:
- Tier 0 - retune what is installed: the identified controller class with new settings. A technician's hour.
- Tier 1 - an off-the-shelf controller class from the template library: settings only, possibly plus one sensor (a room sensor for room compensation, say).
- Tier 2 - standard PLC or DDC function blocks: PID, curve block, scheduler, limiter. Configuration, not code.
- Tier 3 - a custom program in the structure language, proposed by the language model, exported as IEC 61131-3 Structured Text. Only when tiers 0-2 fall short.

The template library, `kayra/templates/*.json`, is curated by hand, not by the model. Each template is the feature set of a controller class that is actually sold - for example "two-circuit weather-compensated district-heating controller: three-point curve per circuit, min and max limits, outdoor filter, optional room compensation, night setback, summer cutoff" - with the parameters it exposes and their ranges, compiled to a structure-language program. A template may list example products, but only with a link to the vendor's own documentation, checked by a human. The model chooses among templates and explains; it never invents a product or a feature. Templates are reviewed code, so their fixed values (curve breakpoints, say) are allowed; the no-literals rule is for model-written programs.

Selection, deterministic:
- Tune every candidate in closed-loop simulation on the identified model, driven by the real outdoor history and the real disturbance events, replayed.
- Objective, all from data: keep each room's temperature at least as tight around its as-found median as the existing stack did, with less heat input. No comfort numbers are invented.
- Robustness: score each tuned candidate across the top models from the posterior, not just the best one. Rank by worst case. A replacement that only works on one model is not a replacement.
- Pick the lowest tier whose worst case is within the noise band of the best candidate overall. Show the higher-tier runners-up and what they would buy.
- No prices are invented. The tier is the cost signal.

The language model's part: propose tier 3 programs when tiers 0-2 leave a structured residual, and write the replacement specification - which tier, which template, which settings, which extra sensor, predicted effect, worst case, and why the cheaper tiers were or were not enough.

Output: tier, template or program, settings with bands, predicted room temperatures and heat input against as-found, worst case across models; for tier 3, the Structured Text, marked as a sketch never run on a PLC.

It is not deployed. The controller stays a black box, there is no write access, and that is the point of the project. The report says so: validated in simulation on the identified model, not on the building.

## Live learning

History does the bulk of the learning. Live data keeps it going and makes it watchable.

The candidate grid from the batch fit is also the prior for live learning. Every candidate carries a log-weight. Each completed hour, every candidate predicts the past 24 hours from the measured state 24 hours ago; the error updates its weight (Gaussian likelihood, noise level from the batch fit). Use a forgetting factor so the posterior can still move. Structure probabilities are the summed weights per structure.

On the panel: the curve band narrows and the structure probabilities shift as hours arrive. That is the live part of the demo, and it is real.

Structure keeps learning too. When the leading program's live residual turns structured - a new periodicity, a dependence on a signal, a break at the first frost - the pusher flags it, and the next batch run starts a new hypothesis round with the new data in the residual report. Accepted programs join the live candidate set. That is the real meaning of "live data improves the model": parameters every hour, mechanism when the evidence demands it.

Where it runs: on the house side, in the pusher (numpy, CPU, a few thousand candidates is cheap). It posts the posterior summary to the hosted app. Batch refits and hypothesis rounds run on AMD. No GPU at request time.

## The AMD component

Two layers. The first is the one that scores.

GPU search. Every program - catalogue and proposed - times thousands of parameter sets times three rooms, each simulated over thousands of hourly steps, scored over held-out windows. Batch the candidates as tensors and step them forward together. PyTorch, device chosen at runtime: `cuda` (what ROCm presents as), else CPU. The same script runs locally on CPU with a coarse grid, so development never waits on the cloud. The three-arm benchmark multiplies this by hidden controllers times arms times rounds. That is the honest reason for the GPU: the language model can only propose as fast as the fitter can refute. Measure the wall time of one hypothesis round on CPU and on the GPU and put both numbers in the deck - measured, not estimated.

Benchmark: identical search, CPU vs AMD GPU, wall time and candidates per second, written to `artifacts/benchmark.json` with hardware, ROCm and PyTorch versions.

Language model: an open model that is good at code and structured output, served by vLLM on AMD Developer Cloud next to the fitter, called through the ported client. Both halves of the loop on the same AMD hardware.

The pip trap, from AMD's own challenge notes: installing almost anything that depends on torch lets pip replace the ROCm build with a CUDA build, and the error that follows does not mention torch. Install with `--no-deps`, and after every install check that `torch.__version__` still ends in `+rocm`. Reference image there: `rocm/pytorch:rocm10.0_ubuntu26.04_py3.14_pytorch_release_2.13.0`; evaluation hardware mentioned is the Instinct MI300X.

AMD cloud runbook (sources: lablab event page, AMD AI Developer Program page, AMD's getting-started article, read 2026-10-12):
- Credit: the event page says free $100 of AMD credits for new members; the older AMD article describes 25 complimentary MI300X hours requested through a "Request Credit" form on the GPU Droplet page, approved hours expiring after 10 days. If the credit is not applied automatically, use that form. Hourly rate is not stated on those pages; the article's footnote implies about $2 per GPU-hour, so $100 is roughly 50 single-GPU hours. Verify on the droplet page before relying on it.
- Rule: a meaningful part of the workload must run on AMD hardware and be part of the product shown to judges. The batch fit, the benchmark and the vLLM endpoint do that.
- Droplet: one single MI300X (192 GB), not the 8-GPU node, which burns quota eight times faster. Quick Start image with the PyTorch or vLLM Docker package. SSH key added in the console. `ssh root@<ip>`, then `docker exec -it rocm bash`.
- Billing: powering off does NOT stop billing. Destroy the droplet when idle. Snapshots are billed separately. If the credit runs out, the GPU and its data are gone, so every run writes its results into `artifacts/` and gets pulled to the PC before the droplet is destroyed.
- Work pattern: develop on the PC, `rsync` the repo to the droplet, run, pull artifacts back, destroy. Claude Code does not need to live on the droplet.
- Short sessions: Mon evening is a 20-minute smoke test (ROCm sees the GPU, torch ends in +rocm, vLLM serves a small model, one fit runs), then destroy. Heavy use is Thu and Fri. Judges never need the live endpoint: the app falls back to the archived run, labelled ARCHIVE.
- The vLLM endpoint, if left public, needs `--api-key`; the key lives in an environment variable.
GPU source: AMD Developer Cloud with the $100 new-member credit. AMD also runs free notebook GPUs at notebooks.amd.com/hackathon (3 hours a day) for its Academy challenge - whether ACT III entrants can use it is unconfirmed, check at kick-off.

Credits: a GPU instance left running for judges will eat $100. Fits run as batch jobs and write artifacts. Every language-model call and its response is archived as jsonl. The hosted app replays from the archive when the endpoint is down and says so on the panel. Never fake a live call.

## The language model's job - and why it is not pattern matching

The standing rule, unchanged: the model proposes and explains, the deterministic layer computes and decides. No number in any output came from the language model. In prose, `guardrails.py` rejects any line containing a number not in the input. In code, the structure language has no numeric literals.

### The defence, in one paragraph

A fitter fits the model you give it. An anomaly detector flags what deviates from what it has seen. Neither can propose a mechanism it was not given. Symbolic regression and grammar search can generate structures, but blindly: the space explodes, and what comes out is an unreadable formula, not a mechanism with a name. Käyrä's language model generates hypotheses from domain knowledge - what controllers in buildings and plants actually do - aimed at the specific residual the current best explanation leaves behind. That step needs knowledge of control engineering, not statistics. It is tested head to head against both alternatives under the same compute budget (Evaluation, item 1). If it does not beat them, the report says so.

### The hypothesis loop - `kayra/hypothesize.py`

1. Seed: every catalogue program fitted on the GPU, plus any operator hypotheses (below).
2. Evidence packet to the model: the ranked programs with scores, the residual report, the discrimination map, the signal list, the operator list. Numbers in, as data.
3. The model returns up to 4 new programs in the structure language, each with: the residual feature it targets, the mechanism in words, and what result would refute it.
4. Validator: parse, whitelist, complexity cap, no literals, parameter types known. Rejects are logged with the reason and returned to the model once.
5. GPU fits each accepted program, scores it on held-out data.
6. Results back to the model. Repeat, up to 5 rounds, or stop when no program improves the held-out score by more than the noise band.
7. Everything goes into the lab notebook: hypothesis, mechanism, target residual, refutation test, score, verdict. That notebook is a screen and a section of the document.

Operator hypotheses. People who work next to a controller have beliefs about it - "L2 is just L1 minus a few degrees", "the night setback was switched off years ago". Those are hypotheses too. The product takes them in plain language, the language model translates each into a program in the structure language, and it is scored like any other, with the operator named as the source. A belief confirmed is documentation; a belief refuted is a finding. Juha's L2 belief is the first entry. His second: the TV room warms on evenings from the people in it, not from heating or neighbours - testable from the TV room's evening residual and humidity.

Realistic hypotheses the model should be able to reach without being told: curve on a filtered outdoor temperature; weekday night setback; output saturating at high load; local feedback in one room only; a cutoff with hysteresis; an autumn offset. None of these is special-cased in the code.

Keeping it honest:
- The prompt never names the hidden synthetic controllers or their mechanisms, and is frozen and committed before the benchmark runs. Changing it after seeing results means rerunning all arms.
- In the blind run on the real data, the model is never told the controller's make or model. It knows it is looking at a building heating system and nothing more.
- Every prompt and response is archived, so a judge can read exactly what the model was given.

### What the model also does

- Next observation. From the discrimination map: the single cheapest observation that would separate the surviving hypotheses - "one panel reading below 0 °C outdoor", "the 5-minute data across the next fireplace evening". For an industrial user, the difference between a targeted check and a bump test.
- The document, two parts. As-found: what the controllers jointly do - identified program and what it means in words, its rank and margin, curve as a table with bands (HA-only or anchored with k spot readings), limits, cutoff, lag, the process map, observed range and what is unobserved, sample sizes, how each figure was obtained, hypotheses ruled out. Replacement: the proposed single controller, its parameters with bands, predicted effect against as-found, worst case, and the plain statement that it is validated in simulation only. Plain operator language. Downloadable as PDF and plain text.
- Replacement proposals, as described above.
- Alerts. Residual, the rule that fired, the explanation, the numbers it came from.

### Site context - optional, second

Real plants have scraps: a menu tree in Finnish, a technician's note, a page of a manual. The model can read them and turn them into hypotheses - a menu entry for outdoor delay becomes a filtered-outdoor program to test. Pattern matching cannot read a menu. Run it as a separate arm: same loop, plus context text. The blind evaluation of the real controller never gets context. Context may contain menu labels only, never values from the curve screen. Cut this first within this section.

## Evaluation - the measurable

Every number in the deck comes from here, written to `artifacts/eval.json`.

1. Does the language model earn its place - the headline. Synthetic, built from the real building: fitted building model, real residuals as noise, driven by hidden controllers deliberately outside the seed catalogue - at least six, for example curve on 6-hour filtered outdoor, curve plus weekday setback, PI with output saturation, cutoff with hysteresis, and at least two stacks of several controllers at once (curve plus local feedback in one room plus an on/off thermostat in another; curve plus a PI trim that partly fights it). For stacks, "right" means the recovered program reproduces the stack's behaviour on held-out data, not that it names each member. `kayra/synth.py` writes them; the hypothesis loop never sees their source. Three arms, same budget of GPU fits per case:
   - A: seed catalogue only.
   - B: catalogue plus non-LLM program search in the same structure language (random or enumerated grammar expansion, best-first on held-out score). This is the baseline a sceptical judge will ask about. It must be a fair effort, not a straw man.
   - C: catalogue plus the language-model loop.
   Report per arm: held-out error against the true controller's behaviour, whether the recovered program is the right mechanism (judged by a written checklist per hidden controller, fixed before the runs), and fits used to get there. Also report a seed-catalogue confusion matrix (each catalogue controller hidden in turn, arm A) to show the basics work. Labelled synthetic, always. Whatever the numbers say goes in the deck - if C only wins on fits-to-answer or readability, that is the claim.
2. The real stack. Arms A and C on the real data; report which program each lands on. HA-only: each room's equivalent curve should sit between the two loops as read off the panel over the observed range - report where, and whether that fits the room's floor. Anchored: per-room shares of L1 and L2 against the written expectations (TV room direct share near zero), and the L1 curve against `ouman_curve_setting.csv` at k = 1, 2, 3... spot readings (anchors from `ouman_readings.csv`, scored on the rest). Carry the FMI-vs-controller offset as uncertainty. False-positive checks: S4 and S6 should lose.
3. Supply prediction, anchored mode. At each timed reading, predicted L1 and L2 supply against the panel.
4. Heat input against the meter. Model heat-input index per meter interval against metered kWh. Correlation, not a calibration.
5. Prediction error per room on held-out weeks.
6. Replacement, synthetic. On each hidden stack: tune a single replacement on the identified model, then run it on the true hidden plant. Room temperature deviation and heat input against the original stack, and which tier was picked. This is the only place the replacement meets a plant it was not fitted to - say so.
7. Replacement, real building, simulated. Predicted room temperatures and heat input against as-found, worst case across the posterior.
8. GPU vs CPU fit time, and wall time per hypothesis round.
9. Live: band width over time since kick-off.

## Ported from Apps\Virta

Each ported file carries a provenance header: source repo, source path, date copied, what changed. The Käyrä repo ships under MIT.

| Virta | Käyrä | Change |
|---|---|---|
| `virta/nebius_client.py` | `kayra/client.py` | Base URL and model ID to the AMD vLLM endpoint. Keep the empty-`content` / `reasoning_content` fallback. Add JSON-structured output for proposed programs. |
| `virta/cost_control.py` | `kayra/cost_control.py` | None. |
| `virta/guardrails.py` | `kayra/guardrails.py` | None. |
| `virta/scoring.py` | `kayra/rules.py` | Pattern only. New rules. |
| `virta/replay.py`, `virta/archive.py` | same names | None, or minimal. |
| `virta/ha_client.py`, `fetch_history` from `virta/history.py` | `kayra/ha_client.py` | Käyrä's entities. Drop `call_service` - read-only. |
| `pi/OPENCLAW_PI.md`, its systemd units | `house/INSTALL_PI.md`, `kayra-pusher.service` | One service, no console. Coexists with Virta on the same Pi. |

Not ported: `virta/console.py`. If the Pi screen stretch goal happens, reuse Virta's screen switching, not its screens. Port `tools/check_secrets.py` from Apps\Whyf and run it before every push.

## Interface

Plant-room aesthetics. Monochrome LCD, segment numerals, dense labelled fields, no decoration, nothing moves unless data moved. Plain HTML, CSS and JS. No framework, no build step. Charts drawn by hand on canvas or SVG in the same monochrome. It should look like an instrument, not copy one: no Ouman name or logo, no reproduction of their screen layouts. Third-party trademarks stay out of the UI and the video.

Screens, never-cut first:

0. Document. As-found and replacement specification.
1. In the box. Ranked programs with probabilities, the model's diagnosis, the next-observation recommendation. The centrepiece.
2. Notebook. Every hypothesis: who proposed it (catalogue, model or operator), the residual it targeted, the mechanism, the refutation test, the score, the verdict. This screen is the defence of the language model - make it readable.
3. Process. The process map: rooms, inputs, links with gain and lag, links the data did not support.
4. Replacement. As-found vs the proposed single controller in simulation over the real history: tier, template, settings, room temperatures, heat input, worst case, and what the cheaper tiers fell short on.
5. Curve. Identified curve with band; toggle HA-only vs k spot readings; after evaluation, the configured curve overlaid.
6. Live. Outdoor now, what the identified law says the heating should be doing, predicted vs measured per room, humidity, regime, residual, structure probabilities moving.
7. Model. Per room: parameters with bands, measured vs predicted, residual underneath.
8. Alert. Residual, rule, explanation, source numbers.

Status line on every screen: data LIVE or REPLAY, AMD endpoint ONLINE or ARCHIVE, age of last reading, mode HA-ONLY or ANCHORED k=n.

## Architecture

Vercel: a static panel plus a few serverless functions. No long-running server, so no SSE - the panel polls. There is no Vercel account yet: Juha creates a free Hobby account (GitHub login) at kick-off.

```
house (LAN, the Pi)                            Vercel (the live URL)
Home Assistant --poll--> pusher --POST /api/push--> function --> small store (Blob)
FMI open data  -------->  (live posterior)                          |
                                      browser panel --GET /api/state--+  every 30 s
                                      static: web/, artifacts/*.json, replay jsonl
AMD Developer Cloud
  batch fit + synthetic benchmark (PyTorch, ROCm) --> artifacts/*.json --> deployed static
  vLLM endpoint <-- hypothesis rounds, document, alerts (archived as jsonl)
```

- Vercel cannot reach Home Assistant, and HA is never exposed to the internet. The pusher runs on the Raspberry Pi that already runs Virta, on the same LAN as HA. Own directory, own venv, own systemd unit `kayra-pusher.service`, following Virta's `pi/OPENCLAW_PI.md`: `Restart=always`, `.env` at `chmod 600`, secrets never printed. It reads HA through `ha_client.py`, fetches FMI, updates the live posterior hourly at low priority (`nice`), and posts out with a push token.
- It must not disturb Virta's 15-second loop. The Pi is a Pi 3: numpy and `websocket-client` only, numpy from piwheels if the OS is 32-bit, as Virta's install notes describe for its own packages. No torch on the Pi. Measure the pusher's CPU and memory on the Pi and put the numbers in the install report. Claude Code writes `house/INSTALL_PI.md` in the same form as Virta's, so it can go to OpenClaw or be done by hand.
- Store: Vercel Blob if the free tier offers it at signup, else Upstash Redis from the Vercel Marketplace. Pick one at signup, note which in the README.
- `/api/state` returns the latest readings, the posterior summary and the model's prediction. Cheap arithmetic, no GPU.
- If the last push is older than 15 minutes, `/api/state` serves the next step of the recorded replay and marks it REPLAY. The page is never dead at 3 a.m.
- Local development needs none of this: `tools/dev_server.py` serves `web/` and answers `/api/state` from replay. Same panel, same JSON shape.
- Secrets in environment variables, never in the repo. `.env.example` carries no LAN addresses - Virta's does; don't copy that. A separate HA token for Käyrä, so either project's can be revoked alone.

## Layout

```
Kayra/
  BUILD.md  kayra.md  kayra-handover.md
  LICENSE (MIT)  README.md  .env.example
  data/raw/ha_exports_20261003/  data/raw/ha_<date>/  data/raw/fmi/  data/manual/  data/derived/
  tools/  fetch_fmi.py  ident_check.py  dev_server.py  check_secrets.py
  kayra/  client.py cost_control.py guardrails.py rules.py replay.py archive.py
          ha_client.py ha_stats.py load.py dsl.py structures/ search.py hypothesize.py
          baseline_search.py process.py replace.py templates/ st_export.py posterior.py
          synth.py evaluate.py document.py
  api/    state.py  push.py
  house/  pusher.py  kayra-pusher.service  INSTALL_PI.md
  web/    index.html  panel.css  panel.js
  artifacts/
  tests/
```

## Milestones

Kick-off Mon 12 Oct 18:00. Submit Sat 17 Oct.

The scope is big for six days solo. The order below puts the language-model defence on Thursday with a day of slack behind it, not on Saturday morning.

- Mon 12 evening. Juha: create the Vercel account; make a long-lived HA token for Käyrä. First direct HA read (`ha_client.py`, `ha_stats.py`) from Oct 3 to now, cached. FMI extended to now. `load.py` joins them into one hourly frame. AMD cloud: confirm ROCm and torch run, vLLM serves a model. Skeleton of `dsl.py`.
- M1, Tue 13 - the evaluator and the panel. `dsl.py` parses, validates and compiles to torch. Seed catalogue written as programs. Building model with summer free-float fit. Which kitchen entity is ceiling and which is window, from data. `dev_server.py` serves Live and Model screens on replay. Done when Juha runs one command on his PC and sees the panel moving, no cloud, no keys.
- M2, Wed 14 - identification. Batched search on CPU over the catalogue, regime and cutoff, three rooms with coupling, disturbance rules. `synth.py` hidden controllers and stacks. Arm A and arm B (`baseline_search.py`) on CPU, small budget. Evaluation against the sealed curve at k = 0..3.
- M3, Thu 15 - AMD and the language model. Search on ROCm, benchmark. `hypothesize.py` arm C on vLLM, guardrails, archived. Full three-arm run on the GPU. Notebook screen. If arm C is not working by Thursday night, ship A and B with the result stated and move on.
- M4, Fri 16 - process, replacement, live, hosted. Process map, `replace.py` with tiers 0-2 from the template library (best model first, robustness second, tier 3 after), document, pusher on the Pi with live posterior, Vercel, the URL, replay fallback proven by switching the pusher off.
- M5, Sat 17 - submission. README that runs, architecture diagram, demo video, slides, cover image, secrets check. Submit, not in the last hour.
- Stretch - a Pi screen. Kiosk browser on the same URL, for the video. The Pi already drives an HDMI screen for Virta; a switch like Virta's `screen.sh` is enough.

Cut order: Pi screen; site context; Structured Text export; live-triggered hypothesis rounds (batch rounds stay); replacement robustness across the posterior (best model stays); Alert screen; room coupling; per-room modifiers in programs. Never cut: real data, the structure language with no literals, the three-arm benchmark, the notebook, the blind-fit separation, the curve with its band, the no-invented-numbers rule.

## Open questions for Juha

1. Fill `ouman_curve_setting.csv` from the curve photo before M2, yourself. Do not paste the values into any chat with the coding agent, and keep the file out of its context: the blind claim depends on the agent never having seen them either.
2. Juha is checking the L2 curve screen. Photograph it the same way as L1, into the same sealed file. Juha says L1 and L2 have separate curves; the photo makes it a graded fact. Without it, L2 is graded on panel readings only.

Closed: start date; FMI station (Utti); hosting (Vercel, new free account); controller (Ouman EH-203, indirect district-heating substation); heating (two Ouman loops, upstairs floor heating and downstairs radiators, no thermostatic valves, hot water outside the Ouman); kitchen sensors (one ceiling, one wall above a window); rooms (kitchen upstairs; fireplace room and TV room downstairs; TV room has no radiator); data source (Home Assistant read directly, Virta's client); house box (the Virta Pi); replacement policy (commercial first, custom PLC last).

## Honest limits, for the report

- One real controller stack. Structure discovery and the language model's contribution are demonstrated on synthetic cases built from the real building; on the real stack it is one data point.
- The baseline program search in arm B is ours. A better non-LLM search may exist. Say what B does, so a reader can judge.
- The replacement controller is validated in simulation only - on the identified model, and on synthetic plants. It was never run on the building.
- The equivalent law describes what the controllers do together. It does not claim to have found each one.
- From Home Assistant alone the curve's slope is identifiable, its level only loosely. The report shows both modes and says which is which.
- Winter is unobserved. The curve is identified over the observed outdoor range only. No extrapolation below it.
- The summer loss coefficient is carried into the heating season; ventilation and open windows make that an approximation.
- Outdoor comes from a station several km away. The controller's own sensor reads 0.2 to 2.1 °C warmer in five checks.
- The two heating loops share one input and mix in open-plan rooms. From Home Assistant alone they are one equivalent curve; splitting them needs spot readings.
- The template library is small and curated by hand from vendor documentation. A better-fitting product may exist that is not in it.
- The heat meter totals the whole substation including hot water. It grades the model; it does not calibrate it.
- An earlier automated data inventory was fabricated by the agent that produced it. Every figure here was re-verified against files on disk or recomputed from source.
