// HoopLab front-end: vanilla JS, no build step.
const $ = (s, el = document) => el.querySelector(s);
const esc = (v) => String(v ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
const pct = (v) => (v == null ? "–" : `${Math.round(v * 100)}%`);
let TEAM = null, META = null, DRILLS = {};

// One small stroke icon set (decorative: aria-hidden; buttons carry the label).
const svg = (d, extra = "") => `<svg class="i" viewBox="0 0 24 24" aria-hidden="true" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" ${extra}>${d}</svg>`;
const ICON = {
  film: svg('<rect x="3" y="4" width="18" height="16" rx="2"/><path d="M7 4v16M17 4v16M3 9h4M3 15h4M17 9h4M17 15h4"/>'),
  spark: svg('<path d="M12 3l1.8 5.2L19 10l-5.2 1.8L12 17l-1.8-5.2L5 10l5.2-1.8z"/><path d="M19 17l.7 1.8 1.8.7-1.8.7-.7 1.8-.7-1.8-1.8-.7 1.8-.7z"/>'),
  mic: svg('<rect x="9" y="3" width="6" height="11" rx="3"/><path d="M5 11a7 7 0 0014 0M12 18v3"/>'),
  close: svg('<path d="M6 6l12 12M18 6L6 18"/>'),
  doc: svg('<path d="M14 3H7a2 2 0 00-2 2v14a2 2 0 002 2h10a2 2 0 002-2V8z"/><path d="M14 3v5h5M9 13h6M9 17h4"/>'),
  send: svg('<path d="M21 3L10 14M21 3l-7 18-4-7-7-4z"/>'),
  up: svg('<path d="M7 10v11H4V10zM7 10l4-7a2 2 0 012 2v4h6a2 2 0 012 2.3l-1.3 8A2 2 0 0117.7 21H7"/>'),
  down: svg('<path d="M17 14V3h3v11zM17 14l-4 7a2 2 0 01-2-2v-4H5a2 2 0 01-2-2.3l1.3-8A2 2 0 016.3 3H17"/>'),
  play: svg('<path d="M7 4l13 8-13 8z"/>'),
};

async function api(path, opts = {}) {
  const init = { ...opts };
  if (opts.json !== undefined) {
    init.body = JSON.stringify(opts.json);
    init.headers = { "Content-Type": "application/json" };
  }
  const r = await fetch(path, init);
  if (!r.ok) {
    let msg = r.statusText;
    try { const j = await r.json(); msg = typeof j.detail === "string" ? j.detail : JSON.stringify(j.detail); } catch {}
    toast(`Error: ${msg}`);
    throw new Error(msg);
  }
  return r.status === 204 ? null : r.json();
}
function toast(msg) {
  const t = $("#toast"); t.textContent = msg; t.classList.remove("hidden");
  clearTimeout(t._h); t._h = setTimeout(() => t.classList.add("hidden"), 3500);
}

// ---------------------------------------------------------------- shell
document.querySelectorAll("#tabs button").forEach((b) => b.addEventListener("click", () => showTab(b.dataset.tab)));
function showTab(name) {
  document.querySelectorAll("#tabs button").forEach((b) => { b.classList.toggle("active", b.dataset.tab === name); b.setAttribute("aria-selected", b.dataset.tab === name); });
  document.querySelectorAll(".tab").forEach((s) => s.classList.toggle("active", s.id === `tab-${name}`));
  if (TEAM) RENDER[name]();
}
const current = () => document.querySelector("#tabs button.active").dataset.tab;

async function loadTeams(select) {
  const teams = await api("/api/teams");
  const sel = $("#teamSelect");
  sel.innerHTML = teams.map((t) => `<option value="${t.id}">${esc(t.name)} (${t.players})</option>`).join("");
  if (select) sel.value = select;
  TEAM = sel.value ? Number(sel.value) : null;
  $("#empty").classList.toggle("hidden", !!TEAM);
  document.querySelectorAll(".tab").forEach((s) => s.classList.toggle("hidden", !TEAM));
  $("#tabs").classList.toggle("hidden", !TEAM);
  $("#teamSelect").classList.toggle("hidden", !TEAM);
  if (TEAM) { syncLang(); RENDER[current()](); }
}
$("#teamSelect").addEventListener("change", (e) => { TEAM = Number(e.target.value); CHAT_ID = null; syncLang(); RENDER[current()](); });
$("#heroDemo").addEventListener("click", () => $("#demoBtn").click());
$("#heroNew").addEventListener("click", () => $("#newTeamBtn").click());
$("#demoBtn").addEventListener("click", async () => {
  const r = await api("/api/demo", { method: "POST" });
  toast("Demo team loaded: 8 players, 10 weeks of games & practices");
  loadTeams(r.team_id);
});
$("#newTeamBtn").addEventListener("click", () => {
  modal(`<h2>New team</h2><form class="form" id="teamForm"><label>Team name<input name="name" required autocomplete="off"></label>
    <label>Level<input name="level" placeholder="e.g. U16 regional"></label><label>Coach<input name="coach"></label><button>Create team</button></form>
    <p class="small muted">Next: add players one by one or import a roster CSV.</p>`);
  $("#teamForm [name=name]").focus();
  $("#teamForm").addEventListener("submit", async (e) => {
    e.preventDefault();
    const t = await api("/api/teams", { method: "POST", json: Object.fromEntries(new FormData(e.target)) });
    closeModal(); await loadTeams(t.id); showTab("players");
  });
});

$("#langSelect").addEventListener("change", async (e) => {
  if (!TEAM) return;
  await api(`/api/teams/${TEAM}/settings`, { method: "PUT", json: { language: e.target.value } });
  toast(e.target.value === "he" ? "דיווחים והודעות ייכתבו בעברית" : "AI reports and messages will be written in English");
});
async function syncLang() {
  if (!TEAM) return;
  const s = await api(`/api/teams/${TEAM}/settings`);
  $("#langSelect").value = s.language || "en";
}

// "Ask the assistant" from anywhere: jumps to the chat with what the coach is looking at.
let PENDING_ASK = null;
function ask(question, context) {
  PENDING_ASK = { question, context };
  showTab("assistant");
}
const askBtn = (q, ctx) => `<button class="ghost ask" data-ask="${esc(q)}" data-ctx="${esc(ctx)}">${ICON.spark} Ask the assistant</button>`;
function bindAsk(el) { el.querySelectorAll("[data-ask]").forEach((b) => b.addEventListener("click", (e) => { e.stopPropagation(); ask(b.dataset.ask, b.dataset.ctx); })); }

// Voice input (browser speech recognition): dictate from the bench, in Hebrew or English.
function micButton(target) {
  const SR = window.SpeechRecognition || window.webkitSpeechRecognition;
  if (!SR) return "";
  return `<button type="button" class="ghost mic icon" data-mic="${target}" aria-label="Dictate" title="Dictate">${ICON.mic}</button>`;
}
function bindMic(el) {
  const SR = window.SpeechRecognition || window.webkitSpeechRecognition;
  if (!SR) return;
  el.querySelectorAll("[data-mic]").forEach((b) => b.addEventListener("click", () => {
    const ta = $(b.dataset.mic);
    if (b._rec) { b._rec.stop(); return; }
    const rec = new SR(); rec.lang = $("#langSelect").value === "he" ? "he-IL" : "en-US"; rec.interimResults = false; rec.continuous = true;
    rec.onresult = (e) => { for (let i = e.resultIndex; i < e.results.length; i++) if (e.results[i].isFinal) ta.value += (ta.value ? " " : "") + e.results[i][0].transcript; };
    rec.onend = () => { b._rec = null; b.classList.remove("on"); };
    b._rec = rec; b.classList.add("on"); rec.start();
  }));
}

// ---------------------------------------------------------------- widgets
function skillBar(s) {
  const x = (v) => (v * 100).toFixed(1);
  const color = s.label === "strength" ? "var(--good)" : s.label === "weakness" ? "var(--bad)" : "var(--info)";
  return `<div class="skill" title="${esc(s.name)}: ${pct(s.mean)} (80% interval ${pct(s.low)}–${pct(s.high)}), expected ${pct(s.baseline)} · ${s.evidence} weighted observations">
    <span>${esc(s.name)}</span>
    <svg viewBox="0 0 100 16" preserveAspectRatio="none">
      <rect x="0" y="6" width="100" height="4" fill="#2a333d" rx="2"/>
      <rect x="${x(s.low)}" y="5" width="${Math.max(0.6, x(s.high) - x(s.low))}" height="6" fill="${color}" opacity=".35" rx="2"/>
      <rect x="${x(s.mean) - 0.6}" y="2" width="1.2" height="12" fill="${color}"/>
      <rect x="${x(s.baseline) - 0.3}" y="0" width="0.6" height="16" fill="#e7ecf1" opacity=".7"/>
    </svg>
    <span>${pct(s.mean)}${s.trend ? (s.trend > 0 ? " ▲" : " ▼") : ""}</span></div>`;
}
const legend = `<div class="legend"><span><i style="background:var(--good)"></i>strength</span><span><i style="background:var(--bad)"></i>weakness</span><span><i style="background:var(--info)"></i>in range</span><span>bar = 80% interval · white tick = expected for position</span></div>`;
const pills = (arr, cls) => arr.map((s) => `<span class="pill ${cls}">${esc(s.name)} ${pct(s.mean)}</span>`).join("") || `<span class="muted small">none confirmed yet</span>`;

// ---------------------------------------------------------------- film: clip player, play types
const ptName = (k) => META.play_types[k] || k;
// Dialog: focus moves in, Tab stays inside, Escape closes, focus returns to the trigger.
let MODAL_RETURN = null;
function modal(html) {
  const m = $("#modal"), opening = m.classList.contains("hidden");
  if (opening) MODAL_RETURN = document.activeElement;
  $("#modalBody").innerHTML = html;
  m.classList.remove("hidden");
  if (opening) $("#modalClose").focus();
}
function closeModal() {
  const v = $("#modal video"); if (v) v.pause();
  $("#modal").classList.add("hidden");
  if (MODAL_RETURN && document.contains(MODAL_RETURN)) MODAL_RETURN.focus();
}
$("#modalClose").addEventListener("click", closeModal);
$("#modal").addEventListener("click", (e) => { if (e.target.id === "modal") closeModal(); });
document.addEventListener("keydown", (e) => {
  if ($("#modal").classList.contains("hidden")) return;
  if (e.key === "Escape") { e.preventDefault(); closeModal(); return; }
  if (e.key !== "Tab") return;
  const f = [...$("#modal").querySelectorAll("button, a[href], input, select, textarea, video, [tabindex]:not([tabindex='-1'])")].filter((x) => !x.disabled && x.offsetParent);
  if (!f.length) return;
  if (e.shiftKey && document.activeElement === f[0]) { e.preventDefault(); f[f.length - 1].focus(); }
  else if (!e.shiftKey && document.activeElement === f[f.length - 1]) { e.preventDefault(); f[0].focus(); }
});
const clipLabel = (c) => `${c.player ? esc(c.player) + " · " : ""}${esc(c.type)}${c.zone ? " " + esc(c.zone) : ""} ${c.outcome == null ? "" : c.outcome ? "✓" : "✗"}${c.play_type ? ` <span class="pill">${esc(ptName(c.play_type))}</span>` : ""}`;

// Plays each clip from t_start to t_end, then moves to the next one.
function clipPlayer(title, clips, sub = "") {
  if (!clips.length) return toast("No film for this yet: upload video to a game to make every number clickable");
  modal(`<h3>${esc(title)} <span class="muted small">${clips.length} clip${clips.length > 1 ? "s" : ""}</span></h3>${sub ? `<p class="small muted">${esc(sub)}</p>` : ""}
    <div class="player-wrap"><video id="clipVideo" controls muted playsinline preload="auto"></video>
    <div class="clip-list">${clips.map((c, i) => `<div class="clip" data-i="${i}"><b>${i + 1}.</b> ${clipLabel(c)}<div class="muted">${esc(c.session)} · ${c.t_start.toFixed(1)}–${c.t_end.toFixed(1)}s</div></div>`).join("")}</div></div>`);
  const v = $("#clipVideo"); let i = 0;
  const play = (k) => {
    i = k; const c = clips[i];
    document.querySelectorAll("#modal .clip").forEach((el) => el.classList.toggle("on", Number(el.dataset.i) === i));
    const go = () => { v.currentTime = c.t_start; v.play().catch(() => {}); };
    if (!v.src.endsWith(c.video_url)) { v.src = c.video_url; v.addEventListener("loadedmetadata", go, { once: true }); } else go();
  };
  v.addEventListener("timeupdate", () => { if (v.currentTime >= clips[i].t_end) { if (i + 1 < clips.length) play(i + 1); else v.pause(); } });
  document.querySelectorAll("#modal .clip").forEach((el) => el.addEventListener("click", () => play(Number(el.dataset.i))));
  play(0);
}
async function openClips(title, params) {
  const q = new URLSearchParams(Object.entries(params).filter(([, v]) => v !== null && v !== undefined && v !== ""));
  clipPlayer(title, await api(`/api/teams/${TEAM}/clips?${q}`));
}
async function openPlaylist(id) {
  const pl = await api(`/api/playlists/${id}`);
  clipPlayer(pl.title, pl.clips, pl.note || "");
}
function playTypeTable(r, clipParams) {
  if (!r.play_types.length) return `<span class="muted">No play-type tags yet. Tag possessions in your film (pick & roll, spot-up, …) to see what works.</span>`;
  const max = Math.max(...r.play_types.map((x) => x.ppp), 1.2);
  return `<p class="small muted">${r.possessions} tagged possessions · overall <b>${r.overall_ppp?.toFixed(2)}</b> points per possession${clipParams ? " · click a row to watch it" : ""}</p>
    <table><tr><th>Play type</th><th>Share</th><th>PPP</th><th></th><th>TO%</th></tr>
    ${r.play_types.map((x) => `<tr class="${clipParams ? "click" : ""}" data-pt="${x.play_type}" ${clipParams ? `tabindex="0" aria-label="Watch ${esc(x.name)} possessions"` : ""}><td>${esc(x.name)}${x.play_type === r.best ? ` <span class="pill good">best</span>` : x.play_type === r.worst ? ` <span class="pill bad">worst</span>` : ""}</td>
      <td>${pct(x.frequency)} <span class="small muted">n=${x.possessions}</span></td><td><b>${x.ppp.toFixed(2)}</b>${x.reliable ? "" : ` <span class="small muted">small sample</span>`}</td>
      <td style="width:28%"><svg viewBox="0 0 100 8" preserveAspectRatio="none" style="width:100%;height:8px"><rect width="${(x.ppp / max) * 100}" height="8" rx="2" fill="${x.ppp >= r.overall_ppp ? "var(--good)" : "var(--bad)"}"/></svg></td>
      <td class="small">${pct(x.turnover_rate)}</td></tr>`).join("")}</table>`;
}
function bindPlayTypeRows(el, title, params) {
  el.querySelectorAll("[data-pt]").forEach((row) => {
    const go = () => openClips(`${title}: ${ptName(row.dataset.pt)}`, { ...params, play_type: row.dataset.pt });
    row.addEventListener("click", go);
    row.addEventListener("keydown", (e) => { if (e.key === "Enter" || e.key === " ") { e.preventDefault(); go(); } });
  });
}
function md(text) { // tiny, safe Markdown subset for reports
  return text.split("\n").map((l) => {
    let h = esc(l).replace(/\*\*(.+?)\*\*/g, "<b>$1</b>").replace(/(^|\s)_(.+?)_(\s|$)/g, "$1<i>$2</i>$3");
    if (/^### /.test(l)) return `<h3>${h.slice(4)}</h3>`;
    if (/^## /.test(l)) return `<h2>${h.slice(3)}</h2>`;
    if (/^# /.test(l)) return `<h1>${h.slice(2)}</h1>`;
    if (/^\s*[-*] /.test(l)) return `<li>${h.replace(/^\s*[-*] /, "")}</li>`;
    if (/^\s*\d+\. /.test(l)) return `<li>${h.replace(/^\s*\d+\. /, "")}</li>`;
    return h.trim() ? `<p>${h}</p>` : "";
  }).join("").replace(/(<li>.*?<\/li>)+/g, (m) => `<ul>${m}</ul>`);
}

// ---------------------------------------------------------------- player card (progress, message, film, edit)
const SERIES_COLORS = ["#f28c28", "#3fb68b", "#4c9be8", "#e5534b", "#c9a227", "#9aa7b4"];
function progressChart(h, dims) {
  const W = 560, H = 190, P = 28, n = h.dates.length;
  const x = (i) => P + (i * (W - 2 * P)) / Math.max(1, n - 1);
  const all = dims.flatMap((d) => h.series[d]);
  const lo = Math.max(0, Math.floor((Math.min(...all) - 0.05) * 10) / 10), hi = Math.min(1, Math.ceil((Math.max(...all) + 0.05) * 10) / 10);
  const y = (v) => H - P - ((v - lo) / (hi - lo || 1)) * (H - 2 * P);
  const grid = [lo, (lo + hi) / 2, hi].map((v) => `<line x1="${P}" x2="${W - P}" y1="${y(v)}" y2="${y(v)}" stroke="var(--line)"/><text x="2" y="${y(v) + 3}">${Math.round(v * 100)}%</text>`).join("");
  const lines = dims.map((d, k) => `<polyline fill="none" stroke="${SERIES_COLORS[k % 6]}" stroke-width="2" points="${h.series[d].map((v, i) => `${x(i)},${y(v)}`).join(" ")}"/>
    <circle cx="${x(n - 1)}" cy="${y(h.series[d][n - 1])}" r="3" fill="${SERIES_COLORS[k % 6]}"/>`).join("");
  const ticks = [0, Math.floor((n - 1) / 2), n - 1].map((i) => `<text x="${x(i)}" y="${H - 8}" text-anchor="middle">${h.dates[i].slice(5)}</text>`).join("");
  return `<svg class="chart" viewBox="0 0 ${W} ${H}" role="img" aria-label="Skill estimates over the last ${n} weeks">${grid}${lines}${ticks}</svg>`;
}
async function playerModal(pid) {
  const [card, h] = await Promise.all([api(`/api/players/${pid}`), api(`/api/players/${pid}/history`)]);
  const p = card.player;
  let dims = [...new Set([...card.focus, ...card.strengths.map((s) => s.dimension), h.most_improved])].slice(0, 4);
  const ctx = `Player card: ${p.name} (#${p.number ?? "?"}, ${p.position})`;
  const draw = () => {
    $("#pmChart").innerHTML = progressChart(h, dims);
    $("#pmLegend").innerHTML = Object.keys(h.series).map((d) => { const k = dims.indexOf(d);
      return `<label><input type="checkbox" data-dim="${d}" ${k >= 0 ? "checked" : ""}><i style="background:${k >= 0 ? SERIES_COLORS[k % 6] : "var(--line)"}"></i>${esc(META.dimensions[d].name)} <span class="muted tnum">${h.change[d] >= 0 ? "+" : ""}${Math.round(h.change[d] * 100)}</span></label>`; }).join("");
    $("#pmLegend").querySelectorAll("[data-dim]").forEach((c) => c.addEventListener("change", () => {
      dims = c.checked ? [...dims, c.dataset.dim].slice(-6) : dims.filter((d) => d !== c.dataset.dim);
      if (!dims.length) dims = [c.dataset.dim];
      draw();
    }));
  };
  modal(`<h2>#${esc(p.number ?? "")} ${esc(p.name)} <span class="pill">${esc(p.position)}</span> <span class="muted small tnum">${card.events} events</span></h2>
    <div class="row-actions">
      <button class="ghost" id="pmFilm">${ICON.film} Film</button>
      <button class="ghost" id="pmMsg">${ICON.send} Message to player</button>
      ${askBtn(`How is ${p.name} doing, and what should we focus on with him?`, ctx)}
      <button class="ghost" id="pmEdit">Edit</button>
    </div>
    <div class="grid2" style="margin-top:14px">
      <div><h3>Progress <span class="muted small">skill estimate week by week · number = change over the last ${h.change_weeks} weeks</span></h3>
        <div id="pmChart"></div><div class="chart-legend" id="pmLegend"></div></div>
      <div><h3>Now</h3><div class="small muted">Strengths</div>${pills(card.strengths, "good")}
        <div class="small muted" style="margin-top:6px">Needs work</div>${pills(card.weaknesses, "bad")}
        <div class="small muted" style="margin-top:6px">Focus this week</div><div>${card.focus.map((d) => esc(META.dimensions[d].name)).join(", ") || "n/a"}</div>
        ${card.recent_trends.length ? `<div class="small muted" style="margin-top:6px">Significant trends</div>${card.recent_trends.map((t) => `<div class="tnum">${esc(t.name)}: ${pct(t.before)} → <b class="${t.trend > 0 ? "edge-pos" : "edge-neg"}">${pct(t.recent)}</b></div>`).join("")}` : ""}
        <div class="small muted" style="margin-top:6px">Homework</div>${card.homework.filter((x) => x.status === "assigned").map((x) => `<div>${esc(DRILLS[x.drill_id]?.name ?? x.drill_id)} <span class="muted small">due ${esc(x.due)}</span></div>`).join("") || `<span class="muted small">None open</span>`}
        <div id="pmOut" style="margin-top:12px"></div></div>
    </div>`);
  draw(); bindAsk($("#modal"));
  $("#pmFilm").addEventListener("click", () => openClips(`${p.name}: all film`, { player_id: pid }));
  $("#pmMsg").addEventListener("click", async () => {
    $("#pmOut").innerHTML = `<p class="muted" aria-live="polite">Writing ${esc(p.name.split(" ")[0])}'s message…</p>`;
    const m = await api(`/api/players/${pid}/message`);
    $("#pmOut").innerHTML = `<h3>Message to ${esc(p.name.split(" ")[0])} <span class="pill">${esc(m.source)}</span></h3><div class="msg-box" dir="auto">${esc(m.text)}</div>
      <div class="row-actions"><button class="ghost" id="pmCopy">Copy</button><a class="btn ghost-link" target="_blank" rel="noopener" href="https://wa.me/?text=${encodeURIComponent(m.text)}">Send on WhatsApp</a></div>`;
    $("#pmCopy").addEventListener("click", async () => { await navigator.clipboard.writeText(m.text); toast("Copied"); });
  });
  $("#pmEdit").addEventListener("click", () => {
    $("#pmOut").innerHTML = `<form class="form" id="pmForm"><label>Name<input name="name" value="${esc(p.name)}" required></label>
      <label>Number<input name="number" type="number" min="0" max="99" value="${esc(p.number ?? "")}" style="width:80px"></label>
      <label>Position<select name="position">${META.positions.map((x) => `<option ${x === p.position ? "selected" : ""}>${x}</option>`).join("")}</select></label>
      <button>Save</button><button type="button" class="ghost danger" id="pmDel">Remove player</button></form>`;
    $("#pmForm").addEventListener("submit", async (e) => {
      e.preventDefault(); const f = Object.fromEntries(new FormData(e.target)); f.number = f.number ? Number(f.number) : null;
      await api(`/api/players/${pid}`, { method: "PATCH", json: f }); toast("Saved"); closeModal(); RENDER[current()]();
    });
    $("#pmDel").addEventListener("click", async (e) => {
      const b = e.currentTarget;
      if (!b.dataset.armed) { b.dataset.armed = "1"; b.textContent = `Remove ${p.name} and all their data`; b.insertAdjacentHTML("afterend", `<span class="small muted" role="alert">This cannot be undone. Click again to confirm.</span>`); return; }
      await api(`/api/players/${pid}`, { method: "DELETE" }); toast("Player removed"); closeModal(); loadTeams(TEAM);
    });
  });
}

// ---------------------------------------------------------------- tabs
let CHAT_ID = null;
const SUGGESTIONS = [
  "What should we work on this week, and who needs what?",
  "We play Maccabi North on Thursday. Plan tomorrow: 75 minutes, 9 players, one hoop, nothing too intense.",
  "Today Noam hit 4 of 6 threes and lost the ball twice under pressure; Daniel was late on help 3 times.",
  "תכין שיעורי בית לכל השחקנים לשבוע הקרוב",
  "Catch me up: what should I know before practice?",
  "How did we play in the last game? Who surprised you?",
  "Self-scout: which play types work for us, and what should we run more?",
  "I hate conditioning drills without a ball. Remember that.",
];
const RENDER = {
  async assistant() {
    const el = $("#tab-assistant");
    const health = await api("/api/health");
    el.innerHTML = `<div class="card chat">
      <h3>Assistant coach <span class="pill">${esc(health.model)}</span> ${health.ai ? `<span class="pill good">online</span>` : `<span class="pill bad">AI not configured</span>`}
        <button class="ghost" id="newChat" style="float:right">New conversation</button></h3>
      <p class="small muted">Ask about the team, plan practices, report what happened, scout opponents. The assistant uses HoopLab's model and tools, and every number it gives comes from your data.</p>
      ${health.ai ? "" : `<p class="small">Set <code>ANTHROPIC_API_KEY</code> on the server to enable the assistant, notes understanding and film AI. Everything else works without it.</p>`}
      <div class="suggest">${SUGGESTIONS.map((q) => `<button class="ghost" data-q="${esc(q)}">${esc(q)}</button>`).join("")}</div>
      <div class="chat-log" id="chatLog"></div>
      <form class="chat-in" id="chatForm"><textarea name="m" id="chatText" dir="auto" placeholder="Message your assistant coach… (Hebrew or English)"></textarea>${micButton("#chatText")}<button>Send</button></form>
    </div>`;
    const log = $("#chatLog");
    const add = (role, text, actions = []) => {
      const d = document.createElement("div");
      d.className = `msg ${role}`; d.dir = "auto"; d.textContent = text;
      if (actions.length) {
        const a = document.createElement("div"); a.className = "acts";
        a.innerHTML = actions.map((x) => x.playlist_id ? `<button class="pill info num" data-pl="${x.playlist_id}">${ICON.film} Watch playlist</button>` : `<span class="pill info">${esc(x.kind.replace("_", " "))}${x.stored ? ` ${x.stored}` : ""}${x.count ? ` ${x.count}` : ""}</span>`).join("");
        a.querySelectorAll("[data-pl]").forEach((b) => b.addEventListener("click", () => openPlaylist(b.dataset.pl)));
        d.appendChild(a);
      }
      log.appendChild(d); log.scrollTop = log.scrollHeight; return d;
    };
    if (CHAT_ID) (await api(`/api/teams/${TEAM}/chats/${CHAT_ID}`)).forEach((m) => add(m.role, m.text));
    const send = async (text, context = null) => {
      if (!text.trim()) return;
      const u = add("user", text);
      if (context) { const c = document.createElement("div"); c.className = "small muted"; c.textContent = `about: ${context}`; u.appendChild(c); }
      const wait = add("assistant", "Thinking…"); wait.classList.add("typing");
      try {
        const r = await api(`/api/teams/${TEAM}/chat`, { method: "POST", json: { message: text, chat_id: CHAT_ID, context } });
        CHAT_ID = r.chat_id; wait.remove(); add("assistant", r.reply || "(no reply)", r.actions);
      } catch (e) { wait.remove(); add("assistant", `Error: ${e.message}`); }
    };
    $("#chatForm").addEventListener("submit", (e) => { e.preventDefault(); const t = e.target.m.value; e.target.m.value = ""; send(t); });
    $("#chatForm textarea").addEventListener("keydown", (e) => { if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); $("#chatForm").requestSubmit(); } });
    el.querySelectorAll("[data-q]").forEach((b) => b.addEventListener("click", () => send(b.dataset.q)));
    $("#newChat").addEventListener("click", () => { CHAT_ID = null; RENDER.assistant(); });
    bindMic(el);
    if (PENDING_ASK) { const p = PENDING_ASK; PENDING_ASK = null; send(p.question, p.context); }
  },

  async team() {
    const el = $("#tab-team");
    el.innerHTML = `<p class="muted">Analysing…</p>`;
    const [s, brief, pt, inbox] = await Promise.all([api(`/api/teams/${TEAM}/snapshot`), api(`/api/teams/${TEAM}/briefing`),
      api(`/api/teams/${TEAM}/play-types`), api(`/api/teams/${TEAM}/inbox`)]);
    el.innerHTML = `
      <div class="kpis">
        <div class="kpi"><span class="muted small">Players</span><b>${s.players.length}</b></div>
        <div class="kpi"><span class="muted small">Events learned from</span><b>${s.data_coverage.events.toLocaleString()}</b></div>
        <div class="kpi"><span class="muted small">Top priority</span><b style="font-size:15px">${esc(s.priorities[0]?.name ?? "–")}</b></div>
        <div class="kpi"><span class="muted small">Significant trends</span><b>${s.trends.length}</b></div>
      </div>
      <div class="grid2">
        <div class="card"><h3>Coach's inbox <span class="pill info">AI</span> <span class="muted small">debriefs after every game and practice, trends, overdue homework</span></h3>
          <div class="inbox-scroll">${inbox.map((i) => `<div class="inbox-item ${esc(i.kind)}"><b dir="auto">${esc(i.title)}</b> ${i.source && i.source !== "model" ? `<span class="pill">${esc(i.source)}</span>` : ""}
            <div class="body" dir="auto">${esc(i.body)}</div>
            <div class="row-actions">${i.ref?.session_id ? `<button class="ghost ask" data-watch-s="${i.ref.session_id}">${ICON.film} Film</button>` : ""}${askBtn("What should we do about this?", `${i.title}: ${i.body}`.slice(0, 1500))}</div></div>`).join("") || `<span class="muted">Nothing new. Debriefs appear here after each game or practice you add.</span>`}</div></div>
        <div class="card"><h3>Coach briefing <span class="pill">${esc(brief.source)}</span></h3><div class="briefing" dir="auto">${esc(brief.text)}</div></div>
        <div class="card"><h3>Strengths to exploit</h3>
          <table><tr><th>Player</th><th>Skill</th><th>Level</th><th>Expected</th></tr>
          ${s.exploit.map((x) => `<tr><td>${esc(x.player)}</td><td>${esc(x.name)}</td><td class="edge-pos">${pct(x.mean)}</td><td class="muted">${pct(x.baseline)}</td></tr>`).join("") || `<tr><td colspan="4" class="muted">Not enough data yet</td></tr>`}
          </table></div>
        <div class="card"><h3>Team priorities (what practice should fix)</h3>
          ${s.priorities.map((p, i) => `<div>${i + 1}. ${esc(p.name)} <span class="muted small">need ${p.need}</span></div>`).join("")}
          <h3 style="margin-top:14px">Trends (statistically significant)</h3>
          ${s.trends.map((t) => `<div>${esc(t.player)} · ${esc(t.name)}: ${pct(t.before)} → <b class="${t.trend > 0 ? "edge-pos" : "edge-neg"}">${pct(t.recent)}</b> <span class="muted small">z=${t.z}</span></div>`).join("") || `<span class="muted">No significant changes in the last 3 weeks.</span>`}
        </div>
        <div class="card"><h3>Team profile vs. expected for your positions</h3>
          <table><tr><th>Skill</th><th>Team</th><th>Expected</th><th>Gap</th></tr>
          ${Object.values(s.team_dimensions).map((d) => `<tr><td>${esc(d.name)}</td><td>${pct(d.mean)}</td><td class="muted">${pct(d.baseline)}</td><td class="${d.gap >= 0 ? "edge-pos" : "edge-neg"}">${d.gap >= 0 ? "+" : ""}${Math.round(d.gap * 100)}%</td></tr>`).join("")}
          </table></div>
        <div class="card" id="ptCard"><h3>Self-scout: points per possession by play type</h3>${playTypeTable(pt, true)}</div>
      </div>
      <h2 style="margin-top:22px">Players at a glance</h2>
      <div class="grid">${s.players.map((c) => `
        <div class="card click" data-pid="${c.player.id}" tabindex="0" role="button" aria-label="Open ${esc(c.player.name)}">
          <h3>#${esc(c.player.number ?? "")} ${esc(c.player.name)} <span class="pill">${esc(c.player.position)}</span></h3>
          <div class="small muted">Strengths</div>${pills(c.strengths, "good")}
          <div class="small muted" style="margin-top:6px">Needs work</div>${pills(c.weaknesses, "bad")}
          <div class="small muted" style="margin-top:6px">Focus this week: ${c.focus.map((d) => esc(META.dimensions[d].name)).join(", ") || "–"}</div>
        </div>`).join("")}</div>`;
    el.querySelectorAll("[data-pid]").forEach((c) => {
      c.addEventListener("click", () => playerModal(Number(c.dataset.pid)));
      c.addEventListener("keydown", (e) => { if (e.key === "Enter" || e.key === " ") { e.preventDefault(); playerModal(Number(c.dataset.pid)); } });
    });
    bindPlayTypeRows($("#ptCard"), "Our team", {});
    bindAsk(el);
    el.querySelectorAll("[data-watch-s]").forEach((b) => b.addEventListener("click", async () => {
      const all = await api(`/api/teams/${TEAM}/clips?limit=200`);
      clipPlayer("Session film", all.filter((c) => c.session_id === Number(b.dataset.watchS)));
    }));
  },

  async players(focusId) {
    const el = $("#tab-players");
    const s = await api(`/api/teams/${TEAM}/snapshot`);
    el.innerHTML = `
      <div class="card" style="margin-bottom:16px"><h3>Add player</h3>
        <form class="form" id="addPlayer">
          <label>Name<input name="name" required></label>
          <label>Number<input name="number" type="number" min="0" max="99" style="width:80px"></label>
          <label>Position<select name="position">${META.positions.map((p) => `<option>${p}</option>`).join("")}</select></label>
          <label>Height (cm)<input name="height_cm" type="number" style="width:90px"></label>
          <button>Add</button>
        </form>
        <form class="form" id="importRoster" style="margin:0"><label>Or import a roster (CSV: name, number, position, height_cm)<input type="file" name="file" accept=".csv"></label><button class="ghost">Import</button></form></div>
      ${legend}<p class="small muted">Click a skill to watch the possessions behind it.</p>
      <div class="grid">${s.players.map((c) => `
        <div class="card" id="p-${c.player.id}">
          <h3><button class="linklike" data-open="${c.player.id}">#${esc(c.player.number ?? "")} ${esc(c.player.name)}</button> <span class="pill">${esc(c.player.position)}</span> <span class="muted small tnum">${c.events} events</span>
            <button class="ghost ask" data-film="${c.player.id}" data-name="${esc(c.player.name)}" style="float:right">${ICON.film} Film</button></h3>
          ${Object.entries(c.skills).map(([k, sk]) => `<button class="skill-row" data-sp="${c.player.id}" data-dim="${k}" data-name="${esc(c.player.name)}" aria-label="Watch ${esc(c.player.name)}: ${esc(sk.name)}">${skillBar(sk)}</button>`).join("")}
          <div class="small muted" style="margin-top:8px">Exploit: ${c.strengths.map((x) => esc(x.name)).join(", ") || "–"}</div>
          <div class="small muted">Work on: ${c.focus.map((d) => esc(META.dimensions[d].name)).join(", ") || "–"}</div>
        </div>`).join("")}</div>`;
    el.querySelectorAll("[data-open]").forEach((b) => b.addEventListener("click", () => playerModal(Number(b.dataset.open))));
    $("#importRoster").addEventListener("submit", async (e) => {
      e.preventDefault(); const fd = new FormData(e.target);
      if (!fd.get("file")?.name) return toast("Choose a CSV file");
      const r = await api(`/api/teams/${TEAM}/players.csv`, { method: "POST", body: fd });
      toast(`${r.added} added, ${r.updated} updated`); RENDER.players(); loadTeams(TEAM);
    });
    el.querySelectorAll("[data-film]").forEach((b) => b.addEventListener("click", () => openClips(`${b.dataset.name}: all film`, { player_id: b.dataset.film })));
    el.querySelectorAll("[data-sp]").forEach((r) => r.addEventListener("click", () =>
      openClips(`${r.dataset.name}: ${META.dimensions[r.dataset.dim].name}`, { player_id: r.dataset.sp, dimension: r.dataset.dim })));
    $("#addPlayer").addEventListener("submit", async (e) => {
      e.preventDefault();
      const f = Object.fromEntries(new FormData(e.target));
      for (const k of ["number", "height_cm"]) f[k] = f[k] ? Number(f[k]) : null;
      await api(`/api/teams/${TEAM}/players`, { method: "POST", json: f });
      toast("Player added"); RENDER.players(); loadTeams(TEAM);
    });
    if (focusId) playerModal(focusId);
  },

  async practice() {
    const el = $("#tab-practice");
    const opps = await api(`/api/teams/${TEAM}/opponents`);
    el.innerHTML = `
      <div class="card" style="margin-bottom:16px"><h3>Build a practice</h3>
      <form class="form" id="planForm">
        <label>Minutes<input name="minutes" type="number" value="90" min="15" max="240" style="width:80px"></label>
        <label>Players available<input name="players" type="number" value="10" min="1" max="30" style="width:80px"></label>
        <label>Hoops<input name="hoops" type="number" value="2" min="0" max="12" style="width:70px"></label>
        <label>Max intensity<select name="max_intensity"><option>high</option><option>medium</option><option>low</option></select></label>
        <label>Court<select name="court"><option value="full">Full court</option><option value="half">Half court only</option></select></label>
        <label>Preparing for<select name="opponent_id"><option value="">–</option>${opps.map((o) => `<option value="${o.id}">${esc(o.name)}</option>`).join("")}</select></label>
        <label>Extra focus<select name="focus" multiple size="3">${Object.entries(META.dimensions).map(([k, v]) => `<option value="${k}">${esc(v.name)}</option>`).join("")}</select></label>
        <button>Generate plan</button>
      </form>
      <p class="small muted">The plan targets the team's measured needs, adapts to the opponent, and learns from your votes: drills you like (and drills similar to them) show up more.</p></div>
      <div id="planOut"></div>`;
    $("#planForm").addEventListener("submit", async (e) => {
      e.preventDefault();
      const fd = new FormData(e.target);
      const body = { minutes: +fd.get("minutes"), players: +fd.get("players"), hoops: +fd.get("hoops"),
        max_intensity: fd.get("max_intensity"), full_court: fd.get("court") !== "half", focus: fd.getAll("focus"), opponent_id: fd.get("opponent_id") ? +fd.get("opponent_id") : null };
      const p = await api(`/api/teams/${TEAM}/plan`, { method: "POST", json: body });
      $("#planOut").innerHTML = `<div class="card"><h3>Practice plan · ${p.total_minutes} min ${p.unfilled_minutes ? `<span class="muted small">(${p.unfilled_minutes} min free)</span>` : ""}</h3>
        ${p.blocks.map((b) => `<div class="block">
          <div class="min">${b.minutes}'</div>
          <div><b>${esc(b.drill.name)}</b> <span class="pill info">${esc(b.why)}</span> ${b.preference > 1.05 ? `<span class="pill good">coach favourite</span>` : ""}
            <div class="small">${esc(b.drill.setup)}</div>
            <div class="small muted">Cue: “${esc(b.drill.cue)}” · Success: ${esc(b.drill.metric)}</div>
            ${b.focus_players.length ? `<div class="small muted">Watch: ${b.focus_players.map(esc).join(", ")}</div>` : ""}</div>
          <div class="vote"><button class="ghost icon" data-d="${b.drill.id}" data-r="1" aria-label="More drills like ${esc(b.drill.name)}">${ICON.up}</button><button class="ghost icon" data-d="${b.drill.id}" data-r="-1" aria-label="Fewer drills like ${esc(b.drill.name)}">${ICON.down}</button></div>
        </div>`).join("")}</div>`;
      $("#planOut").querySelector("h3").insertAdjacentHTML("beforeend", " " + askBtn("Explain this plan and adjust it if something doesn't fit our week.", `Practice plan: ${p.blocks.map((b) => `${b.minutes}' ${b.drill.name}`).join("; ")}`));
      bindAsk($("#planOut"));
      $("#planOut").querySelectorAll("[data-d]").forEach((btn) => btn.addEventListener("click", async () => {
        await api(`/api/teams/${TEAM}/feedback`, { method: "POST", json: { drill_id: btn.dataset.d, rating: +btn.dataset.r, ran: +btn.dataset.r > 0 } });
        toast("Thanks, HoopLab will remember that");
      }));
    });
  },

  async homework() {
    const el = $("#tab-homework");
    const rows = await api(`/api/teams/${TEAM}/homework`);
    el.innerHTML = `<div class="form"><button id="assign">Assign this week's homework</button>
      <span class="muted small">Two personal items per player, from their top development needs, each with a playlist of their own possessions to watch first (when film exists). Logged results feed back into the model (at reduced weight).</span></div>
      <div class="card"><table><tr><th>Player</th><th>Focus</th><th>Drill</th><th>Target</th><th>Due</th><th>Status</th><th></th></tr>
      ${rows.map((h) => `<tr><td>${esc(h.player)}</td><td>${esc(META.dimensions[h.dimension]?.name)}</td><td>${esc(h.drill?.name)}<div class="small muted">${esc(h.drill?.setup)}</div>${h.playlist_id ? `<button class="ghost" data-pl="${h.playlist_id}" style="margin-top:4px;padding:3px 9px">${ICON.film} Watch first</button>` : ""}</td>
        <td class="small">${esc(h.target)}</td><td>${esc(h.due)}</td><td>${h.status === "done" ? `<span class="pill good">done${h.attempts ? ` ${h.made}/${h.attempts}` : ""}</span>` : `<span class="pill">assigned</span>`}</td>
        <td>${h.status !== "done" ? `<button class="ghost" data-h="${h.id}">Log result</button>` : ""}</td></tr>`).join("") || `<tr><td colspan="7" class="muted">No homework yet.</td></tr>`}
      </table></div>`;
    $("#assign").addEventListener("click", async () => {
      const r = await api(`/api/teams/${TEAM}/homework/assign`, { method: "POST" });
      toast(`${r.length} assignments created`); RENDER.homework();
    });
    el.querySelectorAll("[data-pl]").forEach((b) => b.addEventListener("click", () => openPlaylist(b.dataset.pl)));
    el.querySelectorAll("[data-h]").forEach((b) => b.addEventListener("click", () => {
      const cell = b.parentElement;
      cell.innerHTML = `<form class="form" style="margin:0;flex-wrap:nowrap" data-hf="${b.dataset.h}"><label class="sr-only" for="hr${b.dataset.h}">Result</label>
        <input id="hr${b.dataset.h}" name="r" placeholder="made/attempts" style="width:120px" pattern="\\s*\\d+\\s*/\\s*\\d+\\s*|" title="e.g. 32/50, or leave empty"><button>Save</button></form>`;
      const f = cell.querySelector("form"); f.r.focus();
      f.addEventListener("submit", async (e) => {
        e.preventDefault();
        const v = f.r.value.trim(); const [made, attempts] = v.includes("/") ? v.split("/").map(Number) : [null, null];
        await api(`/api/homework/${f.dataset.hf}/complete`, { method: "POST", json: { made, attempts } });
        toast("Logged. The model counts it as evidence."); RENDER.homework();
      });
    }));
  },

  async opponents() {
    const el = $("#tab-opponents");
    const opps = await api(`/api/teams/${TEAM}/opponents`);
    el.innerHTML = `
      <div class="card" style="margin-bottom:16px"><h3>Add opponent</h3>
        <form class="form" id="addOpp"><label>Name<input name="name" required></label><label>Notes<input name="notes" style="width:320px"></label><button>Add</button></form>
        <p class="small muted">Scouting builds up from opponent events tagged in your game videos; manual ratings fill the gaps.</p></div>
      <div class="form">${opps.map((o) => `<button class="ghost" data-o="${o.id}">${esc(o.name)}</button>`).join("")}</div>
      <div id="matchOut"></div>`;
    $("#addOpp").addEventListener("submit", async (e) => {
      e.preventDefault();
      await api(`/api/teams/${TEAM}/opponents`, { method: "POST", json: Object.fromEntries(new FormData(e.target)) });
      RENDER.opponents();
    });
    const show = async (id) => {
      const [m, pt] = await Promise.all([api(`/api/opponents/${id}/matchup`), api(`/api/opponents/${id}/play-types`)]);
      $("#matchOut").innerHTML = `<div class="grid2">
        <div class="card"><h3>Game plan vs ${esc(m.opponent.name)} <button class="ghost ask" id="reportBtn" style="float:right">${ICON.doc} Scouting report</button></h3><p class="muted small">${esc(m.opponent.notes)}</p>
          ${m.game_plan.map((g) => `<div style="margin-bottom:10px">• ${esc(g.insight)}<div class="small muted">${esc(g.evidence)}</div></div>`).join("") || `<span class="muted">Not enough scouting data yet.</span>`}</div>
        <div class="card"><h3>Head to head</h3><table><tr><th>Skill</th><th>Us</th><th>Them</th><th>League</th><th>Edge</th></tr>
          ${m.comparison.map((r) => `<tr><td>${esc(r.name)}</td><td>${pct(r.us)}</td><td>${pct(r.them)} <span class="small muted">${esc(r.source)}</span></td><td class="muted">${pct(r.league)}</td><td class="${r.edge >= 0 ? "edge-pos" : "edge-neg"}">${r.edge == null ? "–" : (r.edge >= 0 ? "+" : "") + Math.round(r.edge * 100)}</td></tr>`).join("")}
        </table></div>
        <div class="card" id="oppPt"><h3>How ${esc(m.opponent.name)} scores (play types)</h3>${playTypeTable(pt, true)}</div></div>`;
      bindPlayTypeRows($("#oppPt"), m.opponent.name, { opponent_id: id });
      $("#matchOut .card h3").insertAdjacentHTML("afterend", `<div class="row-actions" style="margin:0 0 8px">${askBtn(`We play ${m.opponent.name} next. Plan the week: practices, who guards whom, what we run.`, `Opponent: ${m.opponent.name}`)}</div>`);
      bindAsk($("#matchOut"));
      $("#reportBtn").addEventListener("click", async () => {
        modal(`<p class="muted">Writing the scouting report…</p>`);
        const lang = /[\u0590-\u05FF]/.test(navigator.language) || navigator.language.startsWith("he") ? "he" : "en";
        const r = await api(`/api/opponents/${id}/scouting-report?lang=${lang}`);
        modal(`<div class="report" dir="auto">${md(r.text)}</div><p class="small muted">Written by ${esc(r.source)} · every number comes from HoopLab's model <button class="ghost" onclick="window.print()">Print</button></p>`);
      });
    };
    el.querySelectorAll("[data-o]").forEach((b) => b.addEventListener("click", () => show(b.dataset.o)));
    if (opps[0]) show(opps[0].id);
  },

  async data() {
    const el = $("#tab-data");
    const [sessions, opps, health, players] = await Promise.all([
      api(`/api/teams/${TEAM}/sessions`), api(`/api/teams/${TEAM}/opponents`), api("/api/health"), api(`/api/teams/${TEAM}/players`)]);
    el.innerHTML = `
      <div class="grid2">
      <div class="card"><h3>New game / practice</h3>
        <form class="form" id="newSession">
          <label>Type<select name="kind"><option>game</option><option>practice</option><option>scrimmage</option></select></label>
          <label>Title<input name="title"></label>
          <label>Opponent<select name="opponent_id"><option value="">–</option>${opps.map((o) => `<option value="${o.id}">${esc(o.name)}</option>`).join("")}</select></label>
          <button>Create</button></form>
        <h3>Add data to a session</h3>
        <form class="form" id="upload">
          <label>Session<select name="session">${sessions.map((s) => `<option value="${s.id}">${esc(s.title || s.kind)} · ${esc(s.date.slice(0, 10))}</option>`).join("")}</select></label>
          <label>File<input type="file" name="file" accept=".mp4,.mov,.avi,.mkv,.csv,.json"></label>
          <button>Upload</button></form>
        <p class="small muted">Video: ${health.video_processing ? "<span class='pill good'>processing enabled</span>" : "<span class='pill bad'>vision extra not installed</span> videos are stored; add a track file (.json) or a tagged event log (.csv)."}<br>
        CSV columns: <code>player_number,type,outcome,zone,assist,opponent</code>, optional <code>play_type,t_start,t_end</code> (links each event to its clip) · types: shot, pass, turnover, touch, creation, defense, rotation, steal, rebound, sprint</p>
      </div>
      <div class="card"><h3>Coach notes → data <span class="pill info">AI</span></h3>
        <p class="small muted">Write or dictate what you saw, in any language. Claude turns it into events for the selected session.</p>
        <label class="sr-only" for="notesText">Coach notes</label>
        <textarea id="notesText" dir="auto" rows="4" style="width:100%" placeholder="e.g. Noam 3/5 from three, two turnovers vs pressure. Ori didn't sprint back twice. Their #12 kills us on the offensive glass."></textarea>
        <div class="form" style="margin-top:8px"><button id="notesBtn">Analyse notes</button>${micButton("#notesText")}</div>
        <h3>Film AI <span class="pill info">AI</span></h3>
        <p class="small muted">Upload stills (or a short clip with the vision extra). Claude reads the play, tags events by jersey number and adds scouting notes.</p>
        <form class="form" id="filmForm"><input type="file" name="files" multiple accept="image/*,video/*"><input name="our_color" placeholder="our jersey colour"><button>Analyse film</button></form>
        <div id="aiOut" class="small"></div>
      </div>
      <div class="card"><h3>Tagger</h3>
        <p class="small muted">Tag live from the bench, or play the session's film here and tag as you watch: each tag then opens its own clip everywhere in HoopLab.</p>
        <div class="tag-video" id="tagVideoWrap"></div>
        <div class="form"><label>Player<select id="tagPlayer">${players.map((p) => `<option value="${p.id}">#${esc(p.number ?? "")} ${esc(p.name)}</option>`).join("")}</select></label>
          <label>Play type<select id="tagPlay"><option value="">–</option>${Object.entries(META.play_types).map(([k, v]) => `<option value="${k}">${esc(v)}</option>`).join("")}</select></label></div>
        <div class="form" id="tagBtns">
          ${[["shot", "rim", true, "Rim ✓"], ["shot", "rim", false, "Rim ✗"], ["shot", "mid", true, "Mid ✓"], ["shot", "mid", false, "Mid ✗"], ["shot", "three", true, "3PT ✓"], ["shot", "three", false, "3PT ✗"],
             ["shot", "ft", true, "FT ✓"], ["shot", "ft", false, "FT ✗"], ["turnover", null, false, "Turnover"], ["creation", null, true, "Created shot"], ["defense", null, true, "Stop"], ["defense", null, false, "Beaten"],
             ["rotation", null, true, "Good rotation"], ["rotation", null, false, "Late help"], ["rebound", null, true, "Rebound"], ["rebound", null, false, "Lost board"], ["sprint", null, true, "Sprinted back"], ["sprint", null, false, "Jogged back"]]
            .map(([t, z, o, l]) => `<button class="ghost" data-t="${t}" data-z="${z ?? ""}" data-ok="${o}">${l}</button>`).join("")}
        </div></div>
      </div>
      <div class="card" style="margin-top:16px"><h3>Sessions</h3><table><tr><th>Date</th><th>Type</th><th>Title</th><th>Events</th><th>Status</th><th></th></tr>
        ${sessions.map((s) => `<tr><td>${esc(s.date.slice(0, 10))}</td><td>${esc(s.kind)}</td><td>${esc(s.title)}</td><td>${s.events}</td><td class="small">${esc(s.status)}</td>
          <td class="row-actions" style="margin:0">${s.has_video ? `<button class="ghost ask" data-watch="${s.id}" data-title="${esc(s.title)}">${ICON.film} Watch</button>` : ""}${s.events ? `<button class="ghost ask" data-debrief="${s.id}">${ICON.spark} Debrief</button>` : ""}</td></tr>`).join("")}</table></div>`;
    const sessById = Object.fromEntries(sessions.map((x) => [String(x.id), x]));
    const showTagVideo = () => {
      const sid = $("#upload [name=session]").value, sess = sessById[sid];
      $("#tagVideoWrap").innerHTML = sess?.has_video ? `<video id="tagVideo" controls playsinline preload="metadata" src="/api/sessions/${sid}/video"></video>` : "";
    };
    $("#upload [name=session]").addEventListener("change", showTagVideo); showTagVideo();
    el.querySelectorAll("[data-debrief]").forEach((b) => b.addEventListener("click", async () => {
      modal(`<p class="muted" aria-live="polite">Writing the debrief…</p>`);
      const d = await api(`/api/sessions/${b.dataset.debrief}/debrief`, { method: "POST" });
      modal(`<h2>${esc(d.report.session.title || d.report.session.kind)}${d.report.opponent ? ` vs ${esc(d.report.opponent)}` : ""} <span class="pill">${esc(d.source)}</span></h2>
        <div class="msg-box" dir="auto">${esc(d.text)}</div>
        ${d.report.standouts.length ? `<h3 style="margin-top:14px">Against expectation</h3><table><tr><th>Player</th><th>Skill</th><th>This session</th><th>Model expected</th></tr>${d.report.standouts.map((x) => `<tr><td>${esc(x.player)}</td><td>${esc(x.name)}</td><td class="tnum ${x.z > 0 ? "edge-pos" : "edge-neg"}">${x.made}/${x.n}</td><td class="tnum muted">${pct(x.expected)}</td></tr>`).join("")}</table>` : ""}
        <p class="small muted">Also posted to the coach's inbox.</p>`);
    }));
    el.querySelectorAll("[data-watch]").forEach((b) => b.addEventListener("click", async () => {
      const all = await api(`/api/teams/${TEAM}/clips?limit=200`);
      clipPlayer(b.dataset.title, all.filter((c) => c.session_id === Number(b.dataset.watch)));
    }));
    $("#newSession").addEventListener("submit", async (e) => {
      e.preventDefault();
      const f = Object.fromEntries(new FormData(e.target));
      f.opponent_id = f.opponent_id ? Number(f.opponent_id) : null;
      await api(`/api/teams/${TEAM}/sessions`, { method: "POST", json: f });
      RENDER.data();
    });
    $("#upload").addEventListener("submit", async (e) => {
      e.preventDefault();
      const fd = new FormData(e.target), file = fd.get("file"), sid = fd.get("session");
      if (!file || !file.name) return toast("Choose a file");
      let r;
      if (file.name.endsWith(".json")) {
        r = await api(`/api/sessions/${sid}/tracks`, { method: "POST", json: { tracks: JSON.parse(await file.text()), our_team: 1 } });
        toast(`Video analysis: ${r.events_detected} events detected, ${r.events_stored} stored. Debrief posted to your inbox.`);
      } else {
        const body = new FormData(); body.append("file", file);
        const path = file.name.endsWith(".csv") ? `/api/sessions/${sid}/events.csv` : `/api/sessions/${sid}/video`;
        r = await api(path, { method: "POST", body });
        toast(r.stored !== undefined ? `${r.stored} events stored` : r.detail || r.status);
      }
      RENDER.data();
    });
    const aiOut = (r) => { $("#aiOut").innerHTML = `<p><b>${r.stored} events stored.</b></p>${r.observations?.length ? `<p>Observations:</p><ul>${r.observations.map((o) => `<li dir="auto">${esc(o)}</li>`).join("")}</ul>` : ""}${r.unresolved?.length ? `<p class="muted">Not mapped: ${r.unresolved.map(esc).join("; ")}</p>` : ""}`; };
    $("#notesBtn").addEventListener("click", async () => {
      const sid = Number($("#upload [name=session]").value); const notes = $("#notesText").value;
      if (!sid || !notes.trim()) return toast("Pick a session and write some notes");
      $("#aiOut").textContent = "Reading your notes…";
      aiOut(await api(`/api/sessions/${sid}/notes`, { method: "POST", json: { notes } }));
      toast("Events stored; the debrief is in your inbox");
    });
    $("#filmForm").addEventListener("submit", async (e) => {
      e.preventDefault();
      const sid = Number($("#upload [name=session]").value), fd = new FormData(e.target);
      if (!sid) return toast("Create a session first");
      const colour = fd.get("our_color"); fd.delete("our_color");
      $("#aiOut").textContent = "Watching the film…";
      aiOut(await api(`/api/sessions/${sid}/film${colour ? `?our_color=${encodeURIComponent(colour)}` : ""}`, { method: "POST", body: fd }));
    });
    bindMic(el);
    $("#tagBtns").querySelectorAll("button").forEach((b) => b.addEventListener("click", async () => {
      let sid = sessions[0]?.id;
      if (!sid) return toast("Create a session first");
      sid = Number($("#upload [name=session]").value) || sid;
      const ev = { type: b.dataset.t, player_id: Number($("#tagPlayer").value), outcome: b.dataset.ok === "true" };
      if (b.dataset.z) ev.zone = b.dataset.z;
      if ($("#tagPlay").value) ev.play_type = $("#tagPlay").value;
      const v = $("#tagVideo");
      if (v && v.currentTime > 0) { ev.t_start = Math.max(0, +(v.currentTime - 4).toFixed(2)); ev.t_end = +(v.currentTime + 1).toFixed(2); }
      await api(`/api/sessions/${sid}/events`, { method: "POST", json: [ev] });
      toast(`Tagged: ${b.textContent}${ev.t_start !== undefined ? ` at ${Math.round(v.currentTime)}s` : ""}`);
    }));
  },
};

(async function init() {
  META = await api("/api/meta");
  (await api("/api/drills")).forEach((d) => (DRILLS[d.id] = d));
  loadTeams();
})();
