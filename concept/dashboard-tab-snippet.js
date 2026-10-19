// Dashboard tab snippet for concept/index.html (seabasskrahn/sonolumina)
// Add: <button class="nav-btn" data-tab="dash">Dashboard</button>
// Add: <section id="s-dash" class="tab">...cards container...</section>
// Wire into existing setTab() pattern (Read / Book / Visual).

const STATUS_URL = "http://100.89.107.88:8787/status";

async function loadStatus() {
  try {
    const r = await fetch(STATUS_URL);
    const s = await r.json();
    renderDashboard(s);
  } catch (e) {
    const el = document.getElementById("dash-cards");
    if (el) el.innerHTML = "<p class='err'>Box unreachable — " + e.message + "</p>";
  }
}

function renderDashboard(s) {
  const el = document.getElementById("dash-cards");
  if (!el) return;
  el.innerHTML = `
    <div class="card"><h3>Box</h3>
      <p>Uptime ${s.box.uptime_human}</p>
      <p>RAM ${s.box.ram_used_gb} / ${s.box.ram_total_gb} GB</p>
      <p>Disk ${s.box.disk_root_used_gb} / ${s.box.disk_root_total_gb} GB</p></div>
    <div class="card"><h3>1 TB Memory</h3>
      <p>${s.box.disk_1tb_used_gb} / ${s.box.disk_1tb_total_gb} GB used</p>
      <p class="flag">${s.shared_memory.flag}</p></div>
    <div class="card"><h3>Services</h3>
      ${Object.entries(s.services).map(([k, v]) =>
        `<p>${k}: <span class="st-${v}">${v}</span></p>`).join("")}</div>
    <div class="card"><h3>Agents</h3>
      ${Object.entries(s.agents).map(([k, v]) =>
        `<p>${k}: ${v.status}</p>`).join("")}</div>
    <div class="card"><h3>Relay</h3>
      <p>Last: ${s.relay.last_entry}</p>
      <p>Open for Merlin: ${s.relay.open_tasks_for_merlin}</p></div>
  `;
}

setInterval(() => {
  const tab = document.getElementById("s-dash");
  if (tab && tab.classList.contains("active")) loadStatus();
}, 30000);
