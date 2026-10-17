// Käyrä panel. Plain JS, no build. Reads artifacts/*.json written by `python -m kayra.run`.
// Live screen polls /api/state; when there is no API (static hosting) it steps the same replay locally.
"use strict";

const A = {};             // artifacts
const ROOMS = { kitchen: "Kitchen", fireplace: "Fireplace room", tv: "TV room" };
const ROOM_NOTE = { kitchen: "upstairs, floor heating (L2)", fireplace: "downstairs, radiators (L1)", tv: "downstairs, radiator with thermostatic valve" };
const note = (r) => A.real?.site?.rooms?.[r] || ROOM_NOTE[r];
let screen = "home", room = "fireplace", curveK = 0, liveTimer = null, liveIdx = null;

const $ = (s, el = document) => el.querySelector(s);
const esc = (s) => String(s ?? "").replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));
const fmt = (v, d = 2) => (v === null || v === undefined || Number.isNaN(v) ? "-" : Number(v).toFixed(d));

async function get(name) {
  try {
    const r = await fetch("artifacts/" + name, { cache: "no-store" });
    if (!r.ok) return null;
    return name.endsWith(".json") ? r.json() : r.text();
  } catch { return null; }
}

function sourceTag(src) {
  const s = String(src || "");
  if (s.startsWith("stand-in")) return `<span class="tag standin" title="Hand-written by the developer while the model was offline">stand-in</span>`;
  if (s.startsWith("model")) return `<span class="tag" title="${esc(s)}">model</span>`;
  if (s === "operator") return `<span class="tag op">operator</span>`;
  if (s.startsWith("baseline")) return `<span class="tag">grammar</span>`;
  return `<span class="tag">${esc(s || "catalogue")}</span>`;
}

function llmShort(s) {
  s = String(s || "");
  if (s.startsWith("ONLINE")) return ["ONLINE", ""];
  if (s.startsWith("ARCHIVE")) return ["ARCHIVE", ""];
  if (s.startsWith("STAND-IN")) return ["STAND-IN", "cell-warn"];
  return ["OFFLINE", "cell-warn"];
}

function setStatus() {
  const llm = A.real?.meta?.llm || A.explain?.llm || "OFFLINE";
  const [l, cls] = llmShort(llm);
  $("#st-llm").innerHTML = `<span class="${cls}" title="${esc(llm)}">${esc(l === "STAND-IN" ? "STAND-IN (not AMD)" : l === "ONLINE" ? "AMD TOKEN FACTORY" : l)}</span>`;
  const dev = A.real?.meta?.device;
  const onAmd = dev && dev.hip;
  $("#st-amd").innerHTML = onAmd ? "AMD GPU" : `<span title="AMD GPU not available for this run; same PyTorch code on ${esc(dev?.device || "cpu")}">CPU</span>`;
  const dl = A.dataLabel || "REPLAY";
  $("#st-data").innerHTML = `<span class="${dl === "LIVE" ? "" : dl === "REPLAY" ? "" : "cell-warn"}" title="${esc(A.dataNote || "")}">${esc(dl)}</span>`;
  $("#st-mode").textContent = screen === "curve" && curveK > 0 ? `ANCHORED k=${curveK}` : "HA-ONLY";
  const last = A.real?.data?.rooms?.tv?.last;
  if (last) {
    const days = Math.round((Date.now() - new Date(last)) / 864e5);
    $("#st-age").textContent = `${last.slice(0, 10)} (${days} d)`;
  }
  if (A.real?.meta) $("#gen").textContent = `Artifacts generated ${A.real.meta.generated_utc} on ${A.real.meta.device.device}, torch ${A.real.meta.device.torch}.`;
}

// ------------------------------------------------------------------ charts

function chart({ w = 720, h = 260, x0, x1, y0, y1, xTicks, yTicks, xLabel = "", yLabel = "", draw }) {
  const m = { l: 44, r: 12, t: 10, b: 30 };
  const X = (x) => m.l + ((x - x0) / (x1 - x0)) * (w - m.l - m.r);
  const Y = (y) => h - m.b - ((y - y0) / (y1 - y0)) * (h - m.t - m.b);
  let s = `<svg viewBox="0 0 ${w} ${h}" role="img" aria-label="${esc(yLabel)} against ${esc(xLabel)}">`;
  for (const t of yTicks) s += `<line class="grid" x1="${m.l}" x2="${w - m.r}" y1="${Y(t)}" y2="${Y(t)}"/><text x="${m.l - 6}" y="${Y(t) + 3}" text-anchor="end">${t}</text>`;
  for (const t of xTicks) s += `<text x="${X(t.v ?? t)}" y="${h - m.b + 14}" text-anchor="middle">${esc(t.l ?? t)}</text>`;
  s += `<line class="axis" x1="${m.l}" x2="${w - m.r}" y1="${h - m.b}" y2="${h - m.b}"/><line class="axis" x1="${m.l}" x2="${m.l}" y1="${m.t}" y2="${h - m.b}"/>`;
  s += `<text x="${w - m.r}" y="${h - 2}" text-anchor="end">${esc(xLabel)}</text><text x="${m.l}" y="${m.t - 1}" dy="-1">${esc(yLabel)}</text>`;
  s += draw(X, Y);
  return s + "</svg>";
}

const path = (pts, X, Y) => {
  let d = "", pen = false;
  for (const [x, y] of pts) {
    if (y === null || y === undefined || Number.isNaN(y)) { pen = false; continue; }
    d += (pen ? "L" : "M") + X(x).toFixed(1) + "," + Y(y).toFixed(1);
    pen = true;
  }
  return d;
};

function range(vals, pad = 0.5) {
  const v = vals.filter((x) => x !== null && x !== undefined && !Number.isNaN(x));
  return [Math.floor(Math.min(...v) - pad), Math.ceil(Math.max(...v) + pad)];
}
function ticks(a, b, n = 5) {
  const step = Math.max(1, Math.round((b - a) / n));
  const out = [];
  for (let t = Math.ceil(a / step) * step; t <= b; t += step) out.push(t);
  return out;
}

// ------------------------------------------------------------------ screens

function standinNote() {
  const llm = A.real?.meta?.llm || "";
  if (llm.startsWith("ONLINE")) return "";
  if (llm.startsWith("STAND-IN")) return `<p class="note">AMD Developer Cloud is unavailable. The language model runs on a stand-in endpoint (${esc(llm.replace(/^.*\(|\)$/g, ""))}), the same open model planned for vLLM on AMD. The fitter ran on ${esc(A.real.meta.device.device)}. Swap is one line in <code>.env</code>.</p>`;
  return `<p class="note">The language model was offline for this run. Hypotheses tagged <span class="tag standin">stand-in</span> were hand-written by the developer, not proposed by a model. Every value was still found by the fitter.</p>`;
}

function S_box() {
  const R = A.real.rooms;
  let h = `<h2>What is in the box</h2><p class="lede">Ranked control structures per room, scored on held-out cold weeks. P = share of belief from the penalised scores. A gap under 2 in ΔBIC is a tie.</p>${standinNote()}<div class="grid">`;
  for (const [r, d] of Object.entries(R)) {
    const ex = A.explain?.rooms?.[r];
    h += `<section><h3>${ROOMS[r]} · ${esc(note(r))}</h3><div class="scroll"><table><thead><tr><th>Program</th><th>Source</th><th>RMSE °C</th><th>ΔBIC</th><th>P</th></tr></thead><tbody>`;
    d.ranked.slice(0, 6).forEach((x, i) => {
      const bar = Math.max(1, Math.round(x.prob * 44));
      h += `<tr class="${i === 0 ? "lead" : ""}"><td>${esc(x.id)} ${esc(x.name || "")}${x.tie_with_best ? ` <span class="tag">tie</span>` : ""}</td><td>${sourceTag(x.source)}</td><td class="n">${fmt(x.rmse_held_c, 3)}</td><td class="n">${fmt(x.delta_bic, 1)}</td><td class="n" style="white-space:nowrap"><span class="bar ${x.prob < 0.01 ? "empty" : ""}" style="width:${bar}px"></span> ${fmt(x.prob, 2)}</td></tr>`;
    });
    h += `</tbody></table></div><p><code>${esc(d.best.expr)}</code></p>`;
    if (ex) {
      h += `<h3>Diagnosis <span class="tag">computed</span></h3>` + (ex.template || ex.lines).map((l) => `<p>${esc(l)}</p>`).join("");
      if (ex.source !== "TEMPLATE") h += `<h3>Model wording <span class="tag standin" title="${esc(ex.source)}">numbers checked, reasoning not checked</span></h3>` + ex.lines.map((l) => `<p class="lede">${esc(l)}</p>`).join("");
    }
    h += `</section>`;
  }
  h += `</div>`;
  const loops = Object.entries(A.real.loops || {}).filter(([, L]) => L.ranked);
  if (loops.length) {
    h += `<h2 style="margin-top:18px">Heating loops</h2><p class="lede">From operator site knowledge: rooms on one loop share one controller program; each room keeps its own building. Compare the held-out error with each room fitted alone.</p><div class="grid">`;
    for (const [lid, L] of loops) {
      h += `<section><h3>${esc(lid)} ${esc(L.name)} · ${L.rooms.map((r) => ROOMS[r]).join(", ")}</h3><p class="lede">${esc(L.operator_notes)}</p><div class="scroll"><table><thead><tr><th>Program</th><th>Source</th><th>RMSE °C</th><th>ΔBIC</th><th>P</th></tr></thead><tbody>`;
      L.ranked.slice(0, 5).forEach((x, i) => {
        h += `<tr class="${i === 0 ? "lead" : ""}"><td>${esc(x.id)} ${esc(x.name || "")}${x.tie_with_best ? ` <span class="tag">tie</span>` : ""}</td><td>${sourceTag(x.source)}</td><td class="n">${fmt(x.rmse_held_c, 3)}</td><td class="n">${fmt(x.delta_bic, 1)}</td><td class="n">${fmt(x.prob, 2)}</td></tr>`;
      });
      h += `</tbody></table></div><p><code>${esc(L.best.expr)}</code></p><div class="scroll"><table><thead><tr><th>Room</th><th>Heating share</th><th>RMSE in loop °C</th><th>RMSE alone °C</th></tr></thead><tbody>`;
      for (const r of L.rooms) h += `<tr><td>${ROOMS[r]}</td><td class="n">${fmt(L.heating_share[r] * 100, 0)} %</td><td class="n">${fmt(L.held_rmse_rooms[r], 3)}</td><td class="n">${fmt(L.held_rmse_rooms_fitted_alone[r], 3)}</td></tr>`;
      h += `</tbody></table></div></section>`;
    }
    h += `</div>`;
  }
  const n = A.explain?.next_observation;
  if (n) h += `<h3>Next observation</h3><p class="big" style="font-size:20px">${esc(n.pick)}</p><p>${esc(n.why)}</p>`;
  return h;
}

function S_notebook() {
  const ops = A.real.operator;
  let h = `<h2>Lab notebook</h2><p class="lede">Every hypothesis: who proposed it, what it targeted, how it scored, and its verdict. Operator beliefs are tested like any other.</p>`;
  h += `<h3>Operator beliefs</h3><div class="scroll"><table><thead><tr><th>Id</th><th>Belief</th><th>Evidence</th><th>Verdict</th></tr></thead><tbody>`;
  for (const o of ops) {
    const ev = Object.entries(o).filter(([k]) => !["id", "source", "belief", "verdict"].includes(k)).map(([k, v]) => `${k.replace(/_/g, " ")} <b>${esc(v)}</b>`).join(" · ");
    h += `<tr><td>${o.id} ${sourceTag("operator")}</td><td>${esc(o.belief)}</td><td>${ev}</td><td>${esc(o.verdict)}</td></tr>`;
  }
  h += `</tbody></table></div>`;
  const loopIds = Object.keys(A.real.loops || {}).filter((l) => A.real.loops[l].notebook);
  h += `<div class="controls">Room ${Object.keys(ROOMS).map((r) => `<button aria-pressed="${r === room}" data-room="${r}">${ROOMS[r]}</button>`).join("")} ${loopIds.length ? "Loop " : ""}${loopIds.map((l) => `<button aria-pressed="${l === room}" data-room="${l}">${l} ${esc(A.real.loops[l].name)}</button>`).join("")}</div>`;
  h += `<div class="scroll"><table><thead><tr><th>Rd</th><th>Id</th><th>Source</th><th>Mechanism / target / refuted if</th><th>Program</th><th>RMSE °C</th><th>ΔBIC</th><th>Verdict</th></tr></thead><tbody>`;
  const book = (A.real.rooms[room] || A.real.loops?.[room] || A.real.rooms.fireplace).notebook;
  for (const e of book) {
    const mech = [e.mechanism, e.targets && `<i>targets:</i> ${esc(e.targets)}`, e.refute && `<i>refuted if:</i> ${esc(e.refute)}`].filter(Boolean).join("<br>");
    h += `<tr><td class="n">${e.round ?? ""}</td><td>${esc(e.id)}</td><td>${e.id === "-" ? "" : sourceTag(e.source)}</td><td>${mech || ""}</td><td><code>${esc(e.expr || "")}</code></td><td class="n">${fmt(e.rmse_held_c, 3)}</td><td class="n">${fmt(e.delta_bic, 1)}</td><td>${esc(e.verdict)}</td></tr>`;
  }
  return h + `</tbody></table></div>`;
}

function S_curve() {
  const an = A.real.anchored_fireplace;
  const a = an.find((x) => x.k === curveK) || an[0];
  const b = a.band;
  const readings = A.readings || [];
  const ys = [...b.p05, ...b.p95, ...readings.map((r) => r.l1)].filter((v) => v !== null);
  let [y0, y1] = range(ys.length ? ys : [20, 50], 2);
  y0 = Math.max(y0, 0);
  const ev = A.eval?.curve;
  let h = `<h2>Equivalent curve · fireplace room</h2><p class="lede">Supply the identified law asks for at steady outdoor temperature. Band = likelihood-weighted 5-95 % of the search population. HA-only uses room data alone; anchored adds k panel readings of L1, which are then excluded from scoring.</p>`;
  h += `<div class="controls">Spot readings ${an.map((x) => `<button aria-pressed="${x.k === curveK}" data-k="${x.k}">k=${x.k}</button>`).join("")}</div>`;
  h += `<div class="readout"><div><label>Mode</label><span class="big">${a.k ? "ANCH " + a.k : "HA"}</span></div><div><label>Error vs other panel readings</label><span class="big">${fmt(a.rmse_vs_panel_l1_c, 1)}<span class="unit">°C</span></span></div><div><label>Band width at 4 °C outdoor</label><span class="big">${fmt(a.band_width_at_4c, 1)}<span class="unit">°C</span></span></div><div><label>Scored on</label><span class="big">${a.scored_on}</span></div></div>`;
  h += chart({
    x0: -10, x1: 20, y0, y1, xTicks: [-10, -5, 0, 5, 10, 15, 20], yTicks: ticks(y0, y1), xLabel: "outdoor °C (FMI Utti)", yLabel: "supply °C",
    draw: (X, Y) => {
      const up = b.grid_c.map((g, i) => [g, b.p95[i]]), lo = b.grid_c.map((g, i) => [g, b.p05[i]]).reverse();
      const ok = up.filter((p) => p[1] !== null);
      let s = ok.length ? `<path class="band" d="${path(ok, X, Y)}L${lo.filter((p) => p[1] !== null).map((p) => X(p[0]) + "," + Y(p[1])).join("L")}Z"/>` : "";
      s += `<path class="line" d="${path(b.grid_c.map((g, i) => [g, b.p50[i]]), X, Y)}"/>`;
      if (ev) s += `<path class="line2" d="${path(ev.map((p) => [p.outdoor_c, p.supply_c]), X, Y)}"/>`;
      readings.forEach((r, i) => {
        if (r.l1 === null || r.out === null) return;
        s += `<circle class="${i < curveK ? "anchor" : "pt"}" cx="${X(r.out)}" cy="${Y(r.l1)}" r="4"><title>panel L1 ${r.l1} °C at ${r.out} °C ${i < curveK ? "(anchor)" : "(scored)"}</title></circle>`;
        if (r.l2 !== null) s += `<rect class="pt2" x="${X(r.out) - 2.5}" y="${Y(r.l2) - 2.5}" width="5" height="5"><title>panel L2 ${r.l2} °C</title></rect>`;
      });
      return s;
    },
  });
  if (a.rmse_vs_panel_l1_c !== null && a.band_width_at_4c !== null && a.rmse_vs_panel_l1_c > a.band_width_at_4c)
    h += `<p class="note">The error against the panel readings is larger than the band. The band is the spread of the search population and does not capture how loosely room data pin the level. In this mode treat the curve level as not identified; the slope is the usable part.</p>`;
  h += `<p class="lede">Line: p50. Shaded: band. Rings: panel L1 readings (reference, scored). Filled: readings used as anchors. Squares: panel L2 (floor circuit, not modelled). ${ev ? "Dashed: configured curve from the sealed file (evaluate.py)." : "The configured curve stays sealed until <code>evaluate.py</code> runs."} No extrapolation below the observed outdoor range.</p>`;
  h += `<h3>Spot readings against error</h3><div class="scroll"><table><thead><tr><th>Mode</th><th>Error vs remaining readings °C</th><th>Band at 4 °C</th><th>Scored on</th></tr></thead><tbody>${an.map((x) => `<tr><td>${x.mode}</td><td class="n">${fmt(x.rmse_vs_panel_l1_c, 2)}</td><td class="n">${fmt(x.band_width_at_4c, 2)}</td><td class="n">${x.scored_on}</td></tr>`).join("")}</tbody></table></div>`;
  h += `<p class="lede">Controller outdoor sensor against FMI Utti: ${A.real.controller_vs_fmi.map((c) => `${c.offset_c > 0 ? "+" : ""}${c.offset_c}`).join(", ")} °C. Carried as uncertainty, not as a correction.</p>`;
  return h;
}

function liveRow() {
  if (A.live) return A.live;
  const rows = A.replay.rows;
  if (liveIdx === null) liveIdx = Math.floor(Date.now() / 3.6e6) % rows.length; // same hour for every viewer
  return rows[liveIdx];
}

async function liveTick() {
  try {
    const r = await fetch("api/state", { cache: "no-store" });
    if (!r.ok) throw 0;
    const s = await r.json();
    A.dataLabel = s.data || "REPLAY";
    A.dataNote = s.note || "";
    if (s.data && s.data !== "REPLAY" && s.row) { A.live = s.row; }
    else { A.live = null; if (typeof s.index === "number") liveIdx = s.index; }
  } catch { A.live = null; A.dataLabel = "REPLAY"; liveIdx = (liveIdx + 1) % A.replay.rows.length; }
  if (screen === "live" || (screen === "home" && !(document.activeElement && document.activeElement.dataset && document.activeElement.dataset.param))) render();
}

function roomOnly() { if (!ROOMS[room]) room = "fireplace"; }

function S_live() {
  roomOnly();
  const rows = A.replay.rows, row = liveRow();
  const i = liveIdx;
  const lbl = A.dataLabel || "REPLAY";
  let h = lbl === "REPLAY"
    ? `<h2>Live · replay</h2><p class="lede">Recorded Home Assistant history, stepped one hour every two seconds. Prediction = the identified law, 1-24 h ahead from the measured state.</p>`
    : `<h2>Live · ${esc(lbl.toLowerCase())}</h2><p class="lede">Outdoor read from FMI Utti now${lbl === "LIVE" ? ", rooms read from Home Assistant now" : "; rooms from the recorded replay (" + esc(A.dataNote) + ")"}. Prediction = steady state of the loop model fitted to this room. The chart below is the recorded history.</p>`;
  h += `<div class="readout"><div><label>Hour (UTC)</label><span class="big">${row.t.slice(5, 16).replace("T", " ")}</span></div><div><label>Outdoor</label><span class="big">${fmt(row.outdoor_c, 1)}<span class="unit">°C</span></span></div>`;
  for (const r of Object.keys(ROOMS)) {
    const d = row[r];
    const res = d.measured_c !== null && d.predicted_c !== null ? d.measured_c - d.predicted_c : null;
    h += `<div><label>${ROOMS[r]} meas / pred</label><span class="big">${fmt(d.measured_c, 1)}<span class="unit">/ ${fmt(d.predicted_c, 1)} °C</span></span><span class="lede">residual ${fmt(res, 2)} · RH ${fmt(d.rh, 0)} % · supply ${d.supply_c === null ? "OFF" : fmt(d.supply_c, 0) + " °C"}</span></div>`;
  }
  h += `</div>`;
  const win = rows.slice(Math.max(0, i - 71), i + 1);
  const vals = win.flatMap((x) => [x[room].measured_c, x[room].predicted_c]);
  const [y0, y1] = range(vals.length ? vals : [20, 24], 0.3);
  h += `<div class="controls">Room ${Object.keys(ROOMS).map((r) => `<button aria-pressed="${r === room}" data-room="${r}">${ROOMS[r]}</button>`).join("")}</div>`;
  h += chart({
    x0: 0, x1: 71, y0, y1, xTicks: [{ v: 0, l: "-72 h" }, { v: 35, l: "-36 h" }, { v: 71, l: "now" }], yTicks: ticks(y0, y1, 4), xLabel: "hours", yLabel: ROOMS[room] + " °C",
    draw: (X, Y) => `<path class="line2" d="${path(win.map((x, k) => [k, x[room].predicted_c]), X, Y)}"/><path class="line" d="${path(win.map((x, k) => [k, x[room].measured_c]), X, Y)}"/>`,
  });
  h += `<p class="lede">Solid: measured. Dashed: predicted. The live posterior from the house pusher is not deployed in this version.</p>`;
  return h;
}

function S_model() {
  roomOnly();
  const d = A.real.rooms[room];
  const rows = A.replay.rows;
  let h = `<h2>Model · ${ROOMS[room]}</h2><div class="controls">${Object.keys(ROOMS).map((r) => `<button aria-pressed="${r === room}" data-room="${r}">${ROOMS[r]}</button>`).join("")}</div>`;
  const b = d.best.building;
  h += `<div class="readout"><div><label>Structure</label><span class="big">${esc(d.best.id)}</span></div><div><label>Time constant</label><span class="big">${fmt(d.best.time_constant_h, 0)}<span class="unit">h</span></span></div><div><label>Summer free-float</label><span class="big">${fmt(d.summer_prior.time_constant_h, 0)}<span class="unit">h</span></span></div><div><label>Held-out RMSE</label><span class="big">${fmt(d.residual.rmse_held_c, 2)}<span class="unit">°C</span></span></div><div><label>Heat on</label><span class="big">${fmt(d.residual.heat_on_share_of_hours * 100, 0)}<span class="unit">% h</span></span></div></div>`;
  h += `<p><code>${esc(d.best.expr)}</code></p><p class="lede">Building: a ${fmt(b.a, 4)} /h, h ${fmt(b.h, 4)} /h, gain ${fmt(b.g0, 3)} + ${fmt(b.g1, 3)}·cos(hour − ${fmt(b.phi, 1)}) °C/h. Program: ${Object.entries(d.best.theta).map(([k, v]) => `${k} ${fmt(v, 2)}`).join(", ") || "none"}.</p>`;
  const vals = rows.flatMap((x) => [x[room].measured_c, x[room].predicted_c]);
  const [y0, y1] = range(vals, 0.3);
  const n = rows.length - 1;
  const days = [0, Math.round(n / 3), Math.round((2 * n) / 3), n].map((v) => ({ v, l: rows[v].t.slice(5, 10) }));
  h += chart({ h: 220, x0: 0, x1: n, y0, y1, xTicks: days, yTicks: ticks(y0, y1, 4), xLabel: "date (UTC)", yLabel: "room °C",
    draw: (X, Y) => `<path class="line2" d="${path(rows.map((x, k) => [k, x[room].predicted_c]), X, Y)}"/><path class="line" d="${path(rows.map((x, k) => [k, x[room].measured_c]), X, Y)}"/>` });
  const res = rows.map((x, k) => [k, x[room].measured_c !== null && x[room].predicted_c !== null ? x[room].measured_c - x[room].predicted_c : null]);
  const [r0, r1] = range(res.map((p) => p[1]), 0.1);
  h += chart({ h: 120, x0: 0, x1: n, y0: Math.min(r0, -1), y1: Math.max(r1, 1), xTicks: days, yTicks: [Math.min(r0, -1), 0, Math.max(r1, 1)], xLabel: "", yLabel: "residual °C",
    draw: (X, Y) => `<path class="line" d="${path(res, X, Y)}"/>` });
  h += `<h3>Residual by local hour (°C)</h3><p><code>${Object.entries(d.residual.mean_by_local_hour).map(([k, v]) => `${k}:${v}`).join("  ")}</code></p>`;
  return h;
}

function S_bench() {
  let h = `<h2>Benchmark</h2>`;
  const B = A.benchmark;
  if (B) {
    const max = Math.max(...B.runs.map((r) => r.room_hours_simulated_per_s));
    h += `<p class="lede">${esc(B.what)}. Same code, same candidates, measured wall time.</p><div class="scroll"><table><thead><tr><th>Device</th><th>Threads</th><th>Candidates</th><th>Wall s</th><th>Room-hours simulated per s</th></tr></thead><tbody>`;
    for (const r of B.runs) h += `<tr><td>${esc(r.hardware.gpu || r.hardware.cpu || r.device)}</td><td class="n">${r.threads}</td><td class="n">${r.candidates}</td><td class="n">${r.wall_s}</td><td class="n"><span class="bar" style="width:${Math.round((r.room_hours_simulated_per_s / max) * 160)}px"></span> ${r.room_hours_simulated_per_s.toLocaleString("en")}</td></tr>`;
    h += `<tr><td>AMD Instinct MI300X</td><td></td><td></td><td></td><td><span class="tag pending">${esc(B.gpu ? "not measured" : "see above")}</span></td></tr></tbody></table></div>`;
    if (B.gpu) h += `<p class="note">${esc(B.gpu.status)}</p>`;
  } else h += `<p class="note">benchmark.json not generated yet: <code>python -m kayra.run bench</code></p>`;
  const S = A.synth;
  if (S) {
    h += `<h3>Does the language model earn its place · SYNTHETIC</h3><p class="lede">${esc(S.label)}. Hidden controllers sit outside the seed catalogue. A = catalogue only, B = catalogue + grammar search, C = catalogue + language model. Right = recovered program contains the mechanism on the checklist fixed before the runs.</p>`;
    h += `<div class="scroll"><table><thead><tr><th>Case</th><th>Hidden mechanism</th><th>A best · RMSE · right</th><th>B best · RMSE · right · fits</th><th>C best · RMSE · right · fits</th></tr></thead><tbody>`;
    const cell = (x) => x.status ? `<span class="tag pending">not run</span>` : `${esc(x.best)} · ${fmt(x.rmse_held_c, 3)} · ${x.right_mechanism ? "<b>yes</b>" : "no"}${x.fits ? " · " + x.fits.toLocaleString("en") : ""}`;
    for (const c of S.cases) h += `<tr><td>${c.id}</td><td>${esc(c.hidden)}</td><td>${cell(c.arms.A)}</td><td>${cell(c.arms.B)}</td><td>${cell(c.arms.C)}</td></tr>`;
    const tot = (k) => S.cases.filter((c) => c.arms[k] && c.arms[k].right_mechanism).length;
    h += `<tr class="lead"><td></td><td>Right mechanism</td><td>${tot("A")} / ${S.cases.length}</td><td>${tot("B")} / ${S.cases.length}</td><td>${tot("C")} / ${S.cases.length}</td></tr></tbody></table></div>`;
    h += `<p class="lede">Arm C model: ${esc(S.meta.llm)}.</p>`;
  }
  return h;
}

function S_alert() {
  const al = A.explain?.alerts || A.real.alerts.map((a) => ({ ...a, text: `${a.rule} in ${a.room}`, source: "TEMPLATE" }));
  const drift = al.filter((a) => a.kind === "ALERT");
  let h = `<h2>Alert</h2><p class="lede">Residual against the identified law, sorted by named rules. Drift = a persistent residual in every room with nothing in humidity: the heating is not doing what the identified structure says.</p>`;
  h += `<div class="readout"><div><label>Drift alerts in replay</label><span class="big ${drift.length ? "cell-hot" : ""}">${drift.length}</span></div><div><label>Explained disturbances</label><span class="big">${al.length - drift.length}</span></div></div>`;
  h += `<div class="scroll"><table><thead><tr><th>Hour (UTC)</th><th>Room</th><th>Rule</th><th>Kind</th><th>Numbers</th><th>Explanation</th></tr></thead><tbody>`;
  for (const a of al) h += `<tr><td>${esc(a.t.slice(0, 16))}</td><td>${esc(a.room)}</td><td>${esc(a.rule)}</td><td>${a.kind === "ALERT" ? `<span class="cell-hot">ALERT</span>` : esc(a.kind)}</td><td><code>${esc(JSON.stringify(a.numbers))}</code></td><td>${esc(a.text)}</td></tr>`;
  return h + `</tbody></table></div>`;
}

function S_replace() {
  return `<h2>Replacement</h2><p class="note"><span class="tag pending">pending</span> Not computed in this version. The replacement search needs the closed-loop simulation runs scheduled for the AMD GPU.</p>
  <p>The plan: one documented controller that could replace the stack, cheapest tier first, each tuned in closed-loop simulation on the identified model over the real outdoor history.</p>
  <div class="scroll"><table><thead><tr><th>Tier</th><th>What</th><th>Cost signal</th></tr></thead><tbody>
  <tr><td>0</td><td>Retune what is installed: the identified controller class with new settings</td><td>a technician's hour</td></tr>
  <tr><td>1</td><td>Off-the-shelf two-circuit weather-compensated controller from the template library</td><td>settings, maybe one room sensor</td></tr>
  <tr><td>2</td><td>Standard PLC or DDC function blocks: curve, PID, scheduler, limiter</td><td>configuration</td></tr>
  <tr><td>3</td><td>Custom program in the structure language, exported as IEC 61131-3 Structured Text</td><td>code, only if 0-2 fall short</td></tr>
  </tbody></table></div><p class="lede">Objective, from data only: each room at least as tight around its as-found median as now, with less heat input. Validated in simulation only.</p>`;
}

function md(text) {
  const lines = text.split("\n");
  let out = "", inTable = false, inList = false;
  const inline = (s) => esc(s).replace(/`([^`]+)`/g, "<code>$1</code>").replace(/\*\*([^*]+)\*\*/g, "<b>$1</b>").replace(/\*([^*]+)\*/g, "<i>$1</i>");
  for (const l of lines) {
    if (l.startsWith("|")) {
      if (/^\|[-| ]+\|$/.test(l)) continue;
      const cells = l.split("|").slice(1, -1).map((c) => inline(c.trim()));
      if (!inTable) { out += `<div class="scroll"><table><thead><tr>${cells.map((c) => `<th>${c}</th>`).join("")}</tr></thead><tbody>`; inTable = true; }
      else out += `<tr>${cells.map((c) => `<td>${c}</td>`).join("")}</tr>`;
      continue;
    }
    if (inTable) { out += "</tbody></table></div>"; inTable = false; }
    if (l.startsWith("- ") || l.startsWith("  ")) { if (!inList) { out += "<ul>"; inList = true; } out += `<li>${inline(l.replace(/^-\s|^\s+/, ""))}</li>`; continue; }
    if (inList) { out += "</ul>"; inList = false; }
    if (l.startsWith("### ")) out += `<h3>${inline(l.slice(4))}</h3>`;
    else if (l.startsWith("## ")) out += `<h2 style="margin-top:18px">${inline(l.slice(3))}</h2>`;
    else if (l.startsWith("# ")) out += `<h2>${inline(l.slice(2))}</h2>`;
    else if (l.startsWith("> ")) out += `<p class="note">${inline(l.slice(2))}</p>`;
    else if (l.trim()) out += `<p>${inline(l)}</p>`;
  }
  return out + (inTable ? "</tbody></table></div>" : "") + (inList ? "</ul>" : "");
}

function S_doc() {
  let h = `<div class="doc">`;
  const W = A.writeup;
  if (W && W.sections && W.sections.length) {
    h += `<h2>As-found specification</h2><p class="note">Written by the language model (${esc(W.llm)}${W.model ? ", " + esc(W.model) : ""}) from the computed evidence. Every number is checked against that evidence; ${W.dropped.length} line(s) dropped. The reasoning is not checked by code: the computed tables follow below.</p>`;
    for (const sec of W.sections) h += `<h3>${esc(sec.title)}</h3>` + sec.lines.map((l) => `<p>${esc(l)}</p>`).join("");
    h += `<h2 style="margin-top:22px">Computed tables</h2>`;
  }
  return h + (A.document ? md(A.document) : "<p>document.md not generated yet.</p>") + `</div>`;
}


// ------------------------------------------------------------------ home: the simple view
// One loop at a time. Top: the supply curve (outdoor -> supply), fitted, and yours if you move it.
// Bottom: room temperatures against outdoor - daily history and the live hour - and where the
// identified building says each room settles under the curve on top. All arithmetic here is the
// steady state of the fitted building model; nothing is fitted in the browser.
let loopId = null, user = null;
const ROOM_CLASS = ["ra", "rb", "rc"];

function curveAt(p, to) { return to >= p.cutoff ? null : p.level + p.slope * to; }

function roomSteady(b, p, to) {
  // T = T + a(To - T) + h*max(S - T, 0) + g0 at rest; the daily gain term averages out
  const free = to + b.g0 / b.a;
  const S = curveAt(p, to);
  if (S === null) return free;
  const heated = (b.a * to + b.h * S + b.g0) / (b.a + b.h);
  return S > heated ? heated : free;
}

function heatIndex(L, p) {
  // relative heat input over the recorded days: sum of h*max(S - T, 0) per room
  let sum = 0;
  for (const d of A.points.days) for (const r of L.rooms) {
    const b = L.building_rooms[r], S = curveAt(p, d.out);
    if (S === null) continue;
    sum += b.h * Math.max(S - roomSteady(b, p, d.out), 0);
  }
  return sum;
}

function S_home() {
  const simple = A.real.simple || {};
  const ids = Object.keys(simple);
  if (!ids.length || !A.points) return `<p class="note">The simple view needs <code>simple</code> in real.json and points.json. Run <code>python -m kayra.run real</code>.</p>`;
  if (!loopId || !simple[loopId]) loopId = ids[0];
  const L = simple[loopId];
  const fitted = { level: L.theta.level, slope: L.theta.slope, cutoff: L.theta.cutoff };
  if (!user || user._loop !== loopId) user = { ...fitted, _loop: loopId };
  const moved = ["level", "slope", "cutoff"].some((k) => Math.abs(user[k] - fitted[k]) > 1e-6);
  const row = A.replay ? liveRow() : null;
  const vs = L.vs_no_control;

  let h = `<div class="simple"><div>`;
  h += `<div class="controls">${ids.map((id) => `<button aria-pressed="${id === loopId}" data-loop="${id}">${esc(id)} ${esc(simple[id].name)}</button>`).join("")}</div>`;

  // top: supply curve. Outdoor axis runs +20 to -20, the way heating curves are printed.
  const X0 = 20, X1 = -20, grid = [];
  for (let t = 20; t >= -20; t -= 0.5) grid.push(t);
  h += chart({ h: 230, x0: X0, x1: X1, y0: 20, y1: 80, xTicks: [20, 10, 0, -10, -20], yTicks: [20, 35, 50, 65, 80],
    xLabel: "outdoor °C", yLabel: "supply °C",
    draw: (X, Y) => {
      let s = "";
      if (moved) s += `<path class="fit" d="${path(grid.map((t) => [t, curveAt(fitted, t)]), X, Y)}"/>`;
      s += `<path class="curve" d="${path(grid.map((t) => [t, curveAt(user, t)]), X, Y)}"/>`;
      s += `<line class="grid" x1="${X(user.cutoff)}" x2="${X(user.cutoff)}" y1="${Y(80)}" y2="${Y(20)}" stroke-dasharray="2 3"/><text x="${X(user.cutoff) + 3}" y="${Y(77)}">stop ${fmt(user.cutoff, 1)}</text>`;
      for (const r of A.readings || []) {
        const v = loopId === "L1" ? r.l1 : r.l2;
        if (v !== null && v !== undefined) s += `<circle class="pt" cx="${X(r.out)}" cy="${Y(v)}" r="3.5"><title>panel reading ${v} °C at ${r.out} °C (reference)</title></circle>`;
      }
      if (row) {
        const S = curveAt(user, row.outdoor_c);
        if (S !== null) s += `<circle class="live" cx="${X(row.outdoor_c)}" cy="${Y(S)}" r="7"><title>this hour</title></circle>`;
      }
      return s;
    } });

  // bottom: rooms against outdoor
  const vals = A.points.days.flatMap((d) => L.rooms.map((r) => d[r])).filter((v) => v !== null);
  const [y0, y1] = range(vals, 0.5);
  h += chart({ h: 230, x0: X0, x1: X1, y0, y1, xTicks: [20, 10, 0, -10, -20], yTicks: ticks(y0, y1, 4),
    xLabel: "outdoor °C (daily mean)", yLabel: "room °C",
    draw: (X, Y) => {
      let s = "";
      L.rooms.forEach((r, i) => {
        const col = `var(--room-${"abc"[i]})`;
        for (const d of A.points.days) if (d[r] !== null && d.out <= X0 && d.out >= X1) s += `<circle class="${ROOM_CLASS[i]}" cx="${X(d.out)}" cy="${Y(d[r])}" r="2.2" opacity=".55"><title>${d.d} ${ROOMS[r]} ${d[r]} °C at ${d.out} °C</title></circle>`;
        const b = L.building_rooms[r];
        const line = grid.map((t) => { const v = roomSteady(b, user, t); return [t, v >= y0 - 2 && v <= y1 + 2 ? v : null]; });
        s += `<path class="pred" style="stroke:${col}" d="${path(line, X, Y)}"/>`;
        for (const lh of A.liveHist || []) { const v = lh.row && lh.row[r] && lh.row[r].measured_c; if (lh.data === "LIVE" && v !== null && v !== undefined) s += `<rect x="${X(lh.row.outdoor_c) - 2.5}" y="${Y(v) - 2.5}" width="5" height="5" style="fill:${col}"><title>live ${esc(lh.row.t.slice(0, 16))} ${v} °C</title></rect>`; }
        if (row && row[r] && row[r].measured_c !== null && row[r].measured_c !== undefined) s += `<circle class="live" style="stroke:${col}" cx="${X(row.outdoor_c)}" cy="${Y(row[r].measured_c)}" r="6"/>`;
      });
      return s;
    } });
  h += `<div class="legend">${L.rooms.map((r, i) => `<span><i style="background:var(--room-${"abc"[i]})"></i>${ROOMS[r]}: dots are days, line is predicted under the curve above</span>`).join("")}<span>ring: this hour (${esc((A.dataLabel || "REPLAY").toLowerCase())})</span>${(A.liveHist || []).length ? `<span>squares: ${A.liveHist.length} logged live hours</span>` : ""}<span>top rings: panel readings, reference only</span></div>`;
  h += `</div><div class="sliders">`;

  // right column: the controls and what they predict
  h += `<h2>${esc(L.name)}</h2>`;
  if (vs) {
    const d = vs.S0.bic - vs.S3.bic;
    h += `<p class="lede">Weather curve with summer stop, fitted to ${L.rooms.map((r) => ROOMS[r]).join(" and ")} over ${vs.windows} three-day windows. Against no control on the same weeks: ΔBIC <b>${fmt(d, 1)}</b> ${d >= 10 ? "in favour of the curve" : d > 2 ? "for the curve, weakly" : "- a tie"}.</p>`;
  }
  const sl = (k, label, lo, hi, step, unit) => `<div><label for="sl-${k}">${label}<span>${fmt(user[k], step < 0.1 ? 2 : 1)} ${unit}</span></label><input id="sl-${k}" type="range" min="${lo}" max="${hi}" step="${step}" value="${user[k]}" data-param="${k}"></div>`;
  h += sl("level", "Supply at 0 °C outdoor", 15, 80, 0.5, "°C") + sl("slope", "Slope", -3, 0, 0.05, "°C/°C") + sl("cutoff", "Summer stop above", 5, 25, 0.5, "°C");
  h += `<div class="controls"><button class="key" data-fit="1">Fit</button>${moved ? `<span class="tag standin">your curve</span>` : `<span class="tag">fitted</span>`}</div>`;
  const hi0 = heatIndex(L, fitted), hi1 = heatIndex(L, user);
  h += `<div class="readout" style="flex-direction:column;gap:8px">`;
  if (row) {
    const S = curveAt(user, row.outdoor_c);
    h += `<div><label>Outdoor ${A.dataLabel && A.dataLabel !== "REPLAY" ? "now (FMI)" : "this hour (replay)"}</label><span class="big">${fmt(row.outdoor_c, 1)}<span class="unit">°C</span></span></div>`;
    h += `<div><label>Supply asked</label><span class="big">${S === null ? "OFF" : fmt(S, 0)}<span class="unit">${S === null ? "" : "°C"}</span></span></div>`;
    for (const r of L.rooms) h += `<div><label>${ROOMS[r]} predicted / measured</label><span class="big" style="font-size:22px">${fmt(roomSteady(L.building_rooms[r], user, row.outdoor_c), 1)}<span class="unit">/ ${fmt(row[r]?.measured_c, 1)} °C</span></span></div>`;
  }
  const sens = L.rooms.map((r) => {
    const b = L.building_rooms[r];
    return `${ROOMS[r]} ${fmt(roomSteady(b, { ...user, level: user.level + 5 }, 0) - roomSteady(b, user, 0), 2)}`;
  }).join(", ");
  h += `<div><label>Room change for +5 °C supply at 0 °C</label><span style="font:var(--s0) var(--f-num)">${sens} °C</span></div>`;
  h += `<div><label>Heat input vs fitted curve</label><span class="big" style="font-size:22px">${moved && hi0 > 0 ? (hi1 >= hi0 ? "+" : "") + fmt((hi1 / hi0 - 1) * 100, 0) : "0"}<span class="unit">% over the record</span></span></div></div>`;
  h += `<p class="lede">Predictions are the steady state of the building model fitted to the rooms on this loop (held-out error ${L.rooms.map((r) => `${ROOMS[r]} ${fmt(L.held_rmse_rooms[r], 2)} °C`).join(", ")}). Outdoor in the data runs ${fmt(A.real.data.outdoor.min_c, 1)} to ${fmt(A.real.data.outdoor.max_c, 1)} °C; outside that the lines are extrapolation.</p>`;
  h += `<p class="lede">More under the Advanced keys: ranked structures, the hypothesis notebook, spot readings, benchmark.</p>`;
  return h + `</div></div>`;
}

document.addEventListener("input", (e) => {
  const k = e.target.dataset && e.target.dataset.param;
  if (!k || !user) return;
  user[k] = Number(e.target.value);
  const id = e.target.id;
  render();
  const el = document.getElementById(id);
  if (el) el.focus();
});

// ------------------------------------------------------------------ AI: what the model did
function S_ai() {
  const books = [...Object.entries(A.real.rooms), ...Object.entries(A.real.loops || {}).filter(([, L]) => L.notebook)];
  const model = books.flatMap(([k, R]) => R.notebook.filter((e) => String(e.source || "").startsWith("model")).map((e) => ({ ...e, where: k })));
  const rejected = model.filter((e) => String(e.verdict).startsWith("rejected"));
  const repaired = model.filter((e) => /r$/.test(e.id));
  const fitted = model.filter((e) => e.rmse_held_c !== undefined && e.rmse_held_c !== null);
  const C = A.context, W = A.writeup;
  const llm = A.real.meta.llm;
  let h = `<h2>What the language model did</h2><p class="lede">The model proposes and explains; the fitter computes and decides. It never writes a number: programs carry typed parameters only, and every line of prose is checked against the evidence it was given. Model: ${esc(llm)}${C?.model ? `, programs by ${esc(C.model)}` : ""}${W?.model ? `, prose by ${esc(W.model)}` : ""}.</p>`;
  h += `<div class="readout"><div><label>Programs proposed</label><span class="big">${model.length + (C ? C.programs.length : 0)}</span></div><div><label>Rejected by validator</label><span class="big">${rejected.length + (C ? C.programs.filter((e) => String(e.verdict).startsWith("rejected")).length : 0)}</span></div><div><label>Repaired after rejection</label><span class="big">${repaired.length + (C ? C.repaired : 0)}</span></div><div><label>Fitted and scored</label><span class="big">${fitted.length + (C ? C.programs.filter((e) => e.bic !== undefined).length : 0)}</span></div><div><label>Prose lines dropped by guardrails</label><span class="big">${(A.explain?.dropped?.length || 0) + (W?.dropped?.length || 0)}</span></div></div>`;
  if (C) {
    h += `<h3>Site context into programs <span class="tag">separate arm</span></h3><p class="lede">The model read the operator notes and the controller's menu labels (labels only, no values) and wrote a program for each mechanism they imply. The fitter scored each against the best program found without context. ${esc(C.note)}</p>`;
    h += `<div class="scroll"><table><thead><tr><th>Id</th><th>Target</th><th>From the plant</th><th>Program</th><th>ΔBIC vs blind best</th><th>Verdict</th></tr></thead><tbody>`;
    for (const e of C.programs) h += `<tr><td>${esc(e.id)}</td><td>${esc(e.target)}</td><td>"${esc(e.from_text)}"<br><span class="lede">${esc(e.mechanism)}</span></td><td><code>${esc(e.expr || "")}</code></td><td class="n">${e.delta_bic_vs_blind_best === undefined ? "-" : (e.delta_bic_vs_blind_best > 0 ? "+" : "") + fmt(e.delta_bic_vs_blind_best, 1)}</td><td>${esc(e.verdict)}</td></tr>`;
    h += `</tbody></table></div>`;
    if (C.not_expressible?.length) h += `<p class="lede">The model said these cannot be written in the language: ${C.not_expressible.map((x) => `"${esc(x.from_text)}" (${esc(x.why)})`).join("; ")}.</p>`;
  }
  h += `<h3>Validator rejections, examples</h3><div class="scroll"><table><thead><tr><th>Where</th><th>Program</th><th>Reason</th></tr></thead><tbody>`;
  for (const e of rejected.slice(0, 8)) h += `<tr><td>${esc(e.where)} ${esc(e.id)}</td><td><code>${esc(e.expr || "")}</code></td><td>${esc(String(e.verdict).replace("rejected by validator: ", ""))}</td></tr>`;
  h += `</tbody></table></div>`;
  const drops = [...(A.explain?.dropped || []), ...(W?.dropped || [])];
  if (drops.length) {
    h += `<h3>Prose lines dropped by guardrails</h3><div class="scroll"><table><thead><tr><th>Line</th><th>Number not in evidence</th></tr></thead><tbody>`;
    for (const d of drops.slice(0, 8)) h += `<tr><td>${esc(d.line)}</td><td><code>${esc(d.ungrounded.join(", "))}</code></td></tr>`;
    h += `</tbody></table></div>`;
  }
  h += `<p class="lede">Every prompt and reply is in <code>artifacts/llm_archive.jsonl</code>.</p>`;
  return h;
}

const SCREENS = { ai: S_ai, home: S_home, box: S_box, notebook: S_notebook, curve: S_curve, live: S_live, model: S_model, bench: S_bench, alert: S_alert, replace: S_replace, doc: S_doc };

function render() {
  document.querySelectorAll("nav.keys button").forEach((b) => b.setAttribute("aria-selected", String(b.dataset.s === screen)));
  try { $("#screen").innerHTML = SCREENS[screen](); }
  catch (e) { $("#screen").innerHTML = `<p class="note">This screen could not render: ${esc(e.message)}. Re-run <code>python -m kayra.run all</code>.</p>`; }
  setStatus();
}

document.addEventListener("click", (e) => {
  const t = e.target.closest("button");
  if (!t) return;
  if (t.dataset.s) { screen = t.dataset.s; try { history.replaceState(null, "", "#" + screen); } catch {} }
  if (t.dataset.room) room = t.dataset.room;
  if (t.dataset.k !== undefined) curveK = Number(t.dataset.k);
  if (t.dataset.loop) loopId = t.dataset.loop;
  if (t.dataset.fit) user = null;
  render();
});

async function boot() {
  const [real, synth, benchmark, replay, explain, ev, doc, readings, points, context, writeup] = await Promise.all([
    get("real.json"), get("synth.json"), get("benchmark.json"), get("replay.json"), get("explain.json"), get("eval.json"), get("document.md"), get("readings.json"), get("points.json"), get("context.json"), get("writeup.json"),
  ]);
  Object.assign(A, { real, synth, benchmark, replay, explain, eval: ev, document: doc, readings, points, context, writeup });
  if (!real) { $("#screen").innerHTML = `<p class="note">No artifacts found. Run <code>python -m kayra.run all</code>, then <code>python tools/dev_server.py</code>.</p>`; return; }
  const h = location.hash.slice(1);
  if (SCREENS[h]) screen = h;
  render();
  try { const r = await fetch("api/live", { cache: "no-store" }); if (r.ok) A.liveHist = await r.json(); } catch {}
  await liveTick();
  render();
  liveTimer = setInterval(liveTick, 2000);
}
boot();
