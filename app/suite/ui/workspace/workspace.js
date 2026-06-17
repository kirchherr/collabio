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
const sourceDetailPanel = document.querySelector("#source-detail-panel");

const storageKey = "collabio.workspace.context";
let currentCockpit = { modules: [], source_object_flows: [] };
let selectedFlowId = "";
let detailLoadToken = 0;

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
    const body = await readJson(response);
    if (!response.ok) {
      throw new Error(body.detail || `HTTP ${response.status}`);
    }
    currentCockpit = body;
    renderCockpit(body);
    setStatus(`Stand: ${new Date().toLocaleTimeString("de-DE")} | Audit ${body.audit_event_id}`);
  } catch (error) {
    currentCockpit = { modules: [], source_object_flows: [] };
    renderCockpit(currentCockpit);
    setStatus(error.message || "Cockpit konnte nicht geladen werden.", true);
  } finally {
    refreshButton.disabled = false;
  }
}

async function executeModuleAction(module, action) {
  const context = readContext();
  const confirmationText = `${action.label} für ${module.display_name} ausführen?\n\nZielstatus: ${action.targetStatus}\nTenant: ${context.tenantId}`;
  if (!window.confirm(confirmationText)) {
    setStatus("Aktion abgebrochen.");
    return;
  }

  const endpoint = `/v1/admin/tenant-modules/${encodeURIComponent(module.module_id)}/${action.apiAction}`;
  const payload = {
    approval_reference: approvalReferenceFor(module, action),
    reason: `Workspace cockpit controlled ${action.apiAction} for ${module.module_id}; explicit browser confirmation captured before API call.`,
  };
  setStatus(`${action.label} läuft ...`);
  try {
    const response = await fetch(endpoint, {
      method: "POST",
      headers: {
        ...headersForContext(context),
        "Content-Type": "application/json",
      },
      body: JSON.stringify(payload),
    });
    const body = await readJson(response);
    if (!response.ok) {
      throw new Error(body.detail || `HTTP ${response.status}`);
    }
    setStatus(`${module.display_name}: ${body.status} | Audit ${body.audit_chain_ref}`);
    await loadCockpit();
  } catch (error) {
    setStatus(error.message || "Modulaktion konnte nicht ausgeführt werden.", true);
  }
}

function renderCockpit(cockpit) {
  const modules = cockpit.modules || [];
  const flows = cockpit.source_object_flows || [];
  const hashFlowId = flowIdFromHash();
  moduleCount.textContent = String(modules.length);
  flowCount.textContent = String(flows.length);
  if (hashFlowId && flows.some((flow) => flow.flow_id === hashFlowId)) {
    selectedFlowId = hashFlowId;
  } else if (!selectedFlowId || !flows.some((flow) => flow.flow_id === selectedFlowId)) {
    selectedFlowId = flows[0]?.flow_id || "";
  }
  renderModules(modules);
  renderFlows(flows);
  loadSourceObjectDetail();
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
      ${moduleActions(module)}
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
      <td>
        <div class="flow-source-cell">
          <span class="status-pill ${originClass(flow.origin)}">${escapeHtml(flow.origin)}</span>
          <button
            class="detail-link"
            type="button"
            data-flow-id="${escapeHtml(flow.flow_id)}"
            aria-current="${selectedFlowId === flow.flow_id ? "true" : "false"}"
          >
            Details
          </button>
        </div>
      </td>
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

async function loadSourceObjectDetail() {
  const flow = (currentCockpit.source_object_flows || []).find((item) => item.flow_id === selectedFlowId);
  if (!flow) {
    renderSourceObjectDetail(null);
    return;
  }

  const token = detailLoadToken + 1;
  detailLoadToken = token;
  sourceDetailPanel.className = "detail-panel empty-state";
  sourceDetailPanel.textContent = "Lade metadata-only Detail ...";
  try {
    const response = await fetch(
      `/v1/source-objects/${encodeURIComponent(flow.source_object_id)}/versions/${encodeURIComponent(flow.source_version_id)}/metadata`,
      {
        headers: headersForContext(readContext()),
      },
    );
    const body = await readJson(response);
    if (!response.ok) {
      throw new DetailLoadError(response.status, body.detail || `HTTP ${response.status}`);
    }
    if (token === detailLoadToken) {
      renderSourceObjectDetail(body);
    }
  } catch (error) {
    if (token !== detailLoadToken) {
      return;
    }
    renderSourceObjectDetailError(error);
  }
}

class DetailLoadError extends Error {
  constructor(status, message) {
    super(message);
    this.name = "DetailLoadError";
    this.status = status;
  }
}

function renderSourceObjectDetailError(error) {
  const status = Number(error.status || 0);
  const state =
    status === 403
      ? {
          className: "denied",
          title: "Zugriff verweigert",
          detail: error.message || "Der aktuelle Nutzer darf diese SourceObject-Metadaten nicht lesen.",
        }
      : status === 404
        ? {
            className: "not-found",
            title: "Nicht gefunden",
            detail: error.message || "Fuer dieses SourceObject wurde kein Metadatenstand gefunden.",
          }
        : {
            className: "error",
            title: "Detailfehler",
            detail: error.message || "SourceObject-Detail konnte nicht geladen werden.",
          };
  sourceDetailPanel.className = `detail-panel error-state ${state.className}`;
  sourceDetailPanel.innerHTML = `
    <div class="detail-error-title">${escapeHtml(state.title)}</div>
    <div class="detail-error-detail">${escapeHtml(state.detail)}</div>
    <div class="detail-error-meta">HTTP ${status || "n/a"} | metadata_only | content_included=false</div>
  `;
}

function renderSourceObjectDetail(detail) {
  if (!detail) {
    sourceDetailPanel.className = "detail-panel empty-state";
    sourceDetailPanel.textContent = "Wähle einen autorisierten Flow aus.";
    return;
  }

  sourceDetailPanel.className = "detail-panel";
  sourceDetailPanel.innerHTML = `
    <div class="detail-summary">
      <h3>${escapeHtml(detail.title)}</h3>
      <span class="hash-text">${escapeHtml(detail.source_object_id)}:${escapeHtml(detail.source_version_id)}</span>
    </div>
    <dl class="detail-grid">
      ${detailItem("Quelle", detail.origin)}
      ${detailItem("Objekttyp", detail.source_object_type)}
      ${detailItem("Modul", detail.module_id || "workspace")}
      ${detailItem("Modulstatus", detail.module_status || "n/a")}
      ${detailItem("Klassifikation", detail.data_classification)}
      ${detailItem("Retention", detail.retention_policy_id)}
      ${detailItem("Legal Hold", detail.legal_hold_state)}
      ${detailItem("Lifecycle", detail.lifecycle_state)}
      ${detailItem("ACL Version", String(detail.acl_version))}
      ${detailItem("MIME", detail.mime_type)}
      ${detailItem("Bytes", String(detail.content_byte_length))}
      ${detailItem("KMS", detail.kms_key_ref)}
      ${detailItem("Manifest", detail.manifest_hash)}
      ${detailItem("Content Hash", detail.content_hash)}
      ${detailItem("Content", detail.content_included === true ? "content_included" : "metadata_only")}
      ${detailItem("Audit", detail.audit_chain_ref)}
      ${detailItem("Detail Audit", detail.audit_event_id)}
      ${detailItem("Access", detail.access_checked ? "checked" : "not_checked")}
    </dl>
    <div class="evidence-list">
      <strong>Evidence / Downstream</strong>
      ${evidenceList([...(detail.evidence_refs || []), ...(detail.downstream_surfaces || [])])}
    </div>
    <div class="preview-slot-list">
      <strong>Preview Slots</strong>
      ${previewSlotList(detail.preview_slots || [])}
    </div>
  `;
}

function moduleActions(module) {
  const action = moduleActionFor(module);
  if (!action) {
    return '<div class="module-actions"><span class="action-note">Keine direkte Admin-Aktion im Cockpit.</span></div>';
  }
  const disabled = canUseAdminActions() ? "" : " disabled";
  const note = canUseAdminActions() ? "Explizite Bestätigung vor Ausführung." : "Adminrolle fehlt im Kontext.";
  return `
    <div class="module-actions">
      <button
        class="action-button ${action.intent}"
        type="button"
        data-module-id="${escapeHtml(module.module_id)}"
        data-module-action="${escapeHtml(action.apiAction)}"
        ${disabled}
      >
        ${escapeHtml(action.label)}
      </button>
      <span class="action-note">${escapeHtml(note)}</span>
    </div>
  `;
}

function moduleActionFor(module) {
  if (module.status === "available") {
    return { apiAction: "provision", label: "Provisionieren", targetStatus: "disabled", intent: "primary" };
  }
  if (module.status === "disabled") {
    return { apiAction: "enable", label: "Aktivieren", targetStatus: "enabled", intent: "primary" };
  }
  if (module.status === "enabled") {
    return { apiAction: "disable", label: "Deaktivieren", targetStatus: "disabled", intent: "quiet" };
  }
  if (module.status === "suspended") {
    return { apiAction: "enable", label: "Reaktivieren", targetStatus: "enabled", intent: "primary" };
  }
  return null;
}

function canUseAdminActions() {
  const roles = new Set(readContext().roleIds.split(",").map((role) => role.trim()).filter(Boolean));
  return roles.has("tenant-admin") || roles.has("security-admin");
}

function approvalReferenceFor(module, action) {
  const stamp = new Date().toISOString().replace(/[-:.TZ]/g, "").slice(0, 14);
  return `approval:workspace-cockpit-${module.module_id}-${action.apiAction}-${stamp}`;
}

function selectFlow(flowId, updateHash = true) {
  selectedFlowId = flowId;
  if (updateHash && flowId) {
    const nextHash = `#source-object=${encodeURIComponent(flowId)}`;
    if (window.location.hash !== nextHash) {
      window.history.replaceState(null, "", nextHash);
    }
  }
  renderFlows(currentCockpit.source_object_flows || []);
  loadSourceObjectDetail();
}

function flowIdFromHash() {
  const hash = window.location.hash.replace(/^#/, "");
  if (!hash.startsWith("source-object=")) {
    return "";
  }
  try {
    return decodeURIComponent(hash.slice("source-object=".length));
  } catch {
    return "";
  }
}

function detailItem(label, value) {
  return `
    <div class="detail-item">
      <dt class="detail-label">${escapeHtml(label)}</dt>
      <dd class="detail-value"><code>${escapeHtml(value)}</code></dd>
    </div>
  `;
}

function evidenceList(values) {
  if (!values.length) {
    return "<span>Keine Evidence-Referenzen.</span>";
  }
  return values.map((value) => `<code>${escapeHtml(value)}</code>`).join("");
}

function previewSlotList(slots) {
  if (!slots.length) {
    return "<span>Keine Preview-Slots.</span>";
  }
  return slots
    .map(
      (slot) => `
        <div class="preview-slot">
          <span>${escapeHtml(slot.label)} | ${escapeHtml(slot.surface)}</span>
          <code>${escapeHtml(slot.render_contract || "metadata_only_no_source_content")} | content_included=${slot.content_included === true ? "true" : "false"}</code>
          <code>${escapeHtml(slot.blocking_reason || "policy_gate_required")}</code>
        </div>
      `,
    )
    .join("");
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
refreshButton.addEventListener("click", loadCockpit);
moduleGrid.addEventListener("click", (event) => {
  const button = event.target.closest("button[data-module-action]");
  if (!button) {
    return;
  }
  const module = (currentCockpit.modules || []).find((item) => item.module_id === button.dataset.moduleId);
  const action = module ? moduleActionFor(module) : null;
  if (module && action && action.apiAction === button.dataset.moduleAction) {
    executeModuleAction(module, action);
  }
});
flowTableBody.addEventListener("click", (event) => {
  const button = event.target.closest("button[data-flow-id]");
  if (button?.dataset.flowId) {
    selectFlow(button.dataset.flowId);
  }
});
window.addEventListener("hashchange", () => {
  const flowId = flowIdFromHash();
  if (flowId) {
    selectFlow(flowId, false);
  }
});
for (const input of Object.values(fields)) {
  input.addEventListener("change", loadCockpit);
}
loadCockpit();
