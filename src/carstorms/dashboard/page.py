"""The single-file dashboard page (HTML + CSS + vanilla JS), served at ``/``.

Kept as a Python string so it ships in the wheel/image with no package-data setup.
It fetches ``/api/dashboard.json`` and renders the cards, polling periodically.
"""

from __future__ import annotations

DASHBOARD_HTML = """<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>St. John, USVI — Conditions</title>
<style>
  :root {
    --bg:#0e1726; --card:#16213a; --card2:#1d2b49; --text:#e9eefb; --muted:#9bb0d3;
    --line:#26365c; --l0:#3b82f6; --l1:#9aa7bd; --l2:#eab308; --l3:#f97316;
    --l4:#ef4444; --l5:#a855f7; --good:#22c55e; --warn:#eab308; --bad:#ef4444;
  }
  * { box-sizing:border-box; }
  body { margin:0; background:var(--bg); color:var(--text);
    font:15px/1.45 system-ui,-apple-system,Segoe UI,Roboto,sans-serif; }
  header { padding:18px 16px 6px; }
  h1 { margin:0; font-size:20px; }
  .sub { color:var(--muted); font-size:13px; margin-top:2px; }
  main { padding:10px 12px 40px; max-width:1100px; margin:0 auto; }
  .grid { display:grid; gap:12px; grid-template-columns:repeat(auto-fill,minmax(260px,1fr)); }
  .card { background:var(--card); border:1px solid var(--line); border-radius:14px;
    padding:14px; }
  .card h2 { margin:0 0 8px; font-size:13px; text-transform:uppercase;
    letter-spacing:.04em; color:var(--muted); display:flex; justify-content:space-between; }
  .big { font-size:30px; font-weight:600; }
  .row { display:flex; justify-content:space-between; padding:3px 0; border-bottom:1px solid var(--line); }
  .row:last-child { border-bottom:0; }
  .muted { color:var(--muted); }
  .pill { display:inline-block; padding:1px 8px; border-radius:999px; font-size:12px; font-weight:600; }
  .hstrip { display:flex; gap:8px; overflow-x:auto; padding-bottom:4px; }
  .hcol { text-align:center; min-width:46px; font-size:12px; }
  .alerts { margin-bottom:12px; }
  .alert { border-left:5px solid var(--l3); background:var(--card2); border-radius:10px;
    padding:10px 12px; margin-bottom:8px; }
  .alert .t { font-weight:600; }
  .alert .rec { color:var(--muted); font-size:13px; white-space:pre-line; margin-top:4px; }
  .lvl0{border-color:var(--l0)} .lvl1{border-color:var(--l1)} .lvl2{border-color:var(--l2)}
  .lvl3{border-color:var(--l3)} .lvl4{border-color:var(--l4)} .lvl5{border-color:var(--l5)}
  .status-good{color:var(--good)} .status-warn{color:var(--warn)} .status-bad{color:var(--bad)}
  footer { color:var(--muted); font-size:12px; text-align:center; padding:8px; }
  a { color:#7db1ff; }
</style>
</head>
<body>
<header>
  <h1>🌴 St. John, USVI — Conditions</h1>
  <div class="sub" id="updated">Loading…</div>
</header>
<main>
  <div class="alerts" id="alerts"></div>
  <div class="grid" id="grid"></div>
  <footer>CarStorms · data from NWS, NHC, USGS, Open-Meteo, EPA, NOAA · not a substitute for official warnings</footer>
</main>
<script>
const LVL = ["#3b82f6","#9aa7bd","#eab308","#f97316","#ef4444","#a855f7"];
const fmtT = s => { if(!s) return "—"; const d=new Date(s.length<=16? s+"Z":s);
  return isNaN(d)? s : d.toLocaleString([], {weekday:'short',hour:'2-digit',minute:'2-digit'}); };
const fmtTime = s => { if(!s) return "—"; const d=new Date(s.length<=16? s+"Z":s);
  return isNaN(d)? s : d.toLocaleTimeString([], {hour:'2-digit',minute:'2-digit'}); };
const num = (v,u="") => (v===null||v===undefined||v==="")? "—" : v+u;
const card = (title, extra, body) =>
  `<div class="card"><h2><span>${title}</span><span class="muted">${extra||""}</span></h2>${body}</div>`;
const row = (k,v) => `<div class="row"><span class="muted">${k}</span><span>${v}</span></div>`;

function renderAlerts(p){
  const el = document.getElementById('alerts');
  if(!p || !p.available || !p.items || !p.items.length){ el.innerHTML=""; return; }
  el.innerHTML = p.items.map(a => `
    <div class="alert lvl${a.level}" style="border-color:${LVL[a.level]}">
      <div class="t">${a.emoji||""} ${a.level_label}: ${a.title}</div>
      <div class="rec">${a.recommendation||""}</div>
    </div>`).join("");
}

function renderForecast(p){
  if(!p||!p.available) return card("Weather","offline","<div class='muted'>unavailable</div>");
  const c=p.current||{}; const h=(p.hourly||[]).slice(0,12);
  const strip = h.map(x=>`<div class="hcol"><div>${fmtTime(x.time)}</div>
    <div style="font-size:18px">${(x.weather||{}).emoji||""}</div>
    <div>${num(Math.round(x.temp))}°</div><div class="muted">${num(x.precip_prob,'%')}</div></div>`).join("");
  return card("Now & next 24h", fmtTime(c.time),
    `<div class="big">${(c.weather||{}).emoji||""} ${num(Math.round(c.temp))}°C</div>
     <div class="muted">${(c.weather||{}).label||""} · feels ${num(Math.round(c.feels_like))}° · wind ${num(Math.round(c.wind))} km/h</div>
     <div class="hstrip" style="margin-top:8px">${strip}</div>`);
}

function renderDaily(p){
  if(!p||!p.available||!p.daily) return "";
  const days=p.daily.map(d=>row(`${(d.weather||{}).emoji||""} ${fmtT(d.date).split(',')[0]}`,
    `${num(Math.round(d.temp_max))}° / ${num(Math.round(d.temp_min))}° · ${num(d.precip_prob,'%')}`)).join("");
  return card("7-day outlook","", days);
}

function renderUV(p){
  if(!p||!p.available) return card("UV index","offline","");
  const cls = (p.risk==='extreme'||p.risk==='very high')?'status-bad':(p.risk==='high'?'status-warn':'status-good');
  return card("UV index", p.risk||"",
    `<div class="big ${cls}">${num(p.today_max)}</div>
     <div class="muted">now ${num(p.now)} · ${p.risk} risk — protect 9am-4pm</div>`);
}

function renderAir(p){
  if(!p||!p.available) return card("Air quality","offline","");
  const a=p.us_aqi; const cls=(a>150)?'status-bad':(a>100?'status-warn':'status-good');
  return card("Air quality / dust","",
    `<div class="big ${cls}">${num(a)}</div><div class="muted">${p.category||""}</div>
     ${row("PM2.5",num(p.pm2_5,' µg/m³'))}${row("Dust",num(p.dust,' µg/m³'))}`);
}

function renderMarine(p){
  if(!p||!p.available) return card("Marine","offline","");
  let b = row("Waves", num(p.wave_height_m,' m')+" @ "+num(p.wave_period_s,'s'))
        + row("Swell", num(p.swell_height_m,' m'))
        + row("Sea temp", num(p.sea_surface_temp_c,'°C'));
  if(p.observed) b += row("Buoy waves", num(p.observed.wave_height_m,' m'));
  return card("Marine", p.observed?"+buoy":"model", b);
}

function renderTides(p){
  if(!p||!p.available) return card("Tides","offline","");
  const e=(p.events||[]).map(t=>row(`${t.type==='H'?'▲ High':'▼ Low'}`, `${fmtTime(t.time)} · ${num(t.height_ft,' ft')}`)).join("");
  return card("Tides","Lameshur Bay", e||"<div class='muted'>—</div>");
}

function renderSunMoon(p){
  if(!p) return "";
  const m=p.moon||{};
  return card("Sun & moon","",
    row("Sunrise",fmtTime(p.sunrise))+row("Sunset",fmtTime(p.sunset))+
    row("Moon",`${m.emoji||""} ${m.name||""} (${num(m.illumination_pct,'%')})`));
}

function renderTropical(p){
  if(!p) return "";
  if(!p.active||!p.active.length) return card("Tropical outlook","",`<div class="status-good">✓ ${p.note||"No active systems"}</div>`);
  return card("Tropical outlook", p.active.length+" active",
    p.active.map(s=>row(`${s.classification||""} ${s.name||""}`, num(s.intensity_kt,' kt'))).join(""));
}

function renderQuakes(p){
  if(!p||!p.available) return card("Earthquakes","offline","");
  if(!p.items.length) return card("Earthquakes","24h","<div class='status-good'>None nearby</div>");
  return card("Earthquakes (24h)", p.count,
    p.items.map(q=>row(`M${num(q.magnitude)}`, `${num(q.distance_km,' km')} · ${(q.place||'').slice(0,28)}`)).join(""));
}

function renderBeaches(p){
  if(!p||!p.available) return card("Beach water quality","offline","<div class='muted'>"+(p&&p.reason||"")+"</div>");
  if(!p.items.length) return card("Beach water quality","","<div class='muted'>No recent samples</div>");
  return card("Beach water quality", p.count+" beaches",
    p.items.slice(0,8).map(b=>{
      const ok = b.status!=='exceedance';
      return row((b.station_name||'').slice(0,26),
        `<span class="${ok?'status-good':'status-bad'}">${ok?'OK':'Advisory'}</span> ${num(b.value,' '+(b.unit||''))}`);
    }).join(""));
}

function renderTravel(p){
  if(!p||!p.available) return card("Travel","offline","");
  const a=p.airport||{};
  let b = row("STT airport", `${a.flight_category||"—"}`);
  (p.disruptions||[]).forEach(d=> b+=row(d.title, `<span class="status-warn">L${d.level}</span>`));
  if(!(p.disruptions||[]).length) b+=row("Ferry","<span class='status-good'>no reported disruption</span>");
  return card("Travel","STT / ferry", b);
}

function renderEvents(p){
  if(!p||!p.available||!p.items||!p.items.length) return card("What's on","",`<div class="muted">No curated events.</div>`);
  return card("What's on", p.count,
    p.items.slice(0,6).map(e=>row(e.title||"", e.location? `<span class="muted">${e.location}</span>`:fmtT(e.starts_at))).join(""));
}

function renderMoorings(p){
  if(!p||!p.available) return "";
  const cls = p.suitability==='good'?'status-good':(p.suitability==='marginal'?'status-warn':'status-bad');
  return card("Boating & moorings","",
    `<div>Conditions: <span class="${cls}">${(p.suitability||'unknown').toUpperCase()}</span></div>
     <div class="muted" style="font-size:13px;margin:6px 0">${(p.areas||[]).join(' · ')}</div>
     <div class="muted" style="font-size:12px">${p.note||""}</div>`);
}

function renderHealth(p){
  if(!p||!p.available) return "";
  return card("Data health","",
    (p.items||[]).map(s=>row(s.source, `<span class="${s.status==='ok'?'status-good':'status-bad'}">${s.status}</span> ${s.age_minutes!=null? s.age_minutes+'m':''}`)).join(""));
}

async function load(){
  try {
    const r = await fetch('/api/dashboard.json', {cache:'no-store'});
    const d = await r.json();
    if(d.status==='starting'){ document.getElementById('updated').textContent='Starting up…'; return; }
    const P = d.panels||{};
    renderAlerts(P.alerts);
    document.getElementById('grid').innerHTML = [
      renderForecast(P.forecast), renderUV(P.uv), renderMarine(P.marine), renderTides(P.tides),
      renderAir(P.air_quality), renderSunMoon(P.sun_moon), renderDaily(P.forecast),
      renderTropical(P.tropical), renderQuakes(P.earthquakes), renderBeaches(P.beaches),
      renderTravel(P.travel), renderEvents(P.events), renderMoorings(P.moorings), renderHealth(P.data_health)
    ].join("");
    document.getElementById('updated').textContent = 'Updated ' + fmtTime(d.generated_at) + ' · auto-refreshes';
  } catch(e) {
    document.getElementById('updated').textContent = 'Could not load data — retrying…';
  }
}
load();
setInterval(load, 120000);
</script>
</body>
</html>
"""
