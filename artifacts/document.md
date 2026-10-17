# As-found specification - heating controller stack

Generated 2026-10-17T18:26:48Z on `cpu` (torch 2.14.1+cpu). Language model: **ONLINE (AMD 11 calls, OpenRouter fallback, not AMD 21 calls)**.

## Data

- Outdoor: FMI Kouvola Utti lentoasema (fmisid 101191), 4486 hours, 2026-04-13 to 2026-10-17, -1.6 to 28.8 °C, 8 hours interpolated.
- Kitchen (upstairs, floor heating, L1 per operator): 4486 hourly means, 2026-04-13 to 2026-10-17 (`data/raw/ha_exports_20261003/lts_hourly_sensor_keittio_lampotila.csv, data/raw/ha_20261017/lts_hourly_sensor_keittio_lampotila.csv`).
- Fireplace room (downstairs, radiators, L2 per operator): 4486 hourly means, 2026-04-13 to 2026-10-17 (`data/raw/ha_exports_20261003/lts_hourly_sensor_takkahuone_lampotila_2.csv, data/raw/ha_20261017/lts_hourly_sensor_takkahuone_lampotila_2.csv`).
- TV room (downstairs, radiator with thermostatic valve almost closed, L2): 4486 hourly means, 2026-04-13 to 2026-10-17 (`data/raw/ha_exports_20261003/lts_hourly_sensor_tv_huone_lampotila.csv, data/raw/ha_20261017/lts_hourly_sensor_tv_huone_lampotila.csv`).

Room data end where the last Home Assistant pull ends. Outdoor runs to the time of the run.

## What is in the box, per room

### Kitchen (upstairs, floor heating, L1 per operator)

Scored on 62 cold windows (mean outdoor under 12 °C), 11 held out. Building loss time constant from the summer free-float: 151.8 h over 76 warm windows.

| Rank | Program | Source | Held-out RMSE °C | ΔBIC | P |
|---|---|---|---|---|---|
| 1 | S0 No control (free-floating) | catalogue | 0.706 | 0.0 | 0.98 |
| 2 | S1 Weather curve, linear | catalogue | 0.716 | 7.91 | 0.02 |
| 3 | S7 Weather curve plus night setback | catalogue | 0.673 | 14.3 | 0.00 |
| 4 | M2.2  | model (OpenRouter fallback, not AMD) | 0.712 | 14.51 | 0.00 |

Best: `OFF`.

### Fireplace room (downstairs, radiators, L2 per operator)

Scored on 62 cold windows (mean outdoor under 12 °C), 11 held out. Building loss time constant from the summer free-float: 465.5 h over 76 warm windows.

| Rank | Program | Source | Held-out RMSE °C | ΔBIC | P |
|---|---|---|---|---|---|
| 1 | S0 No control (free-floating) | catalogue | 0.381 | 0.0 | 0.76 |
| 2 | S1 Weather curve, linear | catalogue | 0.357 | 2.71 | 0.20 |
| 3 | M2.1  | model (OpenRouter fallback, not AMD) | 0.364 | 7.52 | 0.02 |
| 4 | S7 Weather curve plus night setback | catalogue | 0.331 | 8.25 | 0.01 |

Best: `OFF`.

### TV room (downstairs, radiator with thermostatic valve almost closed, L2)

Scored on 62 cold windows (mean outdoor under 12 °C), 11 held out. Building loss time constant from the summer free-float: 558.1 h over 76 warm windows.

| Rank | Program | Source | Held-out RMSE °C | ΔBIC | P |
|---|---|---|---|---|---|
| 1 | S4 PI control on room temperature | catalogue | 0.211 | 0.0 | 0.70 |
| 2 | S1 Weather curve, linear | catalogue | 0.232 | 2.67 | 0.18 |
| 3 | S5 On/off thermostat with hysteresis | catalogue | 0.224 | 3.83 | 0.10 |
| 4 | S2 Weather curve with min/max clamps | catalogue | 0.229 | 8.67 | 0.01 |

Best: `T_room + kp * (sp - T_room) + integral(sp - T_room, ti)`.

## Heating loops (operator site knowledge)

Rooms on one loop share one controller program; each room keeps its own building parameters.

### down Downstairs radiators: fireplace, tv

Operator: Radiators. Which panel loop (L1 or L2) is not known. Most radiators have no thermostatic valve. The TV room radiator has an analog thermostatic valve, almost closed.

Best: S0 No control (free-floating) (`OFF`), held-out RMSE 0.34 °C, ΔBIC to runner-up 9.69.

| Room | Heating share | RMSE in loop °C | RMSE fitted alone °C |
|---|---|---|---|
| fireplace | 89% | 0.383 | 0.381 |
| tv | 11% | 0.291 | 0.211 |

## Equivalent curve with spot readings (L1: kitchen)

HA-only, then anchored with k panel readings of L1. Band = likelihood-weighted 5-95 % of the search population. Curve is identified over the observed outdoor range only.

- HA-ONLY: RMSE against the remaining 9 panel readings 12.33 °C, band width at 4 °C outdoor 3.04 °C.
- ANCHORED k=1: RMSE against the remaining 8 panel readings 7.09 °C, band width at 4 °C outdoor 1.9 °C.
- ANCHORED k=2: RMSE against the remaining 7 panel readings 6.03 °C, band width at 4 °C outdoor 1.39 °C.
- ANCHORED k=3: RMSE against the remaining 6 panel readings 2.19 °C, band width at 4 °C outdoor 0.65 °C.
- ANCHORED k=4: RMSE against the remaining 5 panel readings 2.23 °C, band width at 4 °C outdoor 0.61 °C.

| Outdoor °C | Supply p05 | p50 | p95 | heat on |
|---|---|---|---|---|
| -10 | 32.5 | 35.0 | 37.4 | 100% |
| -8 | 31.7 | 34.1 | 36.3 | 100% |
| -6 | 31.0 | 33.1 | 35.2 | 100% |
| -4 | 30.3 | 32.3 | 34.2 | 100% |
| -2 | 29.5 | 31.4 | 33.1 | 100% |
| 0 | 28.8 | 30.5 | 32.0 | 100% |
| 2 | 28.1 | 29.6 | 31.1 | 100% |
| 4 | 27.3 | 28.6 | 30.1 | 100% |
| 6 | 26.4 | 27.7 | 29.1 | 100% |
| 8 | 25.4 | 26.8 | 28.1 | 100% |
| 10 | 24.4 | 25.8 | 27.4 | 100% |
| 12 | 23.3 | 25.0 | 26.6 | 100% |
| 14 | 22.3 | 24.0 | 25.8 | 100% |
| 16 | 21.3 | 22.9 | 24.9 | 100% |
| 18 | 20.2 | 22.2 | 24.1 | 100% |
| 20 | 19.1 | 21.3 | 23.3 | 100% |

## Operator beliefs, tested

- **OP1** "L2 is the same curve as L1 with a flat reduction" - refuted: the gap widens as it gets colder; L2 runs its own curve.
  readings 8, gap_mean_c 7.75, gap_vs_outdoor_corr -0.9, gap_change_per_degree_colder_c 0.43, rms_constant_offset_c 1.09, rms_scaled_l1_c 0.43, l2_per_l1_degree 0.46, rms_expected_from_rounding_c 0.41, chi2_constant_offset 57.0, dof 7
- **OP2** "the TV room warms on evenings from the people in it" - not supported by the room data alone.
  evenings 186, mean_tv_rise_18_23_c 0.095, mean_neighbour_rise_18_23_c -0.262, evenings_tv_outpaces_neighbour 121, humidity_rise_on_those_evenings_pct 0.02, humidity_rise_other_evenings_pct 0.47

## Controller outdoor sensor vs FMI Utti

- 2026-10-07T06:50Z controller 9.0 °C, Utti 8.8 °C, offset +0.2
- 2026-10-08T06:33Z controller 4.0 °C, Utti 3.3 °C, offset +0.7
- 2026-10-10T11:35Z controller 5.0 °C, Utti 4.3 °C, offset +0.7
- 2026-10-11T10:20Z controller 6.0 °C, Utti 4.9 °C, offset +1.1
- 2026-10-12T06:24Z controller 5.0 °C, Utti 4.6 °C, offset +0.4
- 2026-10-12T09:51Z controller 6.0 °C, Utti 5.6 °C, offset +0.4

Carried as uncertainty, not as a correction.

## Alerts in the replay window

0 drift alerts, 12 disturbances explained by named rules.

## Synthetic benchmark (SYNTHETIC)

SYNTHETIC - real outdoor history and fitted real building, hidden test controllers.

| Case | Hidden | Arm A best | right? | Arm B best | right? | Arm C |
|---|---|---|---|---|---|---|
| H1 | curve on 12-hour filtered outdoor, summer cutoff | S3 (0.135) | yes | S3 (0.135) | yes | S3 yes |
| H2 | curve with weekday night setback | S4 (0.155) | no | B11 (0.15) | no | M1.3 no |
| H3 | PI on room temperature with output saturation | S1 (0.137) | no | S1 (0.137) | no | M2.2 no |
| H4 | curve with cutoff hysteresis on outdoor | S1 (0.135) | no | S1 (0.135) | no | S1 no |
| H5 | STACK: weather curve plus a PI trim on the room that partly fights it | S1 (0.127) | no | S1 (0.127) | no | M3.1r no |
| H6 | STACK: weather curve gated by an on/off room thermostat | S1 (0.167) | no | S1 (0.167) | no | M1.4 no |

## Compute

- cpu x1 threads: 163840 candidates in 56.32 s, 38118740 room-hours simulated per second.
- cpu x6 threads: 163840 candidates in 31.86 s, 67383566 room-hours simulated per second.
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
