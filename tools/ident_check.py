#!/usr/bin/env python3
"""Identifiability check for the Home-Assistant-only claim. SYNTHETIC - no real data.

Question: if the product sees only outdoor temperature and room temperature,
can it recover a weather curve (supply = a + b * outdoor) hidden behind the
building's thermal dynamics?

Method: simulate a one-room building, summer free-floating then heating season
with a known curve, add noise and 0.1 C sensor quantisation, then recover
loss, heating gain, slope and level by naive one-step regression per regime.
The real fit uses simulation error over windows and should do better; this
script only shows the shape of the problem.

Written 2026-10-12 for BUILD.md, section Identifiability. Standard library + numpy.
The curve values here are arbitrary test values, deliberately unrelated to the
real controller. Never put the real configured curve in any file the fit or the
coding agent reads - it lives only in data/manual/ouman_curve_setting.csv.
"""
import numpy as np


def run(n_summer=2000, n_heat=1200, a=46.0, b=-1.10, alpha=1/60, beta=1/40,
        gain_heat_extra=0.0, noise=0.03, quant=0.1, seed=0):
    rng = np.random.default_rng(seed)
    N = n_summer + n_heat
    hours = np.arange(N) % 24
    base = np.r_[np.full(n_summer, 16.0), np.full(n_heat, 6.0)]
    wx = np.cumsum(rng.normal(0, 0.3, N))
    wx -= np.convolve(wx, np.ones(72) / 72, "same")
    Tout = base + 4 * np.sin(2 * np.pi * (hours - 9) / 24) + wx
    on = np.r_[np.zeros(n_summer), np.ones(n_heat)]
    solar = 0.04 * np.clip(np.sin(2 * np.pi * (hours - 6) / 24), 0, None)
    internal = 0.02 + gain_heat_extra * on   # gains may differ by season
    T = np.empty(N)
    T[0] = 21
    for t in range(N - 1):
        T[t + 1] = (T[t] + alpha * (Tout[t] - T[t]) + on[t] * beta * (a + b * Tout[t] - T[t])
                    + solar[t] + internal[t] + rng.normal(0, noise))
    Tm = np.round(T / quant) * quant
    dT = np.diff(Tm)
    X0, Xo, h, o = Tm[:-1], Tout[:-1], hours[:-1], on[:-1]
    harm = np.c_[np.sin(2 * np.pi * h / 24), np.cos(2 * np.pi * h / 24)]

    def reg(mask):
        A = np.c_[Xo[mask], X0[mask], np.ones(mask.sum()), harm[mask]]
        coef, *_ = np.linalg.lstsq(A, dT[mask], rcond=None)
        return coef

    cs, ch = reg(o == 0), reg(o == 1)
    alpha_hat = cs[0]
    beta_hat = -ch[1] - alpha_hat
    b_hat = (ch[0] - alpha_hat) / beta_hat
    a_hat = (ch[2] - cs[2]) / beta_hat      # assumes same mean gains both seasons
    return a_hat, b_hat


if __name__ == "__main__":
    for extra in (0.0, 0.01):
        res = np.array([run(seed=s, gain_heat_extra=extra) for s in range(40)])
        at5 = res[:, 0] + res[:, 1] * 5
        print(f"extra heating-season gain {extra}: slope {res[:,1].mean():.2f} +/- {res[:,1].std():.2f} (true -1.10); "
              f"supply@5C {at5.mean():.1f} +/- {at5.std():.1f} (true 40.50)")
