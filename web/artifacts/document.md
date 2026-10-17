# As-found specification - heating controller stack

Generated 2026-10-17T15:26:21Z on `cpu` (torch 2.14.1+cpu). Language model: **STAND-IN ENDPOINT (OpenRouter, not AMD)**.

## Data

- Outdoor: FMI Kouvola Utti lentoasema (fmisid 101191), 4478 hours, 2026-04-13 to 2026-10-17, -1.6 to 28.8 °C, 8 hours interpolated.
- Kitchen (upstairs, floor heating): 4144 hourly means, 2026-04-13 to 2026-10-03 (`data/raw/ha_exports_20261003/lts_hourly_sensor_keittio_lampotila.csv`).
- Fireplace room (downstairs, radiators): 4144 hourly means, 2026-04-13 to 2026-10-03 (`data/raw/ha_exports_20261003/lts_hourly_sensor_takkahuone_lampotila_2.csv`).
- TV room (downstairs, radiator with thermostatic valve almost closed): 4144 hourly means, 2026-04-13 to 2026-10-03 (`data/raw/ha_exports_20261003/lts_hourly_sensor_tv_huone_lampotila.csv`).

Room data end where the last Home Assistant pull ends. Outdoor runs to the time of the run.

## What is in the box, per room

### Kitchen (upstairs, floor heating)

Scored on 48 cold windows (mean outdoor under 12 °C), 11 held out. Building loss time constant from the summer free-float: 151.8 h over 76 warm windows.

| Rank | Program | Source | Held-out RMSE °C | ΔBIC | P |
|---|---|---|---|---|---|
| 1 | S0 No control (free-floating) | catalogue | 0.71 | 0.0 | 0.79 |
| 2 | S1 Weather curve, linear | catalogue | 0.667 | 2.85 | 0.19 |
| 3 | M2.3  | model (STAND-IN ENDPOINT (OpenRouter, not AMD)) | 0.677 | 7.39 | 0.02 |
| 4 | S7 Weather curve plus night setback | catalogue | 0.666 | 13.27 | 0.00 |

Best: `OFF`.

### Fireplace room (downstairs, radiators)

Scored on 48 cold windows (mean outdoor under 12 °C), 11 held out. Building loss time constant from the summer free-float: 465.5 h over 76 warm windows.

| Rank | Program | Source | Held-out RMSE °C | ΔBIC | P |
|---|---|---|---|---|---|
| 1 | S0 No control (free-floating) | catalogue | 0.372 | 0.0 | 0.91 |
| 2 | S1 Weather curve, linear | catalogue | 0.36 | 4.76 | 0.08 |
| 3 | M1.3  | model (STAND-IN ENDPOINT (OpenRouter, not AMD)) | 0.367 | 13.02 | 0.00 |
| 4 | M1.1  | model (STAND-IN ENDPOINT (OpenRouter, not AMD)) | 0.368 | 13.16 | 0.00 |

Best: `OFF`.

### TV room (downstairs, radiator with thermostatic valve almost closed)

Scored on 48 cold windows (mean outdoor under 12 °C), 11 held out. Building loss time constant from the summer free-float: 558.1 h over 76 warm windows.

| Rank | Program | Source | Held-out RMSE °C | ΔBIC | P |
|---|---|---|---|---|---|
| 1 | S1 Weather curve, linear | catalogue | 0.236 | 0.0 | 0.92 |
| 2 | S0 No control (free-floating) | catalogue | 0.284 | 5.1 | 0.07 |
| 3 | S5 On/off thermostat with hysteresis | catalogue | 0.26 | 9.78 | 0.01 |
| 4 | S2 Weather curve with min/max clamps | catalogue | 0.252 | 11.1 | 0.00 |

Best: `level + slope * T_out`.

## Heating loops (operator site knowledge)

Rooms on one loop share one controller program; each room keeps its own building parameters.

### L1 Downstairs radiators: fireplace, tv

Operator: Radiators. Most have no thermostatic valve. The TV room radiator has an analog thermostatic valve, almost closed.

Best: S0 No control (free-floating) (`OFF`), held-out RMSE 0.336 °C, ΔBIC to runner-up 5.88.

| Room | Heating share | RMSE in loop °C | RMSE fitted alone °C |
|---|---|---|---|
| fireplace | 94% | 0.373 | 0.372 |
| tv | 6% | 0.295 | 0.236 |

## Equivalent curve, fireplace room

HA-only, then anchored with k panel readings of L1. Band = likelihood-weighted 5-95 % of the search population. Curve is identified over the observed outdoor range only.

- HA-ONLY: RMSE against the remaining 9 panel readings 9.52 °C, band width at 4 °C outdoor 3.79 °C.
- ANCHORED k=1: RMSE against the remaining 8 panel readings 5.35 °C, band width at 4 °C outdoor 1.44 °C.
- ANCHORED k=2: RMSE against the remaining 7 panel readings 3.48 °C, band width at 4 °C outdoor 1.06 °C.
- ANCHORED k=3: RMSE against the remaining 6 panel readings 1.94 °C, band width at 4 °C outdoor 0.71 °C.
- ANCHORED k=4: RMSE against the remaining 5 panel readings 1.97 °C, band width at 4 °C outdoor 0.59 °C.

| Outdoor °C | Supply p05 | p50 | p95 | heat on |
|---|---|---|---|---|
| -10 | 24.3 | 25.2 | 26.2 | 100% |
| -8 | 24.2 | 25.0 | 25.8 | 100% |
| -6 | 24.1 | 24.7 | 25.5 | 100% |
| -4 | 24.0 | 24.5 | 25.2 | 100% |
| -2 | 23.9 | 24.3 | 24.9 | 100% |
| 0 | 23.7 | 24.1 | 24.6 | 100% |
| 2 | 23.5 | 23.9 | 24.2 | 100% |
| 4 | 23.4 | 23.7 | 24.1 | 100% |
| 6 | 23.2 | 23.4 | 23.9 | 100% |
| 8 | 22.9 | 23.2 | 23.7 | 100% |
| 10 | 22.6 | 22.9 | 23.6 | 100% |
| 12 | 22.3 | 22.6 | 23.4 | 100% |
| 14 | 22.0 | 22.4 | 23.3 | 100% |
| 16 | 21.7 | 22.1 | 23.2 | 100% |
| 18 | 21.4 | 21.9 | 23.2 | 100% |
| 20 | 21.1 | 21.6 | 23.1 | 100% |

## Operator beliefs, tested

- **OP1** "L2 is the same curve as L1 with a flat reduction" - refuted: the gap widens as it gets colder; L2 runs its own curve.
  readings 8, gap_mean_c 7.75, gap_vs_outdoor_corr -0.9, gap_change_per_degree_colder_c 0.43, rms_constant_offset_c 1.09, rms_scaled_l1_c 0.43, l2_per_l1_degree 0.46, rms_expected_from_rounding_c 0.41, chi2_constant_offset 57.0, dof 7
- **OP2** "the TV room warms on evenings from the people in it" - not supported by the room data alone.
  evenings 172, mean_tv_rise_18_23_c 0.085, mean_neighbour_rise_18_23_c -0.319, evenings_tv_outpaces_neighbour 116, humidity_rise_on_those_evenings_pct -0.01, humidity_rise_other_evenings_pct 0.34

## Controller outdoor sensor vs FMI Utti

- 2026-10-07T06:50Z controller 9.0 °C, Utti 8.8 °C, offset +0.2
- 2026-10-08T06:33Z controller 4.0 °C, Utti 3.3 °C, offset +0.7
- 2026-10-10T11:35Z controller 5.0 °C, Utti 4.3 °C, offset +0.7
- 2026-10-11T10:20Z controller 6.0 °C, Utti 4.9 °C, offset +1.1
- 2026-10-12T06:24Z controller 5.0 °C, Utti 4.6 °C, offset +0.4
- 2026-10-12T09:51Z controller 6.0 °C, Utti 5.6 °C, offset +0.4

Carried as uncertainty, not as a correction.

## Alerts in the replay window

0 drift alerts, 9 disturbances explained by named rules.

## Synthetic benchmark (SYNTHETIC)

SYNTHETIC - real outdoor history and fitted real building, hidden test controllers.

| Case | Hidden | Arm A best | right? | Arm B best | right? | Arm C |
|---|---|---|---|---|---|---|
| H1 | curve on 12-hour filtered outdoor, summer cutoff | S3 (0.135) | yes | S3 (0.135) | yes | S3 yes |
| H2 | curve with weekday night setback | S4 (0.155) | no | B11 (0.15) | no | S4 no |
| H3 | PI on room temperature with output saturation | S1 (0.137) | no | S1 (0.137) | no | S1 no |
| H4 | curve with cutoff hysteresis on outdoor | S1 (0.135) | no | S1 (0.135) | no | S1 no |
| H5 | STACK: weather curve plus a PI trim on the room that partly fights it | S1 (0.127) | no | S1 (0.127) | no | S1 no |
| H6 | STACK: weather curve gated by an on/off room thermostat | S1 (0.167) | no | S1 (0.167) | no | S1 no |

## Compute

- cpu x1 threads: 163840 candidates in 55.36 s, 35797915 room-hours simulated per second.
- cpu x6 threads: 163840 candidates in 35.29 s, 56154327 room-hours simulated per second.
- AMD GPU: NOT MEASURED - no GPU on this machine. Run `python -m kayra.run bench` on the AMD Developer Cloud droplet to fill this in. No estimate is given.

## Not done in this version

- Replacement specification (tiers 0-3): not run. Screen shows PENDING.
- Room coupling in the process map: not fitted; rooms are identified independently.
- Live posterior from the house pusher: the panel replays recorded history.

## Limits

- Structure discovery is demonstrated on synthetic cases built from the real building; on the real stack it is one data point.
- From Home Assistant alone the curve's slope is identifiable, its level only loosely.
- Winter is unobserved; no extrapolation below the observed outdoor range.
- The two heating loops share one input; from room data they are one equivalent curve per room.
- Validated in simulation only. Nothing was written to the controller.
