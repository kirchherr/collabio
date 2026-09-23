import { Editor, Extension, Mark, Node, textblockTypeInputRule } from "@tiptap/core";
import StarterKit from "@tiptap/starter-kit";
import { Table, TableKit } from "@tiptap/extension-table";
import { AllSelection, Plugin, PluginKey, Selection, TextSelection } from "@tiptap/pm/state";
import { sinkListItem, liftListItem } from "@tiptap/pm/schema-list";
import { closeHistory } from "@tiptap/pm/history";
import { Decoration, DecorationSet } from "@tiptap/pm/view";
import {
  addRowBefore, addRowAfter, addColumnBefore, addColumnAfter, deleteRow, deleteColumn,
  deleteTable, goToNextCell, selectedRect, isInTable, CellSelection, TableMap,
} from "@tiptap/pm/tables";
import { compareOfficeDocuments, describeOfficeBlock } from "./office-comparison.mjs";
import { findDocumentMatches, replaceDocumentMatches, OfficeSearchLimitError } from "./office-search.mjs";
import { renderOfficePrintDocument } from "./office-print.mjs";
import { OfficeImageReadError, officeImageAttributes, officeImageReferences, loadOfficePrintImages } from "./office-images.mjs";
import { officeImageExtension, installOfficeImageControls } from "./office-image-controls.mjs";
import { OFFICE_PARAGRAPH_VALUES, officeParagraphAttributes, officeParagraphDOMAttributes, officeParagraphDescription } from "./office-paragraph.mjs";
import { OFFICE_CHARACTER_VALUES, OFFICE_TEXT_COLORS, officeCharacterAttributes, officeCharacterDOMAttributes, officeCharacterDescription } from "./office-character.mjs";
import { OFFICE_STYLE_LIMIT, OFFICE_STYLE_PRESETS, officeStyles, officeStyleFor, officeTextblockAttributes } from "./office-styles.mjs";

const $ = (id) => document.getElementById(id);
const storageKey = "collabio.workspace.context";
const state = {
  context: null, epoch: 0, listRequest: 0, documents: [], canCreate: false,
  session: null, editor: null, listLoading: false, listQuery: "", listCursor: null, listCursors: new Set(),
  listController: null, listTimer: null, listRetry: null, discardResolve: null, compare: null, restore: null,
  tableAction: null, paragraphAction: null, characterAction: null, listAction: null, styleAction: null, formatSample: null, review: null, suggestions: null, print: null, preparedPrint: null, reuse: null,
};
const searchKey = new PluginKey("officeSearch");
const search = { query: "", matches: [], index: -1, windowStart: 0, notice: "" };
const searchHighlightLimit = 200;
const allowedNodes = new Set([
  "doc", "paragraph", "heading", "text", "hardBreak", "bulletList", "orderedList", "listItem",
  "blockquote", "codeBlock", "horizontalRule", "table", "tableRow", "tableCell", "tableHeader", "image", "pageBreak",
]);
const allowedMarks = new Set(["bold", "italic", "strike", "code", "underline", "textStyle"]);
const commandNames = {
  bold: "toggleBold", italic: "toggleItalic", underline: "toggleUnderline", strike: "toggleStrike",
  code: "toggleCode", bulletList: "toggleBulletList", orderedList: "toggleOrderedList",
  blockquote: "toggleBlockquote", undo: "undo", redo: "redo",
};
const OfficeTable = Table.extend({
  renderHTML() { return ["table", { class: "office-table" }, ["tbody", 0]]; },
});
const OfficePageBreak = Node.create({
  name: "pageBreak", group: "block", atom: true, selectable: true, draggable: false,
  parseHTML: () => [],
  renderHTML: () => ["div", { class: "office-page-break", contenteditable: "false", role: "separator", "aria-label": "Seitenumbruch" }],
  renderText: () => "",
});
const OfficeNamedStyles = Extension.create({
  name: "officeNamedStyles",
  addGlobalAttributes() {
    return [
      { types: ["doc"], attributes: { styles: { default: [], rendered: false } } },
      { types: ["paragraph", "heading"], attributes: { styleId: { default: null, keepOnSplit: true,
        parseHTML: () => null,
        renderHTML: (attrs) => attrs.styleId == null ? {} : { "data-office-style-id": attrs.styleId },
      } } },
    ];
  },
  addProseMirrorPlugins() {
    const decorations = (doc) => {
      const styles = officeStyles(doc.attrs.styles || []), entries = [];
      doc.descendants((entry, position) => {
        if (!["paragraph", "heading"].includes(entry.type.name) || entry.attrs.styleId == null) return;
        const style = officeStyleFor(entry.attrs, styles);
        // Direct paragraph attributes already render on the node and take priority.
        const inherited = { ...style.paragraph };
        for (const key of Object.keys(officeParagraphAttributes(entry.attrs))) delete inherited[key];
        entries.push(Decoration.node(position, position + entry.nodeSize, {
          ...officeParagraphDOMAttributes(inherited), ...officeCharacterDOMAttributes(style.character),
        }));
      });
      return DecorationSet.create(doc, entries);
    };
    const key = new PluginKey("officeNamedStyles");
    return [new Plugin({ key,
      state: { init: (_, editorState) => decorations(editorState.doc),
        apply: (transaction, previous) => transaction.docChanged ? decorations(transaction.doc) : previous },
      props: { decorations: (editorState) => key.getState(editorState) },
    })];
  },
});
const OfficeCharacterFormat = Mark.create({
  name: "textStyle",
  addAttributes() {
    return Object.fromEntries(Object.entries(OFFICE_CHARACTER_VALUES).map(([key, values]) => {
      const domName = key === "fontSize" ? "data-office-font-size" : "data-office-text-color";
      return [key, { default: null, keepOnSplit: true,
        parseHTML: (element) => values.find((value) => String(value) === element.getAttribute(domName)) ?? null,
        renderHTML: (attrs) => officeCharacterDOMAttributes({ [key]: attrs[key] }),
      }];
    }));
  },
  parseHTML() { return [{ tag: "span[data-office-font-size]" }, { tag: "span[data-office-text-color]" }]; },
  renderHTML({ HTMLAttributes }) { return ["span", HTMLAttributes, 0]; },
});
const OfficeParagraphFormat = Extension.create({
  name: "officeParagraphFormat",
  priority: 1000,
  addGlobalAttributes() {
    return [{
      types: ["paragraph", "heading"],
      attributes: Object.fromEntries(Object.entries(OFFICE_PARAGRAPH_VALUES).map(([key, values]) => {
        const domName = Object.keys(officeParagraphDOMAttributes({ [key]: values[0] }))[0];
        return [key, {
          default: null, keepOnSplit: true,
          parseHTML: (element) => values.find((value) => String(value) === element.getAttribute(domName)) ?? null,
          renderHTML: (attrs) => officeParagraphDOMAttributes({ [key]: attrs[key] }),
        }];
      })),
    }];
  },
  addKeyboardShortcuts() {
    return {
      "Mod-Alt-0": () => changeTextStyle("paragraph"),
      ...Object.fromEntries([1, 2, 3].map((level) => [`Mod-Alt-${level}`, () =>
        changeTextStyle(this.editor.isActive("heading", { level }) ? "paragraph" : `heading-${level}`)])),
      "Mod-Shift-7": () => formatEditor((chain) => chain.toggleOrderedList(), true),
      "Mod-Shift-8": () => formatEditor((chain) => chain.toggleBulletList(), true),
    };
  },
  addInputRules() {
    return [textblockTypeInputRule({
      find: /^(#{1,3})\s$/,
      type: this.editor.schema.nodes.heading,
      getAttributes: (match) => ({
        level: match[1].length,
        ...officeTextblockAttributes(this.editor.state.selection.$from.parent.attrs),
      }),
    })];
  },
});

class ApiError extends Error {
  constructor(status, malformed = false) { super(`HTTP ${status}`); this.status = status; this.malformed = malformed; }
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
  try { return await response.json(); } catch { throw new ApiError(502, true); }
}

function denied(error) { return (error instanceof ApiError || error instanceof OfficeImageReadError) && [401, 403, 404, 423].includes(error.status); }
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
  officeImageReferences(document);
  const styles = officeStyles(document?.attrs?.styles || []);
  let nodes = 0;
  let characters = 0;
  let pageBreaks = 0;
  const walk = (value, depth = 0) => {
    if (!value || !allowedNodes.has(value.type) || ++nodes > 10000 || depth > 32) throw new Error("document-shape");
    const result = { type: value.type };
    if (value.type === "pageBreak" && (depth !== 1 || Object.keys(value).length !== 1 || ++pageBreaks > 100)) throw new Error("document-page-break");
    if (value.type === "image") result.attrs = officeImageAttributes(value.attrs);
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
    if (["paragraph", "heading"].includes(value.type)) {
      const attributes = officeTextblockAttributes(value.attrs ?? {});
      officeStyleFor(attributes, styles);
      if (Object.keys(attributes).length) result.attrs = { ...result.attrs, ...attributes };
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
      result.marks = value.marks.flatMap((mark) => {
        if (mark.type !== "textStyle") return [{ type: mark.type }];
        const attrs = officeCharacterAttributes(mark.attrs);
        return Object.keys(attrs).length ? [{ type: mark.type, attrs }] : [];
      });
      if (!result.marks.length) delete result.marks;
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
  const result = walk(document);
  if (styles.length) result.attrs = { styles };
  return result;
}

function draftSnapshot() {
  return { title: $("document-title").value.trim(), document: normalizedDocument(state.editor.getJSON()) };
}

function isDirty() {
  if (!state.session || !state.editor || state.session.historical || state.session.loading) return false;
  try { return JSON.stringify(draftSnapshot()) !== state.session.baseline; } catch { return true; }
}

function updateEditorState() {
  if (state.print && !printCurrent(state.print)) closePrint();
  updateReuseControls();
  const session = state.session;
  const editor = state.editor;
  const editable = Boolean(session && sessionCurrent(session) && editor && session.canWrite && !session.loading &&
    !session.historical && !session.saving && !session.uncertain && !session.restoring && !suggestionLocksDocument());
  if (editor && editor.isEditable !== editable) editor.setEditable(editable, false);
  $("document-title").disabled = !editable;
  $("document-save").disabled = !session || !editor || session.loading || session.saving || session.restoring || session.historical ||
    !session.canWrite || session.conflict || Boolean(state.review?.saving || state.review?.uncertain) || suggestionLocksDocument() || (!session.uncertain && !isDirty());
  $("document-save").textContent = session?.uncertain ? "Speicherung prüfen" : "Version speichern";
  $("document-close").disabled = Boolean(session?.saving);
  $("document-reload").disabled = Boolean(session?.saving || session?.loading || !session?.objectId);
  $("document-reload").textContent = session?.historical ? "Aktuelle Version" : "Neu laden";
  $("document-print").disabled = !printAllowed();
  $("history-refresh").disabled = Boolean(!session?.objectId || session?.loading || session?.saving || session?.restoring || session?.history.loading);
  $("history-more").disabled = $("history-refresh").disabled;
  $("history-retry").disabled = $("history-refresh").disabled;
  $("history-compare").disabled = Boolean(!session?.objectId || session?.loading || session?.saving || session?.restoring);
  $("historical-actions").hidden = !session?.historical || !sourceWriteAccess(session?.objectId);
  $("document-restore").disabled = Boolean(session?.loading || session?.saving || session?.restoring);
  document.querySelectorAll("[data-command]").forEach((button) => {
    const command = button.dataset.command;
    button.disabled = !editable || !editor.can()[commandNames[command]]();
    if (button.hasAttribute("aria-pressed")) button.setAttribute("aria-pressed", String(Boolean(editor?.isActive(command))));
  });
  $("text-style").disabled = !editable;
  $("insert-menu").disabled = !editable;
  $("insert-menu").querySelector('[value="pageBreak"]').disabled = !pageBreakAllowed();
  $("insert-menu").querySelector('[value="removePageBreak"]').disabled = !paragraphAllowed() || pageBreakPosition() === null;
  updateTableControls();
  updateParagraphControls();
  updateCharacterControls();
  updateFormatTransfer();
  updateListControls();
  updateStyleControls();
  imageControls.update();
  if (editor) {
    const level = [1, 2, 3].find((candidate) => editor.isActive("heading", { level: candidate }));
    $("text-style").value = level ? `heading-${level}` : "paragraph";
  }
  updateSearchControls();
  updateReviewControls();
  updateSuggestionControls();
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
    !session.loading && !session.historical && !session.saving && !session.uncertain && !session.restoring && !suggestionLocksDocument());
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

function formatEditor(command, preserveParagraphs = false) {
  const editor = state.editor;
  if (!editor?.isEditable) return false;
  const paragraphs = preserveParagraphs ? selectedParagraphs(editor) : [];
  editor.view.focus();
  const chain = command(editor.chain());
  if (paragraphs.length) chain.command(({ tr }) => {
    // Wrapping a heading in a list can first turn it into a paragraph. Retain
    // each surviving block's own format instead of applying the first to all.
    for (const { entry, position } of paragraphs) {
      const attributes = officeTextblockAttributes(entry.attrs);
      if (!Object.keys(attributes).length) continue;
      const mapped = tr.mapping.map(position + 1);
      if (mapped < 0 || mapped > tr.doc.content.size) continue;
      const resolved = tr.doc.resolve(mapped);
      for (let depth = resolved.depth; depth > 0; depth -= 1) {
        const current = resolved.node(depth);
        if (!["paragraph", "heading"].includes(current.type.name)) continue;
        if (current.content.eq(entry.content) && Object.entries(attributes).some(([key, value]) => current.attrs[key] !== value)) {
          tr.setNodeMarkup(resolved.before(depth), undefined, { ...current.attrs, ...attributes });
        }
        break;
      }
    }
    return true;
  });
  chain.run();
  focusEditor(editor);
  updateEditorState();
  return true;
}

const paragraphFields = {
  textAlign: "paragraph-align", lineSpacing: "paragraph-line-spacing",
  spacingBefore: "paragraph-spacing-before", spacingAfter: "paragraph-spacing-after",
};
const paragraphHelp = "Die Änderungen gelten für die ausgewählten Absätze und bleiben bis zum Speichern im Entwurf.";
const paragraphLimitMessage = "Die Absatzformatierung überschreitet die unterstützte Dokumentgröße oder Struktur. Ihr Entwurf bleibt unverändert.";

function selectedParagraphs(editor = state.editor, includeCode = false) {
  if (!editor || editor.isDestroyed) return [];
  const { doc, selection } = editor.state;
  const entries = new Map();
  const supported = (entry) => ["paragraph", "heading"].includes(entry.type.name) || (includeCode && entry.type.name === "codeBlock");
  if (selection.empty) {
    for (let depth = selection.$from.depth; depth > 0; depth -= 1) {
      const entry = selection.$from.node(depth);
      if (supported(entry)) {
        const position = selection.$from.before(depth);
        entries.set(position, { entry, position });
        break;
      }
    }
  } else if (selection instanceof CellSelection) {
    selection.forEachCell((cell, cellPosition) => {
      cell.descendants((entry, offset) => {
        if (!supported(entry)) return;
        const position = cellPosition + 1 + offset;
        entries.set(position, { entry, position });
        return false;
      });
    });
  } else {
    for (const { $from, $to } of selection.ranges) {
      doc.nodesBetween($from.pos, $to.pos, (entry, position) => {
        if (!supported(entry)) return;
        // An endpoint at the start of the next text block does not select it.
        if ($to.pos !== position + 1) entries.set(position, { entry, position });
        return false;
      });
    }
  }
  return [...entries.values()].sort((left, right) => left.position - right.position);
}

function paragraphAllowed() {
  return replacementAllowed() && !state.review?.saving && !state.review?.settling && !state.review?.uncertain;
}

function pageBreakAllowed() {
  if (!paragraphAllowed()) return false;
  const { selection } = state.editor.state;
  return selection.empty ? selection.$from.depth === 0 ||
    (selection.$from.depth === 1 && ["paragraph", "heading"].includes(selection.$from.parent.type.name)) :
    selection.$from.depth === 0 && ["image", "horizontalRule", "table"].includes(selection.node?.type.name);
}

function pageBreakPosition(direction = null) {
  const selection = state.editor?.state.selection;
  if (!selection) return null;
  if (selection.node?.type.name === "pageBreak") return selection.from;
  if (!selection.empty) return null;
  const { $from } = selection;
  const boundary = $from.depth === 0 ? $from.pos : $from.depth === 1 && $from.parent.isTextblock ?
    direction === "forward" ? ($from.parentOffset === $from.parent.content.size ? $from.after() : null) :
    $from.parentOffset === 0 ? $from.before() : $from.parentOffset === $from.parent.content.size ? $from.after() : null : null;
  if (boundary === null) return null;
  const resolved = selection.$from.doc.resolve(boundary);
  if (direction !== "forward" && resolved.nodeBefore?.type.name === "pageBreak") return boundary - 1;
  if (direction !== "backward" && resolved.nodeAfter?.type.name === "pageBreak") return boundary;
  return null;
}

function changePageBreak(remove = false, direction = null) {
  const editor = state.editor;
  if (!paragraphAllowed() || (!remove && !pageBreakAllowed())) return false;
  const { selection } = editor.state;
  const tr = editor.state.tr;
  if (remove) {
    const position = pageBreakPosition(direction);
    if (position === null) return false;
    tr.delete(position, position + 1);
  } else {
    const marker = editor.schema.nodes.pageBreak.create();
    const { $from } = selection;
    if ($from.depth === 1) {
      const block = $from.parent, offset = $from.parentOffset, start = $from.before();
      const left = block.copy(block.content.cut(0, offset)), right = block.copy(block.content.cut(offset));
      tr.replaceWith(start, $from.after(), [left, marker, right]);
      tr.setSelection(TextSelection.create(tr.doc, start + left.nodeSize + 2));
    } else {
      const position = selection.node ? selection.to : selection.from;
      const atEnd = position === tr.doc.content.size;
      tr.insert(position, atEnd ? [marker, editor.schema.nodes.paragraph.create()] : marker);
      tr.setSelection(atEnd ? TextSelection.create(tr.doc, position + 2) : Selection.near(tr.doc.resolve(position + 1), 1));
    }
  }
  try { validateEditorDocument(tr.doc); }
  catch { notice("Der Seitenumbruch überschreitet die Dokumentgrenzen (höchstens 100 Umbrüche).", true); return false; }
  editor.view.dispatch(closeHistory(tr).scrollIntoView());
  editor.view.dispatch(closeHistory(editor.state.tr));
  focusEditor(editor); updateEditorState(); return true;
}

function handlePageBreakKey(view, event) {
  if (state.editor?.view !== view || event.isComposing) return false;
  if ((event.ctrlKey || event.metaKey) && !event.altKey && !event.shiftKey && event.key === "Enter") {
    event.preventDefault();
    if (!changePageBreak()) notice("Setzen Sie die Schreibmarke in einen Absatz oder eine Überschrift außerhalb von Tabellen, Listen und Zitaten.");
    return true;
  }
  if (!event.ctrlKey && !event.metaKey && !event.altKey && !event.shiftKey && ["Backspace", "Delete"].includes(event.key)) {
    const direction = event.key === "Backspace" ? "backward" : "forward";
    if (pageBreakPosition(direction) !== null) { event.preventDefault(); changePageBreak(true, direction); return true; }
  }
  return false;
}

function paragraphActionCurrent(action) {
  return Boolean(action && sessionCurrent(action.session) && action.context === state.context &&
    action.editor === state.editor && action.revision === state.session.revision &&
    action.document === state.editor.state.doc && action.selection.eq(state.editor.state.selection) && paragraphAllowed());
}

function closeParagraphDialog(restoreFocus = false) {
  const action = state.paragraphAction;
  state.paragraphAction = null;
  $("paragraph-dialog").close();
  $("paragraph-form").reset();
  $("paragraph-selection").textContent = "";
  $("paragraph-status").textContent = "";
  $("paragraph-status").classList.remove("error");
  if (restoreFocus && action?.editor === state.editor && sessionCurrent(action.session)) focusEditor();
}

function updateParagraphControls() {
  if (state.paragraphAction && !paragraphActionCurrent(state.paragraphAction)) closeParagraphDialog();
  $("paragraph-format").disabled = !paragraphAllowed() || !selectedParagraphs().length;
  $("paragraph-apply").disabled = !paragraphActionCurrent(state.paragraphAction);
  $("paragraph-reset").disabled = $("paragraph-apply").disabled;
}

function openParagraphDialog() {
  if (!paragraphAllowed()) return;
  const paragraphs = selectedParagraphs();
  if (!paragraphs.length) return;
  closeParagraphDialog();
  state.paragraphAction = {
    session: state.session, editor: state.editor, context: state.context, revision: state.session.revision,
    document: state.editor.state.doc, selection: state.editor.state.selection, paragraphs,
  };
  for (const [key, id] of Object.entries(paragraphFields)) {
    const values = new Set(paragraphs.map(({ entry }) => entry.attrs[key] ?? "default"));
    const mixed = values.size > 1;
    $(id).querySelector('option[value="mixed"]').hidden = !mixed;
    $(id).value = mixed ? "mixed" : String([...values][0]);
  }
  $("paragraph-selection").textContent = `${paragraphs.length} ${paragraphs.length === 1 ? "Absatz ausgewählt" : "Absätze ausgewählt"}.`;
  $("paragraph-status").textContent = paragraphHelp;
  updateParagraphControls();
  $("paragraph-dialog").showModal();
  $("paragraph-align").focus();
}

function applyParagraphFormat() {
  const action = state.paragraphAction;
  if (!paragraphActionCurrent(action)) { closeParagraphDialog(); return; }
  const editor = action.editor;
  let transaction;
  try {
    const changes = {};
    for (const [key, id] of Object.entries(paragraphFields)) {
      const choice = $(id).value;
      if (choice === "mixed") continue;
      if (choice === "default") changes[key] = null;
      else {
        const value = OFFICE_PARAGRAPH_VALUES[key].find((candidate) => String(candidate) === choice);
        if (value === undefined) throw new Error("paragraph-choice");
        changes[key] = value;
      }
    }
    transaction = editor.state.tr;
    for (const { entry, position } of action.paragraphs) {
      if (Object.entries(changes).every(([key, value]) => (entry.attrs[key] ?? null) === value)) continue;
      transaction.setNodeMarkup(position, undefined, { ...entry.attrs, ...changes });
    }
    if (!transaction.docChanged || transaction.doc.eq(editor.state.doc)) {
      $("paragraph-status").textContent = "Keine Änderung: Die Auswahl hat bereits diese Absatzformatierung.";
      $("paragraph-status").classList.remove("error");
      return;
    }
    validateEditorDocument(transaction.doc);
  } catch {
    $("paragraph-status").textContent = paragraphLimitMessage;
    $("paragraph-status").classList.add("error");
    return;
  }
  if (!paragraphActionCurrent(action)) { closeParagraphDialog(); return; }
  closeParagraphDialog();
  editor.view.dispatch(closeHistory(transaction).scrollIntoView());
  editor.view.dispatch(closeHistory(editor.state.tr));
  focusEditor(editor);
  updateEditorState();
  notice("Absatzformatierung angewendet. Änderungen bleiben bis zum Speichern im Entwurf.");
}

const characterFields = { fontSize: "character-size", textColor: "character-color" };
const characterHelp = "Die Formatierung bleibt bis zum Speichern im Entwurf. Code wird nicht verändert.";

function selectedCharacters(editor = state.editor) {
  if (!editor || editor.isDestroyed) return [];
  const { doc, selection, storedMarks } = editor.state;
  if (selection.empty) {
    const marks = storedMarks || selection.$from.marks();
    return selection.$from.parent.type.allowsMarkType(editor.schema.marks.textStyle) && !marks.some((mark) => mark.type.name === "code") ?
      [{ marks, from: selection.from, to: selection.to }] : [];
  }
  const entries = new Map();
  for (const { $from, $to } of selection.ranges) {
    doc.nodesBetween($from.pos, $to.pos, (entry, position, parent) => {
      if (!entry.isText || !parent.type.allowsMarkType(editor.schema.marks.textStyle) || entry.marks.some((mark) => mark.type.name === "code")) return;
      const from = Math.max(position, $from.pos), to = Math.min(position + entry.nodeSize, $to.pos);
      if (from < to) entries.set(`${from}:${to}`, { marks: entry.marks, from, to });
    });
  }
  return [...entries.values()];
}

function characterActionCurrent(action) {
  return paragraphActionCurrent(action) && action.storedMarks === state.editor.state.storedMarks;
}

function closeCharacterDialog(restoreFocus = false) {
  const action = state.characterAction;
  state.characterAction = null;
  $("character-dialog").close();
  $("character-form").reset();
  $("character-status").textContent = "";
  $("character-status").classList.remove("error");
  if (restoreFocus && action?.editor === state.editor && sessionCurrent(action.session)) focusEditor();
}

function updateCharacterControls() {
  if (state.characterAction && !characterActionCurrent(state.characterAction)) closeCharacterDialog();
  $("character-format").disabled = !paragraphAllowed() || !selectedCharacters().length;
  $("character-apply").disabled = !characterActionCurrent(state.characterAction);
  $("character-reset").disabled = $("character-apply").disabled;
}

function openCharacterDialog() {
  if (!paragraphAllowed()) return;
  const characters = selectedCharacters();
  if (!characters.length) return;
  closeCharacterDialog();
  state.characterAction = {
    session: state.session, editor: state.editor, context: state.context, revision: state.session.revision,
    document: state.editor.state.doc, selection: state.editor.state.selection, storedMarks: state.editor.state.storedMarks, characters,
  };
  for (const [key, id] of Object.entries(characterFields)) {
    const values = new Set(characters.map(({ marks }) => marks.find((mark) => mark.type.name === "textStyle")?.attrs[key] ?? "default"));
    $(id).querySelector('option[value="mixed"]').hidden = values.size < 2;
    $(id).value = values.size > 1 ? "mixed" : String([...values][0]);
  }
  $("character-selection").textContent = state.editor.state.selection.empty ?
    "Gilt für den Text, den Sie als Nächstes am Cursor eingeben." : "Gilt nur für den ausgewählten Text, auch in Listen und Tabellenzellen.";
  $("character-status").textContent = characterHelp;
  updateCharacterControls();
  $("character-dialog").showModal();
  $("character-size").focus();
}

function applyCharacterFormat() {
  const action = state.characterAction;
  if (!characterActionCurrent(action)) { closeCharacterDialog(); return; }
  const editor = action.editor, type = editor.schema.marks.textStyle;
  const transaction = editor.state.tr;
  let changed = false;
  try {
    const changes = {};
    for (const [key, id] of Object.entries(characterFields)) {
      const choice = $(id).value;
      if (choice === "mixed") continue;
      changes[key] = choice === "default" ? null : OFFICE_CHARACTER_VALUES[key].find((value) => String(value) === choice);
      if (changes[key] === undefined) throw new Error("character-choice");
    }
    for (const { marks, from, to } of action.characters) {
      const previous = marks.find((mark) => mark.type === type);
      const before = officeCharacterAttributes(previous?.attrs || {});
      const attrs = officeCharacterAttributes({ ...before, ...changes });
      if (JSON.stringify(before) === JSON.stringify(attrs)) continue;
      changed = true;
      const next = Object.keys(attrs).length ? type.create(attrs) : null;
      if (from === to) {
        const other = type.removeFromSet(marks);
        transaction.setStoredMarks(next ? next.addToSet(other) : other);
      } else {
        transaction.removeMark(from, to, type);
        if (next) transaction.addMark(from, to, next);
      }
    }
    if (!changed) { $("character-status").textContent = "Keine Änderung: Die Auswahl hat bereits diese Zeichenformatierung."; return; }
    validateEditorDocument(transaction.doc);
  } catch {
    $("character-status").textContent = "Die Zeichenformatierung überschreitet die unterstützte Dokumentgröße oder Struktur. Ihr Entwurf bleibt unverändert.";
    $("character-status").classList.add("error");
    return;
  }
  if (!characterActionCurrent(action)) { closeCharacterDialog(); return; }
  closeCharacterDialog();
  editor.view.dispatch(closeHistory(transaction).scrollIntoView());
  // Keep pending typing marks while separating the edit from the next undo group.
  editor.view.dispatch(closeHistory(editor.state.tr).setStoredMarks(editor.state.storedMarks));
  focusEditor(editor);
  updateEditorState();
  notice(action.selection.empty ? "Zeichenformatierung für die nächste Eingabe gewählt." : "Zeichenformatierung angewendet. Änderungen bleiben bis zum Speichern im Entwurf.");
}

const transferableMarks = ["bold", "italic", "underline", "strike", "textStyle"];

function transferMarks(marks) {
  return transferableMarks.flatMap((name) => {
    const mark = marks.find((entry) => entry.type.name === name);
    if (!mark) return [];
    const attrs = name === "textStyle" ? officeCharacterAttributes(mark.attrs) : {};
    return name === "textStyle" && !Object.keys(attrs).length ? [] : [{ type: name, attrs }];
  });
}

function updateFormatTransfer() {
  const sample = state.formatSample;
  if (sample && (sample.editor !== state.editor || sample.session !== state.session || sample.context !== state.context || !sessionCurrent(sample.session))) state.formatSample = null;
  const allowed = paragraphAllowed();
  const characters = selectedCharacters().length > 0, paragraphs = selectedParagraphs().length > 0;
  const menu = $("format-transfer");
  menu.disabled = !allowed;
  menu.querySelector('[value="copy"]').disabled = !allowed || !characters || !paragraphs;
  for (const scope of ["characters", "paragraphs", "both"]) {
    menu.querySelector(`[value="${scope}"]`).disabled = !allowed || !state.formatSample ||
      (scope !== "paragraphs" && !characters) || (scope !== "characters" && !paragraphs);
  }
  menu.querySelector('[value="clear"]').disabled = !state.formatSample;
  menu.querySelector('[value=""]').textContent = state.formatSample ? "Format bereit …" : "Format übertragen …";
  const description = state.formatSample?.description || "Noch kein Format aufgenommen.";
  if ($("format-sample").textContent !== description) $("format-sample").textContent = description;
}

function copyFormat() {
  if (!paragraphAllowed()) return;
  const characters = selectedCharacters(), paragraphs = selectedParagraphs();
  if (!characters.length || !paragraphs.length) return;
  const marks = transferMarks(characters[0].marks);
  const attrs = officeParagraphAttributes(paragraphs[0].entry.attrs);
  if (characters.some((entry) => JSON.stringify(transferMarks(entry.marks)) !== JSON.stringify(marks)) ||
      paragraphs.some(({ entry }) => JSON.stringify(officeParagraphAttributes(entry.attrs)) !== JSON.stringify(attrs))) {
    state.formatSample = null;
    updateFormatTransfer();
    notice("Die Auswahl enthält unterschiedliche Formate. Setzen Sie den Cursor in die gewünschte Vorlage oder wählen Sie einheitlich formatierten Text.", true);
    focusEditor();
    return;
  }
  const labels = { bold: "Fett", italic: "Kursiv", underline: "Unterstrichen", strike: "Durchgestrichen" };
  const description = [marks.map((mark) => labels[mark.type] || officeCharacterDescription(mark.attrs)).join("; ") || "Standardzeichen",
    officeParagraphDescription(attrs).join("; ") || "Standardabsatz"].join(" · ");
  // Only allowlisted presentation values are held in this document's memory.
  // No source text, clipboard, browser storage or cross-document sample is used.
  state.formatSample = { marks, attrs, description, editor: state.editor, session: state.session, context: state.context };
  updateFormatTransfer();
  notice(`Format aufgenommen: ${description}. Wählen Sie das Ziel und wenden Sie Zeichen, Absatz oder beides an. Code bleibt unverändert.`);
  focusEditor();
}

function applyTransferredFormat(scope) {
  updateFormatTransfer();
  const sample = state.formatSample;
  if (!sample || !paragraphAllowed() || !["characters", "paragraphs", "both"].includes(scope)) return;
  const editor = state.editor, transaction = editor.state.tr;
  const characters = scope === "paragraphs" ? [] : selectedCharacters();
  const paragraphs = scope === "characters" ? [] : selectedParagraphs();
  if ((scope !== "paragraphs" && !characters.length) || (scope !== "characters" && !paragraphs.length)) return;
  try {
    for (const { entry, position } of paragraphs) {
      const attrs = { ...entry.attrs, ...Object.fromEntries(Object.keys(OFFICE_PARAGRAPH_VALUES).map((key) => [key, sample.attrs[key] ?? null])) };
      if (JSON.stringify(officeParagraphAttributes(entry.attrs)) !== JSON.stringify(sample.attrs)) transaction.setNodeMarkup(position, undefined, attrs);
    }
    for (const { marks, from, to } of characters) {
      if (JSON.stringify(transferMarks(marks)) === JSON.stringify(sample.marks) && !(from === to && transaction.docChanged)) continue;
      const next = sample.marks.map((mark) => editor.schema.marks[mark.type].create(mark.attrs));
      if (from === to) transaction.setStoredMarks(next);
      else {
        for (const name of transferableMarks) transaction.removeMark(from, to, editor.schema.marks[name]);
        for (const mark of next) transaction.addMark(from, to, mark);
      }
    }
    if (scope === "paragraphs" && transaction.docChanged && editor.state.storedMarks) transaction.setStoredMarks(editor.state.storedMarks);
    validateEditorDocument(transaction.doc);
  } catch {
    notice("Die Formatübertragung überschreitet die unterstützte Dokumentgröße oder Struktur. Ihr Entwurf bleibt unverändert.", true);
    focusEditor();
    return;
  }
  if (transaction.doc.eq(editor.state.doc) && !transaction.storedMarksSet) {
    notice("Keine Änderung: Das Ziel hat bereits dieses Format.");
    focusEditor();
    return;
  }
  editor.view.dispatch(closeHistory(transaction).scrollIntoView());
  editor.view.dispatch(closeHistory(editor.state.tr).setStoredMarks(editor.state.storedMarks));
  focusEditor();
  updateEditorState();
  notice(transaction.docChanged ? "Format übertragen. Rückgängig ist möglich; gespeichert wird erst mit der nächsten bestätigten Version." : "Zeichenformat für die nächste Eingabe gewählt.");
}

function changeTextStyle(value) {
  if (!replacementAllowed() || !["paragraph", "heading-1", "heading-2", "heading-3"].includes(value)) return false;
  const editor = state.editor;
  const type = editor.schema.nodes[value === "paragraph" ? "paragraph" : "heading"];
  const level = value === "paragraph" ? {} : { level: Number(value.split("-")[1]) };
  const transaction = editor.state.tr;
  try {
    for (const { entry, position } of selectedParagraphs(editor, true)) {
      const start = transaction.mapping.map(position);
      const end = transaction.mapping.map(position + entry.nodeSize);
      transaction.setBlockType(start, end, type, { ...level, ...officeTextblockAttributes(entry.attrs) });
    }
    if (!transaction.docChanged || transaction.doc.eq(editor.state.doc)) { focusEditor(editor); updateEditorState(); return true; }
    validateEditorDocument(transaction.doc);
  } catch { notice(paragraphLimitMessage, true); updateEditorState(); return false; }
  editor.view.dispatch(closeHistory(transaction).scrollIntoView());
  editor.view.dispatch(closeHistory(editor.state.tr));
  focusEditor(editor);
  updateEditorState();
  return true;
}

const styleFields = {
  ...Object.fromEntries(Object.keys(OFFICE_PARAGRAPH_VALUES).map((key) => [key, `style-${key}`])),
  ...Object.fromEntries(Object.keys(OFFICE_CHARACTER_VALUES).map((key) => [key, `style-${key}`])),
};

function closeStyleDialog(restoreFocus = false) {
  const action = state.styleAction;
  state.styleAction = null;
  $("style-dialog").close(); $("style-form").reset();
  $("style-choice").replaceChildren(); $("style-status").textContent = "";
  $("style-selection").textContent = ""; $("style-impact").textContent = "";
  $("style-preview").replaceChildren();
  if (restoreFocus && action?.editor === state.editor && sessionCurrent(action.session)) focusEditor();
}

function updateStyleControls() {
  if (state.styleAction && !characterActionCurrent(state.styleAction)) closeStyleDialog();
  const paragraphs = selectedParagraphs(), styles = state.editor?.state.doc.attrs.styles || [];
  $("style-options").disabled = !paragraphAllowed() || !paragraphs.length;
  const ids = new Set(paragraphs.map(({ entry }) => entry.attrs.styleId));
  const current = ids.size === 1 ? styles.find((style) => style.id === [...ids][0]) : null;
  $("style-options").textContent = current ? current.name : ids.size > 1 ? "Vorlagen: gemischt" : "Vorlagen …";
  $("style-options").title = current ? `Formatvorlage: ${current.name}` : "Formatvorlagen verwalten und anwenden";
  $("style-remove").disabled = !state.styleAction || !paragraphs.some(({ entry }) => entry.attrs.styleId != null);
}

function openStyleDialog() {
  if (!paragraphAllowed() || !selectedParagraphs().length) return;
  closeStyleDialog();
  const editor = state.editor, paragraphs = selectedParagraphs(), styles = officeStyles(editor.state.doc.attrs.styles);
  state.styleAction = { editor, session: state.session, context: state.context, revision: state.session.revision,
    document: editor.state.doc, selection: editor.state.selection, storedMarks: editor.state.storedMarks, paragraphs, styles };
  const option = (value, label) => { const element = node("option", label); element.value = value; $("style-choice").append(element); };
  for (const style of styles) option(style.id, style.name);
  for (const preset of OFFICE_STYLE_PRESETS) option(`preset:${preset.id}`, `Neu: ${preset.name}`);
  option("new", "Neue eigene Vorlage");
  const ids = new Set(paragraphs.map(({ entry }) => entry.attrs.styleId));
  $("style-choice").value = ids.size === 1 && styles.some((style) => style.id === [...ids][0]) ? [...ids][0] : "preset:body";
  $("style-selection").textContent = `${paragraphs.length} ${paragraphs.length === 1 ? "Absatz ausgewählt" : "Absätze ausgewählt"}. ${styles.length} von ${OFFICE_STYLE_LIMIT} Dokumentvorlagen angelegt.`;
  chooseDocumentStyle(); updateStyleControls();
  $("style-dialog").showModal(); $("style-choice").focus();
}

function chooseDocumentStyle() {
  const action = state.styleAction;
  if (!characterActionCurrent(action)) { closeStyleDialog(); return; }
  const choice = $("style-choice").value;
  const saved = action.styles.find((style) => style.id === choice);
  const preset = OFFICE_STYLE_PRESETS.find((style) => `preset:${style.id}` === choice);
  const style = saved || preset || { name: "", paragraph: {}, character: {} };
  $("style-name").value = style.name;
  for (const [key, id] of Object.entries(styleFields)) $(id).value = String(style.paragraph[key] ?? style.character[key] ?? "default");
  let count = 0;
  action.document.descendants((entry) => { if (saved && entry.attrs.styleId === saved.id) count += 1; });
  $("style-impact").textContent = saved ? `Diese Vorlage ist mit ${count} Absätzen verbunden. Änderungen an der Vorlage gelten für alle. Direkte Formatierungen haben Vorrang.` :
    "Die neue Vorlage wird in diesem Dokument gespeichert. Sie kann anschließend auf weitere Absätze angewendet werden.";
  $("style-update").disabled = !saved;
  $("style-apply").disabled = !saved && action.styles.length >= OFFICE_STYLE_LIMIT;
  $("style-status").textContent = !saved && action.styles.length >= OFFICE_STYLE_LIMIT ? "Dieses Dokument enthält bereits 20 Vorlagen. Bearbeiten Sie eine bestehende Vorlage." : "";
  previewDocumentStyle();
}

function readDocumentStyle(id) {
  const paragraph = {}, character = {};
  for (const [key, control] of Object.entries(styleFields)) {
    if ($(control).value === "default") continue;
    const values = OFFICE_PARAGRAPH_VALUES[key] || OFFICE_CHARACTER_VALUES[key];
    const value = values.find((candidate) => String(candidate) === $(control).value);
    if (value === undefined) throw new Error("style-choice");
    (Object.hasOwn(OFFICE_PARAGRAPH_VALUES, key) ? paragraph : character)[key] = value;
  }
  return { id, name: $("style-name").value.trim(), paragraph, character };
}

function previewDocumentStyle() {
  $("style-preview").replaceChildren();
  if (!state.styleAction) return;
  try {
    const style = readDocumentStyle("preview"), sample = node("p", "So sieht Ihre Vorlage aus. Café und Ideen.");
    for (const [name, value] of Object.entries({ ...officeParagraphDOMAttributes(style.paragraph), ...officeCharacterDOMAttributes(style.character) })) sample.setAttribute(name, value);
    $("style-preview").append(sample);
  } catch { /* Invalid select values never become CSS or preview attributes. */ }
}

function commitDocumentStyle(mode) {
  const action = state.styleAction;
  if (!characterActionCurrent(action)) { closeStyleDialog(); return; }
  const editor = action.editor, transaction = editor.state.tr;
  try {
    const existing = action.styles.find((style) => style.id === $("style-choice").value);
    if (mode === "remove") {
      for (const { entry, position } of action.paragraphs) transaction.setNodeMarkup(position, undefined, { ...entry.attrs, styleId: null });
    } else {
      if (mode === "update" && !existing) return;
      const style = readDocumentStyle(existing?.id || `style-${mutationReference()}`);
      const styles = officeStyles(existing ? action.styles.map((entry) => entry.id === existing.id ? style : entry) : [...action.styles, style]);
      transaction.setDocAttribute("styles", styles);
      if (mode === "apply") for (const { entry, position } of action.paragraphs) {
        // Application starts with the template's paragraph values. Character
        // highlights stay explicit and continue overriding inherited values.
        transaction.setNodeMarkup(position, undefined, { ...entry.attrs, styleId: style.id,
          ...Object.fromEntries(Object.keys(OFFICE_PARAGRAPH_VALUES).map((key) => [key, null])) });
      }
    }
    validateEditorDocument(transaction.doc);
  } catch {
    $("style-status").textContent = "Prüfen Sie den eindeutigen Namen (1–60 Zeichen) und die Werte. Höchstens 20 Vorlagen und die Dokumentgrößenlimits sind erlaubt. Der Entwurf bleibt unverändert.";
    return;
  }
  if (transaction.doc.eq(editor.state.doc)) { $("style-status").textContent = "Keine Änderung: Die Vorlage und Auswahl sind bereits so eingestellt."; return; }
  if (editor.state.storedMarks) transaction.setStoredMarks(editor.state.storedMarks);
  closeStyleDialog();
  editor.view.dispatch(closeHistory(transaction).scrollIntoView());
  editor.view.dispatch(closeHistory(editor.state.tr).setStoredMarks(editor.state.storedMarks));
  focusEditor(); updateEditorState();
  notice("Formatvorlage geändert. Rückgängig ist möglich; gespeichert wird erst mit der nächsten bestätigten Version.");
}

function selectedList(editor = state.editor) {
  if (!editor || editor.isDestroyed || !(editor.state.selection instanceof TextSelection)) return null;
  const { $from, $to } = editor.state.selection;
  if ([$from, $to].some((position) => position.parent.type.name === "codeBlock")) return null;
  const nearest = (position) => {
    for (let depth = position.depth; depth > 0; depth -= 1) {
      const entry = position.node(depth);
      if (["bulletList", "orderedList"].includes(entry.type.name)) return { entry, position: position.before(depth), depth };
    }
    return null;
  };
  const first = nearest($from), last = nearest($to);
  if (!first || !last || first.position !== last.position) return null;
  return { ...first, count: $to.index(first.depth) - $from.index(first.depth) + 1 };
}

function closeListDialog(restoreFocus = false) {
  const action = state.listAction;
  state.listAction = null;
  $("list-dialog").close();
  $("list-form").reset();
  $("list-status").textContent = "";
  if (restoreFocus && action?.editor === state.editor && sessionCurrent(action.session)) focusEditor();
}

function updateListControls() {
  if (state.listAction && !characterActionCurrent(state.listAction)) closeListDialog();
  const list = selectedList();
  const allowed = paragraphAllowed() && Boolean(list);
  $("list-options").disabled = !allowed;
  for (const [id, command] of [["list-indent", sinkListItem], ["list-outdent", liftListItem]]) {
    $(id).disabled = !allowed || !command(state.editor.schema.nodes.listItem)(state.editor.state);
  }
  $("list-start").disabled = !allowed || list.entry.type.name !== "orderedList";
  $("list-apply").disabled = $("list-start").disabled;
}

function openListDialog() {
  if (!paragraphAllowed()) return;
  const list = selectedList();
  if (!list) return;
  closeListDialog();
  const editor = state.editor;
  state.listAction = { editor, session: state.session, context: state.context, revision: state.session.revision,
    document: editor.state.doc, selection: editor.state.selection, storedMarks: editor.state.storedMarks, list };
  $("list-selection").textContent = `${list.count} ${list.count === 1 ? "Listenpunkt" : "Listenpunkte"} ausgewählt · ${list.entry.type.name === "orderedList" ? "Nummerierte Liste" : "Aufzählung"}`;
  $("list-numbering").hidden = list.entry.type.name !== "orderedList";
  $("list-start").value = String(list.entry.attrs.start || 1);
  updateListControls();
  $("list-dialog").showModal();
  (!$("list-indent").disabled ? $("list-indent") : $("list-outdent")).focus();
}

function commitListTransaction(transaction) {
  const editor = state.editor;
  try { validateEditorDocument(transaction.doc); }
  catch {
    const message = "Die Listenänderung überschreitet die unterstützte Dokumentgröße oder Verschachtelung. Ihr Entwurf bleibt unverändert.";
    if (state.listAction) $("list-status").textContent = message;
    else notice(message, true);
    return true;
  }
  if (transaction.doc.eq(editor.state.doc)) {
    $("list-status").textContent = "Keine Änderung: Die Liste beginnt bereits mit dieser Zahl.";
    return true;
  }
  if (editor.state.storedMarks) transaction.setStoredMarks(editor.state.storedMarks);
  closeListDialog();
  editor.view.dispatch(closeHistory(transaction).scrollIntoView());
  editor.view.dispatch(closeHistory(editor.state.tr).setStoredMarks(editor.state.storedMarks));
  focusEditor();
  updateEditorState();
  notice("Liste geändert. Rückgängig ist möglich; gespeichert wird erst mit der nächsten bestätigten Version.");
  return true;
}

function changeListLevel(direction) {
  if (!paragraphAllowed() || !selectedList() || (state.listAction && !characterActionCurrent(state.listAction))) return false;
  const command = direction === "indent" ? sinkListItem : direction === "outdent" ? liftListItem : null;
  if (!command) return false;
  let transaction;
  if (!command(state.editor.schema.nodes.listItem)(state.editor.state, (candidate) => { transaction = candidate; }) || !transaction) return false;
  return commitListTransaction(transaction);
}

function applyListStart() {
  const action = state.listAction;
  if (!characterActionCurrent(action)) { closeListDialog(); return; }
  const raw = $("list-start").value;
  if (!/^\d+$/.test(raw) || Number(raw) < 1 || Number(raw) > 1000000 || action.list.entry.type.name !== "orderedList") {
    $("list-status").textContent = "Wählen Sie eine ganze Startzahl von 1 bis 1.000.000.";
    return;
  }
  commitListTransaction(state.editor.state.tr.setNodeMarkup(action.list.position, undefined, { ...action.list.entry.attrs, start: Number(raw) }));
}

function handleListKey(view, event) {
  if (state.editor?.view !== view || event.ctrlKey || event.metaKey) return false;
  const tab = event.key === "Tab" && !event.altKey;
  const arrow = event.altKey && event.shiftKey && ["ArrowLeft", "ArrowRight"].includes(event.key);
  if (!tab && !arrow) return false;
  const { $from, $to } = view.state.selection;
  const inList = [$from, $to].some((position) => {
    for (let depth = position.depth; depth > 0; depth -= 1) if (position.node(depth).type.name === "listItem") return true;
    return false;
  });
  if (!inList) return false;
  event.preventDefault();
  if (!changeListLevel((tab ? event.shiftKey : event.key === "ArrowLeft") ? "outdent" : "indent") && tab) {
    // Also consume unsupported list selections so the default list keymap cannot
    // bypass this scope. Leave unavailable Tab actions through a reachable control.
    (!$("list-options").disabled ? $("list-options") : $("find-toggle")).focus();
  }
  return true;
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
  $("table-remove-title").textContent = "Tabelleninhalt entfernen?";
  $("table-remove-confirm").textContent = "Aus Entwurf entfernen";
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

function wholeDocumentHasTables(view) {
  if (state.editor?.view !== view || !(view.state.selection instanceof AllSelection)) return false;
  let found = false;
  view.state.doc.descendants((entry) => { if (entry.type.name === "table") found = true; return !found; });
  return found;
}

function replaceWholeDocument(view, text) {
  if (!wholeDocumentHasTables(view)) return false;
  if (!replacementAllowed()) return true;
  let transaction;
  try {
    if (text.length > 100000) throw new Error("document-length");
    const paragraphs = text.replaceAll("\r", "").split("\n").map((line) =>
      view.state.schema.nodes.paragraph.create(null, line ? view.state.schema.text(line) : null));
    // Replace complete top-level nodes. A text selection ending inside the last
    // table can leave an empty table behind, which the strict guard must reject.
    transaction = view.state.tr.replaceWith(0, view.state.doc.content.size, paragraphs);
    transaction.setSelection(Selection.atEnd(transaction.doc)).setStoredMarks(null);
    validateEditorDocument(transaction.doc);
  } catch {
    notice("Diese Änderung überschreitet die unterstützte Dokumentgröße oder Struktur. Ihr Entwurf bleibt unverändert.", true);
    return true;
  }
  closeTableDialogs();
  state.tableAction = { ...tableActionSnapshot("remove"), transaction };
  $("table-remove-title").textContent = text ? "Gesamten Inhalt ersetzen?" : "Gesamten Inhalt entfernen?";
  $("table-remove-summary").textContent = `Möchten Sie den gesamten Dokumentinhalt einschließlich aller Tabellen ${text ? "durch den eingegebenen Text ersetzen" : "aus dem Entwurf entfernen"}? Die Änderung lässt sich rückgängig machen. Gespeicherte Versionen bleiben erhalten.`;
  $("table-remove-confirm").textContent = text ? "Inhalt ersetzen" : "Inhalt entfernen";
  $("table-remove-dialog").showModal();
  $("table-remove-cancel").focus();
  return true;
}

function handleTableKey(view, event) {
  if (state.editor?.view !== view || event.altKey) return false;
  if ((event.ctrlKey || event.metaKey) && !event.shiftKey && event.key.toLowerCase() === "a") {
    event.preventDefault();
    // Include non-text boundaries, independently of the starting cell or the
    // browser's DOM selection inside a terminal table.
    view.dispatch(view.state.tr.setSelection(new AllSelection(view.state.doc)));
    return true;
  }
  if (["Backspace", "Delete", "Enter"].includes(event.key) && replaceWholeDocument(view, "")) {
    event.preventDefault();
    return true;
  }
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
  imageControls.close();
  closeReuse();
  closePrint();
  closeTableDialogs();
  closeParagraphDialog();
  closeCharacterDialog();
  $("table-message").textContent = "";
  closeListDialog();
  closeStyleDialog();
  closeComparison();
  cancelRestore();
  session.revision += 1;
  search.notice = "";
  session.attempt = null;
  $("save-dialog").close();
  $("save-confirm").checked = false;
  if (!session.conflict) notice();
  refreshDocumentTools();
  clearReviewHighlight();
  if (state.suggestions && !state.suggestions.uncertain) {
    state.suggestions.attempt = null;
    closeSuggestionConfirmation();
  }
}

function prepareEditor(content, session) {
  const editorHost = document.createElement("div");
  const safeContent = normalizedDocument(content);
  const editor = new Editor({
    element: editorHost, injectCSS: false, content: { type: "doc", content: [{ type: "paragraph" }] },
    editable: false, enablePasteRules: false,
    extensions: [
      StarterKit.configure({ link: false, heading: { levels: [1, 2, 3] }, trailingNode: false }),
      TableKit.configure({ table: false }), OfficeTable.configure({ resizable: false }), OfficeParagraphFormat, OfficeCharacterFormat,
      SearchHighlights, NativeDocumentGuard, ReviewHighlight, OfficeNamedStyles, OfficePageBreak,
      officeImageExtension(state.context, () => { if (sessionCurrent(session)) officeAccessDenied(); }),
    ],
    editorProps: {
      attributes: { "aria-label": "Dokumentinhalt", role: "textbox", "aria-multiline": "true", spellcheck: "true" },
      handleKeyDown(view, event) { return handlePageBreakKey(view, event) || handleTableKey(view, event) || handleListKey(view, event); },
      handleTextInput(view, _from, _to, text) { return replaceWholeDocument(view, text); },
      handleDOMEvents: {
        // Android Chromium can bypass ProseMirror's ordinary Enter keymap.
        // Handle this explicit command before native paragraph insertion.
        keydown(view, event) { return handlePageBreakKey(view, event); },
        beforeinput(view, event) {
          if (!event.cancelable || !wholeDocumentHasTables(view)) return false;
          const textInput = ["insertText", "insertReplacementText"].includes(event.inputType) && typeof event.data === "string";
          const removeInput = ["deleteContentBackward", "deleteContentForward", "insertParagraph", "insertLineBreak"].includes(event.inputType);
          if (!textInput && !removeInput) return false;
          // Intercept before Chromium mutates table NodeViews. handleTextInput
          // alone runs too late for a DOM change spanning structural boundaries.
          event.preventDefault();
          return replaceWholeDocument(view, textInput ? event.data : "");
        },
        cut(view, event) {
          if (!wholeDocumentHasTables(view)) return false;
          event.preventDefault();
          if (!replacementAllowed() || !event.clipboardData) return true;
          event.clipboardData.setData("text/plain", view.state.doc.textBetween(0, view.state.doc.content.size, "\n\n"));
          return replaceWholeDocument(view, "");
        },
      },
      handlePaste(view, event) {
        event.preventDefault();
        if (state.editor?.view !== view || !replacementAllowed()) return true;
        const text = event.clipboardData?.getData("text/plain") || "";
        if (replaceWholeDocument(view, text)) return true;
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
    onSelectionUpdate: () => { if (sessionCurrent(session)) updateEditorState(); },
  });
  try {
    validateEditorDocument(editor.schema.nodeFromJSON(safeContent));
    editor.chain().setMeta("addToHistory", false)
      .setContent(safeContent, { emitUpdate: false, errorOnInvalidContent: true })
      .command(({ tr }) => { tr.setDocAttribute("styles", safeContent.attrs?.styles || []); return true; }).run();
  } catch (error) { editor.destroy(); throw error; }
  return { editor, editorHost };
}

function mountEditor(content, session) {
  state.formatSample = null;
  const { editor, editorHost } = prepareEditor(content, session);
  search.matches = [];
  search.index = -1;
  state.editor?.destroy();
  $("office-editor").replaceChildren(editorHost);
  state.editor = editor;
}

function clearWorkspace() {
  imageControls.close();
  closeStyleDialog();
  state.formatSample = null;
  closeReuse();
  closePrint();
  clearReview();
  clearSuggestions();
  closeTableDialogs();
  closeParagraphDialog();
  closeCharacterDialog();
  $("table-tools").hidden = true;
  closeListDialog();
  $("table-info").textContent = "";
  $("table-message").textContent = "";
  closeComparison();
  cancelRestore();
  cancelHistoryRead(state.session);
  state.session = null;
  state.editor?.destroy();
  state.editor = null;
  updateFormatTransfer();
  updateListControls();
  updateStyleControls();
  resetSearch();
  $("office-editor").replaceChildren();
  $("document-title").value = "";
  $("document-history").replaceChildren();
  $("document-outline").replaceChildren();
  $("history-status").textContent = "";
  $("history-selected").textContent = ""; $("history-selected").hidden = true;
  $("history-more").hidden = true; $("history-retry").hidden = true;
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
  const scrollTop = $("documents-list").scrollTop;
  const focusedId = document.activeElement?.closest("[data-document-id]")?.dataset.documentId;
  $("documents-list").replaceChildren();
  state.documents.forEach((document) => {
    const button = node("button", undefined, "document-item");
    button.type = "button";
    button.dataset.documentId = document.object_id;
    button.setAttribute("aria-current", String(state.session?.objectId === document.object_id));
    const copy = node("div");
    copy.append(node("strong", document.title), node("small", dateLabel(document.updated_at_utc)));
    button.append(copy);
    button.addEventListener("click", () => openDocument(document.object_id));
    $("documents-list").append(button);
    if (focusedId === document.object_id) button.focus({ preventScroll: true });
  });
  $("documents-list").scrollTop = scrollTop;
  $("document-new").disabled = !state.canCreate;
  $("welcome-new").disabled = !state.canCreate;
  $("documents-refresh").disabled = state.listLoading;
  $("documents-list").setAttribute("aria-busy", String(state.listLoading));
  $("documents-clear").hidden = !$("documents-search").value;
  $("documents-load-more").hidden = !state.listCursor || Boolean(state.listRetry);
  $("documents-load-more").disabled = state.listLoading;
  $("documents-retry").hidden = !state.listRetry;
  $("documents-retry").disabled = state.listLoading;
  $("documents-retry").textContent = state.listRetry === "restart" ? "Liste neu laden" : "Erneut versuchen";
  updateReuseControls();
}

function documentListStatus(message, error = false) {
  $("documents-status").textContent = message;
  $("documents-status").classList.toggle("error", error);
}

function cancelDocumentListRequest() {
  state.listRequest += 1;
  clearTimeout(state.listTimer);
  state.listTimer = null;
  state.listController?.abort();
  state.listController = null;
  state.listLoading = false;
}

function clearDocumentList(clearQuery = false) {
  cancelDocumentListRequest();
  state.documents = []; state.canCreate = false;
  state.listCursor = null; state.listCursors = new Set(); state.listRetry = null;
  if (clearQuery) $("documents-search").value = "";
  state.listQuery = $("documents-search").value.trim();
  renderDocuments();
}

function validDocumentQuery(query) {
  return Array.from(query).length <= 200 && !/[\u0000-\u001f\u007f-\u009f]/u.test(query) &&
    !Array.from(query).some((character) => { const point = character.codePointAt(0); return point >= 0xd800 && point <= 0xdfff; });
}

function validatedDocumentPage(result, context, cursor) {
  if (result?.tenant_id !== context.tenantId || !Array.isArray(result.documents) || result.documents.length > 50 ||
      typeof result.can_create !== "boolean" || result.page_size !== 50 || typeof result.has_more !== "boolean" ||
      !(result.next_cursor === null || (typeof result.next_cursor === "string" && result.next_cursor.length > 0 && result.next_cursor.length <= 1024)) ||
      result.has_more !== (result.next_cursor !== null) || (result.has_more && !result.documents.length) ||
      (result.next_cursor && (result.next_cursor === cursor || state.listCursors.has(result.next_cursor)))) throw new ApiError(502, true);
  const identifiers = new Set();
  for (const entry of result.documents) {
    if (!entry || typeof entry.object_id !== "string" || !entry.object_id || identifiers.has(entry.object_id) ||
        typeof entry.title !== "string" || !entry.title || Array.from(entry.title).length > 200 ||
        typeof entry.current_version_id !== "string" || !entry.current_version_id || typeof entry.can_write !== "boolean" ||
        typeof entry.created_at_utc !== "string" || !Number.isFinite(Date.parse(entry.created_at_utc)) ||
        typeof entry.updated_at_utc !== "string" || !Number.isFinite(Date.parse(entry.updated_at_utc))) throw new ApiError(502, true);
    identifiers.add(entry.object_id);
  }
  return result;
}

function scheduleDocumentSearch(immediate = false) {
  cancelDocumentListRequest();
  state.documents = []; state.listCursor = null; state.listCursors = new Set(); state.listRetry = null;
  state.listQuery = $("documents-search").value.trim();
  if (!validDocumentQuery(state.listQuery)) {
    documentListStatus("Bitte verwenden Sie höchstens 200 Zeichen ohne Steuerzeichen für die Titelsuche.", true);
    renderDocuments();
    return;
  }
  if (immediate) { loadDocuments(); return; }
  state.listLoading = true;
  documentListStatus("Dokumente werden geladen …");
  renderDocuments();
  state.listTimer = setTimeout(() => loadDocuments(), 250);
}

async function loadDocuments({ append = false, revalidateSource = false } = {}) {
  if (append && (state.listLoading || !state.listCursor || state.listQuery !== $("documents-search").value.trim())) return;
  const query = $("documents-search").value.trim();
  if (!validDocumentQuery(query)) { scheduleDocumentSearch(); return; }
  const cursor = append ? state.listCursor : null;
  const initiator = document.activeElement;
  const restoreFocus = [$("documents-refresh"), $("documents-load-more"), $("documents-retry")].includes(initiator);
  const previousIds = new Set(state.documents.map((entry) => entry.object_id));
  let loaded = false;
  cancelDocumentListRequest();
  const epoch = state.epoch;
  const request = ++state.listRequest;
  const context = state.context;
  const controller = new AbortController();
  state.listController = controller;
  const current = () => state.epoch === epoch && state.context === context && state.listRequest === request &&
    state.listQuery === query && $("documents-search").value.trim() === query;
  state.listQuery = query;
  state.listRetry = null;
  if (!append) { state.documents = []; state.listCursor = null; state.listCursors = new Set(); }
  state.listLoading = true;
  documentListStatus(append ? "Weitere Dokumente werden geladen …" : "Dokumente werden geladen …");
  renderDocuments();
  const source = revalidateSource && state.session?.objectId && state.session.version ? {
    session: state.session, version: state.session.version, editor: state.editor,
  } : null;
  const sourceCurrent = () => source && sessionCurrent(source.session) && source.session.version === source.version && state.editor === source.editor;
  try {
    if (source) {
      try {
        const result = await api(`/v1/office/documents/${encodeURIComponent(source.session.objectId)}/content?version_id=${encodeURIComponent(source.version.version_id)}`,
          { signal: controller.signal }, context);
        if (!current()) return;
        if (sourceCurrent()) {
          try {
            const content = validatedContent(result, source.session.objectId, source.version.version_id);
            if (result.version.content_hash !== source.version.content_hash || result.version.title !== source.version.title ||
                typeof result.document.can_write !== "boolean") throw new ApiError(502);
            validateEditorDocument(source.editor.schema.nodeFromJSON(content));
          } catch { throw new ApiError(502, true); }
          source.session.canWrite = result.can_write && result.document.can_write;
          source.session.metadata = { ...source.session.metadata, can_write: result.document.can_write };
          updateEditorState();
        }
      } catch (error) {
        if (!current()) return;
        if (sourceCurrent()) throw error;
      }
    }
    const parameters = new URLSearchParams({ query, page_size: "50" });
    if (cursor) parameters.set("cursor", cursor);
    const result = await api(`/v1/office/documents?${parameters}`, { signal: controller.signal }, context);
    if (!current()) return;
    validatedDocumentPage(result, context, cursor);
    state.documents = append ? [...new Map([...state.documents, ...result.documents].map((entry) => [entry.object_id, entry])).values()] : result.documents;
    state.canCreate = result.can_create;
    state.listCursor = result.next_cursor;
    if (cursor) state.listCursors.add(cursor);
    loaded = true;
    documentListStatus(state.documents.length
      ? `${state.documents.length} Dokumente geladen.${result.has_more ? " Weitere verfügbar." : ""}`
      : query ? "Keine Dokumente für diese Suche." : "Noch keine freigegebenen Dokumente.");
  } catch (error) {
    if (!current()) return;
    if (denied(error) || (error instanceof ApiError && error.malformed)) {
      clearWorkspace();
      clearDocumentList();
      state.listRetry = "restart";
      documentListStatus(denied(error) ? "Dieses Dokument oder die Dokumentliste ist nicht mehr freigegeben." :
        "Die Antwort konnte nicht sicher zugeordnet werden. Bitte laden Sie die Liste erneut.", true);
      renderDocuments();
      return;
    }
    const invalidCursor = error instanceof ApiError && [400, 422].includes(error.status);
    if (invalidCursor) { state.documents = []; state.listCursor = null; state.listCursors = new Set(); }
    state.listRetry = invalidCursor ? "restart" : append ? "append" : revalidateSource ? "refresh" : "restart";
    documentListStatus(invalidCursor ? "Die Liste muss neu geladen werden. Ihr geöffnetes Dokument bleibt erhalten." :
      append ? "Weitere Dokumente konnten nicht geladen werden. Die bisherige Liste und Ihre Entwürfe bleiben erhalten." :
      "Dokumente sind gerade nicht erreichbar. Bitte versuchen Sie es erneut; Ihre Entwürfe bleiben erhalten.", true);
  } finally {
    if (current()) {
      state.listLoading = false;
      state.listController = null;
      renderDocuments();
      if (restoreFocus && (document.activeElement === document.body || document.activeElement === initiator)) {
        const firstNew = append && loaded ? Array.from($("documents-list").children).find((entry) =>
          entry.dataset.documentId && !previousIds.has(entry.dataset.documentId)) : null;
        const target = firstNew || (state.listRetry ? $("documents-retry") : append && state.listCursor ? $("documents-load-more") : $("documents-refresh"));
        target.focus();
      }
    }
  }
}

function confirmDiscard(scope = "all") {
  if (state.session?.saving || state.review?.saving || state.suggestions?.saving || state.suggestions?.settling) return Promise.resolve(false);
  const documentDraft = scope === "all" && (isDirty() || state.session?.uncertain);
  const reviewDraft = scope !== "suggestions" && hasReviewDraft();
  const suggestionDraft = scope !== "comments" && hasSuggestionDraft();
  if (!documentDraft && !reviewDraft && !suggestionDraft) return Promise.resolve(true);
  if (state.discardResolve) return Promise.resolve(false);
  $("discard-message").textContent = suggestionDraft
    ? `${documentDraft ? "Ihre Dokumentänderungen und " : "Ihre "}ungespeicherten Änderungsvorschläge gehen verloren.${state.suggestions?.uncertain ? " Eine noch nicht bestätigte Speicherung kann bereits erfolgt sein." : ""}`
    : reviewDraft
    ? `${documentDraft ? "Ihre Dokumentänderungen und " : "Ihre "}ungespeicherten Kommentarentwürfe gehen verloren.${state.review?.uncertain ? " Eine noch nicht bestätigte Kommentarspeicherung kann bereits erfolgt sein." : ""}`
    : "Ihre ungespeicherten Änderungen gehen verloren.";
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
  return { epoch: state.epoch, objectId, revision: 0, history: freshHistory(), canWrite: false,
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
  closeReuse();
  closePrint();
  clearReview();
  clearSuggestions();
  mountEditor(result.content, session);
  closeComparison();
  cancelRestore();
  cancelHistoryRead(session);
  session.history = freshHistory(); session.versions = [];
  $("document-history").replaceChildren();
  $("history-more").hidden = true; $("history-retry").hidden = true;
  $("history-selected").textContent = ""; $("history-selected").hidden = true;
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
    if (reviewPanelOpen()) loadReview();
    if (suggestionPanelOpen()) loadSuggestions();
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

async function showSave() {
  const session = state.session;
  if (!session || !state.editor || $("document-save").disabled) return;
  if (hasReviewDraft() || hasSuggestionDraft()) {
    if (!(await confirmDiscard("inspector")) || !sessionCurrent(session)) return;
    clearReview();
    clearSuggestions();
  }
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
    if (sessionCurrent(session) && reviewPanelOpen()) loadReview();
    if (sessionCurrent(session) && suggestionPanelOpen()) loadSuggestions();
  } catch (error) {
    if (!sessionCurrent(session)) return;
    $("save-dialog").close();
    if (denied(error)) {
      clearWorkspace();
      clearDocumentList();
      $("documents-status").textContent = "Der Zugriff wurde nicht bestätigt. Bitte laden Sie Ihre Dokumente erneut.";
      $("documents-status").classList.add("error");
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

function freshHistory() {
  return { request: 0, controller: null, loading: false, cursor: null, seenCursors: new Set(),
    headId: null, currentHeadId: null, retry: null, message: "", error: false };
}

function cancelHistoryRead(owner) {
  if (!owner?.history) return;
  const wasLoading = owner.history.loading;
  owner.history.request += 1;
  owner.history.controller?.abort();
  owner.history.controller = null;
  owner.history.loading = false;
  if (wasLoading) {
    owner.history.message = owner.versions.length ? historyMessage(owner) : "Bitte aktualisieren Sie die Versionsliste.";
    if (owner === state.session) renderHistory(owner);
  }
}

function historyMessage(owner) {
  return `${owner.versions.length} Fassungen geladen. ${historyCoverage(owner.versions, owner.history)}`.trim();
}

function renderHistory(session = state.session) {
  if (!session || !sessionCurrent(session)) return;
  const history = session.history;
  const focusedId = document.activeElement?.closest("[data-version-id]")?.dataset.versionId;
  const scrollTop = $("document-inspector").scrollTop;
  $("document-history").replaceChildren();
  [...session.versions].reverse().forEach((version) => {
    const button = node("button", undefined, "version-entry");
    button.type = "button";
    button.dataset.versionId = version.version_id;
    button.setAttribute("aria-current", String(version.version_id === session.version?.version_id));
    button.append(node("strong", versionLabel(version, session.versions, history.currentHeadId)),
      node("small", dateLabel(version.created_at_utc)), node("small", version.created_by));
    button.title = version.version_id;
    button.addEventListener("click", () => openDocument(session.objectId, version.version_id));
    $("document-history").append(button);
    if (focusedId === version.version_id) button.focus({ preventScroll: true });
  });
  $("history-status").textContent = history.message || (session.versions.length ? historyMessage(session) : "Versionen werden geladen …");
  $("history-status").classList.toggle("error", history.error);
  $("document-history").setAttribute("aria-busy", String(history.loading));
  const outside = session.version && session.versions.length && !session.versions.some((version) => version.version_id === session.version.version_id);
  $("history-selected").hidden = !outside;
  $("history-selected").textContent = outside ? `Geöffnet: ${dateLabel(session.version.created_at_utc)} · außerhalb der geladenen Versionsliste.` : "";
  $("history-refresh").disabled = Boolean(history.loading || session.loading || session.saving || session.restoring);
  $("history-more").hidden = !history.cursor || Boolean(history.retry);
  $("history-more").disabled = history.loading || session.saving || session.restoring;
  $("history-retry").hidden = !history.retry;
  $("history-retry").disabled = history.loading || session.saving || session.restoring;
  $("history-retry").textContent = history.retry === "restart" ? "Versionsliste neu laden" : "Erneut versuchen";
  $("document-inspector").scrollTop = scrollTop;
}

async function loadHistory({ append = false } = {}) {
  const session = state.session;
  if (!session?.objectId || session.loading || session.saving || session.restoring) {
    if (!session?.objectId) $("history-status").textContent = "Mit dem ersten Speichern beginnt die Versionsgeschichte.";
    return;
  }
  return loadVersionPage(session, append);
}

async function loadVersionPage(owner, append = false, comparison = false) {
  const session = comparison ? owner.session : owner;
  const history = owner.history;
  if (!sessionCurrent(session) || (append && (!history.cursor || history.loading)) || session.saving || session.restoring) return;
  cancelHistoryRead(owner);
  const request = ++history.request;
  const context = state.context;
  const current = () => sessionCurrent(session) && state.context === context && owner.history === history && history.request === request &&
    (!comparison || (state.compare === owner && $("compare-dialog").open && session.revision === owner.revision));
  const cursor = append ? history.cursor : null;
  const controller = new AbortController();
  history.controller = controller; history.loading = true; history.retry = null; history.error = false;
  history.message = append ? "Ältere Fassungen werden geladen …" : "Versionsliste wird aktualisiert …";
  if (comparison) renderComparisonHistory(owner); else renderHistory(session);
  try {
    const parameters = new URLSearchParams({ page_size: "50" });
    if (cursor) parameters.set("cursor", cursor);
    const result = await api(`/v1/office/documents/${encodeURIComponent(session.objectId)}/versions?${parameters}`,
      { signal: controller.signal }, context);
    if (!current()) return;
    const versions = validatedHistory(result, session.objectId, owner, append);
    if (comparison) rememberComparisonSelection(owner, versions);
    owner.versions = versions;
    history.headId = result.history_head_version_id; history.currentHeadId = result.current_version_id;
    history.cursor = result.next_cursor;
    if (!append) history.seenCursors = new Set();
    if (cursor) history.seenCursors.add(cursor);
    history.message = historyMessage(owner);
    if (comparison) {
      copyComparisonHistory(owner);
      if (!owner.result) $("compare-status").textContent = "Wählen Sie zwei Fassungen und laden Sie den Vergleich.";
    }
  } catch (error) {
    if (!current()) return;
    if (denied(error) || (error instanceof ApiError && error.malformed)) { officeAccessDenied(); return; }
    const restart = error instanceof ApiError && [400, 422].includes(error.status);
    if (restart) { history.cursor = null; history.seenCursors = new Set(); }
    history.retry = restart || !append ? "restart" : "append";
    history.error = true;
    history.message = restart
      ? "Die Versionsliste muss neu geladen werden. Ihre Auswahl und Entwürfe bleiben erhalten."
      : "Versionen konnten nicht geladen werden. Ihre Auswahl und Entwürfe bleiben erhalten. Bitte versuchen Sie es erneut.";
  } finally {
    if (current()) {
      history.loading = false; history.controller = null;
      if (comparison) renderComparisonHistory(owner); else renderHistory(session);
    }
  }
}

function sourceWriteAccess(objectId) {
  return Boolean(objectId && state.session?.objectId === objectId && state.session.canWrite && state.session.metadata?.can_write === true);
}

function officeAccessDenied() {
  clearWorkspace();
  clearDocumentList();
  $("documents-status").textContent = "Dieses Dokument ist nicht mehr freigegeben.";
  $("documents-status").classList.add("error");
}

function validatedHistory(result, objectId, owner, append) {
  if (result?.tenant_id !== state.context.tenantId || result.object_id !== objectId || result.page_size !== 50 ||
      !Array.isArray(result.versions) || !result.versions.length || result.versions.length > 50 ||
      typeof result.history_head_version_id !== "string" || !result.history_head_version_id ||
      typeof result.current_version_id !== "string" || !result.current_version_id || typeof result.has_more !== "boolean" ||
      !(result.next_cursor === null || (typeof result.next_cursor === "string" && result.next_cursor.length > 0 && result.next_cursor.length <= 1024)) ||
      result.has_more !== (result.next_cursor !== null) ||
      (append && (result.history_head_version_id !== owner.history.headId || result.versions[0]?.version_id !== owner.versions[0]?.previous_version_id)) ||
      (!append && result.versions[0]?.version_id !== result.history_head_version_id) ||
      (result.next_cursor && append && (result.next_cursor === owner.history.cursor || owner.history.seenCursors.has(result.next_cursor)))) throw new ApiError(502, true);
  const ids = new Set(append ? owner.versions.map((version) => version.version_id) : []);
  result.versions.forEach((version, index) => {
    if (!version || typeof version.version_id !== "string" || !version.version_id || typeof version.title !== "string" ||
        typeof version.created_at_utc !== "string" || !Number.isFinite(Date.parse(version.created_at_utc)) || typeof version.created_by !== "string" ||
        typeof version.content_hash !== "string" || typeof version.source_write_receipt_hash !== "string" ||
        !(version.previous_version_id === null || (typeof version.previous_version_id === "string" && version.previous_version_id)) ||
        ids.has(version.version_id) || (index > 0 && result.versions[index - 1].previous_version_id !== version.version_id)) throw new ApiError(502, true);
    ids.add(version.version_id);
  });
  const oldest = result.versions[result.versions.length - 1];
  if (result.has_more !== (oldest.previous_version_id !== null) || ids.has(oldest.previous_version_id)) throw new ApiError(502, true);
  return [...result.versions].reverse().concat(append ? owner.versions : []);
}

function versionLabel(version, versions, currentHeadId = versions[versions.length - 1]?.version_id) {
  const index = versions.findIndex((entry) => entry.version_id === version.version_id);
  if (index < 0) return `Ausgewählte Fassung · ${dateLabel(version.created_at_utc)} · außerhalb der geladenen Liste`;
  const distance = versions.length - 1 - index;
  const newer = currentHeadId !== versions[versions.length - 1]?.version_id;
  const label = distance === 0 ? newer ? "Geladener Stand" : "Aktuelle Fassung" : `${distance} ${distance === 1 ? "Fassung" : "Fassungen"} zuvor${newer ? " · geladener Stand" : ""}`;
  return `${label} · ${dateLabel(version.created_at_utc)}`;
}

function historyCoverage(versions, history = null) {
  const older = versions.length && versions[0].previous_version_id !== null ? "Weitere ältere Fassungen sind nicht geladen." : "";
  const newer = history?.headId && history.headId !== history.currentHeadId ? "Eine neuere Fassung ist verfügbar. Aktualisieren Sie die Versionsliste." : "";
  return `${older} ${newer}`.trim();
}

function validatedContent(result, objectId, versionId = null) {
  if (!contentMatches(result, objectId, versionId) || typeof result.version.title !== "string") throw new ApiError(502);
  const content = normalizedDocument(result.content);
  if (!state.editor) throw new ApiError(502);
  state.editor.schema.nodeFromJSON(content).check();
  return content;
}

function reuseSourceReady() {
  const session = state.session;
  const review = state.review;
  const suggestions = state.suggestions;
  return Boolean(session && sessionCurrent(session) && state.editor && session.objectId && session.version?.version_id &&
    typeof session.version.title === "string" && typeof session.version.content_hash === "string" && session.version.content_hash &&
    !session.loading && !session.saving && !session.restoring && !session.uncertain && !session.conflict &&
    !review?.loading && !review?.pendingReads && !review?.saving && !review?.settling && !review?.uncertain &&
    !suggestions?.loading && !suggestions?.pendingReads && !suggestionLocksDocument());
}

function reuseCurrent(reuse) {
  return Boolean(reuse && state.reuse === reuse && $("reuse-dialog").open && reuseSourceReady() &&
    reuse.context === state.context && sessionCurrent(reuse.session) && state.editor === reuse.editor &&
    reuse.session.revision === reuse.revision && reuse.session.objectId === reuse.objectId &&
    reuse.session.version?.version_id === reuse.versionId &&
    state.review === reuse.review && state.review?.composer === reuse.reviewComposer &&
    state.review?.composer?.revision === reuse.reviewRevision &&
    state.suggestions === reuse.suggestions && state.suggestions?.composer === reuse.suggestionComposer &&
    state.suggestions?.composer?.revision === reuse.suggestionRevision);
}

function closeReuse(returnFocus = false) {
  const reuse = state.reuse;
  state.reuse = null;
  reuse?.controller?.abort();
  if (reuse?.discardResolve && state.discardResolve === reuse.discardResolve) settleDiscard(false);
  $("reuse-dialog").close();
  $("reuse-title").value = "";
  $("reuse-title").disabled = false;
  $("reuse-title").setCustomValidity("");
  $("reuse-source").textContent = "";
  $("reuse-status").textContent = "";
  $("reuse-submit").disabled = true;
  $("document-reuse").disabled = !state.canCreate || !reuseSourceReady();
  if (returnFocus && reuse?.session === state.session && !$("document-reuse").disabled) $("document-reuse").focus();
}

function updateReuseControls() {
  $("document-reuse").disabled = !state.canCreate || !reuseSourceReady() || Boolean(state.reuse?.busy);
  const reuse = state.reuse;
  if (!reuse) return;
  if (!reuseCurrent(reuse)) { closeReuse(); return; }
  const title = $("reuse-title").value.trim();
  $("reuse-title").disabled = reuse.busy;
  $("reuse-title").setCustomValidity(title && !validReuseTitle(title) ? "Bitte verwenden Sie höchstens 200 Zeichen ohne Steuerzeichen." : "");
  $("reuse-submit").disabled = reuse.busy || !validReuseTitle(title);
}

function validReuseTitle(title) {
  return Boolean(title && title.length <= 200 && Array.from(title).every((character) => {
    const code = character.codePointAt(0);
    return code >= 32 && !(code >= 0xd800 && code <= 0xdfff);
  }));
}

function reuseTitle(title) {
  let result = "Kopie von ";
  for (const character of title) {
    if (result.length + character.length > 200) break;
    result += character;
  }
  return result.trim();
}

function openReuse() {
  if (!state.canCreate || !reuseSourceReady() || document.querySelector("dialog[open]")) return;
  const session = state.session;
  state.reuse = { session, editor: state.editor, context: state.context, revision: session.revision,
    objectId: session.objectId, versionId: session.version.version_id, contentHash: session.version.content_hash,
    sourceTitle: session.version.title, review: state.review, reviewComposer: state.review?.composer,
    reviewRevision: state.review?.composer?.revision, suggestions: state.suggestions,
    suggestionComposer: state.suggestions?.composer, suggestionRevision: state.suggestions?.composer?.revision,
    request: 0, controller: null, busy: false, discardResolve: null };
  $("reuse-title").value = reuseTitle(session.version.title);
  $("reuse-source").textContent = `${session.version.title}\n${session.historical ? "Frühere gespeicherte Fassung" : "Geöffnete gespeicherte Fassung"} · ${dateLabel(session.version.created_at_utc)}`;
  $("reuse-status").textContent = "Die gespeicherte Fassung und Ihr Erstellrecht werden vor der Übernahme erneut geprüft.";
  $("reuse-dialog").showModal();
  updateReuseControls();
  $("reuse-title").select();
}

async function submitReuse(event) {
  event.preventDefault();
  const reuse = state.reuse;
  if (!reuseCurrent(reuse) || reuse.busy || !$("reuse-form").reportValidity()) return;
  const title = $("reuse-title").value.trim();
  if (!validReuseTitle(title)) return;
  const request = ++reuse.request;
  const current = () => reuseCurrent(reuse) && reuse.request === request && $("reuse-title").value.trim() === title;
  reuse.busy = true;
  reuse.controller = new AbortController();
  $("reuse-status").textContent = "Übernahme wird vorbereitet …";
  updateReuseControls();
  let prepared = null;
  try {
    // Consent does not discard anything. Authorization is read only after the
    // user has decided, and the original workspace survives every failure.
    const confirmation = confirmDiscard();
    reuse.discardResolve = state.discardResolve;
    const confirmed = await confirmation;
    if (state.reuse === reuse && reuse.request === request) reuse.discardResolve = null;
    if (!current()) return;
    if (!confirmed) { $("reuse-status").textContent = "Übernahme abgebrochen. Ihr bisheriger Entwurf bleibt erhalten."; return; }
    $("reuse-status").textContent = "Gespeicherte Fassung und Erstellrecht werden geprüft …";
    const result = await api(`/v1/office/documents/${encodeURIComponent(reuse.objectId)}/content?version_id=${encodeURIComponent(reuse.versionId)}`,
      { signal: reuse.controller.signal }, reuse.context);
    if (!current()) return;
    if (result?.tenant_id !== reuse.context.tenantId || result.version?.content_hash !== reuse.contentHash ||
        result.version?.title !== reuse.sourceTitle) throw new ApiError(502);
    const content = validatedContent(result, reuse.objectId, reuse.versionId);
    validateEditorDocument(state.editor.schema.nodeFromJSON(content));
    const listing = await api("/v1/office/documents", { signal: reuse.controller.signal }, reuse.context);
    if (!current()) return;
    if (listing?.tenant_id !== reuse.context.tenantId || typeof listing.can_create !== "boolean" ||
        !Array.isArray(listing.documents)) throw new ApiError(502);
    // The listing is bounded. Exact source authorization comes from content;
    // source presence in this page, source write access and head equality do not.
    if (listing.can_create !== true) {
      state.canCreate = false;
      renderDocuments();
      $("reuse-status").textContent = "Sie dürfen derzeit kein neues Dokument anlegen. Ihr bisheriger Entwurf bleibt erhalten.";
      return;
    }
    const replacement = freshSession();
    replacement.canWrite = true;
    prepared = prepareEditor(content, replacement);
    if (!current()) return;
    clearWorkspace();
    state.canCreate = true;
    state.session = replacement;
    state.editor = prepared.editor;
    $("office-editor").replaceChildren(prepared.editorHost);
    prepared = null;
    $("office-welcome").hidden = true;
    $("document-workspace").hidden = false;
    $("document-title").value = title;
    $("document-mode").textContent = "Neuer Entwurf";
    $("document-version").textContent = "Noch nicht gespeichert";
    $("document-version").title = "";
    $("history-status").textContent = "Mit dem ersten Speichern beginnt die Versionsgeschichte.";
    replacement.loading = false;
    $("office-shell").classList.remove("documents-open");
    $("documents-toggle").setAttribute("aria-expanded", "false");
    refreshDocumentTools();
    renderDocuments();
    notice("Gespeicherte Fassung als neues, ungespeichertes Dokument übernommen.");
    state.editor.view.dispatch(state.editor.state.tr.setSelection(Selection.atStart(state.editor.state.doc)));
    focusEditor();
  } catch (error) {
    if (!current()) return;
    if (denied(error)) { officeAccessDenied(); return; }
    $("reuse-status").textContent = "Die Fassung konnte nicht übernommen werden. Bitte versuchen Sie es erneut; Ihr bisheriger Entwurf bleibt erhalten.";
  } finally {
    prepared?.editor.destroy();
    if (current()) { reuse.busy = false; updateReuseControls(); }
  }
}

function printAllowed() {
  const session = state.session;
  return Boolean(session && sessionCurrent(session) && state.editor && session.objectId && session.version?.version_id &&
    typeof session.version.content_hash === "string" && session.version.content_hash &&
    !session.loading && !session.saving && !session.restoring && !session.uncertain && !session.conflict && !isDirty() &&
    !state.review?.saving && !state.review?.settling && !state.review?.uncertain && !suggestionLocksDocument());
}

function printCurrent(print) {
  return Boolean(print && state.print === print && ($("print-dialog").open || print.dialogTransition) && print.context === state.context &&
    sessionCurrent(print.session) && print.session.revision === print.revision &&
    print.session.objectId === print.objectId && print.session.version?.version_id === print.versionId && printAllowed());
}

function clearPreparedPrint(owner = null) {
  if (owner && state.preparedPrint !== owner) return;
  state.preparedPrint = null;
  document.body.classList.remove("office-print-ready");
  $("office-print-root").replaceChildren();
  $("office-print-root").className = "";
}

function closePrint(returnFocus = false) {
  const print = state.print;
  state.print = null;
  print?.controller?.abort();
  for (const url of print?.images?.values() || []) URL.revokeObjectURL(url);
  if (print) print.content = null;
  clearPreparedPrint();
  $("print-preview").replaceChildren();
  $("print-preview").className = "paper-a4 orientation-portrait";
  $("print-version").textContent = "";
  $("print-status").textContent = "";
  $("print-paper").value = "a4";
  $("print-orientation").value = "portrait";
  $("print-submit").disabled = true;
  $("print-dialog").close();
  if (returnFocus && print?.session === state.session && !$("document-print").disabled) $("document-print").focus();
}

function printFormat() {
  const paper = $("print-paper").value === "letter" ? "letter" : "a4";
  const orientation = $("print-orientation").value === "landscape" ? "landscape" : "portrait";
  return `paper-${paper} orientation-${orientation}`;
}

function updatePrintControls() {
  const print = state.print;
  const current = printCurrent(print);
  const busy = Boolean(print?.loading || print?.printing);
  $("print-refresh").disabled = !current || busy;
  $("print-paper").disabled = !current || busy;
  $("print-orientation").disabled = !current || busy;
  $("print-submit").disabled = !current || busy || !print.content;
  $("print-preview").className = printFormat();
}

function setPrintModal(print, modal) {
  if (!printCurrent(print)) return;
  // A modal dialog makes its sibling print root inert, which removes native
  // content semantics from tagged PDFs. Keep the same visible preview open
  // nonmodally only for the browser's print operation.
  print.dialogTransition = true;
  try {
    $("print-dialog").close();
    if (!printCurrent(print)) return;
    if (modal) $("print-dialog").showModal();
    else $("print-dialog").show();
  } finally { print.dialogTransition = false; }
}

function validatePrintContent(result, print) {
  if (result?.tenant_id !== print.context.tenantId || result.version?.content_hash !== print.contentHash ||
    result.version?.title !== print.title) throw new ApiError(502);
  const content = validatedContent(result, print.objectId, print.versionId);
  validateEditorDocument(state.editor.schema.nodeFromJSON(content));
  return content;
}

async function loadPrintContent(print = state.print, finalAction = false) {
  if (!printCurrent(print) || print.loading || print.printing) return;
  const request = ++print.request;
  print.controller?.abort();
  print.controller = new AbortController();
  print.loading = true;
  print.content = null;
  for (const url of print.images?.values() || []) URL.revokeObjectURL(url);
  print.images = new Map();
  clearPreparedPrint();
  $("print-preview").replaceChildren();
  $("print-version").textContent = "";
  $("print-status").textContent = finalAction ? "Gespeicherte Fassung und Freigabe werden erneut geprüft …" : "Druckansicht wird geladen …";
  updatePrintControls();
  const current = () => printCurrent(print) && print.request === request;
  try {
    const result = await api(`/v1/office/documents/${encodeURIComponent(print.objectId)}/content?version_id=${encodeURIComponent(print.versionId)}`,
      { signal: print.controller.signal }, print.context);
    if (!current()) return;
    const content = validatePrintContent(result, print);
    const images = await loadOfficePrintImages(content, print.context, print.controller.signal);
    if (!current()) { for (const url of images.values()) URL.revokeObjectURL(url); return; }
    print.images = images;
    const preview = renderOfficePrintDocument(content, result.version.title, document, images);
    if (!current()) return;
    print.content = content;
    $("print-preview").replaceChildren(preview);
    $("print-version").textContent = `${result.version.title} · ${dateLabel(result.version.created_at_utc)} · Version ${print.versionId}`;
    $("print-status").textContent = "Druckansicht bereit. Vor dem Drucken wird diese Fassung erneut geprüft.";
    if (finalAction) {
      // The print surface is made from this fresh response, never from the live
      // editor, the preview DOM, or an older cached authorization result.
      const root = $("office-print-root");
      root.replaceChildren(renderOfficePrintDocument(content, result.version.title, document, images));
      await Promise.all([...root.querySelectorAll("img")].map((image) => image.decode()));
      if (!current()) return;
      root.className = printFormat();
      print.printing = true;
      state.preparedPrint = print;
      document.body.classList.add("office-print-ready");
      updatePrintControls();
      $("print-status").textContent = "Der Browser steuert Druck und PDF-Speicherung. Schließen Sie anschließend den Browserdialog.";
      try {
        setPrintModal(print, false);
        if (!current()) return;
        await window.print();
      } finally {
        clearPreparedPrint(print);
        if (current()) setPrintModal(print, true);
      }
      if (!current()) return;
      $("print-status").textContent = "Druckansicht bereit. Ob gedruckt oder eine PDF gespeichert wurde, bestimmt der Browser.";
    }
  } catch (error) {
    if (!current()) return;
    clearPreparedPrint(print);
    print.content = null;
    $("print-preview").replaceChildren();
    $("print-version").textContent = "";
    if (denied(error)) { officeAccessDenied(); return; }
    $("print-status").textContent = "Die Druckansicht ist gerade nicht verfügbar. Bitte erneut laden.";
  } finally {
    if (current()) {
      print.loading = false; print.printing = false;
      updatePrintControls();
    }
  }
}

function openPrint() {
  if ($("print-dialog").open) return;
  if (!printAllowed() || document.querySelector("dialog[open]")) {
    if (state.session) notice("Drucken ist für eine gespeicherte Fassung ohne ungespeicherte oder noch unbestätigte Änderungen verfügbar.");
    return;
  }
  const session = state.session;
  const print = { session, context: state.context, revision: session.revision, objectId: session.objectId,
    versionId: session.version.version_id, contentHash: session.version.content_hash, title: session.version.title,
    request: 0, content: null, controller: null, loading: false, printing: false, dialogTransition: false };
  state.print = print;
  $("print-dialog").showModal();
  loadPrintContent(print);
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
  cancelHistoryRead(comparison);
  if (state.restore?.comparison === comparison) cancelRestore();
  clearComparisonResult(comparison);
  if (comparison) { comparison.versions = []; comparison.pinned = []; }
  $("compare-left").replaceChildren(); $("compare-right").replaceChildren();
  $("compare-left").disabled = true; $("compare-right").disabled = true;
  $("compare-status").textContent = "";
  $("compare-history-status").textContent = "";
  $("compare-history-more").hidden = true; $("compare-history-retry").hidden = true;
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
  cancelHistoryRead(session);
  const comparison = { session, revision: session.revision, context: state.context, request: 0,
    controller: new AbortController(), versions: [], history: freshHistory(), pinned: [], selection: null,
    loadingContent: false, result: null, left: null, right: null, page: 0 };
  state.compare = comparison;
  clearComparisonResult(comparison);
  $("compare-status").textContent = "Wählen Sie zwei Fassungen und laden Sie den Vergleich.";
  $("compare-dialog").showModal();
  await loadVersionPage(comparison, false, true);
}

function comparisonVersions(comparison) {
  return [...comparison.versions, ...comparison.pinned.filter((version) =>
    !comparison.versions.some((entry) => entry.version_id === version.version_id))];
}

function sameSavedVersion(left, right) {
  return ["version_id", "previous_version_id", "title", "created_at_utc", "created_by", "content_hash", "source_write_receipt_hash"]
    .every((key) => left?.[key] === right?.[key]);
}

function rememberComparisonSelection(comparison, versions) {
  const previous = comparisonVersions(comparison);
  const selected = comparison.selection || {
    left: comparison.session.historical ? comparison.session.version.version_id : versions[Math.max(0, versions.length - 2)].version_id,
    right: versions[versions.length - 1].version_id,
  };
  comparison.pinned = [...new Set([selected.left, selected.right])].flatMap((id) => {
    const known = previous.find((version) => version.version_id === id) ||
      (comparison.session.version.version_id === id ? comparison.session.version : null);
    const loaded = versions.find((version) => version.version_id === id);
    if (known && loaded && !sameSavedVersion(known, loaded)) throw new ApiError(502, true);
    if (!loaded && !known) throw new ApiError(502, true);
    return loaded ? [] : [known];
  });
  comparison.selection = selected;
}

function copyComparisonHistory(comparison) {
  const session = comparison.session;
  cancelHistoryRead(session);
  session.versions = [...comparison.versions];
  session.history = { ...comparison.history, request: 0, controller: null, loading: false,
    seenCursors: new Set(comparison.history.seenCursors) };
  renderHistory(session);
}

function renderComparisonHistory(comparison) {
  if (!comparisonCurrent(comparison)) return;
  const history = comparison.history;
  const available = comparisonVersions(comparison);
  const scrollTop = $("compare-dialog").querySelector(".compare-body").scrollTop;
  ["left", "right"].forEach((side) => {
    const select = $(`compare-${side}`);
    select.replaceChildren(...available.map((version) => {
      const option = node("option", versionLabel(version, comparison.versions, history.currentHeadId));
      option.value = version.version_id;
      return option;
    }));
    if (comparison.selection) select.value = comparison.selection[side];
    select.disabled = !available.length || Boolean(state.restore);
  });
  $("compare-history-status").textContent = history.message || historyMessage(comparison);
  $("compare-history-status").classList.toggle("error", history.error);
  $("compare-history-refresh").disabled = history.loading || Boolean(state.restore);
  $("compare-history-more").hidden = !history.cursor || Boolean(history.retry);
  $("compare-history-more").disabled = history.loading || Boolean(state.restore);
  $("compare-history-retry").hidden = !history.retry;
  $("compare-history-retry").disabled = history.loading || Boolean(state.restore);
  $("compare-history-retry").textContent = history.retry === "restart" ? "Versionsliste neu laden" : "Erneut versuchen";
  $("compare-load").disabled = !available.length || comparison.loadingContent || Boolean(state.restore);
  if (comparison.result) renderComparison(comparison);
  $("compare-dialog").querySelector(".compare-body").scrollTop = scrollTop;
}

function comparisonSelectionChanged() {
  const comparison = state.compare;
  if (!comparison) return;
  comparison.request += 1;
  comparison.controller.abort();
  comparison.controller = new AbortController();
  comparison.loadingContent = false;
  comparison.selection = { left: $("compare-left").value, right: $("compare-right").value };
  comparison.pinned = comparison.pinned.filter((version) => Object.values(comparison.selection).includes(version.version_id));
  cancelRestore();
  clearComparisonResult(comparison);
  $("compare-status").textContent = "Auswahl geändert. Laden Sie den Vergleich erneut.";
  $("compare-load").disabled = false;
  renderComparisonHistory(comparison);
  updateEditorState();
}

async function loadComparison() {
  const comparison = state.compare;
  if (!comparison || state.restore) return;
  if (!comparison.versions.length) return;
  const leftId = $("compare-left").value;
  const rightId = $("compare-right").value;
  const selected = [leftId, rightId].map((id) => comparisonVersions(comparison).find((entry) => entry.version_id === id));
  if (selected.some((version) => !version)) return;
  comparison.controller.abort();
  comparison.controller = new AbortController();
  const request = ++comparison.request;
  comparison.loadingContent = true;
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
    if (!sameSavedVersion(left.version, selected[0]) || !sameSavedVersion(right.version, selected[1])) throw new ApiError(502, true);
    comparison.result = compareOfficeDocuments(before, after);
    comparison.left = left; comparison.right = right;
    renderComparison(comparison);
    $("compare-status").textContent = "Vergleich geladen. Gespeicherte Fassungen bleiben unverändert.";
  } catch (error) {
    if (!comparisonCurrent(comparison, request)) return;
    clearComparisonResult(comparison);
    if (denied(error) || (error instanceof ApiError && error.malformed)) { officeAccessDenied(); return; }
    $("compare-status").textContent = "Vergleich konnte nicht geladen werden. Bitte versuchen Sie es erneut.";
  } finally {
    if (comparisonCurrent(comparison, request)) { comparison.loadingContent = false; renderComparisonHistory(comparison); }
  }
}

function renderComparison(comparison) {
  if (!comparisonCurrent(comparison) || !comparison.result) return;
  const { rows, counts, simplified } = comparison.result;
  const titleChanged = comparison.left.version.title !== comparison.right.version.title;
  $("compare-summary").textContent = `${counts.changed} geändert · ${counts.added} hinzugefügt · ${counts.removed} entfernt · ${counts.equal} unverändert.${titleChanged ? " Titel geändert." : " Titel unverändert."}${simplified ? " Große Fassung: vereinfachter Blockvergleich; alle Inhalte sind enthalten." : ""} ${historyCoverage(comparison.versions, comparison.history)}`.trim();
  $("compare-results").replaceChildren();
  const titleRow = node("section", undefined, `compare-row ${titleChanged ? "changed" : "equal"}`);
  titleRow.append(node("h3", titleChanged ? "Titel geändert" : "Titel unverändert"));
  const titles = node("div", undefined, "compare-columns");
  [comparison.left, comparison.right].forEach((entry, index) => {
    const side = node("div", undefined, "compare-side");
    side.append(node("h4", `${index ? "Rechts" : "Links"} · ${versionLabel(entry.version, comparison.versions, comparison.history.currentHeadId)}`),
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
  $("compare-restore").disabled = Boolean(state.restore) || comparison.left.version.version_id === comparison.history.currentHeadId ||
    !sourceWriteAccess(comparison.session.objectId);
}

async function restoreVersion(versionId, comparison = null) {
  const session = state.session;
  if (!session?.objectId || session.saving || session.loading || state.restore || !sourceWriteAccess(session.objectId)) return;
  const restore = { session, revision: session.revision, context: state.context, comparison,
    comparisonRequest: comparison?.request, versionId, controller: new AbortController() };
  state.restore = restore;
  const current = () => state.restore === restore && sessionCurrent(session) && session.revision === restore.revision &&
    (!comparison || (comparisonCurrent(comparison, restore.comparisonRequest) && $("compare-left").value === versionId));
  try {
    if (!(await confirmDiscard()) || !current()) return;
    session.restoring = true;
    cancelHistoryRead(session);
    cancelHistoryRead(comparison);
    updateEditorState();
    if (comparison) renderComparisonHistory(comparison);
    if (comparison) {
      clearComparisonResult(comparison);
      $("compare-status").textContent = "Fassung und aktuelle Berechtigung werden geprüft …";
      $("compare-load").disabled = true;
    } else notice("Fassung und aktuelle Berechtigung werden geprüft …");
    const base = `/v1/office/documents/${encodeURIComponent(session.objectId)}/content`;
    const [historical, head] = await Promise.all([
      api(`${base}?version_id=${encodeURIComponent(versionId)}`, { signal: restore.controller.signal }, restore.context),
      api(base, { signal: restore.controller.signal }, restore.context),
    ]);
    if (!current()) return;
    const historicContent = validatedContent(historical, session.objectId, versionId);
    const currentContent = validatedContent(head, session.objectId);
    if (head.can_write !== true || head.document.can_write !== true) throw new ApiError(403);
    if (historical.version.version_id === head.version.version_id) throw new ApiError(409);
    const nativeCurrentContent = normalizedDocument(state.editor.schema.nodeFromJSON(currentContent).toJSON());
    const baseline = JSON.stringify({ title: head.version.title, document: nativeCurrentContent });
    const replacement = freshSession(session.objectId);
    replacement.metadata = head.document; replacement.version = head.version; replacement.canWrite = true;
    replacement.baseline = baseline;
    mountEditor(historicContent, replacement);
    clearReview();
    clearSuggestions();
    closeComparison();
    cancelRestore();
    state.session = replacement;
    $("document-title").value = historical.version.title;
    replacement.loading = false;
    $("document-mode").textContent = "Entwurf aus früherer Fassung";
    $("document-version").textContent = `Basis · ${dateLabel(head.version.created_at_utc)}`;
    $("document-version").title = head.version.version_id;
    $("document-history").replaceChildren();
    $("history-more").hidden = true; $("history-retry").hidden = true;
    $("history-selected").textContent = ""; $("history-selected").hidden = true;
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
      if (comparison && comparisonCurrent(comparison)) renderComparisonHistory(comparison);
    }
  }
}

const reviewKey = new PluginKey("officeReview");
const reviewOperations = new Set(["create", "reply", "resolve", "reopen"]);
const ReviewHighlight = Extension.create({
  name: "officeReview",
  addProseMirrorPlugins() {
    return [new Plugin({ key: reviewKey, props: { decorations(editorState) {
      const range = state.review?.highlight;
      return range && range.to <= editorState.doc.content.size
        ? DecorationSet.create(editorState.doc, [Decoration.inline(range.from, range.to, { class: "review-anchor-highlight" })])
        : DecorationSet.empty;
    } } })];
  },
});

function reviewCurrent(review) {
  return Boolean(review && state.review === review && sessionCurrent(review.session) &&
    review.versionId === state.session.version?.version_id && review.context === state.context);
}
function reviewPanelOpen() {
  return $("comments-tab").getAttribute("aria-selected") === "true" &&
    !$("office-shell").classList.contains("inspector-hidden") && !$("office-shell").classList.contains("focus-mode");
}
function hasReviewDraft() { return Boolean(state.review?.uncertain || state.review?.composer?.body.trim()); }
function reviewBase(review) { return `/v1/office/documents/${encodeURIComponent(review.session.objectId)}/review-threads`; }
function reviewIdentity(result, review) {
  return result?.tenant_id === review.context.tenantId && result.object_id === review.session.objectId &&
    result.rag_indexing_allowed === false && result.search_indexing_allowed === false;
}
function validReviewThread(thread, review) {
  return thread && typeof thread.thread_id === "string" && thread.anchor_version_id === review.versionId &&
    Number.isInteger(thread.revision) && thread.revision > 0 && ["open", "resolved"].includes(thread.status) &&
    typeof thread.created_by === "string" && typeof thread.created_at_utc === "string" &&
    typeof thread.can_comment === "boolean" && typeof thread.can_resolve === "boolean" &&
    (thread.anchor === null || (Number.isInteger(thread.anchor?.from) && Number.isInteger(thread.anchor?.to) &&
      thread.anchor.from >= 0 && thread.anchor.to > thread.anchor.from));
}
function validReviewEvent(event) {
  return event && typeof event.event_id === "string" && Number.isInteger(event.revision) && event.revision > 0 &&
    reviewOperations.has(event.operation) && typeof event.created_by === "string" && typeof event.created_at_utc === "string" &&
    (["create", "reply"].includes(event.operation) ? typeof event.body === "string" && Array.from(event.body).length <= 4000 : event.body === null);
}
function clearReviewHighlight() {
  if (!state.review?.highlight) return;
  state.review.highlight = null;
  state.editor?.view.dispatch(state.editor.state.tr.setMeta(reviewKey, true));
}
function closeReviewConfirmation() {
  $("comment-confirm-dialog").close();
  $("comment-confirm-dialog").querySelectorAll("button,input").forEach((control) => { control.disabled = false; });
  $("comment-confirm-checkbox").checked = false;
  $("comment-confirm-submit").disabled = true;
  $("comment-confirm-summary").textContent = "";
  $("comment-confirm-body").textContent = "";
  $("comment-confirm-anchor").textContent = "";
  $("comment-confirm-message").textContent = "";
}
function clearReview() {
  const review = state.review;
  clearReviewHighlight();
  state.review = null;
  review?.controller.abort();
  closeReviewConfirmation();
  $("comments-list").replaceChildren();
  $("comments-status").textContent = "";
  $("comments-version").textContent = "";
  $("comments-hint").textContent = "";
  $("comments-more").hidden = true;
  $("comment-body").value = "";
  $("comment-anchor").textContent = "";
  $("comment-body-count").textContent = "";
  $("comment-composer").hidden = true;
  $("comment-new").disabled = true;
  $("comment-selection").disabled = true;
}
function reviewReadFailure(error, review) {
  if (!reviewCurrent(review)) return;
  if (denied(error)) { officeAccessDenied(); return; }
  $("comments-status").textContent = "Kommentare sind gerade nicht erreichbar. Ihr Kommentarentwurf bleibt erhalten. Bitte erneut aktualisieren.";
}
function reviewBusy(review = state.review) {
  return !reviewCurrent(review) || review.saving || review.settling || review.session.loading || review.session.saving ||
    review.session.restoring || review.session.uncertain;
}
function canCreateReview(review = state.review) {
  return !reviewBusy(review) && !review.uncertain && !review.loading && review.canCreate &&
    !review.session.historical && !isDirty() && review.currentVersionId === review.versionId;
}
function selectedReviewAnchor() {
  const editor = state.editor;
  if (!editor) return null;
  const { from, to, $from, $to, empty } = editor.state.selection;
  if (empty || !($from.parent.isTextblock && $from.sameParent($to))) return null;
  let valid = true;
  editor.state.doc.nodesBetween(from, to, (entry) => { if (entry.type.name === "hardBreak") valid = false; });
  const quote = editor.state.doc.textBetween(from, to, "", "");
  if (!valid || !quote || Array.from(quote).length > 2000) return null;
  return { anchor: { from, to }, quote };
}
function updateReviewControls() {
  updateReuseControls();
  const review = state.review;
  const busy = reviewBusy(review);
  $("comments-toggle").disabled = !state.editor || !state.session?.objectId || Boolean(state.session?.loading);
  $("comments-refresh").disabled = busy || Boolean(review?.loading || review?.uncertain);
  $("comments-close").disabled = Boolean(review?.saving);
  $("comment-new").disabled = !canCreateReview(review);
  $("comment-selection").disabled = !canCreateReview(review) || !selectedReviewAnchor();
  $("comments-more").disabled = busy || Boolean(review?.loading || review?.uncertain);
  const composer = review?.composer;
  $("comment-body").disabled = busy || Boolean(review?.uncertain);
  $("comment-cancel").disabled = Boolean(review?.saving);
  $("comment-prepare").textContent = review?.uncertain ? "Speicherung prüfen" : "Speicherung vorbereiten";
  const bodyLength = Array.from(composer?.body || "").length;
  $("comment-body-count").textContent = composer ? `${bodyLength} / 4.000 Zeichen` : "";
  const thread = review?.detail?.thread;
  const permitted = composer?.operation === "create" ? canCreateReview(review) && composer.documentRevision === review.session.revision :
    Boolean(thread && thread.thread_id === composer?.threadId && review.detail.can_comment && thread.can_comment && thread.status === "open");
  $("comment-prepare").disabled = busy || (!review?.uncertain && (review?.conflict || !permitted || !composer?.body.trim() || bodyLength > 4000));
  if (!reviewCurrent(review)) return;
  let hint = "Kommentare gehören genau zu dieser gespeicherten Fassung; sie wandern nicht in neue Versionen.";
  if (review.session.loading || review.session.saving || review.session.restoring) hint = "Bitte warten Sie, bis der laufende Dokumentvorgang abgeschlossen ist.";
  else if (review.session.uncertain) hint = "Prüfen Sie zuerst die noch nicht bestätigte Dokumentspeicherung.";
  else if (review.uncertain) hint = "Speicherung noch nicht bestätigt. Prüfen Sie denselben Vorgang erneut; der Entwurf bleibt erhalten.";
  else if (review.conflict) hint = "Laden Sie die Diskussion erneut, bevor Sie die Kommentaraktion wiederholen. Ihr Entwurf bleibt erhalten.";
  else if (isDirty()) hint = "Ungespeicherte Dokumentänderungen: Neue Kommentare und Textmarkierungen sind erst nach dem Speichern verfügbar. Bestehende Diskussionen bleiben ihrer Fassung zugeordnet.";
  else if (composer?.operation === "create" && composer.documentRevision !== review.session.revision) hint = "Die Dokumentauswahl hat sich seit Beginn dieses Kommentars geändert. Ihr Kommentartext bleibt erhalten; beginnen Sie einen neuen Kommentar zur gespeicherten Fassung.";
  else if (review.session.historical || review.currentVersionId !== review.versionId) hint = "Frühere Fassung: Bestehende Diskussionen können bei entsprechender Berechtigung fortgesetzt werden. Neue Kommentare entstehen nur in der aktuellen Fassung.";
  else if (!review.loading && !review.canCreate) hint = "Kommentare sind schreibgeschützt. Sie können freigegebene Diskussionen lesen.";
  $("comments-hint").textContent = hint;
  document.querySelectorAll("[data-review-action]").forEach((button) => {
    const action = button.dataset.reviewAction;
    button.disabled = busy || Boolean(review.uncertain) ||
      (action === "reply" && (!thread?.can_comment || !review.detail?.can_comment || thread.status !== "open")) ||
      (["resolve", "reopen"].includes(action) && (!thread?.can_resolve || !review.detail?.can_resolve)) ||
      (action === "locate" && (isDirty() || !thread?.anchor));
  });
}

async function loadReview(append = false) {
  if (!reviewPanelOpen()) return;
  const session = state.session;
  if (!session?.objectId || !session.version || session.loading) {
    $("comments-status").textContent = "Speichern Sie das Dokument zuerst, um Kommentare zu dieser Fassung anzulegen.";
    return;
  }
  let review = state.review;
  if (!reviewCurrent(review)) {
    clearReview();
    review = { session, context: state.context, versionId: session.version.version_id,
      controller: new AbortController(), listRequest: 0, detailRequest: 0, threads: [], selectedId: null,
      detail: null, nextCursor: null, loading: false, canCreate: false, currentVersionId: null,
      composer: null, attempt: null, saving: false, settling: false, uncertain: false, conflict: false, highlight: null };
    state.review = review;
  }
  if (review.saving || review.uncertain || (append && !review.nextCursor)) return;
  const request = ++review.listRequest;
  const cursor = append ? review.nextCursor : null;
  review.loading = true; review.canCreate = false;
  if (!append) {
    review.threads = []; review.detail = null; review.detailRequest += 1; review.nextCursor = null; review.selectedId = null;
    clearReviewHighlight();
    $("comments-list").replaceChildren();
  }
  $("comments-version").textContent = `${session.historical ? "Frühere Fassung" : "Geöffnete Fassung"} · ${dateLabel(session.version.created_at_utc)}`;
  $("comments-version").title = review.versionId;
  $("comments-status").textContent = "Kommentare werden geladen …";
  updateReviewControls();
  try {
    const result = await api(`${reviewBase(review)}?anchor_version_id=${encodeURIComponent(review.versionId)}&limit=20${cursor ? `&after=${encodeURIComponent(cursor)}` : ""}`, { signal: review.controller.signal }, review.context);
    if (!reviewCurrent(review) || review.listRequest !== request) return;
    if (!reviewIdentity(result, review) || typeof result.current_version_id !== "string" || typeof result.can_create !== "boolean" ||
        !Array.isArray(result.threads) || result.threads.length > 20 || result.threads.some((thread) => !validReviewThread(thread, review)) ||
        !(result.next_cursor === null || typeof result.next_cursor === "string") || (cursor && result.next_cursor === cursor)) throw new ApiError(502);
    const ids = new Set(review.threads.map((thread) => thread.thread_id));
    for (const thread of result.threads) {
      if (ids.has(thread.thread_id)) throw new ApiError(502);
      ids.add(thread.thread_id);
    }
    review.threads.push(...result.threads);
    review.currentVersionId = result.current_version_id;
    review.canCreate = result.can_create;
    if (review.composer?.operation === "create") review.conflict = false;
    review.nextCursor = result.next_cursor;
    $("comments-status").textContent = review.threads.length ? `${review.threads.length} Diskussionen geladen${review.nextCursor ? " · weitere verfügbar" : ""}.` : "Noch keine Kommentare zu dieser Fassung.";
    renderReviewThreads(review);
    return true;
  } catch (error) {
    if (reviewCurrent(review) && review.listRequest === request) reviewReadFailure(error, review);
    return false;
  }
  finally {
    if (reviewCurrent(review) && review.listRequest === request) { review.loading = false; updateReviewControls(); }
  }
}

function renderReviewThreads(review) {
  if (!reviewCurrent(review)) return;
  $("comments-list").replaceChildren();
  const threads = [...review.threads];
  if (review.detail && !threads.some((entry) => entry.thread_id === review.detail.thread.thread_id)) threads.unshift(review.detail.thread);
  threads.forEach((listed) => {
    const thread = review.detail?.thread.thread_id === listed.thread_id ? review.detail.thread : listed;
    const card = node("article", undefined, "review-thread");
    card.dataset.threadId = thread.thread_id;
    const open = node("button", `${thread.anchor ? "Textstelle" : "Dokumentfassung"} · ${thread.status === "open" ? "Offen" : "Erledigt"}`, "review-thread-open");
    open.type = "button"; open.dataset.reviewAction = "open";
    open.setAttribute("aria-expanded", String(review.selectedId === thread.thread_id));
    open.addEventListener("click", () => loadReviewThread(thread.thread_id));
    card.append(open, node("p", `${thread.created_by} · ${dateLabel(thread.created_at_utc)}`, "review-meta"));
    if (review.selectedId === thread.thread_id && review.detail) renderReviewDetail(card, review);
    $("comments-list").append(card);
  });
  $("comments-more").hidden = !review.nextCursor;
  updateReviewControls();
}

async function loadReviewThread(threadId, append = false) {
  const review = state.review;
  if (!reviewCurrent(review) || review.saving || review.uncertain) return;
  const prior = append ? review.detail : null;
  if (append && (!prior || !prior.next_after_revision)) return;
  const request = ++review.detailRequest;
  review.pendingReads = (review.pendingReads || 0) + 1;
  updateReuseControls();
  review.selectedId = threadId;
  if (!append) { review.detail = null; clearReviewHighlight(); renderReviewThreads(review); }
  $("comments-status").textContent = "Diskussion wird geladen …";
  try {
    const after = prior?.next_after_revision || 0;
    const result = await api(`${reviewBase(review)}/${encodeURIComponent(threadId)}?after_revision=${after}&limit=20`, { signal: review.controller.signal }, review.context);
    if (!reviewCurrent(review) || review.detailRequest !== request || review.selectedId !== threadId) return;
    if (!reviewIdentity(result, review) || typeof result.current_version_id !== "string" ||
        !validReviewThread(result.thread, review) || result.thread.thread_id !== threadId ||
        typeof result.can_comment !== "boolean" || typeof result.can_resolve !== "boolean" ||
        !(result.quote === null || (typeof result.quote === "string" && Array.from(result.quote).length <= 2000)) ||
        !Array.isArray(result.events) || result.events.length > 20 || result.events.some((event) => !validReviewEvent(event)) ||
        !(result.next_after_revision === null || (Number.isInteger(result.next_after_revision) && result.next_after_revision > after))) throw new ApiError(502);
    const events = [...(prior?.events || [])];
    let last = after;
    for (const event of result.events) {
      if (event.revision <= last || event.revision > result.thread.revision) throw new ApiError(502);
      last = event.revision; events.push(event);
    }
    review.detail = { ...result, events };
    review.currentVersionId = result.current_version_id;
    review.canCreate = review.canCreate && result.can_resolve;
    if (review.composer?.threadId === threadId) review.conflict = false;
    $("comments-status").textContent = `${events.length} Beiträge geladen${result.next_after_revision ? " · weitere verfügbar" : ""}.`;
    renderReviewThreads(review);
  } catch (error) {
    if (reviewCurrent(review) && review.detailRequest === request) {
      review.detail = null; renderReviewThreads(review); reviewReadFailure(error, review);
    }
  } finally {
    review.pendingReads -= 1;
    if (reviewCurrent(review)) updateReuseControls();
  }
}

function renderReviewDetail(card, review) {
  const detail = review.detail;
  const thread = detail.thread;
  const section = node("section", undefined, "review-detail"); section.id = "comment-thread-detail";
  const quote = node("blockquote", detail.quote || "Kommentar zur gesamten gespeicherten Fassung."); quote.id = "comment-thread-quote";
  section.append(quote, node("p", `Fassung vom ${dateLabel(review.session.version.created_at_utc)} · Revision ${thread.revision}`, "review-meta"));
  const events = node("div"); events.id = "comment-events";
  const labels = { create: "Kommentar", reply: "Antwort", resolve: "Diskussion erledigt", reopen: "Diskussion wieder geöffnet" };
  detail.events.forEach((entry) => {
    const event = node("article", undefined, "review-event"); event.dataset.revision = String(entry.revision);
    event.append(node("strong", labels[entry.operation]), node("p", `${entry.created_by} · ${dateLabel(entry.created_at_utc)}`, "review-meta"));
    if (entry.body !== null) event.append(node("p", entry.body, "review-event-body"));
    events.append(event);
  });
  section.append(events);
  if (detail.next_after_revision) {
    const more = node("button", "Weitere Beiträge laden", "quiet-button"); more.id = "comment-events-more"; more.type = "button";
    more.addEventListener("click", () => loadReviewThread(thread.thread_id, true)); section.append(more);
  }
  const actions = node("div", undefined, "review-actions");
  for (const [action, label] of [["locate", "Textstelle anzeigen"], ["reply", "Antworten"],
    [thread.status === "open" ? "resolve" : "reopen", thread.status === "open" ? "Erledigen" : "Wieder öffnen"]]) {
    if (action === "locate" && !thread.anchor) continue;
    const button = node("button", label, "quiet-button"); button.type = "button"; button.dataset.reviewAction = action;
    button.addEventListener("click", () => {
      if (action === "locate") locateReviewThread(review, thread);
      else if (action === "reply") beginReviewComposer("reply", thread);
      else prepareReviewOperation(action, thread);
    });
    actions.append(button);
  }
  section.append(actions); card.append(section);
}

async function locateReviewThread(review, thread) {
  if (!reviewCurrent(review) || isDirty() || !thread.anchor || reviewBusy(review)) return;
  review.pendingReads = (review.pendingReads || 0) + 1;
  updateReuseControls();
  try {
    const fresh = await api(`/v1/office/documents/${encodeURIComponent(review.session.objectId)}/content?version_id=${encodeURIComponent(review.versionId)}`, { signal: review.controller.signal }, review.context);
    if (!reviewCurrent(review) || isDirty() || review.detail?.thread.thread_id !== thread.thread_id) return;
    const content = validatedContent(fresh, review.session.objectId, review.versionId);
    const saved = state.editor.schema.nodeFromJSON(content);
    if (!saved.eq(state.editor.state.doc) || thread.anchor.to > saved.content.size ||
        saved.textBetween(thread.anchor.from, thread.anchor.to, "", "") !== review.detail.quote) throw new ApiError(502);
    review.highlight = thread.anchor;
    state.editor.commands.setTextSelection(thread.anchor);
    state.editor.view.dispatch(state.editor.state.tr.setMeta(reviewKey, true));
    focusEditor();
    if (window.matchMedia("(max-width: 1000px)").matches) await hideInspectorWithReview();
  } catch (error) { reviewReadFailure(error, review); }
  finally {
    review.pendingReads -= 1;
    if (reviewCurrent(review)) updateReuseControls();
  }
}

async function beginReviewComposer(operation, thread = null, selection = null) {
  const review = state.review;
  if (reviewBusy(review) || review.uncertain || (operation === "create" && !canCreateReview(review))) return;
  const documentRevision = review.session.revision;
  if (!(await confirmDiscard("comments")) || !reviewCurrent(review) || reviewBusy(review)) return;
  if (operation === "create" && (!canCreateReview(review) || review.session.revision !== documentRevision)) return;
  if (operation === "reply" && (!thread?.can_comment || thread.status !== "open" || review.detail?.thread.thread_id !== thread.thread_id)) return;
  review.attempt = null; review.conflict = false;
  review.composer = { operation, threadId: thread?.thread_id || null, anchor: selection?.anchor || null,
    quote: selection?.quote || (thread ? review.detail.quote : null), body: "", revision: 0, documentRevision: review.session.revision };
  $("comment-composer-title").textContent = operation === "reply" ? "Antwort schreiben" : "Neuer Kommentar";
  $("comment-anchor").textContent = review.composer.quote || "Zur gesamten gespeicherten Fassung.";
  $("comment-body").value = "";
  $("comment-composer").hidden = false;
  updateReviewControls();
  $("comment-body").focus();
}

function clearReviewComposer(review) {
  review.composer = null; review.attempt = null; review.uncertain = false; review.conflict = false;
  closeReviewConfirmation();
  $("comment-composer").hidden = true;
  $("comment-body").value = ""; $("comment-anchor").textContent = "";
  updateEditorState();
}

async function prepareReviewOperation(operation = null, thread = null) {
  const review = state.review;
  if (reviewBusy(review)) return;
  if (!review.uncertain && operation) {
    if (!(await confirmDiscard("comments")) || !reviewCurrent(review) || reviewBusy(review)) return;
    const currentThread = review.detail?.thread;
    if (!currentThread?.can_resolve || !review.detail?.can_resolve || currentThread.thread_id !== thread?.thread_id ||
        (operation === "resolve" ? currentThread.status !== "open" : currentThread.status !== "resolved")) return;
    clearReviewComposer(review);
    review.composer = { operation, threadId: thread.thread_id, body: "", revision: 0 };
  }
  const composer = review.composer;
  if (!composer) return;
  if (!review.attempt) {
    if (["create", "reply"].includes(composer.operation) && $("comment-prepare").disabled) return;
    const payload = { mutation_reference: mutationReference(), human_confirmation: true };
    if (composer.operation === "create") {
      if (!canCreateReview(review) || composer.documentRevision !== review.session.revision) return;
      Object.assign(payload, { anchor_version_id: review.versionId, expected_current_version_id: review.versionId,
        anchor: composer.anchor, body: composer.body });
    } else {
      const currentThread = review.detail?.thread;
      if (!currentThread || currentThread.thread_id !== composer.threadId) return;
      Object.assign(payload, { operation: composer.operation, expected_revision: currentThread.revision,
        ...(composer.operation === "reply" ? { body: composer.body } : {}) });
    }
    review.attempt = { operation: composer.operation, threadId: composer.threadId, composerRevision: composer.revision, payload };
  }
  const labels = { create: "Kommentar hinzufügen", reply: "Antwort hinzufügen", resolve: "Diskussion erledigen", reopen: "Diskussion wieder öffnen" };
  $("comment-confirm-title").textContent = labels[review.attempt.operation];
  $("comment-confirm-summary").textContent = `${labels[review.attempt.operation]} · gespeicherte Fassung vom ${dateLabel(review.session.version.created_at_utc)}.${review.uncertain ? " Derselbe Vorgang wird erneut geprüft." : ""}`;
  $("comment-confirm-body").textContent = review.attempt.payload.body || "Der Diskussionsstatus wird verbindlich geändert; die Beiträge bleiben erhalten.";
  $("comment-confirm-anchor").textContent = composer.quote || review.detail?.quote || "Zur gesamten gespeicherten Fassung.";
  $("comment-confirm-checkbox").checked = false;
  $("comment-confirm-submit").disabled = true;
  $("comment-confirm-message").textContent = "";
  $("comment-confirm-dialog").showModal();
}

async function saveReviewOperation(event) {
  event.preventDefault();
  const review = state.review;
  if (reviewBusy(review) || !$("comment-confirm-checkbox").checked || !review.attempt ||
      review.attempt.composerRevision !== review.composer?.revision) return;
  if (!review.uncertain && review.attempt.operation === "create" &&
      (!canCreateReview(review) || review.composer.documentRevision !== review.session.revision)) {
    closeReviewConfirmation(); updateReviewControls(); return;
  }
  const attempt = review.attempt;
  review.saving = true;
  $("comment-confirm-dialog").querySelectorAll("button,input").forEach((control) => { control.disabled = true; });
  $("comment-confirm-message").textContent = "Kommentaraktion wird gespeichert …";
  updateEditorState();
  try {
    const path = `${reviewBase(review)}${attempt.threadId ? `/${encodeURIComponent(attempt.threadId)}/events` : ""}`;
    const result = await api(path, { method: "POST", body: attempt.payload }, review.context);
    if (!reviewCurrent(review)) return;
    if (!reviewIdentity(result, review) || !validReviewThread(result.thread, review) || !validReviewEvent(result.event) ||
        result.event.operation !== attempt.operation || (attempt.threadId && result.thread.thread_id !== attempt.threadId) ||
        !Number.isInteger(result.applied_revision) || result.applied_revision !== result.event.revision ||
        typeof result.replayed !== "boolean") throw new ApiError(502);
    review.selectedId = result.thread.thread_id;
    review.settling = true;
    clearReviewComposer(review);
    review.saving = false;
    const labels = { create: "Kommentar gespeichert.", reply: "Antwort gespeichert.", resolve: "Diskussion erledigt.", reopen: "Diskussion wieder geöffnet." };
    const success = labels[attempt.operation];
    // The mutation is confirmed before refreshing. A failed refresh never turns
    // a committed action into a retry with a new mutation reference.
    const refreshed = await loadReview();
    if (refreshed && reviewCurrent(review)) await loadReviewThread(result.thread.thread_id);
    if (reviewCurrent(review)) $("comments-status").textContent = `${success} ${$("comments-status").textContent}`;
  } catch (error) {
    if (!reviewCurrent(review)) return;
    closeReviewConfirmation();
    if (denied(error)) { officeAccessDenied(); return; }
    if (error instanceof ApiError && error.status === 409) {
      review.attempt = null; review.conflict = true;
      $("comments-status").textContent = "Die Diskussion oder Dokumentfassung hat sich geändert. Ihr Kommentarentwurf bleibt erhalten. Bitte laden Sie die Kommentare erneut.";
    } else if (error instanceof ApiError && [400, 413, 422].includes(error.status)) {
      review.attempt = null;
      $("comments-status").textContent = "Der Kommentar konnte nicht gespeichert werden. Prüfen Sie Textlänge und Textauswahl; Ihr Entwurf bleibt erhalten.";
    } else {
      review.uncertain = true;
      $("comments-status").textContent = "Speicherung noch nicht bestätigt. Prüfen Sie denselben Vorgang erneut; Ihr Kommentarentwurf bleibt erhalten.";
      if (!["create", "reply"].includes(attempt.operation)) {
        $("comment-composer-title").textContent = "Statusänderung prüfen";
        $("comment-anchor").textContent = "Die Antwort auf die Statusänderung ist ausgeblieben.";
        $("comment-body").value = "";
        $("comment-composer").hidden = false;
      }
    }
  } finally {
    if (reviewCurrent(review)) {
      $("comment-confirm-dialog").querySelectorAll("button,input").forEach((control) => { control.disabled = false; });
      $("comment-confirm-submit").disabled = true;
      review.saving = false; review.settling = false; updateEditorState();
    }
  }
}

function suggestionCurrent(suggestions) {
  return Boolean(suggestions && state.suggestions === suggestions && sessionCurrent(suggestions.session) &&
    suggestions.context === state.context && suggestions.versionId === suggestions.session.version?.version_id);
}
function suggestionPanelOpen() {
  return $("suggestions-tab").getAttribute("aria-selected") === "true" &&
    !$("office-shell").classList.contains("inspector-hidden") && !$("office-shell").classList.contains("focus-mode");
}
function hasSuggestionDraft() { return Boolean(state.suggestions?.composer?.operation === "create" || state.suggestions?.uncertain); }
function suggestionLocksDocument() {
  const suggestions = state.suggestions;
  return Boolean(suggestions && (suggestions.preparing || suggestions.saving || suggestions.settling || suggestions.uncertain));
}
function suggestionBusy(suggestions = state.suggestions) {
  return !suggestionCurrent(suggestions) || suggestions.preparing || suggestions.saving || suggestions.settling ||
    suggestions.session.loading || suggestions.session.saving || suggestions.session.restoring || suggestions.session.uncertain;
}
function suggestionBase(suggestions) { return `/v1/office/documents/${encodeURIComponent(suggestions.session.objectId)}/suggestions`; }
function suggestionIdentity(result, suggestions) {
  return result?.tenant_id === suggestions.context.tenantId && result.object_id === suggestions.session.objectId &&
    typeof result.current_version_id === "string" && result.rag_indexing_allowed === false && result.search_indexing_allowed === false;
}
function validSuggestion(value, suggestions) {
  return value && typeof value.suggestion_id === "string" && value.anchor_version_id === suggestions.versionId &&
    Number.isInteger(value.anchor?.from) && Number.isInteger(value.anchor?.to) && value.anchor.from >= 0 && value.anchor.to > value.anchor.from &&
    ["open", "accepted", "rejected"].includes(value.status) && value.revision === (value.status === "open" ? 1 : 2) &&
    typeof value.created_by === "string" && typeof value.created_at_utc === "string" &&
    typeof value.can_accept === "boolean" && typeof value.can_reject === "boolean" &&
    (value.status === "accepted" ? typeof value.result_version_id === "string" : value.result_version_id === null);
}
function validSuggestionDetail(result, suggestions, id = null) {
  if (!suggestionIdentity(result, suggestions) || !validSuggestion(result.suggestion, suggestions) ||
      (id && result.suggestion.suggestion_id !== id) || typeof result.quote !== "string" || !result.quote ||
      Array.from(result.quote).length > 2000 || typeof result.replacement_text !== "string" ||
      Array.from(result.replacement_text).length > 4000 || result.quote === result.replacement_text) return false;
  const decision = result.decision;
  return result.suggestion.status === "open" ? decision === null : Boolean(decision &&
    typeof decision.decision_id === "string" && typeof decision.created_by === "string" && typeof decision.created_at_utc === "string" &&
    decision.operation === (result.suggestion.status === "accepted" ? "accept" : "reject") &&
    decision.result_version_id === result.suggestion.result_version_id);
}
function closeSuggestionConfirmation() {
  $("suggestion-confirm-dialog").close();
  $("suggestion-confirm-dialog").querySelectorAll("button,input").forEach((control) => { control.disabled = false; });
  $("suggestion-confirm-checkbox").checked = false;
  $("suggestion-confirm-submit").disabled = true;
  ["summary", "before", "after", "message"].forEach((name) => { $(`suggestion-confirm-${name}`).textContent = ""; });
}
function clearSuggestions() {
  const suggestions = state.suggestions;
  state.suggestions = null;
  suggestions?.controller.abort();
  closeSuggestionConfirmation();
  $("suggestions-list").replaceChildren();
  ["suggestions-status", "suggestions-version", "suggestions-hint", "suggestion-before", "suggestion-count"].forEach((id) => { $(id).textContent = ""; });
  $("suggestion-replacement").value = "";
  $("suggestion-composer").hidden = true;
  $("suggestions-more").hidden = true;
  $("suggestion-new").disabled = true;
}
function canCreateSuggestion(suggestions = state.suggestions) {
  return !suggestionBusy(suggestions) && !suggestions.uncertain && !suggestions.loading && suggestions.canCreate &&
    suggestions.session.canWrite && !suggestions.session.historical && !suggestions.session.conflict && !isDirty() && suggestions.currentVersionId === suggestions.versionId;
}
function canAcceptSuggestion(suggestions, detail = suggestions?.detail) {
  return !suggestionBusy(suggestions) && !suggestions.uncertain && !suggestions.conflict && !suggestions.loading &&
    detail?.suggestion.status === "open" && detail.suggestion.can_accept && suggestions.session.canWrite &&
    !suggestions.session.historical && !suggestions.session.conflict && !isDirty() && suggestions.currentVersionId === suggestions.versionId;
}
function updateSuggestionControls() {
  updateReuseControls();
  const suggestions = state.suggestions;
  const busy = suggestionBusy(suggestions);
  $("suggestions-toggle").disabled = !state.editor || !state.session?.objectId || Boolean(state.session?.loading);
  $("suggestions-refresh").disabled = busy || Boolean(suggestions?.loading || suggestions?.uncertain);
  $("suggestions-more").disabled = $("suggestions-refresh").disabled;
  $("suggestions-close").disabled = Boolean(suggestions?.saving || suggestions?.settling);
  $("suggestion-new").disabled = !canCreateSuggestion(suggestions) || !selectedReviewAnchor();
  const composer = suggestions?.composer;
  const length = Array.from(composer?.replacement || "").length;
  $("suggestion-count").textContent = composer?.operation === "create" ? `${length} / 4.000 Zeichen` : "";
  $("suggestion-replacement").disabled = busy || Boolean(suggestions?.uncertain) || composer?.operation !== "create";
  $("suggestion-cancel").disabled = Boolean(suggestions?.saving || suggestions?.settling);
  $("suggestion-prepare").textContent = suggestions?.uncertain ? "Speicherung prüfen" : "Speicherung vorbereiten";
  $("suggestion-prepare").disabled = busy || (!suggestions?.uncertain && (suggestions?.conflict ||
    composer?.operation !== "create" || !canCreateSuggestion(suggestions) || composer.documentRevision !== suggestions.session.revision ||
    length > 4000 || composer.replacement === composer.quote));
  document.querySelectorAll("[data-suggestion-action]").forEach((button) => {
    const action = button.dataset.suggestionAction;
    button.disabled = busy || Boolean(suggestions?.uncertain || suggestions?.loading) ||
      (action === "accept" && !canAcceptSuggestion(suggestions)) ||
      (action === "reject" && (!suggestions?.detail?.suggestion.can_reject || suggestions.detail.suggestion.status !== "open"));
  });
  if (!suggestionCurrent(suggestions)) return;
  let hint = "Markieren Sie bis zu 2.000 Zeichen innerhalb eines Absatzes. Vorschläge bleiben an genau diese gespeicherte Fassung gebunden.";
  if (suggestions.uncertain) hint = "Speicherung nicht bestätigt. Prüfen Sie denselben Vorgang erneut, bevor Sie weiterarbeiten.";
  else if (suggestions.conflict) hint = "Der Stand hat sich geändert. Aktualisieren Sie die Vorschläge; Ihr Entwurf bleibt erhalten.";
  else if (suggestions.session.uncertain) hint = "Prüfen Sie zuerst die noch nicht bestätigte Dokumentspeicherung.";
  else if (isDirty()) hint = "Speichern Sie Ihre Dokumentänderungen zuerst. Neue Vorschläge und Annahmen erfordern eine unveränderte gespeicherte Fassung.";
  else if (suggestions.session.historical || suggestions.currentVersionId !== suggestions.versionId) hint = "Frühere Fassung: Vorschläge bleiben lesbar und können bei entsprechender Berechtigung abgelehnt werden. Sie werden nicht auf neuere Fassungen übertragen.";
  else if (composer?.operation === "create" && composer.documentRevision !== suggestions.session.revision) hint = "Die Fassung hat sich seit der Textauswahl geändert. Ihr Ersatztext bleibt erhalten; wählen Sie die Textstelle erneut.";
  else if (composer?.operation === "create" && composer.replacement === composer.quote) hint = "Keine Änderung: Vorher und Nachher sind gleich.";
  else if (!suggestions.loading && !suggestions.canCreate) hint = "Vorschläge sind schreibgeschützt. Freigegebene Vorschläge bleiben lesbar.";
  $("suggestions-hint").textContent = hint;
}
function suggestionReadFailure(error, suggestions) {
  if (!suggestionCurrent(suggestions)) return;
  if (denied(error)) { officeAccessDenied(); return; }
  $("suggestions-status").textContent = "Vorschläge sind gerade nicht erreichbar. Ihr Entwurf bleibt erhalten. Bitte erneut aktualisieren.";
}
async function loadSuggestions(append = false) {
  if (!suggestionPanelOpen()) return false;
  const session = state.session;
  if (!session?.objectId || !session.version || session.loading) {
    $("suggestions-status").textContent = "Speichern Sie das Dokument zuerst, um Änderungen vorzuschlagen.";
    return false;
  }
  let suggestions = state.suggestions;
  if (!suggestionCurrent(suggestions)) {
    clearSuggestions();
    suggestions = { session, context: state.context, versionId: session.version.version_id, controller: new AbortController(),
      listRequest: 0, detailRequest: 0, items: [], selectedId: null, detail: null, nextCursor: null,
      loading: false, canCreate: false, currentVersionId: null, composer: null, attempt: null,
      preparing: false, saving: false, settling: false, uncertain: false, conflict: false };
    state.suggestions = suggestions;
  }
  if (suggestions.saving || suggestions.preparing || suggestions.uncertain || (append && !suggestions.nextCursor)) return false;
  const request = ++suggestions.listRequest;
  const cursor = append ? suggestions.nextCursor : null;
  suggestions.loading = true; suggestions.canCreate = false;
  if (!append) {
    suggestions.items = []; suggestions.detail = null; suggestions.selectedId = null;
    suggestions.detailRequest += 1; suggestions.nextCursor = null;
    suggestions.attempt = null; closeSuggestionConfirmation();
    $("suggestions-list").replaceChildren(); $("suggestions-more").hidden = true;
  }
  $("suggestions-version").textContent = `${session.historical ? "Frühere Fassung" : "Geöffnete Fassung"} · ${dateLabel(session.version.created_at_utc)}`;
  $("suggestions-version").title = suggestions.versionId;
  $("suggestions-status").textContent = "Vorschläge werden geladen …";
  updateSuggestionControls();
  try {
    const result = await api(`${suggestionBase(suggestions)}?anchor_version_id=${encodeURIComponent(suggestions.versionId)}&limit=20${cursor ? `&after=${encodeURIComponent(cursor)}` : ""}`, { signal: suggestions.controller.signal }, suggestions.context);
    if (!suggestionCurrent(suggestions) || suggestions.listRequest !== request) return false;
    if (!suggestionIdentity(result, suggestions) || typeof result.can_create !== "boolean" || !Array.isArray(result.suggestions) ||
        result.suggestions.length > 20 || result.suggestions.some((value) => !validSuggestion(value, suggestions)) ||
        !(result.next_cursor === null || typeof result.next_cursor === "string") || (cursor && result.next_cursor === cursor)) throw new ApiError(502);
    const ids = new Set(suggestions.items.map((value) => value.suggestion_id));
    for (const value of result.suggestions) {
      if (ids.has(value.suggestion_id)) throw new ApiError(502);
      ids.add(value.suggestion_id);
    }
    suggestions.items.push(...result.suggestions); suggestions.nextCursor = result.next_cursor;
    suggestions.currentVersionId = result.current_version_id; suggestions.canCreate = result.can_create;
    if (suggestions.composer?.operation === "create") suggestions.conflict = false;
    $("suggestions-status").textContent = suggestions.items.length ? `${suggestions.items.length} Vorschläge geladen${suggestions.nextCursor ? " · weitere verfügbar" : ""}.` : "Noch keine Vorschläge zu dieser Fassung.";
    renderSuggestions(suggestions);
    return true;
  } catch (error) {
    if (suggestionCurrent(suggestions) && suggestions.listRequest === request) suggestionReadFailure(error, suggestions);
    return false;
  } finally {
    if (suggestionCurrent(suggestions) && suggestions.listRequest === request) { suggestions.loading = false; updateSuggestionControls(); }
  }
}
function renderSuggestions(suggestions) {
  if (!suggestionCurrent(suggestions)) return;
  $("suggestions-list").replaceChildren();
  const items = [...suggestions.items];
  if (suggestions.detail && !items.some((value) => value.suggestion_id === suggestions.detail.suggestion.suggestion_id)) items.unshift(suggestions.detail.suggestion);
  const labels = { open: "Offen", accepted: "Angenommen", rejected: "Abgelehnt" };
  items.forEach((listed) => {
    const value = suggestions.detail?.suggestion.suggestion_id === listed.suggestion_id ? suggestions.detail.suggestion : listed;
    const card = node("article", undefined, "review-thread"); card.dataset.suggestionId = value.suggestion_id;
    const open = node("button", `Textänderung · ${labels[value.status]}`, "review-thread-open");
    open.type = "button"; open.dataset.suggestionAction = "open";
    open.setAttribute("aria-expanded", String(suggestions.selectedId === value.suggestion_id));
    open.addEventListener("click", () => loadSuggestionDetail(value.suggestion_id));
    card.append(open, node("p", `${value.created_by} · ${dateLabel(value.created_at_utc)}`, "review-meta"));
    if (suggestions.selectedId === value.suggestion_id && suggestions.detail) {
      const detail = suggestions.detail;
      const section = node("section", undefined, "suggestion-detail"); section.id = "suggestion-detail";
      section.append(node("p", `Fassung vom ${dateLabel(suggestions.session.version.created_at_utc)} · Revision ${value.revision}`, "review-meta"));
      const before = node("p", detail.quote, "suggestion-text"); before.id = "suggestion-quote";
      const after = node("p", detail.replacement_text || "Textstelle löschen", "suggestion-text"); after.id = "suggestion-after";
      section.append(node("h4", "Vorher"), before, node("h4", detail.replacement_text ? "Nachher" : "Nachher · leer"), after);
      if (detail.decision) section.append(node("p", `${labels[value.status]} durch ${detail.decision.created_by} · ${dateLabel(detail.decision.created_at_utc)}`, "review-meta"));
      const actions = node("div", undefined, "review-actions");
      for (const [operation, label] of [["accept", "Annehmen und neue Version speichern"], ["reject", "Ablehnen"]]) {
        const button = node("button", label, operation === "accept" ? "button secondary" : "quiet-button");
        button.type = "button"; button.dataset.suggestionAction = operation;
        button.addEventListener("click", () => prepareSuggestionOperation(operation, value.suggestion_id)); actions.append(button);
      }
      section.append(actions); card.append(section);
    }
    $("suggestions-list").append(card);
  });
  $("suggestions-more").hidden = !suggestions.nextCursor;
  updateSuggestionControls();
}
async function loadSuggestionDetail(id) {
  const suggestions = state.suggestions;
  if (!suggestionCurrent(suggestions) || suggestions.preparing || suggestions.saving || suggestions.uncertain) return false;
  const request = ++suggestions.detailRequest;
  suggestions.pendingReads = (suggestions.pendingReads || 0) + 1;
  updateReuseControls();
  suggestions.attempt = null; closeSuggestionConfirmation();
  suggestions.selectedId = id; suggestions.detail = null; renderSuggestions(suggestions);
  $("suggestions-status").textContent = "Vorschlag wird geladen …";
  try {
    const result = await api(`${suggestionBase(suggestions)}/${encodeURIComponent(id)}`, { signal: suggestions.controller.signal }, suggestions.context);
    if (!suggestionCurrent(suggestions) || suggestions.detailRequest !== request || suggestions.selectedId !== id) return false;
    if (!validSuggestionDetail(result, suggestions, id)) throw new ApiError(502);
    suggestions.detail = result; suggestions.currentVersionId = result.current_version_id;
    if (suggestions.composer?.suggestionId === id) suggestions.conflict = false;
    $("suggestions-status").textContent = "Vorschlag geladen.";
    renderSuggestions(suggestions);
    return true;
  } catch (error) {
    if (suggestionCurrent(suggestions) && suggestions.detailRequest === request) {
      suggestions.detail = null; renderSuggestions(suggestions); suggestionReadFailure(error, suggestions);
    }
    return false;
  } finally {
    suggestions.pendingReads -= 1;
    if (suggestionCurrent(suggestions)) updateReuseControls();
  }
}
function clearSuggestionComposer(suggestions) {
  suggestions.composer = null; suggestions.attempt = null; suggestions.uncertain = false; suggestions.conflict = false;
  closeSuggestionConfirmation(); $("suggestion-composer").hidden = true;
  $("suggestion-replacement").value = ""; $("suggestion-before").textContent = "";
  updateEditorState();
}
async function beginSuggestion() {
  const suggestions = state.suggestions;
  const selection = selectedReviewAnchor();
  if (!canCreateSuggestion(suggestions) || !selection) return;
  const revision = suggestions.session.revision;
  if (!(await confirmDiscard("suggestions")) || !suggestionCurrent(suggestions) ||
      !canCreateSuggestion(suggestions) || suggestions.session.revision !== revision) return;
  const selected = selectedReviewAnchor();
  if (!selected || selected.anchor.from !== selection.anchor.from || selected.anchor.to !== selection.anchor.to) return;
  clearSuggestionComposer(suggestions);
  suggestions.composer = { operation: "create", suggestionId: null, anchor: selection.anchor, quote: selection.quote,
    replacement: selection.quote, revision: 0, documentRevision: revision };
  $("suggestion-composer-title").textContent = "Neuer Änderungsvorschlag";
  $("suggestion-before").textContent = selection.quote;
  $("suggestion-replacement").value = selection.quote;
  $("suggestion-composer").hidden = false;
  updateSuggestionControls(); $("suggestion-replacement").focus(); $("suggestion-replacement").select();
}
async function prepareSuggestionOperation(operation = null, id = null) {
  const suggestions = state.suggestions;
  if (suggestionBusy(suggestions)) return;
  if (operation && !suggestions.uncertain) {
    if (!(await confirmDiscard("suggestions")) || !suggestionCurrent(suggestions) || suggestionBusy(suggestions)) return;
    const detail = suggestions.detail;
    if (detail?.suggestion.suggestion_id !== id || detail.suggestion.status !== "open" ||
        (operation === "accept" ? !canAcceptSuggestion(suggestions) : !detail.suggestion.can_reject)) return;
    clearSuggestionComposer(suggestions);
    suggestions.composer = { operation, suggestionId: id, quote: detail.quote, replacement: detail.replacement_text,
      revision: 0, documentRevision: suggestions.session.revision };
  }
  const composer = suggestions.composer;
  if (!composer) return;
  if (!suggestions.attempt) {
    if (composer.operation === "create" && $("suggestion-prepare").disabled) return;
    const revision = suggestions.session.revision;
    const detailRequest = suggestions.detailRequest;
    if (composer.operation !== "create") {
      suggestions.preparing = true; updateEditorState();
      $("suggestions-status").textContent = "Vorschlag und aktuelle Berechtigung werden geprüft …";
      try {
        const base = `/v1/office/documents/${encodeURIComponent(suggestions.session.objectId)}`;
        const [detail, head] = await Promise.all([
          api(`${suggestionBase(suggestions)}/${encodeURIComponent(composer.suggestionId)}`, { signal: suggestions.controller.signal }, suggestions.context),
          composer.operation === "accept" ? api(`${base}/content`, { signal: suggestions.controller.signal }, suggestions.context) : null,
        ]);
        if (!suggestionCurrent(suggestions) || suggestions.composer !== composer || suggestions.detailRequest !== detailRequest || suggestions.session.revision !== revision) return;
        if (!validSuggestionDetail(detail, suggestions, composer.suggestionId)) throw new ApiError(502);
        suggestions.detail = detail; suggestions.currentVersionId = detail.current_version_id;
        if (detail.suggestion.status !== "open") throw new ApiError(409);
        if (composer.operation === "accept") {
          const content = validatedContent(head, suggestions.session.objectId);
          if (head.can_write !== true || head.document.can_write !== true) throw new ApiError(403);
          if (head.version.version_id !== suggestions.versionId ||
              detail.current_version_id !== head.version.version_id || !detail.suggestion.can_accept) throw new ApiError(409);
          if (isDirty() || suggestions.session.historical || !state.editor.schema.nodeFromJSON(content).eq(state.editor.state.doc) ||
              head.version.title !== $("document-title").value.trim()) throw new ApiError(409);
        } else if (!detail.suggestion.can_reject) throw new ApiError(403);
        composer.quote = detail.quote; composer.replacement = detail.replacement_text;
      } catch (error) {
        if (!suggestionCurrent(suggestions)) return;
        if (denied(error)) { officeAccessDenied(); return; }
        suggestions.detail = null; renderSuggestions(suggestions);
        suggestions.conflict = error instanceof ApiError && error.status === 409;
        $("suggestions-status").textContent = suggestions.conflict
          ? "Der Stand hat sich geändert. Ihr Entwurf bleibt erhalten. Aktualisieren Sie die Vorschläge."
          : "Der Vorschlag konnte nicht geprüft werden. Bitte erneut aktualisieren; Ihr Entwurf bleibt erhalten.";
        return;
      } finally {
        if (suggestionCurrent(suggestions)) { suggestions.preparing = false; updateEditorState(); }
      }
    }
    if (!suggestionCurrent(suggestions) || suggestions.composer !== composer || suggestions.session.revision !== revision) return;
    const payload = { mutation_reference: mutationReference(), human_confirmation: true };
    if (composer.operation === "create") Object.assign(payload, { anchor_version_id: suggestions.versionId,
      expected_current_version_id: suggestions.versionId, anchor: composer.anchor, replacement_text: composer.replacement });
    else Object.assign(payload, { operation: composer.operation, expected_revision: suggestions.detail.suggestion.revision,
      ...(composer.operation === "accept" ? { expected_current_version_id: suggestions.versionId } : {}) });
    suggestions.attempt = { operation: composer.operation, suggestionId: composer.suggestionId, composerRevision: composer.revision,
      documentRevision: suggestions.session.revision, payload };
  }
  const labels = { create: "Änderungsvorschlag speichern", accept: "Annehmen und neue Version speichern", reject: "Änderungsvorschlag ablehnen" };
  const attempt = suggestions.attempt;
  $("suggestion-confirm-title").textContent = labels[attempt.operation];
  $("suggestion-confirm-submit").textContent = labels[attempt.operation];
  $("suggestion-confirm-summary").textContent = `${labels[attempt.operation]} · Fassung vom ${dateLabel(suggestions.session.version.created_at_utc)}.${suggestions.uncertain ? " Derselbe Vorgang wird erneut geprüft." : attempt.operation === "accept" ? " Die Textänderung wird unmittelbar als neue Dokumentversion gespeichert. Frühere Fassungen bleiben erhalten." : " Der Dokumenttext bleibt unverändert."}`;
  $("suggestion-confirm-before").textContent = composer.quote;
  $("suggestion-confirm-after").textContent = composer.replacement || "Textstelle löschen (leerer Ersatztext)";
  $("suggestion-confirm-label").textContent = attempt.operation === "accept"
    ? "Ich bestätige die Annahme dieses Vorschlags und die Speicherung einer neuen Dokumentversion."
    : "Ich bestätige, dass diese Vorschlagsaktion verbindlich gespeichert werden soll.";
  $("suggestion-confirm-checkbox").checked = false; $("suggestion-confirm-submit").disabled = true;
  $("suggestion-confirm-message").textContent = ""; $("suggestion-confirm-dialog").showModal();
}
async function saveSuggestionOperation(event) {
  event.preventDefault();
  const suggestions = state.suggestions;
  if (suggestionBusy(suggestions) || !$("suggestion-confirm-checkbox").checked || !suggestions.attempt ||
      suggestions.attempt.composerRevision !== suggestions.composer?.revision) return;
  const attempt = suggestions.attempt;
  if (!suggestions.uncertain && attempt.operation !== "reject" && (isDirty() || suggestions.session.historical ||
      suggestions.session.conflict || attempt.documentRevision !== suggestions.session.revision)) {
    closeSuggestionConfirmation(); updateSuggestionControls(); return;
  }
  suggestions.saving = true;
  let acknowledged = false;
  $("suggestion-confirm-dialog").querySelectorAll("button,input").forEach((control) => { control.disabled = true; });
  $("suggestion-confirm-message").textContent = "Vorschlagsaktion wird gespeichert …";
  updateEditorState();
  try {
    const path = `${suggestionBase(suggestions)}${attempt.suggestionId ? `/${encodeURIComponent(attempt.suggestionId)}/decisions` : ""}`;
    const result = await api(path, { method: "POST", body: attempt.payload }, suggestions.context);
    if (!suggestionCurrent(suggestions)) return;
    const expectedStatus = { create: "open", accept: "accepted", reject: "rejected" }[attempt.operation];
    if (!validSuggestionDetail(result, suggestions, attempt.suggestionId) || result.suggestion.status !== expectedStatus ||
        result.applied_revision !== result.suggestion.revision || typeof result.replayed !== "boolean" ||
        result.quote !== suggestions.composer.quote || result.replacement_text !== suggestions.composer.replacement) throw new ApiError(502);
    if (attempt.operation === "create" && (result.suggestion.anchor.from !== attempt.payload.anchor.from ||
        result.suggestion.anchor.to !== attempt.payload.anchor.to)) throw new ApiError(502);
    if (attempt.operation === "accept") {
      const content = result.document_result;
      if (!contentMatches(content, suggestions.session.objectId, result.suggestion.result_version_id) ||
          content.version.previous_version_id !== attempt.payload.expected_current_version_id) throw new ApiError(502);
      validateEditorDocument(state.editor.schema.nodeFromJSON(normalizedDocument(content.content)));
    } else if (result.document_result !== null) throw new ApiError(502);
    // The write is acknowledged here. Refresh failures must never create another mutation.
    acknowledged = true;
    suggestions.settling = true;
    clearSuggestionComposer(suggestions); suggestions.saving = false;
    const success = { create: "Vorschlag gespeichert.", accept: "Vorschlag angenommen. Neue Version gespeichert.", reject: "Vorschlag abgelehnt." }[attempt.operation];
    if (attempt.operation === "accept") {
      const session = suggestions.session;
      acceptContent(result.document_result, session);
      notice(`${success}${result.document_result.is_current_version ? "" : " Inzwischen gibt es eine neuere Fassung. Öffnen Sie die aktuelle Version über „Aktuelle Version“."}`);
      await loadDocuments();
      if (sessionCurrent(session) && suggestionPanelOpen()) {
        await loadSuggestions();
        if (sessionCurrent(session)) $("suggestions-status").textContent = `${success} ${$("suggestions-status").textContent}`;
      }
    } else {
      const refreshed = await loadSuggestions();
      if (refreshed && suggestionCurrent(suggestions)) await loadSuggestionDetail(result.suggestion.suggestion_id);
      if (suggestionCurrent(suggestions)) $("suggestions-status").textContent = `${success} ${$("suggestions-status").textContent}`;
    }
  } catch (error) {
    if (!suggestionCurrent(suggestions)) return;
    closeSuggestionConfirmation();
    if (denied(error)) { officeAccessDenied(); return; }
    if (acknowledged) {
      clearSuggestionComposer(suggestions);
      $("suggestions-status").textContent = "Vorschlagsaktion gespeichert. Die Ansicht konnte nicht aktualisiert werden; laden Sie die Vorschläge erneut.";
      return;
    }
    if (error instanceof ApiError && error.status === 409) {
      suggestions.attempt = null; suggestions.uncertain = false; suggestions.conflict = true;
      $("suggestions-status").textContent = "Der Stand hat sich geändert. Ihr Entwurf bleibt erhalten. Aktualisieren Sie die Vorschläge.";
    } else if (error instanceof ApiError && [400, 413, 422].includes(error.status)) {
      suggestions.attempt = null; suggestions.uncertain = false;
      $("suggestions-status").textContent = "Der Vorschlag konnte nicht gespeichert werden. Prüfen Sie Textauswahl und Ersatztext; Ihr Entwurf bleibt erhalten.";
    } else {
      suggestions.uncertain = true;
      $("suggestions-status").textContent = "Speicherung nicht bestätigt. Prüfen Sie denselben Vorgang erneut.";
    }
    if (attempt.operation !== "create") {
      $("suggestion-composer-title").textContent = "Vorschlagsaktion prüfen";
      $("suggestion-before").textContent = suggestions.composer.quote;
      $("suggestion-replacement").value = suggestions.composer.replacement;
      $("suggestion-composer").hidden = !suggestions.uncertain;
    }
  } finally {
    if (suggestionCurrent(suggestions)) {
      suggestions.saving = false; suggestions.settling = false;
      $("suggestion-confirm-dialog").querySelectorAll("button,input").forEach((control) => { control.disabled = false; });
      $("suggestion-confirm-submit").disabled = true; updateEditorState();
    }
  }
}

async function hideInspectorWithReview() {
  const review = state.review;
  const suggestions = state.suggestions;
  if ((review || suggestions) && (!(await confirmDiscard("inspector")) || state.review !== review || state.suggestions !== suggestions)) return;
  if (review) clearReview();
  if (suggestions) clearSuggestions();
  toggleInspector(false);
  updateEditorState();
}

function toggleInspector(show) {
  if (!show) cancelHistoryRead(state.session);
  $("office-shell").classList.toggle("inspector-hidden", !show);
  $("inspector-toggle").setAttribute("aria-expanded", String(show));
}

async function selectInspector(name) {
  const review = state.review;
  const suggestions = state.suggestions;
  const epoch = state.epoch;
  if (name === "history" && (state.session?.saving || review?.saving || review?.settling ||
      suggestions?.preparing || suggestions?.saving || suggestions?.settling)) return;
  if (name !== "comments" && name !== "history" && review) {
    if (!(await confirmDiscard("comments")) || state.review !== review) return;
    clearReview();
  }
  if (name !== "suggestions" && name !== "history" && suggestions) {
    if (!(await confirmDiscard("suggestions")) || state.suggestions !== suggestions || state.epoch !== epoch) return;
    clearSuggestions();
    updateEditorState();
  }
  if (name !== "history") cancelHistoryRead(state.session);
  ["outline", "history", "comments", "suggestions"].forEach((candidate) => {
    const active = name === candidate;
    $(`${candidate}-tab`).setAttribute("aria-selected", String(active));
    $(`${candidate}-tab`).tabIndex = active ? 0 : -1;
    $(`${candidate}-panel`).hidden = !active;
  });
  $("document-inspector").classList.toggle("comments-active", name === "comments");
  $("document-inspector").classList.toggle("suggestions-active", name === "suggestions");
  if (name === "history") { clearReviewHighlight(); loadHistory(); }
  if (name === "comments") {
    $("office-shell").classList.remove("focus-mode");
    $("focus-toggle").setAttribute("aria-pressed", "false");
    toggleInspector(true);
    if (!reviewCurrent(state.review)) loadReview();
  }
  if (name === "suggestions") {
    $("office-shell").classList.remove("focus-mode");
    $("focus-toggle").setAttribute("aria-pressed", "false");
    toggleInspector(true);
    if (!suggestionCurrent(state.suggestions)) loadSuggestions();
  }
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
$("document-print").addEventListener("click", openPrint);
$("document-reuse").addEventListener("click", openReuse);
$("reuse-form").addEventListener("submit", submitReuse);
$("reuse-title").addEventListener("input", () => {
  const reuse = state.reuse;
  if (!reuse) return;
  reuse.request += 1;
  reuse.controller?.abort();
  if (reuse.discardResolve && state.discardResolve === reuse.discardResolve) settleDiscard(false);
  reuse.discardResolve = null;
  reuse.busy = false;
  $("reuse-status").textContent = "";
  updateReuseControls();
});
["reuse-close", "reuse-cancel"].forEach((id) => $(id).addEventListener("click", () => closeReuse(true)));
$("reuse-dialog").addEventListener("cancel", (event) => { event.preventDefault(); closeReuse(true); });
$("reuse-dialog").addEventListener("close", () => { if (!$("reuse-dialog").open && state.reuse) closeReuse(); });
$("print-close").addEventListener("click", () => closePrint(true));
$("print-dialog").addEventListener("cancel", (event) => { event.preventDefault(); closePrint(true); });
$("print-dialog").addEventListener("close", () => {
  if (!$("print-dialog").open && state.print && !state.print.dialogTransition) closePrint();
});
$("print-refresh").addEventListener("click", () => loadPrintContent());
$("print-submit").addEventListener("click", () => loadPrintContent(state.print, true));
["print-paper", "print-orientation"].forEach((id) => $(id).addEventListener("change", updatePrintControls));
window.addEventListener("beforeprint", () => {
  if (!state.preparedPrint || !printCurrent(state.preparedPrint) || !state.preparedPrint.printing) clearPreparedPrint();
});
window.addEventListener("afterprint", () => clearPreparedPrint());
$("document-close").addEventListener("click", async () => { if (await confirmDiscard()) { clearWorkspace(); renderDocuments(); } });
$("documents-refresh").addEventListener("click", () => loadDocuments({ revalidateSource: true }));
$("documents-search").addEventListener("input", () => scheduleDocumentSearch());
$("documents-search").addEventListener("keydown", (event) => {
  if (event.key === "Enter" && !event.isComposing) { event.preventDefault(); scheduleDocumentSearch(true); }
});
$("documents-clear").addEventListener("click", () => {
  $("documents-search").value = ""; scheduleDocumentSearch(true); $("documents-search").focus();
});
$("documents-load-more").addEventListener("click", () => loadDocuments({ append: true }));
$("documents-retry").addEventListener("click", () => loadDocuments({
  append: state.listRetry === "append", revalidateSource: state.listRetry === "refresh",
}));
$("history-refresh").addEventListener("click", loadHistory);
$("history-more").addEventListener("click", () => loadHistory({ append: true }));
$("history-retry").addEventListener("click", () => loadHistory({ append: state.session?.history.retry === "append" }));
$("compare-history-refresh").addEventListener("click", () => {
  if (state.compare) loadVersionPage(state.compare, false, true);
});
$("compare-history-more").addEventListener("click", () => {
  if (state.compare) loadVersionPage(state.compare, true, true);
});
$("compare-history-retry").addEventListener("click", () => {
  if (state.compare) loadVersionPage(state.compare, state.compare.history.retry === "append", true);
});
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
$("comments-tab").addEventListener("click", () => selectInspector("comments"));
$("comments-toggle").addEventListener("click", () => selectInspector("comments"));
$("comments-close").addEventListener("click", async () => {
  const review = state.review;
  if (!(await confirmDiscard("comments")) || state.review !== review) return;
  clearReview(); toggleInspector(false); updateEditorState(); $("comments-toggle").focus();
});
$("comments-refresh").addEventListener("click", () => loadReview());
$("comments-more").addEventListener("click", () => loadReview(true));
$("comment-new").addEventListener("click", () => beginReviewComposer("create"));
$("comment-selection").addEventListener("mousedown", (event) => { if (event.button === 0) event.preventDefault(); });
$("comment-selection").addEventListener("click", () => {
  const selection = selectedReviewAnchor();
  if (selection) beginReviewComposer("create", null, selection);
});
$("comment-body").addEventListener("input", () => {
  const review = state.review;
  if (!reviewCurrent(review) || !review.composer || review.saving || review.uncertain) return;
  review.composer.body = $("comment-body").value;
  review.composer.revision += 1;
  review.attempt = null;
  closeReviewConfirmation();
  updateReviewControls();
});
$("comment-prepare").addEventListener("click", () => prepareReviewOperation());
$("comment-cancel").addEventListener("click", async () => {
  const review = state.review;
  if (!(await confirmDiscard("comments")) || !reviewCurrent(review)) return;
  clearReviewComposer(review); $("comment-new").focus();
});
$("comment-confirm-checkbox").addEventListener("change", () => { $("comment-confirm-submit").disabled = !$("comment-confirm-checkbox").checked; });
$("comment-confirm-form").addEventListener("submit", saveReviewOperation);
$("comment-confirm-cancel").addEventListener("click", () => { if (!state.review?.saving) closeReviewConfirmation(); });
$("comment-confirm-dialog").addEventListener("cancel", (event) => { event.preventDefault(); if (!state.review?.saving) closeReviewConfirmation(); });
$("suggestions-tab").addEventListener("click", () => selectInspector("suggestions"));
$("suggestions-toggle").addEventListener("mousedown", (event) => { if (event.button === 0) event.preventDefault(); });
$("suggestions-toggle").addEventListener("click", () => selectInspector("suggestions"));
$("suggestions-close").addEventListener("click", async () => {
  const suggestions = state.suggestions;
  if (!(await confirmDiscard("suggestions")) || state.suggestions !== suggestions) return;
  clearSuggestions(); toggleInspector(false); updateEditorState(); $("suggestions-toggle").focus();
});
$("suggestions-refresh").addEventListener("click", () => loadSuggestions());
$("suggestions-more").addEventListener("click", () => loadSuggestions(true));
$("suggestion-new").addEventListener("mousedown", (event) => { if (event.button === 0) event.preventDefault(); });
$("suggestion-new").addEventListener("click", beginSuggestion);
$("suggestion-replacement").addEventListener("input", () => {
  const suggestions = state.suggestions;
  if (!suggestionCurrent(suggestions) || suggestions.composer?.operation !== "create" || suggestionBusy(suggestions) || suggestions.uncertain) return;
  suggestions.composer.replacement = $("suggestion-replacement").value;
  suggestions.composer.revision += 1; suggestions.attempt = null;
  closeSuggestionConfirmation(); updateSuggestionControls();
});
$("suggestion-prepare").addEventListener("click", () => prepareSuggestionOperation());
$("suggestion-cancel").addEventListener("click", async () => {
  const suggestions = state.suggestions;
  if (!(await confirmDiscard("suggestions")) || !suggestionCurrent(suggestions)) return;
  clearSuggestionComposer(suggestions); $("suggestion-new").focus();
});
$("suggestion-confirm-checkbox").addEventListener("change", () => { $("suggestion-confirm-submit").disabled = !$("suggestion-confirm-checkbox").checked; });
$("suggestion-confirm-form").addEventListener("submit", saveSuggestionOperation);
$("suggestion-confirm-cancel").addEventListener("click", () => { if (!state.suggestions?.saving) closeSuggestionConfirmation(); });
$("suggestion-confirm-dialog").addEventListener("cancel", (event) => { event.preventDefault(); if (!state.suggestions?.saving) closeSuggestionConfirmation(); });
$("inspector-toggle").addEventListener("click", () => {
  if (!$("office-shell").classList.contains("inspector-hidden")) hideInspectorWithReview();
  else {
    toggleInspector(true);
    if ($("comments-tab").getAttribute("aria-selected") === "true" && !reviewCurrent(state.review)) loadReview();
    if ($("suggestions-tab").getAttribute("aria-selected") === "true" && !suggestionCurrent(state.suggestions)) loadSuggestions();
  }
});
$("documents-toggle").addEventListener("click", () => {
  const open = $("office-shell").classList.toggle("documents-open");
  $("documents-toggle").setAttribute("aria-expanded", String(open));
});
$("focus-toggle").addEventListener("click", async () => {
  const review = state.review;
  const suggestions = state.suggestions;
  if ((review || suggestions) && !$("office-shell").classList.contains("focus-mode")) {
    if (!(await confirmDiscard("inspector")) || state.review !== review || state.suggestions !== suggestions) return;
    clearReview();
    clearSuggestions();
    updateEditorState();
  }
  const active = $("office-shell").classList.toggle("focus-mode");
  if (active) cancelHistoryRead(state.session);
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
  button.addEventListener("click", () => formatEditor((chain) => chain[commandNames[button.dataset.command]](),
    ["bulletList", "orderedList", "blockquote"].includes(button.dataset.command)));
});
$("text-style").addEventListener("change", () => changeTextStyle($("text-style").value));
$("list-options").addEventListener("mousedown", (event) => { if (event.button === 0) event.preventDefault(); });
$("list-options").addEventListener("click", openListDialog);
$("list-indent").addEventListener("click", () => changeListLevel("indent"));
$("list-outdent").addEventListener("click", () => changeListLevel("outdent"));
$("list-form").addEventListener("submit", (event) => { event.preventDefault(); applyListStart(); });
["list-close", "list-cancel"].forEach((id) => $(id).addEventListener("click", () => closeListDialog(true)));
$("list-dialog").addEventListener("cancel", (event) => { event.preventDefault(); closeListDialog(true); });
$("list-dialog").addEventListener("close", () => { if (!$("list-dialog").open && state.listAction) closeListDialog(); });
for (const [key, id] of Object.entries(characterFields)) {
  for (const value of OFFICE_CHARACTER_VALUES[key]) {
    const option = node("option", key === "fontSize" ? `${value} pt` : OFFICE_TEXT_COLORS[value]);
    option.value = String(value); $(id).append(option);
  }
  $(id).addEventListener("change", () => { $("character-status").textContent = characterHelp; $("character-status").classList.remove("error"); });
}
for (const [key, id] of Object.entries(styleFields)) {
  for (const option of $(paragraphFields[key] || characterFields[key]).options) {
    if (option.value !== "mixed") $(id).append(option.cloneNode(true));
  }
  $(id).addEventListener("change", previewDocumentStyle);
}
$("style-options").addEventListener("mousedown", (event) => { if (event.button === 0) event.preventDefault(); });
$("style-options").addEventListener("click", openStyleDialog);
$("style-choice").addEventListener("change", chooseDocumentStyle);
$("style-form").addEventListener("submit", (event) => { event.preventDefault(); commitDocumentStyle("apply"); });
$("style-update").addEventListener("click", () => commitDocumentStyle("update"));
$("style-remove").addEventListener("click", () => commitDocumentStyle("remove"));
["style-close", "style-cancel"].forEach((id) => $(id).addEventListener("click", () => closeStyleDialog(true)));
$("style-dialog").addEventListener("cancel", (event) => { event.preventDefault(); closeStyleDialog(true); });
$("style-dialog").addEventListener("close", () => { if (!$("style-dialog").open && state.styleAction) closeStyleDialog(); });
$("character-format").addEventListener("mousedown", (event) => { if (event.button === 0) event.preventDefault(); });
$("character-format").addEventListener("click", openCharacterDialog);
$("format-transfer").addEventListener("change", (event) => {
  const choice = event.target.value;
  event.target.value = "";
  if (choice === "copy") copyFormat();
  else if (choice === "clear") { state.formatSample = null; updateFormatTransfer(); notice("Aufgenommenes Format verworfen."); focusEditor(); }
  else applyTransferredFormat(choice);
});
$("character-form").addEventListener("submit", (event) => { event.preventDefault(); applyCharacterFormat(); });
$("character-reset").addEventListener("click", () => {
  if (!characterActionCurrent(state.characterAction)) { closeCharacterDialog(); return; }
  Object.values(characterFields).forEach((id) => { $(id).value = "default"; });
  $("character-status").textContent = "Standard ist ausgewählt. Erst „Anwenden“ ändert die Formatierung.";
});
["character-close", "character-cancel"].forEach((id) => $(id).addEventListener("click", () => closeCharacterDialog(true)));
$("character-dialog").addEventListener("cancel", (event) => { event.preventDefault(); closeCharacterDialog(true); });
$("character-dialog").addEventListener("close", () => { if (!$("character-dialog").open && state.characterAction) closeCharacterDialog(); });
$("paragraph-format").addEventListener("mousedown", (event) => { if (event.button === 0) event.preventDefault(); });
$("paragraph-format").addEventListener("click", openParagraphDialog);
$("paragraph-form").addEventListener("submit", (event) => { event.preventDefault(); applyParagraphFormat(); });
$("paragraph-reset").addEventListener("click", () => {
  if (!paragraphActionCurrent(state.paragraphAction)) { closeParagraphDialog(); return; }
  Object.values(paragraphFields).forEach((id) => { $(id).value = "default"; });
  $("paragraph-status").textContent = "Standard ist ausgewählt. Erst „Auf Auswahl anwenden“ ändert Ihren Entwurf.";
  $("paragraph-status").classList.remove("error");
});
Object.values(paragraphFields).forEach((id) => $(id).addEventListener("change", () => {
  $("paragraph-status").textContent = paragraphHelp;
  $("paragraph-status").classList.remove("error");
}));
["paragraph-close", "paragraph-cancel"].forEach((id) => $(id).addEventListener("click", () => closeParagraphDialog(true)));
$("paragraph-dialog").addEventListener("cancel", (event) => { event.preventDefault(); closeParagraphDialog(true); });
$("paragraph-dialog").addEventListener("close", () => {
  if (!$("paragraph-dialog").open && state.paragraphAction) closeParagraphDialog();
});
$("insert-menu").addEventListener("change", () => {
  const command = $("insert-menu").value;
  if (command) {
    if (command === "insertTable") insertTable();
    else if (command === "insertTableCustom") openTableInsert();
    else if (command === "pageBreak") changePageBreak();
    else if (command === "removePageBreak") changePageBreak(true);
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
  if (action.transaction) {
    commitTableTransaction(action.transaction, "Dokumentinhalt geändert. Rückgängig ist möglich; gespeichert wird erst nach Ihrer Bestätigung.");
    return;
  }
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
    const tabs = ["outline", "history", "comments", "suggestions"];
    const position = tabs.findIndex((name) => tab.id === `${name}-tab`);
    const target = event.key === "Home" ? "outline" : event.key === "End" ? "suggestions" :
      tabs[(position + (event.key === "ArrowRight" ? 1 : -1) + tabs.length) % tabs.length];
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
  clearDocumentList(true);
  localStorage.setItem(storageKey, JSON.stringify(context));
  $("tenant-label").textContent = context.tenantId;
  $("context-panel").hidden = true;
  $("context-toggle").setAttribute("aria-expanded", "false");
  renderDocuments();
  loadDocuments();
});
document.addEventListener("keydown", (event) => {
  if ((event.ctrlKey || event.metaKey) && event.key.toLowerCase() === "p") {
    event.preventDefault(); openPrint(); return;
  }
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
  if (isDirty() || state.session?.saving || state.session?.uncertain || hasReviewDraft() || state.review?.saving || hasSuggestionDraft() || state.suggestions?.saving) { event.preventDefault(); event.returnValue = ""; }
});

const imageControls = installOfficeImageControls({ state,
  allowed: () => paragraphAllowed() && (state.editor.state.selection.empty || state.editor.state.selection.node?.type.name === "image"),
  current: characterActionCurrent,
  validate: validateEditorDocument, focus: focusEditor, notice, accessDenied: officeAccessDenied });
restoreContext();
toggleInspector(!window.matchMedia("(max-width: 1000px)").matches);
window.matchMedia("(max-width: 1000px)").addEventListener("change", (event) => {
  if (event.matches && !hasReviewDraft() && !state.review?.saving && !hasSuggestionDraft() && !state.suggestions?.saving) {
    clearReview(); clearSuggestions(); toggleInspector(false);
  }
});
loadDocuments();
