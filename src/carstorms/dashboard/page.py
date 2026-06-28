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
  .foot { margin-top:8px; padding-top:6px; border-top:1px solid var(--line); font-size:11px; color:var(--muted); }
  .activity-card { grid-column:1 / -1; padding:16px; }
  .activity-periods { display:grid; grid-template-columns:repeat(2,minmax(0,1fr)); gap:12px; }
  .activity-period { background:var(--card2); border:1px solid var(--line); border-radius:11px; padding:12px; }
  .activity-period h3 { margin:0; font-size:17px; }
  .activity-summary { color:var(--muted); font-size:12px; margin:2px 0 10px; }
  .activity-label { margin:9px 0 5px; color:var(--muted); font-size:11px; font-weight:700; letter-spacing:.06em; text-transform:uppercase; }
  .activity-item { display:grid; grid-template-columns:minmax(125px,1fr) 42px; gap:3px 9px; padding:6px 0; border-bottom:1px solid var(--line); }
  .activity-item:last-child { border-bottom:0; }
  .activity-score { font-weight:700; text-align:right; font-variant-numeric:tabular-nums; }
  .activity-reason { grid-column:1 / -1; color:var(--muted); font-size:12px; }
  .score-excellent,.score-good { color:var(--good); }
  .score-fair { color:var(--warn); }
  .score-poor,.score-avoid { color:var(--bad); }
  .safety-note { margin-top:9px; border-left:3px solid var(--warn); padding:5px 8px; background:#2a2940; border-radius:4px; font-size:12px; }
  .score-details { margin-top:10px; color:var(--muted); font-size:12px; }
  .score-details summary { cursor:pointer; color:#b9c8e3; }
  .score-grid { display:grid; grid-template-columns:repeat(auto-fill,minmax(180px,1fr)); gap:3px 12px; margin-top:7px; }
  .power-timeline { margin-top:9px; padding-top:8px; border-top:1px solid var(--line); }
  .power-line { display:grid; grid-template-columns:minmax(100px,auto) minmax(0,1fr); gap:8px; padding:3px 0; font-size:13px; }
  .power-line > span:last-child { text-align:right; overflow-wrap:anywhere; }
  .wind-meter { height:8px; border-radius:999px; background:#273754; overflow:hidden; margin:8px 0; }
  .wind-meter > span { display:block; height:100%; border-radius:999px; }
  .band-green { color:var(--good); } .band-yellow { color:var(--warn); } .band-red { color:var(--bad); }
  .fill-green { background:var(--good); } .fill-yellow { background:var(--warn); } .fill-red { background:var(--bad); }
  .restaurant-card { grid-column:1 / -1; }
  .restaurant-grid { display:grid; grid-template-columns:repeat(auto-fill,minmax(245px,1fr)); gap:8px; }
  .restaurant-item { background:var(--card2); border:1px solid var(--line); border-radius:9px; padding:10px; }
  .restaurant-head { display:flex; align-items:flex-start; justify-content:space-between; gap:8px; }
  .restaurant-source { color:var(--muted); font-size:11px; margin-top:5px; }
  .gmp-attribution { color:#fff; font:400 12px Roboto,Arial,sans-serif; letter-spacing:normal; white-space:nowrap; }
  .disruption-note { border-left:3px solid var(--warn); background:#2a2940; padding:7px 9px; border-radius:4px; margin-bottom:9px; font-size:12px; }
  @media (max-width:650px) {
    .activity-periods { grid-template-columns:1fr; }
    .activity-card > h2 { flex-wrap:wrap; gap:2px 10px; }
    .activity-card > h2 > span:last-child { flex-basis:100%; }
  }
  a, .foot a { color:#7db1ff; text-decoration:none; }
  a:hover, .foot a:hover { text-decoration:underline; }
  #map { height:300px; border-radius:8px; margin-bottom:8px; }
  .leaflet-popup-content { color:#111; }
</style>
<link rel="stylesheet" href="https://unpkg.com/leaflet@1.9.4/dist/leaflet.css"/>
<script src="https://unpkg.com/leaflet@1.9.4/dist/leaflet.js"></script>
</head>
<body>
<header>
  <h1>🌴 St. John, USVI — Conditions</h1>
  <div class="sub" id="updated">Loading…</div>
</header>
<main>
  <div class="alerts" id="alerts"></div>
  <div class="grid" id="grid"></div>
  <div class="grid" id="trailgrid" style="margin-top:12px"></div>
  <footer>
    <div id="dh" style="margin-bottom:6px"></div>
    <a href="https://stj.fyi" style="font-weight:600">stj.fyi</a> · times in St. John local time (AST) · data from NWS, NHC, USGS, Open-Meteo, EPA, NOAA · not a substitute for official warnings
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
const fmtExact = s => { if(!s) return "—"; const d=new Date(s);
  return isNaN(d)? s : d.toLocaleString('en-US',{weekday:'short',month:'short',day:'numeric',year:'numeric',hour:'2-digit',minute:'2-digit',second:'2-digit',timeZone:TZ,timeZoneName:'short'}); };
const num = (v,u="") => (v===null||v===undefined||v==="")? "—" : v+u;
const card = (title, extra, body, foot) =>
  `<div class="card"><h2><span>${title}</span><span class="muted">${extra||""}</span></h2>${body}${foot||""}</div>`;
const row = (k,v) => `<div class="row"><span class="muted">${k}</span><span>${v}</span></div>`;
const link = (label,url) => url? `<a href="${url}" target="_blank" rel="noopener">${label}</a>` : label;
const esc = v => String(v==null?'':v).replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const riskBand = n => n>=60?'red':(n>=30?'yellow':'green');
// Details pages that hold more than the dashboard shows (only where one exists).
const LINKS = {
  forecast:'https://forecast.weather.gov/MapClick.php?lat=18.335&lon=-64.735',
  ndbc:'https://www.ndbc.noaa.gov/station_page.php?station=41052',
  tides:'https://tidesandcurrents.noaa.gov/stationhome.html?id=9751381',
  nhc:'https://www.nhc.noaa.gov/', usgs:'https://earthquake.usgs.gov/earthquakes/map/',
  wapa:'http://www.outageviewer.viwapa.vi:7575/', vipa:'https://www.viport.com/',
  moorings:'https://www.nps.gov/viis/planyourvisit/mooring-buoys.htm'
};
// Footer: "Source (linked if a details page exists) · as of <measured time AST>".
function srcFoot(label, url, t){
  if(!label && !t) return "";
  const src = label? link(label,url) : "";
  const when = t? ('as of '+fmtDT(t)) : "";
  return `<div class="foot">${src}${(src&&when)?' · ':''}${when}</div>`;
}
const clockTime = () => new Date().toLocaleTimeString('en-US',{hour:'2-digit',minute:'2-digit',second:'2-digit',timeZone:TZ});
const clockDate = () => new Date().toLocaleDateString('en-US',{weekday:'long',month:'long',day:'numeric',year:'numeric',timeZone:TZ});

function renderClock(){
  return `<div class="card"><h2><span>St. John time</span><span class="muted">AST</span></h2>
    <div class="big" id="clock-time">${clockTime()}</div>
    <div class="muted" id="clock-date">${clockDate()}</div></div>`;
}
function tick(){
  const t=document.getElementById('clock-time'), d=document.getElementById('clock-date');
  if(t) t.textContent=clockTime();
  if(d) d.textContent=clockDate();
}

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
     <div class="hstrip" style="margin-top:8px">${strip}</div>`,
    srcFoot('Open-Meteo / NWS', LINKS.forecast, c.time));
}

function windAssessment(x){
  if(!x) return '';
  return `<div style="margin-top:8px">
    <div class="row"><span>${x.label||''}</span><span class="band-${x.band||'green'}" style="font-weight:700">${num(x.severity)}/100</span></div>
    <div class="wind-meter"><span class="fill-${x.band||'green'}" style="width:${Math.max(0,Math.min(100,x.severity||0))}%"></span></div>
    <div class="muted" style="font-size:12px">${num(x.speed_kmh,' km/h')} sustained · ${num(x.gust_kmh,' km/h')} gusts · ${x.direction||'unknown'} ${x.direction_deg!=null?'('+x.direction_deg+'°)':''}</div>
    <div style="font-size:12px;margin-top:4px">${x.advice||''}</div>
    ${x.alert_note?`<div class="status-warn" style="font-size:12px;margin-top:3px">⚠ ${x.alert_note}</div>`:''}
  </div>`;
}

function renderWind(p){
  if(!p||!p.available) return card("Wind & outdoor impact","offline",`<div class="muted">${(p&&p.reason)||''}</div>`);
  const periods=(p.periods||[]).map(x=>`<div style="padding:6px 0;border-bottom:1px solid var(--line)">
    <div style="display:flex;justify-content:space-between;gap:8px"><span>${x.label} <span class="muted">${x.time}</span></span><span class="band-${x.band}" style="font-weight:700">${x.severity}/100 · ${x.band}</span></div>
    <div class="muted" style="font-size:12px">${num(x.speed_kmh,' km/h')} · gust ${num(x.gust_kmh,' km/h')} · ${x.direction}</div></div>`).join('');
  return card("Wind & outdoor impact",fmtTime(p.time),windAssessment(p.current)+periods,
    `<div class="foot">${p.method||''}</div>`);
}

function renderDaily(p){
  if(!p||!p.available||!p.daily) return "";
  const days=p.daily.map(d=>row(`${(d.weather||{}).emoji||""} ${fmtDay(d.date)}`,
    `${num(Math.round(d.temp_max))}° / ${num(Math.round(d.temp_min))}° · 🌧️${num(d.precip_prob,'%')}`)).join("");
  return card("7-day outlook","🌧️% = rain chance", days,
    srcFoot('Open-Meteo / NWS', LINKS.forecast, (p.daily[0]||{}).date));
}

function activityItem(a){
  const why=(a.reasons||[]).join(' · ');
  return `<div class="activity-item"><span>${a.emoji||''} ${a.name||''}</span>
    <span class="activity-score score-${a.rating||'fair'}">${num(a.score)}</span>
    <span class="activity-reason">${why}</span></div>`;
}

function renderActivities(p){
  if(!p||!p.available) return card("Today's activity guide","offline",`<div class="muted">${(p&&p.reason)||'Forecast inputs unavailable'}</div>`);
  const periods=(p.periods||[]).map(x=>{
    const best=(x.best||[]).map(activityItem).join('');
    const caution=(x.caution||[]).length ? (x.caution||[]).map(activityItem).join('')
      : '<div class="status-good" style="font-size:13px">No activity falls below the 55-point caution threshold.</div>';
    const all=(x.all||[]).map(a=>`<div class="row"><span>${a.emoji||''} ${a.name||''}</span><span class="score-${a.rating||'fair'}">${a.score} · ${a.rating}</span></div>`).join('');
    return `<section class="activity-period">
      <h3>${x.label} <span class="muted" style="font-size:12px;font-weight:400">${x.time} · ${x.confidence} confidence</span></h3>
      <div class="activity-summary">${x.summary||''}</div>
      <div class="activity-label">Best use of this period</div>${best}
      <div class="activity-label">Not a good time for</div>${caution}
      ${x.safety_note? `<div class="safety-note">⚠️ ${x.safety_note}</div>`:''}
      <details class="score-details"><summary>All activity scores</summary><div class="score-grid">${all}</div></details>
    </section>`;
  }).join('');
  return `<div class="card activity-card"><h2><span>Today's activity guide</span><span class="muted">0 worst · 100 ideal</span></h2>
    <div class="activity-periods">${periods}</div>
    <details class="score-details"><summary>How the scores are calculated</summary>
      <div style="margin-top:6px">${(p.methodology||[]).map(x=>`<div>• ${x}</div>`).join('')}</div>
    </details>
    <div class="foot">${p.method||''} Forecast guidance, not a substitute for beach flags, NPS notices, or captain/dive-operator judgment.</div></div>`;
}

function renderUV(p){
  if(!p||!p.available) return card("UV index","offline","");
  const cls = (p.risk==='extreme'||p.risk==='very high')?'status-bad':(p.risk==='high'?'status-warn':'status-good');
  return card("UV index", p.risk||"",
    `<div class="big ${cls}">${num(p.today_max)}</div>
     <div class="muted">now ${num(p.now)} · ${p.risk} risk — protect 9am-4pm</div>`,
    srcFoot('Open-Meteo', null, p.time));
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
     ${row("Aerosol depth",num(p.aerosol_optical_depth))}`,
    srcFoot('Open-Meteo Air Quality', null, p.time));
}

function renderMarine(p){
  if(!p||!p.available) return card("Marine","offline","");
  let b = row("Waves", num(p.wave_height_m,' m')+" @ "+num(p.wave_period_s,'s'))
        + row("Swell", num(p.swell_height_m,' m'))
        + row("Sea temp", num(p.sea_surface_temp_c,'°C'));
  if(p.observed) b += row("Buoy waves", num(p.observed.wave_height_m,' m'));
  return card("Marine", p.observed?"+buoy":"model", b,
    srcFoot('Open-Meteo model · NDBC 41052', LINKS.ndbc, p.time));
}

function renderTides(p){
  if(!p||!p.available) return card("Tides","offline","");
  const e=(p.events||[]).map(t=>row(`${t.type==='H'?'▲ High':'▼ Low'}`, `${fmtTime(t.time)} · ${num(t.height_ft,' ft')}`)).join("");
  return card("Tides","Lameshur Bay", e||"<div class='muted'>—</div>",
    srcFoot('NOAA Tides & Currents', LINKS.tides, null));
}

function renderSunMoon(p){
  if(!p) return "";
  const m=p.moon||{};
  return card("Sun & moon","",
    row("Sunrise",fmtTime(p.sunrise))+row("Sunset",fmtTime(p.sunset))+
    row("Moon",`${m.emoji||""} ${m.name||""} (${num(m.illumination_pct,'%')})`),
    srcFoot('Open-Meteo / computed', null, p.sunrise));
}

function renderTropical(p){
  if(!p) return "";
  if(!p.active||!p.active.length) return card("Tropical outlook","",`<div class="status-good">✓ ${p.note||"No active systems"}</div>`,
    srcFoot('NOAA NHC', LINKS.nhc, null));
  return card("Tropical outlook", p.active.length+" active",
    p.active.map(s=>row(`${s.classification||""} ${s.name||""}`, num(s.intensity_kt,' kt'))).join(""),
    srcFoot('NOAA NHC', LINKS.nhc, null));
}

function renderQuakes(p){
  if(!p||!p.available) return card("Earthquakes","offline","");
  if(!p.items.length) return card("Earthquakes (24h)","","<div class='status-good'>✓ None nearby</div>",
    srcFoot('USGS', LINKS.usgs, null));
  return card("Earthquakes (24h)", p.count+" recent",
    p.items.map(q=>{
      const mag=q.magnitude||0, mc=mag>=4.5?'status-bad':(mag>=3?'status-warn':'');
      return `<div style="padding:6px 0;border-bottom:1px solid var(--line)">
        <div><span class="${mc}" style="font-size:17px;font-weight:600">M${num(q.magnitude)}</span>
          <span class="muted"> · ${num(q.distance_km,' km')} away · ${fmtDT(q.time)}</span></div>
        <div class="muted" style="font-size:13px">${link(q.place||'', q.url)}</div></div>`;
    }).join(""),
    srcFoot('USGS', LINKS.usgs, null));
}

function renderBeaches(p){
  if(!p||!p.available) return card("Beach water quality","offline","<div class='muted'>"+(p&&p.reason||"")+"</div>");
  if(!p.items.length) return card("Beach water quality","","<div class='muted'>No recent samples</div>");
  return card("Beach water quality", p.count+" St. John beaches",
    p.items.map(b=>{
      const ok = b.status!=='exceedance';
      return `<div class="row"><span style="flex:1;padding-right:8px">${b.station_name||''}</span>
        <span style="white-space:nowrap"><span class="${ok?'status-good':'status-bad'}">${ok?'OK':'Advisory'}</span> ${num(b.value,' '+(b.unit||''))}</span></div>`;
    }).join(""),
    srcFoot('EPA Water Quality Portal', null, p.latest_sampled_at));
}

function renderPower(p){
  if(!p||!p.available) return card("Power (WAPA)","offline","");
  const sj=p.st_john||{}, st=p.st_thomas||{};
  const t=p.st_john_timeline||{};
  const duration = d => d? `${num(d.hours)} hours · ${num(d.days)} days · ${num(d.weeks)} weeks` : '—';
  const pline = (k,v) => `<div class="power-line"><span class="muted">${k}</span><span>${v}</span></div>`;
  let timeline = '<div class="power-timeline"><div class="muted" style="font-size:11px;text-transform:uppercase;letter-spacing:.04em">St. John continuity</div>';
  if(t.available){
    const ongoing=t.status==='outage';
    const sinceLabel=t.since_precision==='history_start'?'At least since':(ongoing?'Ongoing since':'Uninterrupted since');
    timeline += pline(sinceLabel,fmtExact(t.since));
    timeline += pline(ongoing?'Ongoing duration':'Uninterrupted for',duration(t.duration));
    if(t.last_outage){
      timeline += pline('Last failure',duration(t.last_outage.duration));
      timeline += pline('Failure began',`${fmtExact(t.last_outage.start)}${t.last_outage.start_precision==='reported'?'':' (first confirmed)'}`);
      timeline += pline('Power restored',`${fmtExact(t.last_outage.end)}${t.last_outage.end_precision==='reported'?'':' (first confirmed)'}`);
    } else if(!ongoing) {
      timeline += '<div class="muted" style="font-size:12px;margin-top:4px">No completed St. John failure exists in the available archive.</div>';
    }
  } else {
    timeline += `<div class="muted" style="font-size:12px;margin-top:4px">${t.reason||'Historical continuity unavailable.'}</div>`;
  }
  timeline += '</div>';
  return card("Power (WAPA)", p.updated_at? fmtTime(p.updated_at):"",
    `${row("St. John", `<span class="${sj.out>0?'status-bad':'status-good'}">${num(sj.out)} out</span>${sj.count? ' · '+sj.count+' outage(s)':''}`)}
     ${row("St. Thomas", `<span class="${st.out>0?'status-warn':'status-good'}">${num(st.out)} out</span>${st.count? ' · '+st.count+' outage(s)':''}`)}
     ${row("Territory", `${num(p.territory_out)} out of ${num(p.customers_served)}`)}${timeline}`,
    srcFoot('WAPA outage viewer', LINKS.wapa, p.updated_at));
}

function renderRestaurants(p){
  if(!p||!p.available) return card("Restaurants today","offline","");
  const d=p.disruption||{};
  const warning=(d.notes||[]).length? `<div class="disruption-note band-${d.level||'yellow'}">⚠ ${(d.notes||[]).join(' ')}</div>`:'';
  const items=(p.items||[]).map(x=>{
    const statusClass=['open_now','verified_update'].includes(x.status)?'status-good':(['closed','closed_today','scheduled_closed_today'].includes(x.status)?'status-bad':'status-warn');
    const checked=x.checked_at? ` · checked ${fmtDT(x.checked_at)}`:(x.schedule_reviewed_on?` · schedule reviewed ${x.schedule_reviewed_on}`:'');
    const contact=`${x.official_url?link('official',x.official_url):''}${x.maps_url?' · '+link('map',x.maps_url):''}${x.phone?' · <a href="tel:'+x.phone+'">'+x.phone+'</a>':''}`;
    const gmp=x.source_tier==='google_current_hours'?'<span class="gmp-attribution" translate="no">Google Maps</span> ':'';
    const attrs=(x.attributions||[]).map(a=>a.providerUri?link(a.provider||'data provider',a.providerUri):(a.provider||'')).filter(Boolean).join(' · ');
    return `<div class="restaurant-item">
      <div class="restaurant-head"><span><strong>${x.name}</strong><br><span class="muted" style="font-size:12px">${x.area||''}</span></span><span class="${statusClass}" style="text-align:right;font-weight:700;font-size:12px">${x.status_label||''}</span></div>
      <div style="margin-top:7px">Today: <strong>${x.hours_today||'—'}</strong>${x.special_hours?' <span class="pill status-warn">special hours</span>':''}</div>
      ${x.note?`<div class="muted" style="font-size:12px;margin-top:4px">${x.note}</div>`:''}
      <div class="restaurant-source">${gmp}${x.source_label||''}${checked}${attrs?'<br>Data: '+attrs:''}<br>${contact}</div>
    </div>`;
  }).join('');
  return `<div class="card restaurant-card"><h2><span>Popular restaurants today</span><span class="muted">St. John local time</span></h2>${warning}
    <div class="restaurant-grid">${items}</div>
    <div class="foot">${p.policy||''}${p.live_source_available?'':' Add CARSTORMS_GOOGLE_PLACES_API_KEY for current/special Google hours.'}</div></div>`;
}

function renderTravel(p){
  if(!p||!p.available) return card("Travel","offline","");
  const a=p.airport||{};
  let b = row("✈️ STT airport", `${a.flight_category||"—"}`);
  (p.ferries||[]).forEach(f=> b+=`<div style="padding:5px 0;border-bottom:1px solid var(--line)">
      <div>⛴️ ${f.name}</div>
      <div class="muted" style="font-size:12px">next → Cruz Bay ${fmtDT(f.to_st_john)} · → St. Thomas ${fmtDT(f.to_st_thomas)}</div></div>`);
  (p.disruptions||[]).forEach(d=> b+=`<div class="row"><span class="status-warn">⚠ ${d.title}</span><span class="status-warn">L${d.level}</span></div>`);
  return card("Travel","next ferry / STT", b,
    srcFoot('NWS Aviation Weather · ferry timetable', LINKS.vipa, a.obs_time));
}

function renderAirport(p){
  if(!p||!p.available) return card("STT airport forecast","offline",`<div class="muted">Official airport inputs unavailable</div>`);
  const risk=p.risk||{}, ops=p.operations||{}, crowd=p.crowd||{}, weather=p.weather||{}, faa=p.faa||{};
  const score=risk.score==null?0:risk.score, band=riskBand(score);
  let b=`<div style="display:flex;align-items:baseline;justify-content:space-between;gap:10px">
      <span class="big band-${band}">${num(score)}/100</span><span class="band-${band}" style="font-weight:700;text-transform:capitalize">${esc(risk.label||'unknown')}</span></div>
    <div class="wind-meter"><span class="fill-${band}" style="width:${Math.max(0,Math.min(100,score))}%"></span></div>
    <div class="muted" style="font-size:12px">${esc(risk.confidence||'low')} confidence · transparent weather, FAA, flight and terminal-pressure model</div>`;
  if(ops.available){
    b+=row("Live flight window",`${num(ops.total_flights)} flights`);
    b+=row("Delayed 15+ min",`${num(ops.delayed_flights)}${ops.delay_rate_pct!=null?' · '+ops.delay_rate_pct+'% of known':''}`);
    b+=row("Average delay",ops.average_delay_minutes==null?'—':ops.average_delay_minutes+' min');
    b+=row("Cancellations",num(ops.cancelled_flights));
  } else {
    b+=`<div class="disruption-note" style="margin-top:9px">Live flight status is not enabled. The risk score currently uses official FAA and TIST weather data only.</div>`;
  }
  b+=row("TIST conditions",esc(weather.flight_category||'unknown'));
  if(crowd.available&&crowd.peak){
    b+=row("Terminal-pressure peak",`${fmtTime(crowd.peak.time)} · <span class="band-${riskBand(crowd.score||0)}">${esc(crowd.peak.level)}</span>`);
  }
  if((faa.local_events||[]).length) b+=`<div class="status-bad" style="font-size:12px;margin-top:7px">FAA: ${esc(faa.local_events[0].detail)}</div>`;
  (risk.reasons||[]).slice(0,3).forEach(x=> b+=`<div class="muted" style="font-size:12px;margin-top:5px">• ${esc(x)}</div>`);
  const flights=(p.next_flights||[]).filter(x=>x.direction==='departure').slice(0,5);
  if(flights.length){
    b+=`<div class="activity-label">Upcoming departures</div>`;
    flights.forEach(f=> b+=row(`${esc(f.ident)} → ${esc(f.other_airport||'—')}`,`${fmtTime(f.scheduled_at)}${f.cancelled?' · <span class="status-bad">cancelled</span>':(f.delayed?' · <span class="status-warn">+'+num(f.delay_minutes)+' min</span>':'')}`));
  }
  return card("STT airport forecast",`${esc(risk.label||'unknown')} disruption risk`,b,
    `<div class="foot">${link('Independent JSON API','/api/airport.json')} · ${link('FAA NAS Status','https://nasstatus.faa.gov/')} · ${link('Aviation Weather','https://aviationweather.gov/')}<br>Terminal pressure is modeled, not a live TSA wait time.</div>`);
}

function renderNPS(p){
  if(!p||!p.available) return card("National Park","",`<div class='muted'>${(p&&p.reason)||'unavailable'}</div>`);
  let b = "";
  if(p.hours_today) b += row("Hours today", p.hours_today);
  else if(p.hours_description) b += row("Hours", p.hours_description);
  if(p.weather_info) b += `<div class="muted" style="font-size:13px;margin:6px 0">${p.weather_info}</div>`;
  (p.alerts||[]).forEach(a=> b += `<div class="row"><span class="status-warn" style="padding-right:8px">${a.category||'Alert'}</span><span style="flex:1;text-align:right">${link(a.title||'', a.url)}</span></div>`);
  if(!(p.alerts||[]).length) b += `<div class="status-good" style="font-size:13px">✓ No park alerts</div>`;
  return card("Virgin Islands Nat'l Park","", b, srcFoot('NPS', p.url, null));
}

function renderSargassum(p){
  if(!p) return "";
  if(!p.available) return card("Sargassum","",
    `<div class="muted">${esc(p.reason||'No recent coastal or satellite estimate available.')}</div>`,
    srcFoot(p.source||'NOAA SIR / USF AFAI', p.region_url||p.source_url, null));
  const score=p.score, lv=p.risk_level||p.level||'unknown', band=riskBand(score||0);
  const age=p.age_hours==null?'age unavailable':(p.age_hours<24?'<24 hours old':(Math.round(p.age_hours)+' hours old'));
  let b=`<div style="display:flex;justify-content:space-between;align-items:baseline;gap:10px">
      <span class="big band-${band}">${score==null?'—':score+'/100'}</span><span class="band-${band}" style="font-weight:700;text-transform:capitalize">${esc(lv)}</span></div>
    <div class="wind-meter"><span class="fill-${band}" style="width:${Math.max(0,Math.min(100,score||0))}%"></span></div>
    <div class="muted" style="font-size:12px">${esc(p.confidence||'unknown')} · ${esc(age)}${p.source_date?' · NOAA '+esc(p.source_date):''}</div>
    <div style="font-size:12px;margin-top:6px">${esc(p.disclaimer||p.note||'')}</div>`;
  if(p.headline_beach) b+=row("Highest pressure",esc(p.headline_beach));
  const best=(p.best_choices||[]).filter(x=>x.score!=null).slice(0,4);
  if(best.length){
    b+=`<div class="activity-label">Lower-pressure choices</div>`;
    best.forEach(x=>b+=row(esc(x.name),`<span class="band-${riskBand(x.score)}">${x.score}/100 · ${esc(x.risk_level)}</span>${x.confidence==='Observed'?' · observed':''}`));
  }
  const high=(p.highest_pressure||[]).filter(x=>x.score!=null).slice(0,4);
  if(high.length){
    b+=`<details class="score-details"><summary>All highest-pressure beaches</summary>`;
    high.forEach(x=>b+=row(esc(x.name),`${x.score}/100${x.caricoos_adjustment?' · drift '+(x.caricoos_adjustment>0?'+':'')+x.caricoos_adjustment:''}`));
    b+=`</details>`;
  }
  const obs=(p.local_observations||[])[0];
  if(obs) b+=`<div class="status-good" style="font-size:12px;margin-top:7px">Observed ${fmtDT(obs.observed_at)} near ${esc(obs.beach_name)}: ${esc(obs.condition)}${(obs.photos||[])[0]?' · '+link('photo',(obs.photos||[])[0]):''}</div>`;
  const sources=[link(p.source||'NOAA SIR',p.region_url||p.source_url)];
  if(p.caricoos&&p.caricoos.available) sources.push(link('CARICOOS 48h trend',p.caricoos.source_url));
  if(p.observation_source_url) sources.push(link('Sargassum Watch',p.observation_source_url));
  return `<div class="card restaurant-card"><h2><span>Sargassum by beach</span><span class="muted">${esc(p.source||'')}</span></h2>${b}<div class="foot">${sources.join(' · ')}<br>${esc(p.note||'')}</div></div>`;
}

function renderWifi(){
  return card("Connectivity / Wi-Fi","St. John",
    `${row("Public library","Elaine I. Sprauve Library, Cruz Bay")}
     ${row("Park visitor center","V.I. Nat'l Park, Cruz Bay")}
     <div class="muted" style="font-size:12px;margin-top:6px">Many Cruz Bay & Coral Bay cafés/restaurants offer free Wi-Fi. Cell coverage is good in town, patchy on remote trails and beaches.</div>`,
    srcFoot('Local info', null, null));
}

// Famous St. John live webcams (external pages open in a new tab).
const WEBCAMS = [
  {name:'Cruz Bay (live)', url:'https://www.skylinewebcams.com/en/webcam/us-virgin-islands/saint-john/cruz-bay/cruz-bay.html'},
  {name:'Cruz Bay ferry dock', url:'https://www.cruisingearth.com/port-webcams/caribbean/st-john-us-virgin-islands/'},
  {name:'Lovango, Windmill Bar & cays', url:'https://greatexpectationsstj.com/webcam'},
  {name:'All St. John cams (20+)', url:'https://explorestj.com/webcams/'},
  {name:'More live cams (WebcamTaxi)', url:'https://www.webcamtaxi.com/en/virgin-islands/saint-john.html'},
  {name:'News of St. John cams', url:'https://newsofstjohn.com/webcams/'},
];
function renderWebcams(){
  const list = WEBCAMS.map(w=>`<div class="row"><span>📷 ${link(w.name, w.url)}</span></div>`).join("");
  return card("Webcams","St. John", list, srcFoot('Curated links', null, null));
}

function renderEvents(p){
  if(!p||!p.available||!p.items||!p.items.length) return "";  // hide when nothing curated
  return card("What's on", p.count,
    p.items.slice(0,6).map(e=>row(link(e.title||"", e.url), e.location? `<span class="muted">${e.location}</span>`:fmtDT(e.starts_at))).join(""),
    srcFoot('Curated notices', null, null));
}

function renderMoorings(p){
  if(!p||!p.available) return "";
  const cls = p.suitability==='good'?'status-good':(p.suitability==='marginal'?'status-warn':'status-bad');
  return card("Boating & moorings","",
    `<div>Conditions: <span class="${cls}">${(p.suitability||'unknown').toUpperCase()}</span></div>
     <div class="muted" style="font-size:13px;margin:6px 0">${(p.areas||[]).join(' · ')}</div>
     <div class="muted" style="font-size:12px">${p.note||""}</div>`,
    srcFoot('Open-Meteo (derived)', null, null));
}

function renderHealthFooter(p){
  if(!p||!p.available||!p.items||!p.items.length) return "";
  return 'Data freshness: ' + p.items.map(s=>`${s.source} ${s.status==='ok'?'✓':'✕'}${s.age_minutes!=null? ' '+s.age_minutes+'m':''}`).join(' · ');
}

function renderWildlife(p){
  if(!p||!p.available||!p.items||!p.items.length) return card("Wildlife sightings","offline","");
  const items = p.items.map(o=>`<a href="${o.url}" target="_blank" rel="noopener" style="display:flex;gap:8px;align-items:center;padding:5px 0;border-bottom:1px solid var(--line);color:inherit">
     ${o.photo? `<img src="${o.photo}" alt="" loading="lazy" style="width:42px;height:42px;border-radius:6px;object-fit:cover">`:''}
     <span style="flex:1"><div>${o.name}</div><div class="muted" style="font-size:12px">${o.observed_on||''} · ${(o.place||'').slice(0,30)}</div></span></a>`).join("");
  return card("Recent wildlife", p.count+" iNaturalist", items, srcFoot('iNaturalist', p.source_url, null));
}

// Popular St. John (V.I. National Park) trails — curated trailheads + stats.
const TRAILS = [
  {name:'Reef Bay Trail', lat:18.3389, lng:-64.7236, len:'2.4 mi one-way', diff:'Strenuous', high:'937 ft → sea level', note:'Petroglyphs & sugar mill ruins'},
  {name:'Ram Head Trail', lat:18.3035, lng:-64.7044, len:'1.0 mi', diff:'Moderate', high:'~200 ft', note:'Salt Pond Bay to cliffs'},
  {name:'Lind Point Trail', lat:18.3324, lng:-64.7948, len:'1.1 mi', diff:'Easy', high:'~160 ft', note:'Cruz Bay to Honeymoon Beach'},
  {name:'Cinnamon Bay Loop', lat:18.3475, lng:-64.7470, len:'1.1 mi', diff:'Easy', high:'flat', note:'Plantation ruins, self-guided'},
  {name:'Bordeaux Mountain', lat:18.3367, lng:-64.7100, len:'varies', diff:'Strenuous', high:'1,277 ft (island high point)', note:'Highest point on St. John'},
  {name:'Salt Pond Bay / Drunk Bay', lat:18.3060, lng:-64.7060, len:'0.5 mi', diff:'Easy', high:'sea level', note:'Beach & tide pools'},
];
function renderTrails(){
  const list = TRAILS.map(t=>row(`🥾 ${t.name}`, `<span class="muted" style="font-size:12px">${t.diff} · ${t.len} · ${t.high}</span>`)).join("");
  return `<div class="card" style="grid-column:1 / -1">
    <h2><span>Trails &amp; map</span><span class="muted">V.I. National Park</span></h2>
    <div id="map"></div>${list}
    <div class="foot"><a href="https://www.nps.gov/viis/planyourvisit/things2do.htm" target="_blank" rel="noopener">NPS trails</a> · map data © OpenStreetMap</div></div>`;
}
function initMap(){
  const el = document.getElementById('map');
  if(typeof L==='undefined' || !el || el._leaflet_id) return;  // Leaflet missing or already inited
  const map = L.map('map',{scrollWheelZoom:false}).setView([18.335,-64.735],12);
  L.tileLayer('https://tile.openstreetmap.org/{z}/{x}/{y}.png',{maxZoom:17,attribution:'© OpenStreetMap'}).addTo(map);
  TRAILS.forEach(t=> L.marker([t.lat,t.lng]).addTo(map)
    .bindPopup(`<b>${t.name}</b><br>${t.diff} · ${t.len}<br>High point: ${t.high}<br>${t.note}`));
}

async function load(){
  try {
    const r = await fetch('/api/dashboard.json', {cache:'no-store'});
    const d = await r.json();
    if(d.status==='starting'){ document.getElementById('updated').textContent='Starting up…'; return; }
    const P = d.panels||{};
    renderAlerts(P.alerts);
    document.getElementById('grid').innerHTML = [
      renderClock(),
      renderForecast(P.forecast), renderWind(P.wind), renderActivities(P.activities), renderUV(P.uv), renderSunMoon(P.sun_moon), renderDaily(P.forecast),
      renderMarine(P.marine), renderTides(P.tides), renderAir(P.air_quality),
      renderSargassum(P.sargassum), renderTropical(P.tropical), renderQuakes(P.earthquakes),
      renderBeaches(P.beaches), renderPower(P.power), renderRestaurants(P.restaurants), renderNPS(P.national_park),
      renderAirport(P.airport), renderTravel(P.travel), renderMoorings(P.moorings), renderWildlife(P.wildlife),
      renderWebcams(), renderWifi(), renderEvents(P.events)
    ].join("");
    document.getElementById('dh').innerHTML = renderHealthFooter(P.data_health);
    document.getElementById('updated').textContent = 'Updated ' + fmtTime(d.generated_at) + ' AST · auto-refreshes';
  } catch(e) {
    document.getElementById('updated').textContent = 'Could not load data — retrying…';
  }
}
document.getElementById('grid').innerHTML = renderClock();  // show the clock instantly
document.getElementById('trailgrid').innerHTML = renderTrails();  // static; render once
initMap();
setInterval(tick, 1000);
load();
setInterval(load, 120000);
</script>
</body>
</html>
"""
