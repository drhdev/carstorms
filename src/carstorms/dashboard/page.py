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
  <footer>
    <div id="dh" style="margin-bottom:6px"></div>
    CarStorms · times in St. John local time (AST) · data from NWS, NHC, USGS, Open-Meteo, EPA, NOAA · not a substitute for official warnings
  </footer>
</main>
<script>
const LVL = ["#3b82f6","#9aa7bd","#eab308","#f97316","#ef4444","#a855f7"];
const TZ = 'America/St_Thomas';  // all times shown in St. John local time (AST)
const fmtTime = s => { if(!s) return "—"; const d=new Date(s);
  return isNaN(d)? s : d.toLocaleTimeString('en-US',{hour:'2-digit',minute:'2-digit',timeZone:TZ}); };
const fmtDay = s => { if(!s) return "—"; const d=new Date(s);
  return isNaN(d)? s : d.toLocaleDateString('en-US',{weekday:'short',timeZone:TZ}); };
const fmtDT = s => { if(!s) return "—"; const d=new Date(s);
  return isNaN(d)? s : d.toLocaleString('en-US',{weekday:'short',hour:'2-digit',minute:'2-digit',timeZone:TZ}); };
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
  const days=p.daily.map(d=>row(`${(d.weather||{}).emoji||""} ${fmtDay(d.date)}`,
    `${num(Math.round(d.temp_max))}° / ${num(Math.round(d.temp_min))}° · 🌧️${num(d.precip_prob,'%')}`)).join("");
  return card("7-day outlook","🌧️% = rain chance", days);
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
  const dustCls = /elevated|high/.test(p.dust_label||"")?'status-warn':'muted';
  return card("Air quality / dust","",
    `<div class="big ${cls}">${num(a)}</div><div class="muted">US AQI · ${p.category||""}</div>
     ${row("PM2.5",num(p.pm2_5,' µg/m³'))}
     ${row("PM10",num(p.pm10,' µg/m³'))}
     ${row("Dust",`${num(p.dust,' µg/m³')} <span class="${dustCls}">${p.dust_label||''}</span>`)}
     ${row("Aerosol depth",num(p.aerosol_optical_depth))}`);
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
  if(!p.items.length) return card("Earthquakes (24h)","","<div class='status-good'>✓ None nearby</div>");
  return card("Earthquakes (24h)", p.count+" recent",
    p.items.map(q=>{
      const mag=q.magnitude||0, mc=mag>=4.5?'status-bad':(mag>=3?'status-warn':'');
      return `<div style="padding:6px 0;border-bottom:1px solid var(--line)">
        <div><span class="${mc}" style="font-size:17px;font-weight:600">M${num(q.magnitude)}</span>
          <span class="muted"> · ${num(q.distance_km,' km')} away · ${fmtDT(q.time)}</span></div>
        <div class="muted" style="font-size:13px">${q.place||''}</div></div>`;
    }).join(""));
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

function renderPower(p){
  if(!p||!p.available) return card("Power (WAPA)","offline","");
  const sj=p.st_john||{}, st=p.st_thomas||{};
  return card("Power (WAPA)", p.updated_at? fmtTime(p.updated_at):"",
    `${row("St. John", `<span class="${sj.out>0?'status-bad':'status-good'}">${num(sj.out)} out</span>${sj.count? ' · '+sj.count+' outage(s)':''}`)}
     ${row("St. Thomas", `<span class="${st.out>0?'status-warn':'status-good'}">${num(st.out)} out</span>${st.count? ' · '+st.count+' outage(s)':''}`)}
     ${row("Territory", `${num(p.territory_out)} out of ${num(p.customers_served)}`)}`);
}

function renderTravel(p){
  if(!p||!p.available) return card("Travel","offline","");
  const a=p.airport||{};
  let b = row("✈️ STT airport", `${a.flight_category||"—"}`);
  (p.ferry_routes||[]).forEach(f=> b+=row("⛴️ "+f.name, `<span class="muted" style="font-size:12px">${f.note||""}</span>`));
  (p.disruptions||[]).forEach(d=> b+=`<div class="row"><span class="status-warn">⚠ ${d.title}</span><span class="status-warn">L${d.level}</span></div>`);
  if(!(p.disruptions||[]).length) b+=`<div class="muted" style="font-size:12px;margin-top:4px">No reported disruptions. Live ferry status isn't published — check operators.</div>`;
  return card("Travel","STT airport / ferries", b);
}

function renderEvents(p){
  if(!p||!p.available||!p.items||!p.items.length) return "";  // hide when nothing curated
  return card("What's on", p.count,
    p.items.slice(0,6).map(e=>row(e.title||"", e.location? `<span class="muted">${e.location}</span>`:fmtDT(e.starts_at))).join(""));
}

function renderMoorings(p){
  if(!p||!p.available) return "";
  const cls = p.suitability==='good'?'status-good':(p.suitability==='marginal'?'status-warn':'status-bad');
  return card("Boating & moorings","",
    `<div>Conditions: <span class="${cls}">${(p.suitability||'unknown').toUpperCase()}</span></div>
     <div class="muted" style="font-size:13px;margin:6px 0">${(p.areas||[]).join(' · ')}</div>
     <div class="muted" style="font-size:12px">${p.note||""}</div>`);
}

function renderHealthFooter(p){
  if(!p||!p.available||!p.items||!p.items.length) return "";
  return 'Data freshness: ' + p.items.map(s=>`${s.source} ${s.status==='ok'?'✓':'✕'}${s.age_minutes!=null? ' '+s.age_minutes+'m':''}`).join(' · ');
}

async function load(){
  try {
    const r = await fetch('/api/dashboard.json', {cache:'no-store'});
    const d = await r.json();
    if(d.status==='starting'){ document.getElementById('updated').textContent='Starting up…'; return; }
    const P = d.panels||{};
    renderAlerts(P.alerts);
    document.getElementById('grid').innerHTML = [
      renderForecast(P.forecast), renderUV(P.uv), renderSunMoon(P.sun_moon), renderDaily(P.forecast),
      renderMarine(P.marine), renderTides(P.tides), renderAir(P.air_quality),
      renderTropical(P.tropical), renderQuakes(P.earthquakes), renderBeaches(P.beaches),
      renderPower(P.power), renderTravel(P.travel), renderEvents(P.events), renderMoorings(P.moorings)
    ].join("");
    document.getElementById('dh').innerHTML = renderHealthFooter(P.data_health);
    document.getElementById('updated').textContent = 'Updated ' + fmtTime(d.generated_at) + ' AST · auto-refreshes';
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
