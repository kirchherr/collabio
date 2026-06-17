const fields = {
  tenantId: document.querySelector("#tenant-id"),
  userId: document.querySelector("#user-id"),
  roleIds: document.querySelector("#role-ids"),
  readableObjectIds: document.querySelector("#readable-object-ids"),
};

const statusLine = document.querySelector("#status-line");
const refreshButton = document.querySelector("#refresh-button");
const moduleGrid = document.querySelector("#module-grid");
const flowTableBody = document.querySelector("#flow-table-body");
const moduleCount = document.querySelector("#module-count");
const flowCount = document.querySelector("#flow-count");

const storageKey = "collabio.workspace.context";

function readContext() {
  return {
    tenantId: fields.tenantId.value.trim(),
    userId: fields.userId.value.trim(),
    roleIds: fields.roleIds.value.trim(),
    readableObjectIds: fields.readableObjectIds.value.trim(),
  };
}

function writeContext(context) {
  fields.tenantId.value = context.tenantId || "tenant-demo";
  fields.userId.value = context.userId || "user-demo";
  fields.roleIds.value = context.roleIds || "tenant-admin";
  fields.readableObjectIds.value = context.readableObjectIds || "doc-1,mail-1";
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
    "X-Readable-Object-Ids": context.readableObjectIds,
  };
}

async function loadCockpit() {
  const context = readContext();
  persistContext();
  setStatus("Lade Cockpit ...");
  refreshButton.disabled = true;
  try {
    const response = await fetch("/v1/platform/cockpit", {
      headers: headersForContext(context),
    });
    const body = await response.json();
    if (!response.ok) {
      throw new Error(body.detail || `HTTP ${response.status}`);
    }
    renderCockpit(body);
    setStatus(`Stand: ${new Date().toLocaleTimeString("de-DE")} | Audit ${body.audit_event_id}`);
  } catch (error) {
    renderCockpit({ modules: [], source_object_flows: [] });
    setStatus(error.message || "Cockpit konnte nicht geladen werden.", true);
  } finally {
    refreshButton.disabled = false;
  }
}

function renderCockpit(cockpit) {
  const modules = cockpit.modules || [];
  const flows = cockpit.source_object_flows || [];
  moduleCount.textContent = String(modules.length);
  flowCount.textContent = String(flows.length);
  renderModules(modules);
  renderFlows(flows);
}

function renderModules(modules) {
  moduleGrid.innerHTML = "";
  if (!modules.length) {
    moduleGrid.innerHTML = '<div class="empty-state">Keine Modulzeilen verfügbar.</div>';
    return;
  }
  for (const module of modules) {
    const row = document.createElement("article");
    row.className = "module-row";
    row.innerHTML = `
      <div class="module-title">
        <div>
          <strong>${escapeHtml(module.display_name)}</strong>
          <div class="module-route-list">${routes(module.primary_routes)}</div>
        </div>
        <span class="status-pill ${statusClass(module.status)}">${escapeHtml(module.status)}</span>
      </div>
      <div class="module-meta-list">
        <span>Domain: ${escapeHtml(module.continuity_domain)}</span>
        <span>Aktive Features: ${Number(module.enabled_feature_count || 0)}</span>
        <span>Normalbetrieb: ${module.normal_use_enabled ? "aktiv" : "gesperrt"}</span>
        <span>Nächste Aktion: ${escapeHtml(module.next_action)}</span>
      </div>
    `;
    moduleGrid.appendChild(row);
  }
}

function renderFlows(flows) {
  flowTableBody.innerHTML = "";
  if (!flows.length) {
    const empty = document.createElement("tr");
    empty.innerHTML = '<td colspan="6" class="empty-state">Keine autorisierten SourceObject-Flows.</td>';
    flowTableBody.appendChild(empty);
    return;
  }
  for (const flow of flows) {
    const row = document.createElement("tr");
    const contentState = flow.content_included === true ? "content_included" : "metadata_only";
    row.innerHTML = `
      <td><span class="status-pill ${originClass(flow.origin)}">${escapeHtml(flow.origin)}</span></td>
      <td>
        <div class="flow-title">
          <strong>${escapeHtml(flow.title)}</strong>
          <span class="hash-text">${escapeHtml(flow.source_object_id)}:${escapeHtml(flow.source_version_id)}</span>
        </div>
      </td>
      <td>${escapeHtml(flow.source_object_type)}</td>
      <td>${escapeHtml(flow.data_classification)}</td>
      <td>${escapeHtml(flow.retention_policy_id)}</td>
      <td>
        <div class="flow-title">
          <span>${escapeHtml(contentState)}</span>
          <span class="hash-text">${escapeHtml(flow.manifest_hash)}</span>
          <span class="hash-text">${escapeHtml(flow.content_hash)}</span>
        </div>
      </td>
    `;
    flowTableBody.appendChild(row);
  }
}

function routes(values) {
  if (!values || !values.length) {
    return "<span>Keine Route</span>";
  }
  return values.map((route) => `<code>${escapeHtml(route)}</code>`).join("");
}

function statusClass(status) {
  const normalized = String(status || "other").replace(/[^a-z0-9_]/g, "_");
  if (["enabled", "available", "disabled", "suspended", "decommission_requested", "decommission_blocked"].includes(normalized)) {
    return `status-${normalized}`;
  }
  return "status-other";
}

function originClass(origin) {
  if (origin === "knowledge_base") {
    return "status-enabled";
  }
  if (origin === "mail") {
    return "status-other";
  }
  return "status-available";
}

function setStatus(message, isError = false) {
  statusLine.textContent = message;
  statusLine.classList.toggle("error", isError);
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
refreshButton.addEventListener("click", loadCockpit);
for (const input of Object.values(fields)) {
  input.addEventListener("change", loadCockpit);
}
loadCockpit();
