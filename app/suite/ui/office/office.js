import { Editor, Extension } from "@tiptap/core";
import StarterKit from "@tiptap/starter-kit";
import { Table, TableKit } from "@tiptap/extension-table";
import { Plugin, PluginKey } from "@tiptap/pm/state";
import { Decoration, DecorationSet } from "@tiptap/pm/view";

const $ = (id) => document.getElementById(id);
const storageKey = "collabio.workspace.context";
const state = {
  context: null, epoch: 0, listRequest: 0, documents: [], canCreate: false,
  session: null, editor: null, listLoading: false, discardResolve: null,
};
const searchKey = new PluginKey("officeSearch");
const search = { query: "", matches: [], index: -1 };
const allowedNodes = new Set([
  "doc", "paragraph", "heading", "text", "hardBreak", "bulletList", "orderedList", "listItem",
  "blockquote", "codeBlock", "horizontalRule", "table", "tableRow", "tableCell", "tableHeader",
]);
const allowedMarks = new Set(["bold", "italic", "strike", "code", "underline"]);
const commandNames = {
  bold: "toggleBold", italic: "toggleItalic", underline: "toggleUnderline", strike: "toggleStrike",
  code: "toggleCode", bulletList: "toggleBulletList", orderedList: "toggleOrderedList",
  blockquote: "toggleBlockquote", undo: "undo", redo: "redo",
};
const OfficeTable = Table.extend({
  renderHTML() { return ["table", { class: "office-table" }, ["tbody", 0]]; },
});

class ApiError extends Error {
  constructor(status) { super(`HTTP ${status}`); this.status = status; }
}

function contextFields() {
  return {
    tenantId: $("tenant-id").value.trim(), userId: $("user-id").value.trim(),
    roleIds: $("role-ids").value.trim(), readableObjectIds: $("readable-object-ids").value.trim(),
  };
}

function restoreContext() {
  let saved = {};
  try { saved = JSON.parse(localStorage.getItem(storageKey) || "{}") || {}; } catch { /* Context only. */ }
  const context = {
    tenantId: saved.tenantId || "tenant-demo", userId: saved.userId || "user-demo",
    roleIds: saved.roleIds || "tenant-admin", readableObjectIds: saved.readableObjectIds || "",
  };
  ["tenantId", "userId", "roleIds", "readableObjectIds"].forEach((key, index) => {
    $(["tenant-id", "user-id", "role-ids", "readable-object-ids"][index]).value = context[key];
  });
  state.context = context;
  $("tenant-label").textContent = context.tenantId;
}

async function api(path, { method = "GET", body } = {}, context = state.context) {
  const response = await fetch(path, {
    method, cache: "no-store",
    headers: {
      "X-Tenant-Id": context.tenantId, "X-User-Id": context.userId,
      "X-Role-Ids": context.roleIds, "X-Readable-Object-Ids": context.readableObjectIds,
      ...(body ? { "Content-Type": "application/json" } : {}),
    },
    ...(body ? { body: JSON.stringify(body) } : {}),
  });
  if (!response.ok) {
    const reader = response.body?.getReader();
    if (reader) {
      let receivedBytes = 0;
      try {
        while (true) {
          const { done, value } = await reader.read();
          if (done) break;
          receivedBytes += value.byteLength;
          if (receivedBytes > 65536) { await reader.cancel(); break; }
        }
      } catch { /* Preserve the safe HTTP status if the error body cannot be drained. */ }
      finally { reader.releaseLock(); }
    }
    throw new ApiError(response.status);
  }
  try { return await response.json(); } catch { throw new ApiError(502); }
}

function denied(error) { return error instanceof ApiError && [401, 403, 404, 423].includes(error.status); }
function sessionCurrent(session) { return state.session === session && session.epoch === state.epoch; }
function dateLabel(value) {
  const date = new Date(value || "");
  return Number.isNaN(date.getTime()) ? "Datum nicht verfügbar" :
    new Intl.DateTimeFormat("de-DE", { dateStyle: "medium", timeStyle: "short" }).format(date);
}
function node(tag, text, className) {
  const element = document.createElement(tag);
  if (text !== undefined) element.textContent = text;
  if (className) element.className = className;
  return element;
}
function notice(text = "", error = false) {
  $("document-notice").textContent = text;
  $("document-notice").hidden = !text;
  $("document-notice").classList.toggle("error", error);
}

function normalizedDocument(document) {
  let nodes = 0;
  let characters = 0;
  const walk = (value, depth = 0) => {
    if (!value || !allowedNodes.has(value.type) || ++nodes > 10000 || depth > 32) throw new Error("document-shape");
    const result = { type: value.type };
    if (value.type === "text") {
      if (typeof value.text !== "string") throw new Error("document-text");
      characters += value.text.length;
      if (characters > 100000) throw new Error("document-length");
      result.text = value.text;
    }
    if (value.type === "heading") {
      if (![1, 2, 3].includes(value.attrs?.level)) throw new Error("document-heading");
      result.attrs = { level: value.attrs.level };
    }
    if (value.type === "orderedList") {
      const start = value.attrs?.start ?? 1;
      if (!Number.isInteger(start) || start < 1 || start > 1000000) throw new Error("document-list");
      result.attrs = { start };
    }
    if (["tableCell", "tableHeader"].includes(value.type)) {
      if ((value.attrs?.colspan ?? 1) !== 1 || (value.attrs?.rowspan ?? 1) !== 1 || value.attrs?.colwidth != null) {
        throw new Error("document-table");
      }
      result.attrs = { colspan: 1, rowspan: 1 };
    }
    if (value.marks?.length) {
      if (value.type !== "text" || value.marks.some((mark) => !allowedMarks.has(mark.type))) throw new Error("document-marks");
      result.marks = value.marks.map((mark) => ({ type: mark.type }));
    }
    if (value.content) {
      if (!Array.isArray(value.content)) throw new Error("document-content");
      result.content = value.content.map((child) => walk(child, depth + 1));
    }
    return result;
  };
  if (document?.type !== "doc") throw new Error("document-root");
  return walk(document);
}

function draftSnapshot() {
  return { title: $("document-title").value.trim(), document: normalizedDocument(state.editor.getJSON()) };
}

function isDirty() {
  if (!state.session || !state.editor || state.session.historical || state.session.loading) return false;
  try { return JSON.stringify(draftSnapshot()) !== state.session.baseline; } catch { return true; }
}

function updateEditorState() {
  const session = state.session;
  const editor = state.editor;
  const editable = Boolean(session && editor && session.canWrite && !session.historical && !session.saving && !session.uncertain);
  if (editor && editor.isEditable !== editable) editor.setEditable(editable, false);
  $("document-title").disabled = !editable;
  $("document-save").disabled = !session || !editor || session.loading || session.saving || session.historical ||
    !session.canWrite || session.conflict || (!session.uncertain && !isDirty());
  $("document-save").textContent = session?.uncertain ? "Speicherung prüfen" : "Version speichern";
  $("document-close").disabled = Boolean(session?.saving);
  $("document-reload").disabled = Boolean(session?.saving || session?.loading || !session?.objectId);
  $("document-reload").textContent = session?.historical ? "Aktuelle Version" : "Neu laden";
  $("history-refresh").disabled = Boolean(!session?.objectId || session?.loading || session?.saving);
  document.querySelectorAll("[data-command]").forEach((button) => {
    const command = button.dataset.command;
    button.disabled = !editable || !editor.can()[commandNames[command]]();
    if (button.hasAttribute("aria-pressed")) button.setAttribute("aria-pressed", String(Boolean(editor?.isActive(command))));
  });
  $("text-style").disabled = !editable;
  $("insert-menu").disabled = !editable;
  $("insert-menu").querySelectorAll("optgroup option").forEach((option) => {
    option.disabled = !editable || !editor.isActive("table");
  });
  if (editor) {
    const level = [1, 2, 3].find((candidate) => editor.isActive("heading", { level: candidate }));
    $("text-style").value = level ? `heading-${level}` : "paragraph";
  }
  const status = $("document-status");
  status.className = "document-status";
  if (!session) return;
  if (session.loading) status.textContent = "Dokument wird geladen …";
  else if (session.saving) status.textContent = "Version wird gespeichert …";
  else if (session.uncertain) { status.textContent = "Speicherung noch nicht bestätigt"; status.classList.add("error"); }
  else if (session.conflict) { status.textContent = "Neuere Version vorhanden · Ihr Entwurf bleibt erhalten"; status.classList.add("error"); }
  else if (session.historical) status.textContent = "Frühere Version · Schreibgeschützt";
  else if (!session.canWrite) status.textContent = "Schreibgeschützt";
  else if (isDirty()) status.textContent = "Ungespeicherte Änderungen";
  else { status.textContent = `Gespeichert · ${dateLabel(session.version?.created_at_utc)}`; status.classList.add("saved"); }
}

const SearchHighlights = Extension.create({
  name: "officeSearch",
  addProseMirrorPlugins() {
    return [new Plugin({
      key: searchKey,
      props: {
        decorations(editorState) {
          return DecorationSet.create(editorState.doc, search.matches.filter((match) =>
            match.from >= 0 && match.to <= editorState.doc.content.size,
          ).map((match, index) =>
            Decoration.inline(match.from, match.to, { class: `search-match${index === search.index ? " current" : ""}` }),
          ));
        },
      },
    })];
  },
});

function rebuildSearch(scroll = false) {
  const editor = state.editor;
  search.query = $("find-query").value;
  search.matches = [];
  if (editor && search.query) {
    const query = search.query.toLocaleLowerCase("de-DE");
    editor.state.doc.descendants((block, position) => {
      if (!block.isTextblock) return;
      const text = block.textBetween(0, block.content.size, "", " ").toLocaleLowerCase("de-DE");
      let index = 0;
      while ((index = text.indexOf(query, index)) !== -1 && search.matches.length < 1000) {
        search.matches.push({ from: position + 1 + index, to: position + 1 + index + query.length });
        index += Math.max(query.length, 1);
      }
      return false;
    });
  }
  search.index = search.matches.length ? Math.min(Math.max(search.index, 0), search.matches.length - 1) : -1;
  $("find-count").textContent = search.matches.length ? `${search.index + 1} / ${search.matches.length}` : "0 Treffer";
  $("find-previous").disabled = !search.matches.length;
  $("find-next").disabled = !search.matches.length;
  if (editor) editor.view.dispatch(editor.state.tr.setMeta(searchKey, true));
  if (scroll && search.index >= 0) moveToMatch(0);
}

function moveToMatch(direction) {
  if (!state.editor || !search.matches.length) return;
  search.index = (search.index + direction + search.matches.length) % search.matches.length;
  const match = search.matches[search.index];
  state.editor.commands.setTextSelection({ from: match.from, to: match.to });
  state.editor.commands.scrollIntoView();
  $("find-count").textContent = `${search.index + 1} / ${search.matches.length}`;
  state.editor.view.dispatch(state.editor.state.tr.setMeta(searchKey, true));
}

function refreshDocumentTools() {
  const editor = state.editor;
  if (!editor) return;
  const words = editor.getText().trim().match(/\S+/gu)?.length || 0;
  $("word-count").textContent = `${words.toLocaleString("de-DE")} ${words === 1 ? "Wort" : "Wörter"}`;
  $("document-outline").replaceChildren();
  let headings = 0;
  editor.state.doc.descendants((entry, position) => {
    if (entry.type.name !== "heading") return;
    headings += 1;
    const button = node("button", entry.textContent || "Ohne Überschrift", `outline-entry level-${entry.attrs.level}`);
    button.type = "button";
    button.addEventListener("click", () => {
      editor.chain().focus().setTextSelection(position + 1).scrollIntoView().run();
      if (window.matchMedia("(max-width: 1000px)").matches) toggleInspector(false);
    });
    $("document-outline").append(button);
  });
  $("outline-empty").hidden = headings > 0;
  rebuildSearch();
  updateEditorState();
}

function contentChanged(session) {
  if (!sessionCurrent(session) || session.loading) return;
  session.revision += 1;
  session.attempt = null;
  $("save-dialog").close();
  $("save-confirm").checked = false;
  if (!session.conflict) notice();
  refreshDocumentTools();
}

function mountEditor(content, session) {
  const editorHost = document.createElement("div");
  const safeContent = normalizedDocument(content);
  search.matches = [];
  search.index = -1;
  const editor = new Editor({
    element: editorHost, injectCSS: false, content: { type: "doc", content: [{ type: "paragraph" }] },
    editable: false, enablePasteRules: false,
    extensions: [
      StarterKit.configure({ link: false, heading: { levels: [1, 2, 3] }, trailingNode: false }),
      TableKit.configure({ table: false }), OfficeTable.configure({ resizable: false }), SearchHighlights,
    ],
    editorProps: {
      attributes: { "aria-label": "Dokumentinhalt", role: "textbox", "aria-multiline": "true", spellcheck: "true" },
      handlePaste(view, event) {
        event.preventDefault();
        const text = event.clipboardData?.getData("text/plain") || "";
        if (text.length > 100000) { notice("Der eingefügte Text ist zu lang.", true); return true; }
        const paragraphs = text.replaceAll("\r", "").split("\n").map((line) => ({
          type: "paragraph", ...(line ? { content: [{ type: "text", text: line }] } : {}),
        }));
        state.editor?.commands.insertContent(paragraphs);
        return true;
      },
      handleDrop() { notice("Dateien werden hier nicht eingefügt. Text lässt sich über die Zwischenablage übernehmen."); return true; },
    },
    onUpdate: () => contentChanged(session),
    onSelectionUpdate: () => updateEditorState(),
  });
  try {
    editor.schema.nodeFromJSON(safeContent).check();
    editor.commands.setContent(safeContent, { emitUpdate: false, errorOnInvalidContent: true });
  } catch (error) { editor.destroy(); throw error; }
  state.editor?.destroy();
  $("office-editor").replaceChildren(editorHost);
  state.editor = editor;
}

function clearWorkspace() {
  state.session = null;
  state.editor?.destroy();
  state.editor = null;
  search.query = ""; search.matches = []; search.index = -1;
  $("office-editor").replaceChildren();
  $("document-title").value = "";
  $("document-history").replaceChildren();
  $("document-outline").replaceChildren();
  $("history-status").textContent = "";
  $("document-status").textContent = "";
  $("document-version").textContent = "";
  $("find-query").value = "";
  $("find-panel").hidden = true;
  $("find-toggle").setAttribute("aria-expanded", "false");
  $("document-workspace").hidden = true;
  $("office-welcome").hidden = false;
  $("save-dialog").close();
  $("save-confirm").checked = false;
  $("save-summary").textContent = "";
  $("save-message").textContent = "";
  notice();
}

function renderDocuments() {
  const query = $("documents-search").value.trim().toLocaleLowerCase("de-DE");
  const documents = state.documents.filter((document) => document.title.toLocaleLowerCase("de-DE").includes(query));
  $("documents-list").replaceChildren();
  documents.forEach((document) => {
    const button = node("button", undefined, "document-item");
    button.type = "button";
    button.dataset.documentId = document.object_id;
    button.setAttribute("aria-current", String(state.session?.objectId === document.object_id));
    const copy = node("div");
    copy.append(node("strong", document.title), node("small", dateLabel(document.updated_at_utc)));
    button.append(copy);
    button.addEventListener("click", () => openDocument(document.object_id));
    $("documents-list").append(button);
  });
  if (!documents.length && !state.listLoading && state.documents.length) $("documents-list").append(node("p", "Keine Dokumente für diese Suche.", "list-status"));
  $("document-new").disabled = !state.canCreate;
  $("welcome-new").disabled = !state.canCreate;
}

async function loadDocuments() {
  const epoch = state.epoch;
  const request = ++state.listRequest;
  const context = state.context;
  const current = () => state.epoch === epoch && state.listRequest === request;
  state.listLoading = true;
  $("documents-refresh").disabled = true;
  $("documents-status").classList.remove("error");
  $("documents-status").textContent = "Dokumente werden geladen …";
  try {
    const result = await api("/v1/office/documents", {}, context);
    if (!current()) return;
    if (result.tenant_id !== context.tenantId || !Array.isArray(result.documents) ||
      result.documents.some((entry) => typeof entry.object_id !== "string" || typeof entry.title !== "string")) throw new ApiError(502);
    state.documents = result.documents;
    state.canCreate = result.can_create === true;
    if (state.session?.objectId && !state.documents.some((entry) => entry.object_id === state.session.objectId)) clearWorkspace();
    if (state.session?.objectId) {
      state.session.canWrite = state.documents.find((entry) => entry.object_id === state.session.objectId)?.can_write === true;
      updateEditorState();
    }
    if (state.session && !state.session.objectId && !state.canCreate) clearWorkspace();
    $("documents-status").textContent = result.documents.length ? "" : "Noch keine freigegebenen Dokumente.";
  } catch (error) {
    if (!current()) return;
    state.documents = [];
    state.canCreate = false;
    if (denied(error)) clearWorkspace();
    $("documents-status").textContent = denied(error)
      ? "Dokumente sind nicht freigegeben."
      : "Dokumente sind gerade nicht erreichbar. Bitte die Liste erneut laden.";
    $("documents-status").classList.add("error");
  } finally {
    if (current()) {
      state.listLoading = false;
      $("documents-refresh").disabled = false;
      renderDocuments();
    }
  }
}

function confirmDiscard() {
  if (state.session?.saving) return Promise.resolve(false);
  if (!isDirty() && !state.session?.uncertain) return Promise.resolve(true);
  if (state.discardResolve) return Promise.resolve(false);
  $("discard-dialog").showModal();
  return new Promise((resolve) => { state.discardResolve = resolve; });
}

function settleDiscard(confirmed) {
  const resolve = state.discardResolve;
  state.discardResolve = null;
  $("discard-dialog").close();
  resolve?.(confirmed);
}

function freshSession(objectId = null) {
  return { epoch: state.epoch, objectId, revision: 0, historyRequest: 0, canWrite: false,
    loading: true, saving: false, historical: false, conflict: false, uncertain: false,
    version: null, metadata: null, baseline: "", attempt: null };
}

function contentMatches(result, objectId, versionId = null) {
  return result?.tenant_id === state.context.tenantId && result.document?.object_id === objectId &&
    typeof result.document.title === "string" && typeof result.version?.version_id === "string" &&
    (versionId ? result.version.version_id === versionId :
      result.is_current_version === true && result.version.version_id === result.document.current_version_id) &&
    typeof result.is_current_version === "boolean" && typeof result.can_write === "boolean" &&
    result.rag_indexing_allowed === false && result.search_indexing_allowed === false && result.content?.type === "doc";
}

function acceptContent(result, session) {
  mountEditor(result.content, session);
  session.historyRequest += 1;
  session.metadata = result.document;
  session.version = result.version;
  session.objectId = result.document.object_id;
  session.canWrite = result.can_write === true;
  session.historical = !result.is_current_version;
  session.conflict = false; session.uncertain = false; session.attempt = null;
  $("document-title").value = result.version.title || result.document.title;
  session.loading = false;
  session.baseline = JSON.stringify(draftSnapshot());
  $("document-mode").textContent = session.historical ? "Frühere Fassung" : "Collabio-Dokument";
  $("document-version").textContent = `${session.historical ? "Frühere Version" : "Aktuelle Version"} · ${result.version.version_id}`;
  $("document-version").title = result.version.version_id;
  refreshDocumentTools();
}

async function openDocument(objectId, versionId = null) {
  const epoch = state.epoch;
  if (!(await confirmDiscard()) || epoch !== state.epoch) return;
  clearWorkspace();
  const session = freshSession(objectId);
  state.session = session;
  $("document-workspace").hidden = false;
  $("office-welcome").hidden = true;
  $("office-shell").classList.remove("documents-open");
  $("documents-toggle").setAttribute("aria-expanded", "false");
  $("document-mode").textContent = "Dokument";
  updateEditorState();
  renderDocuments();
  try {
    const result = await api(`/v1/office/documents/${encodeURIComponent(objectId)}/content${versionId ? `?version_id=${encodeURIComponent(versionId)}` : ""}`);
    if (!sessionCurrent(session)) return;
    if (!contentMatches(result, objectId, versionId)) throw new ApiError(502);
    acceptContent(result, session);
    if ($("history-tab").getAttribute("aria-selected") === "true") loadHistory();
  } catch (error) {
    if (!sessionCurrent(session)) return;
    state.editor?.destroy(); state.editor = null; $("office-editor").replaceChildren();
    session.loading = false; session.canWrite = false;
    $("document-title").value = "";
    notice(denied(error) ? "Dieses Dokument ist nicht verfügbar oder nicht mehr freigegeben." :
      "Das Dokument konnte nicht geladen werden. Versuchen Sie es mit „Neu laden“ erneut.", true);
    updateEditorState();
  }
}

const paragraph = (text = "") => ({ type: "paragraph", ...(text ? { content: [{ type: "text", text }] } : {}) });
const heading = (text, level = 2) => ({ type: "heading", attrs: { level }, content: [{ type: "text", text }] });
function templateDocument(template) {
  if (template === "meeting") return { type: "doc", content: [
    heading("Besprechungsnotiz", 1), paragraph("Datum und Teilnehmende"), heading("Agenda"),
    { type: "bulletList", content: [{ type: "listItem", content: [paragraph("Thema der Besprechung")] }] },
    heading("Entscheidungen"), paragraph(), heading("Nächste Schritte"), paragraph(),
  ] };
  if (template === "brief") return { type: "doc", content: [
    heading("Projektbrief", 1), paragraph("Ein kurzer Überblick über das Vorhaben."), heading("Ziel"), paragraph(),
    heading("Rahmen und Beteiligte"), paragraph(), heading("Meilensteine"),
    { type: "orderedList", attrs: { start: 1 }, content: [{ type: "listItem", content: [paragraph("Erster Meilenstein")] }] },
    heading("Erfolgskriterien"), paragraph(),
  ] };
  return { type: "doc", content: [paragraph()] };
}

async function showNewDocument() {
  const epoch = state.epoch;
  if (!state.canCreate || !(await confirmDiscard()) || epoch !== state.epoch) return;
  $("new-document-form").reset();
  $("new-document-dialog").showModal();
  $("new-document-form").elements.title.select();
}

function beginDraft(event) {
  event.preventDefault();
  if (!state.canCreate || !$("new-document-form").reportValidity()) return;
  const form = $("new-document-form");
  const title = form.elements.title.value.trim();
  if (!title) return;
  clearWorkspace();
  const session = freshSession();
  session.canWrite = true;
  state.session = session;
  $("office-welcome").hidden = true;
  $("document-workspace").hidden = false;
  $("document-title").value = title;
  $("document-mode").textContent = "Neuer Entwurf";
  $("document-version").textContent = "Noch nicht gespeichert";
  $("history-status").textContent = "Mit dem ersten Speichern beginnt die Versionsgeschichte.";
  mountEditor(templateDocument(form.elements.template.value), session);
  session.loading = false;
  session.baseline = "";
  $("new-document-dialog").close();
  $("office-shell").classList.remove("documents-open");
  $("documents-toggle").setAttribute("aria-expanded", "false");
  refreshDocumentTools();
  renderDocuments();
  state.editor.commands.focus("end");
}

function mutationReference() {
  const bytes = crypto.getRandomValues(new Uint8Array(16));
  bytes[6] = (bytes[6] & 0x0f) | 0x40;
  bytes[8] = (bytes[8] & 0x3f) | 0x80;
  const hex = Array.from(bytes, (byte) => byte.toString(16).padStart(2, "0")).join("");
  return `${hex.slice(0, 8)}-${hex.slice(8, 12)}-${hex.slice(12, 16)}-${hex.slice(16, 20)}-${hex.slice(20)}`;
}

function showSave() {
  const session = state.session;
  if (!session || !state.editor || $("document-save").disabled) return;
  let snapshot;
  try { snapshot = draftSnapshot(); } catch { notice("Das Dokument überschreitet das unterstützte Format oder die Größenbegrenzung.", true); return; }
  if (!snapshot.title || snapshot.title.length > 200) { notice("Bitte geben Sie einen Titel mit 1 bis 200 Zeichen ein.", true); $("document-title").focus(); return; }
  if (!session.attempt) {
    session.attempt = {
      revision: session.revision,
      payload: { ...snapshot, mutation_reference: mutationReference(), human_confirmation: true,
        ...(session.objectId ? { expected_current_version_id: session.metadata.current_version_id } : {}) },
    };
  }
  $("save-summary").textContent = session.uncertain
    ? `Die Speicherung von „${snapshot.title}“ wird mit derselben Vorgangskennung erneut geprüft.`
    : `„${snapshot.title}“ wird ${session.objectId ? "als neue Version" : "als neues Dokument"} gespeichert.`;
  $("save-confirm").checked = false;
  $("save-submit").disabled = true;
  $("save-message").textContent = "";
  $("save-dialog").showModal();
}

async function saveDocument(event) {
  event.preventDefault();
  const session = state.session;
  if (!session || session.saving || !$("save-confirm").checked || !session.attempt ||
    session.attempt.revision !== session.revision || !sessionCurrent(session)) return;
  const attempt = session.attempt;
  session.saving = true;
  $("save-submit").disabled = true;
  $("save-dialog").querySelectorAll("button,input").forEach((control) => { control.disabled = true; });
  $("save-message").textContent = "Version wird gespeichert …";
  updateEditorState();
  try {
    const path = session.objectId ? `/v1/office/documents/${encodeURIComponent(session.objectId)}/versions` : "/v1/office/documents";
    const result = await api(path, { method: "POST", body: attempt.payload });
    if (!sessionCurrent(session)) return;
    const objectId = session.objectId || result.document?.object_id;
    if (typeof objectId !== "string" || !contentMatches(result, objectId, result.version?.version_id)) throw new ApiError(502);
    acceptContent(result, session);
    $("save-dialog").close();
    notice(result.replayed && !result.is_current_version
      ? "Diese Speicherung wurde bestätigt. Inzwischen gibt es eine neuere Version; öffnen Sie sie über „Aktuelle Version“."
      : "");
    await loadDocuments();
    if (sessionCurrent(session) && $("history-tab").getAttribute("aria-selected") === "true") loadHistory();
  } catch (error) {
    if (!sessionCurrent(session)) return;
    $("save-dialog").close();
    if (denied(error)) {
      clearWorkspace();
      $("documents-status").textContent = "Der Zugriff wurde nicht bestätigt. Bitte laden Sie Ihre Dokumente erneut.";
      $("documents-status").classList.add("error");
      state.canCreate = false;
      state.documents = [];
      renderDocuments();
      return;
    }
    if (error instanceof ApiError && error.status === 409) {
      session.conflict = true;
      session.uncertain = false;
      notice("Eine neuere Version ist vorhanden. Ihr Entwurf wurde nicht überschrieben. Mit „Neu laden“ können Sie die aktuelle Version öffnen; dabei werden Ihre ungespeicherten Änderungen verworfen.", true);
    } else if (error instanceof ApiError && [400, 413, 422].includes(error.status)) {
      session.attempt = null;
      notice("Das Dokument konnte nicht gespeichert werden. Prüfen Sie Titel, Dokumentgröße und Tabellenstruktur.", true);
    } else {
      session.uncertain = true;
      notice("Die Antwort auf die Speicherung ist ausgeblieben. „Speicherung prüfen“ wiederholt denselben Vorgang ohne eine zusätzliche Version anzulegen. Ihr Entwurf bleibt erhalten.", true);
    }
  } finally {
    $("save-dialog").querySelectorAll("button,input").forEach((control) => { control.disabled = false; });
    $("save-submit").disabled = true;
    if (sessionCurrent(session)) { session.saving = false; updateEditorState(); }
  }
}

async function loadHistory() {
  const session = state.session;
  if (!session?.objectId || session.loading) {
    $("history-status").textContent = "Mit dem ersten Speichern beginnt die Versionsgeschichte.";
    return;
  }
  const request = ++session.historyRequest;
  const current = () => sessionCurrent(session) && session.historyRequest === request;
  $("document-history").replaceChildren();
  $("history-status").textContent = "Versionen werden geladen …";
  $("history-refresh").disabled = true;
  try {
    const result = await api(`/v1/office/documents/${encodeURIComponent(session.objectId)}/versions`);
    if (!current()) return;
    if (result.tenant_id !== state.context.tenantId || result.object_id !== session.objectId || !Array.isArray(result.versions)) throw new ApiError(502);
    $("history-status").textContent = "Gespeicherte Versionen öffnen Sie schreibgeschützt.";
    result.versions.forEach((version) => {
      if (typeof version.version_id !== "string") throw new ApiError(502);
      const button = node("button", undefined, "version-entry");
      button.type = "button";
      button.dataset.versionId = version.version_id;
      button.setAttribute("aria-current", String(version.version_id === session.version?.version_id));
      button.append(node("strong", version.version_id === session.metadata.current_version_id ? "Aktuelle Version" : "Gespeicherte Version"),
        node("small", dateLabel(version.created_at_utc)), node("small", version.created_by));
      button.title = version.version_id;
      button.addEventListener("click", () => openDocument(session.objectId, version.version_id));
      $("document-history").append(button);
    });
  } catch (error) {
    if (!current()) return;
    $("document-history").replaceChildren();
    if (denied(error)) {
      clearWorkspace();
      $("documents-status").textContent = "Dieses Dokument ist nicht mehr freigegeben.";
      return;
    }
    $("history-status").textContent = "Versionen konnten nicht geladen werden. Bitte versuchen Sie es erneut.";
  } finally {
    if (current()) $("history-refresh").disabled = false;
  }
}

function toggleInspector(show) {
  $("office-shell").classList.toggle("inspector-hidden", !show);
  $("inspector-toggle").setAttribute("aria-expanded", String(show));
}

function selectInspector(name) {
  ["outline", "history"].forEach((candidate) => {
    const active = name === candidate;
    $(`${candidate}-tab`).setAttribute("aria-selected", String(active));
    $(`${candidate}-tab`).tabIndex = active ? 0 : -1;
    $(`${candidate}-panel`).hidden = !active;
  });
  if (name === "history") loadHistory();
}

function toggleFind(show) {
  $("find-panel").hidden = !show;
  $("find-toggle").setAttribute("aria-expanded", String(show));
  if (show) { $("find-query").focus(); $("find-query").select(); }
  else { $("find-query").value = ""; rebuildSearch(); state.editor?.commands.focus(); }
}

$("document-new").addEventListener("click", showNewDocument);
$("welcome-new").addEventListener("click", showNewDocument);
$("new-document-form").addEventListener("submit", beginDraft);
$("document-save").addEventListener("click", showSave);
$("save-form").addEventListener("submit", saveDocument);
$("save-confirm").addEventListener("change", () => { $("save-submit").disabled = !$("save-confirm").checked; });
$("document-title").addEventListener("input", () => { if (state.session) contentChanged(state.session); });
$("document-reload").addEventListener("click", () => { if (state.session?.objectId) openDocument(state.session.objectId); });
$("document-close").addEventListener("click", async () => { if (await confirmDiscard()) { clearWorkspace(); renderDocuments(); } });
$("documents-refresh").addEventListener("click", loadDocuments);
$("documents-search").addEventListener("input", renderDocuments);
$("history-refresh").addEventListener("click", loadHistory);
$("outline-tab").addEventListener("click", () => selectInspector("outline"));
$("history-tab").addEventListener("click", () => selectInspector("history"));
$("inspector-toggle").addEventListener("click", () => toggleInspector($("office-shell").classList.contains("inspector-hidden")));
$("documents-toggle").addEventListener("click", () => {
  const open = $("office-shell").classList.toggle("documents-open");
  $("documents-toggle").setAttribute("aria-expanded", String(open));
});
$("focus-toggle").addEventListener("click", () => {
  const active = $("office-shell").classList.toggle("focus-mode");
  $("focus-toggle").setAttribute("aria-pressed", String(active));
});
$("find-toggle").addEventListener("click", () => toggleFind($("find-panel").hidden));
$("find-close").addEventListener("click", () => toggleFind(false));
$("find-query").addEventListener("input", () => { search.index = 0; rebuildSearch(true); });
$("find-next").addEventListener("click", () => moveToMatch(1));
$("find-previous").addEventListener("click", () => moveToMatch(-1));
$("find-query").addEventListener("keydown", (event) => {
  if (event.key === "Enter") { event.preventDefault(); moveToMatch(event.shiftKey ? -1 : 1); }
  if (event.key === "Escape") { event.preventDefault(); toggleFind(false); }
});
document.querySelectorAll("[data-command]").forEach((button) => {
  button.addEventListener("click", () => { state.editor?.chain().focus()[commandNames[button.dataset.command]]().run(); updateEditorState(); });
});
$("text-style").addEventListener("change", () => {
  const value = $("text-style").value;
  if (value === "paragraph") state.editor?.chain().focus().setParagraph().run();
  else state.editor?.chain().focus().setHeading({ level: Number(value.split("-")[1]) }).run();
});
$("insert-menu").addEventListener("change", () => {
  const command = $("insert-menu").value;
  const editor = state.editor;
  if (editor && command) {
    if (command === "insertTable") editor.chain().focus().insertTable({ rows: 3, cols: 3, withHeaderRow: true }).run();
    else if (command === "horizontalRule") editor.chain().focus().setHorizontalRule().run();
    else if (command === "codeBlock") editor.chain().focus().toggleCodeBlock().run();
    else editor.chain().focus()[command]().run();
  }
  $("insert-menu").value = "";
});
document.querySelectorAll("[data-close-dialog]").forEach((button) => {
  button.addEventListener("click", () => { if (!state.session?.saving) button.closest("dialog").close(); });
});
$("save-dialog").addEventListener("cancel", (event) => { if (state.session?.saving) event.preventDefault(); });
$("discard-cancel").addEventListener("click", () => settleDiscard(false));
$("discard-confirm").addEventListener("click", () => settleDiscard(true));
$("discard-dialog").addEventListener("cancel", (event) => { event.preventDefault(); settleDiscard(false); });
document.querySelectorAll(".inspector-tabs [role=tab]").forEach((tab) => {
  tab.addEventListener("keydown", (event) => {
    if (!["ArrowLeft", "ArrowRight", "Home", "End"].includes(event.key)) return;
    event.preventDefault();
    const target = event.key === "Home" ? "outline" : event.key === "End" ? "history" :
      tab.id === "outline-tab" ? "history" : "outline";
    selectInspector(target); $(`${target}-tab`).focus();
  });
});
$("context-toggle").addEventListener("click", () => {
  $("context-panel").hidden = !$("context-panel").hidden;
  $("context-toggle").setAttribute("aria-expanded", String(!$("context-panel").hidden));
});
$("context-form").addEventListener("submit", async (event) => {
  event.preventDefault();
  const context = contextFields();
  if (!context.tenantId || !context.userId || !(await confirmDiscard())) return;
  state.epoch += 1;
  clearWorkspace();
  $("new-document-dialog").close();
  state.context = context;
  state.documents = []; state.canCreate = false;
  localStorage.setItem(storageKey, JSON.stringify(context));
  $("tenant-label").textContent = context.tenantId;
  $("context-panel").hidden = true;
  $("context-toggle").setAttribute("aria-expanded", "false");
  renderDocuments();
  loadDocuments();
});
document.addEventListener("keydown", (event) => {
  if (event.key === "Escape" && !document.querySelector("dialog[open]")) {
    $("office-shell").classList.remove("documents-open");
    $("documents-toggle").setAttribute("aria-expanded", "false");
  }
  if (!state.editor || document.querySelector("dialog[open]") || !(event.ctrlKey || event.metaKey)) return;
  if (event.key.toLowerCase() === "s") { event.preventDefault(); showSave(); }
  if (event.key.toLowerCase() === "f") { event.preventDefault(); toggleFind(true); }
});
window.addEventListener("beforeunload", (event) => {
  if (isDirty() || state.session?.saving || state.session?.uncertain) { event.preventDefault(); event.returnValue = ""; }
});

restoreContext();
toggleInspector(!window.matchMedia("(max-width: 1000px)").matches);
loadDocuments();
