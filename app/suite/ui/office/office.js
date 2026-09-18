import { Editor, Extension } from "@tiptap/core";
import StarterKit from "@tiptap/starter-kit";
import { Table, TableKit } from "@tiptap/extension-table";
import { Plugin, PluginKey, Selection } from "@tiptap/pm/state";
import { closeHistory } from "@tiptap/pm/history";
import { Decoration, DecorationSet } from "@tiptap/pm/view";
import {
  addRowBefore, addRowAfter, addColumnBefore, addColumnAfter, deleteRow, deleteColumn,
  deleteTable, goToNextCell, selectedRect, isInTable, CellSelection, TableMap,
} from "@tiptap/pm/tables";
import { compareOfficeDocuments, describeOfficeBlock } from "./office-comparison.mjs";
import { findDocumentMatches, replaceDocumentMatches, OfficeSearchLimitError } from "./office-search.mjs";

const $ = (id) => document.getElementById(id);
const storageKey = "collabio.workspace.context";
const state = {
  context: null, epoch: 0, listRequest: 0, documents: [], canCreate: false,
  session: null, editor: null, listLoading: false, discardResolve: null, compare: null, restore: null,
  tableAction: null,
};
const searchKey = new PluginKey("officeSearch");
const search = { query: "", matches: [], index: -1, windowStart: 0, notice: "" };
const searchHighlightLimit = 200;
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

async function api(path, { method = "GET", body, signal } = {}, context = state.context) {
  const response = await fetch(path, {
    method, cache: "no-store", signal,
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
      characters += Array.from(value.text).length;
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
      const types = value.marks.map((mark) => mark.type);
      if (value.type !== "text" || types.some((type) => !allowedMarks.has(type)) ||
          new Set(types).size !== types.length || (types.includes("code") && types.length > 1)) throw new Error("document-marks");
      result.marks = value.marks.map((mark) => ({ type: mark.type }));
    }
    if (value.content) {
      if (!Array.isArray(value.content)) throw new Error("document-content");
      result.content = value.content.map((child) => walk(child, depth + 1));
    }
    if (value.type === "table") {
      const rows = result.content || [];
      if (!rows.length || rows.length > 200 || rows.some((row) => row.type !== "tableRow" ||
          !row.content?.length || row.content.length > 20 || row.content.length !== rows[0].content.length)) {
        throw new Error("document-table");
      }
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
  const editable = Boolean(session && sessionCurrent(session) && editor && session.canWrite && !session.loading &&
    !session.historical && !session.saving && !session.uncertain && !session.restoring);
  if (editor && editor.isEditable !== editable) editor.setEditable(editable, false);
  $("document-title").disabled = !editable;
  $("document-save").disabled = !session || !editor || session.loading || session.saving || session.restoring || session.historical ||
    !session.canWrite || session.conflict || (!session.uncertain && !isDirty());
  $("document-save").textContent = session?.uncertain ? "Speicherung prüfen" : "Version speichern";
  $("document-close").disabled = Boolean(session?.saving);
  $("document-reload").disabled = Boolean(session?.saving || session?.loading || !session?.objectId);
  $("document-reload").textContent = session?.historical ? "Aktuelle Version" : "Neu laden";
  $("history-refresh").disabled = Boolean(!session?.objectId || session?.loading || session?.saving || session?.restoring);
  $("history-compare").disabled = Boolean(!session?.objectId || session?.loading || session?.saving || session?.restoring);
  $("historical-actions").hidden = !session?.historical || !listedWriteAccess(session?.objectId);
  $("document-restore").disabled = Boolean(session?.loading || session?.saving || session?.restoring);
  document.querySelectorAll("[data-command]").forEach((button) => {
    const command = button.dataset.command;
    button.disabled = !editable || !editor.can()[commandNames[command]]();
    if (button.hasAttribute("aria-pressed")) button.setAttribute("aria-pressed", String(Boolean(editor?.isActive(command))));
  });
  $("text-style").disabled = !editable;
  $("insert-menu").disabled = !editable;
  updateTableControls();
  if (editor) {
    const level = [1, 2, 3].find((candidate) => editor.isActive("heading", { level: candidate }));
    $("text-style").value = level ? `heading-${level}` : "paragraph";
  }
  updateSearchControls();
  const status = $("document-status");
  status.className = "document-status";
  if (!session) return;
  if (session.loading) status.textContent = "Dokument wird geladen …";
  else if (session.saving) status.textContent = "Version wird gespeichert …";
  else if (session.restoring) status.textContent = "Frühere Fassung wird geprüft …";
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
          return DecorationSet.create(editorState.doc, search.matches.slice(search.windowStart, search.windowStart + searchHighlightLimit).filter((match) =>
            match.from >= 0 && match.to <= editorState.doc.content.size,
          ).map((match, index) =>
            Decoration.inline(match.from, match.to, { class: `search-match${index + search.windowStart === search.index ? " current" : ""}` }),
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
    try {
      search.matches = findDocumentMatches(normalizedDocument(editor.getJSON()), search.query, {
        caseSensitive: $("find-case-sensitive").checked, wholeWord: $("find-whole-word").checked,
      });
    } catch { search.notice = "Die Suche überschreitet die unterstützte Dokumentgröße oder Struktur."; }
  }
  search.index = search.matches.length ? Math.min(Math.max(search.index, 0), search.matches.length - 1) : -1;
  updateSearchControls();
  if (editor) editor.view.dispatch(editor.state.tr.setMeta(searchKey, true));
  if (scroll && search.index >= 0) moveToMatch(0);
}

function replacementAllowed() {
  const session = state.session;
  return Boolean(session && sessionCurrent(session) && state.editor?.isEditable && session.canWrite &&
    !session.loading && !session.historical && !session.saving && !session.uncertain && !session.restoring);
}

function updateSearchControls() {
  search.windowStart = Math.max(0, Math.min(search.index - Math.floor(searchHighlightLimit / 2), search.matches.length - searchHighlightLimit));
  $("find-count").textContent = search.matches.length ? `${search.index + 1} / ${search.matches.length}` : "0 Treffer";
  $("find-previous").disabled = !search.matches.length;
  $("find-next").disabled = !search.matches.length;
  const allowed = replacementAllowed();
  $("replace-query").disabled = !allowed;
  $("replace-current").disabled = !allowed || !search.matches.length;
  $("replace-all").disabled = !allowed || !search.matches.length;
  $("find-highlight-note").hidden = search.matches.length <= searchHighlightLimit;
  $("find-highlight-note").textContent = search.matches.length > searchHighlightLimit
    ? `Markiert werden Treffer ${search.windowStart + 1}–${Math.min(search.windowStart + searchHighlightLimit, search.matches.length)} von ${search.matches.length}. Alle Treffer sind über die Suche erreichbar.` : "";
  const session = state.session;
  let message = search.notice;
  if (session?.loading) message = "Das Dokument wird geladen. Ersetzen ist noch nicht verfügbar.";
  else if (session?.saving) message = "Während der Speicherung ist Ersetzen nicht verfügbar.";
  else if (session?.restoring) message = "Während der Übernahme einer Fassung ist Ersetzen nicht verfügbar.";
  else if (session?.uncertain) message = "Prüfen Sie zuerst die noch nicht bestätigte Speicherung, bevor Sie Text ersetzen.";
  else if (session && !allowed) message = "Schreibgeschützt: Suchen ist möglich, Ersetzen nicht.";
  $("find-message").textContent = message;
}

function moveToMatch(direction) {
  if (!state.editor || !search.matches.length) return;
  search.index = (search.index + direction + search.matches.length) % search.matches.length;
  const match = search.matches[search.index];
  state.editor.commands.setTextSelection({ from: match.from, to: match.to });
  state.editor.commands.scrollIntoView();
  updateSearchControls();
  state.editor.view.dispatch(state.editor.state.tr.setMeta(searchKey, true));
}

function resetSearch() {
  search.query = ""; search.matches = []; search.index = -1; search.windowStart = 0; search.notice = "";
  $("find-query").value = ""; $("replace-query").value = "";
  $("find-case-sensitive").checked = false; $("find-whole-word").checked = false;
  $("find-message").textContent = ""; $("find-highlight-note").textContent = "";
  $("find-highlight-note").hidden = true;
  updateSearchControls();
}

function replaceMatches(all) {
  const editor = state.editor;
  const session = state.session;
  if (!replacementAllowed() || !search.query || !search.matches.length) return;
  const options = { caseSensitive: $("find-case-sensitive").checked, wholeWord: $("find-whole-word").checked };
  const replacement = $("replace-query").value;
  const initiatingControl = document.activeElement;
  let change;
  try {
    const documentContent = normalizedDocument(editor.getJSON());
    const matches = findDocumentMatches(documentContent, $("find-query").value, options);
    const index = Math.min(Math.max(search.index, 0), matches.length - 1);
    if (!matches.length) { rebuildSearch(); return; }
    const result = replaceDocumentMatches(documentContent, matches, replacement, all ? {} : { currentIndex: index });
    const nextDocument = editor.schema.nodeFromJSON(result.document);
    nextDocument.check();
    if (result.noOp || !result.changedCount || nextDocument.eq(editor.state.doc)) {
      search.notice = "Keine Änderung: Suchtext und Ersatz ergeben denselben Inhalt.";
      updateSearchControls();
      return;
    }
    if (!sessionCurrent(session) || !replacementAllowed()) return;
    const position = Math.min((all ? matches[0].from : matches[index].from) + replacement.length, nextDocument.content.size);
    const transaction = closeHistory(editor.state.tr).replaceWith(0, editor.state.doc.content.size, nextDocument.content);
    transaction.setSelection(Selection.near(transaction.doc.resolve(position)));
    change = { transaction, position, count: result.changedCount };
  } catch (error) {
    search.notice = error instanceof OfficeSearchLimitError
      ? "Die Ersetzung überschreitet die unterstützte Dokumentgröße oder Struktur. Ihr Entwurf bleibt unverändert."
      : "Die Ersetzung konnte nicht angewendet werden. Ihr Entwurf bleibt unverändert.";
    updateSearchControls();
    return;
  }
  editor.view.dispatch(change.transaction);
  editor.view.dispatch(closeHistory(editor.state.tr));
  search.notice = `${change.count} Treffer ersetzt.`;
  if (!all && search.matches.length) {
    const nextIndex = search.matches.findIndex((match) => match.from >= change.position);
    search.index = nextIndex >= 0 ? nextIndex : 0;
    moveToMatch(0);
  } else {
    updateSearchControls();
    editor.commands.scrollIntoView();
  }
  if (["replace-current", "replace-all"].includes(initiatingControl?.id) && initiatingControl.disabled) {
    $("replace-query").focus();
  }
}

function focusEditor(editor = state.editor) {
  if (!editor || editor.isDestroyed) return;
  // This vanilla workspace must be ready for input before the control event returns.
  // Tiptap's focus command defers browser focus to requestAnimationFrame.
  editor.view.focus();
  editor.commands.scrollIntoView();
}

function formatEditor(command) {
  const editor = state.editor;
  if (!editor?.isEditable) return;
  editor.view.focus();
  command(editor.chain()).run();
  focusEditor(editor);
  updateEditorState();
}

const tableCommands = { addRowBefore, addRowAfter, addColumnBefore, addColumnAfter, deleteRow, deleteColumn, deleteTable };
const tableSizeMessage = "Tabellen unterstützen höchstens 200 Zeilen und 20 Spalten.";
const tableLimitMessage = "Die Tabellenänderung überschreitet die unterstützte Dokumentgröße oder Struktur. Ihr Entwurf bleibt unverändert.";

function validateEditorDocument(documentNode) {
  documentNode.check();
  const documentContent = normalizedDocument(documentNode.toJSON());
  // The shared native preflight checks code points, controls, depth, node count
  // and the server's ASCII-escaped canonical JSON byte limit, even for no query.
  findDocumentMatches(documentContent, "");
  return documentContent;
}

const NativeDocumentGuard = Extension.create({
  name: "nativeDocumentGuard",
  addProseMirrorPlugins() {
    const editor = this.editor;
    return [new Plugin({
      filterTransaction(transaction) {
        if (!transaction.docChanged) return true;
        if (editor === state.editor && !replacementAllowed()) return false;
        try { validateEditorDocument(transaction.doc); return true; }
        catch {
          if (editor === state.editor) notice("Diese Änderung überschreitet die unterstützte Dokumentgröße oder Struktur. Ihr Entwurf bleibt unverändert.", true);
          return false;
        }
      },
    })];
  },
});

function currentTable(editor = state.editor) {
  if (!editor || !isInTable(editor.state)) return null;
  try { return selectedRect(editor.state); } catch { return null; }
}

function tableActionSnapshot(kind, command) {
  return { kind, command, session: state.session, editor: state.editor, revision: state.session.revision,
    document: state.editor.state.doc, selection: state.editor.state.selection };
}

function tableActionCurrent(action) {
  return Boolean(action && sessionCurrent(action.session) && action.editor === state.editor &&
    action.revision === state.session.revision && action.document === state.editor.state.doc &&
    action.selection.eq(state.editor.state.selection) && replacementAllowed());
}

function closeTableDialogs(restoreFocus = false) {
  const action = state.tableAction;
  state.tableAction = null;
  $("table-insert-dialog").close();
  $("table-remove-dialog").close();
  $("table-insert-form").reset();
  $("table-insert-message").textContent = "";
  $("table-remove-summary").textContent = "";
  if (restoreFocus && action?.editor === state.editor && sessionCurrent(action.session)) focusEditor();
}

function updateTableControls() {
  const rect = currentTable();
  const allowed = replacementAllowed();
  $("table-tools").hidden = !rect || !$("find-panel").hidden;
  if (state.tableAction && !tableActionCurrent(state.tableAction)) closeTableDialogs();
  const rowCount = rect?.map.height || 0;
  const columnCount = rect?.map.width || 0;
  $("table-info").textContent = rect ? `${rowCount} ${rowCount === 1 ? "Zeile" : "Zeilen"} × ${columnCount} ${columnCount === 1 ? "Spalte" : "Spalten"} · Zelle ${rect.top + 1}, ${rect.left + 1}` : "";
  $("table-row-action").disabled = !rect || !allowed;
  $("table-column-action").disabled = !rect || !allowed;
  $("table-header-toggle").disabled = !rect || !allowed;
  $("table-delete").disabled = !rect || !allowed;
  $("table-select").disabled = !rect || Boolean(state.session?.loading || state.session?.saving || state.session?.restoring);
  const header = Boolean(rect && Array.from({ length: rect.table.firstChild.childCount }, (_, index) =>
    rect.table.firstChild.child(index).type.name === "tableHeader").every(Boolean));
  $("table-header-toggle").setAttribute("aria-pressed", String(header));
  $("table-header-toggle").title = header ? "Kopfzeile in normale Zellen umwandeln" : "Erste Zeile als Kopfzeile formatieren";
  for (const select of [$("table-row-action"), $("table-column-action"), $("insert-menu")]) {
    select.querySelectorAll("option").forEach((option) => {
      if (!Object.hasOwn(tableCommands, option.value)) return;
      option.disabled = !rect || !allowed ||
        (option.value === "deleteRow" && rect.bottom - rect.top === rowCount) ||
        (option.value === "deleteColumn" && rect.right - rect.left === columnCount);
    });
  }
}

function commitTableTransaction(transaction, message) {
  const editor = state.editor;
  if (!replacementAllowed() || !transaction || !transaction.docChanged || transaction.doc.eq(editor.state.doc)) return false;
  try { validateEditorDocument(transaction.doc); }
  catch {
    $("table-message").textContent = tableLimitMessage;
    if ($("table-tools").hidden && !$("table-insert-dialog").open) notice(tableLimitMessage, true);
    return false;
  }
  closeTableDialogs();
  editor.view.dispatch(closeHistory(transaction).scrollIntoView());
  editor.view.dispatch(closeHistory(editor.state.tr));
  $("table-message").textContent = message;
  focusEditor(editor);
  updateEditorState();
  if ($("table-tools").hidden) notice(message);
  return true;
}

function insertTable(rows = 3, columns = 3, withHeader = true) {
  if (!replacementAllowed()) return false;
  if (!Number.isInteger(rows) || rows < 1 || rows > 200 || !Number.isInteger(columns) || columns < 1 || columns > 20) {
    $("table-insert-message").textContent = tableSizeMessage;
    return false;
  }
  const editor = state.editor;
  const schema = editor.schema;
  const tableRows = Array.from({ length: rows }, (_, rowIndex) => schema.nodes.tableRow.create(null,
    Array.from({ length: columns }, () => (withHeader && rowIndex === 0 ? schema.nodes.tableHeader : schema.nodes.tableCell).createAndFill()),
  ));
  const transaction = editor.state.tr.replaceSelectionWith(schema.nodes.table.create(null, tableRows));
  // The insertion can split a paragraph. Locate the actual inserted table rather
  // than assuming that its start equals the old text selection position.
  const insertedEnd = transaction.selection.from;
  let tableStart = null;
  transaction.doc.descendants((entry, position) => {
    if (entry.type.name === "table" && position < insertedEnd && position + entry.nodeSize >= insertedEnd) tableStart = position + 1;
  });
  if (tableStart !== null) transaction.setSelection(Selection.near(transaction.doc.resolve(tableStart + 2)));
  if (commitTableTransaction(transaction, "Tabelle eingefügt. Änderungen bleiben bis zum Speichern im Entwurf.")) return true;
  $("table-insert-message").textContent = tableLimitMessage;
  return false;
}

function openTableInsert() {
  if (!replacementAllowed()) return;
  closeTableDialogs();
  state.tableAction = tableActionSnapshot("insert");
  $("table-insert-dialog").showModal();
  $("table-rows").focus();
}

function runTableCommand(command, confirmed = false, firstColumn = false) {
  if (!replacementAllowed() || !Object.hasOwn(tableCommands, command)) return false;
  const editor = state.editor;
  const rect = currentTable();
  if (!rect) return false;
  if ((command.startsWith("addRow") && rect.map.height >= 200) ||
      (command.startsWith("addColumn") && rect.map.width >= 20)) {
    $("table-message").textContent = tableSizeMessage;
    focusEditor();
    return false;
  }
  if ((command === "deleteRow" && rect.bottom - rect.top === rect.map.height) ||
      (command === "deleteColumn" && rect.right - rect.left === rect.map.width)) {
    $("table-message").textContent = "Die letzte Zeile oder Spalte bleibt erhalten. Verwenden Sie „Tabelle entfernen“, um die ganze Tabelle zu entfernen.";
    return false;
  }
  if (command.startsWith("delete") && !confirmed) {
    closeTableDialogs();
    state.tableAction = tableActionSnapshot("remove", command);
    const target = command === "deleteTable" ? "die gesamte Tabelle" : command === "deleteRow" ? "die ausgewählten Zeilen" : "die ausgewählten Spalten";
    $("table-remove-summary").textContent = `Möchten Sie ${target} mit ihren Inhalten aus dem Entwurf entfernen? Die Änderung lässt sich rückgängig machen. Gespeicherte Versionen bleiben erhalten.`;
    $("table-remove-dialog").showModal();
    $("table-remove-cancel").focus();
    return false;
  }
  let transaction = null;
  tableCommands[command](editor.state, (candidate) => { transaction = candidate; });
  if (!transaction) return false;
  if (command !== "deleteTable") {
    const remainingTable = transaction.doc.nodeAt(rect.tableStart - 1);
    if (remainingTable?.type.name === "table") {
      const map = TableMap.get(remainingTable);
      const row = command === "addRowAfter" ? rect.bottom : Math.min(rect.top, map.height - 1);
      const column = firstColumn ? 0 : command === "addColumnAfter" ? rect.right : Math.min(rect.left, map.width - 1);
      transaction.setSelection(Selection.near(transaction.doc.resolve(rect.tableStart + map.map[row * map.width + column] + 1)));
    }
  }
  return commitTableTransaction(transaction, command.startsWith("delete") ? "Auswahl aus dem Entwurf entfernt. Rückgängig ist möglich." : "Tabelle erweitert. Änderungen bleiben im Entwurf.");
}

function toggleTableHeader() {
  if (!replacementAllowed()) return;
  const editor = state.editor;
  const rect = currentTable();
  if (!rect) return;
  const firstRow = rect.table.firstChild;
  let allHeaders = true;
  firstRow.forEach((cell) => { if (cell.type.name !== "tableHeader") allHeaders = false; });
  const type = allHeaders ? editor.schema.nodes.tableCell : editor.schema.nodes.tableHeader;
  const transaction = editor.state.tr;
  for (let column = 0; column < rect.map.width; column += 1) {
    const position = rect.tableStart + rect.map.map[column];
    const cell = transaction.doc.nodeAt(position);
    transaction.setNodeMarkup(position, type, cell.attrs, cell.marks);
  }
  commitTableTransaction(transaction, allHeaders ? "Kopfzeile in normale Zellen umgewandelt." : "Erste Zeile als Kopfzeile formatiert.");
}

function selectTablePart(part) {
  const editor = state.editor;
  const rect = currentTable();
  if (!rect || !["cell", "row", "column", "table"].includes(part) || $("table-select").disabled) return;
  const row = rect.top;
  const column = rect.left;
  const anchor = part === "table" ? 0 : part === "column" ? column : row * rect.map.width + (part === "row" ? 0 : column);
  const head = part === "table" ? rect.map.map.length - 1 : part === "column" ? (rect.map.height - 1) * rect.map.width + column :
    part === "row" ? (row + 1) * rect.map.width - 1 : anchor;
  editor.view.dispatch(editor.state.tr.setSelection(CellSelection.create(editor.state.doc,
    rect.tableStart + rect.map.map[anchor], rect.tableStart + rect.map.map[head])));
  focusEditor();
}

function handleTableKey(view, event) {
  if (state.editor?.view !== view || event.altKey) return false;
  const rect = currentTable();
  if (!rect) return false;
  if (["Backspace", "Delete"].includes(event.key) && state.editor.state.selection instanceof CellSelection &&
      rect.top === 0 && rect.left === 0 && rect.bottom === rect.map.height && rect.right === rect.map.width) {
    event.preventDefault();
    runTableCommand("deleteTable");
    return true;
  }
  if (event.key !== "Tab" || event.ctrlKey || event.metaKey) return false;
  event.preventDefault();
  const moved = goToNextCell(event.shiftKey ? -1 : 1)(state.editor.state, (transaction) => view.dispatch(transaction));
  if (moved) return true;
  if (event.shiftKey) {
    leaveTableByKeyboard();
    $("table-message").textContent = "Tabellenanfang erreicht. Wählen Sie eine Tabellenaktion oder navigieren Sie mit Tab weiter.";
  } else if (replacementAllowed()) {
    if (!runTableCommand("addRowAfter", false, true)) leaveTableByKeyboard();
  } else {
    leaveTableByKeyboard();
    $("table-message").textContent = "Tabellenende erreicht. Eine neue Zeile ist im aktuellen Dokumentzustand nicht verfügbar.";
  }
  return true;
}

function leaveTableByKeyboard() {
  const target = !$("table-tools").hidden && !$("table-select").disabled ? $("table-select") :
    !$("find-panel").hidden ? $("find-query") : $("find-toggle");
  target.focus();
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
      editor.commands.setTextSelection(position + 1);
      focusEditor(editor);
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
  closeTableDialogs();
  $("table-message").textContent = "";
  closeComparison();
  cancelRestore();
  session.revision += 1;
  search.notice = "";
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
      TableKit.configure({ table: false }), OfficeTable.configure({ resizable: false }), SearchHighlights, NativeDocumentGuard,
    ],
    editorProps: {
      attributes: { "aria-label": "Dokumentinhalt", role: "textbox", "aria-multiline": "true", spellcheck: "true" },
      handleKeyDown: handleTableKey,
      handlePaste(view, event) {
        event.preventDefault();
        if (state.editor?.view !== view || !replacementAllowed()) return true;
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
    validateEditorDocument(editor.schema.nodeFromJSON(safeContent));
    editor.chain().setMeta("addToHistory", false)
      .setContent(safeContent, { emitUpdate: false, errorOnInvalidContent: true }).run();
  } catch (error) { editor.destroy(); throw error; }
  state.editor?.destroy();
  $("office-editor").replaceChildren(editorHost);
  state.editor = editor;
}

function clearWorkspace() {
  closeTableDialogs();
  $("table-tools").hidden = true;
  $("table-info").textContent = "";
  $("table-message").textContent = "";
  closeComparison();
  cancelRestore();
  state.session = null;
  state.editor?.destroy();
  state.editor = null;
  resetSearch();
  $("office-editor").replaceChildren();
  $("document-title").value = "";
  $("document-history").replaceChildren();
  $("document-outline").replaceChildren();
  $("history-status").textContent = "";
  $("document-status").textContent = "";
  $("document-version").textContent = "";
  $("historical-actions").hidden = true;
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
    loading: true, saving: false, historical: false, conflict: false, uncertain: false, restoring: false,
    version: null, metadata: null, baseline: "", attempt: null, versions: [] };
}

function contentMatches(result, objectId, versionId = null) {
  return result?.tenant_id === state.context.tenantId && result.document?.object_id === objectId &&
    typeof result.document.title === "string" && typeof result.document.current_version_id === "string" &&
    typeof result.version?.version_id === "string" &&
    (!result.is_current_version || result.version.version_id === result.document.current_version_id) &&
    (versionId ? result.version.version_id === versionId :
      result.is_current_version === true && result.version.version_id === result.document.current_version_id) &&
    typeof result.is_current_version === "boolean" && typeof result.can_write === "boolean" &&
    result.rag_indexing_allowed === false && result.search_indexing_allowed === false && result.content?.type === "doc";
}

function acceptContent(result, session) {
  mountEditor(result.content, session);
  closeComparison();
  cancelRestore();
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
  state.editor.view.dispatch(state.editor.state.tr.setSelection(Selection.atEnd(state.editor.state.doc)));
  focusEditor();
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
    const versions = validatedHistory(result, session.objectId);
    session.versions = versions;
    $("history-status").textContent = `Frühere Versionen öffnen Sie schreibgeschützt. ${historyCoverage(versions)}`.trim();
    [...versions].reverse().forEach((version) => {
      const button = node("button", undefined, "version-entry");
      button.type = "button";
      button.dataset.versionId = version.version_id;
      button.setAttribute("aria-current", String(version.version_id === session.version?.version_id));
      button.append(node("strong", versionLabel(version, versions)),
        node("small", dateLabel(version.created_at_utc)), node("small", version.created_by));
      button.title = version.version_id;
      button.addEventListener("click", () => openDocument(session.objectId, version.version_id));
      $("document-history").append(button);
    });
  } catch (error) {
    if (!current()) return;
    $("document-history").replaceChildren();
    if (denied(error)) {
      officeAccessDenied();
      return;
    }
    $("history-status").textContent = "Versionen konnten nicht geladen werden. Bitte versuchen Sie es erneut.";
  } finally {
    if (current()) $("history-refresh").disabled = false;
  }
}

function listedWriteAccess(objectId) {
  return state.documents.some((entry) => entry.object_id === objectId && entry.can_write === true);
}

function officeAccessDenied() {
  clearWorkspace();
  state.documents = []; state.canCreate = false;
  renderDocuments();
  $("documents-status").textContent = "Dieses Dokument ist nicht mehr freigegeben.";
  $("documents-status").classList.add("error");
}

function validatedHistory(result, objectId) {
  if (result?.tenant_id !== state.context.tenantId || result.object_id !== objectId ||
    !Array.isArray(result.versions) || !result.versions.length) throw new ApiError(502);
  const successors = new Map();
  const ids = new Set();
  result.versions.forEach((version) => {
    if (typeof version.version_id !== "string" || typeof version.title !== "string" ||
      typeof version.created_at_utc !== "string" || typeof version.created_by !== "string" ||
      !(version.previous_version_id === null || typeof version.previous_version_id === "string") ||
      ids.has(version.version_id) || successors.has(version.previous_version_id)) throw new ApiError(502);
    ids.add(version.version_id);
    successors.set(version.previous_version_id, version);
  });
  const roots = result.versions.filter((version) => version.previous_version_id === null || !ids.has(version.previous_version_id));
  if (roots.length !== 1) throw new ApiError(502);
  const ordered = [];
  let version = roots[0];
  while (version && ordered.length < result.versions.length) {
    ordered.push(version);
    version = successors.get(version.version_id);
  }
  if (version || ordered.length !== result.versions.length) throw new ApiError(502);
  return ordered;
}

function versionLabel(version, versions) {
  const index = versions.findIndex((entry) => entry.version_id === version.version_id);
  const distance = versions.length - 1 - index;
  const label = distance === 0 ? "Aktuelle Fassung" : `${distance} ${distance === 1 ? "Fassung" : "Fassungen"} zuvor`;
  return `${label} · ${dateLabel(version.created_at_utc)}`;
}

function historyCoverage(versions) {
  return versions[0]?.previous_version_id !== null
    ? `Angezeigt werden die letzten ${versions.length} Fassungen; ältere Fassungen sind nicht geladen.` : "";
}

function validatedContent(result, objectId, versionId = null) {
  if (!contentMatches(result, objectId, versionId) || typeof result.version.title !== "string") throw new ApiError(502);
  const content = normalizedDocument(result.content);
  if (!state.editor) throw new ApiError(502);
  state.editor.schema.nodeFromJSON(content).check();
  return content;
}

function cancelRestore() {
  const restore = state.restore;
  state.restore = null;
  if (!restore) return;
  restore.controller.abort();
  restore.session.restoring = false;
  if (state.discardResolve) settleDiscard(false);
}

function clearComparisonResult(comparison = state.compare) {
  if (comparison) { comparison.result = null; comparison.left = null; comparison.right = null; comparison.page = 0; }
  $("compare-results").replaceChildren();
  $("compare-summary").textContent = "";
  $("compare-page").textContent = "";
  $("compare-previous").disabled = true;
  $("compare-next").disabled = true;
  $("compare-restore").disabled = true;
}

function closeComparison() {
  const comparison = state.compare;
  if (!comparison && !$("compare-dialog").open) return;
  state.compare = null;
  comparison?.controller.abort();
  if (state.restore?.comparison === comparison) cancelRestore();
  clearComparisonResult(comparison);
  if (comparison) comparison.versions = [];
  $("compare-left").replaceChildren(); $("compare-right").replaceChildren();
  $("compare-left").disabled = true; $("compare-right").disabled = true;
  $("compare-status").textContent = "";
  $("compare-load").disabled = true;
  $("compare-dialog").close();
  if (state.session) updateEditorState();
}

function comparisonCurrent(comparison, request = comparison.request) {
  return state.compare === comparison && $("compare-dialog").open && sessionCurrent(comparison.session) &&
    comparison.session.revision === comparison.revision && comparison.request === request;
}

async function openComparison() {
  const session = state.session;
  if (!session?.objectId || session.loading || session.saving || !state.editor) return;
  closeComparison();
  const comparison = { session, revision: session.revision, context: state.context, request: 0,
    controller: new AbortController(), versions: [], result: null, left: null, right: null, page: 0 };
  state.compare = comparison;
  const request = comparison.request;
  clearComparisonResult(comparison);
  $("compare-status").textContent = "Versionen werden geladen …";
  $("compare-dialog").showModal();
  try {
    const result = await api(`/v1/office/documents/${encodeURIComponent(session.objectId)}/versions`,
      { signal: comparison.controller.signal }, comparison.context);
    if (!comparisonCurrent(comparison, request)) return;
    const versions = validatedHistory(result, session.objectId);
    comparison.versions = versions;
    session.versions = versions;
    ["compare-left", "compare-right"].forEach((id) => {
      $(id).replaceChildren(...versions.map((version) => {
        const option = node("option", versionLabel(version, versions));
        option.value = version.version_id;
        return option;
      }));
      $(id).disabled = false;
    });
    $("compare-left").value = versions[Math.max(0, versions.length - 2)].version_id;
    $("compare-right").value = versions[versions.length - 1].version_id;
    $("compare-load").disabled = false;
    $("compare-status").textContent = `Wählen Sie zwei Fassungen und laden Sie den Vergleich. ${historyCoverage(versions)}`.trim();
  } catch (error) {
    if (!comparisonCurrent(comparison, request)) return;
    if (denied(error)) { officeAccessDenied(); return; }
    $("compare-status").textContent = "Versionen konnten nicht geladen werden. Bitte versuchen Sie es erneut.";
    $("compare-load").disabled = false;
  }
}

function comparisonSelectionChanged() {
  const comparison = state.compare;
  if (!comparison) return;
  comparison.request += 1;
  comparison.controller.abort();
  comparison.controller = new AbortController();
  cancelRestore();
  clearComparisonResult(comparison);
  $("compare-status").textContent = "Auswahl geändert. Laden Sie den Vergleich erneut.";
  $("compare-load").disabled = false;
  updateEditorState();
}

async function loadComparison() {
  const comparison = state.compare;
  if (!comparison || state.restore) return;
  if (!comparison.versions.length) { openComparison(); return; }
  const leftId = $("compare-left").value;
  const rightId = $("compare-right").value;
  if (![leftId, rightId].every((id) => comparison.versions.some((entry) => entry.version_id === id))) return;
  comparison.controller.abort();
  comparison.controller = new AbortController();
  const request = ++comparison.request;
  clearComparisonResult(comparison);
  $("compare-status").textContent = "Vergleich wird geladen …";
  $("compare-load").disabled = true;
  try {
    const path = `/v1/office/documents/${encodeURIComponent(comparison.session.objectId)}/content?version_id=`;
    const [left, right] = await Promise.all([leftId, rightId].map((id) =>
      api(`${path}${encodeURIComponent(id)}`, { signal: comparison.controller.signal }, comparison.context)));
    if (!comparisonCurrent(comparison, request)) return;
    const before = validatedContent(left, comparison.session.objectId, leftId);
    const after = validatedContent(right, comparison.session.objectId, rightId);
    comparison.result = compareOfficeDocuments(before, after);
    comparison.left = left; comparison.right = right;
    renderComparison(comparison);
    $("compare-status").textContent = "Vergleich geladen. Gespeicherte Fassungen bleiben unverändert.";
  } catch (error) {
    if (!comparisonCurrent(comparison, request)) return;
    clearComparisonResult(comparison);
    if (denied(error)) { officeAccessDenied(); return; }
    $("compare-status").textContent = "Vergleich konnte nicht geladen werden. Bitte versuchen Sie es erneut.";
  } finally {
    if (comparisonCurrent(comparison, request)) $("compare-load").disabled = false;
  }
}

function renderComparison(comparison) {
  if (!comparisonCurrent(comparison) || !comparison.result) return;
  const { rows, counts, simplified } = comparison.result;
  const titleChanged = comparison.left.version.title !== comparison.right.version.title;
  $("compare-summary").textContent = `${counts.changed} geändert · ${counts.added} hinzugefügt · ${counts.removed} entfernt · ${counts.equal} unverändert.${titleChanged ? " Titel geändert." : " Titel unverändert."}${simplified ? " Große Fassung: vereinfachter Blockvergleich; alle Inhalte sind enthalten." : ""} ${historyCoverage(comparison.versions)}`.trim();
  $("compare-results").replaceChildren();
  const titleRow = node("section", undefined, `compare-row ${titleChanged ? "changed" : "equal"}`);
  titleRow.append(node("h3", titleChanged ? "Titel geändert" : "Titel unverändert"));
  const titles = node("div", undefined, "compare-columns");
  [comparison.left, comparison.right].forEach((entry, index) => {
    const side = node("div", undefined, "compare-side");
    side.append(node("h4", `${index ? "Rechts" : "Links"} · ${versionLabel(entry.version, comparison.versions)}`),
      node("p", entry.version.title, "compare-text"));
    titles.append(side);
  });
  titleRow.append(titles);
  $("compare-results").append(titleRow);
  const pageSize = 40;
  const pages = Math.max(1, Math.ceil(rows.length / pageSize));
  comparison.page = Math.min(Math.max(comparison.page, 0), pages - 1);
  const labels = { equal: "Unverändert", changed: "Geändert", added: "Hinzugefügt", removed: "Entfernt" };
  rows.slice(comparison.page * pageSize, (comparison.page + 1) * pageSize).forEach((row, index) => {
    const section = node("section", undefined, `compare-row ${row.kind}`);
    section.dataset.changeKind = row.kind;
    section.append(node("h3", `${labels[row.kind]} · Block ${comparison.page * pageSize + index + 1}`));
    const columns = node("div", undefined, "compare-columns");
    [row.before, row.after].forEach((block, sideIndex) => {
      const side = node("div", undefined, "compare-side");
      side.append(node("h4", sideIndex ? "Rechts · Nachher" : "Links · Vorher"));
      if (block) {
        const description = describeOfficeBlock(block);
        side.append(node("p", description.label, "compare-block-label"), node("pre", description.text, "compare-text"));
      } else side.append(node("p", "Kein Block in dieser Fassung", "compare-empty"));
      columns.append(side);
    });
    section.append(columns);
    $("compare-results").append(section);
  });
  $("compare-page").textContent = `Seite ${comparison.page + 1} von ${pages} · ${rows.length} Blöcke`;
  $("compare-previous").disabled = comparison.page === 0;
  $("compare-next").disabled = comparison.page === pages - 1;
  $("compare-restore").disabled = Boolean(state.restore) || comparison.left.is_current_version ||
    !listedWriteAccess(comparison.session.objectId);
}

async function restoreVersion(versionId, comparison = null) {
  const session = state.session;
  if (!session?.objectId || session.saving || session.loading || state.restore || !listedWriteAccess(session.objectId)) return;
  const restore = { session, revision: session.revision, context: state.context, comparison,
    comparisonRequest: comparison?.request, versionId, controller: new AbortController() };
  state.restore = restore;
  const current = () => state.restore === restore && sessionCurrent(session) && session.revision === restore.revision &&
    (!comparison || (comparisonCurrent(comparison, restore.comparisonRequest) && $("compare-left").value === versionId));
  try {
    if (!(await confirmDiscard()) || !current()) return;
    session.restoring = true;
    updateEditorState();
    if (comparison) {
      clearComparisonResult(comparison);
      $("compare-status").textContent = "Fassung und aktuelle Berechtigung werden geprüft …";
      $("compare-load").disabled = true;
    } else notice("Fassung und aktuelle Berechtigung werden geprüft …");
    const base = `/v1/office/documents/${encodeURIComponent(session.objectId)}/content`;
    const [historical, head, listing] = await Promise.all([
      api(`${base}?version_id=${encodeURIComponent(versionId)}`, { signal: restore.controller.signal }, restore.context),
      api(base, { signal: restore.controller.signal }, restore.context),
      api("/v1/office/documents", { signal: restore.controller.signal }, restore.context),
    ]);
    if (!current()) return;
    const historicContent = validatedContent(historical, session.objectId, versionId);
    const currentContent = validatedContent(head, session.objectId);
    if (listing?.tenant_id !== restore.context.tenantId || !Array.isArray(listing.documents)) throw new ApiError(502);
    const listed = listing.documents.find((entry) => entry.object_id === session.objectId);
    if (!listed || head.can_write !== true || listed.can_write !== true) throw new ApiError(403);
    if (listed.current_version_id !== head.version.version_id) throw new ApiError(409);
    if (historical.version.version_id === head.version.version_id) throw new ApiError(409);
    const nativeCurrentContent = normalizedDocument(state.editor.schema.nodeFromJSON(currentContent).toJSON());
    const baseline = JSON.stringify({ title: head.version.title, document: nativeCurrentContent });
    const replacement = freshSession(session.objectId);
    replacement.metadata = head.document; replacement.version = head.version; replacement.canWrite = true;
    replacement.versions = session.versions;
    replacement.baseline = baseline;
    mountEditor(historicContent, replacement);
    closeComparison();
    cancelRestore();
    state.session = replacement;
    $("document-title").value = historical.version.title;
    replacement.loading = false;
    $("document-mode").textContent = "Entwurf aus früherer Fassung";
    $("document-version").textContent = `Basis · ${dateLabel(head.version.created_at_utc)}`;
    $("document-version").title = head.version.version_id;
    $("document-history").replaceChildren();
    $("history-status").textContent = "Die Versionsgeschichte bleibt unverändert, bis Sie den Entwurf speichern.";
    refreshDocumentTools();
    notice(isDirty() ? "Frühere Fassung als ungespeicherten Entwurf übernommen. Speichern Sie sie bei Bedarf als neue Version." :
      "Die gewählte Fassung entspricht bereits der aktuellen Version. Es gibt keine ungespeicherten Änderungen.");
    focusEditor();
    renderDocuments();
  } catch (error) {
    if (!current()) return;
    if (denied(error)) { officeAccessDenied(); return; }
    const message = error instanceof ApiError && error.status === 409
      ? "Die aktuelle Version hat sich geändert. Bitte laden Sie die Fassungen erneut; Ihr Entwurf bleibt erhalten."
      : "Die Fassung konnte nicht übernommen werden. Bitte versuchen Sie es erneut; Ihr Entwurf bleibt erhalten.";
    if (comparison) { clearComparisonResult(comparison); $("compare-status").textContent = message; }
    else notice(message, true);
  } finally {
    if (state.restore === restore) {
      state.restore = null;
      session.restoring = false;
      if (sessionCurrent(session)) updateEditorState();
      if (comparison && comparisonCurrent(comparison)) $("compare-load").disabled = false;
    }
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

function toggleFind(show, replacement = false) {
  $("find-panel").hidden = !show;
  $("find-toggle").setAttribute("aria-expanded", String(show));
  if (show) {
    updateSearchControls();
    const input = replacement && replacementAllowed() ? $("replace-query") : $("find-query");
    input.focus(); input.select();
  } else { resetSearch(); rebuildSearch(); focusEditor(); }
  updateTableControls();
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
$("history-compare").addEventListener("click", openComparison);
$("compare-close").addEventListener("click", closeComparison);
$("compare-dialog").addEventListener("cancel", (event) => { event.preventDefault(); closeComparison(); });
$("compare-dialog").addEventListener("close", () => { if (!$("compare-dialog").open) closeComparison(); });
$("compare-left").addEventListener("change", comparisonSelectionChanged);
$("compare-right").addEventListener("change", comparisonSelectionChanged);
$("compare-load").addEventListener("click", loadComparison);
$("compare-restore").addEventListener("click", () => {
  const comparison = state.compare;
  if (comparison?.left && !$("compare-restore").disabled) restoreVersion(comparison.left.version.version_id, comparison);
});
$("document-restore").addEventListener("click", () => {
  if (state.session?.historical && !$("document-restore").disabled) restoreVersion(state.session.version.version_id);
});
["previous", "next"].forEach((direction) => {
  $(`compare-${direction}`).addEventListener("click", () => {
    if (!state.compare?.result) return;
    state.compare.page += direction === "next" ? 1 : -1;
    renderComparison(state.compare);
    $("compare-results").scrollIntoView({ block: "start" });
    $("compare-results").focus({ preventScroll: true });
  });
});
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
$("find-query").addEventListener("input", () => { search.index = 0; search.notice = ""; rebuildSearch(true); });
$("replace-query").addEventListener("input", () => { search.notice = ""; updateSearchControls(); });
$("find-case-sensitive").addEventListener("change", () => { search.index = 0; search.notice = ""; rebuildSearch(true); });
$("find-whole-word").addEventListener("change", () => { search.index = 0; search.notice = ""; rebuildSearch(true); });
$("replace-current").addEventListener("click", () => replaceMatches(false));
$("replace-all").addEventListener("click", () => replaceMatches(true));
$("find-next").addEventListener("click", () => moveToMatch(1));
$("find-previous").addEventListener("click", () => moveToMatch(-1));
$("find-panel").addEventListener("keydown", (event) => {
  if (event.key === "Enter" && [$("find-query"), $("replace-query")].includes(event.target)) {
    event.preventDefault(); moveToMatch(event.shiftKey ? -1 : 1);
  }
  if (event.key === "Escape") { event.preventDefault(); event.stopPropagation(); toggleFind(false); }
});
document.querySelectorAll("[data-command]").forEach((button) => {
  button.addEventListener("mousedown", (event) => { if (event.button === 0) event.preventDefault(); });
  button.addEventListener("click", () => formatEditor((chain) => chain[commandNames[button.dataset.command]]()));
});
$("text-style").addEventListener("change", () => {
  const value = $("text-style").value;
  if (value === "paragraph") formatEditor((chain) => chain.setParagraph());
  else formatEditor((chain) => chain.setHeading({ level: Number(value.split("-")[1]) }));
});
$("insert-menu").addEventListener("change", () => {
  const command = $("insert-menu").value;
  if (command) {
    if (command === "insertTable") insertTable();
    else if (command === "insertTableCustom") openTableInsert();
    else if (command === "horizontalRule") formatEditor((chain) => chain.setHorizontalRule());
    else if (command === "codeBlock") formatEditor((chain) => chain.toggleCodeBlock());
    else runTableCommand(command);
  }
  $("insert-menu").value = "";
});
["table-row-action", "table-column-action"].forEach((id) => {
  $(id).addEventListener("change", () => { const command = $(id).value; $(id).value = ""; runTableCommand(command); });
});
$("table-select").addEventListener("change", () => { const part = $("table-select").value; $("table-select").value = ""; selectTablePart(part); });
$("table-header-toggle").addEventListener("click", toggleTableHeader);
$("table-delete").addEventListener("click", () => runTableCommand("deleteTable"));
["table-header-toggle", "table-delete"].forEach((id) => {
  $(id).addEventListener("mousedown", (event) => { if (event.button === 0) event.preventDefault(); });
});
$("table-insert-form").addEventListener("submit", (event) => {
  event.preventDefault();
  if (!tableActionCurrent(state.tableAction) || state.tableAction.kind !== "insert") { closeTableDialogs(); return; }
  insertTable(Number($("table-rows").value), Number($("table-columns").value), $("table-with-header").checked);
});
$("table-remove-confirm").addEventListener("click", () => {
  const action = state.tableAction;
  if (!tableActionCurrent(action) || action.kind !== "remove") { closeTableDialogs(); return; }
  const command = action.command;
  closeTableDialogs();
  runTableCommand(command, true);
});
["table-insert-cancel", "table-insert-close", "table-remove-cancel"].forEach((id) => {
  $(id).addEventListener("click", () => closeTableDialogs(true));
});
["table-insert-dialog", "table-remove-dialog"].forEach((id) => {
  $(id).addEventListener("cancel", (event) => { event.preventDefault(); closeTableDialogs(true); });
  $(id).addEventListener("close", () => {
    if (!$(id).open && state.tableAction?.kind === (id === "table-insert-dialog" ? "insert" : "remove")) closeTableDialogs();
  });
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
    if (!$("find-panel").hidden) { event.preventDefault(); toggleFind(false); }
  }
  if (!state.editor || document.querySelector("dialog[open]") || !(event.ctrlKey || event.metaKey)) return;
  if (event.key.toLowerCase() === "s") { event.preventDefault(); showSave(); }
  if (event.key.toLowerCase() === "f") { event.preventDefault(); toggleFind(true); }
  if (event.key.toLowerCase() === "h") { event.preventDefault(); toggleFind(true, true); }
});
window.addEventListener("beforeunload", (event) => {
  if (isDirty() || state.session?.saving || state.session?.uncertain) { event.preventDefault(); event.returnValue = ""; }
});

restoreContext();
toggleInspector(!window.matchMedia("(max-width: 1000px)").matches);
window.matchMedia("(max-width: 1000px)").addEventListener("change", (event) => {
  if (event.matches) toggleInspector(false);
});
loadDocuments();
