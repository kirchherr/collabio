const fields = {
  tenantId: document.querySelector("#tenant-id"),
  userId: document.querySelector("#user-id"),
  roleIds: document.querySelector("#role-ids"),
  readableObjectIds: document.querySelector("#readable-object-ids"),
};

const statusLine = document.querySelector("#status-line");
const mvpReadinessPanel = document.querySelector("#mvp-readiness-panel");
const pilotDecisionPanel = document.querySelector("#pilot-decision-panel");
const foundationWorkflowButton = document.querySelector("#foundation-workflow-button");
const foundationWorkflowDialog = document.querySelector("#foundation-workflow-dialog");
const foundationWorkflowContent = document.querySelector("#foundation-workflow-content");
const foundationWorkflowClose = document.querySelector("#foundation-workflow-close");
const foundationWorkflowCancel = document.querySelector("#foundation-workflow-cancel");
const foundationWorkflowRun = document.querySelector("#foundation-workflow-run");
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
const crmSearchForm = document.querySelector("#crm-search-form");
const crmSearchQuery = document.querySelector("#crm-search-query");
const crmSearchTopK = document.querySelector("#crm-search-top-k");
const crmSearchButton = document.querySelector("#crm-search-button");
const crmSearchCount = document.querySelector("#crm-search-count");
const crmSearchMeta = document.querySelector("#crm-search-meta");
const crmSearchResults = document.querySelector("#crm-search-results");
const crmSearchReadiness = document.querySelector("#crm-search-readiness");
const readinessCounts = {
  metadataReady: document.querySelector("#metadata-ready-count"),
  previewPending: document.querySelector("#preview-pending-count"),
  previewBlocked: document.querySelector("#preview-blocked-count"),
  evidenceComplete: document.querySelector("#preview-evidence-complete-count"),
};

const storageKey = "collabio.workspace.context";
const defaultReadableObjectIds = [
  "doc-1",
  "mail-1",
  "crm-account-acme-demo",
  "crm-contact-ada-demo",
  "crm-activity-followup-demo",
  "crm-note-acme-demo",
  "erp-product-standard-widget-demo",
  "erp-order-acme-widget-demo",
  "erp-invoice-acme-widget-demo",
].join(",");
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
let crmSearchReadinessState = null;
let currentPilotDecisionContext = null;
let foundationWorkflowState = null;
const foundationWorkflowGapIds = new Set([
  "preview_decisions_pending",
  "module_activation_work_items_open",
]);
const pilotDecisionConfirmationStatement =
  "I explicitly record this tenant-scoped MVP pilot decision against the supplied evidence context. " +
  "This stores decision evidence only; it does not admit users, activate modules, authorize traffic, " +
  "start the pilot, or execute external or destructive actions.";

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
  fields.readableObjectIds.value = context.readableObjectIds || defaultReadableObjectIds;
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
    applyCockpit(body);
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
    currentPilotDecisionContext = null;
    renderPilotDecisionError("Pilot-Entscheidungskontext konnte nicht geladen werden.");
    renderCrmErpSearchReadinessError(error.message || "Cockpit konnte nicht geladen werden.");
    setStatus(error.message || "Cockpit konnte nicht geladen werden.", true);
  } finally {
    refreshButton.disabled = false;
  }
}

function applyCockpit(body) {
  currentCockpit = body;
  renderCockpit(body);
  loadCrmErpSearchReadiness();
  loadPilotDecisionState();
}

async function loadPilotDecisionState() {
  const context = readContext();
  pilotDecisionPanel.innerHTML = '<div class="empty-state compact">Pilot-Entscheidung wird geladen ...</div>';
  try {
    const [contextResponse, currentResponse] = await Promise.all([
      fetch("/v1/platform/cockpit/mvp-pilot-decision-context", {
        headers: headersForContext(context),
      }),
      fetch("/v1/platform/cockpit/mvp-pilot-decisions/current", {
        headers: headersForContext(context),
      }),
    ]);
    const contextBody = await readJson(contextResponse);
    const currentBody = await readJson(currentResponse);
    if (!contextResponse.ok) {
      throw new Error(contextBody.detail || `HTTP ${contextResponse.status}`);
    }
    if (!currentResponse.ok) {
      throw new Error(currentBody.detail || `HTTP ${currentResponse.status}`);
    }
    currentPilotDecisionContext = contextBody;
    renderPilotDecision(contextBody, currentBody);
  } catch (error) {
    currentPilotDecisionContext = null;
    renderPilotDecisionError(error.message || "Pilot-Entscheidung konnte nicht geladen werden.");
  }
}

function renderPilotDecision(context, currentDecision) {
  const canGo = context.go_decision_allowed === true;
  const latest = currentDecision
    ? `<div class="pilot-decision-current">
        <span>Aktueller Entscheid</span>
        <strong class="decision-value decision-${escapeHtml(currentDecision.go_no_go_decision)}">${escapeHtml(currentDecision.go_no_go_decision)}</strong>
        <code>${escapeHtml(currentDecision.evidence_hash)}</code>
        <span>${escapeHtml(currentDecision.decided_by)} | ${escapeHtml(formatPilotTimestamp(currentDecision.decided_at))}</span>
      </div>`
    : '<div class="pilot-decision-current"><span>Aktueller Entscheid</span><strong>nicht erfasst</strong></div>';
  pilotDecisionPanel.innerHTML = `
    <div class="section-heading">
      <div>
        <p class="eyebrow">Human Gate</p>
        <h2>MVP Pilot-Entscheidung</h2>
      </div>
      <span class="status-pill ${canGo ? "status-enabled" : "readiness-blocked"}">${canGo ? "go_verfuegbar" : "go_blockiert"}</span>
    </div>
    <div class="pilot-decision-evidence">
      ${detailItem("Scope", context.decision_scope)}
      ${detailItem("Readiness", context.mvp_readiness_decision)}
      ${detailItem("Module Gate", context.module_gate_status)}
      ${detailItem("Content Gate", context.content_gate_status)}
      ${detailItem("Context Hash", context.context_hash)}
      ${detailItem("Naechste Aktion", context.next_foundation_action)}
    </div>
    ${latest}
    <div class="pilot-decision-form">
      <label class="pilot-decision-reason">
        Entscheidungsgrund
        <input id="pilot-decision-reason" autocomplete="off" maxlength="1000" value="Metadata-only scope and current evidence reviewed." />
      </label>
      <label>
        Change
        <input id="pilot-decision-change-ref" autocomplete="off" value="change:mvp-pilot-review" />
      </label>
      <label>
        Freigabe
        <input id="pilot-decision-confirmation-ref" autocomplete="off" value="approval:mvp-pilot-review" />
      </label>
      <div class="pilot-decision-segmented" role="group" aria-label="Pilot Entscheidung">
        <button class="decision-button decision-go" type="button" data-pilot-decision="go" ${canGo ? "" : "disabled"}>Go</button>
        <button class="decision-button decision-defer" type="button" data-pilot-decision="defer">Defer</button>
        <button class="decision-button decision-no-go" type="button" data-pilot-decision="no_go">No-Go</button>
      </div>
    </div>
  `;
}

function renderPilotDecisionError(message) {
  pilotDecisionPanel.innerHTML = `
    <div class="section-heading">
      <div><p class="eyebrow">Human Gate</p><h2>MVP Pilot-Entscheidung</h2></div>
      <span class="status-pill readiness-blocked">nicht_verfuegbar</span>
    </div>
    <div class="empty-state compact error-copy">${escapeHtml(message)}</div>
  `;
}

function formatPilotTimestamp(value) {
  const timestamp = new Date(value);
  return Number.isNaN(timestamp.valueOf()) ? String(value || "n/a") : timestamp.toLocaleString("de-DE");
}

async function submitPilotDecision(decision) {
  if (!currentPilotDecisionContext) {
    setStatus("Pilot-Entscheidungskontext fehlt.", true);
    return;
  }
  if (decision === "go" && currentPilotDecisionContext.go_decision_allowed !== true) {
    setStatus("Go ist durch den aktuellen Evidenzkontext blockiert.", true);
    return;
  }
  const reason = document.querySelector("#pilot-decision-reason")?.value.trim() || "";
  const changeRequestRef = document.querySelector("#pilot-decision-change-ref")?.value.trim() || "";
  const confirmationReference = document.querySelector("#pilot-decision-confirmation-ref")?.value.trim() || "";
  if (!reason || !changeRequestRef || !confirmationReference) {
    setStatus("Entscheidungsgrund, Change und Freigabe sind erforderlich.", true);
    return;
  }
  const context = readContext();
  const confirmation = [
    pilotDecisionConfirmationStatement,
    "",
    `Entscheidung: ${decision}`,
    `Tenant: ${context.tenantId}`,
    `Evidence: ${currentPilotDecisionContext.context_hash}`,
  ].join("\n");
  if (!window.confirm(confirmation)) {
    setStatus("Pilot-Entscheidung abgebrochen.");
    return;
  }
  const stamp = `${Date.now()}-${Math.random().toString(16).slice(2, 10)}`;
  const payload = {
    tenant_id: context.tenantId,
    decision_id: `mvp-pilot-decision-${stamp}`,
    decision_capture_submit_contract_id: "mvp_pilot_decision_capture_submit_contract.v1",
    decision_context_hash: currentPilotDecisionContext.context_hash,
    go_no_go_decision: decision,
    decision_reason: reason,
    human_confirmation_statement: pilotDecisionConfirmationStatement,
    human_confirmation_reference: confirmationReference,
    change_request_ref: changeRequestRef,
    confirmed_by: context.userId,
    confirmed_at: new Date().toISOString(),
    confirmation_role_ids: context.roleIds.split(",").map((value) => value.trim()).filter(Boolean),
    idempotency_key: `request:mvp-pilot-decision-${stamp}`,
  };
  const buttons = pilotDecisionPanel.querySelectorAll("button[data-pilot-decision]");
  buttons.forEach((button) => {
    button.disabled = true;
  });
  try {
    const response = await fetch("/v1/platform/cockpit/mvp-pilot-decision-capture-submit", {
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
    setStatus(`Pilot-Entscheidung ${body.go_no_go_decision} gespeichert | Evidence ${body.evidence_hash}`);
    await loadPilotDecisionState();
  } catch (error) {
    setStatus(error.message || "Pilot-Entscheidung konnte nicht gespeichert werden.", true);
    await loadPilotDecisionState();
  }
}

async function loadCrmErpSearchReadiness() {
  const context = readContext();
  renderCrmErpSearchReadinessLoading();
  try {
    const response = await fetch("/v1/platform/search/crm-erp/readiness", {
      headers: headersForContext(context),
    });
    const body = await readJson(response);
    if (!response.ok) {
      throw new DetailLoadError(response.status, body.detail || `HTTP ${response.status}`);
    }
    crmSearchReadinessState = body;
    renderCrmErpSearchReadiness(body);
  } catch (error) {
    renderCrmErpSearchReadinessError(error.message || "CRM/ERP Search-Readiness konnte nicht geladen werden.");
  }
}

function renderCrmErpSearchReadinessLoading() {
  crmSearchButton.disabled = true;
  crmSearchReadiness.innerHTML = '<div class="empty-state compact">Search-Readiness wird geladen ...</div>';
}

function renderCrmErpSearchReadiness(readiness) {
  const gates = readiness.gates || [];
  const blockingReasons = readiness.blocking_reasons || [];
  crmSearchButton.disabled = readiness.ready_for_keyword_search !== true;
  crmSearchMeta.textContent = [
    `readiness=${readiness.status || "blocked"}`,
    `contract=${readiness.result_contract || "metadata_only_search_readiness_no_content"}`,
    `search_contract=${readiness.search_result_contract || "candidate_only_metadata_only_acl_checked"}`,
    `content_included=${readiness.content_included === true ? "true" : "false"}`,
    `ai_used=${readiness.ai_used === true ? "true" : "false"}`,
    `rag_context_created=${readiness.rag_context_created === true ? "true" : "false"}`,
  ].join(" | ");
  crmSearchReadiness.innerHTML = `
    <div class="crm-search-readiness-summary">
      <span class="status-pill ${searchReadinessStatusClass(readiness.status)}">${escapeHtml(readiness.status || "blocked")}</span>
      <div class="crm-search-readiness-copy">
        <strong>${escapeHtml(readiness.feature_id)}</strong>
        <code>module=${escapeHtml(readiness.module_status)} | normal_use=${readiness.module_enabled_for_normal_use === true ? "true" : "false"} | feature=${readiness.feature_configured_enabled === true ? "true" : "false"}</code>
        <code>keyword_ready=${readiness.ready_for_keyword_search === true ? "true" : "false"} | ready_for_rag_context=${readiness.ready_for_rag_context === true ? "true" : "false"}</code>
      </div>
    </div>
    <div class="crm-search-readiness-grid">
      ${gates.map(crmSearchReadinessGate).join("")}
    </div>
    ${crmSearchBlockingReasons(blockingReasons)}
  `;
}

function renderCrmErpSearchReadinessError(message) {
  crmSearchReadinessState = null;
  crmSearchButton.disabled = true;
  crmSearchMeta.textContent = "readiness=error | metadata_only | content_included=false | ai_used=false | rag_context_created=false";
  crmSearchReadiness.innerHTML = `<div class="empty-state compact error-copy">${escapeHtml(message)}</div>`;
}

function crmSearchReadinessGate(gate) {
  return `
    <div class="crm-search-readiness-gate">
      <span class="status-pill ${searchGateStatusClass(gate.status)}">${escapeHtml(gate.status)}</span>
      <strong>${escapeHtml(gate.gate_id)}</strong>
      <span>${escapeHtml(gate.summary)}</span>
      <code>${escapeHtml(gate.evidence_ref)}</code>
    </div>
  `;
}

function crmSearchBlockingReasons(reasons) {
  if (!reasons.length) {
    return '<div class="crm-search-readiness-blockers"><code>blocking_reasons=none</code></div>';
  }
  return `
    <div class="crm-search-readiness-blockers">
      ${reasons.map((reason) => `<code>${escapeHtml(reason)}</code>`).join("")}
    </div>
  `;
}

function searchReadinessStatusClass(status) {
  if (status === "ready") {
    return "status-enabled";
  }
  return "status-available";
}

function searchGateStatusClass(status) {
  if (status === "satisfied") {
    return "status-enabled";
  }
  if (status === "blocked") {
    return "readiness-blocked";
  }
  if (status === "deferred_by_policy") {
    return "readiness-complete-blocked";
  }
  return "status-other";
}
async function runCrmErpSearch(event) {
  if (event) {
    event.preventDefault();
  }
  const context = readContext();
  persistContext();
  const query = crmSearchQuery.value.trim();
  const topK = Math.max(1, Math.min(50, Number.parseInt(crmSearchTopK.value, 10) || 10));
  crmSearchTopK.value = String(topK);
  if (!query) {
    renderCrmErpSearchError("Query darf nicht leer sein.");
    return;
  }
  if (crmSearchReadinessState?.ready_for_keyword_search === false) {
    const blockers = crmSearchReadinessState.blocking_reasons || ["search_readiness_blocked"];
    renderCrmErpSearchError(`Search-Readiness blockiert: ${blockers.join(", ")}`);
    return;
  }
  crmSearchButton.disabled = true;
  crmSearchMeta.textContent = "Suche laeuft | metadata_only | content_included=false | ai_used=false";
  crmSearchResults.innerHTML = '<div class="empty-state compact">Suche laeuft ...</div>';
  try {
    const response = await fetch("/v1/crm-erp/search", {
      method: "POST",
      headers: {
        ...headersForContext(context),
        "Content-Type": "application/json",
      },
      body: JSON.stringify({ query, top_k: topK }),
    });
    const body = await readJson(response);
    if (!response.ok) {
      throw new DetailLoadError(response.status, body.detail || `HTTP ${response.status}`);
    }
    renderCrmErpSearchResults(body);
    setStatus(`CRM/ERP Suche: ${Number((body.candidates || []).length)} Kandidat(en) | Audit ${body.audit_event_id}`);
  } catch (error) {
    const prefix = error.status === 403 ? "Feature-Gate" : "Suchfehler";
    renderCrmErpSearchError(`${prefix}: ${error.message || "CRM/ERP Suche konnte nicht ausgefuehrt werden."}`);
    setStatus(error.message || "CRM/ERP Suche konnte nicht ausgefuehrt werden.", true);
  } finally {
    crmSearchButton.disabled = crmSearchReadinessState ? crmSearchReadinessState.ready_for_keyword_search !== true : false;
  }
}

function renderCrmErpSearchResults(response) {
  const candidates = response.candidates || [];
  crmSearchCount.textContent = String(candidates.length);
  crmSearchMeta.textContent = [
    `audit=${response.audit_event_id || "n/a"}`,
    `policy=${response.search_policy_id || "keyword_candidate_acl_v1"}`,
    `contract=${response.result_contract || "candidate_only_metadata_only_acl_checked"}`,
    `content_included=${response.content_included === true ? "true" : "false"}`,
    `ai_used=${response.ai_used === true ? "true" : "false"}`,
    `rag_context_created=${response.rag_context_created === true ? "true" : "false"}`,
  ].join(" | ");
  if (!candidates.length) {
    crmSearchResults.innerHTML = '<div class="empty-state compact">Keine autorisierten Kandidaten.</div>';
    return;
  }
  crmSearchResults.innerHTML = candidates.map(crmSearchCandidateRow).join("");
}

function renderCrmErpSearchError(message) {
  crmSearchCount.textContent = "0";
  crmSearchMeta.textContent = "metadata_only | content_included=false | ai_used=false | rag_context_created=false";
  crmSearchResults.innerHTML = `<div class="empty-state compact error-copy">${escapeHtml(message)}</div>`;
}

function crmSearchCandidateRow(candidate) {
  return `
    <article class="crm-search-result" data-search-object-id="${escapeHtml(candidate.object_id)}">
      <div class="crm-search-result-title">
        <strong>${escapeHtml(candidate.title)}</strong>
        <span class="status-pill status-enabled">${escapeHtml(candidate.object_type)}</span>
      </div>
      <div class="crm-search-result-grid">
        ${detailItem("Object", candidate.object_id)}
        ${detailItem("Version", candidate.version_id)}
        ${detailItem("Class", candidate.classification)}
        ${detailItem("Retention", candidate.retention_policy_id)}
        ${detailItem("Legal Hold", candidate.legal_hold_state)}
        ${detailItem("ACL", `v${candidate.acl_version} checked=${candidate.access_checked === true ? "true" : "false"}`)}
        ${detailItem("Score", String(candidate.score))}
        ${detailItem("Content Hash", candidate.content_hash)}
      </div>
    </article>
  `;
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
async function executeModuleAction(module, action, options = {}) {
  const context = readContext();
  if (options.skipConfirmation !== true) {
    const confirmationText = `${action.label} fuer ${module.display_name} ausfuehren?\n\nZielstatus: ${action.targetStatus}\nTenant: ${context.tenantId}`;
    if (!window.confirm(confirmationText)) {
      setStatus("Aktion abgebrochen.");
      return null;
    }
  }

  const endpoint = `/v1/admin/tenant-modules/${encodeURIComponent(module.module_id)}/${action.apiAction}`;
  const payload = {
    approval_reference: approvalReferenceFor(module, action),
    reason: options.reason || `Workspace cockpit controlled ${action.apiAction} for ${module.module_id}; explicit browser confirmation captured before API call.`,
  };
  setStatus(`${action.label} laeuft ...`);
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
    if (options.reloadAfter !== false) {
      await loadCockpit();
    }
    return body;
  } catch (error) {
    setStatus(error.message || "Modulaktion konnte nicht ausgefuehrt werden.", true);
    return null;
  }
}

async function executeGuidedPreviewDecision(flow, options = {}) {
  const context = readContext();
  const slot = previewSlotForFlow(flow);
  const gate = slot?.gate || {};
  if (!slot?.slot_id || !gate.policy_id) {
    setStatus("Preview-Gate fehlt fuer diesen Flow.", true);
    return;
  }

  if (options.skipConfirmation !== true) {
    const confirmationText = `Metadata-only Preview-Evidence und Preview-Decision fuer ${flow.source_object_id}:${flow.source_version_id} anfordern?\n\nEs werden keine Inhalte gerendert, keine Rohdaten freigegeben und content_release_allowed bleibt policy-gesteuert blockiert.`;
    if (!window.confirm(confirmationText)) {
      setStatus("Preview-Flow abgebrochen.");
      return null;
    }
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
    if (options.reloadAfter !== false) {
      await loadCockpit();
    }
    return decisionBody;
  } catch (error) {
    setStatus(error.message || "Preview-Decision-Flow konnte nicht ausgefuehrt werden.", true);
    return null;
  }
}

function executeFoundationGapAction(action) {
  if (["resolve_preview_decision_work_items", "complete_module_activation_work_items"].includes(action.next_action)) {
    openFoundationCompletionWorkflow(action.gap_id);
    return;
  }
  setStatus("Foundation-Gap-Aktion ist aktuell nur als Review-Hinweis verfuegbar.");
}

function renderFoundationWorkflowLaunch(cockpit) {
  const plan = buildFoundationCompletionPlan(cockpit, readContext());
  const hasTargetGaps = plan.targetGapIds.length > 0;
  foundationWorkflowButton.disabled = !hasTargetGaps;
  foundationWorkflowButton.textContent = hasTargetGaps
    ? `Foundation-Abschluss (${plan.tasks.length})`
    : "Foundation abgeschlossen";
  foundationWorkflowButton.title = hasTargetGaps
    ? `${plan.targetGapIds.length} Foundation-Gap(s), ${plan.tasks.length} kontrollierte Aufgabe(n)`
    : "Keine offenen Preview-Decision- oder Modulaktivierungs-Gaps";
}

function buildFoundationCompletionPlan(cockpit, context) {
  const actions = (cockpit.foundation_gap_actions || []).filter((action) =>
    foundationWorkflowGapIds.has(action.gap_id),
  );
  const workItems = cockpit.work_items || [];
  const flows = cockpit.source_object_flows || [];
  const modules = cockpit.modules || [];
  const tasks = [];
  const blockers = [];
  if (!context.tenantId) {
    blockers.push("Tenant-ID fehlt im aktuellen Kontext.");
  }
  if (!context.userId) {
    blockers.push("User-ID fehlt im aktuellen Kontext.");
  }

  for (const action of actions) {
    if (action.status !== "ready") {
      blockers.push(`${action.gap_id}: Status ${action.status || "unknown"} ist nicht ausfuehrbar.`);
      continue;
    }
    const coveredIds = new Set(action.covered_by_work_item_ids || []);
    const coveredItems = workItems.filter((item) => coveredIds.has(item.work_item_id));
    if (!coveredIds.size) {
      blockers.push(`${action.gap_id}: Keine ausfuehrbaren Work-Items im aktuellen Cockpit.`);
    }
    for (const workItemId of coveredIds) {
      if (!coveredItems.some((item) => item.work_item_id === workItemId)) {
        blockers.push(`${action.gap_id}: Work-Item ${workItemId} fehlt im aktuellen Cockpit.`);
      }
    }

    if (action.gap_id === "preview_decisions_pending") {
      for (const item of coveredItems) {
        const hint = item.primary_action_hint || {};
        const safetyIssue = foundationWorkItemSafetyIssue(item, hint);
        const flow = flows.find((candidate) => candidate.flow_id === item.flow_id);
        const slot = flow ? previewSlotForFlow(flow) : null;
        if (
          safetyIssue
          || item.action !== "request_preview_decision"
          || hint.ui_action !== "guided_preview_decision"
          || !flow
          || !slot?.slot_id
          || !slot?.gate?.policy_id
        ) {
          blockers.push(`${action.gap_id}: ${safetyIssue || `Work-Item ${item.work_item_id} ist veraltet.`}`);
          continue;
        }
        tasks.push({
          id: `preview:${flow.flow_id}`,
          gapId: action.gap_id,
          phase: "preview",
          title: flow.title || flow.source_object_id,
          subject: `${flow.source_object_id}:${flow.source_version_id}`,
          flowId: flow.flow_id,
          requiredRoles: [...new Set([...(hint.required_roles || []), ...(action.required_roles || [])])],
          operations: ["Renderer-Sandbox-Evidence", "Preview-Decision-Ledger"],
        });
      }
    }

    if (action.gap_id === "module_activation_work_items_open") {
      for (const item of coveredItems) {
        const hint = item.primary_action_hint || {};
        const safetyIssue = foundationWorkItemSafetyIssue(item, hint);
        const module = modules.find((candidate) => candidate.module_id === item.module_id);
        const firstAction = module ? moduleActionFor(module) : null;
        if (
          safetyIssue
          || item.scope !== "module"
          || !["module_provision", "module_enable"].includes(hint.ui_action)
          || !module
          || !firstAction
          || !["provision", "enable"].includes(firstAction.apiAction)
          || firstAction.apiAction !== hint.api_action
        ) {
          blockers.push(`${action.gap_id}: ${safetyIssue || `Work-Item ${item.work_item_id} ist veraltet.`}`);
          continue;
        }
        const transitions = module.status === "available"
          ? ["provision", "enable"]
          : ["enable"];
        tasks.push({
          id: `module:${module.module_id}`,
          gapId: action.gap_id,
          phase: "module",
          title: module.display_name,
          subject: `${module.module_id}:${module.status}`,
          moduleId: module.module_id,
          initialStatus: module.status,
          requiredRoles: [...new Set([...(hint.required_roles || []), ...(action.required_roles || [])])],
          transitions,
          operations: transitions.map((transition) => transition === "provision" ? "Provisionieren" : "Aktivieren"),
        });
      }
    }
  }

  tasks.sort((left, right) => {
    const phaseOrder = { preview: 0, module: 1 };
    return phaseOrder[left.phase] - phaseOrder[right.phase] || left.id.localeCompare(right.id);
  });
  for (const task of tasks) {
    if (!contextHasAnyRole(context, task.requiredRoles)) {
      blockers.push(`${task.id}: Erforderliche Rolle fehlt (${task.requiredRoles.join(",")}).`);
    }
  }

  const targetGapIds = actions.map((action) => action.gap_id).sort();
  const confirmationPhrase = `TENANT ${context.tenantId} FOUNDATION ${tasks.length}`;
  const uniqueBlockers = [...new Set(blockers)].sort();
  const key = JSON.stringify({
    tenantId: context.tenantId,
    userId: context.userId,
    roleIds: normalizedContextValues(context.roleIds),
    readableObjectIds: normalizedContextValues(context.readableObjectIds),
    targetGapIds,
    blockers: uniqueBlockers,
    tasks: tasks.map((task) => ({
      id: task.id,
      subject: task.subject,
      operations: task.operations,
      requiredRoles: [...task.requiredRoles].sort(),
    })),
  });
  return {
    tenantId: context.tenantId,
    userId: context.userId,
    targetGapIds,
    tasks,
    blockers: uniqueBlockers,
    confirmationPhrase,
    key,
  };
}

function foundationWorkItemSafetyIssue(item, hint) {
  if (hint.metadata_only !== true || hint.content_included === true) {
    return `Work-Item ${item.work_item_id} ist nicht metadata-only.`;
  }
  if (hint.persistent_task_created === true || hint.destructive === true || hint.external_side_effect === true) {
    return `Work-Item ${item.work_item_id} verletzt die sichere Foundation-Grenze.`;
  }
  return "";
}

function normalizedContextValues(value) {
  return String(value || "")
    .split(",")
    .map((entry) => entry.trim())
    .filter(Boolean)
    .sort();
}

function contextHasAnyRole(context, requiredRoles) {
  if (!requiredRoles.length) {
    return true;
  }
  const roles = new Set(normalizedContextValues(context.roleIds));
  return requiredRoles.some((role) => roles.has(role));
}

function openFoundationCompletionWorkflow(focusGapId = "") {
  const plan = buildFoundationCompletionPlan(currentCockpit, readContext());
  foundationWorkflowState = {
    plan,
    acknowledged: false,
    confirmationValue: "",
    running: false,
    completed: false,
    requiresReopen: false,
    error: "",
    remainingGapIds: [],
    taskStates: Object.fromEntries(plan.tasks.map((task) => [task.id, { status: "pending", detail: "" }])),
  };
  renderFoundationCompletionWorkflow();
  if (!foundationWorkflowDialog.open) {
    foundationWorkflowDialog.showModal();
  }
  const focusedTask = focusGapId
    ? foundationWorkflowContent.querySelector(`[data-workflow-gap-id="${CSS.escape(focusGapId)}"]`)
    : null;
  focusedTask?.scrollIntoView({ block: "center" });
  foundationWorkflowContent.querySelector("#foundation-workflow-confirmation")?.focus();
}

function renderFoundationCompletionWorkflow() {
  const state = foundationWorkflowState;
  if (!state) {
    foundationWorkflowContent.innerHTML = "";
    return;
  }
  const { plan } = state;
  const previewTasks = plan.tasks.filter((task) => task.phase === "preview");
  const moduleTasks = plan.tasks.filter((task) => task.phase === "module");
  const completedCount = Object.values(state.taskStates).filter((taskState) => taskState.status === "completed").length;
  const progressLabel = state.completed
    ? "abgeschlossen"
    : state.requiresReopen
      ? "unterbrochen"
      : state.running
        ? "in_arbeit"
        : "bereit";
  foundationWorkflowContent.innerHTML = [
    '<div class="foundation-workflow-summary">',
    foundationWorkflowMetric("Tenant", plan.tenantId || "n/a"),
    foundationWorkflowMetric("Foundation-Gaps", plan.targetGapIds.length),
    foundationWorkflowMetric("Aufgaben", plan.tasks.length),
    foundationWorkflowMetric("Fortschritt", `${completedCount}/${plan.tasks.length}`),
    '</div>',
    '<div class="foundation-workflow-boundary">',
    '<strong>Ausfuehrungsgrenze</strong>',
    '<span>Metadata-only Preview-Evidence und Modulstatuswechsel. Kein Content-Release, keine Fachmodul-Daten, keine Automationen, keine externen oder destruktiven Aktionen.</span>',
    '</div>',
    foundationWorkflowBlockers(plan.blockers),
    foundationWorkflowPhase("1", "Preview-Entscheidungen", previewTasks, state.taskStates),
    foundationWorkflowPhase("2", "Modulaktivierung", moduleTasks, state.taskStates),
    foundationWorkflowResult(state, progressLabel),
    state.completed || state.requiresReopen || state.running || !plan.tasks.length
      ? ""
      : foundationWorkflowConfirmation(plan, state),
  ].join("");

  const confirmationInput = foundationWorkflowContent.querySelector("#foundation-workflow-confirmation");
  const acknowledgement = foundationWorkflowContent.querySelector("#foundation-workflow-acknowledgement");
  if (confirmationInput) {
    confirmationInput.value = state.confirmationValue;
    confirmationInput.addEventListener("input", () => {
      state.confirmationValue = confirmationInput.value;
      syncFoundationWorkflowControls();
    });
  }
  if (acknowledgement) {
    acknowledgement.checked = state.acknowledged;
    acknowledgement.addEventListener("change", () => {
      state.acknowledged = acknowledgement.checked;
      syncFoundationWorkflowControls();
    });
  }
  syncFoundationWorkflowControls();
}

function foundationWorkflowMetric(label, value) {
  return `<div><span>${escapeHtml(label)}</span><strong>${escapeHtml(value)}</strong></div>`;
}

function foundationWorkflowBlockers(blockers) {
  if (!blockers.length) {
    return "";
  }
  return [
    '<section class="foundation-workflow-blockers" aria-label="Ausfuehrungsblocker">',
    '<strong>Ausfuehrung blockiert</strong>',
    '<ul>',
    blockers.map((blocker) => `<li>${escapeHtml(blocker)}</li>`).join(""),
    '</ul>',
    '</section>',
  ].join("");
}

function foundationWorkflowPhase(number, title, tasks, taskStates) {
  if (!tasks.length) {
    return "";
  }
  return [
    '<section class="foundation-workflow-phase">',
    `<div class="foundation-workflow-phase-heading"><span>${escapeHtml(number)}</span><h3>${escapeHtml(title)}</h3></div>`,
    '<ol class="foundation-workflow-task-list">',
    tasks.map((task) => foundationWorkflowTask(task, taskStates[task.id])).join(""),
    '</ol>',
    '</section>',
  ].join("");
}

function foundationWorkflowTask(task, taskState) {
  const status = taskState?.status || "pending";
  const labels = {
    pending: "ausstehend",
    running: "laeuft",
    completed: "erledigt",
    failed: "fehlgeschlagen",
  };
  return [
    `<li class="foundation-workflow-task task-${escapeHtml(status)}" data-workflow-gap-id="${escapeHtml(task.gapId)}">`,
    '<div class="foundation-workflow-task-copy">',
    `<strong>${escapeHtml(task.title)}</strong>`,
    `<code>${escapeHtml(task.subject)}</code>`,
    `<span>${task.operations.map((operation) => escapeHtml(operation)).join(" &rarr; ")}</span>`,
    taskState?.detail ? `<code class="foundation-workflow-task-detail">${escapeHtml(taskState.detail)}</code>` : "",
    '</div>',
    `<span class="status-pill workflow-${escapeHtml(status)}">${labels[status] || escapeHtml(status)}</span>`,
    '</li>',
  ].join("");
}

function foundationWorkflowResult(state, progressLabel) {
  if (!state.error && !state.completed && !state.running) {
    return "";
  }
  const remaining = state.remainingGapIds.length
    ? `<code>remaining=${escapeHtml(state.remainingGapIds.join(","))}</code>`
    : "";
  return [
    `<div class="foundation-workflow-result result-${escapeHtml(progressLabel)}">`,
    `<strong>${escapeHtml(progressLabel)}</strong>`,
    state.error ? `<span>${escapeHtml(state.error)}</span>` : "",
    remaining,
    '</div>',
  ].join("");
}

function foundationWorkflowConfirmation(plan, state) {
  return [
    '<section class="foundation-workflow-confirmation">',
    '<label class="foundation-workflow-check">',
    '<input type="checkbox" id="foundation-workflow-acknowledgement" />',
    '<span>Ich bestaetige die aufgefuehrten Preview-Entscheidungen und Modulstatuswechsel fuer diesen Tenant.</span>',
    '</label>',
    '<label for="foundation-workflow-confirmation">Bestaetigung exakt eingeben</label>',
    `<code>${escapeHtml(plan.confirmationPhrase)}</code>`,
    '<input id="foundation-workflow-confirmation" autocomplete="off" spellcheck="false" />',
    `<span class="foundation-workflow-confirmation-state" id="foundation-workflow-confirmation-state">${state.confirmationValue === plan.confirmationPhrase ? "Bestaetigung stimmt ueberein." : "Ausfuehrung bleibt gesperrt."}</span>`,
    '</section>',
  ].join("");
}

function syncFoundationWorkflowControls() {
  const state = foundationWorkflowState;
  if (!state) {
    foundationWorkflowRun.disabled = true;
    return;
  }
  const ready = state.acknowledged
    && state.confirmationValue === state.plan.confirmationPhrase
    && state.plan.tasks.length > 0
    && state.plan.blockers.length === 0
    && !state.running
    && !state.completed
    && !state.requiresReopen;
  foundationWorkflowRun.disabled = !ready;
  foundationWorkflowRun.hidden = state.completed || state.requiresReopen;
  foundationWorkflowRun.textContent = state.running ? "Workflow laeuft ..." : "Workflow ausfuehren";
  foundationWorkflowClose.disabled = state.running;
  foundationWorkflowCancel.disabled = state.running;
  foundationWorkflowCancel.textContent = state.completed || state.requiresReopen ? "Schliessen" : "Abbrechen";
  const confirmationState = foundationWorkflowContent.querySelector("#foundation-workflow-confirmation-state");
  if (confirmationState) {
    confirmationState.textContent = state.confirmationValue === state.plan.confirmationPhrase
      ? "Bestaetigung stimmt ueberein."
      : "Ausfuehrung bleibt gesperrt.";
  }
}

async function fetchFoundationWorkflowCockpit(context) {
  const response = await fetch("/v1/platform/cockpit", {
    headers: headersForContext(context),
  });
  const body = await readJson(response);
  if (!response.ok) {
    throw new Error(body.detail || `HTTP ${response.status}`);
  }
  return body;
}

async function runFoundationCompletionWorkflow() {
  const state = foundationWorkflowState;
  if (!state || foundationWorkflowRun.disabled) {
    return;
  }
  state.running = true;
  state.error = "";
  let activeTask = null;
  let executionStarted = false;
  renderFoundationCompletionWorkflow();
  setStatus("Foundation-Plan wird unmittelbar vor Ausfuehrung erneut validiert ...");
  try {
    const context = readContext();
    const freshCockpit = await fetchFoundationWorkflowCockpit(context);
    const freshPlan = buildFoundationCompletionPlan(freshCockpit, context);
    if (freshPlan.key !== state.plan.key) {
      applyCockpit(freshCockpit);
      throw new Error("Der Foundation-Plan ist veraltet. Cockpit wurde aktualisiert; Workflow erneut oeffnen.");
    }
    state.plan = freshPlan;
    currentCockpit = freshCockpit;

    for (const task of state.plan.tasks) {
      activeTask = task;
      executionStarted = true;
      state.taskStates[task.id] = { status: "running", detail: task.operations.join(" -> ") };
      renderFoundationCompletionWorkflow();

      if (task.phase === "preview") {
        const flow = (freshCockpit.source_object_flows || []).find((candidate) => candidate.flow_id === task.flowId);
        const result = flow
          ? await executeGuidedPreviewDecision(flow, { skipConfirmation: true, reloadAfter: false })
          : null;
        if (!result) {
          throw new Error(`Preview-Aufgabe ${task.subject} konnte nicht abgeschlossen werden.`);
        }
        state.taskStates[task.id] = {
          status: "completed",
          detail: result.decision_ledger_ref || result.preview_decision_evidence_hash || "Decision gespeichert",
        };
      } else {
        let module = (freshCockpit.modules || []).find((candidate) => candidate.module_id === task.moduleId);
        const auditRefs = [];
        if (!module) {
          throw new Error(`Modul ${task.moduleId} fehlt im frischen Cockpit.`);
        }
        for (const transition of task.transitions) {
          const action = moduleActionFor(module);
          if (!action || action.apiAction !== transition || !["provision", "enable"].includes(transition)) {
            throw new Error(`Modul ${task.moduleId} ist nicht mehr im erwarteten Zustand.`);
          }
          const result = await executeModuleAction(module, action, {
            skipConfirmation: true,
            reloadAfter: false,
            reason: `Workspace foundation completion ${transition} for ${task.moduleId}; exact tenant confirmation captured before execution. No domain data, persistent tasks, automations, content release, destructive or external action requested.`,
          });
          if (!result) {
            throw new Error(`Modulaktion ${task.moduleId}:${transition} konnte nicht abgeschlossen werden.`);
          }
          auditRefs.push(result.audit_chain_ref || `${transition}:recorded`);
          module = { ...module, ...result };
          state.taskStates[task.id] = {
            status: "running",
            detail: auditRefs.join(" | "),
          };
          renderFoundationCompletionWorkflow();
        }
        state.taskStates[task.id] = { status: "completed", detail: auditRefs.join(" | ") };
      }
      renderFoundationCompletionWorkflow();
    }

    const completionCockpit = await fetchFoundationWorkflowCockpit(context);
    applyCockpit(completionCockpit);
    state.remainingGapIds = (completionCockpit.foundation_gap_actions || [])
      .map((action) => action.gap_id)
      .filter((gapId) => foundationWorkflowGapIds.has(gapId));
    if (state.remainingGapIds.length) {
      throw new Error("Nicht alle Ziel-Gaps wurden geschlossen. Den aktualisierten Stand vor einer Fortsetzung pruefen.");
    }
    state.completed = true;
    setStatus(`Foundation-Abschluss fuer Tenant ${state.plan.tenantId} ausgefuehrt; Content-Release bleibt policy-gesteuert.`);
  } catch (error) {
    if (activeTask && state.taskStates[activeTask.id]?.status === "running") {
      state.taskStates[activeTask.id] = {
        status: "failed",
        detail: error.message || "Ausfuehrung fehlgeschlagen",
      };
    }
    state.error = error.message || "Foundation-Workflow konnte nicht abgeschlossen werden.";
    state.requiresReopen = true;
    setStatus(state.error, true);
    if (executionStarted) {
      await loadCockpit();
    }
  } finally {
    state.running = false;
    renderFoundationCompletionWorkflow();
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
  const mvpDecision = cockpit.mvp_readiness_decision || {};
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
  renderMvpReadinessSummary(mvpSummary, foundationGapActions, mvpDecision);
  renderFoundationWorkflowLaunch(cockpit);
  renderWorkItemOperationalSummary(workSummary);
  renderWorkItems(workItems);
  renderFlows(flows);
  loadSourceObjectDetail();
}

function renderMvpReadinessSummary(summary, foundationGapActions, decision) {
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
    renderMvpReadinessDecision(decision),
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

function renderMvpReadinessDecision(decision) {
  if (!decision || !decision.schema_version) {
    return "";
  }
  return [
    '<div class="mvp-readiness-decision" data-mvp-readiness-decision="true">',
    '<code>decision=' + escapeHtml(decision.decision || 'foundation_work_required')
      + ' | productive=' + (decision.metadata_only_productive_path === true ? 'true' : 'false') + '</code>',
    '<code>roles=' + escapeHtml((decision.required_roles || []).join(',') || 'context')
      + ' | role_gate=' + escapeHtml(decision.role_gate_status || 'context_only') + '</code>',
    '<code>audit=' + escapeHtml(decision.audit_gate_status || 'audit_not_ready')
      + ' ' + Number(decision.audit_visible_flow_count || 0) + '/' + Number(decision.audit_required_flow_count || 0)
      + ' | backup_failover=' + escapeHtml(decision.backup_failover_gate_status || 'review') + '</code>',
    '<code>modules=' + escapeHtml(decision.module_gate_status || 'review')
      + ' | content_gate=' + escapeHtml(decision.content_gate_status || 'review')
      + ' | foundation=' + escapeHtml(decision.foundation_gap_status || 'review') + '</code>',
    '</div>',
  ].join('');
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
    foundationGapEvidenceBrief(action.evidence_brief),
    foundationGapConfirmationBrief(action.confirmation_brief),
    foundationGapContentReleaseBrief(action.content_release_brief),
    foundationGapActionButton(action),
    '</div>',
    '</div>',
  ].join('')).join('');
  return '<div class="foundation-gap-plan">' + items + '</div>';
}

function foundationGapEvidenceBrief(brief) {
  if (!brief) {
    return "";
  }
  const needed = brief.evidence_required_now || [];
  const missing = brief.missing_evidence || [];
  const deferred = brief.deferred_evidence || [];
  const verified = brief.verified_evidence || [];
  const ledgerCount = (brief.decision_ledger_refs || []).length;
  const policyBlockCount = (brief.policy_blocking_reasons || []).length;
  return [
    '<div class="foundation-gap-evidence-brief" data-evidence-brief="true">',
    '<code>needed_now=' + escapeHtml(needed.length ? needed.join(',') : 'none') + '</code>',
    '<code>missing=' + escapeHtml(missing.length ? missing.join(',') : 'none') + '</code>',
    '<code>verified=' + escapeHtml(verified.length ? verified.join(',') : 'none') + '</code>',
    '<code>deferred=' + escapeHtml(deferred.length ? deferred.join(',') : 'none') + '</code>',
    '<code>ledger_refs=' + Number(ledgerCount) + ' | policy_blocks=' + Number(policyBlockCount)
      + ' | content_release=' + (brief.content_release_allowed === true ? 'allowed' : 'blocked') + '</code>',
    '</div>',
  ].join('');
}

function foundationGapConfirmationBrief(brief) {
  if (!brief) {
    return "";
  }
  const allCount = (brief.confirmation_work_item_ids || []).length;
  const coveredCount = (brief.covered_by_specific_gap_work_item_ids || []).length;
  const standaloneCount = (brief.standalone_work_item_ids || []).length;
  const coveringGaps = brief.covering_gap_ids || [];
  return [
    '<div class="foundation-gap-confirmation-brief" data-confirmation-brief="true">',
    '<code>confirmations=' + Number(allCount) + ' | covered=' + Number(coveredCount)
      + ' | standalone=' + Number(standaloneCount) + '</code>',
    '<code>covering_gaps=' + escapeHtml(coveringGaps.length ? coveringGaps.join(',') : 'none') + '</code>',
    '<code>next_confirmation_action=' + escapeHtml(brief.next_confirmation_action || 'review')
      + ' | separate=' + (brief.requires_separate_foundation_action === true ? 'true' : 'false') + '</code>',
    '</div>',
  ].join('');
}

function foundationGapContentReleaseBrief(brief) {
  if (!brief) {
    return "";
  }
  const dependencies = brief.deferred_dependencies || [];
  const blockingReasons = brief.blocking_reasons || [];
  return [
    '<div class="foundation-gap-content-release-brief" data-content-release-brief="true">',
    '<code>blocked_flows=' + Number(brief.content_release_blocked_count || 0)
      + ' | allowed=' + Number(brief.content_release_allowed_count || 0)
      + ' | content=' + Number(brief.content_included_count || 0) + '</code>',
    '<code>preview_pending=' + Number(brief.preview_decision_pending_count || 0)
      + ' | preview_blocked=' + Number(brief.preview_decision_blocked_count || 0)
      + ' | evidence_complete=' + Number(brief.preview_evidence_complete_but_content_blocked_count || 0)
      + '</code>',
    '<code>metadata_only_mvp_ready=' + (brief.metadata_only_mvp_ready === true ? 'true' : 'false')
      + ' | next_release_action=' + escapeHtml(brief.next_release_action || 'review_content_release_gate')
      + '</code>',
    '<code>deferred=' + escapeHtml(dependencies.length ? dependencies.join(',') : 'none')
      + ' | policy_blocks=' + Number(blockingReasons.length) + '</code>',
    '</div>',
  ].join('');
}

function foundationGapActionButton(action) {
  if (action.status !== "ready") {
    return "";
  }
  if (action.next_action === "resolve_preview_decision_work_items") {
    return [
      '<div class="foundation-gap-controls">',
      '<button class="action-button primary" type="button" data-foundation-gap-action="'
        + escapeHtml(action.gap_id) + '">Im Workflow pruefen</button>',
      '</div>',
    ].join("");
  }
  if (action.next_action === "complete_module_activation_work_items") {
    const disabled = canUseAnyRole(action.required_roles || []) ? "" : " disabled";
    return [
      '<div class="foundation-gap-controls">',
      '<button class="action-button primary" type="button" data-foundation-gap-action="'
        + escapeHtml(action.gap_id) + '"' + disabled + '>Im Workflow pruefen</button>',
      '</div>',
    ].join("");
  }
  return "";
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
  return contextHasAnyRole(readContext(), requiredRoles);
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
crmSearchForm.addEventListener("submit", runCrmErpSearch);
refreshButton.addEventListener("click", loadCockpit);
foundationWorkflowButton.addEventListener("click", () => openFoundationCompletionWorkflow());
foundationWorkflowRun.addEventListener("click", runFoundationCompletionWorkflow);
foundationWorkflowClose.addEventListener("click", closeFoundationCompletionWorkflow);
foundationWorkflowCancel.addEventListener("click", closeFoundationCompletionWorkflow);
foundationWorkflowDialog.addEventListener("cancel", (event) => {
  if (foundationWorkflowState?.running) {
    event.preventDefault();
    return;
  }
  foundationWorkflowState = null;
});
foundationWorkflowDialog.addEventListener("close", () => {
  foundationWorkflowState = null;
});
mvpReadinessPanel.addEventListener("click", (event) => {
  const button = event.target.closest("button[data-foundation-gap-action]");
  if (!button) {
    return;
  }
  const action = (currentCockpit.foundation_gap_actions || []).find(
    (candidate) => candidate.gap_id === button.dataset.foundationGapAction,
  );
  if (action) {
    executeFoundationGapAction(action);
  }
});

function closeFoundationCompletionWorkflow() {
  if (foundationWorkflowState?.running) {
    return;
  }
  foundationWorkflowDialog.close();
}
pilotDecisionPanel.addEventListener("click", (event) => {
  const button = event.target.closest("button[data-pilot-decision]");
  if (button?.dataset.pilotDecision) {
    submitPilotDecision(button.dataset.pilotDecision);
  }
});
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
