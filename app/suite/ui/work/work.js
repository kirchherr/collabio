const fields = {
  tenantId: document.querySelector("#tenant-id"),
  userId: document.querySelector("#user-id"),
  roleIds: document.querySelector("#role-ids"),
  readableObjectIds: document.querySelector("#readable-object-ids"),
};

const elements = {
  viewTitle: document.querySelector("#view-title"),
  viewEyebrow: document.querySelector("#view-eyebrow"),
  tenantLabel: document.querySelector("#tenant-label"),
  syncLine: document.querySelector("#sync-line"),
  refreshButton: document.querySelector("#refresh-button"),
  contextButton: document.querySelector("#context-button"),
  contextPanel: document.querySelector("#context-panel"),
  contextForm: document.querySelector("#context-form"),
  globalFilter: document.querySelector("#global-filter"),
  todayMetrics: document.querySelector("#today-metrics"),
  todayTaskList: document.querySelector("#today-task-list"),
  todayTimeList: document.querySelector("#today-time-list"),
  todayTicketList: document.querySelector("#today-ticket-list"),
  availabilityGrid: document.querySelector("#availability-grid"),
  taskList: document.querySelector("#task-list"),
  taskActivityList: document.querySelector("#task-activity-list"),
  timePeriodLabel: document.querySelector("#time-period-label"),
  timeMetrics: document.querySelector("#time-metrics"),
  timeEntryList: document.querySelector("#time-entry-list"),
  ticketList: document.querySelector("#ticket-list"),
  knowledgeList: document.querySelector("#knowledge-list"),
  knowledgeCreate: document.querySelector("#knowledge-create"),
  knowledgeResult: document.querySelector("#knowledge-result"),
  knowledgeEvidence: document.querySelector("#knowledge-evidence"),
  knowledgeVersion: document.querySelector("#knowledge-version"),
  knowledgePreview: document.querySelector("#knowledge-preview"),
  knowledgeApprove: document.querySelector("#knowledge-approve"),
  knowledgeExecute: document.querySelector("#knowledge-execute"),
  knowledgeConfirmation: document.querySelector("#knowledge-confirmation"),
  knowledgeConfirm: document.querySelector("#knowledge-confirm"),
  knowledgeReaderTitle: document.querySelector("#knowledge-reader-title"),
  knowledgeReaderBody: document.querySelector("#knowledge-reader-body"),
  knowledgeReaderMeta: document.querySelector("#knowledge-reader-meta"),
  knowledgeReaderVersion: document.querySelector("#knowledge-reader-version"),
  knowledgeReaderUpdated: document.querySelector("#knowledge-reader-updated"),
  knowledgeReaderMessage: document.querySelector("#knowledge-reader-message"),
  knowledgeReaderRefresh: document.querySelector("#knowledge-reader-refresh"),
  crmList: document.querySelector("#crm-list"),
  crmDetailTitle: document.querySelector("#crm-detail-title"),
  crmDetailStatus: document.querySelector("#crm-detail-status"),
  crmDetailContent: document.querySelector("#crm-detail-content"),
  crmDetailAccount: document.querySelector("#crm-detail-account"),
  crmDetailContacts: document.querySelector("#crm-detail-contacts"),
  crmDetailActivities: document.querySelector("#crm-detail-activities"),
  crmDetailRefresh: document.querySelector("#crm-detail-refresh"),
};

const dialogs = {
  task: document.querySelector("#task-dialog"),
  taskAmendment: document.querySelector("#task-amendment-dialog"),
  taskTransition: document.querySelector("#task-transition-dialog"),
  time: document.querySelector("#time-dialog"),
  timeCorrection: document.querySelector("#time-correction-dialog"),
  timeApproval: document.querySelector("#time-approval-dialog"),
  ticket: document.querySelector("#ticket-dialog"),
  ticketTransition: document.querySelector("#ticket-transition-dialog"),
  knowledge: document.querySelector("#knowledge-dialog"),
  knowledgeReader: document.querySelector("#knowledge-reader-dialog"),
  crmDetail: document.querySelector("#crm-detail-dialog"),
};

const forms = {
  task: document.querySelector("#task-form"),
  taskAmendment: document.querySelector("#task-amendment-form"),
  taskTransition: document.querySelector("#task-transition-form"),
  time: document.querySelector("#time-form"),
  timeCorrection: document.querySelector("#time-correction-form"),
  timeApproval: document.querySelector("#time-approval-form"),
  ticket: document.querySelector("#ticket-form"),
  ticketTransition: document.querySelector("#ticket-transition-form"),
  knowledge: document.querySelector("#knowledge-form"),
};

const storageKey = "collabio.workspace.context";
const defaultReadableObjectIds = [
  "doc-1",
  "mail-1",
  "kb-article-backup-runbook-demo",
  "kb-article-version-backup-runbook-v1-demo",
  "kb-article-security-baseline-demo",
  "kb-article-version-security-baseline-v1-demo",
  "crm-account-acme-demo",
  "crm-account-northwind-demo",
  "crm-contact-ada-demo",
  "crm-activity-followup-demo",
  "crm-note-acme-demo",
  "erp-product-standard-widget-demo",
  "erp-order-acme-widget-demo",
  "erp-invoice-acme-widget-demo",
].join(",");

const resourceDefinitions = {
  tasks: { label: "Aufgaben", path: "/v1/tasks/items", collection: "items" },
  taskActivities: { label: "Aktivitaeten", path: "/v1/tasks/activities", collection: "activities" },
  timeEntries: { label: "Zeit", path: "/v1/time-tracking/entries", collection: "entries" },
  timeApprovals: { label: "Freigaben", path: "/v1/time-tracking/approvals", collection: "approvals" },
  tickets: { label: "Tickets", path: "/v1/tickets", collection: "tickets" },
  knowledge: { label: "Wissen", path: "/v1/kb/articles", collection: "articles" },
  crm: { label: "Kontakte", path: "/v1/crm/accounts", collection: "accounts" },
};

const viewMetadata = {
  today: { title: "Heute", eyebrow: "Persoenlicher Arbeitsbereich" },
  tasks: { title: "Aufgaben", eyebrow: "Tasks & Activities" },
  time: { title: "Zeiterfassung", eyebrow: "Arbeitszeit" },
  tickets: { title: "Tickets", eyebrow: "Service & Incidents" },
  knowledge: { title: "Wissen", eyebrow: "Knowledge Base" },
  crm: { title: "Kontakte", eyebrow: "CRM" },
};

const statusLabels = {
  new: "Neu",
  open: "Offen",
  triaged: "Eingeordnet",
  assigned: "Zugewiesen",
  in_progress: "In Arbeit",
  waiting: "Wartet",
  blocked: "Blockiert",
  completed: "Erledigt",
  resolved: "Geloest",
  cancelled: "Storniert",
  archived: "Archiviert",
  recorded: "Erfasst",
  not_submitted: "Nicht eingereicht",
  submitted: "Eingereicht",
  approved: "Freigegeben",
  rejected: "Abgelehnt",
  correction_requested: "Korrektur",
  published: "Veroeffentlicht",
  draft: "Entwurf",
  restricted: "Geschuetzt",
  working: "In Arbeit",
  on_track: "Im Plan",
  at_risk: "Gefaehrdet",
  breached: "Ueberschritten",
  paused: "Pausiert",
  not_started: "Nicht gestartet",
};

const priorityLabels = {
  urgent: "Dringend",
  high: "Hoch",
  normal: "Normal",
  low: "Niedrig",
};

const ticketTransitions = {
  new: ["open", "triaged"],
  open: ["triaged", "in_progress", "waiting", "resolved"],
  triaged: ["in_progress", "waiting", "resolved"],
  in_progress: ["waiting", "resolved"],
  waiting: ["in_progress", "resolved"],
  resolved: ["open"],
  cancelled: ["open"],
  archived: [],
};

const taskTransitions = {
  assigned: [
    { target: "in_progress", kind: "started" },
    { target: "blocked", kind: "blocked" },
    { target: "completed", kind: "completed" },
  ],
  in_progress: [
    { target: "blocked", kind: "blocked" },
    { target: "completed", kind: "completed" },
  ],
  blocked: [{ target: "in_progress", kind: "resumed" }],
};

const timeApprovalTransitions = {
  not_submitted: [{ target: "submitted", action: "submit" }],
  submitted: [
    { target: "approved", action: "approve" },
    { target: "rejected", action: "reject" },
    { target: "correction_requested", action: "request_correction" },
  ],
  correction_requested: [{ target: "submitted", action: "submit" }],
};

const state = {
  currentView: "today",
  query: "",
  taskFilter: "active",
  ticketFilter: "open",
  loading: false,
  refreshGeneration: 0,
  refreshContext: "",
  knowledgeEditor: null,
  knowledgeReader: null,
  crmDetail: null,
  resources: Object.fromEntries(
    Object.keys(resourceDefinitions).map((key) => [key, { status: "idle", items: [], detail: "" }]),
  ),
};

class ApiError extends Error {
  constructor(message, status) {
    super(message);
    this.name = "ApiError";
    this.status = status;
  }
}

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
  elements.tenantLabel.textContent = fields.tenantId.value;
}

function restoreContext() {
  const saved = window.localStorage.getItem(storageKey);
  if (!saved) {
    writeContext({});
    return;
  }
  try {
    writeContext(JSON.parse(saved) || {});
  } catch {
    window.localStorage.removeItem(storageKey);
    writeContext({});
  }
}

function persistContext() {
  const context = readContext();
  window.localStorage.setItem(storageKey, JSON.stringify(context));
  elements.tenantLabel.textContent = context.tenantId || "Tenant fehlt";
}

function headersForContext(context, includeJson = false) {
  const headers = {
    "X-Tenant-Id": context.tenantId,
    "X-User-Id": context.userId,
    "X-Role-Ids": context.roleIds,
    "X-Readable-Object-Ids": context.readableObjectIds,
  };
  if (includeJson) {
    headers["Content-Type"] = "application/json";
  }
  return headers;
}

async function readJson(response) {
  const text = await response.text();
  if (!text) {
    return {};
  }
  try {
    return JSON.parse(text);
  } catch {
    throw new ApiError(`Ungueltige Serverantwort (HTTP ${response.status})`, response.status);
  }
}

async function apiRequest(path, options = {}) {
  const context = readContext();
  const hasBody = options.body !== undefined;
  const response = await fetch(path, {
    ...options,
    headers: {
      ...headersForContext(context, hasBody),
      ...(options.headers || {}),
    },
  });
  const body = await readJson(response);
  if (!response.ok) {
    const detail = typeof body.detail === "string" ? body.detail : `HTTP ${response.status}`;
    throw new ApiError(detail, response.status);
  }
  return body;
}

async function loadResource(key) {
  const definition = resourceDefinitions[key];
  const generation = state.refreshGeneration;
  const context = JSON.stringify(readContext());
  const pending = { status: "loading", items: [], detail: "" };
  state.resources[key] = pending;
  const isCurrent = () => generation === state.refreshGeneration &&
    context === JSON.stringify(readContext()) && state.resources[key] === pending;
  try {
    const body = await apiRequest(definition.path);
    if (!isCurrent()) {
      return;
    }
    const items = Array.isArray(body[definition.collection]) ? body[definition.collection] : [];
    state.resources[key] = {
      status: "ready",
      items,
      detail: "",
      auditEventId: body.audit_event_id || "",
      canWrite: key === "knowledge" && body.can_write === true,
    };
  } catch (error) {
    if (!isCurrent()) {
      return;
    }
    const status = error instanceof ApiError && [403, 404, 423].includes(error.status) ? "blocked" : "error";
    state.resources[key] = {
      status,
      items: [],
      detail: error instanceof Error ? error.message : "Unbekannter Fehler",
      httpStatus: error instanceof ApiError ? error.status : 0,
    };
  }
}

async function refreshAll() {
  const context = readContext();
  const contextSnapshot = JSON.stringify(context);
  if (state.loading && state.refreshContext === contextSnapshot) {
    return;
  }
  const generation = ++state.refreshGeneration;
  state.refreshContext = contextSnapshot;
  Object.keys(resourceDefinitions).forEach((key) => {
    state.resources[key] = { status: "loading", items: [], detail: "" };
  });
  renderAll();
  if (!context.tenantId || !context.userId) {
    state.loading = false;
    elements.refreshButton.disabled = false;
    setSyncStatus("Tenant und User sind erforderlich.", true);
    elements.contextPanel.hidden = false;
    return;
  }
  persistContext();
  state.loading = true;
  elements.refreshButton.disabled = true;
  setSyncStatus("Arbeitsbereich wird aktualisiert ...");
  await Promise.allSettled(Object.keys(resourceDefinitions).map((key) => loadResource(key)));
  if (generation !== state.refreshGeneration) {
    return;
  }
  state.loading = false;
  elements.refreshButton.disabled = false;
  if (contextSnapshot !== JSON.stringify(readContext())) {
    Object.keys(resourceDefinitions).forEach((key) => {
      state.resources[key] = { status: "idle", items: [], detail: "" };
    });
    setSyncStatus("Kontext geaendert. Bitte Kontext anwenden.");
    renderAll();
    return;
  }
  const readyCount = Object.values(state.resources).filter((resource) => resource.status === "ready").length;
  const blockedCount = Object.values(state.resources).filter((resource) => resource.status === "blocked").length;
  setSyncStatus(
    `Stand ${new Date().toLocaleTimeString("de-DE", { hour: "2-digit", minute: "2-digit" })} | ${readyCount}/7 Bereiche bereit${blockedCount ? ` | ${blockedCount} gesperrt` : ""}`,
    readyCount === 0,
  );
  renderAll();
}

function setSyncStatus(message, isError = false) {
  elements.syncLine.textContent = message;
  elements.syncLine.classList.toggle("error", isError);
}

function resourceItems(key) {
  return state.resources[key]?.status === "ready" ? state.resources[key].items : [];
}

function isActiveTask(item) {
  return !["completed", "cancelled", "archived"].includes(item.lifecycle_state);
}

function isOpenTicket(item) {
  return !["resolved", "cancelled", "archived"].includes(item.ticket_status);
}

function localDateKey(date = new Date()) {
  const year = date.getFullYear();
  const month = String(date.getMonth() + 1).padStart(2, "0");
  const day = String(date.getDate()).padStart(2, "0");
  return `${year}-${month}-${day}`;
}

function filterMatches(...values) {
  if (!state.query) {
    return true;
  }
  return values.some((value) => String(value || "").toLocaleLowerCase("de-DE").includes(state.query));
}

function renderAll() {
  renderToday();
  renderTasks();
  renderTime();
  renderTickets();
  renderKnowledge();
  renderCrm();
  renderAvailability();
}

function renderToday() {
  const tasks = resourceItems("tasks").filter(isActiveTask);
  const today = localDateKey();
  const entries = resourceItems("timeEntries").filter((entry) => entry.work_date === today);
  const tickets = resourceItems("tickets").filter(isOpenTicket);
  const knowledge = resourceItems("knowledge");
  const minutes = entries.reduce((total, entry) => total + Number(entry.duration_minutes || 0), 0);

  elements.todayMetrics.innerHTML = [
    metric("Offene Aufgaben", resourceValue("tasks", tasks.length), "Autorisierte Eintraege"),
    metric("Zeit heute", resourceValue("timeEntries", formatDuration(minutes)), localDateLabel(today)),
    metric("Offene Tickets", resourceValue("tickets", tickets.length), "Ohne geloeste Eintraege"),
    metric("Wissensartikel", resourceValue("knowledge", knowledge.length), "Autorisierte Quellen"),
  ].join("");

  if (state.resources.tasks.status !== "ready") {
    elements.todayTaskList.innerHTML = resourceState("tasks");
  } else {
    const visibleTasks = tasks.filter((item) => filterMatches(item.title, item.task_number, item.assigned_principal_id));
    elements.todayTaskList.innerHTML = visibleTasks.length
      ? visibleTasks.slice(0, 7).map(todayTaskRow).join("")
      : emptyState("Keine offenen Aufgaben.");
  }

  if (state.resources.timeEntries.status !== "ready") {
    elements.todayTimeList.innerHTML = resourceState("timeEntries");
  } else {
    elements.todayTimeList.innerHTML = entries.length
      ? entries.slice(0, 4).map(todayTimeRow).join("")
      : emptyState("Heute keine Zeit erfasst.");
  }

  if (state.resources.tickets.status !== "ready") {
    elements.todayTicketList.innerHTML = resourceState("tickets");
  } else {
    elements.todayTicketList.innerHTML = tickets.length
      ? tickets.slice(0, 4).map(todayTicketRow).join("")
      : emptyState("Keine offenen Tickets.");
  }
}

function renderTasks() {
  const resource = state.resources.tasks;
  if (resource.status !== "ready") {
    elements.taskList.innerHTML = resourceState("tasks");
  } else {
    const items = resource.items.filter((item) => {
      if (state.taskFilter === "active" && !isActiveTask(item)) {
        return false;
      }
      if (state.taskFilter === "completed" && item.lifecycle_state !== "completed") {
        return false;
      }
      return filterMatches(item.title, item.task_number, item.assigned_principal_id, item.priority);
    });
    elements.taskList.innerHTML = items.length ? items.map(taskRow).join("") : emptyState("Keine Aufgaben im Filter.");
    elements.taskList.querySelectorAll("[data-task-transition]").forEach((button) => {
      button.addEventListener("click", () => openTaskTransition(button.dataset.taskTransition));
    });
    elements.taskList.querySelectorAll("[data-task-amendment]").forEach((button) => {
      button.addEventListener("click", () => openTaskAmendment(button.dataset.taskAmendment));
    });
  }

  const activityResource = state.resources.taskActivities;
  if (activityResource.status !== "ready") {
    elements.taskActivityList.innerHTML = resourceState("taskActivities");
  } else {
    const activities = activityResource.items.filter((item) =>
      filterMatches(item.summary, item.activity_number, item.activity_type),
    );
    elements.taskActivityList.innerHTML = activities.length
      ? activities.slice(0, 30).map(activityRow).join("")
      : emptyState("Keine Aktivitaeten im Filter.");
  }
}

function renderTime() {
  const entriesResource = state.resources.timeEntries;
  const approvals = new Map(
    resourceItems("timeApprovals").map((approval) => [approval.entry_object_id, approval]),
  );
  const entries = resourceItems("timeEntries").filter((entry) =>
    filterMatches(entry.entry_number, entry.worker_principal_id, entry.project_reference, entry.cost_center_reference),
  );
  const totalMinutes = entries.reduce((total, entry) => total + Number(entry.duration_minutes || 0), 0);
  const currentMonth = new Intl.DateTimeFormat("de-DE", { month: "long", year: "numeric" }).format(new Date());
  elements.timePeriodLabel.textContent = currentMonth;
  elements.timeMetrics.innerHTML = [
    metric("Gesamt", entriesResource.status === "ready" ? formatDuration(totalMinutes) : "-", "Aktueller Filter"),
    metric("Eintraege", entriesResource.status === "ready" ? entries.length : "-", "Autorisierte Eintraege"),
    metric("Offen", approvalMetric(approvals, "not_submitted"), "Nicht eingereicht"),
    metric("Freigegeben", approvalMetric(approvals, "approved"), "Approval-Status"),
  ].join("");

  if (entriesResource.status !== "ready") {
    elements.timeEntryList.innerHTML = resourceState("timeEntries");
    return;
  }
  elements.timeEntryList.innerHTML = entries.length
    ? entries.map((entry) => timeRow(entry, approvals.get(entry.object_id))).join("")
    : emptyState("Keine Zeiteintraege im Filter.");
  elements.timeEntryList.querySelectorAll("[data-time-approval]").forEach((button) => {
    button.addEventListener("click", () => openTimeApproval(button.dataset.timeApproval));
  });
  elements.timeEntryList.querySelectorAll("[data-time-correction]").forEach((button) => {
    button.addEventListener("click", () => openTimeCorrection(button.dataset.timeCorrection));
  });
}

function renderTickets() {
  const resource = state.resources.tickets;
  if (resource.status !== "ready") {
    elements.ticketList.innerHTML = resourceState("tickets");
    return;
  }
  const items = resource.items.filter((item) => {
    if (state.ticketFilter === "open" && !isOpenTicket(item)) {
      return false;
    }
    if (state.ticketFilter === "resolved" && !["resolved", "archived"].includes(item.ticket_status)) {
      return false;
    }
    return filterMatches(item.subject_redacted, item.ticket_number, item.owner_principal_id, item.ticket_status);
  });
  elements.ticketList.innerHTML = items.length ? items.map(ticketRow).join("") : emptyState("Keine Tickets im Filter.");
  elements.ticketList.querySelectorAll("[data-ticket-transition]").forEach((button) => {
    button.addEventListener("click", () => openTicketTransition(button.dataset.ticketTransition));
  });
}

function renderKnowledge() {
  const resource = state.resources.knowledge;
  elements.knowledgeCreate.hidden = resource.status !== "ready" || !resource.canWrite;
  if (resource.status !== "ready") {
    elements.knowledgeList.innerHTML = resourceState("knowledge");
    return;
  }
  const items = resource.items.filter((item) =>
    filterMatches(item.title, item.article_key, item.current_version_label, item.status),
  );
  elements.knowledgeList.innerHTML = items.length
    ? items.map(knowledgeItem).join("")
    : emptyState("Keine Wissensartikel im Filter.");
  elements.knowledgeList.querySelectorAll("[data-knowledge-edit]").forEach((button) => {
    button.addEventListener("click", () => openKnowledgeEditor(button.dataset.knowledgeEdit));
  });
  elements.knowledgeList.querySelectorAll("[data-knowledge-read]").forEach((button) => {
    button.addEventListener("click", () => openKnowledgeReader(button.dataset.knowledgeRead));
  });
}

function renderCrm() {
  const resource = state.resources.crm;
  if (resource.status !== "ready") {
    elements.crmList.innerHTML = resourceState("crm");
    return;
  }
  const items = resource.items.filter((item) =>
    filterMatches(item.display_name, item.account_number, item.account_kind, item.status),
  );
  elements.crmList.innerHTML = items.length ? items.map(crmRow).join("") : emptyState("Keine Accounts im Filter.");
  elements.crmList.querySelectorAll("[data-crm-detail]").forEach((button) => {
    button.addEventListener("click", () => openCrmDetail(button.dataset.crmDetail));
  });
}

function renderAvailability() {
  const groups = [
    ["Aufgaben", ["tasks", "taskActivities"]],
    ["Zeiterfassung", ["timeEntries", "timeApprovals"]],
    ["Tickets", ["tickets"]],
    ["Wissen", ["knowledge"]],
    ["CRM", ["crm"]],
  ];
  elements.availabilityGrid.innerHTML = groups
    .map(([label, keys]) => {
      const resources = keys.map((key) => state.resources[key]);
      const ready = resources.every((resource) => resource.status === "ready");
      const loading = resources.some((resource) => ["idle", "loading"].includes(resource.status));
      const detail = ready
        ? `${resources.reduce((sum, resource) => sum + resource.items.length, 0)} autorisierte Eintraege`
        : loading
          ? "Wird geladen"
          : displayResourceDetail(resources.find((resource) => resource.detail)) || "Nicht verfuegbar";
      return `
        <div class="availability-item">
          <strong>${escapeHtml(label)}</strong>
          <small title="${escapeHtml(detail)}">${escapeHtml(detail)}</small>
          <span class="availability-state ${ready ? "" : "blocked"}">${ready ? "Bereit" : loading ? "Laedt" : "Gesperrt"}</span>
        </div>
      `;
    })
    .join("");
}

function metric(label, value, detail) {
  return `<div class="metric"><span>${escapeHtml(label)}</span><strong>${escapeHtml(value)}</strong><small>${escapeHtml(detail)}</small></div>`;
}

function resourceValue(key, value) {
  return state.resources[key].status === "ready" ? String(value) : "-";
}

function approvalMetric(approvals, expectedState) {
  if (state.resources.timeApprovals.status !== "ready") {
    return "-";
  }
  return String([...approvals.values()].filter((item) => item.approval_state === expectedState).length);
}

function todayTaskRow(item) {
  return `
    <article class="data-row today-task-row">
      <div class="row-primary"><strong>${escapeHtml(item.title)}</strong><small>${escapeHtml(item.task_number)} · ${escapeHtml(item.assigned_principal_id)}</small></div>
      ${priorityPill(item.priority)}
      <span class="date-cell">${escapeHtml(item.due_at_utc ? formatDate(item.due_at_utc) : "Ohne Termin")}</span>
    </article>
  `;
}

function todayTimeRow(entry) {
  return `
    <article class="data-row today-compact-row">
      <div class="row-primary"><strong>${escapeHtml(formatTimeRange(entry.started_at_utc, entry.ended_at_utc))}</strong><small>${escapeHtml(entry.project_reference || entry.entry_number)}</small></div>
      <span class="duration-cell">${escapeHtml(formatDuration(entry.duration_minutes))}</span>
    </article>
  `;
}

function todayTicketRow(ticket) {
  return `
    <article class="data-row today-compact-row">
      <div class="row-primary"><strong>${escapeHtml(ticket.subject_redacted)}</strong><small>${escapeHtml(ticket.ticket_number)}</small></div>
      ${statusPill(ticket.ticket_status)}
    </article>
  `;
}

function taskRow(item) {
  const canTransition = (taskTransitions[item.lifecycle_state] || []).length > 0;
  const canAmend = isActiveTask(item);
  return `
    <article class="data-row task-row">
      <div class="row-primary"><strong>${escapeHtml(item.title)}</strong><small>${escapeHtml(item.task_number)} · ${escapeHtml(item.assigned_principal_id)}</small></div>
      ${priorityPill(item.priority)}
      <span class="date-cell">${escapeHtml(item.due_at_utc ? formatDateTime(item.due_at_utc) : "Ohne Termin")}</span>
      ${statusPill(item.lifecycle_state)}
      <div class="row-actions">
        <button class="icon-button row-action" type="button" data-task-amendment="${escapeHtml(item.object_id)}" title="Zuweisung oder Termin aendern" aria-label="Zuweisung oder Termin von ${escapeHtml(item.task_number)} aendern" ${canAmend ? "" : "disabled"}><span aria-hidden="true">&#9998;</span></button>
        <button class="icon-button row-action" type="button" data-task-transition="${escapeHtml(item.object_id)}" title="Status aendern" aria-label="Status von ${escapeHtml(item.task_number)} aendern" ${canTransition ? "" : "disabled"}><span aria-hidden="true">›</span></button>
      </div>
    </article>
  `;
}

function activityRow(item) {
  return `
    <article class="timeline-item">
      <time datetime="${escapeHtml(item.occurred_at_utc)}">${escapeHtml(formatDateTime(item.occurred_at_utc))}</time>
      <div><strong>${escapeHtml(item.summary)}</strong><small>${escapeHtml(statusLabels[item.activity_type] || humanize(item.activity_type))} · ${escapeHtml(item.activity_number)}</small></div>
    </article>
  `;
}

function timeRow(entry, approval) {
  const approvalState = approval?.approval_state || "not_submitted";
  const canCorrect = approvalState === "correction_requested";
  const canTransition =
    Boolean(approval) &&
    (timeApprovalTransitions[approvalState] || []).length > 0 &&
    (!canCorrect || Number(entry.revision_no || 0) > 0);
  const assignment = [entry.project_reference, entry.cost_center_reference].filter(Boolean).join(" · ") || entry.worker_principal_id;
  return `
    <article class="data-row time-row">
      <span class="date-cell">${escapeHtml(localDateLabel(entry.work_date))}</span>
      <div class="row-primary"><strong>${escapeHtml(formatTimeRange(entry.started_at_utc, entry.ended_at_utc))}</strong><small>${escapeHtml(entry.entry_number)}</small></div>
      <span class="muted">${escapeHtml(assignment)}</span>
      <span class="duration-cell">${escapeHtml(formatDuration(entry.duration_minutes))}</span>
      ${statusPill(approvalState)}
      <div class="row-actions">
        <button class="icon-button row-action" type="button" data-time-correction="${escapeHtml(entry.object_id)}" title="Zeiteintrag korrigieren" aria-label="${escapeHtml(entry.entry_number)} korrigieren" ${canCorrect ? "" : "disabled"}><span aria-hidden="true">&#9998;</span></button>
        <button class="icon-button row-action" type="button" data-time-approval="${escapeHtml(approval?.object_id || "")}" title="Freigabe bearbeiten" aria-label="Freigabe von ${escapeHtml(entry.entry_number)} bearbeiten" ${canTransition ? "" : "disabled"}><span aria-hidden="true">›</span></button>
      </div>
    </article>
  `;
}

function ticketRow(item) {
  const canTransition = (ticketTransitions[item.ticket_status] || []).length > 0;
  return `
    <article class="data-row ticket-row">
      <div class="row-primary"><strong>${escapeHtml(item.subject_redacted)}</strong><small>${escapeHtml(item.ticket_number)} · ${escapeHtml(item.owner_principal_id)}</small></div>
      ${priorityPill(item.priority)}
      ${statusPill(item.ticket_status)}
      ${statusPill(item.sla_state)}
      <button class="icon-button row-action" type="button" data-ticket-transition="${escapeHtml(item.ticket_id)}" title="Status aendern" aria-label="Status von ${escapeHtml(item.ticket_number)} aendern" ${canTransition ? "" : "disabled"}><span aria-hidden="true">›</span></button>
    </article>
  `;
}

function knowledgeItem(item) {
  return `
    <article class="knowledge-item">
      <div><span class="status-pill ${statusClass(item.status)}">${escapeHtml(statusLabels[item.status] || humanize(item.status))}</span><h3>${escapeHtml(item.title)}</h3></div>
      <div class="knowledge-meta"><span>${escapeHtml(item.article_key)}</span><span>${escapeHtml(item.current_version_label)}</span><span>${escapeHtml(formatDate(item.updated_at_utc))}</span></div>
      <div class="knowledge-actions">
        <button class="button secondary" type="button" data-knowledge-read="${escapeHtml(item.object_id)}" aria-label="Artikel ${escapeHtml(item.title)} lesen">Artikel lesen</button>
        ${state.resources.knowledge.canWrite ? `<button class="button secondary" type="button" data-knowledge-edit="${escapeHtml(item.object_id)}" aria-label="Artikel ${escapeHtml(item.title)} bearbeiten">Artikel bearbeiten</button>` : ""}
      </div>
    </article>
  `;
}

function crmRow(item) {
  return `
    <article class="data-row crm-row">
      <div class="row-primary"><strong>${escapeHtml(item.display_name)}</strong><small>${escapeHtml(item.owner_principal_id)}</small></div>
      <span class="number-cell">${escapeHtml(item.account_number || "-")}</span>
      <span class="muted">${escapeHtml(humanize(item.account_kind))}</span>
      ${statusPill(item.status)}
      <button class="button secondary crm-detail-action" type="button" data-crm-detail="${escapeHtml(item.object_id)}" aria-label="Kontodetails fuer ${escapeHtml(item.display_name)}">Kontodetails</button>
    </article>
  `;
}

function statusPill(status) {
  return `<span class="status-pill ${statusClass(status)}">${escapeHtml(statusLabels[status] || humanize(status))}</span>`;
}

function priorityPill(priority) {
  return `<span class="priority-pill ${statusClass(priority)}">${escapeHtml(priorityLabels[priority] || humanize(priority))}</span>`;
}

function statusClass(value) {
  return String(value || "pending").toLowerCase().replace(/[^a-z0-9_]+/g, "_");
}

function humanize(value) {
  return String(value || "-")
    .replaceAll("_", " ")
    .replace(/^./, (character) => character.toUpperCase());
}

function resourceState(key) {
  const resource = state.resources[key];
  if (["idle", "loading"].includes(resource.status)) {
    return emptyState(`${resourceDefinitions[key].label} wird geladen ...`);
  }
  return `<div class="resource-error"><div><strong>${resource.status === "blocked" ? "Bereich gesperrt" : "Bereich nicht verfuegbar"}</strong><span>${escapeHtml(displayResourceDetail(resource))}</span></div></div>`;
}

function displayResourceDetail(resource) {
  const detail = resource?.detail || "Keine Detailinformation";
  if (detail.includes("productivity_pilot_runtime_disabled")) {
    return "Pilot-Laufzeit geschlossen";
  }
  if (detail.includes("operation_outside_productivity_pilot_route_scope")) {
    return "Nicht im aktuellen Pilotumfang";
  }
  if (detail.includes("Unknown tenant module")) {
    return "Modul fuer diesen Tenant nicht bereit";
  }
  if (detail.includes("Module is not enabled for normal use")) {
    return "Modul fuer normale Nutzung deaktiviert";
  }
  return detail;
}

function emptyState(message) {
  return `<div class="empty-state">${escapeHtml(message)}</div>`;
}

function formatDate(value) {
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) {
    return String(value || "-");
  }
  return new Intl.DateTimeFormat("de-DE", { day: "2-digit", month: "2-digit", year: "numeric" }).format(date);
}

function formatDateTime(value) {
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) {
    return String(value || "-");
  }
  return new Intl.DateTimeFormat("de-DE", {
    day: "2-digit",
    month: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
  }).format(date);
}

function formatTimeRange(start, end) {
  const formatter = new Intl.DateTimeFormat("de-DE", { hour: "2-digit", minute: "2-digit" });
  const startDate = new Date(start);
  const endDate = new Date(end);
  if (Number.isNaN(startDate.getTime()) || Number.isNaN(endDate.getTime())) {
    return "-";
  }
  return `${formatter.format(startDate)}–${formatter.format(endDate)}`;
}

function formatDuration(minutes) {
  const value = Number(minutes || 0);
  const hours = Math.floor(value / 60);
  const remainder = value % 60;
  if (!hours) {
    return `${remainder} min`;
  }
  return remainder ? `${hours} h ${remainder} min` : `${hours} h`;
}

function localDateLabel(value) {
  const parts = String(value).split("-");
  if (parts.length !== 3) {
    return String(value || "-");
  }
  const date = new Date(Number(parts[0]), Number(parts[1]) - 1, Number(parts[2]));
  return new Intl.DateTimeFormat("de-DE", { day: "2-digit", month: "short", year: "numeric" }).format(date);
}

function escapeHtml(value) {
  return String(value ?? "")
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#039;");
}

function setView(view, updateHash = true) {
  const normalized = viewMetadata[view] ? view : "today";
  state.currentView = normalized;
  document.querySelectorAll("[data-view]").forEach((button) => {
    button.classList.toggle("active", button.dataset.view === normalized);
  });
  document.querySelectorAll("[data-view-panel]").forEach((panel) => {
    panel.classList.toggle("active", panel.dataset.viewPanel === normalized);
  });
  elements.viewTitle.textContent = viewMetadata[normalized].title;
  elements.viewEyebrow.textContent = viewMetadata[normalized].eyebrow;
  if (updateHash) {
    window.history.replaceState(null, "", normalized === "today" ? "/work" : `/work#${normalized}`);
  }
}

function openDialog(dialog) {
  if (!dialog) {
    return;
  }
  const form = dialog.querySelector("form");
  if (form) {
    form.reset();
    clearFormMessage(form);
  }
  prefillDialog(dialog);
  dialog.showModal();
}

function prefillDialog(dialog) {
  const context = readContext();
  if (dialog === dialogs.task) {
    forms.task.elements.assigned_principal_id.value = context.userId;
  }
  if (dialog === dialogs.time) {
    forms.time.elements.worker_principal_id.value = context.userId;
    const now = new Date();
    now.setSeconds(0, 0);
    const end = new Date(now.getTime() + 60 * 60 * 1000);
    forms.time.elements.started_at_utc.value = toLocalInputValue(now);
    forms.time.elements.ended_at_utc.value = toLocalInputValue(end);
  }
  if (dialog === dialogs.ticket) {
    forms.ticket.elements.owner_principal_id.value = context.userId;
  }
}

function toLocalInputValue(date) {
  const offset = date.getTimezoneOffset() * 60 * 1000;
  return new Date(date.getTime() - offset).toISOString().slice(0, 16);
}

function setFormMessage(form, message, success = false) {
  const target = form.querySelector("[data-form-message]");
  target.textContent = message;
  target.classList.add("visible");
  target.classList.toggle("success", success);
}

function clearFormMessage(form) {
  const target = form.querySelector("[data-form-message]");
  target.textContent = "";
  target.classList.remove("visible", "success");
}

function setFormBusy(form, busy) {
  form.querySelectorAll("button, input, select, textarea").forEach((control) => {
    control.disabled = busy;
  });
}

function generatedId(prefix) {
  const id = window.crypto?.randomUUID ? window.crypto.randomUUID() : `${Date.now()}-${Math.random().toString(16).slice(2)}`;
  return `${prefix}-${id}`;
}

function shortNumber(prefix) {
  const now = new Date();
  const stamp = [
    now.getFullYear(),
    String(now.getMonth() + 1).padStart(2, "0"),
    String(now.getDate()).padStart(2, "0"),
    String(now.getHours()).padStart(2, "0"),
    String(now.getMinutes()).padStart(2, "0"),
    String(now.getSeconds()).padStart(2, "0"),
  ].join("");
  return `${prefix}-${stamp}-${Math.random().toString(36).slice(2, 6).toUpperCase()}`;
}

function optionalValue(value) {
  const normalized = String(value || "").trim();
  return normalized || null;
}

function rememberReadableObjectIds(objectIds) {
  const current = new Set(
    fields.readableObjectIds.value
      .split(",")
      .map((item) => item.trim())
      .filter(Boolean),
  );
  objectIds.filter(Boolean).forEach((objectId) => current.add(objectId));
  fields.readableObjectIds.value = [...current].join(",");
  persistContext();
}

function clearCrmDetailContent() {
  elements.crmDetailTitle.textContent = "Kontodetails";
  elements.crmDetailContent.hidden = true;
  elements.crmDetailContent.scrollTop = 0;
  elements.crmDetailAccount.replaceChildren();
  elements.crmDetailContacts.replaceChildren();
  elements.crmDetailActivities.replaceChildren();
  elements.crmDetailStatus.textContent = "";
  elements.crmDetailStatus.classList.remove("error");
}

function closeCrmDetail() {
  state.crmDetail = null;
  clearCrmDetailContent();
  dialogs.crmDetail.removeAttribute("aria-busy");
  dialogs.crmDetail.close();
}

function openCrmDetail(accountObjectId) {
  if (!resourceItems("crm").some((account) => account.object_id === accountObjectId)) {
    return;
  }
  state.crmDetail = {
    accountObjectId,
    context: JSON.stringify(readContext()),
    requestNumber: 0,
  };
  clearCrmDetailContent();
  if (!dialogs.crmDetail.open) {
    dialogs.crmDetail.showModal();
  }
  loadCrmDetail();
}

function crmWorkspaceMatches(result, accountObjectId, tenantId) {
  const account = result?.account;
  const requiredFeatures = ["crm_erp.crm.accounts", "crm_erp.crm.contacts", "crm_erp.crm.activities"];
  if (
    result?.tenant_id !== tenantId || result.schema_version !== "crm_account_workspace.v1" ||
    result.module_id !== "crm_erp" || result.result_contract !== "metadata_only_account_workspace" ||
    result.content_included !== false || result.access_checked !== true ||
    !Array.isArray(result.required_feature_ids) || result.required_feature_ids.length !== requiredFeatures.length ||
    !requiredFeatures.every((feature) => result.required_feature_ids.includes(feature)) ||
    account?.object_id !== accountObjectId || account.object_type !== "crm.account" ||
    account.access_checked !== true || typeof account.display_name !== "string" ||
    !Array.isArray(result.contacts) || !Array.isArray(result.activities)
  ) {
    return false;
  }
  const contactIds = new Set(result.contacts.map((contact) => contact?.object_id));
  return result.contacts.every((contact) =>
    contact?.object_type === "crm.contact" && typeof contact.object_id === "string" &&
    typeof contact.display_name === "string" && contact.account_object_id === accountObjectId &&
    contact.access_checked === true && contact.linked_account_access_checked === true,
  ) && result.activities.every((activity) =>
    activity?.object_type === "crm.activity" && typeof activity.object_id === "string" &&
    typeof activity.subject === "string" && activity.access_checked === true &&
    activity.linked_object_access_checked === true &&
    (activity.account_object_id === accountObjectId ||
      (activity.account_object_id === null && contactIds.has(activity.contact_object_id))),
  );
}

async function loadCrmDetail() {
  const detail = state.crmDetail;
  if (!detail || !dialogs.crmDetail.open) {
    return;
  }
  const context = readContext();
  if (detail.context !== JSON.stringify(context)) {
    closeCrmDetail();
    return;
  }
  const accountObjectId = detail.accountObjectId;
  const requestNumber = ++detail.requestNumber;
  const isCurrent = () => state.crmDetail === detail && dialogs.crmDetail.open &&
    detail.context === JSON.stringify(readContext()) && detail.accountObjectId === accountObjectId &&
    detail.requestNumber === requestNumber;
  clearCrmDetailContent();
  elements.crmDetailStatus.textContent = "Kontodetails werden geladen ...";
  elements.crmDetailRefresh.textContent = "Erneut laden";
  elements.crmDetailRefresh.disabled = true;
  dialogs.crmDetail.setAttribute("aria-busy", "true");
  try {
    const result = await apiRequest(`/v1/crm/accounts/${encodeURIComponent(accountObjectId)}/workspace`, {
      cache: "no-store",
    });
    if (!isCurrent()) {
      return;
    }
    if (!crmWorkspaceMatches(result, accountObjectId, context.tenantId)) {
      throw new ApiError("Unvollstaendige Kontodetails", 502);
    }
    renderCrmDetail(result);
    elements.crmDetailStatus.textContent = "";
    elements.crmDetailRefresh.textContent = "Aktualisieren";
  } catch (error) {
    if (!isCurrent()) {
      return;
    }
    clearCrmDetailContent();
    const denied = error instanceof ApiError && [401, 403, 404, 423].includes(error.status);
    elements.crmDetailStatus.textContent = denied
      ? "Die Kontodetails sind nicht verfuegbar oder nicht freigegeben."
      : "Die Kontodetails konnten nicht geladen werden. Bitte versuchen Sie es erneut.";
    elements.crmDetailStatus.classList.add("error");
  } finally {
    if (isCurrent()) {
      elements.crmDetailRefresh.disabled = false;
      dialogs.crmDetail.removeAttribute("aria-busy");
    }
  }
}

function appendCrmDetailFields(container, fieldsToShow) {
  fieldsToShow.forEach(([label, value]) => {
    const term = document.createElement("dt");
    const description = document.createElement("dd");
    term.textContent = label;
    description.textContent = value || "Nicht angegeben";
    container.append(term, description);
  });
}

function crmDetailCard(title, testId, fieldsToShow) {
  const card = document.createElement("article");
  card.className = "crm-detail-card";
  card.dataset.testid = testId;
  const heading = document.createElement("h4");
  heading.textContent = title;
  const fieldsToRender = document.createElement("dl");
  fieldsToRender.className = "crm-detail-fields";
  appendCrmDetailFields(fieldsToRender, fieldsToShow);
  card.append(heading, fieldsToRender);
  return card;
}

function renderCrmDetail(result) {
  const account = result.account;
  const statusLabel = (status) => ({ active: "Aktiv", planned: "Geplant", done: "Erledigt" }[status] ||
    statusLabels[status] || humanize(status));
  const dateLabel = (value) => {
    const date = new Date(value || "");
    return Number.isNaN(date.getTime()) ? "Nicht angegeben" :
      new Intl.DateTimeFormat("de-DE", { dateStyle: "medium", timeStyle: "short" }).format(date);
  };
  elements.crmDetailTitle.textContent = account.display_name;
  appendCrmDetailFields(elements.crmDetailAccount, [
    ["Kontonummer", account.account_number],
    ["Art", account.account_kind === "organization" ? "Organisation" : humanize(account.account_kind)],
    ["Status", statusLabel(account.status)],
    ["Verantwortlich", account.owner_principal_id],
    ["Geaendert", dateLabel(account.updated_at_utc)],
  ]);
  result.contacts.forEach((contact) => {
    elements.crmDetailContacts.append(crmDetailCard(contact.display_name, "crm-detail-contact", [
      ["Rolle", contact.role_label],
      ["E-Mail", contact.primary_email],
      ["Telefon", contact.primary_phone],
      ["Kontaktnummer", contact.contact_number],
      ["Status", statusLabel(contact.status)],
    ]));
  });
  result.activities.forEach((activity) => {
    const contact = result.contacts.find((candidate) => candidate.object_id === activity.contact_object_id);
    const activityType = {
      task: "Aufgabe", call: "Anruf", meeting: "Termin", email: "E-Mail", follow_up: "Nachverfolgung",
    }[activity.activity_type] || humanize(activity.activity_type);
    const activityFields = [
      ["Art", activityType],
      ["Status", statusLabel(activity.status)],
      ["Faellig", dateLabel(activity.due_at_utc)],
      ["Verantwortlich", activity.owner_principal_id],
    ];
    if (contact) {
      activityFields.push(["Kontakt", contact.display_name]);
    }
    if (activity.completed_at_utc) {
      activityFields.push(["Erledigt", dateLabel(activity.completed_at_utc)]);
    }
    elements.crmDetailActivities.append(crmDetailCard(activity.subject, "crm-detail-activity", activityFields));
  });
  [
    [elements.crmDetailContacts, result.contacts, "Keine freigegebenen Kontakte zu diesem Konto."],
    [elements.crmDetailActivities, result.activities, "Keine freigegebenen Aktivitaeten zu diesem Konto."],
  ].forEach(([container, items, message]) => {
    if (!items.length) {
      const empty = document.createElement("p");
      empty.className = "crm-detail-empty";
      empty.textContent = message;
      container.append(empty);
    }
  });
  elements.crmDetailContent.hidden = false;
}

function clearKnowledgeReaderContent() {
  elements.knowledgeReaderTitle.textContent = "Artikel lesen";
  elements.knowledgeReaderBody.textContent = "";
  elements.knowledgeReaderBody.hidden = true;
  elements.knowledgeReaderBody.scrollTop = 0;
  elements.knowledgeReaderMeta.hidden = true;
  elements.knowledgeReaderVersion.textContent = "";
  elements.knowledgeReaderUpdated.textContent = "";
  elements.knowledgeReaderUpdated.removeAttribute("datetime");
  elements.knowledgeReaderMessage.textContent = "";
  elements.knowledgeReaderMessage.classList.remove("error");
}

function closeKnowledgeReader() {
  state.knowledgeReader = null;
  clearKnowledgeReaderContent();
  dialogs.knowledgeReader.removeAttribute("aria-busy");
  dialogs.knowledgeReader.close();
}

function openKnowledgeReader(articleObjectId) {
  if (!resourceItems("knowledge").some((article) => article.object_id === articleObjectId)) {
    return;
  }
  state.knowledgeReader = {
    articleObjectId,
    context: JSON.stringify(readContext()),
    requestNumber: 0,
  };
  clearKnowledgeReaderContent();
  if (!dialogs.knowledgeReader.open) {
    dialogs.knowledgeReader.showModal();
  }
  loadKnowledgeReader();
}

async function loadKnowledgeReader() {
  const reader = state.knowledgeReader;
  if (!reader || !dialogs.knowledgeReader.open) {
    return;
  }
  if (reader.context !== JSON.stringify(readContext())) {
    closeKnowledgeReader();
    return;
  }
  const articleObjectId = reader.articleObjectId;
  const requestNumber = ++reader.requestNumber;
  const isCurrent = () => state.knowledgeReader === reader && dialogs.knowledgeReader.open &&
    reader.context === JSON.stringify(readContext()) && reader.articleObjectId === articleObjectId &&
    reader.requestNumber === requestNumber;
  clearKnowledgeReaderContent();
  elements.knowledgeReaderMessage.textContent = "Artikel wird geladen ...";
  elements.knowledgeReaderRefresh.textContent = "Erneut laden";
  elements.knowledgeReaderRefresh.disabled = true;
  dialogs.knowledgeReader.setAttribute("aria-busy", "true");
  try {
    const result = await apiRequest(`/v1/kb/articles/${encodeURIComponent(articleObjectId)}/content`, {
      cache: "no-store",
    });
    if (!isCurrent()) {
      return;
    }
    const article = result.article;
    if (
      result.tenant_id !== readContext().tenantId || article?.object_id !== articleObjectId ||
      typeof article.title !== "string" || !article.current_version_object_id || !article.current_version_label ||
      typeof result.body !== "string" || result.body.length > 200000 ||
      result.rag_indexing_allowed !== false || result.search_indexing_allowed !== false
    ) {
      throw new ApiError("Unvollstaendige Artikelantwort", 502);
    }
    elements.knowledgeReaderTitle.textContent = article.title;
    elements.knowledgeReaderVersion.textContent = `${article.current_version_label} · ${article.current_version_object_id}`;
    const updated = new Date(article.updated_at_utc);
    if (!Number.isNaN(updated.getTime())) {
      elements.knowledgeReaderUpdated.dateTime = updated.toISOString();
      elements.knowledgeReaderUpdated.textContent = new Intl.DateTimeFormat("de-DE", {
        dateStyle: "medium", timeStyle: "short",
      }).format(updated);
    } else {
      elements.knowledgeReaderUpdated.textContent = "Nicht angegeben";
    }
    elements.knowledgeReaderMeta.hidden = false;
    elements.knowledgeReaderBody.textContent = result.body;
    elements.knowledgeReaderBody.hidden = false;
    elements.knowledgeReaderMessage.textContent = "";
    elements.knowledgeReaderRefresh.textContent = "Aktualisieren";
  } catch (error) {
    if (!isCurrent()) {
      return;
    }
    const denied = error instanceof ApiError && [401, 403, 404, 423].includes(error.status);
    elements.knowledgeReaderMessage.textContent = denied
      ? "Dieser Artikel ist nicht verfuegbar oder nicht mehr freigegeben."
      : "Der Artikel konnte nicht geladen werden. Bitte versuchen Sie es erneut.";
    elements.knowledgeReaderMessage.classList.add("error");
  } finally {
    if (isCurrent()) {
      elements.knowledgeReaderRefresh.disabled = false;
      dialogs.knowledgeReader.removeAttribute("aria-busy");
    }
  }
}

function knowledgeSessionIsCurrent(editor) {
  return state.knowledgeEditor === editor && dialogs.knowledge.open &&
    editor.context === JSON.stringify(readContext());
}

function renderKnowledgeEditor() {
  const editor = state.knowledgeEditor;
  if (!editor) {
    return;
  }
  const locked = ["loading", "unavailable", "saved", "uncertain"].includes(editor.stage);
  setFormBusy(forms.knowledge, editor.busy);
  forms.knowledge.elements.title.disabled = editor.busy || locked;
  forms.knowledge.elements.content_text.disabled = editor.busy || locked;
  elements.knowledgePreview.hidden = editor.stage !== "draft";
  elements.knowledgeApprove.hidden = editor.stage !== "preview";
  elements.knowledgeConfirmation.hidden = editor.stage !== "approved";
  elements.knowledgeExecute.hidden = editor.stage !== "approved";
  elements.knowledgeExecute.disabled = editor.busy || !elements.knowledgeConfirm.checked;
  elements.knowledgeEvidence.hidden = !["preview", "approved", "saved"].includes(editor.stage);
  forms.knowledge.querySelectorAll("[data-knowledge-step]").forEach((step) => {
    step.classList.toggle("active", step.dataset.knowledgeStep === editor.stage);
  });
  if (editor.stage === "preview" || editor.stage === "approved") {
    const command = editor.prepared.write_command;
    elements.knowledgeEvidence.innerHTML = `
      <strong>${editor.stage === "approved" ? "Aenderung freigegeben" : "Vorschau geprueft"}</strong>
      <p>${editor.operation === "create" ? "Neuer interner Artikel" : `Bearbeitung ab ${escapeHtml(editor.versionLabel)}`} → ${escapeHtml(command.proposed_version_label)}</p>
      <p>${editor.stage === "approved" ? "Quelle, Freigabe und Wiederherstellungsnachweis sind geprueft. Die abschliessende Bestaetigung steht aus." : "Titel und Inhalt sind an diese Vorschau gebunden. Bitte pruefen und die Aenderung freigeben."}</p>
      <p>Der Artikel ist noch nicht gespeichert. RAG und Suche bleiben ausgeschaltet.</p>
    `;
  }
}

async function openKnowledgeEditor(articleObjectId = null) {
  if (!state.resources.knowledge.canWrite || state.knowledgeEditor?.busy) {
    return;
  }
  forms.knowledge.reset();
  clearFormMessage(forms.knowledge);
  elements.knowledgeEvidence.replaceChildren();
  const editor = {
    operation: articleObjectId ? "edit" : "create",
    articleObjectId,
    expectedVersion: null,
    versionLabel: "",
    context: JSON.stringify(readContext()),
    stage: articleObjectId ? "loading" : "draft",
    busy: Boolean(articleObjectId),
  };
  state.knowledgeEditor = editor;
  document.querySelector("#knowledge-dialog-title").textContent = articleObjectId ? "Artikel bearbeiten" : "Neuer Artikel";
  elements.knowledgeVersion.textContent = articleObjectId ? "Autorisierte aktuelle Version wird geladen ..." : "Die Artikelkennung wird beim Pruefen vergeben.";
  renderKnowledgeEditor();
  dialogs.knowledge.showModal();
  if (!articleObjectId) {
    return;
  }
  try {
    const result = await apiRequest(`/v1/admin/kb/articles/${encodeURIComponent(articleObjectId)}/edit-content`);
    if (!knowledgeSessionIsCurrent(editor)) {
      return;
    }
    if (!result.article?.current_version_object_id || typeof result.body !== "string") {
      throw new ApiError("Unvollstaendige Artikelversion", 502);
    }
    editor.expectedVersion = result.article.current_version_object_id;
    editor.versionLabel = result.article.current_version_label;
    forms.knowledge.elements.title.value = result.article.title;
    forms.knowledge.elements.content_text.value = result.body;
    elements.knowledgeVersion.textContent = `Geladene Version: ${editor.versionLabel}. Beim Speichern wird diese Version erneut geprueft.`;
    editor.stage = "draft";
  } catch (error) {
    if (knowledgeSessionIsCurrent(editor)) {
      editor.stage = "unavailable";
      setFormMessage(forms.knowledge, knowledgeErrorMessage(error));
    }
  } finally {
    if (knowledgeSessionIsCurrent(editor)) {
      editor.busy = false;
      renderKnowledgeEditor();
    }
  }
}

function invalidateKnowledgePreview() {
  const editor = state.knowledgeEditor;
  if (!editor || editor.busy || ["conflict", "uncertain", "saved"].includes(editor.stage)) {
    return;
  }
  editor.stage = "draft";
  editor.prepared = null;
  editor.dryRun = null;
  editor.approval = null;
  editor.refresh = null;
  editor.guard = null;
  elements.knowledgeConfirm.checked = false;
  clearFormMessage(forms.knowledge);
  renderKnowledgeEditor();
}

function knowledgeErrorMessage(error) {
  if (error instanceof ApiError && (error.status === 409 || /current.version|version.mismatch|stale|conflict/i.test(error.message))) {
    return "Versionskonflikt: Der Artikel oder seine Nachweise wurden inzwischen geaendert. Ihr Entwurf bleibt hier erhalten. Schliessen Sie nach dem Sichern Ihres Entwurfs diesen Dialog und laden Sie den Artikel erneut; es wurde nichts ueberschrieben.";
  }
  if (error instanceof ApiError && [401, 403, 404, 423].includes(error.status)) {
    return "Wissensartikel gesperrt: Rolle, Zugriffsrechte, Modul oder Schreibfunktion erlauben diese Aktion derzeit nicht. Ihr Entwurf bleibt hier erhalten.";
  }
  if (error instanceof ApiError && [400, 422].includes(error.status)) {
    return "Die Artikelangaben oder die gebundene Freigabe sind ungueltig. Bitte pruefen Sie Titel und Inhalt und erstellen Sie eine neue Vorschau.";
  }
  return "Die Knowledge Base ist derzeit nicht verfuegbar. Ihr Entwurf bleibt hier erhalten. Bitte versuchen Sie es spaeter erneut.";
}

function handleKnowledgeFailure(editor, error, duringExecution = false) {
  if (!knowledgeSessionIsCurrent(editor)) {
    return;
  }
  const conflict = error instanceof ApiError && (error.status === 409 || /current.version|version.mismatch|stale|conflict/i.test(error.message));
  const uncertain = duringExecution && (!(error instanceof ApiError) || error.status < 400 || error.status >= 500);
  editor.stage = conflict ? "conflict" : uncertain ? "uncertain" : "draft";
  elements.knowledgeConfirm.checked = false;
  setFormMessage(forms.knowledge, uncertain
    ? "Speicherung konnte nicht bestaetigt werden. Ihr Entwurf bleibt hier erhalten. Aktualisieren Sie die Artikelliste und laden Sie den Artikel erneut, bevor Sie eine weitere Speicherung starten."
    : knowledgeErrorMessage(error));
}

async function knowledgePost(path, payload, editor) {
  if (!knowledgeSessionIsCurrent(editor)) {
    throw new ApiError("Kontext wurde geaendert", 403);
  }
  return apiRequest(`/v1/admin/kb/articles/${path}`, { method: "POST", body: JSON.stringify(payload) });
}

async function previewKnowledge(event) {
  event.preventDefault();
  const editor = state.knowledgeEditor;
  if (!editor || editor.busy || editor.stage !== "draft" || !forms.knowledge.reportValidity()) {
    return;
  }
  const payload = {
    operation: editor.operation,
    title: forms.knowledge.elements.title.value.trim(),
    body: forms.knowledge.elements.content_text.value,
  };
  if (editor.operation === "edit") {
    payload.article_object_id = editor.articleObjectId;
    payload.expected_current_version_object_id = editor.expectedVersion;
  }
  editor.busy = true;
  clearFormMessage(forms.knowledge);
  renderKnowledgeEditor();
  try {
    const prepared = await knowledgePost("prepare-write", payload, editor);
    if (!prepared.write_command || !prepared.proposed_source_record || prepared.rag_indexing_allowed !== false || prepared.search_indexing_allowed !== false) {
      throw new ApiError("Unvollstaendige Schreibvorschau", 502);
    }
    const dryRun = await knowledgePost("write-dry-run", prepared.write_command, editor);
    if (!knowledgeSessionIsCurrent(editor)) {
      return;
    }
    editor.prepared = prepared;
    editor.dryRun = dryRun;
    editor.stage = "preview";
  } catch (error) {
    handleKnowledgeFailure(editor, error);
  } finally {
    if (knowledgeSessionIsCurrent(editor)) {
      editor.busy = false;
      renderKnowledgeEditor();
    }
  }
}

async function approveKnowledge() {
  const editor = state.knowledgeEditor;
  if (!editor || editor.busy || editor.stage !== "preview") {
    return;
  }
  editor.busy = true;
  clearFormMessage(forms.knowledge);
  renderKnowledgeEditor();
  try {
    const approval = await knowledgePost("write-approvals/approve", {
      dry_run_write_approval_evidence_hash: editor.dryRun.write_approval_evidence_hash,
      approval_reference: `approval:${generatedId("work-kb")}`,
      reason: "User approved the reviewed Knowledge Base draft in Collabio Work",
    }, editor);
    const refresh = await knowledgePost("write-approvals/refresh-preview", {
      approved_write_approval_evidence_hash: approval.approved_write_approval_evidence_hash,
      preview_reference: `preview:${generatedId("work-kb")}`,
      reason: "Refresh source and restore evidence for the approved Work draft",
    }, editor);
    const guard = await knowledgePost("source-object-write-guard", {
      approved_write_approval_evidence_hash: approval.approved_write_approval_evidence_hash,
      proposed_source_record: editor.prepared.proposed_source_record,
    }, editor);
    if (!knowledgeSessionIsCurrent(editor)) {
      return;
    }
    if (!guard.allowed || !guard.source_authority_verified || guard.rag_indexing_allowed !== false) {
      throw new ApiError("Schreibpruefung hat die Aenderung gesperrt", 423);
    }
    editor.approval = approval;
    editor.refresh = refresh;
    editor.guard = guard;
    editor.stage = "approved";
  } catch (error) {
    handleKnowledgeFailure(editor, error);
  } finally {
    if (knowledgeSessionIsCurrent(editor)) {
      editor.busy = false;
      renderKnowledgeEditor();
    }
  }
}

async function executeKnowledge() {
  const editor = state.knowledgeEditor;
  if (!editor || editor.busy || editor.stage !== "approved" || !elements.knowledgeConfirm.checked) {
    return;
  }
  editor.busy = true;
  clearFormMessage(forms.knowledge);
  renderKnowledgeEditor();
  let executionSent = false;
  try {
    const command = {
      approved_write_approval_evidence_hash: editor.approval.approved_write_approval_evidence_hash,
      source_object_write_guard_decision: editor.guard,
      refresh_preview_command_hash: editor.refresh.preview_command_hash,
      projected_restore_evidence_preview_hash: editor.refresh.projected_restore_evidence_preview_hash,
      execution_reference: `execution:${generatedId("work-kb")}`,
      human_confirmation_reference: `human-confirmation:${generatedId("work-kb")}`,
      reason: "User explicitly confirmed saving the reviewed Knowledge Base article in Collabio Work",
    };
    const skeleton = await knowledgePost("write-approvals/execution-skeleton", command, editor);
    executionSent = true;
    const result = await knowledgePost("write-approvals/execute", {
      ...command,
      execution_skeleton_command_hash: skeleton.execution_command_hash,
      execution_plan_hash: skeleton.execution_plan_hash,
      proposed_source_record: editor.prepared.proposed_source_record,
    }, editor);
    if (!knowledgeSessionIsCurrent(editor)) {
      return;
    }
    if (!result.write_unit_of_work_committed || !result.source_object_write_receipt_persisted || !result.restore_evidence_refreshed || result.rag_indexing_allowed !== false || result.search_indexing_allowed !== false) {
      throw new ApiError("Unvollstaendige Speicherbestaetigung", 502);
    }
    editor.stage = "saved";
    const evidence = `<strong>Artikel gespeichert</strong><p>Inhalt, Freigabe, Schreibbeleg und Wiederherstellungsnachweis sind verbunden. RAG und Suche bleiben ausgeschaltet.</p><dl><dt>Artikel</dt><dd>${escapeHtml(result.article_object_id)}</dd><dt>Version</dt><dd>${escapeHtml(result.current_source_version_id)}</dd><dt>Auditbeleg</dt><dd>${escapeHtml(result.audit_event_id)}</dd></dl>`;
    elements.knowledgeEvidence.innerHTML = evidence;
    elements.knowledgeResult.innerHTML = evidence;
    elements.knowledgeResult.hidden = false;
    setFormMessage(forms.knowledge, "Artikel gespeichert. Sie koennen den Dialog schliessen.", true);
    rememberReadableObjectIds([result.article_object_id, result.current_version_object_id]);
    editor.context = JSON.stringify(readContext());
    await loadResource("knowledge");
    renderAll();
  } catch (error) {
    handleKnowledgeFailure(editor, error, executionSent);
  } finally {
    if (knowledgeSessionIsCurrent(editor)) {
      editor.busy = false;
      renderKnowledgeEditor();
    }
  }
}

async function submitTask(event) {
  event.preventDefault();
  clearFormMessage(forms.task);
  const values = new FormData(forms.task);
  const taskId = generatedId("task");
  const activityId = generatedId("task-activity");
  const mutationId = generatedId("work-task");
  const dueValue = optionalValue(values.get("due_at_utc"));
  const payload = {
    mutation_reference: `request:${mutationId}`,
    task_object_id: taskId,
    task_number: shortNumber("TASK"),
    title: String(values.get("title") || "").trim(),
    priority: String(values.get("priority") || "normal"),
    assigned_principal_id: optionalValue(values.get("assigned_principal_id")),
    due_at_utc: dueValue ? new Date(dueValue).toISOString() : null,
    activity_object_id: activityId,
    activity_number: shortNumber("TASK-ACT"),
    activity_summary: "Task created in Collabio Work",
    source_system: "native",
  };
  setFormBusy(forms.task, true);
  try {
    const body = await apiRequest("/v1/tasks/items", { method: "POST", body: JSON.stringify(payload) });
    rememberReadableObjectIds([body.task?.object_id, body.activity?.object_id]);
    setFormMessage(forms.task, "Aufgabe angelegt.", true);
    await refreshAll();
    window.setTimeout(() => dialogs.task.close(), 350);
  } catch (error) {
    setFormMessage(forms.task, error instanceof Error ? error.message : "Aufgabe konnte nicht angelegt werden.");
  } finally {
    setFormBusy(forms.task, false);
  }
}

async function submitTime(event) {
  event.preventDefault();
  clearFormMessage(forms.time);
  const values = new FormData(forms.time);
  const started = new Date(String(values.get("started_at_utc") || ""));
  const ended = new Date(String(values.get("ended_at_utc") || ""));
  if (Number.isNaN(started.getTime()) || Number.isNaN(ended.getTime()) || ended <= started) {
    setFormMessage(forms.time, "Der Zeitraum ist ungueltig.");
    return;
  }
  const entryId = generatedId("time-entry");
  const approvalId = generatedId("time-approval");
  const payload = {
    mutation_reference: `request:${generatedId("work-time")}`,
    entry_object_id: entryId,
    entry_number: shortNumber("TIME"),
    worker_principal_id: optionalValue(values.get("worker_principal_id")),
    work_date: localDateKey(started),
    started_at_utc: started.toISOString(),
    ended_at_utc: ended.toISOString(),
    project_reference: optionalValue(values.get("project_reference")),
    cost_center_reference: optionalValue(values.get("cost_center_reference")),
    approval_object_id: approvalId,
    approval_number: shortNumber("TIME-APPROVAL"),
    source_system: "native",
  };
  setFormBusy(forms.time, true);
  try {
    const body = await apiRequest("/v1/time-tracking/entries", { method: "POST", body: JSON.stringify(payload) });
    rememberReadableObjectIds([body.entry?.object_id, body.approval?.object_id]);
    setFormMessage(forms.time, "Zeit gespeichert.", true);
    await refreshAll();
    window.setTimeout(() => dialogs.time.close(), 350);
  } catch (error) {
    setFormMessage(forms.time, error instanceof Error ? error.message : "Zeit konnte nicht gespeichert werden.");
  } finally {
    setFormBusy(forms.time, false);
  }
}

async function submitTicket(event) {
  event.preventDefault();
  clearFormMessage(forms.ticket);
  const values = new FormData(forms.ticket);
  const context = readContext();
  const ticketId = generatedId("ticket");
  const eventId = generatedId("ticket-event");
  const auditRef = `audit:work-ticket:${ticketId}`;
  const payload = {
    ticket_id: ticketId,
    ticket_number: shortNumber("TKT"),
    subject_redacted: String(values.get("subject_redacted") || "").trim(),
    priority: String(values.get("priority") || "normal"),
    owner_principal_id: optionalValue(values.get("owner_principal_id")),
    kms_key_ref: `kms:${context.tenantId}:tickets`,
    audit_chain_ref: auditRef,
    created_event_id: eventId,
    created_event_summary_redacted: String(values.get("event_summary_redacted") || "").trim(),
    occurred_at_utc: new Date().toISOString(),
    source_system: "native",
  };
  setFormBusy(forms.ticket, true);
  try {
    await apiRequest("/v1/tickets", { method: "POST", body: JSON.stringify(payload) });
    setFormMessage(forms.ticket, "Ticket angelegt.", true);
    await refreshAll();
    window.setTimeout(() => dialogs.ticket.close(), 350);
  } catch (error) {
    setFormMessage(forms.ticket, error instanceof Error ? error.message : "Ticket konnte nicht angelegt werden.");
  } finally {
    setFormBusy(forms.ticket, false);
  }
}

function openTaskAmendment(taskObjectId) {
  const task = resourceItems("tasks").find((item) => item.object_id === taskObjectId);
  if (!task) {
    return;
  }
  forms.taskAmendment.reset();
  clearFormMessage(forms.taskAmendment);
  forms.taskAmendment.elements.task_object_id.value = task.object_id;
  forms.taskAmendment.elements.expected_assigned_principal_id.value = task.assigned_principal_id;
  forms.taskAmendment.elements.expected_due_at_utc.value = task.due_at_utc || "";
  forms.taskAmendment.elements.target_assigned_principal_id.value = task.assigned_principal_id;
  forms.taskAmendment.elements.target_due_at_utc.value = task.due_at_utc
    ? toLocalInputValue(new Date(task.due_at_utc))
    : "";
  forms.taskAmendment.elements.activity_summary.value = `${task.task_number}: Zuweisung oder Termin aktualisiert`;
  document.querySelector("#task-amendment-title").textContent = task.task_number;
  dialogs.taskAmendment.showModal();
}

async function submitTaskAmendment(event) {
  event.preventDefault();
  clearFormMessage(forms.taskAmendment);
  const values = new FormData(forms.taskAmendment);
  const taskObjectId = String(values.get("task_object_id") || "");
  const expectedDue = optionalValue(values.get("expected_due_at_utc"));
  const targetDue = optionalValue(values.get("target_due_at_utc"));
  const targetAssignee = String(values.get("target_assigned_principal_id") || "").trim();
  if (!targetAssignee) {
    setFormMessage(forms.taskAmendment, "Bitte eine zustaendige Person angeben.");
    return;
  }
  if (!window.confirm("Zuweisung und Termin als unveraenderliche Aufgabenaenderung speichern?")) {
    return;
  }
  const activityId = generatedId("task-activity");
  const payload = {
    mutation_reference: `request:${generatedId("work-task-amendment")}`,
    amendment_object_id: generatedId("task-amendment"),
    activity_object_id: activityId,
    activity_number: shortNumber("TASK-ACT"),
    expected_assigned_principal_id: String(values.get("expected_assigned_principal_id") || ""),
    target_assigned_principal_id: targetAssignee,
    expected_due_at_utc: expectedDue,
    target_due_at_utc: targetDue ? new Date(targetDue).toISOString() : null,
    activity_summary: String(values.get("activity_summary") || "").trim(),
    source_system: "native",
  };
  setFormBusy(forms.taskAmendment, true);
  try {
    await apiRequest(`/v1/tasks/items/${encodeURIComponent(taskObjectId)}/amendments`, {
      method: "POST",
      body: JSON.stringify(payload),
    });
    rememberReadableObjectIds([activityId]);
    setFormMessage(forms.taskAmendment, "Aufgabe aktualisiert.", true);
    await refreshAll();
    window.setTimeout(() => dialogs.taskAmendment.close(), 350);
  } catch (error) {
    setFormMessage(
      forms.taskAmendment,
      error instanceof Error ? error.message : "Aufgabe konnte nicht aktualisiert werden.",
    );
  } finally {
    setFormBusy(forms.taskAmendment, false);
  }
}

function openTaskTransition(taskObjectId) {
  const task = resourceItems("tasks").find((item) => item.object_id === taskObjectId);
  if (!task) {
    return;
  }
  forms.taskTransition.reset();
  clearFormMessage(forms.taskTransition);
  forms.taskTransition.elements.task_object_id.value = task.object_id;
  forms.taskTransition.elements.expected_state.value = task.lifecycle_state;
  forms.taskTransition.elements.transition.innerHTML = (taskTransitions[task.lifecycle_state] || [])
    .map(
      (transition) =>
        `<option value="${escapeHtml(`${transition.target}|${transition.kind}`)}">${escapeHtml(statusLabels[transition.target] || humanize(transition.target))}</option>`,
    )
    .join("");
  forms.taskTransition.elements.activity_summary.value = `${task.task_number}: Status aktualisiert`;
  document.querySelector("#task-transition-title").textContent = task.task_number;
  dialogs.taskTransition.showModal();
}

async function submitTaskTransition(event) {
  event.preventDefault();
  clearFormMessage(forms.taskTransition);
  const values = new FormData(forms.taskTransition);
  const taskObjectId = String(values.get("task_object_id") || "");
  const expectedState = String(values.get("expected_state") || "");
  const [targetState, transitionKind] = String(values.get("transition") || "").split("|");
  if (!targetState || !transitionKind) {
    setFormMessage(forms.taskTransition, "Bitte einen Zielstatus waehlen.");
    return;
  }
  if (
    !window.confirm(
      `Aufgabenstatus von ${statusLabels[expectedState] || expectedState} auf ${statusLabels[targetState] || targetState} aendern?`,
    )
  ) {
    return;
  }
  const activityId = generatedId("task-activity");
  const payload = {
    mutation_reference: `request:${generatedId("work-task-transition")}`,
    transition_object_id: generatedId("task-transition"),
    activity_object_id: activityId,
    activity_number: shortNumber("TASK-ACT"),
    expected_state: expectedState,
    target_state: targetState,
    transition_kind: transitionKind,
    activity_summary: String(values.get("activity_summary") || "").trim(),
    source_system: "native",
  };
  setFormBusy(forms.taskTransition, true);
  try {
    await apiRequest(`/v1/tasks/items/${encodeURIComponent(taskObjectId)}/transitions`, {
      method: "POST",
      body: JSON.stringify(payload),
    });
    rememberReadableObjectIds([activityId]);
    setFormMessage(forms.taskTransition, "Aufgabenstatus aktualisiert.", true);
    await refreshAll();
    window.setTimeout(() => dialogs.taskTransition.close(), 350);
  } catch (error) {
    setFormMessage(
      forms.taskTransition,
      error instanceof Error ? error.message : "Aufgabenstatus konnte nicht aktualisiert werden.",
    );
  } finally {
    setFormBusy(forms.taskTransition, false);
  }
}

function openTimeApproval(approvalObjectId) {
  const approval = resourceItems("timeApprovals").find((item) => item.object_id === approvalObjectId);
  if (!approval) {
    return;
  }
  forms.timeApproval.reset();
  clearFormMessage(forms.timeApproval);
  forms.timeApproval.elements.approval_object_id.value = approval.object_id;
  forms.timeApproval.elements.expected_state.value = approval.approval_state;
  forms.timeApproval.elements.decision.innerHTML = (timeApprovalTransitions[approval.approval_state] || [])
    .map(
      (transition) =>
        `<option value="${escapeHtml(`${transition.target}|${transition.action}`)}">${escapeHtml(statusLabels[transition.target] || humanize(transition.target))}</option>`,
    )
    .join("");
  document.querySelector("#time-approval-title").textContent = approval.approval_number;
  dialogs.timeApproval.showModal();
}

function openTimeCorrection(entryObjectId) {
  const entry = resourceItems("timeEntries").find((item) => item.object_id === entryObjectId);
  const approval = resourceItems("timeApprovals").find((item) => item.entry_object_id === entryObjectId);
  if (!entry || !approval || approval.approval_state !== "correction_requested") {
    return;
  }
  forms.timeCorrection.reset();
  clearFormMessage(forms.timeCorrection);
  forms.timeCorrection.elements.entry_object_id.value = entry.object_id;
  forms.timeCorrection.elements.expected_revision_no.value = String(entry.revision_no || 0);
  forms.timeCorrection.elements.work_date.value = entry.work_date;
  forms.timeCorrection.elements.started_at_utc.value = toLocalInputValue(new Date(entry.started_at_utc));
  forms.timeCorrection.elements.ended_at_utc.value = toLocalInputValue(new Date(entry.ended_at_utc));
  forms.timeCorrection.elements.project_reference.value = entry.project_reference || "";
  forms.timeCorrection.elements.cost_center_reference.value = entry.cost_center_reference || "";
  document.querySelector("#time-correction-title").textContent = entry.entry_number;
  dialogs.timeCorrection.showModal();
}

async function submitTimeCorrection(event) {
  event.preventDefault();
  clearFormMessage(forms.timeCorrection);
  const values = new FormData(forms.timeCorrection);
  const entryObjectId = String(values.get("entry_object_id") || "");
  const started = new Date(String(values.get("started_at_utc") || ""));
  const ended = new Date(String(values.get("ended_at_utc") || ""));
  if (Number.isNaN(started.getTime()) || Number.isNaN(ended.getTime()) || ended <= started) {
    setFormMessage(forms.timeCorrection, "Der korrigierte Zeitraum ist ungueltig.");
    return;
  }
  const payload = {
    mutation_reference: `request:${generatedId("work-time-correction")}`,
    correction_object_id: generatedId("time-correction"),
    expected_revision_no: Number(values.get("expected_revision_no") || 0),
    expected_approval_state: "correction_requested",
    work_date: String(values.get("work_date") || ""),
    started_at_utc: started.toISOString(),
    ended_at_utc: ended.toISOString(),
    project_reference: optionalValue(values.get("project_reference")),
    cost_center_reference: optionalValue(values.get("cost_center_reference")),
    source_system: "native",
  };
  setFormBusy(forms.timeCorrection, true);
  try {
    await apiRequest(`/v1/time-tracking/entries/${encodeURIComponent(entryObjectId)}/corrections`, {
      method: "POST",
      body: JSON.stringify(payload),
    });
    setFormMessage(forms.timeCorrection, "Korrektur gespeichert. Der Eintrag kann erneut eingereicht werden.", true);
    await refreshAll();
    window.setTimeout(() => dialogs.timeCorrection.close(), 650);
  } catch (error) {
    setFormMessage(
      forms.timeCorrection,
      error instanceof Error ? error.message : "Zeiteintrag konnte nicht korrigiert werden.",
    );
  } finally {
    setFormBusy(forms.timeCorrection, false);
  }
}

async function submitTimeApproval(event) {
  event.preventDefault();
  clearFormMessage(forms.timeApproval);
  const values = new FormData(forms.timeApproval);
  const approvalObjectId = String(values.get("approval_object_id") || "");
  const expectedState = String(values.get("expected_state") || "");
  const [targetState, action] = String(values.get("decision") || "").split("|");
  if (!targetState || !action) {
    setFormMessage(forms.timeApproval, "Bitte eine Freigabeaktion waehlen.");
    return;
  }
  const isDecision = action !== "submit";
  const confirmationStatement = isDecision
    ? `I explicitly confirm time approval ${approvalObjectId} decision ${targetState}.`
    : null;
  if (
    isDecision &&
    !window.confirm(
      `Diese Entscheidung wird unveraenderlich protokolliert. Bestaetigen Sie exakt:\n\n${confirmationStatement}`,
    )
  ) {
    return;
  }
  const payload = {
    mutation_reference: `request:${generatedId("work-time-decision")}`,
    decision_object_id: generatedId("time-decision"),
    expected_state: expectedState,
    target_state: targetState,
    action,
    human_confirmation_statement: confirmationStatement,
    source_system: "native",
  };
  setFormBusy(forms.timeApproval, true);
  try {
    await apiRequest(`/v1/time-tracking/approvals/${encodeURIComponent(approvalObjectId)}/transitions`, {
      method: "POST",
      body: JSON.stringify(payload),
    });
    setFormMessage(forms.timeApproval, isDecision ? "Freigabe entschieden." : "Zeit eingereicht.", true);
    await refreshAll();
    window.setTimeout(() => dialogs.timeApproval.close(), 350);
  } catch (error) {
    setFormMessage(
      forms.timeApproval,
      error instanceof Error ? error.message : "Freigabeaktion konnte nicht abgeschlossen werden.",
    );
  } finally {
    setFormBusy(forms.timeApproval, false);
  }
}

function openTicketTransition(ticketId) {
  const ticket = resourceItems("tickets").find((item) => item.ticket_id === ticketId);
  if (!ticket) {
    return;
  }
  forms.ticketTransition.reset();
  clearFormMessage(forms.ticketTransition);
  forms.ticketTransition.elements.ticket_id.value = ticket.ticket_id;
  forms.ticketTransition.elements.expected_status.value = ticket.ticket_status;
  const select = forms.ticketTransition.elements.new_status;
  select.innerHTML = (ticketTransitions[ticket.ticket_status] || [])
    .map((status) => `<option value="${escapeHtml(status)}">${escapeHtml(statusLabels[status] || humanize(status))}</option>`)
    .join("");
  forms.ticketTransition.elements.event_summary_redacted.value = `${ticket.ticket_number}: Status aktualisiert`;
  document.querySelector("#ticket-transition-title").textContent = ticket.ticket_number;
  dialogs.ticketTransition.showModal();
}

async function submitTicketTransition(event) {
  event.preventDefault();
  clearFormMessage(forms.ticketTransition);
  const values = new FormData(forms.ticketTransition);
  const ticketId = String(values.get("ticket_id") || "");
  const expectedStatus = String(values.get("expected_status") || "");
  const newStatus = String(values.get("new_status") || "");
  if (!window.confirm(`Status von ${statusLabels[expectedStatus] || expectedStatus} auf ${statusLabels[newStatus] || newStatus} aendern?`)) {
    return;
  }
  const payload = {
    event_id: generatedId("ticket-event"),
    expected_status: expectedStatus,
    new_status: newStatus,
    event_summary_redacted: String(values.get("event_summary_redacted") || "").trim(),
    audit_chain_ref: `audit:work-ticket-transition:${ticketId}:${Date.now()}`,
    occurred_at_utc: new Date().toISOString(),
  };
  setFormBusy(forms.ticketTransition, true);
  try {
    await apiRequest(`/v1/tickets/${encodeURIComponent(ticketId)}/transitions`, {
      method: "POST",
      body: JSON.stringify(payload),
    });
    setFormMessage(forms.ticketTransition, "Status aktualisiert.", true);
    await refreshAll();
    window.setTimeout(() => dialogs.ticketTransition.close(), 350);
  } catch (error) {
    setFormMessage(
      forms.ticketTransition,
      error instanceof Error ? error.message : "Ticketstatus konnte nicht aktualisiert werden.",
    );
  } finally {
    setFormBusy(forms.ticketTransition, false);
  }
}

document.querySelectorAll("[data-view]").forEach((button) => {
  button.addEventListener("click", () => setView(button.dataset.view));
});

document.querySelectorAll("[data-open-dialog]").forEach((button) => {
  button.addEventListener("click", () => openDialog(document.querySelector(`#${button.dataset.openDialog}`)));
});

document.querySelectorAll("[data-close-dialog]").forEach((button) => {
  button.addEventListener("click", () => {
    const dialog = button.closest("dialog");
    if (dialog === dialogs.knowledgeReader) {
      closeKnowledgeReader();
    } else if (dialog === dialogs.crmDetail) {
      closeCrmDetail();
    } else {
      dialog?.close();
    }
  });
});

document.querySelectorAll(".editor-dialog").forEach((dialog) => {
  dialog.addEventListener("click", (event) => {
    if (event.target === dialog && !(dialog === dialogs.knowledge && state.knowledgeEditor?.busy)) {
      if (dialog === dialogs.knowledgeReader) {
        closeKnowledgeReader();
      } else if (dialog === dialogs.crmDetail) {
        closeCrmDetail();
      } else {
        dialog.close();
      }
    }
  });
});

document.querySelectorAll("[data-task-filter]").forEach((button) => {
  button.addEventListener("click", () => {
    state.taskFilter = button.dataset.taskFilter;
    document.querySelectorAll("[data-task-filter]").forEach((candidate) => {
      candidate.classList.toggle("active", candidate === button);
    });
    renderTasks();
  });
});

document.querySelectorAll("[data-ticket-filter]").forEach((button) => {
  button.addEventListener("click", () => {
    state.ticketFilter = button.dataset.ticketFilter;
    document.querySelectorAll("[data-ticket-filter]").forEach((candidate) => {
      candidate.classList.toggle("active", candidate === button);
    });
    renderTickets();
  });
});

elements.contextButton.addEventListener("click", () => {
  elements.contextPanel.hidden = !elements.contextPanel.hidden;
});

elements.contextForm.addEventListener("submit", (event) => {
  event.preventDefault();
  closeKnowledgeReader();
  closeCrmDetail();
  dialogs.knowledge.close();
  elements.knowledgeResult.hidden = true;
  elements.knowledgeResult.replaceChildren();
  persistContext();
  elements.contextPanel.hidden = true;
  refreshAll();
});

elements.refreshButton.addEventListener("click", refreshAll);
elements.globalFilter.addEventListener("input", () => {
  state.query = elements.globalFilter.value.trim().toLocaleLowerCase("de-DE");
  renderAll();
});
forms.task.addEventListener("submit", submitTask);
forms.taskAmendment.addEventListener("submit", submitTaskAmendment);
forms.taskTransition.addEventListener("submit", submitTaskTransition);
forms.time.addEventListener("submit", submitTime);
forms.timeCorrection.addEventListener("submit", submitTimeCorrection);
forms.timeApproval.addEventListener("submit", submitTimeApproval);
forms.ticket.addEventListener("submit", submitTicket);
forms.ticketTransition.addEventListener("submit", submitTicketTransition);
elements.knowledgeCreate.addEventListener("click", () => openKnowledgeEditor());
forms.knowledge.addEventListener("submit", previewKnowledge);
forms.knowledge.elements.title.addEventListener("input", invalidateKnowledgePreview);
forms.knowledge.elements.content_text.addEventListener("input", invalidateKnowledgePreview);
elements.knowledgeApprove.addEventListener("click", approveKnowledge);
elements.knowledgeExecute.addEventListener("click", executeKnowledge);
elements.knowledgeConfirm.addEventListener("change", renderKnowledgeEditor);
elements.knowledgeReaderRefresh.addEventListener("click", loadKnowledgeReader);
elements.crmDetailRefresh.addEventListener("click", loadCrmDetail);
elements.contextForm.addEventListener("input", () => {
  if (state.knowledgeReader && state.knowledgeReader.context !== JSON.stringify(readContext())) {
    closeKnowledgeReader();
  }
  if (state.crmDetail && state.crmDetail.context !== JSON.stringify(readContext())) {
    closeCrmDetail();
  }
});
dialogs.crmDetail.addEventListener("cancel", (event) => {
  event.preventDefault();
  closeCrmDetail();
});
dialogs.crmDetail.addEventListener("close", () => {
  if (!dialogs.crmDetail.open) {
    state.crmDetail = null;
    clearCrmDetailContent();
  }
});
dialogs.knowledgeReader.addEventListener("cancel", (event) => {
  event.preventDefault();
  closeKnowledgeReader();
});
dialogs.knowledgeReader.addEventListener("close", () => {
  if (!dialogs.knowledgeReader.open) {
    state.knowledgeReader = null;
    clearKnowledgeReaderContent();
  }
});
dialogs.knowledge.addEventListener("cancel", (event) => {
  if (state.knowledgeEditor?.busy) {
    event.preventDefault();
  }
});
dialogs.knowledge.addEventListener("close", () => {
  state.knowledgeEditor = null;
  forms.knowledge.reset();
  elements.knowledgeEvidence.replaceChildren();
});

restoreContext();
setView(window.location.hash.replace(/^#/, ""), false);
refreshAll();
