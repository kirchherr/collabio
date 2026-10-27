const fields = {
  tenantId: document.querySelector("#tenant-id"),
  userId: document.querySelector("#user-id"),
  roleIds: document.querySelector("#role-ids"),
};

const statusLine = document.querySelector("#status-line");
const refreshButton = document.querySelector("#refresh-button");
const summaryBand = document.querySelector("#summary-band");
const planBand = document.querySelector("#plan-band");
const groupStack = document.querySelector("#group-stack");
const detailPanel = document.querySelector("#detail-panel");
const filterButtons = Array.from(document.querySelectorAll("[data-status-filter]"));

const storageKey = "collabio.roadmap.context";
let currentRoadmap = null;
let currentFilter = "all";
let selectedCapabilityId = "";

function readContext() {
  return {
    tenantId: fields.tenantId.value.trim(),
    userId: fields.userId.value.trim(),
    roleIds: fields.roleIds.value.trim(),
  };
}

function writeContext(context) {
  fields.tenantId.value = context.tenantId || "tenant-demo";
  fields.userId.value = context.userId || "user-demo";
  fields.roleIds.value = context.roleIds || "tenant-admin";
}

function restoreContext() {
  const saved = window.localStorage.getItem(storageKey);
  if (!saved) {
    return;
  }
  try {
    writeContext(JSON.parse(saved));
  } catch {
    window.localStorage.removeItem(storageKey);
  }
}

function persistContext() {
  window.localStorage.setItem(storageKey, JSON.stringify(readContext()));
}

function headersForContext(context) {
  return {
    "X-Tenant-Id": context.tenantId,
    "X-User-Id": context.userId,
    "X-Role-Ids": context.roleIds,
  };
}

async function loadRoadmap() {
  const context = readContext();
  const headers = headersForContext(context);
  persistContext();
  setStatus("Lade Roadmap ...");
  refreshButton.disabled = true;
  try {
    const response = await fetch("/v1/platform/roadmap", { headers });
    const body = await readJson(response);
    if (!response.ok) {
      throw new Error(body.detail || `HTTP ${response.status}`);
    }
    const planResponse = await fetch("/v1/platform/roadmap/plan-snapshot", { headers });
    const planBody = await readJson(planResponse);
    if (!planResponse.ok) {
      throw new Error(planBody.detail || `HTTP ${planResponse.status}`);
    }
    currentRoadmap = body;
    selectedCapabilityId = selectedCapabilityId || firstCapability(body)?.capability_id || "";
    renderRoadmap(body);
    renderPlan(planBody);
    setStatus(`Stand: ${new Date().toLocaleTimeString("de-DE")} | ${body.schema_version}`);
  } catch (error) {
    currentRoadmap = null;
    renderEmpty();
    setStatus(error.message || "Roadmap konnte nicht geladen werden.", true);
  } finally {
    refreshButton.disabled = false;
  }
}

function renderRoadmap(roadmap) {
  renderSummary(roadmap);
  renderGroups(roadmap.groups || []);
  renderDetail(selectedCapability(roadmap));
}

function renderSummary(roadmap) {
  const summary = roadmap.summary || {};
  summaryBand.innerHTML = [
    '<div class="summary-header">',
    '<div class="summary-copy">',
    '<p class="eyebrow">Foundation Status</p>',
    '<h2>' + escapeHtml(roadmap.title || "Collabio Foundation Roadmap") + "</h2>",
    '<div class="summary-state">' + escapeHtml(roadmap.current_foundation_state || "metadata_only") + "</div>",
    "</div>",
    '<span class="status-pill status-metadata_only">' + escapeHtml(roadmap.current_focus || "foundation_review") + "</span>",
    "</div>",
    '<div class="metric-grid">',
    metric("Ready", summary.foundation_ready_count),
    metric("Operational", summary.operational_count),
    metric("Metadata", summary.metadata_only_count),
    metric("Guarded", summary.guarded_count),
    metric("Planned", summary.planned_count),
    metric("Deferred", summary.deferred_count),
    "</div>",
    '<div class="code-list">' + codeList("Evidence Contracts", roadmap.evidence_contracts || []) + "</div>",
  ].join("");
}

function metric(label, value) {
  return '<div class="metric"><span>' + escapeHtml(label) + "</span><strong>" + Number(value || 0) + "</strong></div>";
}
function renderPlan(snapshot) {
  if (!snapshot) {
    planBand.innerHTML = '<div class="empty-state">Keine Plan-Daten.</div>';
    return;
  }
  const items = snapshot.items || [];
  const summary = snapshot.summary || {};
  planBand.innerHTML = [
    '<div class="plan-header">',
    '<div class="summary-copy">',
    '<p class="eyebrow">Fahrplan</p>',
    '<h2>Jetzt, danach, spaeter</h2>',
    '<div class="plan-rule">' + escapeHtml(snapshot.decision_rule || "foundation_first") + "</div>",
    "</div>",
    '<span class="status-pill priority-next">' + Number(summary.total_count || items.length) + " Plan Items</span>",
    "</div>",
    '<div class="plan-grid">',
    planColumn("Jetzt", "now", items),
    planColumn("Danach", "next", items),
    planColumn("Spaeter", "later", items),
    "</div>",
  ].join("");
}

function planColumn(label, priority, items) {
  const filtered = items.filter((item) => item.priority === priority);
  return [
    '<section class="plan-column">',
    '<div class="plan-column-heading">',
    "<h3>" + escapeHtml(label) + "</h3>",
    '<span class="count-pill">' + Number(filtered.length) + "</span>",
    "</div>",
    '<div class="plan-list">',
    filtered.map(planCard).join("") || '<div class="plan-card empty-state">Keine Eintraege.</div>',
    "</div>",
    "</section>",
  ].join("");
}

function planCard(item) {
  return [
    '<article class="plan-card">',
    '<div class="plan-card-title">' + escapeHtml(item.title) + "</div>",
    "<p>" + escapeHtml(item.summary) + "</p>",
    '<span class="status-pill ' + priorityClass(item.priority) + '">' + escapeHtml(item.priority) + "</span>",
    "<code>" + escapeHtml(item.readiness_gate || "gate_pending") + "</code>",
    "</article>",
  ].join("");
}

function priorityClass(priority) {
  const normalized = String(priority || "next").replace(/[^a-z0-9_]/g, "_");
  if (["now", "next", "later"].includes(normalized)) {
    return "priority-" + normalized;
  }
  return "priority-next";
}


function renderGroups(groups) {
  groupStack.innerHTML = "";
  const filteredGroups = groups
    .map((group) => ({
      ...group,
      capabilities: (group.capabilities || []).filter((capability) =>
        currentFilter === "all" ? true : capability.status === currentFilter,
      ),
    }))
    .filter((group) => group.capabilities.length);
  if (!filteredGroups.length) {
    groupStack.innerHTML = '<div class="group-panel empty-state">Keine Capabilities fuer diesen Filter.</div>';
    renderDetail(null);
    return;
  }
  if (!filteredGroups.some((group) => group.capabilities.some((item) => item.capability_id === selectedCapabilityId))) {
    selectedCapabilityId = filteredGroups[0].capabilities[0].capability_id;
  }
  for (const group of filteredGroups) {
    const panel = document.createElement("section");
    panel.className = "group-panel";
    panel.innerHTML = [
      '<div class="group-header">',
      "<div>",
      '<p class="eyebrow">' + escapeHtml(group.group_id) + "</p>",
      "<h2>" + escapeHtml(group.title) + "</h2>",
      '<p class="group-summary">' + escapeHtml(group.summary) + "</p>",
      "</div>",
      '<span class="count-pill">' + Number(group.capabilities.length) + "</span>",
      "</div>",
      '<div class="capability-list">',
      group.capabilities.map(capabilityRow).join(""),
      "</div>",
    ].join("");
    groupStack.appendChild(panel);
  }
}

function capabilityRow(capability) {
  return [
    '<button class="capability-row" type="button" data-capability-id="' + escapeHtml(capability.capability_id) + '" aria-current="' + (selectedCapabilityId === capability.capability_id ? "true" : "false") + '">',
    '<span class="capability-copy">',
    "<h3>" + escapeHtml(capability.title) + "</h3>",
    '<span class="capability-summary">' + escapeHtml(capability.summary) + "</span>",
    '<span class="capability-meta"><code>' + escapeHtml(capability.capability_type) + "</code></span>",
    "</span>",
    '<span class="status-pill ' + statusClass(capability.status) + '">' + escapeHtml(capability.status) + "</span>",
    "</button>",
  ].join("");
}

function renderDetail(capability) {
  if (!capability) {
    detailPanel.innerHTML = '<div class="empty-state">Keine Capability ausgewählt.</div>';
    return;
  }
  detailPanel.innerHTML = [
    '<div class="detail-section">',
    '<p class="eyebrow">Capability</p>',
    "<h2>" + escapeHtml(capability.title) + "</h2>",
    '<p class="capability-summary">' + escapeHtml(capability.summary) + "</p>",
    "</div>",
    '<div class="detail-grid">',
    detailItem("Status", capability.status),
    detailItem("Type", capability.capability_type),
    detailItem("ID", capability.capability_id),
    detailItem("Next", capability.next_action || "foundation_ready"),
    "</div>",
    '<div class="detail-section"><div class="list-label">API Routes</div><div class="code-list">' + codeList("API Routes", capability.api_routes || []) + "</div></div>",
    '<div class="detail-section"><div class="list-label">Evidence</div><div class="code-list">' + codeList("Evidence", capability.evidence_refs || []) + "</div></div>",
    '<div class="detail-section"><div class="list-label">Guardrails</div><div class="code-list">' + codeList("Guardrails", capability.guardrails || []) + "</div></div>",
  ].join("");
}

function detailItem(label, value) {
  return [
    '<div class="detail-item">',
    '<div class="detail-label">' + escapeHtml(label) + "</div>",
    '<div class="detail-value"><code>' + escapeHtml(value || "n/a") + "</code></div>",
    "</div>",
  ].join("");
}

function codeList(label, values) {
  if (!values.length) {
    return "<code>" + escapeHtml(label) + ": none</code>";
  }
  return values.map((value) => "<code>" + escapeHtml(value) + "</code>").join("");
}

function selectedCapability(roadmap) {
  return allCapabilities(roadmap).find((capability) => capability.capability_id === selectedCapabilityId) || firstCapability(roadmap);
}

function firstCapability(roadmap) {
  return allCapabilities(roadmap)[0] || null;
}

function allCapabilities(roadmap) {
  return (roadmap?.groups || []).flatMap((group) => group.capabilities || []);
}

function setFilter(filter) {
  currentFilter = filter;
  for (const button of filterButtons) {
    button.classList.toggle("active", button.dataset.statusFilter === filter);
  }
  if (currentRoadmap) {
    renderRoadmap(currentRoadmap);
  }
}

function renderEmpty() {
  summaryBand.innerHTML = '<div class="empty-state">Keine Roadmap-Daten.</div>';
  planBand.innerHTML = '<div class="empty-state">Keine Plan-Daten.</div>';
  groupStack.innerHTML = "";
  renderDetail(null);
}

function statusClass(status) {
  const normalized = String(status || "planned").replace(/[^a-z0-9_]/g, "_");
  if (["operational", "metadata_only", "guarded", "planned", "deferred"].includes(normalized)) {
    return "status-" + normalized;
  }
  return "status-planned";
}

function setStatus(message, isError = false) {
  statusLine.textContent = message;
  statusLine.classList.toggle("error", isError);
}

async function readJson(response) {
  try {
    return await response.json();
  } catch {
    return {};
  }
}

function escapeHtml(value) {
  return String(value ?? "")
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#039;");
}

restoreContext();
refreshButton.addEventListener("click", loadRoadmap);
for (const input of Object.values(fields)) {
  input.addEventListener("change", loadRoadmap);
}
for (const button of filterButtons) {
  button.addEventListener("click", () => setFilter(button.dataset.statusFilter || "all"));
}
groupStack.addEventListener("click", (event) => {
  const button = event.target.closest("button[data-capability-id]");
  if (!button) {
    return;
  }
  selectedCapabilityId = button.dataset.capabilityId || "";
  if (currentRoadmap) {
    renderRoadmap(currentRoadmap);
  }
});
loadRoadmap();
