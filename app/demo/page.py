"""The demo dashboard, as a single self-contained HTML string.

No CDN and no build step: a container may have no outbound internet, and a demo that silently
loses its charting library in front of a reviewer is worse than no demo. Charts are inline SVG
drawn from the same JSON the API returns.

The page is deliberately explicit about the boundary it exists to show: the model produces
typed directives, and every kWh after that is computed by the optimizer.
"""

from __future__ import annotations

DEMO_PAGE = """<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>GridWise — pipeline demo</title>
<style>
  :root {
    --bg:#0f1420; --panel:#171e2e; --line:#2a3550; --text:#e8edf7; --muted:#9aa8c4;
    --ok:#3ddc97; --warn:#ffb454; --bad:#ff6b6b; --grid:#5b8def; --solar:#ffd166; --batt:#c792ea;
  }
  * { box-sizing:border-box; }
  body { margin:0; background:var(--bg); color:var(--text);
         font:14px/1.5 ui-sans-serif,system-ui,'Segoe UI',Roboto,sans-serif; }
  header { padding:18px 24px; border-bottom:1px solid var(--line); display:flex;
           align-items:baseline; gap:16px; flex-wrap:wrap; }
  h1 { font-size:18px; margin:0; letter-spacing:.3px; }
  .sub { color:var(--muted); font-size:13px; }
  main { padding:20px 24px; display:grid; gap:18px; max-width:1200px; }
  .panel { background:var(--panel); border:1px solid var(--line); border-radius:10px; padding:16px; }
  .panel h2 { font-size:13px; text-transform:uppercase; letter-spacing:.8px;
              color:var(--muted); margin:0 0 12px; }
  button { background:var(--grid); color:#07101f; border:0; border-radius:7px;
           padding:9px 16px; font-weight:650; cursor:pointer; }
  button:disabled { opacity:.5; cursor:default; }
  textarea { width:100%; min-height:120px; background:#0d1322; color:var(--text);
             border:1px solid var(--line); border-radius:7px; padding:10px;
             font-family:ui-monospace,Menlo,Consolas,monospace; font-size:12px; }
  table { width:100%; border-collapse:collapse; font-size:13px; }
  th,td { text-align:left; padding:6px 8px; border-bottom:1px solid var(--line); }
  th { color:var(--muted); font-weight:600; font-size:12px; }
  .pill { display:inline-block; padding:1px 8px; border-radius:99px; font-size:11px; font-weight:650; }
  .pill.ok { background:rgba(61,220,151,.16); color:var(--ok); }
  .pill.bad { background:rgba(255,107,107,.16); color:var(--bad); }
  .pill.warn { background:rgba(255,180,84,.16); color:var(--warn); }
  .flow { display:flex; align-items:center; gap:8px; flex-wrap:wrap; color:var(--muted); font-size:12px; }
  .flow b { color:var(--text); }
  .stats { display:grid; grid-template-columns:repeat(auto-fit,minmax(150px,1fr)); gap:12px; }
  .stat { background:#0d1322; border:1px solid var(--line); border-radius:8px; padding:10px 12px; }
  .stat .k { color:var(--muted); font-size:11px; text-transform:uppercase; letter-spacing:.6px; }
  .stat .v { font-size:19px; font-weight:680; margin-top:3px; }
  .note { color:var(--muted); font-size:12px; margin-top:8px; }
  .legend span { margin-right:14px; font-size:12px; color:var(--muted); }
  .swatch { display:inline-block; width:10px; height:10px; border-radius:2px; margin-right:5px; }
  .err { color:var(--bad); white-space:pre-wrap; font-size:12px; }
</style>
</head>
<body>
<header>
  <h1>GridWise</h1>
  <span class="sub">operator notes &rarr; typed directives &rarr; constraints &rarr; optimal plan &rarr; independent replay</span>
</header>

<main>
  <section class="panel">
    <h2>Scenario</h2>
    <div class="flow">
      <b>LLM</b> interprets language &rarr; <b>guardrails</b> validate &rarr;
      <b>compiler</b> makes constraints &rarr; <b>LP+MILP</b> computes every kWh &rarr;
      <b>replay</b> proves it. <em>The model never chooses a number.</em>
    </div>
    <p class="note">Paste a scenario request, or load a public sample.</p>
    <textarea id="scenario" spellcheck="false"></textarea>
    <div style="margin-top:10px; display:flex; gap:10px; flex-wrap:wrap;">
      <button id="run">Analyze</button>
      <button id="sample">Load sample</button>
      <button id="regress">Run public cases</button>
    </div>
    <div id="error" class="err"></div>
  </section>

  <section class="panel" id="summary" hidden>
    <h2>Result</h2>
    <div class="stats" id="stats"></div>
    <p class="note" id="plan-summary"></p>
  </section>

  <section class="panel" id="interp" hidden>
    <h2>Interpretation trace</h2>
    <table><thead><tr>
      <th>#</th><th>Operator note</th><th>Directive</th><th>Hours</th><th>Value</th><th>Guardrail</th>
    </tr></thead><tbody id="interp-body"></tbody></table>
  </section>

  <section class="panel" id="chart-panel" hidden>
    <h2>24-hour energy flow</h2>
    <div class="legend">
      <span><i class="swatch" style="background:var(--grid)"></i>grid</span>
      <span><i class="swatch" style="background:var(--solar)"></i>solar used</span>
      <span><i class="swatch" style="background:var(--batt)"></i>state of charge</span>
      <span><i class="swatch" style="background:#8899bb"></i>demand</span>
    </div>
    <div id="chart"></div>
  </section>

  <section class="panel" id="proof" hidden>
    <h2>Validation proof</h2>
    <div class="stats" id="proof-stats"></div>
    <p class="note">Residuals are measured by replaying the serialized response, independently of the optimizer.</p>
  </section>

  <section class="panel" id="hours-panel" hidden>
    <h2>Per-hour detail and binding constraints</h2>
    <table><thead><tr>
      <th>H</th><th>Demand</th><th>Solar (eff.)</th><th>Used</th><th>Grid</th>
      <th>Battery</th><th>SoC</th><th>Tariff</th><th>Binding</th>
    </tr></thead><tbody id="hours-body"></tbody></table>
  </section>

  <section class="panel" id="regress-panel" hidden>
    <h2>Public-case regression</h2>
    <div id="regress-body"></div>
  </section>
</main>

<script>
const $ = (id) => document.getElementById(id);
const fmt = (v, d = 1) => (v === null || v === undefined) ? "-" : Number(v).toFixed(d);

async function loadSample() {
  const res = await fetch("/demo/sample-scenario");
  $("scenario").value = JSON.stringify(await res.json(), null, 2);
}

function stat(label, value) {
  return `<div class="stat"><div class="k">${label}</div><div class="v">${value}</div></div>`;
}

function renderChart(hours) {
  const W = 1040, H = 260, P = 34;
  const maxFlow = Math.max(...hours.map(h => Math.max(h.demand_kwh, h.grid_kwh, h.solar_used_kwh)), 1);
  const maxSoc = Math.max(...hours.map(h => h.battery_energy_after_kwh), 1);
  const bw = (W - 2 * P) / hours.length;
  const y = (v, max) => H - P - (v / max) * (H - 2 * P);

  let svg = `<svg viewBox="0 0 ${W} ${H}" width="100%" height="${H}">`;
  svg += `<line x1="${P}" y1="${H - P}" x2="${W - P}" y2="${H - P}" stroke="#2a3550"/>`;
  hours.forEach((h, i) => {
    const x = P + i * bw;
    svg += `<rect x="${x + 1}" y="${y(h.grid_kwh, maxFlow)}" width="${bw * .42}" `
         + `height="${H - P - y(h.grid_kwh, maxFlow)}" fill="#5b8def"/>`;
    svg += `<rect x="${x + 1 + bw * .46}" y="${y(h.solar_used_kwh, maxFlow)}" width="${bw * .42}" `
         + `height="${H - P - y(h.solar_used_kwh, maxFlow)}" fill="#ffd166"/>`;
    if (i % 3 === 0) {
      svg += `<text x="${x + bw / 2}" y="${H - P + 14}" fill="#9aa8c4" font-size="10" `
           + `text-anchor="middle">${h.hour}</text>`;
    }
  });
  const demand = hours.map((h, i) => `${P + i * bw + bw / 2},${y(h.demand_kwh, maxFlow)}`).join(" ");
  svg += `<polyline points="${demand}" fill="none" stroke="#8899bb" stroke-width="1.5" stroke-dasharray="4 3"/>`;
  const soc = hours.map((h, i) => `${P + i * bw + bw / 2},${y(h.battery_energy_after_kwh, maxSoc)}`).join(" ");
  svg += `<polyline points="${soc}" fill="none" stroke="#c792ea" stroke-width="2"/>`;
  svg += `</svg>`;
  $("chart").innerHTML = svg;
}

function render(data) {
  $("summary").hidden = $("interp").hidden = $("chart-panel").hidden = false;
  $("proof").hidden = $("hours-panel").hidden = false;

  const c = data.cost_comparison;
  $("stats").innerHTML = [
    stat("Total cost (BDT)", fmt(data.totals_cost_bdt, 2)),
    stat("Grid energy (kWh)", fmt(data.totals_grid_kwh, 1)),
    stat("Peak grid (kWh)", fmt(data.peak_grid_kwh, 1)),
    stat("Optimal proven", data.solver.proven_optimal
      ? '<span class="pill ok">yes</span>' : '<span class="pill warn">time-limited</span>'),
    stat("No-storage baseline", c.baseline_feasible
      ? `${fmt(c.baseline_cost_bdt, 0)} (saves ${fmt(c.savings_percent, 1)}%)`
      : '<span class="pill warn">infeasible</span>'),
    stat("Pipeline", `${fmt(data.pipeline_ms, 0)} ms`),
  ].join("");
  $("plan-summary").textContent = data.plan_summary;

  $("interp-body").innerHTML = data.interpretation.map(n => `<tr>
    <td>${n.note_index}</td><td>${n.note}</td>
    <td><b>${n.directive_type}</b></td>
    <td>${n.hours.length ? "[" + n.hours.join(", ") + "]" : "-"}</td>
    <td>${n.numeric_value === null ? "-" : n.numeric_value + " <span class='sub'>" + n.numeric_label + "</span>"}</td>
    <td><span class="pill ok">${n.guardrail_status}</span></td></tr>`).join("");

  const v = data.validation;
  $("proof-stats").innerHTML = [
    stat("Replay", v.passed ? '<span class="pill ok">PASS</span>' : '<span class="pill bad">FAIL</span>'),
    stat("Max balance error", v.max_energy_balance_error.toExponential(1)),
    stat("Max transition error", v.max_battery_transition_error.toExponential(1)),
    stat("Final SoC error", v.final_state_of_charge_error.toExponential(1)),
    stat("LP &le; MILP", data.solver.lower_bound_respected
      ? '<span class="pill ok">held</span>' : '<span class="pill bad">violated</span>'),
  ].join("");

  $("hours-body").innerHTML = data.hours.map(h => `<tr>
    <td>${h.hour}</td><td>${fmt(h.demand_kwh)}</td>
    <td>${fmt(h.effective_solar_kwh)}${h.effective_solar_kwh < h.original_solar_kwh
      ? ` <span class="pill warn">was ${fmt(h.original_solar_kwh)}</span>` : ""}</td>
    <td>${fmt(h.solar_used_kwh)}</td><td>${fmt(h.grid_kwh)}</td>
    <td>${h.battery_action}${h.battery_kwh ? " " + fmt(h.battery_kwh) : ""}</td>
    <td>${fmt(h.battery_energy_after_kwh)}</td><td>${fmt(h.tariff_bdt_per_kwh, 2)}</td>
    <td>${h.binding.map(b => `<span class="pill warn">${b}</span>`).join(" ")}</td></tr>`).join("");

  renderChart(data.hours);
}

async function analyze() {
  $("error").textContent = "";
  $("run").disabled = true;
  try {
    const res = await fetch("/demo/analyze", {
      method: "POST", headers: { "content-type": "application/json" }, body: $("scenario").value,
    });
    const body = await res.json();
    if (!res.ok) { $("error").textContent = JSON.stringify(body, null, 2); return; }
    render(body);
  } catch (e) {
    $("error").textContent = String(e);
  } finally {
    $("run").disabled = false;
  }
}

async function regression() {
  $("regress-panel").hidden = false;
  $("regress-body").textContent = "running...";
  const res = await fetch("/demo/public-cases");
  const data = await res.json();
  $("regress-body").innerHTML = `<p>${data.passed}/${data.total} passed</p>`
    + `<table><thead><tr><th>Case</th><th>Valid</th><th>Cost gap</th><th>Latency</th></tr></thead><tbody>`
    + data.cases.map(c => `<tr><td>${c.case_id}</td>
        <td><span class="pill ${c.validity === "PASS" ? "ok" : "bad"}">${c.validity}</span></td>
        <td>${fmt(c.cost_gap, 2)}</td><td>${fmt(c.latency_ms, 0)} ms</td></tr>`).join("")
    + `</tbody></table>`;
}

$("run").onclick = analyze;
$("sample").onclick = loadSample;
$("regress").onclick = regression;
loadSample();
</script>
</body>
</html>
"""

__all__ = ["DEMO_PAGE"]
