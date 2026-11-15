"use strict";

// ------------------------------------------------------------------ utilitaires
const $ = (s, el = document) => el.querySelector(s);
const $$ = (s, el = document) => [...el.querySelectorAll(s)];
const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));

async function api(path, opts = {}) {
  const o = { ...opts };
  if (o.json !== undefined) {
    o.body = JSON.stringify(o.json);
    o.headers = { "Content-Type": "application/json", ...(o.headers || {}) };
    delete o.json;
  }
  const r = await fetch(path, o);
  if (!r.ok) {
    let msg = r.statusText;
    try { msg = (await r.json()).detail || msg; } catch {}
    throw new Error(typeof msg === "string" ? msg : JSON.stringify(msg));
  }
  const ct = r.headers.get("content-type") || "";
  return ct.includes("json") ? r.json() : r.text();
}

function toast(msg, ms = 2600) {
  const t = $("#toast");
  t.textContent = msg;
  t.classList.add("show");
  clearTimeout(toast._t);
  toast._t = setTimeout(() => t.classList.remove("show"), ms);
}

const pad = (n) => String(n).padStart(2, "0");
const hm = (iso) => { const d = new Date(iso); return `${d.getHours()}h${pad(d.getMinutes())}`; };
const todayISO = () => { const d = new Date(); return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}`; };

function ago(iso) {
  if (!iso) return "—";
  const s = (Date.now() - new Date(iso).getTime()) / 1000;
  if (s < 60) return "à l'instant";
  if (s < 3600) return `il y a ${Math.round(s / 60)} min`;
  if (s < 86400) return `il y a ${Math.round(s / 3600)} h`;
  return `il y a ${Math.round(s / 86400)} j`;
}
function until(iso) {
  if (!iso) return "—";
  const d = new Date(iso);
  const s = (d.getTime() - Date.now()) / 1000;
  const same = d.toDateString() === new Date().toDateString();
  const when = same ? hm(iso) : d.toLocaleDateString("fr-FR", { weekday: "short", day: "numeric" }) + " " + hm(iso);
  return s < 0 ? `${when} <span class="badge warn">en retard</span>` : when;
}

function battery(pct, mv, low) {
  if (pct == null) return '<span class="muted">—</span>';
  return `<span class="batt ${low ? "low" : ""}" title="${mv} mV"><span class="bar"><span class="fill" style="width:${pct}%"></span></span>${pct} %</span>`;
}
function signal(rssi) {
  if (rssi == null) return '<span class="muted">—</span>';
  const lvl = rssi >= -55 ? 4 : rssi >= -65 ? 3 : rssi >= -75 ? 2 : 1;
  const bars = [1, 2, 3, 4].map((i) => `<i class="${i <= lvl ? "on" : ""}" style="height:${i * 3}px"></i>`).join("");
  return `<span class="sig">${bars}</span>${rssi} dBm`;
}

// ------------------------------------------------------------------ onglets
let currentTab = "planning";
$$("#tabs button").forEach((b) =>
  b.addEventListener("click", () => {
    currentTab = b.dataset.tab;
    $$("#tabs button").forEach((x) => x.classList.toggle("active", x === b));
    $$(".tab").forEach((t) => t.classList.toggle("active", t.id === "tab-" + currentTab));
    refreshTab();
  })
);

function refreshTab() {
  loadOverview();
  if (currentTab === "planning") loadRooms();
  if (currentTab === "devices") loadDevices();
  if (currentTab === "firmware") loadFirmware();
  if (currentTab === "settings") loadSettings();
}

async function loadOverview() {
  const o = await api("/api/overview");
  const chips = [
    `<span class="chip">${o.online}/${o.devices} écrans en ligne</span>`,
    o.offline ? `<span class="chip bad">${o.offline} hors ligne</span>` : "",
    o.low_battery ? `<span class="chip warn">${o.low_battery} batterie faible</span>` : "",
    o.unassigned ? `<span class="chip warn">${o.unassigned} non affecté${o.unassigned > 1 ? "s" : ""}</span>` : "",
    `<span class="chip">${o.rooms} salles · ${o.events} cours</span>`,
  ];
  $("#overview").innerHTML = chips.join("");
}

// ------------------------------------------------------------------ PLANNING
let rooms = [];
let selRoom = null;

async function loadRooms() {
  rooms = await api("/api/rooms");
  const tb = $("#rooms-table tbody");
  tb.innerHTML = rooms.length
    ? rooms.map((r) => `
      <tr data-code="${esc(r.code)}" class="${r.code === selRoom ? "sel" : ""}">
        <td><b>${esc(r.code)}</b></td>
        <td>${esc(r.name) || '<span class="muted">—</span>'}${r.message ? ' <span class="badge warn">bandeau</span>' : ""}</td>
        <td class="num">${r.today_count} cours</td>
        <td>${r.occupied ? `<span class="badge busy" title="${esc(r.current)}">occupée</span>` : '<span class="badge free">libre</span>'}</td>
        <td>${r.devices.length ? r.devices.length + " écran" + (r.devices.length > 1 ? "s" : "") : '<span class="muted">aucun</span>'}</td>
      </tr>`).join("")
    : '<tr><td colspan="5" class="muted">Aucune salle. Importez un emploi du temps ou ajoutez une salle.</td></tr>';
  $$("tr[data-code]", tb).forEach((tr) => tr.addEventListener("click", () => openRoom(tr.dataset.code)));
  if (selRoom) renderRoomDetail();
}

$("#room-add").addEventListener("submit", async (e) => {
  e.preventDefault();
  const f = new FormData(e.target);
  try {
    await api("/api/rooms", { method: "POST", json: { code: f.get("code"), name: f.get("name") } });
    e.target.reset();
    toast("Salle ajoutée");
    loadRooms();
  } catch (err) { toast(err.message); }
});

function openRoom(code) {
  selRoom = code;
  $("#rd-day").value = $("#rd-day").value || todayISO();
  $("#room-detail").hidden = false;
  loadRooms();
  $("#room-detail").scrollIntoView({ behavior: "smooth", block: "start" });
}

async function renderRoomDetail() {
  const r = rooms.find((x) => x.code === selRoom);
  if (!r) { $("#room-detail").hidden = true; selRoom = null; return; }
  $("#rd-title").textContent = `Salle ${r.code}`;
  const meta = $("#rd-meta");
  meta.name.value = r.name; meta.building.value = r.building; meta.message.value = r.message;
  const day = $("#rd-day").value || todayISO();
  const t = $("#rd-time").value;
  const at = t ? `${day}T${t}` : (day === todayISO() ? "" : `${day}T10:00`);
  $("#rd-preview").src = `/api/rooms/${encodeURIComponent(r.code)}/preview.png?${at ? "at=" + at + "&" : ""}_=${Date.now()}`;
  const evs = await api(`/api/rooms/${encodeURIComponent(r.code)}/events?day=${day}`);
  $("#rd-events").innerHTML = evs.length
    ? evs.map((e) => `<li><span class="t">${hm(e.start)} – ${hm(e.end)}</span>
        <span>${esc(e.title) || "Cours"}${e.teacher || e.grp ? ` <span class="muted">· ${esc([e.teacher, e.grp].filter(Boolean).join(" · "))}</span>` : ""}
        <span class="src">${esc(e.source)}</span></span>
        <button class="x" data-id="${e.id}" title="Supprimer">✕</button></li>`).join("")
    : '<li class="muted">Aucun cours ce jour-là.</li>';
  $$("#rd-events .x").forEach((b) => b.addEventListener("click", async () => {
    await api(`/api/events/${b.dataset.id}`, { method: "DELETE" });
    toast("Cours supprimé");
    loadRooms();
  }));
}

["change", "input"].forEach((ev) => {
  $("#rd-day").addEventListener(ev, renderRoomDetail);
  $("#rd-time").addEventListener(ev, renderRoomDetail);
});
$("#rd-now").addEventListener("click", () => { $("#rd-day").value = todayISO(); $("#rd-time").value = ""; renderRoomDetail(); });
$("#rd-meta").addEventListener("submit", async (e) => {
  e.preventDefault();
  const f = new FormData(e.target);
  await api(`/api/rooms/${encodeURIComponent(selRoom)}`, { method: "PATCH", json: Object.fromEntries(f) });
  toast("Salle mise à jour — les écrans se rafraîchiront au prochain réveil");
  loadRooms();
});
$("#rd-add").addEventListener("submit", async (e) => {
  e.preventDefault();
  const f = Object.fromEntries(new FormData(e.target));
  const day = $("#rd-day").value || todayISO();
  try {
    await api(`/api/rooms/${encodeURIComponent(selRoom)}/events`, {
      method: "POST",
      json: { start: `${day}T${f.start}`, end: `${day}T${f.end}`, title: f.title, teacher: f.teacher, grp: f.grp },
    });
    e.target.reset();
    toast("Cours ajouté");
    loadRooms();
  } catch (err) { toast(err.message); }
});
$("#rd-delete").addEventListener("click", async () => {
  if (!confirm(`Supprimer la salle ${selRoom} et tous ses cours ?`)) return;
  await api(`/api/rooms/${encodeURIComponent(selRoom)}`, { method: "DELETE" });
  selRoom = null;
  $("#room-detail").hidden = true;
  loadRooms();
});

// import
const drop = $("#drop");
const fileInput = $("#import-form input[type=file]");
fileInput.addEventListener("change", () => { $("#drop-label").textContent = fileInput.files[0]?.name || ""; });
["dragover", "dragenter"].forEach((ev) => drop.addEventListener(ev, (e) => { e.preventDefault(); drop.classList.add("over"); }));
["dragleave", "drop"].forEach((ev) => drop.addEventListener(ev, () => drop.classList.remove("over")));
drop.addEventListener("drop", (e) => {
  e.preventDefault();
  fileInput.files = e.dataTransfer.files;
  $("#drop-label").textContent = fileInput.files[0]?.name || "";
});
$("#import-form").addEventListener("submit", async (e) => {
  e.preventDefault();
  const fd = new FormData(e.target);
  fd.set("create_rooms", e.target.create_rooms.checked ? "true" : "false");
  const out = $("#import-report");
  out.innerHTML = '<div class="report">Import en cours…</div>';
  try {
    const r = await api("/api/import", { method: "POST", body: fd });
    out.innerHTML = `<div class="report">
      <b>${r.events} cours importés</b>${r.range[0] ? ` (du ${r.range[0]} au ${r.range[1]})` : ""}.
      ${r.rooms_created.length ? `<br>Salles créées : ${r.rooms_created.map(esc).join(", ")}` : ""}
      ${r.skipped_count ? `<br>${r.skipped_count} ligne(s) ignorée(s) :<ul>${r.skipped.map((s) => `<li>${esc(s)}</li>`).join("")}</ul>` : ""}
    </div>`;
    loadRooms(); loadOverview();
  } catch (err) {
    out.innerHTML = `<div class="report err">${esc(err.message)}</div>`;
  }
});

// ------------------------------------------------------------------ ÉCRANS
let devices = [];
let selDev = null;

async function loadDevices() {
  [devices, rooms] = await Promise.all([api("/api/devices"), api("/api/rooms")]);
  const tb = $("#devices-table tbody");
  tb.innerHTML = devices.length
    ? devices.map((d) => {
        const dot = d.status === "en ligne" ? "ok" : d.status === "hors ligne" ? "bad" : "never";
        return `<tr data-mac="${d.mac}" class="${d.mac === selDev ? "sel" : ""}">
          <td><span class="dot ${dot}" title="${d.status}"></span></td>
          <td><b>${esc(d.name) || '<span class="muted">sans nom</span>'}</b><br><span class="muted small">${d.mac}</span></td>
          <td>${d.room_code ? esc(d.room_code) : '<span class="badge warn">non affecté</span>'}</td>
          <td>${battery(d.battery_pct, d.battery_mv, d.low_battery)}</td>
          <td class="num">${signal(d.rssi)}</td>
          <td class="num">${esc(d.ip) || "—"}</td>
          <td>${esc(d.fw_version) || "—"}</td>
          <td>${ago(d.last_seen)}</td>
          <td>${until(d.next_wake)}</td>
        </tr>`;
      }).join("")
    : '<tr><td colspan="9" class="muted">Aucun écran ne s\'est encore connecté.</td></tr>';
  $$("tr[data-mac]", tb).forEach((tr) => tr.addEventListener("click", () => openDevice(tr.dataset.mac)));
  $("#dev-updated").textContent = "Mis à jour " + new Date().toLocaleTimeString("fr-FR");
  if (selDev) renderDeviceDetail();
}

function openDevice(mac) {
  selDev = mac;
  $("#dev-detail").hidden = false;
  loadDevices();
  $("#dev-detail").scrollIntoView({ behavior: "smooth", block: "start" });
}

function sparkline(points, { min, max, unit, fmt = (v) => v }) {
  if (points.length < 2) return '<p class="muted small">Pas encore assez de mesures.</p>';
  const W = 600, H = 110, P = 22;
  const t0 = new Date(points[0].t).getTime(), t1 = new Date(points.at(-1).t).getTime();
  const lo = min ?? Math.min(...points.map((p) => p.v)), hi = max ?? Math.max(...points.map((p) => p.v));
  const x = (t) => P + ((new Date(t).getTime() - t0) / Math.max(1, t1 - t0)) * (W - 2 * P);
  const y = (v) => H - P - ((v - lo) / Math.max(1e-9, hi - lo)) * (H - 2 * P);
  const path = points.map((p, i) => `${i ? "L" : "M"}${x(p.t).toFixed(1)},${y(p.v).toFixed(1)}`).join("");
  const last = points.at(-1);
  return `<svg viewBox="0 0 ${W} ${H}" preserveAspectRatio="none">
    <line x1="${P}" x2="${W - P}" y1="${y(lo)}" y2="${y(lo)}" stroke="#e4e2db"/>
    <line x1="${P}" x2="${W - P}" y1="${y(hi)}" y2="${y(hi)}" stroke="#e4e2db"/>
    <text x="2" y="${y(hi) + 4}" font-size="10" fill="#6f6d66">${fmt(hi)}</text>
    <text x="2" y="${y(lo) + 4}" font-size="10" fill="#6f6d66">${fmt(lo)}</text>
    <path d="${path}" fill="none" stroke="#1f4e79" stroke-width="2" vector-effect="non-scaling-stroke"/>
    <circle cx="${x(last.t)}" cy="${y(last.v)}" r="3.5" fill="#1f4e79"/>
    <text x="${W - P}" y="12" font-size="11" text-anchor="end" fill="#1b1b1a">${fmt(last.v)}${unit}</text>
  </svg>`;
}

async function renderDeviceDetail() {
  const d = devices.find((x) => x.mac === selDev);
  if (!d) { $("#dev-detail").hidden = true; selDev = null; return; }
  $("#dd-title").textContent = d.name || d.mac;
  $("#dd-preview").src = `/api/devices/${d.mac}/preview.png?_=${Date.now()}`;
  const f = $("#dd-form");
  if (document.activeElement?.form !== f) {
    f.name.value = d.name; f.notes.value = d.notes;
    f.room_code.innerHTML = '<option value="">— non affecté —</option>' +
      rooms.map((r) => `<option value="${esc(r.code)}" ${r.code === d.room_code ? "selected" : ""}>${esc(r.code)}${r.name ? " — " + esc(r.name) : ""}</option>`).join("");
  }
  const kv = [
    ["Statut", d.status], ["MAC", d.mac], ["IP", d.ip || "—"], ["Firmware", d.fw_version || "—"],
    ["Batterie", d.battery_mv ? `${d.battery_pct} % (${d.battery_mv} mV)` : "—"],
    ["Signal", d.rssi != null ? `${d.rssi} dBm` : "—"],
    ["Connexion Wi-Fi", d.wifi_ms != null ? `${d.wifi_ms} ms` : "—"],
    ["Dernier réveil", d.last_seen ? `${new Date(d.last_seen).toLocaleString("fr-FR")} (${d.wake_reason || "?"})` : "—"],
    ["Dernier rafraîchissement", d.last_refresh ? new Date(d.last_refresh).toLocaleString("fr-FR") : "—"],
    ["Prochain réveil", until(d.next_wake)],
    ["Rafraîchissements", d.refresh_count], ["Démarrages", d.boot_count ?? "—"],
    ["Échecs consécutifs", d.fail_count ?? "—"],
    ["Rafraîchissement forcé", d.force_refresh ? "en attente du prochain réveil" : "non"],
  ];
  $("#dd-kv").innerHTML = kv.map(([k, v]) => `<dt>${k}</dt><dd>${typeof v === "string" && v.includes("<") ? v : esc(v)}</dd>`).join("");
  const tel = await api(`/api/devices/${d.mac}/telemetry?days=14`);
  $("#dd-chart-batt").innerHTML = sparkline(tel.filter((p) => p.battery_pct != null).map((p) => ({ t: p.ts, v: p.battery_pct })), { min: 0, max: 100, unit: " %" });
  $("#dd-chart-rssi").innerHTML = sparkline(tel.filter((p) => p.rssi != null).map((p) => ({ t: p.ts, v: p.rssi })), { unit: " dBm" });
}

$("#dd-form").addEventListener("submit", async (e) => {
  e.preventDefault();
  const f = Object.fromEntries(new FormData(e.target));
  try {
    await api(`/api/devices/${selDev}`, { method: "PATCH", json: f });
    toast("Écran mis à jour — nouvelle image au prochain réveil");
    loadDevices(); loadOverview();
  } catch (err) { toast(err.message); }
});
$("#dd-refresh").addEventListener("click", async () => {
  const r = await api(`/api/devices/${selDev}/refresh`, { method: "POST" });
  toast(r.note, 4000);
  loadDevices();
});
$("#dd-delete").addEventListener("click", async () => {
  if (!confirm("Oublier cet écran ? Il réapparaîtra comme « non affecté » à son prochain réveil.")) return;
  await api(`/api/devices/${selDev}`, { method: "DELETE" });
  selDev = null; $("#dev-detail").hidden = true; loadDevices();
});

// ------------------------------------------------------------------ FIRMWARE
async function loadFirmware() {
  const [fws, devs] = await Promise.all([api("/api/firmware"), api("/api/devices")]);
  const count = (v) => devs.filter((d) => d.fw_version === v).length;
  $("#fw-table tbody").innerHTML = fws.length
    ? fws.map((f) => `<tr>
        <td><b>${esc(f.version)}</b> ${f.active ? '<span class="badge busy">active</span>' : ""}</td>
        <td class="num">${(f.size / 1024).toFixed(0)} Ko</td>
        <td>${new Date(f.uploaded_at + "Z").toLocaleString("fr-FR")}</td>
        <td class="num">${count(f.version)}/${devs.length}</td>
        <td>${f.factory_filename ? '<a href="/flash">oui</a>' : '<span class="muted">non</span>'}</td>
        <td style="text-align:right">
          ${f.active ? `<button data-a="deactivate">Désactiver</button>` : `<button data-a="activate" data-v="${esc(f.version)}">Activer</button>`}
          <button class="danger ghost" data-a="delete" data-v="${esc(f.version)}">✕</button>
        </td></tr>`).join("")
    : '<tr><td colspan="6" class="muted">Aucun firmware publié.</td></tr>';
  $$("#fw-table button").forEach((b) => b.addEventListener("click", async (e) => {
    e.stopPropagation();
    const a = b.dataset.a, v = b.dataset.v;
    if (a === "activate") {
      if (!confirm(`Déployer la version ${v} sur tous les écrans à leur prochain réveil ?`)) return;
      await api(`/api/firmware/${encodeURIComponent(v)}/activate`, { method: "POST" });
    } else if (a === "deactivate") {
      await api(`/api/firmware/deactivate`, { method: "POST" });
    } else if (a === "delete") {
      if (!confirm(`Supprimer la version ${v} ?`)) return;
      await api(`/api/firmware/${encodeURIComponent(v)}`, { method: "DELETE" });
    }
    loadFirmware();
  }));
}
$("#fw-form").addEventListener("submit", async (e) => {
  e.preventDefault();
  try {
    await api("/api/firmware", { method: "POST", body: new FormData(e.target) });
    e.target.reset();
    toast("Firmware envoyé — activez-le pour le déployer");
    loadFirmware();
  } catch (err) { toast(err.message, 5000); }
});

// ------------------------------------------------------------------ RÉGLAGES
async function loadSettings() {
  const s = await api("/api/settings");
  const f = $("#settings-form");
  for (const [k, v] of Object.entries(s)) if (f[k]) f[k].value = v;
}
$("#settings-form").addEventListener("submit", async (e) => {
  e.preventDefault();
  try {
    await api("/api/settings", { method: "PUT", json: Object.fromEntries(new FormData(e.target)) });
    toast("Réglages enregistrés");
  } catch (err) { toast(err.message, 5000); }
});

// ------------------------------------------------------------------ démarrage
refreshTab();
setInterval(() => { if (currentTab === "devices" && document.visibilityState === "visible") { loadDevices(); loadOverview(); } }, 30000);
