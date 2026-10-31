// HoopLab front end: vanilla JS, no build step. Every view reads the model through the JSON API.
const $ = (s, el = document) => el.querySelector(s);
const $$ = (s, el = document) => [...el.querySelectorAll(s)];
const esc = (v) => String(v ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
const pct = (v) => (v == null ? "n/a" : `${Math.round(v * 100)}%`);
const trim = (t) => String(t ?? "").trim().replace(/[.。]+$/, "");
const signed = (v) => { const n = Math.round(v * 100); return n === 0 ? "0" : `${n > 0 ? "+" : "−"}${Math.abs(n)}`; };
const nf = new Intl.NumberFormat("en-US");
const dateFmt = new Intl.DateTimeFormat("en-GB", { day: "numeric", month: "short" });
const day = (iso) => (iso ? dateFmt.format(new Date(iso)) : "");
const first = (name) => String(name || "").trim().split(/\s+/)[0];
let TEAM = null, META = null, DRILLS = {}, VIEW = "today", PLAYER = null, OPP = null, FILM = null;

// Short labels for the ten skills; the model's long names stay in tooltips and reports.
const SHORT = { rim_finishing: "Rim", midrange: "Mid-range", three_point: "Three", free_throw: "Free throws",
  ball_security: "Ball security", playmaking: "Playmaking", on_ball_defense: "On-ball D", help_defense: "Help D",
  rebounding: "Rebounding", transition: "Transition" };
const GROUPS = [["scoring", "Scoring"], ["playmaking", "Playmaking"], ["defense", "Defense and boards"], ["athletic", "Effort"]];
// The same skills as a coach would say them in a sentence.
const PHRASE = { rim_finishing: "finishing at the rim", midrange: "the mid-range shot", three_point: "three-point shooting", free_throw: "free throws",
  ball_security: "taking care of the ball", playmaking: "creating for others", on_ball_defense: "on-ball defense", help_defense: "help defense",
  rebounding: "rebounding", transition: "getting back in transition" };
const cap = (t) => t.charAt(0).toUpperCase() + t.slice(1);
const short = (d) => SHORT[d] || META.dimensions[d]?.name || d;

const svg = (d) => `<svg class="i" viewBox="0 0 24 24" aria-hidden="true" fill="none" stroke="currentColor" stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round">${d}</svg>`;
const ICON = {
  today: svg('<rect x="3.5" y="5" width="17" height="15" rx="1.5"/><path d="M3.5 10h17M8 3v4M16 3v4"/>'),
  assistant: svg('<path d="M4 5.5h16v10H9l-5 4z"/><path d="M8 9.5h8M8 12.5h5"/>'),
  roster: svg('<circle cx="9" cy="8" r="3.2"/><path d="M3 19.5c.6-3.3 3-5 6-5s5.4 1.7 6 5"/><path d="M16 5.2a3 3 0 010 5.6M18 14.8c1.6.7 2.6 2.2 3 4.7"/>'),
  practice: svg('<circle cx="12" cy="13" r="7.5"/><path d="M12 9v4l2.5 2M10 2.5h4"/>'),
  homework: svg('<path d="M6 3.5h9l3 3v14H6z"/><path d="M9 11l2 2 4-4M9 17h6"/>'),
  opponents: svg('<path d="M5 5l6 6M11 5l-6 6"/><circle cx="16.5" cy="16.5" r="3.5"/>'),
  film: svg('<rect x="3" y="5" width="18" height="14" rx="1.5"/><path d="M10 9.5v5l4.5-2.5z"/>'),
  mic: svg('<rect x="9" y="3" width="6" height="11" rx="3"/><path d="M5.5 11a6.5 6.5 0 0013 0M12 17.5V21"/>'),
  send: svg('<path d="M5 12h13M13 6l6 6-6 6"/>'),
};
const VIEWS = [["today", "Home"], ["film", "Film"], ["roster", "Players"], ["practice", "Practice"],
  ["homework", "Homework"], ["opponents", "Opponents"], ["assistant", "Assistant"]];

async function api(path, opts = {}) {
  const init = { ...opts };
  if (opts.json !== undefined) { init.body = JSON.stringify(opts.json); init.headers = { "Content-Type": "application/json" }; }
  const r = await fetch(path, init);
  if (!r.ok) {
    let msg = r.statusText;
    try { const j = await r.json(); msg = typeof j.detail === "string" ? j.detail : JSON.stringify(j.detail); } catch {}
    toast(msg); throw new Error(msg);
  }
  return r.status === 204 ? null : r.json();
}
function toast(msg) {
  const t = $("#toast"); t.textContent = msg; t.classList.remove("hidden");
  clearTimeout(t._h); t._h = setTimeout(() => t.classList.add("hidden"), 3600);
}
const writtenBy = (src) => (src === "template" ? "Drafted from the numbers. Claude was offline, so this is the plain version." : "Written by Claude from HoopLab's numbers.");

// ---------------------------------------------------------------- shell
$("#nav").innerHTML = VIEWS.map(([k, label]) => `<button type="button" data-view="${k}">${label}</button>`).join("");
$$("#nav button").forEach((b) => b.addEventListener("click", () => go(b.dataset.view)));
function go(view, opts = {}) {
  VIEW = view;
  if (opts.player !== undefined) PLAYER = opts.player;
  $$("#nav button").forEach((b) => (b.dataset.view === view ? b.setAttribute("aria-current", "page") : b.removeAttribute("aria-current")));
  const main = $("#main");
  main.innerHTML = `<p class="loading">Loading…</p>`;
  RENDER[view]().catch((e) => { main.innerHTML = `<p class="empty">This page could not load: ${esc(e.message)}</p>`; });
  if (opts.focus !== false) main.focus({ preventScroll: true });
  window.scrollTo(0, 0);
}

async function loadTeams(select) {
  const teams = await api("/api/teams");
  const sel = $("#teamSelect");
  sel.innerHTML = teams.map((t) => `<option value="${t.id}">${esc(t.name)}</option>`).join("");
  if (select) sel.value = select;
  TEAM = sel.value ? Number(sel.value) : null;
  document.body.classList.toggle("bare", !TEAM);
  if (!TEAM) return firstRun();
  const t = teams.find((x) => x.id === TEAM);
  $("#teamMeta").textContent = `${t.players} player${t.players === 1 ? "" : "s"}${t.level ? ` · ${t.level}` : ""}`;
  syncLang(); go(VIEW, { focus: false });
}
$("#teamSelect").addEventListener("change", (e) => { TEAM = Number(e.target.value); CHAT_ID = null; PLAYER = null; OPP = null; loadTeams(TEAM); });
async function loadDemo() {
  const r = await api("/api/demo", { method: "POST" });
  toast("Demo team loaded: 8 players, 10 weeks of games and practices");
  VIEW = "today"; loadTeams(r.team_id);
}
$("#demoBtn").addEventListener("click", loadDemo);
$("#newTeamBtn").addEventListener("click", () => {
  modal(`<h2 id="modalTitle">New team</h2><form class="form-col" id="teamForm">
    <label class="field">Team name<input name="name" required autocomplete="off" placeholder="Hapoel Galil U16"></label>
    <div class="two"><label class="field">Level<input name="level" placeholder="U16 regional"></label><label class="field">Head coach<input name="coach"></label></div>
    <div><button class="btn">Create team</button></div></form>`, "narrow");
  $("#teamForm [name=name]").focus();
  $("#teamForm").addEventListener("submit", async (e) => {
    e.preventDefault();
    const t = await api("/api/teams", { method: "POST", json: Object.fromEntries(new FormData(e.target)) });
    closeModal(); VIEW = "roster"; loadTeams(t.id);
  });
});

$$(".seg [data-lang]").forEach((b) => b.addEventListener("click", async () => {
  if (!TEAM) return;
  await api(`/api/teams/${TEAM}/settings`, { method: "PUT", json: { language: b.dataset.lang } });
  setLang(b.dataset.lang);
  toast(b.dataset.lang === "he" ? "דיבריפים, דוחות והודעות לשחקנים ייכתבו בעברית" : "Debriefs, reports and player messages will be written in English");
}));
const setLang = (l) => $$(".seg [data-lang]").forEach((x) => x.setAttribute("aria-pressed", String(x.dataset.lang === l)));
const LANG = () => $(".seg [aria-pressed=true]")?.dataset.lang || "en";
async function syncLang() { if (TEAM) setLang((await api(`/api/teams/${TEAM}/settings`)).language || "en"); }

// Light and dark. The choice is kept on this device; the first visit follows the system.
const THEME = () => document.documentElement.dataset.theme || "dark";
function setTheme(t) {
  document.documentElement.dataset.theme = t; localStorage.setItem("hooplab-theme", t);
  $$("[data-theme-set]").forEach((b) => b.setAttribute("aria-pressed", String(b.dataset.themeSet === t)));
}
$$("[data-theme-set]").forEach((b) => b.addEventListener("click", () => setTheme(b.dataset.themeSet)));
$$("[data-theme-set]").forEach((b) => b.setAttribute("aria-pressed", String(b.dataset.themeSet === THEME())));
document.addEventListener("click", (e) => { const m = $("details.more[open]"); if (m && !m.contains(e.target)) m.open = false; });
$("#askBar").addEventListener("submit", (e) => { e.preventDefault(); const q = $("#askInput").value.trim(); if (!q || !TEAM) return; $("#askInput").value = ""; ask(q); });

// "Ask about this" from any page: opens the assistant with what the coach is looking at.
let PENDING_ASK = null;
function ask(question, context) { PENDING_ASK = { question, context }; go("assistant"); }
const askBtn = (label, q, ctx) => `<button type="button" class="btn quiet" data-ask="${esc(q)}" data-ctx="${esc(ctx)}">${esc(label)}</button>`;
function bindAsk(el) { $$("[data-ask]", el).forEach((b) => b.addEventListener("click", (e) => { e.stopPropagation(); closeModal(); ask(b.dataset.ask, b.dataset.ctx); })); }

// Dictation from the bench, Hebrew or English (browser speech recognition, where available).
const SR = window.SpeechRecognition || window.webkitSpeechRecognition;
const micButton = (target) => (SR ? `<button type="button" class="icon-btn" data-mic="${target}" aria-label="Dictate" title="Dictate">${ICON.mic}</button>` : "");
function bindMic(el) {
  if (!SR) return;
  $$("[data-mic]", el).forEach((b) => b.addEventListener("click", () => {
    const ta = $(b.dataset.mic);
    if (b._rec) { b._rec.stop(); return; }
    const rec = new SR(); rec.lang = LANG() === "he" ? "he-IL" : "en-US"; rec.continuous = true;
    rec.onresult = (e) => { for (let i = e.resultIndex; i < e.results.length; i++) if (e.results[i].isFinal) ta.value += (ta.value ? " " : "") + e.results[i][0].transcript; };
    rec.onend = () => { b._rec = null; b.classList.remove("on"); b.setAttribute("aria-pressed", "false"); };
    b._rec = rec; b.classList.add("on"); b.setAttribute("aria-pressed", "true"); rec.start();
  }));
}

// ---------------------------------------------------------------- dialog
let MODAL_RETURN = null;
function modal(html, size = "") {
  const m = $("#modal"), opening = m.classList.contains("hidden");
  if (opening) MODAL_RETURN = document.activeElement;
  $(".modal-box", m).className = `modal-box ${size}`;
  $("#modalBody").innerHTML = html;
  m.classList.remove("hidden");
  if (opening) $("#modalClose").focus();
}
function closeModal() {
  const m = $("#modal"); if (m.classList.contains("hidden")) return;
  const v = $("video", m); if (v) v.pause();
  m.classList.add("hidden");
  if (MODAL_RETURN && document.contains(MODAL_RETURN)) MODAL_RETURN.focus();
}
$("#modalClose").addEventListener("click", closeModal);
$("#modal").addEventListener("click", (e) => { if (e.target.id === "modal") closeModal(); });
document.addEventListener("keydown", (e) => {
  if ($("#modal").classList.contains("hidden")) return;
  if (e.key === "Escape") { e.preventDefault(); closeModal(); return; }
  if (e.key !== "Tab") return;
  const f = $$("#modal button, #modal a[href], #modal input, #modal select, #modal textarea, #modal video, #modal [tabindex]:not([tabindex='-1'])").filter((x) => !x.disabled && x.offsetParent);
  if (!f.length) return;
  if (e.shiftKey && document.activeElement === f[0]) { e.preventDefault(); f[f.length - 1].focus(); }
  else if (!e.shiftKey && document.activeElement === f[f.length - 1]) { e.preventDefault(); f[0].focus(); }
});

// ---------------------------------------------------------------- film: the clip player
const ptName = (k) => META.play_types[k] || k;
const KIND = { game: "Game", practice: "Practice", scrimmage: "Scrimmage" };
const TYPE_WORD = { shot: "Shot", pass: "Pass", turnover: "Turnover", touch: "Touch", creation: "Created shot", defense: "Defense", rotation: "Rotation", steal: "Steal", rebound: "Rebound", sprint: "Sprint back" };
const ZONE_WORD = { rim: "at the rim", mid: "mid-range", three: "from three", ft: "free throw" };
function clipLabel(c) {
  const what = `${TYPE_WORD[c.type] || c.type}${c.zone ? ` ${ZONE_WORD[c.zone] || c.zone}` : ""}`;
  const res = c.outcome == null ? "" : c.type === "shot" ? (c.outcome ? ", made" : ", missed") : c.outcome ? ", good" : ", bad";
  return `${c.player ? esc(first(c.player)) + ": " : ""}${esc(what)}${res}`;
}
function clipPlayer(title, clips, sub = "") {
  if (!clips.length) return toast("No film behind this yet. Upload video to a game and every number here becomes playable.");
  modal(`<h2 id="modalTitle">${esc(title)}</h2><p class="note">${clips.length} clip${clips.length > 1 ? "s" : ""}${sub ? ` · ${esc(sub)}` : ""}</p>
    <div class="clips"><video id="clipVideo" class="video" controls muted playsinline preload="auto"></video>
    <ol>${clips.map((c, i) => `<li><button type="button" data-i="${i}"><b>${i + 1}</b><span>${clipLabel(c)}${c.play_type ? ` · ${esc(ptName(c.play_type))}` : ""}</span>
      <span class="sub">${esc(c.session)}, ${c.t_start.toFixed(1)} to ${c.t_end.toFixed(1)} s</span></button></li>`).join("")}</ol></div>`);
  const v = $("#clipVideo"); let i = 0;
  const play = (k) => {
    i = k; const c = clips[i];
    $$("#modal .clips li button").forEach((el) => el.setAttribute("aria-current", String(Number(el.dataset.i) === i)));
    const start = () => { v.currentTime = c.t_start; v.play().catch(() => {}); };
    if (!v.src.endsWith(c.video_url)) { v.src = c.video_url; v.addEventListener("loadedmetadata", start, { once: true }); } else start();
  };
  v.addEventListener("timeupdate", () => { if (v.currentTime >= clips[i].t_end) { if (i + 1 < clips.length) play(i + 1); else v.pause(); } });
  $$("#modal .clips li button").forEach((el) => el.addEventListener("click", () => play(Number(el.dataset.i))));
  play(0);
}
async function openClips(title, params) {
  const q = new URLSearchParams(Object.entries(params).filter(([, v]) => v !== null && v !== undefined && v !== ""));
  clipPlayer(title, await api(`/api/teams/${TEAM}/clips?${q}`));
}
async function openPlaylist(id) { const pl = await api(`/api/playlists/${id}`); clipPlayer(pl.title, pl.clips, pl.note || ""); }

function playTypeTable(r, playable) {
  if (!r.play_types.length) return `<p class="empty">No play types tagged yet. Tag possessions in the film room (pick and roll, spot-up, post-up) and this table shows what scores.</p>`;
  const max = Math.max(...r.play_types.map((x) => x.ppp), 1.4);
  return `<div class="tbl"><table><thead><tr><th>Play type</th><th class="r">Share</th><th class="r">Pts per poss.</th><th class="hide-narrow"></th><th class="r">Turnovers</th></tr></thead><tbody>
    ${r.play_types.map((x) => `<tr ${playable ? `class="go" tabindex="0" data-pt="${x.play_type}" aria-label="Watch ${esc(x.name)} possessions"` : ""}>
      <td>${esc(x.name)}${x.play_type === r.best ? `<span class="tag up">best</span>` : x.play_type === r.worst ? `<span class="tag down">worst</span>` : ""}${x.reliable ? "" : `<span class="sub">${x.possessions} possessions, small sample</span>`}</td>
      <td class="r">${pct(x.frequency)}</td><td class="r"><b>${x.ppp.toFixed(2)}</b></td>
      <td class="hide-narrow" style="width:26%"><div class="ppp"><div class="b"><i style="width:${(x.ppp / max) * 100}%;background:${x.ppp >= r.overall_ppp ? "var(--ink)" : "var(--line-strong)"}"></i><s style="left:${(r.overall_ppp / max) * 100}%"></s></div></div></td>
      <td class="r">${pct(x.turnover_rate)}</td></tr>`).join("")}</tbody></table></div>
    <p class="note" style="margin-top:8px">${nf.format(r.possessions)} tagged possessions, ${r.overall_ppp?.toFixed(2)} points per possession overall (the thin line).${playable ? " Select a row to watch those possessions." : ""}</p>`;
}
function bindPlayTypeRows(el, title, params) {
  $$("[data-pt]", el).forEach((row) => {
    const open = () => openClips(`${title}: ${ptName(row.dataset.pt)}`, { ...params, play_type: row.dataset.pt });
    row.addEventListener("click", open);
    row.addEventListener("keydown", (e) => { if (e.key === "Enter" || e.key === " ") { e.preventDefault(); open(); } });
  });
}
function md(text) { // small, escaped Markdown subset for written reports
  return text.split("\n").map((l) => {
    const h = esc(l).replace(/\*\*(.+?)\*\*/g, "<b>$1</b>").replace(/(^|\s)_(.+?)_(\s|$)/g, "$1<i>$2</i>$3");
    if (/^### /.test(l)) return `<h3>${h.slice(4)}</h3>`;
    if (/^## /.test(l)) return `<h2>${h.slice(3)}</h2>`;
    if (/^# /.test(l)) return `<h1>${h.slice(2)}</h1>`;
    if (/^\s*[-*] /.test(l)) return `<li>${h.replace(/^\s*[-*] /, "")}</li>`;
    if (/^\s*\d+\. /.test(l)) return `<li>${h.replace(/^\s*\d+\. /, "")}</li>`;
    return h.trim() ? `<p>${h}</p>` : "";
  }).join("").replace(/(<li>.*?<\/li>)+/g, (m) => `<ul>${m}</ul>`);
}

// ---------------------------------------------------------------- charts
// One skill row: grey band = 80% interval, tick = expected for the position, dot = current estimate.
function skillRow(pid, name, k, s) {
  const x = (v) => `${(v * 100).toFixed(1)}%`;
  return `<button type="button" class="sk ${s.label}" data-sp="${pid}" data-dim="${k}" data-name="${esc(name)}"
      title="${esc(s.name)}: ${pct(s.mean)}, likely between ${pct(s.low)} and ${pct(s.high)}. Expected for the position ${pct(s.baseline)}. ${s.evidence} weighted observations."
      aria-label="${esc(s.name)} ${pct(s.mean)}, expected ${pct(s.baseline)}. Watch the clips.">
    <span class="lab">${esc(SHORT[k])}</span>
    <span class="rng"><span class="band" style="left:${x(s.low)};width:${x(Math.max(0.006, s.high - s.low))}"></span><span class="exp" style="left:${x(s.baseline)}"></span><span class="est" style="left:${x(s.mean)}"></span></span>
    <span class="v">${pct(s.mean)}${s.trend ? (s.trend > 0 ? ` <span class="up" aria-label="improving">↑</span>` : ` <span class="down" aria-label="slipping">↓</span>`) : ""}</span></button>`;
}
const skillKey = `<div class="key"><span><i class="d"></i>estimate</span><span><i class="b"></i>likely range</span><span><i class="e"></i>expected for the position</span></div>`;

// The shot chart: a half court in marker. Zone tint says above or below expectation; each zone plays its clips.
function shotChart(card) {
  const S = card.skills;
  const tint = (s) => {
    const g = (s.mean - s.baseline) / Math.max(0.05, s.baseline);
    const a = Math.min(0.32, 0.06 + Math.abs(g) * 0.5);
    return Math.abs(g) < 0.04 ? "transparent" : `color-mix(in srgb, var(--${g > 0 ? "good" : "bad"}) ${Math.round(a * 100)}%, transparent)`;
  };
  const zone = (k, shape, lx, ly, sy = 18) => `<g class="zone" tabindex="0" role="button" data-zone="${k}" aria-label="${esc(S[k].name)}: ${pct(S[k].mean)}, expected ${pct(S[k].baseline)}. Watch the shots.">
      ${shape.replace("/>", ` class="hit" style="fill:${tint(S[k])}"/>`)}
      <text class="zl" x="${lx}" y="${ly}" text-anchor="middle">${pct(S[k].mean)}</text>
      <text class="zs" x="${lx}" y="${ly + sy}" text-anchor="middle">${esc(SHORT[k])}, exp. ${pct(S[k].baseline)}</text></g>`;
  // 10 units per foot; basket at (250, 52.5); three-point arc 23.75 ft, corners at x = 30 and 470.
  return `<svg class="court" viewBox="0 0 500 380" role="group" aria-label="Shot chart for ${esc(card.player.name)}">
    <rect class="floor" x="0" y="0" width="500" height="380"/>
    ${zone("three_point", `<path d="M0 0H30V142A237.5 237.5 0 0 0 470 142V0H500V380H0Z"/>`, 250, 336)}
    ${zone("midrange", `<path d="M30 0V142A237.5 237.5 0 0 0 470 142V0H330V190H170V0Z"/>`, 100, 70)}
    ${zone("rim_finishing", `<rect x="170" y="0" width="160" height="190"/>`, 250, 118)}
    ${zone("free_throw", `<path d="M190 190A60 60 0 0 0 310 190Z"/>`, 250, 222, 40)}
    <path class="ln" d="M1 1H499V379H1Z M170 0V190H330V0 M190 190A60 60 0 0 0 310 190 M30 0V142A237.5 237.5 0 0 0 470 142V0 M220 40H280"/>
    <circle class="ln" cx="250" cy="52.5" r="7.5"/>
  </svg>`;
}
function progressChart(h, dims, colors, width = 560) {
  const W = Math.max(320, Math.round(width)), H = 220, L = 34, R = 10, T = 12, B = 26, n = h.dates.length;
  const x = (i) => L + (i * (W - L - R)) / Math.max(1, n - 1);
  const all = dims.flatMap((d) => h.series[d]);
  const lo = Math.max(0, Math.floor((Math.min(...all) - 0.05) * 10) / 10), hi = Math.min(1, Math.ceil((Math.max(...all) + 0.05) * 10) / 10);
  const y = (v) => T + (1 - (v - lo) / (hi - lo || 1)) * (H - T - B);
  const grid = [lo, (lo + hi) / 2, hi].map((v) => `<line x1="${L}" x2="${W - R}" y1="${y(v)}" y2="${y(v)}" stroke="var(--line)"/><text x="0" y="${y(v) + 4}">${Math.round(v * 100)}%</text>`).join("");
  const lines = dims.map((d, k) => `<polyline fill="none" style="stroke:${colors[k]}" stroke-width="2" stroke-linejoin="round" points="${h.series[d].map((v, i) => `${x(i).toFixed(1)},${y(v).toFixed(1)}`).join(" ")}"/>
    <circle cx="${x(n - 1)}" cy="${y(h.series[d][n - 1])}" r="3.5" style="fill:${colors[k]}"/>`).join("");
  const ticks = [0, Math.floor((n - 1) / 2), n - 1].map((i) => `<text x="${x(i)}" y="${H - 6}" text-anchor="middle">${day(h.dates[i])}</text>`).join("");
  return `<svg viewBox="0 0 ${W} ${H}" role="img" aria-label="Skill estimates week by week">${grid}${lines}${ticks}</svg>`;
}
const SERIES = ["var(--ink)", "var(--accent)", "var(--them)", "var(--good)", "var(--bad)", "var(--ink-faint)"];

// ---------------------------------------------------------------- first run (no team yet)
function firstRun() {
  $("#main").innerHTML = `<div class="first">
    <div>
      <div class="wordmark">HoopLab</div>
      <h1>Know every player before you draw up the week.</h1>
      <p class="lede">Bring your roster and film. HoopLab learns each player and plans practice with you.</p>
      <form id="startForm"><label class="sr-only" for="startName">Team name</label><input id="startName" name="name" required autocomplete="off" placeholder="Your team's name"><button class="btn">Start</button></form>
      <p class="or">Or <button type="button" class="btn quiet" id="startDemo">open a demo team</button> with ten weeks of games already tagged.</p>
    </div>
    <figure class="board glass" aria-hidden="true" style="margin:0">
      <svg viewBox="0 0 520 380">
        <rect class="floor" x="0" y="0" width="520" height="380" rx="16"/>
        <g class="ln"><path d="M20 24H500V356H20Z M180 24V224H340V24 M200 224A60 60 0 0 0 320 224 M40 24V144A240 240 0 0 0 480 144V24 M230 56H290"/><circle cx="260" cy="70" r="8"/></g>
        <path class="trail us draw" d="M262 316C300 312 330 296 350 264"/>
        <path class="trail us draw d2" d="M120 168C150 140 190 128 226 112"/>
        <path class="pass draw d3" d="M168 262C200 290 230 300 252 312"/>
        <path class="screen" d="M284 326L304 340"/>
        <g class="them"><circle cx="256" cy="300" r="13"/><text x="256" y="304.5">11</text><circle cx="306" cy="298" r="13"/><text x="306" y="302.5">15</text><circle cx="176" cy="226" r="13"/><text x="176" y="230.5">13</text><circle cx="396" cy="176" r="13"/><text x="396" y="180.5">12</text><circle cx="208" cy="148" r="13"/><text x="208" y="152.5">14</text></g>
        <g class="us"><circle cx="262" cy="340" r="13"/><text x="262" y="344.5">4</text><circle cx="296" cy="330" r="13"/><text x="296" y="334.5">33</text><circle cx="150" cy="250" r="13"/><text x="150" y="254.5">7</text><circle cx="420" cy="190" r="13"/><text x="420" y="194.5">23</text><circle cx="104" cy="182" r="13"/><text x="104" y="186.5">12</text></g>
        <circle class="ball" cx="274" cy="350" r="5.5"/>
      </svg>
      <figcaption>High pick and roll, weak-side flare. Every possession you tag becomes a clip you can replay from the numbers.</figcaption>
    </figure></div>`;
  $("#startDemo").addEventListener("click", loadDemo);
  $("#startForm").addEventListener("submit", async (e) => {
    e.preventDefault();
    const t = await api("/api/teams", { method: "POST", json: { name: e.target.name.value } });
    VIEW = "roster"; loadTeams(t.id);
  });
}

// ---------------------------------------------------------------- views
let CHAT_ID = null;
const SUGGESTIONS = [
  "Catch me up before practice: what changed since the last game?",
  "We play Maccabi North on Thursday. Plan tomorrow: 75 minutes, 9 players, one hoop, nothing too intense.",
  "Today Noam hit 4 of 6 threes and lost the ball twice under pressure. Daniel was late on help three times.",
  "תכין שיעורי בית לכל השחקנים לשבוע הקרוב",
  "Self-scout: which play types work for us, and what should we run more?",
];

// One row per player, best two edges each, at most four players.
function feature(list) {
  const by = new Map();
  for (const x of list) {
    if (!by.has(x.player_id)) by.set(x.player_id, { id: x.player_id, player: x.player, items: [] });
    const g = by.get(x.player_id); if (g.items.length < 2) g.items.push(x);
  }
  return [...by.values()].slice(0, 4);
}

const RENDER = {
  async today() {
    const [s, brief, pt, inbox] = await Promise.all([api(`/api/teams/${TEAM}/snapshot`), api(`/api/teams/${TEAM}/briefing`),
      api(`/api/teams/${TEAM}/play-types`), api(`/api/teams/${TEAM}/inbox`)]);
    const top = s.priorities[0];
    const maxNeed = Math.max(...s.priorities.map((p) => p.need), 0.001);
    const feed = inbox.map((i, n) => {
      const kind = { debrief: "Debrief", trend: "Trend", data: "Needs data", homework: "Homework" }[i.kind] || i.kind;
      return `<details ${n === 0 ? "open" : ""}><summary><span class="kind ${esc(i.kind)}">${kind}${i.at ? `<br>${day(i.at)}` : ""}</span><span class="t" dir="auto">${esc(i.title.replace(/^(debrief|trend)\s*:\s*/i, ""))}</span></summary>
        <div class="body" dir="auto">${esc(i.body).split("\n").filter(Boolean).map((l) => `<p>${l}</p>`).join("")}
          ${i.kind === "debrief" ? `<p class="by">${writtenBy(i.source)}</p>` : ""}
          <div class="actions">${i.ref?.session_id ? `<button type="button" class="btn quiet small" data-watch="${i.ref.session_id}" data-title="${esc(i.title)}">Review the film</button>` : ""}
          ${askBtn("Ask what to do about it", "What should we do about this?", `${i.title}: ${i.body}`.slice(0, 1500))}</div></div></details>`;
    }).join("");
    const dimRows = Object.entries(s.team_dimensions).map(([k, d]) => {
      const lo = Math.min(d.mean, d.baseline), hi = Math.max(d.mean, d.baseline), c = d.gap >= 0 ? "var(--good)" : "var(--bad)";
      return `<div class="lab" title="${esc(d.name)}">${esc(SHORT[k])}</div><div class="track"><span class="gap" style="left:${lo * 100}%;width:${(hi - lo) * 100}%;background:${c};opacity:.35"></span><span class="exp" style="left:${d.baseline * 100}%"></span><span class="dot" style="left:${d.mean * 100}%;background:${c}"></span></div><div class="val ${d.gap >= 0 ? "up" : "down"}">${signed(d.gap)}${Math.round(d.gap * 100) ? "%" : ""}</div>`;
    }).join("");
    $("#main").innerHTML = `<div class="view">
      <header class="page-head"><p class="kicker">${esc(s.team.name)}</p><h1>${top ? `This week, work on <em>${esc(PHRASE[top.dimension] || top.name.toLowerCase())}</em>.` : "Add a game to see where the team stands."}</h1>
        <p class="lede">${s.players.length} players and ${nf.format(s.data_coverage.events)} tagged events so far${s.trends.length ? `. ${s.trends.length === 1 ? "One clear trend" : `${s.trends.length} clear trends`} in the last three weeks` : ""}.</p></header>
      <div class="split">
        <section aria-labelledby="hFeed"><h2 id="hFeed">Debriefs and alerts</h2>
          <div class="feed">${feed || `<p class="empty">Nothing new. A debrief lands here after every game or practice you add.</p>`}</div></section>
        <aside class="stack">
          <section aria-labelledby="hNeed"><h2 id="hNeed">Practice priorities</h2>
            <ol class="needs">${s.priorities.map((p) => `<li><span>${esc(cap(PHRASE[p.dimension] || p.name))}</span><span class="bar"><i style="width:${(p.need / maxNeed) * 100}%"></i></span></li>`).join("")}</ol></section>
          <section aria-labelledby="hUse"><h2 id="hUse">Players to feature</h2>
            <ul class="plain">${feature(s.exploit).map((g) => `<li><button type="button" class="row" data-player="${g.id}">${esc(g.player)}<span class="sub">${g.items.map((x) => `${esc(x.name)} ${pct(x.mean)}, position expects ${pct(x.baseline)}`).join("; ")}</span></button></li>`).join("") || `<li class="soft">Not enough data yet.</li>`}</ul></section>
          <section><details class="brief"><summary>Practice briefing</summary><div class="text" dir="auto">${esc(brief.text)}</div><p class="note" style="margin-top:8px">${writtenBy(brief.source)}</p></details></section>
        </aside></div>
      <section aria-labelledby="hRoster"><h2 id="hRoster">Roster</h2>
        <div class="tbl"><table><thead><tr><th>#</th><th>Player</th><th class="hide-narrow">Pos.</th><th class="hide-narrow">Best right now</th><th>Work on</th><th class="r hide-narrow">Events</th></tr></thead><tbody>
        ${s.players.map((c) => `<tr class="go" tabindex="0" data-player="${c.player.id}" aria-label="Open ${esc(c.player.name)}"><td class="jersey">${esc(c.player.number ?? "")}</td><td class="nm">${esc(c.player.name)}</td><td class="hide-narrow">${esc(c.player.position)}</td>
          <td class="hide-narrow">${c.strengths.slice(0, 2).map((x) => `${esc(SHORT[x.dimension])} <span class="soft">${pct(x.mean)}</span>`).join(", ") || `<span class="soft">nothing confirmed yet</span>`}</td>
          <td>${c.focus.map((d) => esc(short(d))).join(", ") || `<span class="soft">n/a</span>`}</td><td class="r soft hide-narrow">${nf.format(c.events)}</td></tr>`).join("")}</tbody></table></div></section>
      <div class="split even">
        <section aria-labelledby="hDims"><h2 id="hDims">Team against positional expectation</h2>
          <div class="dots">${dimRows}</div><div class="key"><span><i class="d"></i>team average</span><span><i class="e"></i>expected for our positions</span></div></section>
        <section id="ptSec" aria-labelledby="hPt"><h2 id="hPt">Our play types</h2>${playTypeTable(pt, true)}</section>
      </div></div>`;
    const main = $("#main");
    $$("[data-player]", main).forEach((r) => {
      const open = () => go("roster", { player: Number(r.dataset.player) });
      r.addEventListener("click", open);
      if (r.tagName === "TR") r.addEventListener("keydown", (e) => { if (e.key === "Enter" || e.key === " ") { e.preventDefault(); open(); } });
    });
    $$("[data-watch]", main).forEach((b) => b.addEventListener("click", () => { FILM = Number(b.dataset.watch); go("film"); }));
    bindPlayTypeRows($("#ptSec"), "Our team", {});
    bindAsk(main);
  },

  async assistant() {
    const health = await api("/api/health");
    $("#main").innerHTML = `<div class="chat">
      <header class="page-head"><h1>Assistant</h1>
        <p class="lede">Claude, with your team's numbers, film tags, drills and homework at hand. It can plan, log what you saw, and write to players. Hebrew or English.</p>
        ${health.ai ? "" : `<p class="offline">Claude is not connected on this server. Set <code>ANTHROPIC_API_KEY</code> to talk to it; every other page works without it.</p>`}</header>
      <div class="log" id="log" aria-live="polite"></div>
      <div class="dock"><form id="chatForm"><label class="sr-only" for="chatText">Message</label><textarea id="chatText" name="m" dir="auto" rows="1" placeholder="Ask about the team, or tell it what happened today"></textarea>${micButton("#chatText")}<button class="btn" aria-label="Send">${ICON.send}</button></form>
        <p class="note" style="margin-top:6px">${health.ai ? "Claude Opus 5.5." : ""} <button type="button" class="btn quiet small" id="newChat">Start a new conversation</button></p></div></div>`;
    const log = $("#log");
    const add = (role, text, extra = {}) => {
      const d = document.createElement("div");
      d.className = `m ${role}`; d.dir = "auto";
      if (role === "assistant" && !extra.wait) d.innerHTML = `<span class="who">HoopLab</span>`;
      d.appendChild(document.createTextNode(text));
      if (extra.about) d.insertAdjacentHTML("beforeend", `<span class="about">About: ${esc(extra.about.slice(0, 140))}${extra.about.length > 140 ? "…" : ""}</span>`);
      if (extra.actions?.length) {
        const a = document.createElement("div"); a.className = "acts";
        a.innerHTML = extra.actions.map((x) => x.playlist_id ? `<button type="button" class="btn line small" data-pl="${x.playlist_id}">Watch the playlist</button>`
          : `<span class="did">${esc(x.kind === "plan" ? "Practice plan saved" : x.kind.replace(/_/g, " "))}${x.stored ? `: ${x.stored} stored` : ""}${x.count ? `: ${x.count}` : ""}</span>`).join("");
        $$("[data-pl]", a).forEach((b) => b.addEventListener("click", () => openPlaylist(b.dataset.pl)));
        d.appendChild(a);
      }
      log.querySelector(".try-wrap")?.remove();
      log.appendChild(d); d.scrollIntoView({ block: "nearest" }); return d;
    };
    if (CHAT_ID) (await api(`/api/teams/${TEAM}/chats/${CHAT_ID}`)).forEach((m) => add(m.role, m.text));
    else log.innerHTML = `<div class="try-wrap"><p class="note">Things coaches ask it</p><ul class="try">${SUGGESTIONS.map((q) => `<li><button type="button" dir="auto" data-q="${esc(q)}">${esc(q)}</button></li>`).join("")}</ul></div>`;
    const send = async (text, context = null) => {
      if (!text.trim()) return;
      add("user", text, { about: context });
      const wait = add("assistant", "Reading the numbers…", { wait: true }); wait.classList.add("wait");
      try {
        const r = await api(`/api/teams/${TEAM}/chat`, { method: "POST", json: { message: text, chat_id: CHAT_ID, context } });
        CHAT_ID = r.chat_id; wait.remove(); add("assistant", r.reply || "(no reply)", { actions: r.actions });
      } catch (e) { wait.remove(); add("assistant", `That did not go through: ${e.message}`); }
    };
    const ta = $("#chatText");
    $("#chatForm").addEventListener("submit", (e) => { e.preventDefault(); const t = ta.value; ta.value = ""; send(t); });
    ta.addEventListener("keydown", (e) => { if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); $("#chatForm").requestSubmit(); } });
    $$("[data-q]", log).forEach((b) => b.addEventListener("click", () => send(b.dataset.q)));
    $("#newChat").addEventListener("click", () => { CHAT_ID = null; go("assistant"); });
    bindMic($("#main"));
    if (PENDING_ASK) { const p = PENDING_ASK; PENDING_ASK = null; send(p.question, p.context); } else ta.focus({ preventScroll: true });
  },

  async roster() {
    const s = await api(`/api/teams/${TEAM}/snapshot`);
    const cards = s.players;
    if (!cards.find((c) => c.player.id === PLAYER)) PLAYER = cards[0]?.player.id ?? null;
    $("#main").innerHTML = `<div class="split list">
      <nav aria-label="Players">
        <ul class="roster">${cards.map((c) => `<li><button type="button" data-pid="${c.player.id}" ${c.player.id === PLAYER ? `aria-current="true"` : ""}><span class="n">${esc(c.player.number ?? "")}</span><span class="nm">${esc(c.player.name)}</span><span class="pos">${esc(c.player.position)}</span></button></li>`).join("")}</ul>
        <details class="add" ${cards.length ? "" : "open"}><summary>Add a player</summary>
          <form class="form-col" id="addPlayer"><label class="field">Name<input name="name" required autocomplete="off"></label>
            <div class="three"><label class="field">Number<input name="number" type="number" min="0" max="99"></label><label class="field">Position<select name="position">${META.positions.map((p) => `<option>${p}</option>`).join("")}</select></label><label class="field">Height<input name="height_cm" type="number" placeholder="cm"></label></div>
            <div><button class="btn small">Add player</button></div></form></details>
        <details class="add"><summary>Import a roster file</summary>
          <form class="form-col" id="importRoster"><p class="note">CSV with columns name, number, position, height_cm. Existing numbers are updated.</p><input type="file" name="file" accept=".csv"><div><button class="btn line small">Import</button></div></form></details>
      </nav>
      <div id="sheet">${cards.length ? `<p class="loading">Loading…</p>` : `<p class="empty"><b>No players yet.</b> Add your first player on the left, or import the roster file you already keep.</p>`}</div></div>`;
    $$("[data-pid]").forEach((b) => b.addEventListener("click", () => {
      PLAYER = Number(b.dataset.pid);
      $$("[data-pid]").forEach((x) => (x === b ? x.setAttribute("aria-current", "true") : x.removeAttribute("aria-current")));
      playerSheet(cards.find((c) => c.player.id === PLAYER));
    }));
    $("#addPlayer").addEventListener("submit", async (e) => {
      e.preventDefault();
      const f = Object.fromEntries(new FormData(e.target));
      for (const k of ["number", "height_cm"]) f[k] = f[k] ? Number(f[k]) : null;
      const p = await api(`/api/teams/${TEAM}/players`, { method: "POST", json: f });
      toast(`${f.name} added`); PLAYER = p.id; loadTeams(TEAM);
    });
    $("#importRoster").addEventListener("submit", async (e) => {
      e.preventDefault(); const fd = new FormData(e.target);
      if (!fd.get("file")?.name) return toast("Choose a CSV file first");
      const r = await api(`/api/teams/${TEAM}/players.csv`, { method: "POST", body: fd });
      toast(`${r.added} added, ${r.updated} updated`); loadTeams(TEAM);
    });
    if (PLAYER) playerSheet(cards.find((c) => c.player.id === PLAYER));
  },

  async practice() {
    const opps = await api(`/api/teams/${TEAM}/opponents`);
    $("#main").innerHTML = `<div class="view">
      <header class="page-head"><h1>Plan tonight's practice.</h1><p class="lede">Built from what the team needs most, the next opponent, your court, and the drills you have voted up.</p></header>
      <div class="split plan-split">
        <form class="panel form-col" id="planForm"><h2>Practice constraints</h2>
          <div class="two"><label class="field">Starts at<input name="start" type="time" value="18:00"></label><label class="field">Minutes<input name="minutes" type="number" value="90" min="15" max="240"></label></div>
          <div class="two"><label class="field">Players<input name="players" type="number" value="10" min="1" max="30"></label><label class="field">Hoops<input name="hoops" type="number" value="2" min="0" max="12"></label></div>
          <div class="two"><label class="field">Court<select name="court"><option value="full">Full court</option><option value="half">Half court</option></select></label><label class="field">Hardest allowed<select name="max_intensity"><option value="high">High</option><option value="medium">Medium</option><option value="low">Low</option></select></label></div>
          <label class="field">Preparing for<select name="opponent_id"><option value="">No one in particular</option>${opps.map((o) => `<option value="${o.id}">${esc(o.name)}</option>`).join("")}</select></label>
          <fieldset style="border:0;padding:0;margin:0"><legend class="note" style="margin-bottom:6px">Also work on</legend>
            <div class="chips">${Object.keys(META.dimensions).map((k) => `<label><input type="checkbox" name="focus" value="${k}">${esc(SHORT[k])}</label>`).join("")}</div></fieldset>
          <div><button class="btn">Build the plan</button></div></form>
        <div id="planOut"><p class="empty">Set tonight's constraints and build the plan. Each block names who to watch and how you will know it worked.</p></div>
      </div></div>`;
    $("#planForm").addEventListener("submit", async (e) => {
      e.preventDefault();
      const fd = new FormData(e.target);
      const body = { minutes: +fd.get("minutes"), players: +fd.get("players"), hoops: +fd.get("hoops"), max_intensity: fd.get("max_intensity"),
        full_court: fd.get("court") !== "half", focus: fd.getAll("focus"), opponent_id: fd.get("opponent_id") ? +fd.get("opponent_id") : null };
      const p = await api(`/api/teams/${TEAM}/plan`, { method: "POST", json: body });
      let [hh, mm] = (fd.get("start") || "18:00").split(":").map(Number); let t = hh * 60 + mm;
      const clock = () => `${String(Math.floor(t / 60) % 24).padStart(2, "0")}:${String(t % 60).padStart(2, "0")}`;
      $("#planOut").innerHTML = `<h2>${p.total_minutes} minutes${p.opponent ? `, ready for ${esc(p.opponent)}` : ""}</h2>
        <p class="note">${p.unfilled_minutes ? `${p.unfilled_minutes} minutes left open for your own work. ` : ""}<span class="actions" style="display:inline-flex">${askBtn("Talk this plan through", "Explain this plan and adjust it if something doesn't fit our week.", `Practice plan: ${p.blocks.map((b) => `${b.minutes}' ${b.drill.name}`).join("; ")}`)}</span></p>
        <div class="plan">${p.blocks.map((b) => { const at = clock(); t += b.minutes; return `<div class="block">
          <div class="clock">${at}<small>${b.minutes} min</small></div>
          <div><h3>${esc(b.drill.name)}</h3><p class="why">${esc(b.why)}${b.preference > 1.05 ? ", one of your favourites" : ""}</p>
            <p class="setup">${esc(b.drill.setup)}</p>
            <p class="cue">Cue <b>“${esc(trim(b.drill.cue))}”</b>. It worked if: ${esc(trim(b.drill.metric))}.${b.focus_players.length ? ` Watch ${b.focus_players.map(esc).join(", ")}.` : ""}</p></div>
          <div class="vote"><button type="button" class="btn quiet small" data-d="${b.drill.id}" data-r="1">More like this</button><button type="button" class="btn quiet small" data-d="${b.drill.id}" data-r="-1">Less</button></div></div>`; }).join("")}</div>`;
      bindAsk($("#planOut"));
      $$("[data-d]", $("#planOut")).forEach((btn) => btn.addEventListener("click", async () => {
        await api(`/api/teams/${TEAM}/feedback`, { method: "POST", json: { drill_id: btn.dataset.d, rating: +btn.dataset.r, ran: +btn.dataset.r > 0 } });
        btn.parentElement.innerHTML = `<span class="note">${+btn.dataset.r > 0 ? "Noted, more like this" : "Noted, less of this"}</span>`;
      }));
    });
  },

  async homework() {
    const rows = await api(`/api/teams/${TEAM}/homework`);
    const open = rows.filter((h) => h.status !== "done").length;
    $("#main").innerHTML = `<div class="view">
      <header class="page-head"><h1>${rows.length ? `${open ? `<em>${open} item${open === 1 ? "" : "s"}</em> still open this week.` : "All homework is done."}` : "Give every player two things to work on."}</h1>
        <p class="lede">Two items per player from their biggest needs, each with their own possessions to watch first. Logged results count as evidence, at lower weight than games.</p>
        <div class="actions"><button type="button" class="btn" id="assign">Assign this week's homework</button>${rows.length ? `<span class="note">${open} open, ${rows.length - open} done</span>` : ""}</div></header>
      ${rows.length ? `<section aria-label="This week's homework"><div class="tbl"><table class="hw"><thead><tr><th>Player</th><th>Drill</th><th>Target</th><th>Due</th><th class="r">Result</th></tr></thead><tbody>
      ${rows.map((h, i) => `<tr><td class="nm">${i === 0 || rows[i - 1].player !== h.player ? esc(h.player) : ""}</td>
        <td>${esc(h.drill?.name)}<span class="sub">${esc(SHORT[h.dimension] || "")}: ${esc(h.drill?.setup)}</span>${h.playlist_id ? `<button type="button" class="btn quiet small" data-pl="${h.playlist_id}">Watch first</button>` : ""}</td>
        <td data-l="Target">${esc(h.target)}</td><td data-l="Due" style="white-space:nowrap">${day(h.due)}</td>
        <td class="r">${h.status === "done" ? `<span class="up">Done${h.attempts ? ` ${h.made}/${h.attempts}` : ""}</span>` : `<button type="button" class="btn line small" data-h="${h.id}">Log result</button>`}</td></tr>`).join("")}
      </tbody></table></div></section>` : `<p class="empty"><b>Nothing assigned yet.</b> Assign the week and every player gets two items from their own numbers.</p>`}</div>`;
    $("#assign").addEventListener("click", async () => {
      const r = await api(`/api/teams/${TEAM}/homework/assign`, { method: "POST" });
      toast(`${r.length} items assigned`); go("homework", { focus: false });
    });
    $$("[data-pl]").forEach((b) => b.addEventListener("click", () => openPlaylist(b.dataset.pl)));
    $$("[data-h]").forEach((b) => b.addEventListener("click", () => {
      const cell = b.parentElement, id = b.dataset.h;
      cell.innerHTML = `<form class="form-row" style="justify-content:end;flex-wrap:nowrap"><label class="sr-only" for="hr${id}">Made out of attempts</label>
        <input id="hr${id}" name="r" placeholder="32/50" style="width:88px" pattern="\\s*\\d+\\s*/\\s*\\d+\\s*|" title="Made/attempts, for example 32/50. Leave empty if it has no count."><button class="btn small">Save</button></form>`;
      const f = $("form", cell); f.r.focus();
      f.addEventListener("submit", async (e) => {
        e.preventDefault();
        const v = f.r.value.trim(); const [made, attempts] = v.includes("/") ? v.split("/").map(Number) : [null, null];
        await api(`/api/homework/${id}/complete`, { method: "POST", json: { made, attempts } });
        toast("Logged. The model counts it as evidence."); go("homework", { focus: false });
      });
    }));
  },

  async opponents() {
    const opps = await api(`/api/teams/${TEAM}/opponents`);
    if (!opps.find((o) => o.id === OPP)) OPP = opps[0]?.id ?? null;
    $("#main").innerHTML = `<div class="split list">
      <nav aria-label="Opponents">
        <ul class="roster">${opps.map((o) => `<li><button type="button" data-o="${o.id}" ${o.id === OPP ? `aria-current="true"` : ""} style="grid-template-columns:minmax(0,1fr)"><span class="nm">${esc(o.name)}</span></button></li>`).join("")}</ul>
        <details class="add" ${opps.length ? "" : "open"}><summary>Add an opponent</summary>
          <form class="form-col" id="addOpp"><label class="field">Name<input name="name" required autocomplete="off"></label><label class="field">What you know<textarea name="notes" rows="3" placeholder="Big lineup, presses after made baskets"></textarea></label><div><button class="btn small">Add</button></div></form></details>
      </nav><div id="oppOut">${opps.length ? `<p class="loading">Loading…</p>` : `<p class="empty"><b>No opponents yet.</b> Add one, then tag their possessions in the film room to build the scouting picture.</p>`}</div></div>`;
    $("#addOpp").addEventListener("submit", async (e) => {
      e.preventDefault();
      const o = await api(`/api/teams/${TEAM}/opponents`, { method: "POST", json: Object.fromEntries(new FormData(e.target)) });
      OPP = o.id; go("opponents", { focus: false });
    });
    $$("[data-o]").forEach((b) => b.addEventListener("click", () => {
      OPP = Number(b.dataset.o);
      $$("[data-o]").forEach((x) => (x === b ? x.setAttribute("aria-current", "true") : x.removeAttribute("aria-current")));
      opponentSheet(OPP);
    }));
    if (OPP) opponentSheet(OPP);
  },

  async film() {
    const [sessions, opps, health, players, inbox] = await Promise.all([api(`/api/teams/${TEAM}/sessions`), api(`/api/teams/${TEAM}/opponents`), api("/api/health"), api(`/api/teams/${TEAM}/players`), api(`/api/teams/${TEAM}/inbox`)]);
    const TAGS = [["shot", "rim", "Shot at the rim", "Made", "Missed"], ["shot", "mid", "Mid-range shot", "Made", "Missed"], ["shot", "three", "Three", "Made", "Missed"], ["shot", "ft", "Free throw", "Made", "Missed"],
      ["defense", "", "On-ball defense", "Stop", "Beaten"], ["rotation", "", "Help rotation", "On time", "Late"], ["rebound", "", "Rebound chance", "Won", "Lost"], ["sprint", "", "Getting back", "Sprinted", "Jogged"]];
    if (!sessions.find((x) => x.id === FILM)) FILM = (sessions.find((x) => x.has_video) || sessions[0])?.id ?? null;
    $("#main").innerHTML = `<div class="view">
      ${FILM ? `<div id="review"><p class="loading">Loading…</p></div>` : `<header class="page-head"><h1>Add your last game.</h1><p class="lede">Every game and practice you add gets a debrief, and each tagged moment becomes a clip you can replay from any number in HoopLab.</p></header>`}
      <section aria-labelledby="hSess"><h2 id="hSess">All sessions</h2>
        ${sessions.length ? `<div class="tbl"><table class="lib"><thead><tr><th>Date</th><th>Session</th><th class="r">Tagged</th><th class="r hide-narrow">Film</th></tr></thead><tbody>
        ${sessions.map((s, n) => `<tr class="go"${n >= 8 ? " hidden" : ""} tabindex="0" data-open="${s.id}" ${s.id === FILM ? `aria-current="true"` : ""} aria-label="Review ${esc(s.title || KIND[s.kind])}"><td style="white-space:nowrap">${day(s.date)}</td><td>${esc(s.title || KIND[s.kind])}<span class="sub">${KIND[s.kind] || esc(s.kind)}${s.status && s.status !== "analyzed" ? `, ${esc(s.status)}` : ""}</span></td><td class="r">${nf.format(s.events)}</td>
          <td class="r soft hide-narrow">${s.has_video ? "Film" : ""}</td></tr>`).join("")}</tbody></table></div>${sessions.length > 8 ? `<p style="margin-top:var(--s3)"><button type="button" class="btn quiet small" id="allSess">Show all ${sessions.length} sessions</button></p>` : ""}`
        : `<p class="empty"><b>No sessions yet.</b> Add your last game below, then upload its film or tag it from the bench.</p>`}</section>
      <div class="split even">
        <section aria-labelledby="hAdd"><h2 id="hAdd">New session</h2>
          <form class="form-col" id="newSession"><div class="two"><label class="field">Type<select name="kind"><option value="game">Game</option><option value="practice">Practice</option><option value="scrimmage">Scrimmage</option></select></label>
            <label class="field">Opponent<select name="opponent_id"><option value="">None</option>${opps.map((o) => `<option value="${o.id}">${esc(o.name)}</option>`).join("")}</select></label></div>
            <label class="field">Title<input name="title" placeholder="Away at Maccabi North"></label><div><button class="btn line">Add session</button></div></form>
          <h2 style="margin-top:var(--s10)">Data import</h2>
          <form class="form-col" id="upload"><label class="field">Into session<select name="session" id="sessPick">${sessions.map((s) => `<option value="${s.id}">${esc(s.title || KIND[s.kind])}, ${day(s.date)}</option>`).join("")}</select></label>
            <label class="field">Film, tracking file or tagged event log<input type="file" name="file" accept=".mp4,.mov,.avi,.mkv,.csv,.json"></label><div><button class="btn line">Upload</button></div></form>
          <p class="note" style="margin-top:var(--s3)">${health.video_processing ? "Video is analysed on upload." : "Video is stored and playable. Automatic tracking needs the vision extra; until then add a tracking file (.json) or an event log (.csv)."}
            Event log columns: <code>player_number, type, outcome, zone, assist, opponent</code>, plus optional <code>play_type, t_start, t_end</code> to link each event to its clip.</p>
          <h2 style="margin-top:var(--s10)">Coach notes</h2>
          <p class="note" style="margin-bottom:var(--s2)">Write or dictate what you saw, in Hebrew or English. Claude turns it into tagged events for the session above.</p>
          <label class="sr-only" for="notesText">Coach notes</label>
          <textarea id="notesText" dir="auto" rows="4" placeholder="Noam 3 of 5 from three, two turnovers against the press. Ori did not sprint back twice. Their 12 owns the offensive glass."></textarea>
          <div class="actions" style="margin-top:var(--s2)"><button type="button" class="btn line" id="notesBtn">Turn into events</button>${micButton("#notesText")}</div>
          <details class="add" style="margin-top:var(--s5)"><summary>Read stills from the film</summary>
            <form class="form-col" id="filmForm"><p class="note">Upload frames from the game. Claude reads each play, tags events by jersey number and adds scouting notes.</p><input type="file" name="files" multiple accept="image/*,video/*"><label class="field">Our jersey colour<input name="our_color" placeholder="white"></label><div><button class="btn line small">Read the frames</button></div></form></details>
          <div id="aiOut" class="ai-out" aria-live="polite"></div></section>
        <section aria-labelledby="hTag"><h2 id="hTag">Live tagging</h2>
          <p class="note" style="margin-bottom:var(--s3)">Play the selected session's film and tag as it runs. Each tag keeps the five seconds before it as its clip. Without film, tags still count.</p>
          <div id="tagVideoWrap"></div>
          <div class="form-col" style="margin:var(--s4) 0"><div class="two"><label class="field">Player<select id="tagPlayer">${players.map((p) => `<option value="${p.id}">${esc(p.number ?? "")} ${esc(p.name)}</option>`).join("")}</select></label>
            <label class="field">Play type<select id="tagPlay"><option value="">Not set</option>${Object.entries(META.play_types).map(([k, v]) => `<option value="${k}">${esc(v)}</option>`).join("")}</select></label></div></div>
          <div class="tagger" id="tagBtns">${TAGS.map(([t, z, label, yes, no]) => `<span>${label}</span><button type="button" class="btn line small" data-t="${t}" data-z="${z}" data-ok="true">${yes}</button><button type="button" class="btn line small" data-t="${t}" data-z="${z}" data-ok="false">${no}</button>`).join("")}
            <span>Ball handling</span><button type="button" class="btn line small" data-t="creation" data-z="" data-ok="true">Created a shot</button><button type="button" class="btn line small" data-t="turnover" data-z="" data-ok="false">Turnover</button></div>
        </section></div></div>`;
    const main = $("#main");
    const sessById = Object.fromEntries(sessions.map((x) => [String(x.id), x]));
    const showTagVideo = () => { const sid = $("#sessPick")?.value, s = sessById[sid];
      $("#tagVideoWrap").innerHTML = s?.has_video ? `<video id="tagVideo" class="video" controls playsinline preload="metadata" src="/api/sessions/${sid}/video"></video>` : ""; };
    $("#sessPick").addEventListener("change", showTagVideo); showTagVideo();
    $("#allSess")?.addEventListener("click", (e) => { $$("tr[hidden]", main).forEach((r) => (r.hidden = false)); e.currentTarget.remove(); });
    $$("[data-open]", main).forEach((row) => {
      const open = () => {
        FILM = Number(row.dataset.open);
        $$("[data-open]", main).forEach((x) => (x === row ? x.setAttribute("aria-current", "true") : x.removeAttribute("aria-current")));
        filmReview(sessById[row.dataset.open], inbox, players); window.scrollTo({ top: 0, behavior: "smooth" });
      };
      row.addEventListener("click", open);
      row.addEventListener("keydown", (e) => { if (e.key === "Enter" || e.key === " ") { e.preventDefault(); open(); } });
    });
    if (FILM) filmReview(sessById[String(FILM)], inbox, players);
    $("#newSession").addEventListener("submit", async (e) => {
      e.preventDefault();
      const f = Object.fromEntries(new FormData(e.target)); f.opponent_id = f.opponent_id ? Number(f.opponent_id) : null;
      await api(`/api/teams/${TEAM}/sessions`, { method: "POST", json: f }); toast("Session added"); go("film", { focus: false });
    });
    $("#upload").addEventListener("submit", async (e) => {
      e.preventDefault();
      const fd = new FormData(e.target), file = fd.get("file"), sid = fd.get("session");
      if (!sid) return toast("Add a session first");
      if (!file || !file.name) return toast("Choose a file");
      if (file.name.endsWith(".json")) {
        const r = await api(`/api/sessions/${sid}/tracks`, { method: "POST", json: { tracks: JSON.parse(await file.text()), our_team: 1 } });
        toast(`${r.events_stored} events from the tracking file. The debrief is on Today.`);
      } else {
        const body = new FormData(); body.append("file", file);
        const r = await api(file.name.endsWith(".csv") ? `/api/sessions/${sid}/events.csv` : `/api/sessions/${sid}/video`, { method: "POST", body });
        toast(r.stored !== undefined ? `${r.stored} events stored` : r.detail || r.status);
      }
      go("film", { focus: false });
    });
    const aiOut = (r) => { if (!$("#aiOut")) return; $("#aiOut").innerHTML = `<p><b>${r.stored} events stored.</b></p>${r.observations?.length ? `<ul>${r.observations.map((o) => `<li dir="auto">${esc(o)}</li>`).join("")}</ul>` : ""}${r.unresolved?.length ? `<p class="soft">Could not place: ${r.unresolved.map(esc).join("; ")}</p>` : ""}`; };
    $("#notesBtn").addEventListener("click", async () => {
      const sid = Number($("#sessPick")?.value), notes = $("#notesText").value;
      if (!sid || !notes.trim()) return toast("Pick a session and write what you saw");
      $("#aiOut").textContent = "Reading your notes…";
      aiOut(await api(`/api/sessions/${sid}/notes`, { method: "POST", json: { notes } }));
    });
    $("#filmForm").addEventListener("submit", async (e) => {
      e.preventDefault();
      const sid = Number($("#sessPick")?.value), fd = new FormData(e.target);
      if (!sid) return toast("Add a session first");
      const colour = fd.get("our_color"); fd.delete("our_color");
      $("#aiOut").textContent = "Reading the frames…";
      aiOut(await api(`/api/sessions/${sid}/film${colour ? `?our_color=${encodeURIComponent(colour)}` : ""}`, { method: "POST", body: fd }));
    });
    bindMic(main);
    $$("#tagBtns button").forEach((b) => b.addEventListener("click", async () => {
      const sid = Number($("#sessPick")?.value);
      if (!sid) return toast("Add a session first");
      const ev = { type: b.dataset.t, player_id: Number($("#tagPlayer").value), outcome: b.dataset.ok === "true" };
      if (b.dataset.z) ev.zone = b.dataset.z;
      if ($("#tagPlay").value) ev.play_type = $("#tagPlay").value;
      const v = $("#tagVideo");
      if (v && v.currentTime > 0) { ev.t_start = Math.max(0, +(v.currentTime - 5).toFixed(2)); ev.t_end = +(v.currentTime + 1).toFixed(2); }
      await api(`/api/sessions/${sid}/events`, { method: "POST", json: [ev] });
      toast(`${$("#tagPlayer").selectedOptions[0].text.trim()}: ${b.previousElementSibling?.tagName === "SPAN" ? b.previousElementSibling.textContent : b.previousElementSibling.previousElementSibling.textContent}, ${b.textContent.toLowerCase()}${ev.t_start !== undefined ? ` at ${Math.round(v.currentTime)} s` : ""}`);
    }));
  },
};

// ---------------------------------------------------------------- film review: one session, its film and its moments
const PTS = { rim: 2, mid: 2, three: 3, ft: 1 };
const SHOT_WORD = { rim: "layup", mid: "mid-range jumper", three: "three", ft: "free throw" };
const NUM_WORD = ["No", "One", "Two", "Three", "Four", "Five", "Six", "Seven", "Eight", "Nine", "Ten"];
const clock = (t) => `${Math.floor(t / 60)}:${String(Math.floor(t % 60)).padStart(2, "0")}`;
const longDay = (iso) => new Intl.DateTimeFormat("en-GB", { day: "numeric", month: "long" }).format(new Date(iso));
const PLAY_ICON = '<svg viewBox="0 0 12 12" aria-hidden="true"><path d="M3 1.5v9l7.5-4.5z"/></svg>';
const PAUSE_ICON = '<svg viewBox="0 0 12 12" aria-hidden="true"><path d="M2.5 1.5h2.5v9H2.5zM7 1.5h2.5v9H7z"/></svg>';

// Events tagged at the same instant are one moment: a shot with its pass, a turnover with who got back.
function moments(clips) {
  const at = new Map();
  for (const c of clips) { const k = c.t_start.toFixed(1); if (!at.has(k)) at.set(k, []); at.get(k).push(c); }
  const passes = clips.filter((c) => c.type === "pass" && c.player);
  const out = [];
  for (const cs of at.values()) {
    const ours = (t) => cs.find((c) => c.type === t && c.player);
    const shot = ours("shot"), tov = ours("turnover"), reb = ours("rebound"), lead = shot || tov || reb;
    if (!lead) continue;
    const m = { t0: lead.t_start, t1: lead.t_end, player: lead.player, play: lead.play_type,
      jogged: cs.filter((c) => c.type === "sprint" && c.player && !c.outcome).map((c) => first(c.player)) };
    if (shot) {
      const from = passes.find((p) => p.t_start <= shot.t_start && shot.t_start - p.t_start < 3 && p.player !== shot.player);
      Object.assign(m, { kind: "shot", what: SHOT_WORD[shot.zone] || "shot", good: !!shot.outcome, result: shot.outcome ? "Made" : "Missed",
        sub: [m.play && ptName(m.play), from && `from ${first(from.player)}`].filter(Boolean).join(", ") });
    } else if (tov) {
      const stolen = cs.some((c) => c.type === "steal" && !c.player);
      Object.assign(m, { kind: "tov", what: stolen ? "turnover, stolen" : "turnover", good: false,
        result: m.jogged.length ? `${m.jogged.length} jogged back` : "Lost it", sub: [m.play && ptName(m.play)].filter(Boolean).join("") });
    } else {
      Object.assign(m, { kind: "reb", what: "rebound", good: !!reb.outcome, result: reb.outcome ? "Won it" : "Lost it", sub: "After a miss" });
    }
    out.push(m);
  }
  return out.sort((a, b) => a.t0 - b.t0);
}

async function filmReview(s, inbox, players) {
  const [r, clips] = await Promise.all([api(`/api/sessions/${s.id}/report`), s.has_video ? api(`/api/teams/${TEAM}/clips?session_id=${s.id}&limit=300`) : Promise.resolve([])]);
  if (FILM !== s.id || !$("#review")) return;
  const num = Object.fromEntries(players.map((p) => [p.name, p.number]));
  const ms = moments(clips);
  const deb = inbox.find((i) => i.kind === "debrief" && i.ref?.session_id === s.id);
  const sh = r.team.shooting;
  const fg = Object.entries(sh).filter(([z]) => z !== "ft").reduce((a, [, v]) => [a[0] + v.made, a[1] + v.attempts], [0, 0]);
  const pts = Object.entries(sh).reduce((a, [z, v]) => a + v.made * (PTS[z] || 0), 0);
  const three = sh.three || { made: 0, attempts: 0 };
  const tov = r.team.turnovers;
  const jog = ms.filter((m) => m.jogged.length);
  const title = s.title || KIND[s.kind];
  const oppShort = r.opponent ? r.opponent.split(" ")[0] : "";
  const kicker = `${esc(title)}${r.opponent && !title.includes(oppShort) ? `, vs ${esc(r.opponent)}` : ""}, ${longDay(s.date)}`;
  const second = jog.length ? `<em>${NUM_WORD[jog[0].jogged.length] || jog[0].jogged.length} players</em> jogged back after ${jog.length === 1 ? "a turnover" : `${jog.length} turnovers`}.`
    : tov ? `Gave the ball away <em>${tov} time${tov === 1 ? "" : "s"}</em>.` : `No turnovers.`;
  const head = fg[1] ? `Scored ${pts} on ${fg[0]} of ${fg[1]} shooting. ${second}` : `${nf.format(r.events)} moments tagged. ${second}`;
  const top = r.standouts[0];
  const facts = [[pts, "Points"], [`${fg[0]}/${fg[1]}`, "Field goals"], [`${three.made}/${three.attempts}`, "Threes"], [tov, `Turnover${tov === 1 ? "" : "s"}`], [nf.format(r.events), "Tagged moments"]];
  const debLines = deb ? deb.body.split("\n").filter(Boolean) : [];
  const ctx = `Session: ${title}${r.opponent ? ` vs ${r.opponent}` : ""}, ${day(s.date)}. ${debLines.join(" ")}`.slice(0, 1500);
  const factsHtml = `<div class="statrow">${facts.map(([v, l]) => `<div><b>${v}</b><span>${l}</span></div>`).join("")}</div>`;
  const standouts = r.standouts.length ? `<div class="tbl"><table><thead><tr><th>Player</th><th>Skill</th><th class="r">This session</th><th class="r">Expected</th></tr></thead><tbody>${r.standouts.map((x) => `<tr><td class="nm">${esc(x.player)}</td><td>${esc(SHORT[x.dimension] || x.name)}</td><td class="r ${x.z > 0 ? "up" : "down"}">${x.made}/${x.n}</td><td class="r soft">${pct(x.expected)}</td></tr>`).join("")}</tbody></table></div>` : `<p class="empty">Nobody was far from what the model expected.</p>`;
  $("#review").innerHTML = `
    <header class="page-head review-head"><div><p class="kicker">${kicker}</p><h1>${head}</h1></div>
      ${top ? `<p class="aside-fact">Furthest from expected<b>${esc(first(top.player))}, ${esc((SHORT[top.dimension] || top.name).toLowerCase())} ${top.made}/${top.n}</b></p>` : ""}</header>
    <div class="split film-grid">
      <section class="film-panel" aria-label="Film and numbers">
        ${s.has_video ? `<div class="screen">
          <video id="fv" playsinline muted preload="auto" src="/api/sessions/${s.id}/video"></video>
          <p class="now" id="fvNow" aria-live="polite"></p>
          <div class="bar"><button type="button" class="play" id="fvPlay" aria-label="Play">${PLAY_ICON}</button><span class="idx" id="fvIdx"></span>
            <div class="tl" id="fvTl" role="slider" tabindex="0" aria-label="Position in the film" aria-valuemin="0" aria-valuenow="0"><i class="ph" id="fvPh"></i></div>
            <span class="tm" id="fvTime">0:00</span></div></div>` : `<h2>Away from what the model expected</h2>${standouts}`}
        ${factsHtml}
      </section>
      <aside class="stack">
        <section class="coach" aria-labelledby="hCoach"><h2 id="hCoach">Assistant coach</h2>
          ${deb ? `<p class="said" dir="auto">${debLines.slice(0, 3).map(esc).join(" ")}</p>` : `<p class="said">No debrief for this session yet. Claude writes one from the tagged moments and what the model expected from each player.</p>`}
          <div class="acts">
            ${deb ? `<button type="button" class="act" data-ask="Plan the next practice around what this session showed." data-ctx="${esc(ctx)}">Plan the next practice from this</button>` : `<button type="button" class="act" id="writeDeb">Write the debrief</button>`}
            ${deb && debLines.length > 3 ? `<button type="button" class="act" id="readDeb">Read the full debrief</button>` : ""}
            <button type="button" class="act" data-ask="What stands out in this session, and what should I show the players?" data-ctx="${esc(ctx)}">Ask about this ${s.kind === "practice" ? "practice" : "game"}</button>
          </div>
          ${deb ? `<p class="by">${writtenBy(deb.source)}</p>` : ""}</section>
        ${s.has_video ? `<section class="cliplist" aria-labelledby="hClips"><div class="ch"><h2 id="hClips">Moments</h2>
            <div class="seg" role="group" aria-label="Show"><button type="button" data-f="all" aria-pressed="true">All</button><button type="button" data-f="shot" aria-pressed="false">Shots</button><button type="button" data-f="tov" aria-pressed="false">Turnovers</button><button type="button" data-f="reb" aria-pressed="false">Boards</button></div></div>
          <ol id="fvList">${ms.map((m, i) => `<li data-k="${m.kind}"><button type="button" class="mrow" data-m="${i}"><span class="n">${esc(num[m.player] ?? "")}</span>
            <span class="x"><b>${esc(first(m.player))}, ${esc(m.what)}</b><span>${esc(m.sub)}${m.sub ? " " : ""}<span class="r ${m.good ? "g" : "b"}">${esc(m.result)}</span></span></span><span class="q">${clock(m.t0)}</span></button></li>`).join("")}</ol></section>`
          : `<section aria-labelledby="hNoFilm"><h2 id="hNoFilm">No film for this session</h2><p class="note">Upload the video below and every moment you tag becomes a clip here.</p></section>`}
      </aside></div>`;
  const el = $("#review");
  bindAsk(el);
  $("#readDeb")?.addEventListener("click", () => modal(`<h2 id="modalTitle">${esc(title)}</h2><p class="note">${day(s.date)}. ${writtenBy(deb.source)}</p><div class="msg-out" dir="auto">${esc(deb.body)}</div>`, "narrow"));
  $("#writeDeb")?.addEventListener("click", async (e) => {
    e.currentTarget.disabled = true; e.currentTarget.textContent = "Writing the debrief…";
    await api(`/api/sessions/${s.id}/debrief?lang=${LANG()}`, { method: "POST" });
    filmReview(s, await api(`/api/teams/${TEAM}/inbox`), players);
  });
  if (!s.has_video) return;

  const v = $("#fv"), tl = $("#fvTl"), rows = $$(".mrow", el);
  let cur = -1;
  const dur = () => (Number.isFinite(v.duration) && v.duration > 0 ? v.duration : Math.max(1, ...ms.map((m) => m.t1)));
  const drawTicks = () => {
    $$(".tk", tl).forEach((t) => t.remove());
    const d = dur();
    for (let t = 0; t < d; t += 2) tl.insertAdjacentHTML("afterbegin", `<i class="tk minor" style="left:${(t / d) * 100}%"></i>`);
    ms.forEach((m) => tl.insertAdjacentHTML("afterbegin", `<i class="tk ${m.good ? "g" : "b"}" style="left:${(m.t0 / d) * 100}%"></i>`));
    tl.setAttribute("aria-valuemax", String(Math.round(d)));
  };
  const show = (i) => {
    if (i === cur) return; cur = i;
    if (!$("#fvNow")) return;
    rows.forEach((b) => b.setAttribute("aria-current", String(Number(b.dataset.m) === i)));
    const m = ms[i];
    $("#fvNow").innerHTML = m ? `<b>${num[m.player] != null ? `#${esc(num[m.player])} ` : ""}${esc(first(m.player))}</b>, ${esc(m.what)}, ${clock(m.t0)}` : "";
    $("#fvNow").hidden = !m;
    $("#fvIdx").textContent = m ? `${i + 1} of ${ms.length}` : `${ms.length} moments`;
  };
  const tick = () => {
    if (!$("#fvPh")) return;                      // the page changed under the video
    const t = v.currentTime, d = dur();
    $("#fvPh").style.left = `${Math.min(100, (t / d) * 100)}%`;
    $("#fvTime").textContent = clock(t);
    tl.setAttribute("aria-valuenow", String(Math.round(t))); tl.setAttribute("aria-valuetext", clock(t));
    let i = -1; ms.forEach((m, k) => { if (m.t0 <= t + 0.05) i = k; });
    show(i);
  };
  const setPlaying = () => { if (!$("#fvPlay")) return; const p = !v.paused; $("#fvPlay").innerHTML = p ? PAUSE_ICON : PLAY_ICON; $("#fvPlay").setAttribute("aria-label", p ? "Pause" : "Play"); };
  const seek = (t) => { v.currentTime = Math.max(0, Math.min(dur(), t)); tick(); };
  v.addEventListener("loadedmetadata", () => { drawTicks(); tick(); });
  v.addEventListener("timeupdate", tick);
  v.addEventListener("play", setPlaying); v.addEventListener("pause", setPlaying);
  $("#fvPlay").addEventListener("click", () => (v.paused ? v.play().catch(() => {}) : v.pause()));
  tl.addEventListener("click", (e) => { const b = tl.getBoundingClientRect(); seek(((e.clientX - b.left) / b.width) * dur()); });
  tl.addEventListener("keydown", (e) => {
    const step = { ArrowLeft: -2, ArrowRight: 2, PageDown: -10, PageUp: 10 }[e.key];
    if (step) { e.preventDefault(); seek(v.currentTime + step); }
    else if (e.key === "Home") { e.preventDefault(); seek(0); } else if (e.key === "End") { e.preventDefault(); seek(dur()); }
  });
  rows.forEach((b) => b.addEventListener("click", () => { seek(ms[Number(b.dataset.m)].t0); v.play().catch(() => {}); }));
  $$(".cliplist [data-f]", el).forEach((b) => b.addEventListener("click", () => {
    $$(".cliplist [data-f]", el).forEach((x) => x.setAttribute("aria-pressed", String(x === b)));
    $$("#fvList li", el).forEach((li) => (li.hidden = b.dataset.f !== "all" && li.dataset.k !== b.dataset.f));
  }));
  drawTicks(); show(ms.length ? 0 : -1); if (ms.length) { $("#fvIdx").textContent = `${ms.length} moments`; }
  if (v.readyState >= 1) { drawTicks(); tick(); }
}

// ---------------------------------------------------------------- the player sheet
async function playerSheet(card) {
  const pid = card.player.id, p = card.player;
  const h = await api(`/api/players/${pid}/history`);
  if (PLAYER !== pid || !$("#sheet")) return;
  let dims = [...new Set([...card.focus, ...card.strengths.map((s) => s.dimension), h.most_improved])].filter(Boolean).slice(0, 3);
  const ctx = `Player: ${p.name} (#${p.number ?? "?"}, ${p.position})`;
  const groups = GROUPS.map(([g, label]) => {
    const rows = Object.entries(card.skills).filter(([, s]) => s.group === g);
    return rows.length ? `<h3>${label}</h3>${rows.map(([k, s]) => skillRow(pid, p.name, k, s)).join("")}` : "";
  }).join("");
  const hw = card.homework || [];
  $("#sheet").innerHTML = `<div class="stack">
    <header class="sheet-head"><div class="big-n" aria-hidden="true">${esc(p.number ?? "")}</div>
      <div><h1>${esc(p.name)}</h1><p class="facts">${esc(p.position)}${p.height_cm ? `, ${p.height_cm} cm` : ""}. ${nf.format(card.events)} tagged events.${card.focus.length ? ` This week: ${card.focus.map((d) => esc(short(d).toLowerCase())).join(" and ")}.` : ""}</p></div>
      <div class="actions"><button type="button" class="btn line" id="pmFilm">All film</button><button type="button" class="btn line" id="pmMsg">Write ${esc(first(p.name))} a message</button>
        ${askBtn(`Ask about ${first(p.name)}`, `How is ${p.name} doing, and what should we focus on with ${first(p.name)}?`, ctx)}<button type="button" class="btn quiet" id="pmEdit">Edit</button></div></header>
    <div id="pmOut"></div>
    <div class="sheet-grid">
      <section aria-labelledby="hShot"><h2 id="hShot">Shot chart</h2>${shotChart(card)}
        <p class="court-key">Green zones are above what the position expects, red below. Select a zone to watch those shots.</p></section>
      <section class="skills" aria-labelledby="hSk"><h2 id="hSk">Skills</h2>${groups}${skillKey}</section>
    </div>
    <section class="progress" aria-labelledby="hProg"><h2 id="hProg">Progress</h2><p class="note" style="margin-bottom:var(--s3)">Estimates over the last ${h.dates.length} weeks. The number is the change over the last ${h.change_weeks}.</p>
      <div id="pmChart"></div><div class="series" id="pmLegend"></div></section>
  </div>`;
  const draw = () => {
    const colors = dims.map((_, k) => SERIES[k % SERIES.length]);
    $("#pmChart").innerHTML = progressChart(h, dims, colors, $("#pmChart").clientWidth);
    $("#pmLegend").innerHTML = Object.keys(h.series).map((d) => { const k = dims.indexOf(d);
      return `<label class="${k >= 0 ? "on" : ""}"><input type="checkbox" data-dim="${d}" ${k >= 0 ? "checked" : ""}>${k >= 0 ? `<i style="background:${colors[k]}"></i>` : ""}${esc(SHORT[d])} <span class="${h.change[d] > 0.005 ? "up" : h.change[d] < -0.005 ? "down" : "soft"}">${signed(h.change[d])}</span></label>`; }).join("");
    $$("[data-dim]", $("#pmLegend")).forEach((c) => c.addEventListener("change", () => {
      dims = c.checked ? [...dims, c.dataset.dim].slice(-5) : dims.filter((d) => d !== c.dataset.dim);
      if (!dims.length) dims = [c.dataset.dim];
      draw();
    }));
  };
  draw();
  const sheet = $("#sheet");
  bindAsk(sheet);
  const watchDim = (dim) => openClips(`${p.name}: ${META.dimensions[dim].name}`, { player_id: pid, dimension: dim });
  $$("[data-sp]", sheet).forEach((r) => r.addEventListener("click", () => watchDim(r.dataset.dim)));
  $$("[data-zone]", sheet).forEach((z) => {
    z.addEventListener("click", () => watchDim(z.dataset.zone));
    z.addEventListener("keydown", (e) => { if (e.key === "Enter" || e.key === " ") { e.preventDefault(); watchDim(z.dataset.zone); } });
  });
  $("#pmFilm").addEventListener("click", () => openClips(`${p.name}: all film`, { player_id: pid }));
  $("#pmMsg").addEventListener("click", async () => {
    $("#pmOut").innerHTML = `<p class="loading" aria-live="polite">Writing ${esc(first(p.name))}'s message…</p>`;
    const m = await api(`/api/players/${pid}/message?lang=${LANG()}`);
    if (!$("#pmOut")) return;
    $("#pmOut").innerHTML = `<h2>Message to ${esc(first(p.name))}</h2><p class="note">${writtenBy(m.source)} Read it before you send it.</p><div class="msg-out" dir="auto">${esc(m.text)}</div>
      <div class="actions" style="margin-top:var(--s3)"><button type="button" class="btn line small" id="pmCopy">Copy</button><a class="btn line small" target="_blank" rel="noopener" href="https://wa.me/?text=${encodeURIComponent(m.text)}">Open in WhatsApp</a></div>`;
    $("#pmCopy").addEventListener("click", async () => { await navigator.clipboard.writeText(m.text); toast("Copied"); });
  });
  $("#pmEdit").addEventListener("click", () => {
    modal(`<h2 id="modalTitle">Edit ${esc(p.name)}</h2><form class="form-col" id="pmForm"><label class="field">Name<input name="name" value="${esc(p.name)}" required></label>
      <div class="two"><label class="field">Number<input name="number" type="number" min="0" max="99" value="${esc(p.number ?? "")}"></label>
      <label class="field">Position<select name="position">${META.positions.map((x) => `<option ${x === p.position ? "selected" : ""}>${x}</option>`).join("")}</select></label></div>
      <div class="actions"><button class="btn">Save</button><button type="button" class="btn quiet danger" id="pmDel">Remove from the team</button></div></form>`, "narrow");
    $("#pmForm").addEventListener("submit", async (e) => {
      e.preventDefault(); const f = Object.fromEntries(new FormData(e.target)); f.number = f.number ? Number(f.number) : null;
      await api(`/api/players/${pid}`, { method: "PATCH", json: f }); toast("Saved"); closeModal(); loadTeams(TEAM);
    });
    $("#pmDel").addEventListener("click", async (e) => {
      const b = e.currentTarget;
      if (!b.dataset.armed) { b.dataset.armed = "1"; b.textContent = `Remove ${first(p.name)} and all of their data`; b.insertAdjacentHTML("afterend", `<span class="note" role="alert">This cannot be undone. Select again to confirm.</span>`); return; }
      await api(`/api/players/${pid}`, { method: "DELETE" }); toast(`${p.name} removed`); closeModal(); PLAYER = null; loadTeams(TEAM);
    });
  });
}

// ---------------------------------------------------------------- the opponent sheet
async function opponentSheet(id) {
  const [m, pt] = await Promise.all([api(`/api/opponents/${id}/matchup`), api(`/api/opponents/${id}/play-types`)]);
  if (OPP !== id || !$("#oppOut")) return;
  const o = m.opponent;
  const rows = m.comparison.map((r) => `<div>${esc(SHORT[r.dimension] || r.name)}</div>
    <div class="us"><i style="width:${(r.us || 0) * 100}%"></i><span>${pct(r.us)}</span></div>
    <div class="them"><i style="width:${(r.them || 0) * 100}%"></i><span>${pct(r.them)}</span></div>
    <div class="r ${r.edge == null ? "soft" : r.edge >= 0 ? "up" : "down"}">${r.edge == null ? "n/a" : signed(r.edge)}</div>`).join("");
  $("#oppOut").innerHTML = `<div class="stack">
    <header class="page-head"><h1>vs ${esc(o.name)}</h1>${o.notes ? `<p class="lede" dir="auto">${esc(o.notes)}</p>` : ""}
      <div class="actions"><button type="button" class="btn" id="reportBtn">Write the scouting report</button>${askBtn("Plan the week for this game", `We play ${o.name} next. Plan the week: practices, who guards whom, what we run.`, `Opponent: ${o.name}`)}</div></header>
    <div class="split even">
      <section aria-labelledby="hKeys"><h2 id="hKeys">Keys to the game</h2>
        ${m.game_plan.length ? `<ol class="keys">${m.game_plan.map((g) => `<li>${esc(g.insight)}<span class="sub">${esc(g.evidence)}</span></li>`).join("")}</ol>` : `<p class="empty">Not enough on them yet. Tag their possessions in the film room.</p>`}</section>
      <section aria-labelledby="hH2h"><h2 id="hH2h">Head to head</h2>
        <div class="h2h"><div class="hd">Skill</div><div class="hd" style="text-align:right">Us</div><div class="hd">Them</div><div class="hd r">Edge</div>${rows}</div>
        <p class="note" style="margin-top:var(--s2)">Their numbers come from tagged film where we have it and from your ratings where we do not.</p></section>
    </div>
    <section id="oppPt" aria-labelledby="hOppPt"><h2 id="hOppPt">Their play types</h2>${playTypeTable(pt, true)}</section></div>`;
  bindPlayTypeRows($("#oppPt"), o.name, { opponent_id: id });
  bindAsk($("#oppOut"));
  $("#reportBtn").addEventListener("click", async () => {
    modal(`<p class="loading" aria-live="polite">Writing the scouting report…</p>`);
    const r = await api(`/api/opponents/${id}/scouting-report?lang=${LANG()}`);
    modal(`<div class="report" dir="auto" id="modalTitle">${md(r.text)}</div><div class="actions" style="margin-top:var(--s5)"><span class="note">${writtenBy(r.source)}</span><button type="button" class="btn line small" onclick="window.print()">Print</button></div>`);
  });
}

(async function init() {
  META = await api("/api/meta");
  (await api("/api/drills")).forEach((d) => (DRILLS[d.id] = d));
  loadTeams();
})();
