"use strict";
let csrf = "";
const el = id => document.getElementById(id);
const report = e => { el("message").textContent = String(e.message || e); };
async function api(path, options = {}) {
  options.headers = {...options.headers, "X-CSRF-Token": csrf};
  const response = await fetch("api/" + path, options);
  if (!response.ok) { const text = await response.text(); throw new Error(text.slice(0, 300)); }
  return response.json();
}
function button(parent, text, action) {
  const b = document.createElement("button"); b.type = "button"; b.textContent = text;
  b.onclick = () => Promise.resolve().then(action).catch(report); parent.append(b);
}
async function people() {
  const list = await api("people"); el("people").replaceChildren();
  const select = el("filter-person"); select.replaceChildren(new Option("All people", ""));
  for (const p of list) {
    select.add(new Option(p.name, p.id));
    const row = document.createElement("article");
    const title = document.createElement("p"); title.textContent = `${p.name} · ${p.template_count} templates · trusted: ${!!p.trusted}`; row.append(title);
    button(row, "Rename", async () => { const name = prompt("New name", p.name); if (name) await api("people/" + p.id, {method:"PATCH",headers:{"Content-Type":"application/json"},body:JSON.stringify({name})}); await people(); });
    button(row, "Toggle trusted", async () => { await api("people/" + p.id,{method:"PATCH",headers:{"Content-Type":"application/json"},body:JSON.stringify({trusted:!p.trusted})}); await people(); });
    button(row, "Replace templates", () => { el("person-id").value=p.id; el("person-name").value=p.name; el("person-trusted").checked=!!p.trusted; el("enroll").scrollIntoView(); });
    button(row, "Delete person", async () => { if (confirm("Delete biometric templates and redact this person's event identities?")) { await api("people/"+p.id,{method:"DELETE"}); await people(); await history(); } });
    el("people").append(row);
  }
}
async function history() {
  const query = new URLSearchParams(new FormData(el("filter")));
  const events = await api("history?" + query); el("history").replaceChildren();
  if (!events.length) el("history").textContent = "No events in this filter.";
  for (const e of events) {
    const row = document.createElement("article");
    const line = document.createElement("p"); line.textContent = `${e.local_time} · ${e.corrected_identity || e.identity} · ${e.status} · score ${e.score === null ? "—" : e.score.toFixed(3)} · faces ${e.face_count}`; row.append(line);
    const detail = document.createElement("small"); detail.textContent = `Freshness: ${e.freshness}; trusted label: ${!!e.trusted}; ${e.duration_ms} ms; ID ${e.id}${e.error ? "; " + e.error : ""}${e.corrected_identity ? "; original: " + e.identity : ""}`; row.append(detail);
    if (e.snapshot) button(row, "View private snapshot", () => { const existing = row.querySelector("img"); if (existing) { existing.remove(); return; } const img = document.createElement("img"); img.src="api/history/"+encodeURIComponent(e.id)+"/image"; img.alt="Visitor snapshot"; row.append(img); });
    button(row, "Correct label", async () => { const identity=prompt("Corrected identity (does not retrain)",e.corrected_identity || e.identity); if(identity) await api("history/"+e.id,{method:"PATCH",headers:{"Content-Type":"application/json"},body:JSON.stringify({identity})}); await history(); });
    button(row, "Delete record", async () => { if(confirm("Delete this event and its retained image?")){await api("history/"+e.id,{method:"DELETE"}); await history();} });
    el("history").append(row);
  }
}
el("enroll").onsubmit=async event=>{event.preventDefault();try{el("message").textContent="Validating photos…";const r=await api("people",{method:"POST",body:new FormData(event.target)});el("message").textContent="Saved. "+r.warnings.join("; ");event.target.reset();await people();}catch(e){report(e);}};
el("filter").onsubmit=event=>{event.preventDefault();history().catch(report);};
el("retention").onsubmit=async event=>{event.preventDefault();try{const f=new FormData(event.target);await api("retention",{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify({history_days:Number(f.get("history_days")),image_days:Number(f.get("image_days"))})});el("message").textContent="Retention saved and expired images purged.";await history();}catch(e){report(e);}};
(async()=>{const s=await api("session");csrf=s.csrf;el("health").textContent=`Worker: ${s.health}; snapshot wait: ${s.capture_timeout}s; engine peak: ${(s.engine_peak_rss_kib/1024).toFixed(1)} MiB (engine only)`;el("retention").elements.history_days.value=s.history_days;el("retention").elements.image_days.value=s.image_days;await people();await history();})().catch(report);

let lastCaptureStatus = "";
let lastHistoryCaptureKey;
async function refreshCaptureStatus() {
  const s = await api("capture-status");
  const key = JSON.stringify(s);
  if (key === lastCaptureStatus) return;
  lastCaptureStatus = key;
  const box = el("capture-status"); box.replaceChildren();
  const connection = document.createElement("p");
  connection.textContent = `App ${s.version}; MQTT: ${s.mqtt_connected ? "connected" : "disconnected"}; worker: ${s.health}; last command: ${s.last_command_at ? new Date(s.last_command_at).toLocaleString() : "none since startup"} (${s.last_command_result}).`;
  box.append(connection);
  const row = document.createElement("p");
  const e = s.latest;
  row.textContent = e ? `Last capture: ${e.local_time} · ${e.status} · ${e.face_count} detected faces${e.error ? " · " + e.error : ""}` : "No capture has reached visitor history yet. Check the HA automation trace if a manual capture produces no command.";
  box.append(row);
  if (e && e.image_metadata) {
    try {
      const meta=JSON.parse(e.image_metadata);
      const source=document.createElement("p");
      source.textContent=meta.source === "ring_completed_recording"
        ? `Source: completed Ring recording ${meta.recording_id}; selected frame at ${meta.selected_seconds}s; sampled ${meta.sampled_seconds.join(", ")}s. Delayed recording analysis; source authenticity/freshness unverified.`
        : "Source: HA camera snapshot. Ring may supply a cached recording still; this is not the Ring app's live feed. Use the completed-recording automation for recorded visitors.";
      box.append(source);
    } catch (_) { /* Older diagnostic metadata can be absent. */ }
  }
  if (e && e.status === "no_face") {
    const note = document.createElement("p");
    note.textContent = "Capture ran, but the detector found no face. This event is hidden from normal visitor history. Ring may return an early or cached frame; source freshness remains unverified.";
    box.append(note);
  }
  if (e && e.snapshot) button(box, "View latest private snapshot", () => {
    let img = box.querySelector("img"); if (img) { img.remove(); return; }
    img = document.createElement("img"); img.src = "api/history/"+encodeURIComponent(e.id)+"/image"; img.alt="Latest capture"; box.append(img);
  });
  if (s.image_days === 0) {
    const note = document.createElement("p"); note.textContent = "Snapshot retention is disabled. Set Image days above 0 to view new pictures."; box.append(note);
  }
  const captureKey = e ? JSON.stringify([e.id, e.attempt, e.status, e.snapshot]) : null;
  if (lastHistoryCaptureKey !== undefined && lastHistoryCaptureKey !== captureKey) await history();
  lastHistoryCaptureKey = captureKey;
}
refreshCaptureStatus().catch(report);
setInterval(() => { if (!document.hidden) refreshCaptureStatus().catch(report); }, 10000);
