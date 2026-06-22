const fields = {
  tenantId: document.querySelector("#tenant-id"),
  userId: document.querySelector("#user-id"),
  roleIds: document.querySelector("#role-ids"),
  readableObjectIds: document.querySelector("#readable-object-ids"),
};

const statusLine = document.querySelector("#status-line");
const mvpReadinessPanel = document.querySelector("#mvp-readiness-panel");
const snapshotButton = document.querySelector("#snapshot-button");
const refreshButton = document.querySelector("#refresh-button");
const moduleGrid = document.querySelector("#module-grid");
const workEvidencePanel = document.querySelector("#work-evidence-panel");
const workItemList = document.querySelector("#work-item-list");
const flowTableBody = document.querySelector("#flow-table-body");
const moduleCount = document.querySelector("#module-count");
const workItemCount = document.querySelector("#work-item-count");
const flowCount = document.querySelector("#flow-count");
const sourceDetailPanel = document.querySelector("#source-detail-panel");
const readinessCounts = {
  metadataReady: document.querySelector("#metadata-ready-count"),
  previewPending: document.querySelector("#preview-pending-count"),
  previewBlocked: document.querySelector("#preview-blocked-count"),
  evidenceComplete: document.querySelector("#preview-evidence-complete-count"),
};

const storageKey = "collabio.workspace.context";
let currentCockpit = {
  modules: [],
  source_object_flows: [],
  flow_readiness_summary: {},
  work_items: [],
  work_item_operational_summary: null,
  mvp_readiness_summary: null,
  foundation_gap_actions: [],
};
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
    currentCockpit = {
      modules: [],
      source_object_flows: [],
      flow_readiness_summary: {},
      work_items: [],
      work_item_operational_summary: null,
      mvp_readiness_summary: null,
      foundation_gap_actions: [],
    };
    renderCockpit(currentCockpit);
    setStatus(error.message || "Cockpit konnte nicht geladen werden.", true);
  } finally {
    refreshButton.disabled = false;
  }
}

async function downloadMvpSnapshot() {
  const context = readContext();
  persistContext();
  snapshotButton.disabled = true;
  setStatus("MVP-Snapshot wird erzeugt ...");
  try {
    const response = await fetch("/v1/platform/cockpit/mvp-snapshot", {
      headers: headersForContext(context),
    });
    const body = await readJson(response);
    if (!response.ok) {
      throw new Error(body.detail || "HTTP " + response.status);
    }
    const serialized = JSON.stringify(body, null, 2);
    const blob = new Blob([serialized], { type: "application/json" });
    const url = URL.createObjectURL(blob);
    const link = document.createElement("a");
    link.href = url;
    link.download = "collabio-mvp-snapshot-" + safeRefPart(body.audit_event_id || "snapshot") + ".json";
    document.body.appendChild(link);
    link.click();
    link.remove();
    URL.revokeObjectURL(url);
    setStatus("MVP-Snapshot exportiert | Audit " + body.audit_event_id);
  } catch (error) {
    setStatus(error.message || "MVP-Snapshot konnte nicht erzeugt werden.", true);
  } finally {
    snapshotButton.disabled = false;
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

async function executeGuidedPreviewDecision(flow) {
  const context = readContext();
  const slot = previewSlotForFlow(flow);
  const gate = slot?.gate || {};
  if (!slot?.slot_id || !gate.policy_id) {
    setStatus("Preview-Gate fehlt fuer diesen Flow.", true);
    return;
  }

  const confirmationText = `Metadata-only Preview-Evidence und Preview-Decision fuer ${flow.source_object_id}:${flow.source_version_id} anfordern?\n\nEs werden keine Inhalte gerendert, keine Rohdaten freigegeben und content_release_allowed bleibt policy-gesteuert blockiert.`;
  if (!window.confirm(confirmationText)) {
    setStatus("Preview-Flow abgebrochen.");
    return;
  }

  const refs = metadataEvidenceRefsFor(flow);
  const baseEndpoint = `/v1/source-objects/${encodeURIComponent(flow.source_object_id)}/versions/${encodeURIComponent(flow.source_version_id)}`;
  const sharedPayload = {
    preview_slot_id: slot.slot_id,
    preview_policy_id: gate.policy_id,
    parser_sanitizer_evidence_ref: refs.parserSanitizer,
    backup_coverage_evidence_ref: refs.backupCoverage,
    restore_evidence_ref: refs.restore,
  };

  setStatus(`Renderer-Sandbox-Evidence fuer ${flow.source_object_id}:${flow.source_version_id} wird erfasst ...`);
  try {
    const rendererResponse = await fetch(`${baseEndpoint}/preview-renderer-runs`, {
      method: "POST",
      headers: {
        ...headersForContext(context),
        "Content-Type": "application/json",
      },
      body: JSON.stringify({
        ...sharedPayload,
        reason: `Workspace guided metadata-only preview renderer evidence for ${flow.source_object_id}:${flow.source_version_id}; no source content, rendered content or raw payload is requested.`,
      }),
    });
    const rendererBody = await readJson(rendererResponse);
    if (!rendererResponse.ok) {
      throw new Error(rendererBody.detail || `HTTP ${rendererResponse.status}`);
    }
    if (!rendererBody.renderer_sandbox_evidence_ref) {
      throw new Error("Renderer-Sandbox-Evidence fehlt in der Antwort.");
    }

    setStatus(`Preview-Decision fuer ${flow.source_object_id}:${flow.source_version_id} wird angefordert ...`);
    const decisionResponse = await fetch(`${baseEndpoint}/preview-decisions`, {
      method: "POST",
      headers: {
        ...headersForContext(context),
        "Content-Type": "application/json",
      },
      body: JSON.stringify({
        ...sharedPayload,
        renderer_sandbox_evidence_ref: rendererBody.renderer_sandbox_evidence_ref,
        human_confirmation_reference: refs.humanConfirmation,
        reason: `Workspace guided metadata-only preview decision for ${flow.source_object_id}:${flow.source_version_id}; no content rendering or raw data release requested.`,
      }),
    });
    const decisionBody = await readJson(decisionResponse);
    if (!decisionResponse.ok) {
      throw new Error(decisionBody.detail || `HTTP ${decisionResponse.status}`);
    }

    selectedFlowId = flow.flow_id;
    setStatus(`Preview-Decision: ${decisionBody.decision_status || "recorded"} | ${decisionBody.decision_ledger_ref || "ledger_ref_pending"}`);
    await loadCockpit();
  } catch (error) {
    setStatus(error.message || "Preview-Decision-Flow konnte nicht ausgefuehrt werden.", true);
  }
}

function renderCockpit(cockpit) {
  const modules = cockpit.modules || [];
  const flows = cockpit.source_object_flows || [];
  const hashFlowId = flowIdFromHash();
  const readinessSummary = cockpit.flow_readiness_summary || {};
  const workItems = cockpit.work_items || [];
  const workSummary = cockpit.work_item_operational_summary || {};
  const mvpSummary = cockpit.mvp_readiness_summary || {};
  const foundationGapActions = cockpit.foundation_gap_actions || [];
  moduleCount.textContent = String(modules.length);
  workItemCount.textContent = String(workItems.length);
  flowCount.textContent = String(flows.length);
  readinessCounts.metadataReady.textContent = String(readinessSummary.metadata_ready_flow_count || 0);
  readinessCounts.previewPending.textContent = String(readinessSummary.preview_decision_pending_count || 0);
  readinessCounts.previewBlocked.textContent = String(readinessSummary.preview_decision_blocked_count || 0);
  readinessCounts.evidenceComplete.textContent = String(
    readinessSummary.preview_evidence_complete_but_content_blocked_count || 0,
  );
  if (hashFlowId && flows.some((flow) => flow.flow_id === hashFlowId)) {
    selectedFlowId = hashFlowId;
  } else if (!selectedFlowId || !flows.some((flow) => flow.flow_id === selectedFlowId)) {
    selectedFlowId = flows[0]?.flow_id || "";
  }
  renderModules(modules);
  renderMvpReadinessSummary(mvpSummary, foundationGapActions);
  renderWorkItemOperationalSummary(workSummary);
  renderWorkItems(workItems);
  renderFlows(flows);
  loadSourceObjectDetail();
}

function renderMvpReadinessSummary(summary, foundationGapActions) {
  if (!summary || !summary.schema_version) {
    mvpReadinessPanel.innerHTML = '<div class="empty-state compact">Keine MVP-Readiness-Evidence.</div>';
    return;
  }
  const stateClass = summary.mvp_entry_ready === true ? "mvp-ready" : "mvp-gapped";
  const stateLabel = summary.mvp_entry_ready === true ? "entry_ready" : "foundation_gaps";
  mvpReadinessPanel.innerHTML = [
    '<div class="mvp-readiness-header">',
    '<div><p class="eyebrow">MVP Startpunkt</p><h2>Workspace Cockpit</h2></div>',
    '<span class="status-pill ' + stateClass + '">' + stateLabel + '</span>',
    '</div>',
    '<div class="mvp-readiness-grid">',
    mvpReadinessMetric("Surfaces", summary.ready_surface_count),
    mvpReadinessMetric("Gaps", summary.foundation_gap_count),
    mvpReadinessMetric("Deferred", summary.deferred_item_count),
    mvpReadinessMetric("Gap actions", foundationGapActions.length),
    '</div>',
    '<div class="mvp-readiness-next"><span>Naechste Foundation-Aktion</span><code>',
    escapeHtml(summary.next_foundation_action || "continue_foundation_review"),
    '</code></div>',
    '<div class="mvp-readiness-tags">',
    mvpReadinessTagList("Ready", summary.ready_surfaces || []),
    mvpReadinessTagList("Foundation", summary.foundation_gaps || []),
    mvpReadinessTagList("Deferred", summary.deferred_items || []),
    '</div>',
    renderFoundationGapActionPlan(foundationGapActions),
    '<div class="mvp-readiness-contract"><code>',
    escapeHtml(summary.schema_version),
    ' | content_included=' + (summary.content_included === true ? "true" : "false"),
    ' | persistent_task_created=' + (summary.persistent_task_created === true ? "true" : "false"),
    '</code></div>',
  ].join("");
}

function renderFoundationGapActionPlan(actions) {
  if (!actions.length) {
    return '<div class="foundation-gap-plan empty-state compact">Keine Foundation-Gap-Aktionen.</div>';
  }
  const items = actions.map((action) => [
    '<div class="foundation-gap-action" data-foundation-gap-id="' + escapeHtml(action.gap_id) + '">',
    '<span class="status-pill ' + foundationGapStatusClass(action.status) + '">' + escapeHtml(action.status) + '</span>',
    '<div class="foundation-gap-copy">',
    '<strong>#' + Number(action.priority || 0) + ' ' + escapeHtml(action.gap_id) + '</strong>',
    '<code>' + escapeHtml(action.next_action || 'continue_foundation_review') + '</code>',
    '<code>work_items=' + Number((action.covered_by_work_item_ids || []).length)
      + ' | roles=' + escapeHtml((action.required_roles || []).join(',') || 'context')
      + ' | confirm=' + (action.requires_confirmation === true ? 'true' : 'false') + '</code>',
    '</div>',
    '</div>',
  ].join('')).join('');
  return '<div class="foundation-gap-plan">' + items + '</div>';
}

function foundationGapStatusClass(status) {
  if (status === "ready") {
    return "mvp-ready";
  }
  if (status === "deferred") {
    return "priority-low";
  }
  return "mvp-gapped";
}

function mvpReadinessMetric(label, value) {
  return [
    '<div class="mvp-readiness-metric">',
    '<span>' + escapeHtml(label) + '</span>',
    '<strong>' + Number(value || 0) + '</strong>',
    '</div>',
  ].join("");
}

function mvpReadinessTagList(label, values) {
  const tags = values.length
    ? values.map((value) => '<code>' + escapeHtml(value) + '</code>').join("")
    : "<code>none</code>";
  return '<div class="mvp-readiness-tag-group"><span>' + escapeHtml(label) + '</span>' + tags + '</div>';
}

function renderWorkItemOperationalSummary(summary) {
  if (!summary || !summary.schema_version) {
    workEvidencePanel.innerHTML = '<div class="empty-state compact">Keine Arbeitskorb-Evidence.</div>';
    return;
  }
  workEvidencePanel.innerHTML = `
    <div class="work-evidence-grid">
      ${workEvidenceMetric("Actions", summary.action_hint_count)}
      ${workEvidenceMetric("Confirm", summary.confirmation_required_action_count)}
      ${workEvidenceMetric("Role gates", summary.role_required_action_count)}
      ${workEvidenceMetric("State signals", summary.state_transition_signal_count)}
      ${workEvidenceMetric("Persistent tasks", summary.persistent_task_created_count)}
      ${workEvidenceMetric("Content", summary.content_included_action_count)}
    </div>
    <div class="work-evidence-tags">
      ${workEvidenceTagList("UI", summary.ui_actions || [])}
      ${workEvidenceTagList("State", summary.state_gates || [])}
      ${workEvidenceTagList("Roles", summary.role_gates || [])}
      ${workEvidenceTagList("Transitions", summary.state_transition_signals || [])}
    </div>
    <div class="work-evidence-contract">
      <code>${escapeHtml(summary.schema_version)} | content_included=${summary.content_included === true ? "true" : "false"} | destructive=${Number(summary.destructive_action_count || 0)} | external=${Number(summary.external_side_effect_action_count || 0)}</code>
    </div>
  `;
}

function workEvidenceMetric(label, value) {
  return `
    <div class="work-evidence-metric">
      <span>${escapeHtml(label)}</span>
      <strong>${Number(value || 0)}</strong>
    </div>
  `;
}

function workEvidenceTagList(label, values) {
  const tags = values.length
    ? values.map((value) => `<code>${escapeHtml(value)}</code>`).join("")
    : "<code>none</code>";
  return `<div class="work-evidence-tag-group"><span>${escapeHtml(label)}</span>${tags}</div>`;
}

function renderWorkItems(items) {
  workItemList.innerHTML = "";
  if (!items.length) {
    workItemList.innerHTML = '<div class="empty-state compact">Keine offenen Cockpit-Arbeitsschritte.</div>';
    return;
  }
  for (const item of items) {
    const row = document.createElement("article");
    row.className = `work-item ${workPriorityClass(item.priority)}`;
    row.innerHTML = `
      <div class="work-item-main">
        <span class="status-pill ${workPriorityClass(item.priority)}">${escapeHtml(item.priority)}</span>
        <div class="work-item-copy">
          <strong>${escapeHtml(item.title)}</strong>
          <span>${escapeHtml(item.target_label)}</span>
          <code>${escapeHtml(item.action)} | ${escapeHtml(item.scope)} | ui=${escapeHtml(item.primary_action_hint?.ui_action || "none")}</code>
        </div>
      </div>
      <div class="work-item-meta">
        <code>${escapeHtml(item.reason)}</code>
        <code>gate=${escapeHtml(item.primary_action_hint?.state_gate || "none")} | roles=${escapeHtml((item.primary_action_hint?.required_roles || []).join(",") || "context")}</code>
        <code>persistent_task_created=${item.persistent_task_created === true ? "true" : "false"} | content_included=${item.content_included === true ? "true" : "false"}</code>
      </div>
      ${workItemActions(item)}
    `;
    workItemList.appendChild(row);
  }
}

function workItemActions(item) {
  const hints = [item.primary_action_hint, ...(item.secondary_action_hints || [])].filter(Boolean);
  if (!hints.length) {
    return '<div class="work-item-actions"><span class="action-note">Keine sichere Aktion verfuegbar.</span></div>';
  }
  const buttons = hints.map((hint, index) => workItemActionButton(item, hint, index)).join("");
  return `<div class="work-item-actions">${buttons}</div>`;
}

function workItemActionButton(item, hint, index) {
  const disabledReason = workItemActionDisabledReason(item, hint);
  const disabled = disabledReason ? " disabled" : "";
  const intent = hint.requires_confirmation ? "primary" : "quiet";
  const title = disabledReason ? ` title="${escapeHtml(disabledReason)}"` : "";
  return `
    <button
      class="action-button ${intent}"
      type="button"
      data-work-item-id="${escapeHtml(item.work_item_id)}"
      data-work-action-index="${index}"
      data-work-ui-action="${escapeHtml(hint.ui_action)}"
      data-work-required-roles="${escapeHtml((hint.required_roles || []).join(","))}"
      data-work-state-gate="${escapeHtml(hint.state_gate || "none")}"
      data-work-requires-confirmation="${hint.requires_confirmation === true ? "true" : "false"}"
      aria-disabled="${disabledReason ? "true" : "false"}"
      ${disabled}${title}
    >
      ${escapeHtml(hint.label)}
    </button>
  `;
}

function workItemActionDisabledReason(item, hint) {
  if (hint.content_included === true || hint.metadata_only !== true || hint.persistent_task_created === true) {
    return "Action-Hint verletzt metadata-only Arbeitskorb-Regeln.";
  }
  if (!canUseAnyRole(hint.required_roles || [])) {
    return "Erforderliche Rolle fehlt im aktuellen Kontext.";
  }
  if (hint.ui_action === "guided_preview_decision" && (!item.flow_id || item.action !== "request_preview_decision")) {
    return "Preview Decision ist fuer diesen Zustand nicht die naechste sichere Aktion.";
  }
  if (hint.ui_action?.startsWith("module_") && !item.module_id) {
    return "Modulziel fehlt.";
  }
  return "";
}
function workPriorityClass(priority) {
  if (priority === "high") {
    return "priority-high";
  }
  if (priority === "medium") {
    return "priority-medium";
  }
  return "priority-low";
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
        ${readinessCell(flow)}
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

  const selectedFlow = (currentCockpit.source_object_flows || []).find((flow) => flow.flow_id === selectedFlowId);
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
    <div class="readiness-list">
      <strong>Flow Readiness</strong>
      ${readinessList(selectedFlow?.readiness)}
    </div>
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

function readinessCell(flow) {
  const readiness = flow.readiness || {};
  const decisionRef = readiness.latest_preview_decision_evidence_hash || "preview_decision_not_requested";
  const missingCount = (readiness.latest_preview_decision_missing_evidence || []).length;
  return `
    <div class="readiness-cell">
      <span class="status-pill ${readinessStatusClass(readiness.status)}">${escapeHtml(readiness.status || "metadata_ready")}</span>
      <span>${escapeHtml(readiness.next_action || "request_preview_decision")}</span>
      <span class="hash-text">${escapeHtml(decisionRef)}</span>
      <span class="hash-text">missing_evidence=${missingCount}</span>
      ${guidedPreviewActionButton(flow)}
    </div>
  `;
}

function guidedPreviewActionButton(flow) {
  const slot = previewSlotForFlow(flow);
  const gate = slot?.gate || {};
  if (!slot?.slot_id || !gate.policy_id) {
    return "";
  }
  return `
    <button
      class="action-button quiet guided-preview-action"
      type="button"
      data-preview-action="guided-preview-decision"
      data-flow-id="${escapeHtml(flow.flow_id)}"
    >
      Evidence + Decision
    </button>
  `;
}

function previewSlotForFlow(flow) {
  const slots = flow.preview_slots || [];
  return slots.find((slot) => slot?.gate?.policy_id) || slots[0] || null;
}

function metadataEvidenceRefsFor(flow) {
  const stamp = new Date().toISOString().replace(/[-:.TZ]/g, "").slice(0, 14);
  const refBase = `${safeRefPart(flow.source_object_id)}-${safeRefPart(flow.source_version_id)}-${stamp}`;
  return {
    parserSanitizer: `parser-sanitizer:workspace-preview-${refBase}`,
    backupCoverage: `backup:workspace-preview-${refBase}`,
    restore: `restore-drill:workspace-preview-${refBase}`,
    humanConfirmation: `approval:workspace-preview-decision-${refBase}`,
  };
}

function safeRefPart(value) {
  return String(value || "flow")
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, "-")
    .replace(/^-+|-+$/g, "")
    .slice(0, 64) || "flow";
}
function readinessList(readiness) {
  if (!readiness) {
    return "<span>Keine Flow-Readiness.</span>";
  }
  const missing = readiness.latest_preview_decision_missing_evidence || [];
  return `
    <div class="readiness-grid">
      ${detailItem("Status", readiness.status)}
      ${detailItem("Next", readiness.next_action)}
      ${detailItem("Preview Gate", readiness.preview_gate_status)}
      ${detailItem("Preview Decision", readiness.latest_preview_decision_ledger_ref || "not_requested")}
      ${detailItem("Missing Evidence", missing.length ? missing.join(",") : "none")}
      ${detailItem("Evidence Complete", readiness.content_release_evidence_complete ? "true" : "false")}
      ${detailItem("Content Release", readiness.content_release_allowed ? "allowed" : "blocked")}
      ${detailItem("Cockpit Audit", readiness.cockpit_audit_event_id || "n/a")}
    </div>
    <div class="evidence-list compact">${evidenceList(readiness.evidence_refs || [])}</div>
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
  return canUseAnyRole(["tenant-admin", "security-admin"]);
}

function canUseAnyRole(requiredRoles) {
  if (!requiredRoles.length) {
    return true;
  }
  const roles = new Set(readContext().roleIds.split(",").map((role) => role.trim()).filter(Boolean));
  return requiredRoles.some((role) => roles.has(role));
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
          ${previewGateSummary(slot.gate)}
          <code>${escapeHtml(slot.blocking_reason || "policy_gate_required")}</code>
        </div>
      `,
    )
    .join("");
}

function previewGateSummary(gate) {
  if (!gate) {
    return "<code>gate=missing | content_release_allowed=false</code>";
  }
  return `
    <code>${escapeHtml(gate.status || "metadata_ready_content_blocked")} | ${escapeHtml(gate.policy_id || "preview-policy.missing")}</code>
    <code>parser=${escapeHtml(gate.parser_profile_id || "n/a")} | sanitizer=${escapeHtml(gate.sanitizer_profile_id || "n/a")}</code>
    <code>content_release_allowed=${gate.content_release_allowed === true ? "true" : "false"}</code>
  `;
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

function readinessStatusClass(status) {
  if (status === "metadata_ready_preview_decision_pending") {
    return "readiness-pending";
  }
  if (status === "metadata_ready_preview_evidence_complete_content_blocked") {
    return "readiness-complete-blocked";
  }
  if (status === "metadata_ready_preview_blocked") {
    return "readiness-blocked";
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
snapshotButton.addEventListener("click", downloadMvpSnapshot);
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
function executeWorkItemAction(item, hint) {
  const disabledReason = workItemActionDisabledReason(item, hint);
  if (disabledReason) {
    setStatus(disabledReason, true);
    return;
  }
  if (hint.ui_action === "open_flow" && item.flow_id) {
    selectFlow(item.flow_id);
    return;
  }
  if (hint.ui_action === "guided_preview_decision" && item.flow_id) {
    const flow = (currentCockpit.source_object_flows || []).find((candidate) => candidate.flow_id === item.flow_id);
    if (flow) {
      executeGuidedPreviewDecision(flow);
      return;
    }
  }
  if (hint.ui_action === "module_provision" || hint.ui_action === "module_enable") {
    const module = (currentCockpit.modules || []).find((candidate) => candidate.module_id === item.module_id);
    const action = module ? moduleActionFor(module) : null;
    if (module && action && action.apiAction === hint.api_action) {
      executeModuleAction(module, action);
      return;
    }
    setStatus("Arbeitskorb-Aktion ist nicht mehr synchron mit dem Modulstatus.", true);
    return;
  }
  setStatus("Diese Arbeitskorb-Aktion ist nur als Review-Hinweis verfuegbar.");
}

workItemList.addEventListener("click", (event) => {
  const button = event.target.closest("button[data-work-item-id]");
  if (!button) {
    return;
  }
  const item = (currentCockpit.work_items || []).find((candidate) => candidate.work_item_id === button.dataset.workItemId);
  const actionIndex = Number(button.dataset.workActionIndex || 0);
  const hint = item ? [item.primary_action_hint, ...(item.secondary_action_hints || [])].filter(Boolean)[actionIndex] : null;
  if (item && hint) {
    executeWorkItemAction(item, hint);
  }
});
flowTableBody.addEventListener("click", (event) => {
  const actionButton = event.target.closest("button[data-preview-action]");
  if (actionButton?.dataset.flowId) {
    const flow = (currentCockpit.source_object_flows || []).find((item) => item.flow_id === actionButton.dataset.flowId);
    if (flow && actionButton.dataset.previewAction === "guided-preview-decision") {
      executeGuidedPreviewDecision(flow);
    }
    return;
  }

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
