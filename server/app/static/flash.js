"use strict";
// Mise en service d'un écran depuis le navigateur :
//  1. flash de l'image complète via ESP Web Tools (Web Serial)
//  2. provisioning série (protocole texte du firmware : INFO / SET / GET / DONE)
//  3. enregistrement de l'écran (nom, salle, IP) côté serveur

const $ = (s) => document.querySelector(s);
const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

async function api(path, opts = {}) {
  const r = await fetch(path, opts);
  if (!r.ok) {
    let msg = r.statusText;
    try { msg = (await r.json()).detail || msg; } catch {}
    throw new Error(msg);
  }
  return r.json();
}

if (!("serial" in navigator) || !window.isSecureContext) $("#no-serial").hidden = false;

// ------------------------------------------------------------------ 1. flash
async function loadFirmwares() {
  const fws = (await api("/api/firmware")).filter((f) => f.factory_filename);
  const sel = $("#fw-version");
  if (!fws.length) { $("#fw-none").hidden = false; sel.disabled = true; return; }
  fws.sort((a, b) => (b.active - a.active) || b.uploaded_at.localeCompare(a.uploaded_at));
  sel.innerHTML = fws.map((f) => `<option value="${esc(f.version)}">${esc(f.version)}${f.active ? " (active)" : ""}</option>`).join("");
  const render = () => {
    const v = encodeURIComponent(sel.value);
    $("#install-slot").innerHTML = `
      <esp-web-install-button manifest="/api/v1/firmware/${v}/manifest.json">
        <button slot="activate" class="primary">Flasher la version ${esc(sel.value)}</button>
        <span slot="unsupported" class="report err">Navigateur non compatible (Chrome/Edge requis, en HTTPS).</span>
        <span slot="not-allowed" class="report err">Page non sécurisée : ouvrez-la en HTTPS ou depuis localhost.</span>
      </esp-web-install-button>`;
  };
  sel.onchange = render;
  render();
}

// ------------------------------------------------------------------ 2. provisioning
const logEl = $("#log");
function log(line, cls = "") {
  logEl.hidden = false;
  logEl.insertAdjacentHTML("beforeend", `<span class="${cls}">${esc(line)}</span>\n`);
  logEl.scrollTop = logEl.scrollHeight;
}

class SerialLines {
  constructor(port) {
    this.port = port;
    this.lines = [];
    this.waiters = [];
    this.buf = "";
    this.closed = false;
  }
  async start() {
    const dec = new TextDecoderStream();
    this.pipe = this.port.readable.pipeTo(dec.writable).catch(() => {});
    this.reader = dec.readable.getReader();
    (async () => {
      try {
        while (true) {
          const { value, done } = await this.reader.read();
          if (done) break;
          this.buf += value;
          let i;
          while ((i = this.buf.indexOf("\n")) >= 0) {
            const line = this.buf.slice(0, i).replace(/\r$/, "").trim();
            this.buf = this.buf.slice(i + 1);
            if (!line) continue;
            log("< " + line, "in");
            this.lines.push(line);
            this.waiters = this.waiters.filter((w) => !w(line));
          }
        }
      } catch {}
    })();
  }
  waitFor(pred, timeoutMs) {
    return new Promise((resolve, reject) => {
      const t = setTimeout(() => reject(new Error("délai dépassé")), timeoutMs);
      this.waiters.push((line) => { if (pred(line)) { clearTimeout(t); resolve(line); return true; } return false; });
    });
  }
  async send(text, secret = false) {
    log("> " + (secret ? text.replace(/=.*/, "=***") : text), "out");
    const w = this.port.writable.getWriter();
    await w.write(new TextEncoder().encode(text + "\n"));
    w.releaseLock();
  }
  async cmd(text, expect, timeoutMs = 3000, secret = false) {
    const p = this.waitFor((l) => expect.some((e) => l.startsWith(e)) || l.startsWith("ERR"), timeoutMs);
    await this.send(text, secret);
    const line = await p;
    if (line.startsWith("ERR")) throw new Error("L'écran a refusé : " + line);
    return line;
  }
  async close() {
    try { await this.reader.cancel(); } catch {}
    try { await this.pipe; } catch {}
    try { await this.port.close(); } catch {}
  }
}

async function provision(ev) {
  ev.preventDefault();
  const f = Object.fromEntries(new FormData(ev.target));
  const btn = $("#prov-btn");
  $("#prov-result").innerHTML = "";
  logEl.innerHTML = "";
  if (!f.dhcp && f.ip && !/^\d{1,3}(\.\d{1,3}){3}$/.test(f.ip.trim())) {
    $("#prov-result").innerHTML = '<div class="report err">Adresse IP invalide.</div>';
    return;
  }

  let port;
  try {
    port = await navigator.serial.requestPort();
  } catch {
    return; // l'utilisateur a fermé le sélecteur
  }
  btn.disabled = true;
  const s = new SerialLines(port);
  try {
    await port.open({ baudRate: 115200 });
    await s.start();

    // Redémarrage de la carte (même séquence qu'esptool) pour ouvrir la fenêtre de provisioning
    log("Redémarrage de l'écran…", "info");
    await port.setSignals({ dataTerminalReady: false, requestToSend: true });
    await sleep(150);
    await port.setSignals({ requestToSend: false });

    let ready;
    try {
      ready = await s.waitFor((l) => l.startsWith("PROVISION READY"), 8000);
    } catch {
      log("Pas de réponse. Appuyez sur le bouton reset de l'écran (30 s)…", "info");
      ready = await s.waitFor((l) => l.startsWith("PROVISION READY"), 30000);
    }
    const mac = (ready.match(/mac=(\S+)/) || [])[1];
    await s.cmd("INFO", ["INFO"]);

    if (f.clear) await s.cmd("CLEAR", ["OK"]);
    const sets = [];
    if (f.dhcp) sets.push(["ip", ""]);
    else if (f.ip) sets.push(["ip", f.ip.trim()]);
    for (const k of ["gw", "mask", "dns", "ssid", "pass", "server"]) if (f[k]) sets.push([k, f[k].trim()]);
    for (const [k, v] of sets) await s.cmd(`SET ${k}=${v}`, ["OK"], 3000, k === "pass");
    const cfg = await s.cmd("GET", ["CFG"]);
    await s.cmd("DONE", ["OK DONE"]);
    await s.close();

    const ip = (cfg.match(/ip=(\S+)/) || [])[1];
    await api(`/api/provision/${encodeURIComponent(mac)}?ip=${encodeURIComponent(ip && ip !== "dhcp" ? ip : "")}`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ ...(f.name ? { name: f.name } : {}), ...(f.room_code ? { room_code: f.room_code } : {}) }),
    });
    $("#prov-result").innerHTML = `<div class="report">
      <b>Écran ${esc(mac)} configuré.</b><br>
      IP : ${esc(ip)} · Salle : ${esc(f.room_code || "non affecté")}<br>
      Il redémarre et affiche sa salle d'ici quelques secondes. S'il n'y parvient pas, il affiche un écran de
      diagnostic (Wi-Fi ou serveur injoignable).</div>`;
    ev.target.reset();
    suggestIp();
  } catch (err) {
    log("Erreur : " + err.message, "err");
    $("#prov-result").innerHTML = `<div class="report err">${esc(err.message)}</div>`;
    await s.close();
  } finally {
    btn.disabled = false;
  }
}

async function suggestIp() {
  const r = await api("/api/provision/next-ip");
  if (r.ip) $("#prov-form").ip.value = r.ip;
  $("#prov-form").ip.placeholder = r.ip || (r.reason ? `(${r.reason})` : "10.20.0.31");
}

async function loadRooms() {
  const rooms = await api("/api/rooms");
  $("#prov-form").room_code.innerHTML = '<option value="">— plus tard —</option>' +
    rooms.map((r) => `<option value="${esc(r.code)}">${esc(r.code)}${r.name ? " — " + esc(r.name) : ""}${r.devices.length ? " (déjà " + r.devices.length + " écran)" : ""}</option>`).join("");
}

$("#prov-form").addEventListener("submit", provision);
loadFirmwares();
loadRooms();
suggestIp();
