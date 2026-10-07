import { officeRunningSettings, officeRunningDescription, officeRunningNumber, officeResolveRunningFields, configureOfficeRunningPrint, clearOfficeRunningPrint } from "./office-running.mjs";
import { Editor, Extension, Mark, Node, textblockTypeInputRule } from "@tiptap/core";
import StarterKit from "@tiptap/starter-kit";
import { Table, TableKit } from "@tiptap/extension-table";
import { AllSelection, NodeSelection, Plugin, PluginKey, Selection, TextSelection } from "@tiptap/pm/state";
import { sinkListItem, liftListItem } from "@tiptap/pm/schema-list";
import { closeHistory } from "@tiptap/pm/history";
import { Decoration, DecorationSet } from "@tiptap/pm/view";
import {
  addRowBefore, addRowAfter, addColumnBefore, addColumnAfter, deleteRow, deleteColumn,
  deleteTable, mergeCells, splitCell, toggleHeaderColumn, goToNextCell, selectedRect, isInTable, CellSelection, TableMap,
} from "@tiptap/pm/tables";
import { compareOfficeDocuments, describeOfficeBlock } from "./office-comparison.mjs";
import { findDocumentMatches, replaceDocumentMatches, OfficeSearchLimitError } from "./office-search.mjs";
import { renderOfficePrintDocument } from "./office-print.mjs";
import { OFFICE_PAGE_SIDES, officePageSettings, officePageDescription, officePagePreview, configureOfficePrintPage } from "./office-page.mjs";
import { installOfficePageControls } from "./office-page-controls.mjs";
import { OFFICE_SECTION_LIMIT, clearOfficeSectionPrint, configureOfficeSectionPrint, officeSectionDescription, officeSectionProfile } from "./office-sections.mjs";
import { OfficeImageReadError, officeImageAttributes, officeImageReferences, loadOfficePrintImages } from "./office-images.mjs";
import { officeImageExtension, installOfficeImageControls } from "./office-image-controls.mjs";
import { officeImageGroupAttributes } from "./office-image-groups.mjs";
import { officeImageGroupExtension } from "./office-image-group-extension.mjs";
import { officeShapeAttributes } from "./office-shapes.mjs";
import { officeShapeExtension, installOfficeShapeControls } from "./office-shape-controls.mjs";
import { officeChartExtension, installOfficeChartControls } from "./office-chart-controls.mjs";
import { officeChartAttributes } from "./office-charts.mjs";
import { officeShapeGroupAttributes } from "./office-shape-groups.mjs";
import { officeShapeGroupExtension } from "./office-shape-group-extension.mjs";
import { OFFICE_PARAGRAPH_VALUES, officeParagraphAttributes, officeParagraphDOMAttributes, officeParagraphDescription } from "./office-paragraph.mjs";
import { OFFICE_CHARACTER_VALUES, OFFICE_TEXT_COLORS, officeCharacterAttributes, officeCharacterDOMAttributes, officeCharacterDescription } from "./office-character.mjs";
import { OFFICE_STYLE_LIMIT, OFFICE_STYLE_PRESETS, officeStyles, officeStyleFor, officeTextblockAttributes } from "./office-styles.mjs";
import { officeLinkDOMAttributes, officeLinkHref } from "./office-links.mjs";
import { OFFICE_BOOKMARK_LIMIT, officeBookmarkAttributes, officeBookmarkDescription, officeBookmarkInventory, officeReferenceInventory, officeCrossReferenceAttributes, officeCrossReferenceDescription } from "./office-bookmarks.mjs";
import { OFFICE_NUMBERED_TABLE_LIMIT, duplicateOfficeTableColumns, duplicateOfficeTableRows, moveOfficeTableColumns, moveOfficeTableRows, officeTableAttributes, officeTableCaption, officeTableCellAttributes, officeTableCellDOMAttributes, officeTableCellText, officeTableDOMAttributes, officeTableFormulaSource, officeTableFragment, officeTableGrid, officeTableInventory, officeTableReorderInfo, officeTableSortInfo, sortOfficeTable } from "./office-tables.mjs";
import { clearOfficeTableFormula, officeTableFromTSV, pasteOfficeTableCells, recalculateOfficeTableFormulas, remapOfficeTableFormulas, setOfficeTableFormula } from "./office-table-formulas.mjs";
import { officeBibliographyLabel, officeCitationAttributes, officeCitationLabel, officeCitationSources, officeDocumentFields, officeEquationAttributes, officeFieldAttributes, officeNoteAttributes, officeOpaqueId, officeSemanticInventory } from "./office-semantics.mjs";
import { OFFICE_DOCUMENT_REFERENCE_LIMIT, officeDocumentReferenceAttributes, officeDocumentReferenceDescription, officeDocumentReferenceKey, officeDocumentReferenceResolutions } from "./office-document-references.mjs";
import { officeDocumentCardAttributes, officeDocumentCardDescription, officeDocumentCardKey } from "./office-document-cards.mjs";
import { officeDocumentCardExtension, installOfficeDocumentCardControls } from "./office-document-card-controls.mjs";
import { OFFICE_BACKLINK_PAGE_MAX, officeBacklinkPage } from "./office-backlinks.mjs";

const $ = (id) => document.getElementById(id);
const storageKey = "collabio.workspace.context";
const state = {
  context: null, epoch: 0, listRequest: 0, documents: [], canCreate: false,
  session: null, editor: null, listLoading: false, listQuery: "", listCursor: null, listCursors: new Set(),
  listController: null, listTimer: null, listRetry: null, discardResolve: null, compare: null, restore: null,
  tableAction: null, formulaRecalculating: false, paragraphAction: null, characterAction: null, linkAction: null, bookmarkAction: null, crossReferenceAction: null, documentReferenceAction: null, documentReferenceResolutions: new Map(), backlinksAction: null, semanticAction: null, listAction: null, styleAction: null, sectionAction: null, formatSample: null, review: null, suggestions: null, print: null, preparedPrint: null, reuse: null,
};
const searchKey = new PluginKey("officeSearch");
const search = { query: "", matches: [], index: -1, windowStart: 0, notice: "" };
const searchHighlightLimit = 200;
const allowedNodes = new Set([
  "doc", "paragraph", "heading", "text", "hardBreak", "bulletList", "orderedList", "listItem",
  "blockquote", "codeBlock", "horizontalRule", "table", "tableRow", "tableCell", "tableHeader", "image", "imageGroup", "shape", "shapeGroup", "pageBreak", "sectionBreak", "bookmark",
  "documentField", "noteReference", "citationReference", "tableOfContents", "bibliography", "equation", "referenceIndex", "documentCard", "chart",
]);
const allowedMarks = new Set(["bold", "italic", "strike", "code", "underline", "textStyle", "link", "crossReference", "documentReference"]);
const commandNames = {
  bold: "toggleBold", italic: "toggleItalic", underline: "toggleUnderline", strike: "toggleStrike",
  code: "toggleCode", bulletList: "toggleBulletList", orderedList: "toggleOrderedList",
  blockquote: "toggleBlockquote", undo: "undo", redo: "redo",
};
const OfficeTable = Table.extend({
  addAttributes() {
    const inert = () => ({ default: null, rendered: false });
    return { ...(this.parent?.() || {}), caption: inert(), tableId: inert(), style: inert(), width: inert(),
      align: inert(), columns: inert(), captionPosition: inert() };
  },
  renderHTML({ node }) {
    return ["table", { class: "office-table", ...officeTableDOMAttributes(node.attrs) },
      ["caption", { hidden: "", "data-office-table-caption": "" }, ""], ["tbody", 0]];
  },
  addNodeView() {
    return ({ node: tableNode }) => {
      const table = document.createElement("table"); table.className = "office-table";
      const caption = document.createElement("caption"); caption.hidden = true;
      caption.dataset.officeTableCaption = "";
      const body = document.createElement("tbody"); table.append(caption, body);
      const apply = (node) => {
        for (const name of ["data-office-table-style", "data-office-table-width", "data-office-table-align",
          "data-office-table-columns", "data-office-caption-position"]) table.removeAttribute(name);
        for (const [name, value] of Object.entries(officeTableDOMAttributes(node.attrs))) table.setAttribute(name, value);
      };
      apply(tableNode);
      return { dom: table, contentDOM: body,
        update(updated) { if (updated.type !== tableNode.type) return false; apply(updated); return true; },
        ignoreMutation(mutation) {
          return mutation.target === caption || caption.contains(mutation.target) ||
            (mutation.type === "attributes" && mutation.target === table);
        },
      };
    };
  },
});
const OfficeTableCellStyle = Extension.create({
  name: "officeTableCellStyle",
  addGlobalAttributes() {
    const attribute = (name) => ({ default: null, keepOnSplit: true, parseHTML: () => null,
      renderHTML: (attrs) => officeTableCellDOMAttributes(attrs)[name] ?
        { [name]: officeTableCellDOMAttributes(attrs)[name] } : {},
    });
    return [{ types: ["tableCell", "tableHeader"], attributes: {
      background: attribute("data-office-cell-fill"), verticalAlign: attribute("data-office-cell-vertical"),
      horizontalAlign: attribute("data-office-cell-align"), padding: attribute("data-office-cell-padding"),
      border: attribute("data-office-cell-border"), formula: attribute("data-office-cell-formula"),
      formulaResult: attribute("data-office-cell-formula-result"),
    } }];
  },
});
const OfficePageBreak = Node.create({
  name: "pageBreak", group: "block", atom: true, selectable: true, draggable: false,
  parseHTML: () => [],
  renderHTML: () => ["div", { class: "office-page-break", contenteditable: "false", role: "separator", "aria-label": "Seitenumbruch" }],
  renderText: () => "",
});
const OfficeSectionBreak = Node.create({
  name: "sectionBreak", group: "block", atom: true, selectable: true, draggable: false,
  addAttributes() { return { page: { default: null, rendered: false }, running: { default: null, rendered: false } }; },
  parseHTML: () => [],
  renderHTML: () => ["div", { class: "office-section-break", contenteditable: "false", role: "separator", "aria-label": "Abschnittsumbruch" }],
  renderText: () => "",
});
const OfficeNamedStyles = Extension.create({
  name: "officeNamedStyles",
  addGlobalAttributes() {
    return [
      { types: ["doc"], attributes: { styles: { default: [], rendered: false }, page: { default: null, rendered: false }, running: { default: null, rendered: false } } },
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
const OfficeLink = Mark.create({
  name: "link", inclusive: false, excludes: "code crossReference",
  addAttributes() { return { href: { default: null, rendered: false } }; },
  parseHTML() {
    return [{ tag: "a[data-office-link][href]", getAttrs: (element) => {
      try { return { href: officeLinkHref(element.getAttribute("href")) }; } catch { return false; }
    } }];
  },
  renderHTML({ mark }) { return ["a", officeLinkDOMAttributes(mark.attrs.href), 0]; },
});
const OfficeBookmark = Node.create({
  name: "bookmark", group: "inline", inline: true, atom: true, selectable: true,
  addAttributes() { return { id: { default: null, rendered: false }, label: { default: null, rendered: false } }; },
  parseHTML() {
    return [{ tag: "span[data-office-bookmark]", getAttrs: (element) => {
      try { return officeBookmarkAttributes({ id: element.getAttribute("data-office-bookmark"), label: element.getAttribute("data-office-bookmark-label") }); }
      catch { return false; }
    } }];
  },
  renderHTML({ node: bookmark }) {
    const attrs = officeBookmarkAttributes(bookmark.attrs);
    return ["span", { "data-office-bookmark": attrs.id, "data-office-bookmark-label": attrs.label,
      "aria-label": officeBookmarkDescription(attrs), contenteditable: "false" }, `🔖 ${attrs.label}`];
  },
});
const OfficeCrossReference = Mark.create({
  name: "crossReference", inclusive: false, excludes: "code link documentReference",
  addAttributes() { return { targetId: { default: null, rendered: false } }; },
  parseHTML() {
    return [{ tag: "span[data-office-cross-reference]", getAttrs: (element) => {
      try { return officeCrossReferenceAttributes({ targetId: element.getAttribute("data-office-cross-reference") }); }
      catch { return false; }
    } }];
  },
  renderHTML({ mark }) {
    const attrs = officeCrossReferenceAttributes(mark.attrs);
    return ["span", { "data-office-cross-reference": attrs.targetId }, 0];
  },
});
const OfficeDocumentReference = Mark.create({
  name: "documentReference", inclusive: false, excludes: "code link crossReference",
  addAttributes() { return { targetObjectId: { default: null, rendered: false }, targetVersionId: { default: null, rendered: false } }; },
  parseHTML() {
    return [{ tag: "span[data-office-document-reference][data-office-document-version]", getAttrs: (element) => {
      try { return officeDocumentReferenceAttributes({ targetObjectId: element.getAttribute("data-office-document-reference"),
        targetVersionId: element.getAttribute("data-office-document-version") }); } catch { return false; }
    } }];
  },
  renderHTML({ mark }) {
    const attrs = officeDocumentReferenceAttributes(mark.attrs);
    return ["span", { "data-office-document-reference": attrs.targetObjectId,
      "data-office-document-version": attrs.targetVersionId, "data-office-reference-status": "unavailable",
      title: "Dokumentziel nicht verfügbar" }, 0];
  },
});
const semanticAtom = (name, group, inline, attributes, label) => Node.create({
  name, group, inline, atom: true, selectable: true, draggable: false,
  addAttributes() { return Object.fromEntries(attributes.map((key) => [key, { default: key === "locator" ? "" : null, rendered: false }])); },
  parseHTML: () => [],
  renderHTML({ node }) { return [inline ? "span" : "div", { class: `office-semantic office-${name}`, contenteditable: "false", [`data-office-${name}`]: "" }, label(node.attrs)]; },
});
const OfficeDocumentField = semanticAtom("documentField", "inline", true, ["key"], (attrs) => `Feld · ${attrs.key || "?"}`);
const OfficeNoteReference = semanticAtom("noteReference", "inline", true, ["id", "kind", "text"], (attrs) => attrs.kind === "endnote" ? "Endnote" : "Fußnote");
const OfficeCitationReference = semanticAtom("citationReference", "inline", true, ["sourceId", "locator"], () => "Quelle");
const OfficeTableOfContents = semanticAtom("tableOfContents", "block", false, ["maxLevel"], () => "Inhaltsverzeichnis");
const OfficeBibliography = semanticAtom("bibliography", "block", false, [], () => "Literaturverzeichnis");
const OfficeEquation = semanticAtom("equation", "block", false, ["id", "source", "alt"], (attrs) => attrs.source || "Formel");
const OfficeReferenceIndex = semanticAtom("referenceIndex", "block", false, [], () => "Referenznavigator");
const OfficeSemantics = Extension.create({
  name: "officeSemantics",
  addGlobalAttributes() {
    return [{ types: ["doc"], attributes: {
      documentFields: { default: [], rendered: false }, citationSources: { default: [], rendered: false },
    } }];
  },
  addProseMirrorPlugins() {
    return [new Plugin({ view: (view) => {
      const refresh = () => {
        const inventory = officeSemanticInventory(view.state.doc.toJSON());
        view.dom.querySelectorAll("[data-office-documentField]").forEach((element) => {
          const position = view.posAtDOM(element, 0), node = view.state.doc.nodeAt(position);
          if (!node) return;
          const field = officeFieldAttributes(node.attrs, inventory.fieldMap);
          element.textContent = field.value; element.dataset.officeFieldKey = field.key;
          element.toggleAttribute("data-office-broken", !field.field);
        });
        let footnote = 0, endnote = 0;
        view.dom.querySelectorAll("[data-office-noteReference]").forEach((element) => {
          const position = view.posAtDOM(element, 0), node = view.state.doc.nodeAt(position);
          if (!node) return;
          const note = officeNoteAttributes(node.attrs), number = note.kind === "footnote" ? ++footnote : ++endnote;
          element.textContent = `${note.kind === "footnote" ? "Fußnote" : "Endnote"} ${number}`;
          element.title = note.text;
        });
        view.dom.querySelectorAll("[data-office-citationReference]").forEach((element) => {
          const position = view.posAtDOM(element, 0), node = view.state.doc.nodeAt(position);
          if (!node) return;
          const citation = officeCitationAttributes(node.attrs, inventory.sourceMap);
          element.textContent = officeCitationLabel(citation.source, citation.locator);
          element.toggleAttribute("data-office-broken", !citation.source);
        });
        view.dom.querySelectorAll("[data-office-tableOfContents]").forEach((element) => {
          const position = view.posAtDOM(element, 0), node = view.state.doc.nodeAt(position);
          const entries = inventory.headings.filter((heading) => heading.level <= (node?.attrs.maxLevel || 3));
          element.textContent = entries.length ? entries.map((entry) => `${"  ".repeat(entry.level - 1)}${entry.text}`).join("\n") : "Inhaltsverzeichnis · noch keine Überschriften";
        });
        view.dom.querySelectorAll("[data-office-bibliography]").forEach((element) => {
          element.textContent = inventory.sources.length ? inventory.sources.map(officeBibliographyLabel).join("\n") : "Literaturverzeichnis · noch keine Quellen";
        });
        view.dom.querySelectorAll("[data-office-referenceIndex]").forEach((element) => {
          element.textContent = inventory.references.length ? inventory.references.map((entry) => `${entry.kind}: ${entry.label}${entry.broken ? " (fehlt)" : ""}`).join("\n") : "Referenznavigator · noch keine Referenzen";
        });
      };
      refresh(); return { update: refresh };
    } })];
  },
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
  officeBookmarkInventory(document);
  officeReferenceInventory(document);
  officeTableInventory(document);
  officeSemanticInventory(document);
  const styles = officeStyles(document?.attrs?.styles || []);
  let nodes = 0;
  let characters = 0;
  let pageBreaks = 0;
  let sectionBreaks = 0;
  let documentReferences = 0;
  const chartIds = new Set();
  const imageGroupIds = new Set();
  const shapeIds = new Set();
  const shapeGroupIds = new Set();
  const walk = (value, depth = 0, parentType = null) => {
    if (!value || !allowedNodes.has(value.type) || ++nodes > 10000 || depth > 32) throw new Error("document-shape");
    const result = { type: value.type };
    if (value.type === "pageBreak" && (depth !== 1 || Object.keys(value).length !== 1 || ++pageBreaks > 100)) throw new Error("document-page-break");
    if (value.type === "sectionBreak") {
      if (depth !== 1 || Object.keys(value).sort().join(",") !== "attrs,type" || ++sectionBreaks > OFFICE_SECTION_LIMIT) throw new Error("document-section-break");
      result.attrs = officeSectionProfile(value.attrs);
    }
    if (value.type === "documentCard") {
      if (depth !== 1 || ++documentReferences > OFFICE_DOCUMENT_REFERENCE_LIMIT) throw new Error("document-reference-limit");
      result.attrs = officeDocumentCardAttributes(value.attrs);
    }
    if (value.type === "chart") {
      if (depth !== 1 || chartIds.size >= 20) throw new Error("document-chart");
      result.attrs = officeChartAttributes(value.attrs);
      if (chartIds.has(result.attrs.id)) throw new Error("document-chart");
      chartIds.add(result.attrs.id);
      characters += Array.from(result.attrs.title + result.attrs.altText).length;
      characters += result.attrs.categories.reduce((total, category) => total + Array.from(category).length, 0);
      characters += result.attrs.series.reduce((total, entry) => total + Array.from(entry.name).length, 0);
      if (characters > 100000) throw new Error("document-length");
    }
    if (value.type === "image") result.attrs = officeImageAttributes(value.attrs);
    if (value.type === "imageGroup") {
      if (depth !== 1 || !Array.isArray(value.content) || value.content.length < 2 || value.content.length > 8 ||
          value.content.some((child) => child.type !== "image" || child.attrs?.wrap != null || child.attrs?.position != null)) {
        throw new Error("document-image-group");
      }
      result.attrs = officeImageGroupAttributes(value.attrs);
      if (imageGroupIds.has(result.attrs.id) || imageGroupIds.size >= 20) throw new Error("document-image-group");
      imageGroupIds.add(result.attrs.id);
    }
    if (value.type === "shape") {
      if (depth !== 1 && parentType !== "shapeGroup") throw new Error("document-shape");
      result.attrs = officeShapeAttributes(value.attrs);
      if (shapeIds.has(result.attrs.id) || shapeIds.size >= 100) throw new Error("document-shape");
      shapeIds.add(result.attrs.id); characters += Array.from(result.attrs.text).length;
      if (characters > 100000) throw new Error("document-length");
    }
    if (value.type === "shapeGroup") {
      if (depth !== 1 || !Array.isArray(value.content) || value.content.length < 2 || value.content.length > 8 ||
          value.content.some((child) => child.type !== "shape" || child.attrs?.wrap != null || child.attrs?.position != null)) {
        throw new Error("document-shape-group");
      }
      result.attrs = officeShapeGroupAttributes(value.attrs);
      if (shapeGroupIds.has(result.attrs.id) || shapeGroupIds.size >= 20) throw new Error("document-shape-group");
      shapeGroupIds.add(result.attrs.id);
    }
    if (value.type === "bookmark") result.attrs = officeBookmarkAttributes(value.attrs);
    if (value.type === "documentField") result.attrs = { key: officeFieldAttributes(value.attrs, new Map()).key };
    if (value.type === "noteReference") result.attrs = officeNoteAttributes(value.attrs);
    if (value.type === "citationReference") {
      const citation = officeCitationAttributes(value.attrs, new Map());
      result.attrs = { sourceId: citation.sourceId, locator: citation.locator };
    }
    if (value.type === "tableOfContents") {
      if (depth !== 1 || ![1, 2, 3].includes(value.attrs?.maxLevel)) throw new Error("document-toc");
      result.attrs = { maxLevel: value.attrs.maxLevel };
    }
    if (["bibliography", "referenceIndex"].includes(value.type) && depth !== 1) throw new Error("document-generated-block");
    if (value.type === "equation") {
      if (depth !== 1) throw new Error("document-equation");
      result.attrs = officeEquationAttributes(value.attrs);
    }
    if (value.type === "table") {
      const attributes = officeTableAttributes(value.attrs);
      if (Object.keys(attributes).length) result.attrs = attributes;
    }
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
      result.attrs = officeTableCellAttributes(value.attrs);
    }
    if (value.marks?.length) {
      const types = value.marks.map((mark) => mark.type);
      if (value.type !== "text" || types.some((type) => !allowedMarks.has(type)) ||
          new Set(types).size !== types.length || (types.includes("code") && types.length > 1) ||
          (types.includes("link") && types.includes("crossReference")) ||
          (types.includes("documentReference") && types.some((type) => ["link", "crossReference"].includes(type)))) throw new Error("document-marks");
      result.marks = value.marks.flatMap((mark) => {
        if (mark.type === "link") return [{ type: "link", attrs: { href: officeLinkHref(mark.attrs?.href) } }];
        if (mark.type === "crossReference") return [{ type: "crossReference", attrs: officeCrossReferenceAttributes(mark.attrs) }];
        if (mark.type === "documentReference") {
          if (++documentReferences > OFFICE_DOCUMENT_REFERENCE_LIMIT) throw new Error("document-reference-limit");
          return [{ type: "documentReference", attrs: officeDocumentReferenceAttributes(mark.attrs) }];
        }
        if (mark.type !== "textStyle") return [{ type: mark.type }];
        const attrs = officeCharacterAttributes(mark.attrs);
        return Object.keys(attrs).length ? [{ type: mark.type, attrs }] : [];
      });
      if (!result.marks.length) delete result.marks;
    }
    if (value.content) {
      if (!Array.isArray(value.content)) throw new Error("document-content");
      result.content = value.content.map((child) => walk(child, depth + 1, value.type));
    }
    if (value.type === "table") {
      officeTableGrid(result);
    }
    return result;
  };
  if (document?.type !== "doc") throw new Error("document-root");
  if (!Array.isArray(document.content)) throw new Error("document-content");
  document.content.forEach((entry, index) => {
    if (entry?.type !== "sectionBreak") return;
    if (index === 0 || index === document.content.length - 1 ||
        ["pageBreak", "sectionBreak"].includes(document.content[index - 1]?.type) ||
        ["pageBreak", "sectionBreak"].includes(document.content[index + 1]?.type)) throw new Error("document-section-boundary");
  });
  const result = walk(document);
  if (styles.length) result.attrs = { styles };
  if (document.attrs?.running != null) result.attrs = { ...result.attrs, running: officeRunningSettings(document.attrs.running, document.attrs.page) };
  if (document.attrs?.page != null) result.attrs = { ...result.attrs, page: officePageSettings(document.attrs.page) };
  const fields = officeDocumentFields(document.attrs?.documentFields || []);
  const sources = officeCitationSources(document.attrs?.citationSources || []);
  if (fields.length) result.attrs = { ...result.attrs, documentFields: fields };
  if (sources.length) result.attrs = { ...result.attrs, citationSources: sources };
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
  updateBacklinkControls();
  const session = state.session;
  const editor = state.editor;
  if (editor) {
    try {
      const labels = new Map(officeTableInventory(editor.getJSON()).map(({ id, label }) => [id, label]));
      const attributes = [];
      const collect = (value) => {
        if (value.type === "table") attributes.push(officeTableAttributes(value.attrs));
        for (const child of value.content || []) collect(child);
      };
      collect(editor.getJSON());
      editor.view.dom.querySelectorAll("table.office-table").forEach((table, index) => {
        const attrs = attributes[index] || {}, caption = table.querySelector("caption[data-office-table-caption]");
        if (!caption) return;
        if (attrs.tableId) {
          table.id = officeTableFragment(attrs.tableId); table.dataset.officeTable = attrs.tableId;
          caption.hidden = false; caption.textContent = labels.get(attrs.tableId) || officeTableCaption(attrs, index + 1);
        } else {
          table.removeAttribute("id"); delete table.dataset.officeTable;
          caption.hidden = true; caption.textContent = "";
        }
      });
    } catch { /* Invalid drafts remain blocked by the shared document guard. */ }
  }
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
  $("semantic-options").disabled = !editable || !paragraphAllowed();
  $("insert-menu").querySelector('[value="pageBreak"]').disabled = !pageBreakAllowed();
  $("insert-menu").querySelector('[value="removePageBreak"]').disabled = !paragraphAllowed() || pageBreakPosition() === null;
  $("insert-menu").querySelector('[value="sectionBreak"]').disabled = !sectionBreakAllowed();
  $("insert-menu").querySelector('[value="editSectionBreak"]').disabled = !paragraphAllowed() || !selectedSectionBreak();
  $("insert-menu").querySelector('[value="removeSectionBreak"]').disabled = !paragraphAllowed() || !selectedSectionBreak();
  updateTableControls();
  updateParagraphControls();
  updateCharacterControls();
  updateLinkControls();
  updateBookmarkControls();
  updateDocumentReferenceControls();
  paintDocumentReferences();
  documentCardControls.update();
  chartControls.update();
  updateFormatTransfer();
  updateListControls();
  updateStyleControls();
  pageControls.update();
  imageControls.update();
  shapeControls.update();
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

function selectedSectionBreak() {
  const selection = state.editor?.state.selection;
  return selection?.node?.type.name === "sectionBreak" ? { position: selection.from, node: selection.node } : null;
}

function sectionBreakAllowed() {
  if (!pageBreakAllowed()) return false;
  let count = 0;
  state.editor.state.doc.forEach((node) => { if (node.type.name === "sectionBreak") count += 1; });
  return count < OFFICE_SECTION_LIMIT;
}

function sectionProfileBefore(position) {
  const doc = state.editor.state.doc;
  const rootRunning = officeRunningSettings(doc.attrs.running ?? undefined, doc.attrs.page);
  let profile = { page: officePageSettings(doc.attrs.page ?? undefined),
    running: { header: rootRunning.header, footer: rootRunning.footer, numbering: rootRunning.numbering } };
  doc.forEach((node, offset) => { if (offset < position && node.type.name === "sectionBreak") profile = officeSectionProfile(node.attrs); });
  return profile;
}

function closeSectionDialog(restoreFocus = false) {
  const action = state.sectionAction;
  state.sectionAction = null;
  $("section-dialog").close(); $("section-form").reset(); $("section-status").textContent = "";
  $("section-description").textContent = ""; $("section-running-preview").textContent = "";
  $("section-preview").removeAttribute("style");
  if (restoreFocus && action?.editor === state.editor && sessionCurrent(action.session)) focusEditor();
}

function readSectionProfile() {
  const page = officePageSettings({ paper: $("section-paper").value, orientation: $("section-orientation").value,
    margins: Object.fromEntries(OFFICE_PAGE_SIDES.map((side) => [side, $(`section-${side}`).valueAsNumber])) });
  return officeSectionProfile({ page, running: { header: $("section-header").value, footer: $("section-footer").value,
    numbering: $("section-numbering").value } });
}

function previewSectionProfile() {
  if (!characterActionCurrent(state.sectionAction)) { closeSectionDialog(); return; }
  try {
    const profile = readSectionProfile();
    officePagePreview($("section-preview"), profile.page);
    $("section-description").textContent = officeSectionDescription(profile);
    $("section-running-preview").textContent = [profile.running.header || "(keine Kopfzeile)",
      "— Beispiel für Abschnittsinhalt —", profile.running.footer || "(keine Fußzeile)",
      officeRunningNumber(profile.running, 2, 4)].filter(Boolean).join("\n");
    $("section-status").textContent = ""; $("section-apply").disabled = false;
  } catch {
    $("section-description").textContent = ""; $("section-running-preview").textContent = "";
    $("section-status").textContent = "Ränder: ganze Zahlen von 5 bis 50 mm; mit Kopf-/Fußzeile oder Seitenzahl mindestens 16 mm am jeweiligen Rand. Texte: höchstens 64 Zeichen ohne Zeilenumbrüche.";
    $("section-apply").disabled = true;
  }
}

function openSectionDialog(edit = false) {
  const selected = selectedSectionBreak();
  if (!paragraphAllowed() || (edit ? !selected : !sectionBreakAllowed())) return;
  closeSectionDialog();
  const editor = state.editor, position = selected?.position ?? editor.state.selection.from;
  const profile = selected ? officeSectionProfile(selected.node.attrs) : sectionProfileBefore(position);
  state.sectionAction = { editor, session: state.session, context: state.context, revision: state.session.revision,
    document: editor.state.doc, selection: editor.state.selection, storedMarks: editor.state.storedMarks,
    mode: selected ? "edit" : "insert", position };
  $("section-title").textContent = selected ? "Abschnitt bearbeiten" : "Abschnitt einfügen";
  $("section-apply").textContent = selected ? "Änderungen übernehmen" : "Abschnitt einfügen";
  $("section-paper").value = profile.page.paper; $("section-orientation").value = profile.page.orientation;
  for (const side of OFFICE_PAGE_SIDES) $(`section-${side}`).value = String(profile.page.margins[side]);
  $("section-header").value = profile.running.header; $("section-footer").value = profile.running.footer;
  $("section-numbering").value = profile.running.numbering;
  $("section-dialog").showModal(); previewSectionProfile(); $("section-paper").focus();
}

function removeSectionBreak() {
  const selected = selectedSectionBreak();
  if (!paragraphAllowed() || !selected) return false;
  const editor = state.editor, transaction = editor.state.tr.delete(selected.position, selected.position + 1);
  try { validateEditorDocument(transaction.doc); } catch { notice("Der Abschnittsumbruch konnte nicht entfernt werden.", true); return false; }
  editor.view.dispatch(closeHistory(transaction).scrollIntoView()); editor.view.dispatch(closeHistory(editor.state.tr));
  focusEditor(); updateEditorState(); notice("Abschnittsumbruch entfernt. Gespeichert wird erst mit der nächsten bestätigten Version.");
  return true;
}

function applySectionProfile(event) {
  event.preventDefault();
  const action = state.sectionAction;
  if (!characterActionCurrent(action)) { closeSectionDialog(); return; }
  const editor = action.editor;
  let profile, transaction = editor.state.tr;
  try {
    profile = readSectionProfile();
    if (action.mode === "edit") transaction.setNodeMarkup(action.position, undefined, profile);
    else {
      const { selection } = editor.state, marker = editor.schema.nodes.sectionBreak.create(profile), { $from } = selection;
      if ($from.depth === 1) {
        const block = $from.parent, offset = $from.parentOffset, start = $from.before();
        const left = block.copy(block.content.cut(0, offset)), right = block.copy(block.content.cut(offset));
        transaction.replaceWith(start, $from.after(), [left, marker, right]);
        transaction.setSelection(TextSelection.create(transaction.doc, start + left.nodeSize + 2));
      } else {
        const position = selection.node ? selection.to : selection.from, atEnd = position === transaction.doc.content.size;
        transaction.insert(position, atEnd ? [marker, editor.schema.nodes.paragraph.create()] : marker);
        transaction.setSelection(atEnd ? TextSelection.create(transaction.doc, position + 2) : Selection.near(transaction.doc.resolve(position + 1), 1));
      }
    }
    validateEditorDocument(transaction.doc);
  } catch {
    $("section-status").textContent = "Dieser Abschnittsumbruch wäre ungültig, angrenzend an einen anderen Umbruch oder außerhalb der Dokumentgrenzen. Ihr Entwurf bleibt unverändert.";
    return;
  }
  if (transaction.doc.eq(editor.state.doc)) { $("section-status").textContent = "Keine Änderung: Dieses Abschnittsprofil gilt bereits."; return; }
  if (editor.state.storedMarks) transaction.setStoredMarks(editor.state.storedMarks);
  closeSectionDialog(); editor.view.dispatch(closeHistory(transaction).scrollIntoView());
  editor.view.dispatch(closeHistory(editor.state.tr).setStoredMarks(editor.state.storedMarks));
  focusEditor(); updateEditorState(); notice(`${action.mode === "edit" ? "Abschnitt geändert" : "Abschnitt eingefügt"}. Rückgängig ist möglich; gespeichert wird erst mit der nächsten bestätigten Version.`);
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

function linkCharacters(editor = state.editor) {
  if (!editor || editor.state.selection.empty) return [];
  return selectedCharacters(editor);
}

function commonLink(entries) {
  const values = new Set(entries.map(({ marks }) => marks.find((mark) => mark.type.name === "link")?.attrs.href || null));
  return values.size === 1 ? [...values][0] : null;
}

function linkActionCurrent(action) {
  return paragraphActionCurrent(action) && action.characters.length > 0;
}

function closeLinkDialog(restoreFocus = false) {
  const action = state.linkAction;
  state.linkAction = null;
  $("link-dialog").close();
  $("link-form").reset();
  $("link-status").textContent = "";
  if (restoreFocus && action?.editor === state.editor) focusEditor(action.editor);
}

function updateLinkControls() {
  if (state.linkAction && !linkActionCurrent(state.linkAction)) closeLinkDialog();
  const entries = linkCharacters();
  const enabled = paragraphAllowed() && entries.length > 0;
  $("link-options").disabled = !enabled;
  $("link-options").setAttribute("aria-pressed", String(enabled && entries.some(({ marks }) => marks.some((mark) => mark.type.name === "link"))));
}

function openLinkDialog() {
  const characters = linkCharacters();
  if (!characters.length) return;
  closeLinkDialog();
  state.linkAction = { session: state.session, editor: state.editor, context: state.context,
    revision: state.session.revision, document: state.editor.state.doc, selection: state.editor.state.selection, characters };
  const href = commonLink(characters);
  $("link-href").value = href || "";
  $("link-selection").textContent = `${state.editor.state.doc.textBetween(state.editor.state.selection.from, state.editor.state.selection.to, " ").slice(0, 160)}${state.editor.state.selection.to - state.editor.state.selection.from > 160 ? "…" : ""}`;
  $("link-remove").disabled = !characters.some(({ marks }) => marks.some((mark) => mark.type.name === "link"));
  $("link-open").disabled = !href;
  $("link-status").textContent = href ? "Das vorhandene Ziel kann geändert, entfernt oder bewusst geöffnet werden." : "HTTPS-Adresse oder einfache mailto:-Adresse eingeben.";
  $("link-dialog").showModal();
  $("link-href").focus();
}

function commitLink(remove = false) {
  const action = state.linkAction;
  if (!linkActionCurrent(action)) { closeLinkDialog(); return; }
  let href = null;
  try { if (!remove) href = officeLinkHref($("link-href").value); }
  catch {
    $("link-status").textContent = "Nur vollständige HTTPS-Adressen oder einfache mailto:-Adressen sind zulässig.";
    $("link-status").classList.add("error"); return;
  }
  const type = action.editor.schema.marks.link;
  const transaction = action.editor.state.tr;
  let changed = false;
  for (const { marks, from, to } of action.characters) {
    const prior = marks.find((mark) => mark.type === type)?.attrs.href || null;
    if (prior === href) continue;
    changed = true; transaction.removeMark(from, to, type);
    if (href) transaction.addMark(from, to, type.create({ href }));
  }
  if (!changed) { $("link-status").textContent = "Keine Änderung: Die Auswahl verwendet bereits dieses Ziel."; return; }
  try { validateEditorDocument(transaction.doc); }
  catch { $("link-status").textContent = "Der Link überschreitet die unterstützte Dokumentgröße oder Struktur."; $("link-status").classList.add("error"); return; }
  if (!linkActionCurrent(action)) { closeLinkDialog(); return; }
  closeLinkDialog();
  action.editor.view.dispatch(closeHistory(transaction).scrollIntoView());
  focusEditor(action.editor); updateEditorState();
  notice(remove ? "Link entfernt. Der Text bleibt erhalten; gespeichert wird erst mit der nächsten bestätigten Version." :
    "Link angewendet. Gespeichert wird erst mit der nächsten bestätigten Version.");
}

function openSelectedLink() {
  const action = state.linkAction;
  const href = linkActionCurrent(action) ? commonLink(action.characters) : null;
  if (!href) return;
  const opened = window.open(officeLinkHref(href), "_blank", "noopener,noreferrer");
  if (opened) opened.opener = null;
}

function selectedBookmark(editor = state.editor) {
  const selection = editor?.state.selection;
  return selection instanceof NodeSelection && selection.node.type.name === "bookmark" ?
    { node: selection.node, position: selection.from } : null;
}

function bookmarkCaretAllowed(editor = state.editor) {
  const selection = editor?.state.selection;
  return Boolean(selection?.empty && selection instanceof TextSelection && ["paragraph", "heading"].includes(selection.$from.parent.type.name));
}

function bookmarkActionCurrent(action) { return paragraphActionCurrent(action); }

function closeBookmarkDialog(restoreFocus = false) {
  const action = state.bookmarkAction;
  state.bookmarkAction = null; $("bookmark-dialog").close(); $("bookmark-form").reset(); $("bookmark-status").textContent = "";
  if (restoreFocus && action?.editor === state.editor) focusEditor(action.editor);
}

function uniqueBookmarkLabel(inventory) {
  const labels = new Set(inventory.map(({ label }) => label.toLowerCase()));
  for (let number = 1; number <= OFFICE_BOOKMARK_LIMIT; number += 1) {
    const candidate = `Lesezeichen ${number}`;
    if (!labels.has(candidate.toLowerCase())) return candidate;
  }
  return "Lesezeichen";
}

function updateBookmarkControls() {
  if (state.bookmarkAction && !bookmarkActionCurrent(state.bookmarkAction)) closeBookmarkDialog();
  if (state.crossReferenceAction && !bookmarkActionCurrent(state.crossReferenceAction)) closeCrossReferenceDialog();
  const bookmark = selectedBookmark();
  let bookmarks = [], references = [];
  try {
    if (state.editor) {
      const document = state.editor.getJSON();
      bookmarks = officeBookmarkInventory(document); references = officeReferenceInventory(document);
    }
  } catch { /* Invalid drafts remain disabled. */ }
  $("bookmark-options").disabled = !paragraphAllowed() || (!bookmark && (!bookmarkCaretAllowed() || bookmarks.length >= OFFICE_BOOKMARK_LIMIT));
  $("bookmark-options").setAttribute("aria-pressed", String(Boolean(bookmark)));
  const entries = linkCharacters();
  const hasReference = entries.some(({ marks }) => marks.some((mark) => mark.type.name === "crossReference"));
  $("cross-reference-options").disabled = !paragraphAllowed() || !entries.length || (!references.length && !hasReference);
  $("cross-reference-options").setAttribute("aria-pressed", String(hasReference));
}

function openBookmarkDialog() {
  const editor = state.editor, selected = selectedBookmark(editor);
  if (!paragraphAllowed() || (!selected && !bookmarkCaretAllowed(editor))) return;
  let inventory;
  try { inventory = officeBookmarkInventory(editor.getJSON()); } catch { return; }
  if (!selected && inventory.length >= OFFICE_BOOKMARK_LIMIT) return;
  closeBookmarkDialog();
  state.bookmarkAction = { session: state.session, editor, context: state.context, revision: state.session.revision,
    document: editor.state.doc, selection: editor.state.selection, selected };
  $("bookmark-title").textContent = selected ? "Lesezeichen bearbeiten" : "Lesezeichen einfügen";
  $("bookmark-label").value = selected?.node.attrs.label || uniqueBookmarkLabel(inventory);
  $("bookmark-remove").hidden = !selected;
  $("bookmark-apply").textContent = selected ? "Änderung übernehmen" : "Lesezeichen einfügen";
  $("bookmark-status").textContent = `${inventory.length} von ${OFFICE_BOOKMARK_LIMIT} Lesezeichen im Dokument.`;
  $("bookmark-dialog").showModal(); $("bookmark-label").select();
}

function commitBookmark(remove = false) {
  const action = state.bookmarkAction;
  if (!bookmarkActionCurrent(action)) { closeBookmarkDialog(); return; }
  const editor = action.editor, current = action.selected;
  let attrs, transaction = editor.state.tr;
  try {
    if (remove) {
      if (!current) return;
      transaction.delete(current.position, current.position + current.node.nodeSize);
    } else {
      const existingId = current?.node.attrs.id;
      const id = existingId || `bookmark-${mutationReference().replaceAll("-", "").slice(0, 24)}`;
      attrs = officeBookmarkAttributes({ id, label: $("bookmark-label").value });
      const inventory = officeBookmarkInventory(editor.getJSON());
      if (inventory.some((entry) => entry.id !== existingId && entry.label.toLowerCase() === attrs.label.toLowerCase())) {
        throw new Error("duplicate-label");
      }
      if (current) transaction.setNodeMarkup(current.position, undefined, attrs);
      else {
        transaction.replaceSelectionWith(editor.schema.nodes.bookmark.create(attrs));
        transaction.setSelection(NodeSelection.create(transaction.doc, action.selection.from));
      }
    }
    validateEditorDocument(transaction.doc);
  } catch (error) {
    $("bookmark-status").textContent = error.message === "duplicate-label" ? "Dieser Lesezeichenname ist bereits vergeben." :
      "Der Name muss 1 bis 64 sichtbare Zeichen enthalten und im Dokument eindeutig sein.";
    $("bookmark-status").classList.add("error"); return;
  }
  closeBookmarkDialog(); editor.view.dispatch(closeHistory(transaction).scrollIntoView());
  editor.view.dispatch(closeHistory(editor.state.tr)); focusEditor(editor); updateEditorState();
  notice(remove ? "Lesezeichen entfernt. Vorhandene Querverweise zeigen das fehlende Ziel an." :
    `${current ? "Lesezeichen umbenannt" : "Lesezeichen eingefügt"}. Gespeichert wird erst mit der nächsten bestätigten Version.`);
}

function commonCrossReference(entries) {
  const values = new Set(entries.map(({ marks }) => marks.find((mark) => mark.type.name === "crossReference")?.attrs.targetId || null));
  return values.size === 1 ? [...values][0] : null;
}

function closeCrossReferenceDialog(restoreFocus = false) {
  const action = state.crossReferenceAction;
  state.crossReferenceAction = null; $("cross-reference-dialog").close(); $("cross-reference-form").reset();
  $("cross-reference-status").textContent = ""; $("cross-reference-target").replaceChildren();
  if (restoreFocus && action?.editor === state.editor) focusEditor(action.editor);
}

function openCrossReferenceDialog() {
  const editor = state.editor, characters = linkCharacters(editor);
  if (!characters.length) return;
  let inventory;
  try { inventory = officeReferenceInventory(editor.getJSON()); } catch { return; }
  const existing = commonCrossReference(characters);
  if (!inventory.length && !existing) return;
  closeCrossReferenceDialog();
  state.crossReferenceAction = { session: state.session, editor, context: state.context, revision: state.session.revision,
    document: editor.state.doc, selection: editor.state.selection, characters };
  const targets = $("cross-reference-target");
  for (const entry of inventory) { const option = node("option", entry.label); option.value = entry.id; targets.append(option); }
  if (existing && !inventory.some(({ id }) => id === existing)) {
    const option = node("option", `Ziel nicht verfügbar (${existing})`); option.value = existing; option.dataset.broken = "true"; targets.prepend(option);
  }
  targets.value = existing || inventory[0]?.id || "";
  $("cross-reference-selection").textContent = editor.state.doc.textBetween(editor.state.selection.from, editor.state.selection.to, " ").slice(0, 160);
  $("cross-reference-remove").disabled = !characters.some(({ marks }) => marks.some((mark) => mark.type.name === "crossReference"));
  $("cross-reference-jump").disabled = !inventory.some(({ id }) => id === targets.value);
  $("cross-reference-status").textContent = officeCrossReferenceDescription({ targetId: targets.value }, inventory);
  $("cross-reference-dialog").showModal(); targets.focus();
}

function commitCrossReference(remove = false) {
  const action = state.crossReferenceAction;
  if (!bookmarkActionCurrent(action) || !action.characters.length) { closeCrossReferenceDialog(); return; }
  const targetId = remove ? null : $("cross-reference-target").value;
  let attrs = null, transaction = action.editor.state.tr, changed = false;
  try {
    const inventory = officeReferenceInventory(action.editor.getJSON());
    if (!remove) {
      attrs = officeCrossReferenceAttributes({ targetId });
      if (!inventory.some(({ id }) => id === attrs.targetId)) throw new Error("missing-target");
      if (action.characters.some(({ marks }) => marks.some((mark) => ["link", "code"].includes(mark.type.name)))) throw new Error("incompatible-mark");
    }
    const type = action.editor.schema.marks.crossReference;
    for (const { from, to, marks } of action.characters) {
      const prior = marks.find((mark) => mark.type === type)?.attrs.targetId || null;
      if (prior === targetId) continue;
      changed = true; transaction.removeMark(from, to, type);
      if (attrs) transaction.addMark(from, to, type.create(attrs));
    }
    if (!changed) { $("cross-reference-status").textContent = "Keine Änderung: Die Auswahl verwendet bereits dieses Ziel."; return; }
    validateEditorDocument(transaction.doc);
  } catch (error) {
    $("cross-reference-status").textContent = error.message === "incompatible-mark" ?
      "Entfernen Sie zuerst Link- oder Codeformatierung aus der Auswahl." : "Wählen Sie ein vorhandenes Lesezeichen als Ziel.";
    $("cross-reference-status").classList.add("error"); return;
  }
  closeCrossReferenceDialog(); action.editor.view.dispatch(closeHistory(transaction).scrollIntoView());
  action.editor.view.dispatch(closeHistory(action.editor.state.tr)); focusEditor(action.editor); updateEditorState();
  notice(remove ? "Querverweis entfernt. Der Text bleibt erhalten." : "Querverweis angewendet. Gespeichert wird erst mit der nächsten bestätigten Version.");
}

function jumpToCrossReference() {
  const action = state.crossReferenceAction;
  if (!bookmarkActionCurrent(action)) { closeCrossReferenceDialog(); return; }
  const targetId = $("cross-reference-target").value;
  let targetPosition = null;
  action.editor.state.doc.descendants((entry, position) => {
    if (targetPosition === null && ((entry.type.name === "bookmark" && entry.attrs.id === targetId) ||
        (entry.type.name === "image" && entry.attrs.figureId === targetId) ||
        (entry.type.name === "table" && entry.attrs.tableId === targetId))) targetPosition = position;
  });
  if (targetPosition === null) return;
  closeCrossReferenceDialog();
  action.editor.view.dispatch(action.editor.state.tr.setSelection(NodeSelection.create(action.editor.state.doc, targetPosition)).scrollIntoView());
  focusEditor(action.editor); updateEditorState(); notice("Zum Verweisziel gesprungen.");
}

function commonDocumentReference(entries) {
  const values = new Map();
  for (const { marks } of entries) {
    const mark = marks.find((entry) => entry.type.name === "documentReference");
    const attrs = mark ? officeDocumentReferenceAttributes(mark.attrs) : null;
    values.set(attrs ? officeDocumentReferenceKey(attrs) : "", attrs);
  }
  return values.size === 1 ? [...values.values()][0] : null;
}

function documentReferenceActionCurrent(action = state.documentReferenceAction) {
  return bookmarkActionCurrent(action) && action.context === state.context;
}

function closeDocumentReferenceDialog(restoreFocus = false) {
  const action = state.documentReferenceAction;
  state.documentReferenceAction = null;
  $("document-reference-dialog").close(); $("document-reference-form").reset();
  $("document-reference-target").replaceChildren(); $("document-reference-status").textContent = "";
  if (restoreFocus && action?.editor === state.editor) focusEditor(action.editor);
}

function updateDocumentReferenceControls() {
  if (state.documentReferenceAction && !documentReferenceActionCurrent()) closeDocumentReferenceDialog();
  const entries = linkCharacters();
  const active = entries.some(({ marks }) => marks.some((mark) => mark.type.name === "documentReference"));
  $("document-reference-options").disabled = !paragraphAllowed() || !entries.length || !state.session?.objectId;
  $("document-reference-options").setAttribute("aria-pressed", String(active));
}

function paintDocumentReferences() {
  state.editor?.view.dom.querySelectorAll("[data-office-document-reference]").forEach((element) => {
    try {
      const attrs = officeDocumentReferenceAttributes({ targetObjectId: element.dataset.officeDocumentReference,
        targetVersionId: element.dataset.officeDocumentVersion });
      const resolved = state.documentReferenceResolutions.get(officeDocumentReferenceKey(attrs));
      const status = resolved?.status === "resolved" ? "resolved" : "unavailable";
      element.dataset.officeReferenceStatus = status;
      element.title = officeDocumentReferenceDescription(attrs, state.documentReferenceResolutions);
    } catch { element.dataset.officeReferenceStatus = "unavailable"; element.title = "Dokumentziel nicht verfügbar"; }
  });
  state.editor?.view.dom.querySelectorAll("[data-office-document-card]").forEach((element) => {
    try {
      const attrs = officeDocumentCardAttributes({ targetObjectId: element.dataset.officeDocumentCard,
        targetVersionId: element.dataset.officeDocumentVersion, mode: element.dataset.officeDocumentMode });
      const resolved = state.documentReferenceResolutions.get(officeDocumentCardKey(attrs));
      const available = resolved?.status === "resolved";
      element.dataset.officeReferenceStatus = available ? "resolved" : "unavailable";
      element.querySelector(".office-document-card-title").textContent = available ? resolved.title : "Dokumentobjekt nicht verfügbar";
      element.querySelector(".office-document-card-detail").textContent = available ?
        `${resolved.isCurrentVersion ? "Aktuelle" : "Gespeicherte"} Version` : "Zugriff oder Version nicht verfügbar";
      element.setAttribute("aria-label", officeDocumentCardDescription(attrs, state.documentReferenceResolutions));
    } catch { element.dataset.officeReferenceStatus = "unavailable"; }
  });
}

async function refreshDocumentReferences(session = state.session) {
  if (!sessionCurrent(session) || !session.objectId || !session.version?.version_id) return new Map();
  const objectId = session.objectId, versionId = session.version.version_id, context = state.context;
  try {
    const payload = await api(`/v1/office/documents/${encodeURIComponent(objectId)}/outbound-references?version_id=${encodeURIComponent(versionId)}`, {}, context);
    if (!sessionCurrent(session) || session.version?.version_id !== versionId || state.context !== context) return new Map();
    state.documentReferenceResolutions = officeDocumentReferenceResolutions(payload, objectId, versionId);
  } catch {
    if (!sessionCurrent(session) || session.version?.version_id !== versionId) return new Map();
    state.documentReferenceResolutions = new Map();
  }
  paintDocumentReferences();
  return state.documentReferenceResolutions;
}

async function openDocumentReferenceDialog() {
  const editor = state.editor, characters = linkCharacters(editor);
  if (!characters.length || !state.session?.objectId) return;
  closeDocumentReferenceDialog();
  documentCardControls.close();
  const action = { session: state.session, editor, context: state.context, revision: state.session.revision,
    document: editor.state.doc, selection: editor.state.selection, characters };
  state.documentReferenceAction = action;
  const existing = commonDocumentReference(characters), select = $("document-reference-target");
  $("document-reference-selection").textContent = editor.state.doc.textBetween(editor.state.selection.from, editor.state.selection.to, " ").slice(0, 160);
  $("document-reference-remove").disabled = !existing;
  $("document-reference-open").disabled = true;
  $("document-reference-apply").disabled = true;
  $("document-reference-status").textContent = "Freigegebene Dokumente werden geladen …";
  $("document-reference-dialog").showModal();
  try {
    const [payload, resolutions] = await Promise.all([
      api("/v1/office/documents?query=&page_size=200", {}, action.context),
      existing ? refreshDocumentReferences(action.session) : Promise.resolve(state.documentReferenceResolutions),
    ]);
    if (!documentReferenceActionCurrent(action) || payload?.tenant_id !== action.context.tenantId || !Array.isArray(payload.documents)) return;
    const documents = payload.documents.filter((entry) => entry.object_id !== action.session.objectId &&
      typeof entry.title === "string" && /^office-doc-[a-f0-9]{32}$/.test(entry.object_id) && /^office-version-[a-f0-9]{32}$/.test(entry.current_version_id));
    for (const entry of documents) {
      const option = new Option(entry.title, officeDocumentReferenceKey({ targetObjectId: entry.object_id, targetVersionId: entry.current_version_id }));
      option.dataset.objectId = entry.object_id; option.dataset.versionId = entry.current_version_id; select.append(option);
    }
    if (existing && !documents.some((entry) => entry.object_id === existing.targetObjectId && entry.current_version_id === existing.targetVersionId)) {
      const resolution = resolutions.get(officeDocumentReferenceKey(existing));
      const available = resolution?.status === "resolved";
      const option = new Option(available ? `${resolution.title} · gespeicherte Version` : "Dokumentziel nicht verfügbar", officeDocumentReferenceKey(existing));
      option.dataset.objectId = existing.targetObjectId; option.dataset.versionId = existing.targetVersionId;
      if (!available) option.dataset.unavailable = "true";
      select.prepend(option);
    }
    select.value = existing ? officeDocumentReferenceKey(existing) : select.options[0]?.value || "";
    $("document-reference-apply").disabled = !select.value || select.selectedOptions[0]?.dataset.unavailable === "true";
    const resolved = existing && resolutions.get(officeDocumentReferenceKey(existing));
    $("document-reference-open").disabled = !existing || resolved?.status !== "resolved" || isDirty();
    $("document-reference-status").textContent = select.value ?
      (existing ? officeDocumentReferenceDescription(existing, state.documentReferenceResolutions) : "Die aktuell freigegebene Zielversion wird fest gespeichert.") :
      "Kein anderes freigegebenes Dokument verfügbar.";
    select.focus();
  } catch {
    if (documentReferenceActionCurrent(action)) $("document-reference-status").textContent = "Dokumentziele sind gerade nicht verfügbar.";
  }
}

function commitDocumentReference(remove = false) {
  const action = state.documentReferenceAction;
  if (!documentReferenceActionCurrent(action)) { closeDocumentReferenceDialog(); return; }
  const option = $("document-reference-target").selectedOptions[0];
  let attrs = null, transaction = action.editor.state.tr, changed = false;
  try {
    if (!remove) {
      if (!option || option.dataset.unavailable === "true") throw new Error("unavailable");
      attrs = officeDocumentReferenceAttributes({ targetObjectId: option.dataset.objectId, targetVersionId: option.dataset.versionId });
      if (action.characters.some(({ marks }) => marks.some((mark) => ["link", "crossReference", "code"].includes(mark.type.name)))) throw new Error("incompatible");
    }
    const type = action.editor.schema.marks.documentReference;
    for (const { from, to, marks } of action.characters) {
      const priorMark = marks.find((mark) => mark.type === type);
      const prior = priorMark ? officeDocumentReferenceKey(priorMark.attrs) : null;
      const next = attrs ? officeDocumentReferenceKey(attrs) : null;
      if (prior === next) continue;
      changed = true; transaction.removeMark(from, to, type);
      if (attrs) transaction.addMark(from, to, type.create(attrs));
    }
    if (!changed) { $("document-reference-status").textContent = "Keine Änderung: Die Auswahl verwendet bereits dieses Ziel."; return; }
    validateEditorDocument(transaction.doc);
  } catch (error) {
    $("document-reference-status").textContent = error.message === "incompatible" ?
      "Entfernen Sie zuerst Link-, Querverweis- oder Codeformatierung aus der Auswahl." : "Wählen Sie ein aktuell freigegebenes Dokumentziel.";
    $("document-reference-status").classList.add("error"); return;
  }
  closeDocumentReferenceDialog(); action.editor.view.dispatch(closeHistory(transaction).scrollIntoView());
  action.editor.view.dispatch(closeHistory(action.editor.state.tr)); focusEditor(action.editor); updateEditorState();
  notice(remove ? "Dokumentverweis entfernt. Der Text bleibt erhalten." : "Dokumentverweis angewendet. Nach dem Speichern wird das Ziel erneut geprüft.");
}

async function openSelectedDocumentReference() {
  const action = state.documentReferenceAction, attrs = action && commonDocumentReference(action.characters);
  if (!documentReferenceActionCurrent(action) || !attrs || isDirty()) return;
  $("document-reference-open").disabled = true; $("document-reference-status").textContent = "Zugriff auf die gespeicherte Zielversion wird erneut geprüft …";
  const resolutions = await refreshDocumentReferences(action.session);
  if (!documentReferenceActionCurrent(action)) return;
  const resolved = resolutions.get(officeDocumentReferenceKey(attrs));
  if (resolved?.status !== "resolved") { $("document-reference-status").textContent = "Dokumentziel nicht verfügbar"; return; }
  closeDocumentReferenceDialog(); await openDocument(attrs.targetObjectId, attrs.targetVersionId);
}

function backlinkActionCurrent(action = state.backlinksAction) {
  return Boolean(action && action.session === state.session && action.context === state.context &&
    sessionCurrent(action.session) && action.objectId === state.session?.objectId &&
    action.versionId === state.session?.version?.version_id);
}

function closeBacklinksDialog() {
  state.backlinksAction = null;
  $("backlinks-dialog").close();
  $("backlinks-list").replaceChildren();
  $("backlinks-status").textContent = "";
  $("backlinks-more").hidden = true;
}

function updateBacklinkControls() {
  if (state.backlinksAction && !backlinkActionCurrent()) closeBacklinksDialog();
  $("document-backlinks").disabled = Boolean(!state.session?.objectId || !state.session?.version?.version_id ||
    state.session.loading || state.session.saving || state.session.restoring);
}

function appendBacklink(action, backlink) {
  const key = `${backlink.sourceObjectId}:${backlink.sourceVersionId}`;
  if (action.seenSources.has(key)) return;
  action.seenSources.add(key);
  const button = document.createElement("button");
  button.type = "button"; button.className = "backlink-item";
  button.dataset.sourceObjectId = backlink.sourceObjectId;
  button.dataset.sourceVersionId = backlink.sourceVersionId;
  const copy = document.createElement("span"), title = document.createElement("strong"), detail = document.createElement("small");
  title.textContent = backlink.title;
  detail.textContent = `${backlink.referenceCount} ${backlink.referenceCount === 1 ? "Verweis" : "Verweise"} · aktuelle Quellversion`;
  copy.append(title, detail); button.append(copy);
  button.addEventListener("click", () => {
    if (!backlinkActionCurrent(action)) return;
    closeBacklinksDialog();
    void openDocument(backlink.sourceObjectId, backlink.sourceVersionId);
  });
  $("backlinks-list").append(button);
}

async function loadBacklinks(action, cursor = null) {
  if (!backlinkActionCurrent(action) || action.loading) return;
  action.loading = true; $("backlinks-more").disabled = true;
  $("backlinks-status").textContent = cursor ? "Weitere aktuell lesbare Quellen werden geprüft …" :
    "Aktuell lesbare Quellen werden geprüft …";
  try {
    const query = new URLSearchParams({ version_id: action.versionId, page_size: String(OFFICE_BACKLINK_PAGE_MAX) });
    if (cursor) query.set("cursor", cursor);
    const payload = await api(`/v1/office/documents/${encodeURIComponent(action.objectId)}/backlinks?${query}`, {}, action.context);
    if (!backlinkActionCurrent(action)) return;
    const page = officeBacklinkPage(payload, action.context.tenantId, action.objectId, action.versionId);
    if (cursor && action.seenCursors.has(cursor)) throw new Error("repeated-backlink-cursor");
    if (cursor) action.seenCursors.add(cursor);
    page.backlinks.forEach((backlink) => appendBacklink(action, backlink));
    action.cursor = page.nextCursor;
    $("backlinks-more").hidden = !page.hasMore;
    $("backlinks-status").textContent = action.seenSources.size ?
      `${action.seenSources.size} aktuell lesbare ${action.seenSources.size === 1 ? "Quelle" : "Quellen"} geladen.` :
      (page.hasMore ? "In diesem Abschnitt wurden keine lesbaren Rückverweise gefunden." : "Keine aktuell lesbaren Rückverweise auf diese Version.");
  } catch {
    if (backlinkActionCurrent(action)) {
      $("backlinks-status").textContent = "Rückverweise sind gerade nicht verfügbar.";
      $("backlinks-more").hidden = true;
    }
  } finally {
    if (backlinkActionCurrent(action)) { action.loading = false; $("backlinks-more").disabled = false; }
  }
}

function openBacklinksDialog() {
  const session = state.session;
  if (!session?.objectId || !session.version?.version_id || session.loading) return;
  closeBacklinksDialog();
  const action = { session, context: state.context, objectId: session.objectId,
    versionId: session.version.version_id, cursor: null, loading: false, seenCursors: new Set(), seenSources: new Set() };
  state.backlinksAction = action;
  $("backlinks-dialog").showModal();
  void loadBacklinks(action);
}

function semanticActionCurrent(action = state.semanticAction) {
  return Boolean(action && action.editor === state.editor && action.session === state.session &&
    action.context === state.context && sessionCurrent(action.session) && action.revision === action.session.revision);
}

function updateSemanticFields() {
  const kind = $("semantic-kind").value;
  $("semantic-field-fields").hidden = kind !== "field";
  $("semantic-toc-fields").hidden = kind !== "toc";
  $("semantic-note-fields").hidden = !["footnote", "endnote"].includes(kind);
  $("semantic-source-fields").hidden = !["source", "citation"].includes(kind);
  $("semantic-citation-fields").hidden = kind !== "citation";
  $("semantic-equation-fields").hidden = kind !== "equation";
  $("semantic-remove").hidden = !["field", "source", "citation"].includes(kind);
  $("semantic-apply").textContent = kind === "source" ? "Quelle anlegen" : "Einfügen";
}

function closeSemanticDialog(restoreFocus = false) {
  const action = state.semanticAction; state.semanticAction = null;
  $("semantic-dialog").close(); $("semantic-form").reset(); $("semantic-status").textContent = "";
  updateSemanticFields(); if (restoreFocus && action?.editor === state.editor) focusEditor(action.editor);
}

function openSemanticDialog() {
  if (!paragraphAllowed()) return;
  closeSemanticDialog();
  const editor = state.editor, inventory = officeSemanticInventory(editor.getJSON());
  state.semanticAction = { editor, session: state.session, context: state.context, revision: state.session.revision };
  const select = $("semantic-source-id"); select.replaceChildren(new Option("Neue Quelle", ""));
  for (const source of inventory.sources) select.append(new Option(officeBibliographyLabel(source), source.id));
  updateSemanticFields(); $("semantic-dialog").showModal(); $("semantic-kind").focus();
}

function commitSemanticElement() {
  const action = state.semanticAction;
  if (!semanticActionCurrent(action)) { closeSemanticDialog(); return; }
  const editor = action.editor, kind = $("semantic-kind").value;
  try {
    let transaction = editor.state.tr;
    const rootAttrs = { ...editor.state.doc.attrs };
    let inserted = null;
    if (kind === "field") {
      const field = { key: $("semantic-field-key").value.trim(), label: $("semantic-field-label").value.trim(), value: $("semantic-field-value").value };
      const fields = officeDocumentFields(rootAttrs.documentFields || []), index = fields.findIndex((entry) => entry.key === field.key);
      if (index < 0) fields.push(field); else fields[index] = field;
      rootAttrs.documentFields = officeDocumentFields(fields);
      transaction.setDocAttribute("documentFields", rootAttrs.documentFields);
      inserted = editor.schema.nodes.documentField.create({ key: field.key });
    } else if (["footnote", "endnote"].includes(kind)) {
      inserted = editor.schema.nodes.noteReference.create(officeNoteAttributes({ id: officeOpaqueId("note"), kind, text: $("semantic-note-text").value.trim() }));
    } else if (kind === "source") {
      const source = { id: officeOpaqueId("source"), author: $("semantic-source-author").value.trim(), title: $("semantic-source-title").value.trim(), year: $("semantic-source-year").value.trim(), locator: $("semantic-source-locator").value.trim() };
      rootAttrs.citationSources = officeCitationSources([...(rootAttrs.citationSources || []), source]);
      transaction.setDocAttribute("citationSources", rootAttrs.citationSources);
    } else if (kind === "citation") {
      const sourceId = $("semantic-source-id").value;
      if (!sourceId) throw new Error("Wählen Sie zuerst eine vorhandene Quelle oder legen Sie eine Quelle an.");
      inserted = editor.schema.nodes.citationReference.create({ sourceId, locator: $("semantic-citation-locator").value.trim() });
    } else if (kind === "toc") inserted = editor.schema.nodes.tableOfContents.create({ maxLevel: Number($("semantic-toc-level").value) });
    else if (kind === "bibliography") inserted = editor.schema.nodes.bibliography.create();
    else if (kind === "equation") inserted = editor.schema.nodes.equation.create(officeEquationAttributes({ id: officeOpaqueId("equation"), source: $("semantic-equation-source").value.trim(), alt: $("semantic-equation-alt").value.trim() }));
    else if (kind === "index") inserted = editor.schema.nodes.referenceIndex.create();
    if (inserted) transaction.replaceSelectionWith(inserted, false);
    validateEditorDocument(transaction.doc); closeSemanticDialog();
    editor.view.dispatch(transaction.scrollIntoView()); focusEditor(editor); updateEditorState();
    notice(kind === "source" ? "Quelle im Dokumentkatalog angelegt." : "Strukturelement eingefügt. Gespeichert wird erst mit der nächsten bestätigten Version.");
  } catch (error) {
    $("semantic-status").textContent = error instanceof Error ? error.message : "Das Element ist ungültig.";
    $("semantic-status").classList.add("error");
  }
}

function removeSemanticCatalogEntry() {
  const action = state.semanticAction;
  if (!semanticActionCurrent(action)) { closeSemanticDialog(); return; }
  const editor = action.editor, kind = $("semantic-kind").value, rootAttrs = { ...editor.state.doc.attrs };
  try {
    if (kind === "field") {
      const key = $("semantic-field-key").value.trim();
      if (!key) throw new Error("Geben Sie den zu entfernenden Feldschlüssel ein.");
      const fields = officeDocumentFields(rootAttrs.documentFields || []), remaining = fields.filter((field) => field.key !== key);
      if (remaining.length === fields.length) throw new Error("Dieses Feld ist nicht im Katalog vorhanden.");
      rootAttrs.documentFields = remaining;
    } else {
      const sourceId = $("semantic-source-id").value;
      if (!sourceId) throw new Error("Wählen Sie die zu entfernende Quelle.");
      const sources = officeCitationSources(rootAttrs.citationSources || []), remaining = sources.filter((source) => source.id !== sourceId);
      if (remaining.length === sources.length) throw new Error("Diese Quelle ist nicht im Katalog vorhanden.");
      rootAttrs.citationSources = remaining;
    }
    let transaction = editor.state.tr;
    transaction = transaction.setDocAttribute("documentFields", rootAttrs.documentFields || []);
    transaction = transaction.setDocAttribute("citationSources", rootAttrs.citationSources || []);
    validateEditorDocument(transaction.doc); closeSemanticDialog(); editor.view.dispatch(transaction); focusEditor(editor); updateEditorState();
    notice("Katalogeintrag entfernt. Vorhandene Verweise bleiben als fehlend sichtbar und rückgängig machbar.");
  } catch (error) {
    $("semantic-status").textContent = error instanceof Error ? error.message : "Der Katalogeintrag konnte nicht entfernt werden.";
    $("semantic-status").classList.add("error");
  }
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
const tableReorderCommands = new Set(["moveRowBefore", "moveRowAfter", "moveColumnBefore", "moveColumnAfter"]);
const tableDuplicateCommands = new Set(["duplicateRows", "duplicateColumns"]);
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

function currentTableNode(editor = state.editor) {
  if (!editor || !currentTable(editor)) return null;
  const resolved = editor.state.selection.$from;
  for (let depth = resolved.depth; depth > 0; depth -= 1) {
    const entry = resolved.node(depth);
    if (entry.type.name === "table") return { entry, position: resolved.before(depth) };
  }
  return null;
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
  $("table-caption-dialog").close();
  $("table-cell-style-dialog").close();
  $("table-layout-dialog").close();
  $("table-sort-dialog").close();
  $("table-formula-dialog").close();
  $("table-insert-form").reset();
  $("table-insert-message").textContent = "";
  $("table-remove-summary").textContent = "";
  $("table-remove-title").textContent = "Tabelleninhalt entfernen?";
  $("table-remove-confirm").textContent = "Aus Entwurf entfernen";
  $("table-caption-form").reset();
  $("table-cell-style-form").reset();
  $("table-layout-form").reset();
  $("table-sort-form").reset();
  $("table-formula-form").reset();
  $("table-caption-status").textContent = "";
  $("table-cell-style-status").textContent = "";
  $("table-layout-status").textContent = "";
  $("table-sort-status").textContent = "";
  $("table-formula-status").textContent = "";
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
  $("table-header-column-toggle").disabled = !rect || !allowed;
  $("table-merge").disabled = !rect || !allowed || !mergeCells(state.editor.state);
  $("table-split").disabled = !rect || !allowed || !splitCell(state.editor.state);
  $("table-caption").disabled = !rect || !allowed;
  $("table-cell-style").disabled = !rect || !allowed;
  $("table-layout").disabled = !rect || !allowed;
  let reorder = null;
  try { reorder = rect ? officeTableReorderInfo(rect.table.toJSON()) : null; } catch { reorder = null; }
  let sortable = false;
  try { sortable = Boolean(rect && officeTableSortInfo(rect.table.toJSON()).dataRows >= 2); } catch { sortable = false; }
  $("table-sort").disabled = !rect || !allowed || !sortable;
  $("table-sort").title = sortable ? "Datenzeilen nach einer Spalte sortieren" : "Sortieren benötigt mindestens zwei Datenzeilen ohne verbundene Zellen";
  const formulaCell = rect && reorder && rect.bottom - rect.top === 1 && rect.right - rect.left === 1 ?
    state.editor.state.doc.nodeAt(rect.tableStart + rect.map.map[rect.top * rect.map.width + rect.left]) : null;
  $("table-formula").disabled = !rect || !allowed || !reorder || formulaCell?.type.name !== "tableCell";
  $("table-formula").title = formulaCell?.type.name === "tableCell" ? "Lokale Formel für diese Zelle bearbeiten" :
    "Formeln benötigen genau eine gewöhnliche Zelle in einer Tabelle ohne verbundene Zellen";
  $("table-delete").disabled = !rect || !allowed;
  $("table-select").disabled = !rect || Boolean(state.session?.loading || state.session?.saving || state.session?.restoring);
  const header = Boolean(rect && Array.from({ length: rect.table.firstChild.childCount }, (_, index) =>
    rect.table.firstChild.child(index).type.name === "tableHeader").every(Boolean));
  $("table-header-toggle").setAttribute("aria-pressed", String(header));
  $("table-header-toggle").title = header ? "Kopfzeile in normale Zellen umwandeln" : "Erste Zeile als Kopfzeile formatieren";
  const columnHeader = Boolean(rect && Array.from({ length: rect.map.height }, (_, row) =>
    state.editor.state.doc.nodeAt(rect.tableStart + rect.map.map[row * rect.map.width])?.type.name === "tableHeader").every(Boolean));
  $("table-header-column-toggle").setAttribute("aria-pressed", String(columnHeader));
  $("table-header-column-toggle").title = columnHeader ? "Kopfspalte in normale Zellen umwandeln" : "Erste Spalte als Kopfspalte formatieren";
  const numbered = Boolean(currentTableNode()?.entry.attrs.tableId);
  $("table-caption").setAttribute("aria-pressed", String(numbered));
  $("table-caption").textContent = numbered ? "Beschriftung bearbeiten …" : "Beschriftung …";
  for (const select of [$("table-row-action"), $("table-column-action"), $("insert-menu")]) {
    select.querySelectorAll("option").forEach((option) => {
      if (tableReorderCommands.has(option.value)) {
        const rowMove = option.value.startsWith("moveRow");
        const minimum = rowMove ? (reorder?.header ? 1 : 0) : (reorder?.headerColumn ? 1 : 0);
        const from = rowMove ? rect?.top : rect?.left; const to = rowMove ? rect?.bottom : rect?.right;
        const limit = rowMove ? rowCount : columnCount;
        option.disabled = !rect || !allowed || !reorder || from < minimum ||
          (option.value.endsWith("Before") ? from <= minimum : to >= limit);
        return;
      }
      if (tableDuplicateCommands.has(option.value)) {
        const rows = option.value === "duplicateRows";
        const minimum = rows ? (reorder?.header ? 1 : 0) : (reorder?.headerColumn ? 1 : 0);
        const from = rows ? rect?.top : rect?.left; const to = rows ? rect?.bottom : rect?.right;
        const count = rows ? rowCount : columnCount; const maximum = rows ? 200 : 20;
        option.disabled = !rect || !allowed || !reorder || from < minimum || count + to - from > maximum;
        return;
      }
      if (!Object.hasOwn(tableCommands, option.value)) return;
      option.disabled = !rect || !allowed ||
        (option.value === "deleteRow" && rect.bottom - rect.top === rowCount) ||
        (option.value === "deleteColumn" && rect.right - rect.left === columnCount);
    });
  }
}

function openTableCaption() {
  if (!replacementAllowed()) return;
  const current = currentTableNode();
  if (!current) return;
  let attrs, inventory;
  try { attrs = officeTableAttributes(current.entry.attrs); inventory = officeTableInventory(state.editor.getJSON()); }
  catch { return; }
  if (!attrs.tableId && inventory.length >= OFFICE_NUMBERED_TABLE_LIMIT) {
    $("table-message").textContent = `Ein Dokument unterstützt höchstens ${OFFICE_NUMBERED_TABLE_LIMIT} nummerierte Tabellen.`;
    return;
  }
  closeTableDialogs();
  state.tableAction = { ...tableActionSnapshot("caption"), position: current.position, table: current.entry };
  $("table-caption-text").value = attrs.caption || "";
  $("table-caption-remove").disabled = !attrs.tableId;
  $("table-caption-dialog").showModal();
  $("table-caption-text").focus();
}

function selectedTableCells(editor = state.editor) {
  const rect = currentTable(editor);
  if (!rect) return [];
  return [...new Set(rect.map.cellsInRect(rect))].map((offset) => rect.tableStart + offset);
}

function openTableCellStyle() {
  if (!replacementAllowed()) return;
  const positions = selectedTableCells();
  if (!positions.length) return;
  const cells = positions.map((position) => officeTableCellAttributes(state.editor.state.doc.nodeAt(position)?.attrs));
  const uniform = (key) => cells.every((attrs) => (attrs[key] || null) === (cells[0][key] || null)) ?
    (cells[0][key] || "default") : "mixed";
  closeTableDialogs();
  state.tableAction = { ...tableActionSnapshot("cellStyle"), positions };
  $("table-cell-fill").value = uniform("background");
  $("table-cell-vertical").value = uniform("verticalAlign");
  $("table-cell-horizontal").value = uniform("horizontalAlign");
  $("table-cell-padding").value = uniform("padding");
  $("table-cell-border").value = uniform("border");
  $("table-cell-style-summary").textContent = `${positions.length} ${positions.length === 1 ? "Zelle" : "Zellen"} ausgewählt.`;
  $("table-cell-style-dialog").showModal();
  $("table-cell-fill").focus();
}

function tableLayoutValue(attrs, key) { return attrs[key] || "default"; }

function openTableLayout() {
  if (!replacementAllowed()) return;
  const current = currentTableNode();
  if (!current) return;
  let attrs;
  try { attrs = officeTableAttributes(current.entry.attrs); } catch { return; }
  closeTableDialogs();
  state.tableAction = { ...tableActionSnapshot("layout"), position: current.position, table: current.entry };
  $("table-layout-style").value = tableLayoutValue(attrs, "style");
  $("table-layout-width").value = tableLayoutValue(attrs, "width");
  $("table-layout-align").value = tableLayoutValue(attrs, "align");
  $("table-layout-columns").value = tableLayoutValue(attrs, "columns");
  $("table-layout-caption").value = tableLayoutValue(attrs, "captionPosition");
  $("table-layout-summary").textContent = `${current.entry.childCount} ${current.entry.childCount === 1 ? "Zeile" : "Zeilen"} · feste, drucksichere Layoutwerte`;
  $("table-layout-dialog").showModal();
  $("table-layout-style").focus();
}

function commitTableLayout(event, reset = false) {
  event?.preventDefault();
  const action = state.tableAction;
  if (!tableActionCurrent(action) || action.kind !== "layout") { closeTableDialogs(); return; }
  try {
    const current = officeTableAttributes(action.table.attrs);
    const optional = (id) => reset || $(id).value === "default" ? null : $(id).value;
    const attrs = officeTableAttributes({ ...current, style: optional("table-layout-style"),
      width: optional("table-layout-width"), align: optional("table-layout-align"),
      columns: optional("table-layout-columns"), captionPosition: optional("table-layout-caption") });
    const transaction = action.editor.state.tr.setNodeMarkup(action.position, undefined, attrs);
    if (!commitTableTransaction(transaction, reset ? "Tabellenlayout auf Standard zurückgesetzt." :
      "Tabellenlayout übernommen. Gespeichert wird erst mit der nächsten bestätigten Version.")) closeTableDialogs(true);
  } catch {
    $("table-layout-status").textContent = "Das Tabellenlayout konnte nicht sicher übernommen werden.";
  }
}

function openTableSort() {
  if (!replacementAllowed()) return;
  const current = currentTableNode(); const rect = currentTable();
  if (!current || !rect) return;
  let info;
  try { info = officeTableSortInfo(current.entry.toJSON()); } catch {
    $("table-message").textContent = "Sortieren ist nur für Tabellen ohne verbundene Zellen verfügbar."; return;
  }
  if (info.dataRows < 2) { $("table-message").textContent = "Zum Sortieren sind mindestens zwei Datenzeilen erforderlich."; return; }
  closeTableDialogs();
  state.tableAction = { ...tableActionSnapshot("sort"), position: current.position, table: current.entry };
  const select = $("table-sort-column"); select.replaceChildren();
  for (let column = 0; column < info.columns; column += 1) {
    const option = document.createElement("option"); option.value = String(column);
    const heading = info.header ? officeTableCellText(current.entry.firstChild.child(column).toJSON()) : "";
    option.textContent = heading ? `Spalte ${column + 1} — ${heading.slice(0, 80)}` : `Spalte ${column + 1}`;
    select.append(option);
  }
  select.value = String(Math.min(rect.left, info.columns - 1));
  $("table-sort-summary").textContent = `${info.dataRows} Datenzeilen · ${info.header ? "Kopfzeile bleibt oben" : "keine Kopfzeile erkannt"}`;
  $("table-sort-dialog").showModal(); select.focus();
}

function commitTableSort(event) {
  event.preventDefault();
  const action = state.tableAction;
  if (!tableActionCurrent(action) || action.kind !== "sort") { closeTableDialogs(); return; }
  try {
    const options = { column: Number($("table-sort-column").value), type: $("table-sort-type").value,
      direction: $("table-sort-direction").value };
    const original = action.table.toJSON(); let sorted = sortOfficeTable(original, options);
    if (tableContainsFormulas(original)) {
      const rowMap = sorted.content.map((row) => ({ source: original.content.indexOf(row), duplicate: false }));
      sorted = remapOfficeTableFormulas(original, sorted,
        { rows: rowMap, columns: formulaIdentityMap(original.content[0].content.length) });
    }
    const replacement = action.editor.schema.nodeFromJSON(sorted);
    if (replacement.eq(action.table)) {
      $("table-sort-status").textContent = "Die Tabelle ist bereits in dieser Reihenfolge sortiert."; return;
    }
    const info = officeTableSortInfo(sorted), map = TableMap.get(replacement), row = info.header ? 1 : 0;
    const transaction = action.editor.state.tr.replaceWith(action.position, action.position + action.table.nodeSize, replacement);
    transaction.setSelection(Selection.near(transaction.doc.resolve(action.position + 1 + map.map[row * map.width + options.column] + 1)));
    if (!commitTableTransaction(transaction, "Datenzeilen sortiert. Die Änderung lässt sich rückgängig machen und wird erst mit der nächsten Version gespeichert.")) {
      closeTableDialogs(true);
    }
  } catch {
    $("table-sort-status").textContent = "Alle Werte der gewählten Spalte müssen zum ausgewählten Datentyp passen; leere Zellen bleiben am Ende.";
    $("table-sort-status").classList.add("error");
  }
}

function openTableFormula() {
  if (!replacementAllowed()) return;
  const current = currentTableNode(); const rect = currentTable();
  if (!current || !rect || rect.bottom - rect.top !== 1 || rect.right - rect.left !== 1) return;
  try {
    officeTableReorderInfo(current.entry.toJSON());
    const cell = current.entry.child(rect.top).child(rect.left);
    if (cell.type.name !== "tableCell") throw new Error("header");
    closeTableDialogs();
    state.tableAction = { ...tableActionSnapshot("formula"), position: current.position, table: current.entry,
      row: rect.top, column: rect.left };
    $("table-formula-source").value = cell.attrs.formula || "=";
    $("table-formula-summary").textContent = `Zelle ${String.fromCharCode(65 + rect.left)}${rect.top + 1}${cell.attrs.formulaResult ? ` · Ergebnis ${cell.attrs.formulaResult}` : ""}`;
    $("table-formula-remove").disabled = !cell.attrs.formula;
    $("table-formula-dialog").showModal(); $("table-formula-source").focus();
  } catch {
    $("table-message").textContent = "Formeln sind nur in einzelnen Datenzellen einfacher Tabellen verfügbar.";
  }
}

function commitTableFormula(event, remove = false) {
  event?.preventDefault();
  const action = state.tableAction;
  if (!tableActionCurrent(action) || action.kind !== "formula") { closeTableDialogs(); return; }
  try {
    const options = { row: action.row, column: action.column };
    const calculated = remove ? clearOfficeTableFormula(action.table.toJSON(), options) :
      setOfficeTableFormula(action.table.toJSON(), { ...options, formula: $("table-formula-source").value });
    const replacement = action.editor.schema.nodeFromJSON(calculated); const map = TableMap.get(replacement);
    const transaction = action.editor.state.tr.replaceWith(action.position, action.position + action.table.nodeSize, replacement);
    transaction.setSelection(Selection.near(transaction.doc.resolve(action.position + 1 +
      map.map[action.row * map.width + action.column] + 1)));
    if (!commitTableTransaction(transaction, remove ? "Tabellenformel entfernt; der letzte Ergebniswert bleibt als Zellinhalt erhalten." :
      "Tabellenformel berechnet. Änderungen an lokalen Bezugszellen aktualisieren das Ergebnis automatisch.")) closeTableDialogs(true);
  } catch {
    $("table-formula-status").textContent = "Die Formel ist ungültig. Verwenden Sie nur lokale Bezüge A1 bis T200 und die unterstützten Funktionen.";
    $("table-formula-status").classList.add("error");
  }
}

function commitTableCellStyle(event, reset = false) {
  event?.preventDefault();
  const action = state.tableAction;
  if (!tableActionCurrent(action) || action.kind !== "cellStyle") { closeTableDialogs(); return; }
  const fill = $("table-cell-fill").value;
  const vertical = $("table-cell-vertical").value;
  const horizontal = $("table-cell-horizontal").value;
  const padding = $("table-cell-padding").value;
  const border = $("table-cell-border").value;
  const chosen = (value, current) => reset ? null : value === "mixed" ? current : value === "default" ? null : value;
  try {
    let transaction = action.editor.state.tr;
    for (const position of action.positions) {
      const node = transaction.doc.nodeAt(position);
      if (!node || !["tableCell", "tableHeader"].includes(node.type.name)) throw new Error("table-cell-style");
      const current = officeTableCellAttributes(node.attrs);
      const attrs = officeTableCellAttributes({ ...current,
        background: chosen(fill, current.background),
        verticalAlign: chosen(vertical, current.verticalAlign),
        horizontalAlign: chosen(horizontal, current.horizontalAlign),
        padding: chosen(padding, current.padding),
        border: chosen(border, current.border),
      });
      transaction = transaction.setNodeMarkup(position, undefined, attrs);
    }
    if (!commitTableTransaction(transaction, reset ? "Zellformatierung auf Standard zurückgesetzt." :
      "Zellformatierung übernommen. Gespeichert wird erst mit der nächsten bestätigten Version.")) {
      closeTableDialogs(true);
    }
  } catch {
    $("table-cell-style-status").textContent = "Die ausgewählten Zellen konnten nicht sicher formatiert werden.";
  }
}

function commitTableCaption(remove = false) {
  const action = state.tableAction;
  if (!tableActionCurrent(action) || action.kind !== "caption") { closeTableDialogs(); return; }
  let attrs = {};
  try {
    const current = officeTableAttributes(action.table.attrs);
    if (!remove) {
      const caption = $("table-caption-text").value.trim();
      attrs = officeTableAttributes({ ...current, caption,
        tableId: action.table.attrs.tableId || `table-${mutationReference().replaceAll("-", "").slice(0, 24)}` });
    } else attrs = officeTableAttributes({ ...current, caption: null, tableId: null });
    const transaction = action.editor.state.tr.setNodeMarkup(action.position, undefined, attrs);
    validateEditorDocument(transaction.doc);
    closeTableDialogs();
    action.editor.view.dispatch(closeHistory(transaction).scrollIntoView());
    action.editor.view.dispatch(closeHistory(action.editor.state.tr));
    focusEditor(action.editor); updateEditorState();
    notice(remove ? "Tabellenbeschriftung entfernt. Vorhandene Querverweise zeigen das fehlende Ziel an." :
      "Tabellenbeschriftung übernommen. Gespeichert wird erst mit der nächsten bestätigten Version.");
  } catch {
    $("table-caption-status").textContent = "Geben Sie eine nicht leere Beschriftung mit höchstens 1000 Zeichen ein.";
    $("table-caption-status").classList.add("error");
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

function tableContainsFormulas(value) {
  return value.content.some((row) => row.content.some((cell) => cell.attrs?.formula != null));
}

function formulaIdentityMap(length) {
  return Array.from({ length }, (_entry, source) => ({ source, duplicate: false }));
}

function formulaInsertMap(length, index) {
  const result = formulaIdentityMap(length);
  result.splice(index, 0, { source: Math.min(index, length - 1), duplicate: true });
  return result;
}

function formulaDeleteMap(length, from, to) {
  return formulaIdentityMap(length).filter((entry) => entry.source < from || entry.source >= to);
}

function formulaMoveMap(length, from, to, direction) {
  const result = formulaIdentityMap(length); const block = result.splice(from, to - from);
  result.splice(direction === "before" ? from - 1 : from + 1, 0, ...block); return result;
}

function formulaDuplicateMap(length, from, to) {
  const result = formulaIdentityMap(length);
  result.splice(to, 0, ...Array.from({ length: to - from }, (_entry, offset) =>
    ({ source: from + offset, duplicate: true })));
  return result;
}

function remapStructuralFormulas(original, transformed, rows, columns) {
  return tableContainsFormulas(original) ? remapOfficeTableFormulas(original, transformed, { rows, columns }) : transformed;
}

function runTableCommand(command, confirmed = false, firstColumn = false) {
  if (!replacementAllowed() || !Object.hasOwn(tableCommands, command)) return false;
  const editor = state.editor;
  const rect = currentTable(); const current = currentTableNode();
  if (!rect || !current) return false;
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
    let remainingTable = transaction.doc.nodeAt(rect.tableStart - 1);
    if (remainingTable?.type.name === "table") {
      const original = current.entry.toJSON(); const transformed = remainingTable.toJSON();
      let rows = formulaIdentityMap(original.content.length);
      let columns = formulaIdentityMap(original.content[0].content.length);
      if (command === "addRowBefore") rows = formulaInsertMap(rows.length, rect.top);
      if (command === "addRowAfter") rows = formulaInsertMap(rows.length, rect.bottom);
      if (command === "deleteRow") rows = formulaDeleteMap(rows.length, rect.top, rect.bottom);
      if (command === "addColumnBefore") columns = formulaInsertMap(columns.length, rect.left);
      if (command === "addColumnAfter") columns = formulaInsertMap(columns.length, rect.right);
      if (command === "deleteColumn") columns = formulaDeleteMap(columns.length, rect.left, rect.right);
      const remapped = editor.schema.nodeFromJSON(remapStructuralFormulas(original, transformed, rows, columns));
      transaction = editor.state.tr.replaceWith(current.position, current.position + current.entry.nodeSize, remapped);
      remainingTable = remapped;
      const map = TableMap.get(remainingTable);
      const row = command === "addRowAfter" ? rect.bottom : Math.min(rect.top, map.height - 1);
      const column = firstColumn ? 0 : command === "addColumnAfter" ? rect.right : Math.min(rect.left, map.width - 1);
      transaction.setSelection(Selection.near(transaction.doc.resolve(rect.tableStart + map.map[row * map.width + column] + 1)));
    }
  }
  return commitTableTransaction(transaction, command.startsWith("delete") ? "Auswahl aus dem Entwurf entfernt. Rückgängig ist möglich." : "Tabelle erweitert. Änderungen bleiben im Entwurf.");
}

function runTableReorder(command) {
  if (!replacementAllowed() || !tableReorderCommands.has(command)) return false;
  const editor = state.editor; const rect = currentTable(); const current = currentTableNode();
  if (!rect || !current) return false;
  try {
    const rowMove = command.startsWith("moveRow"); const direction = command.endsWith("Before") ? "before" : "after";
    const options = { from: rowMove ? rect.top : rect.left, to: rowMove ? rect.bottom : rect.right, direction };
    const original = current.entry.toJSON(); let moved = rowMove ? moveOfficeTableRows(original, options) :
      moveOfficeTableColumns(current.entry.toJSON(), options);
    const rows = rowMove ? formulaMoveMap(original.content.length, options.from, options.to, direction) :
      formulaIdentityMap(original.content.length);
    const columns = rowMove ? formulaIdentityMap(original.content[0].content.length) :
      formulaMoveMap(original.content[0].content.length, options.from, options.to, direction);
    moved = remapStructuralFormulas(original, moved, rows, columns);
    const replacement = editor.schema.nodeFromJSON(moved); const map = TableMap.get(replacement);
    const top = rowMove ? rect.top + (direction === "before" ? -1 : 1) : rect.top;
    const left = rowMove ? rect.left : rect.left + (direction === "before" ? -1 : 1);
    const bottom = top + (rect.bottom - rect.top); const right = left + (rect.right - rect.left);
    const transaction = editor.state.tr.replaceWith(current.position, current.position + current.entry.nodeSize, replacement);
    transaction.setSelection(CellSelection.create(transaction.doc,
      current.position + 1 + map.map[top * map.width + left],
      current.position + 1 + map.map[(bottom - 1) * map.width + right - 1]));
    return commitTableTransaction(transaction, rowMove ?
      `Ausgewählte Zeilen nach ${direction === "before" ? "oben" : "unten"} verschoben.` :
      `Ausgewählte Spalten nach ${direction === "before" ? "links" : "rechts"} verschoben.`);
  } catch {
    $("table-message").textContent = "Umordnen ist nur innerhalb einfacher Tabellen möglich; Kopfzeile und Kopfspalte bleiben geschützt.";
    focusEditor();
    return false;
  }
}

function runTableDuplicate(command) {
  if (!replacementAllowed() || !tableDuplicateCommands.has(command)) return false;
  const editor = state.editor; const rect = currentTable(); const current = currentTableNode();
  if (!rect || !current) return false;
  try {
    const rows = command === "duplicateRows";
    const options = { from: rows ? rect.top : rect.left, to: rows ? rect.bottom : rect.right };
    const original = current.entry.toJSON(); let duplicated = rows ? duplicateOfficeTableRows(original, options) :
      duplicateOfficeTableColumns(original, options);
    const rowMap = rows ? formulaDuplicateMap(original.content.length, options.from, options.to) :
      formulaIdentityMap(original.content.length);
    const columnMap = rows ? formulaIdentityMap(original.content[0].content.length) :
      formulaDuplicateMap(original.content[0].content.length, options.from, options.to);
    duplicated = remapStructuralFormulas(original, duplicated, rowMap, columnMap);
    const replacement = editor.schema.nodeFromJSON(duplicated); const map = TableMap.get(replacement);
    const top = rows ? rect.bottom : rect.top; const left = rows ? rect.left : rect.right;
    const bottom = top + (rect.bottom - rect.top); const right = left + (rect.right - rect.left);
    const transaction = editor.state.tr.replaceWith(current.position, current.position + current.entry.nodeSize, replacement);
    transaction.setSelection(CellSelection.create(transaction.doc,
      current.position + 1 + map.map[top * map.width + left],
      current.position + 1 + map.map[(bottom - 1) * map.width + right - 1]));
    return commitTableTransaction(transaction, rows ?
      "Ausgewählte Zeilen direkt darunter dupliziert." : "Ausgewählte Spalten direkt rechts dupliziert.");
  } catch {
    $("table-message").textContent = "Duplizieren ist nur innerhalb der Tabellengrenzen und ohne verbundene Zellen möglich; Kopfzeile und Kopfspalte bleiben geschützt.";
    focusEditor();
    return false;
  }
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
  for (const relative of new Set(rect.map.map.slice(0, rect.map.width))) {
    const position = rect.tableStart + relative;
    const cell = transaction.doc.nodeAt(position);
    transaction.setNodeMarkup(position, type, cell.attrs, cell.marks);
  }
  commitTableTransaction(transaction, allHeaders ? "Kopfzeile in normale Zellen umgewandelt." : "Erste Zeile als Kopfzeile formatiert.");
}

function runTableCellCommand(command, message) {
  if (!replacementAllowed() || !currentTable()) return false;
  const editor = state.editor; let transaction = null;
  command(editor.state, (candidate) => { transaction = candidate; });
  return commitTableTransaction(transaction, message);
}

function toggleTableHeaderColumn() {
  return runTableCellCommand(toggleHeaderColumn, "Kopfspalte umgeschaltet. Änderungen bleiben bis zum Speichern im Entwurf.");
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

function clipboardCellParagraphs(element) {
  const copy = element.cloneNode(true);
  copy.querySelectorAll("script,style,link,meta,img,svg,math,object,embed,iframe,input,button,textarea,select,table")
    .forEach((entry) => entry.remove());
  const paragraphs = [[]]; let characters = 0; let nodes = 0;
  const newParagraph = () => { if (paragraphs.at(-1).length) paragraphs.push([]); };
  const addText = (value, marks) => {
    const text = value.replaceAll("\u00a0", " ").replaceAll("\r", "")
      .replace(/[\u0000-\u0008\u000b\u000c\u000e-\u001f\u007f-\u009f]/gu, "");
    characters += Array.from(text).length;
    if (characters > 10000) throw new TypeError("Office clipboard cell too large");
    if (text) paragraphs.at(-1).push({ type: "text", text, ...(marks.length ? { marks } : {}) });
  };
  const visit = (entry, inherited = []) => {
    nodes += 1; if (nodes > 2000) throw new TypeError("Office clipboard cell too complex");
    if (entry.nodeType === 3) { addText(entry.nodeValue || "", inherited); return; }
    if (entry.nodeType !== 1) return;
    const name = entry.tagName.toLowerCase();
    if (name === "br") { paragraphs.at(-1).push({ type: "hardBreak" }); return; }
    const markType = ({ b: "bold", strong: "bold", i: "italic", em: "italic", u: "underline",
      s: "strike", strike: "strike", del: "strike", code: "code" })[name];
    const marks = markType && !inherited.some((mark) => mark.type === markType) ? [...inherited, { type: markType }] : inherited;
    const block = ["p", "div", "li"].includes(name); if (block) newParagraph();
    for (const child of entry.childNodes) visit(child, marks);
    if (block) newParagraph();
  };
  for (const child of copy.childNodes) visit(child);
  while (paragraphs.length > 1 && !paragraphs.at(-1).length) paragraphs.pop();
  return paragraphs.map((content) => ({ type: "paragraph", ...(content.length ? { content } : {}) }));
}

function clipboardCellPresentation(element) {
  const attrs = {}; const horizontal = (element.style.textAlign || element.getAttribute("align") || "").toLowerCase();
  const vertical = (element.style.verticalAlign || element.getAttribute("valign") || "").toLowerCase();
  if (["center", "right"].includes(horizontal)) attrs.horizontalAlign = horizontal;
  if (["middle", "bottom"].includes(vertical)) attrs.verticalAlign = vertical;
  const inlineColor = /(?:^|;)\s*background(?:-color)?\s*:\s*([^;]+)/iu.exec(element.getAttribute("style") || "")?.[1];
  const color = (inlineColor || element.style.backgroundColor || element.getAttribute("bgcolor") || "")
    .trim().replaceAll(" ", "").toLowerCase();
  const fills = { "#f2f2f2": "gray", "rgb(242,242,242)": "gray", "#d9eaf7": "blue", "rgb(217,234,247)": "blue",
    "#e2f0d9": "green", "rgb(226,240,217)": "green", "#fff2cc": "yellow", "rgb(255,242,204)": "yellow",
    "#f4cccc": "red", "rgb(244,204,204)": "red" };
  if (fills[color]) attrs.background = fills[color];
  return attrs;
}

function officeTableFromClipboardHTML(html) {
  if (typeof html !== "string" || !html.trim() || html.length > 400000) return null;
  const parsed = new DOMParser().parseFromString(html, "text/html"); const tables = [...parsed.querySelectorAll("table")];
  if (!tables.length) return null;
  if (tables.length !== 1) throw new TypeError("Office clipboard contains multiple tables");
  const source = tables[0]; const rows = [...source.rows];
  if (!rows.length || rows.length > 200) throw new TypeError("Invalid Office clipboard rows");
  const table = { type: "table", content: rows.map((row) => ({ type: "tableRow", content: [...row.cells].map((cell) => {
    if (cell.querySelector("table")) throw new TypeError("Nested Office clipboard table");
    const colspan = Number(cell.getAttribute("colspan") || 1), rowspan = Number(cell.getAttribute("rowspan") || 1);
    const formulaValue = cell.getAttribute("data-office-formula") || cell.getAttribute("data-formula") ||
      cell.getAttribute("x:fmla");
    let formula = null;
    if (formulaValue && cell.tagName.toLowerCase() !== "th") {
      try {
        formula = officeTableFormulaSource(formulaValue);
      } catch (_error) {
        // Excel can expose R1C1, external workbook or vendor-specific formulas.
        // Keep the displayed value instead of rejecting an otherwise valid table.
      }
    }
    const attrs = officeTableCellAttributes({ colspan, rowspan, ...clipboardCellPresentation(cell),
      ...(formula ? { formula, formulaResult: "#WERT!" } : {}) });
    return { type: cell.tagName.toLowerCase() === "th" ? "tableHeader" : "tableCell", attrs,
      content: formula ? [{ type: "paragraph", content: [{ type: "text", text: "#WERT!" }] }] : clipboardCellParagraphs(cell) };
  }) })) };
  officeTableGrid(table); return recalculateOfficeTableFormulas(table);
}

function insertClipboardTable(view, event) {
  if (state.editor?.view !== view || !replacementAllowed() || !event.clipboardData ||
      view.state.selection instanceof AllSelection) return false;
  const html = event.clipboardData.getData("text/html") || ""; const text = event.clipboardData.getData("text/plain") || "";
  let table = null; const containsHTMLTable = /<table[\s>]/iu.test(html);
  try { table = officeTableFromClipboardHTML(html) || officeTableFromTSV(text); }
  catch {
    if (containsHTMLTable || text.includes("\t")) {
      event.preventDefault(); notice("Die kopierte Tabelle ist zu groß, unregelmäßig oder enthält nicht unterstützte Formeln. Der Entwurf blieb unverändert.", true); return true;
    }
  }
  if (!table) return false;
  event.preventDefault();
  try {
    if (isInTable(view.state)) {
      const rect = selectedRect(view.state); const current = currentTableNode(state.editor);
      if (!current) throw new TypeError("Missing Office table paste target");
      const pasted = pasteOfficeTableCells(current.entry.toJSON(), table,
        { top: rect.top, left: rect.left, bottom: rect.bottom, right: rect.right });
      const replacement = view.state.schema.nodeFromJSON(pasted); const map = TableMap.get(replacement);
      const singleTarget = rect.bottom - rect.top === 1 && rect.right - rect.left === 1;
      const lastRow = (singleTarget ? rect.top + table.content.length : rect.bottom) - 1;
      const lastColumn = (singleTarget ? rect.left + table.content[0].content.length : rect.right) - 1;
      const transaction = view.state.tr.replaceWith(current.position, current.position + current.entry.nodeSize, replacement);
      transaction.setSelection(CellSelection.create(transaction.doc,
        current.position + 1 + map.map[rect.top * map.width + rect.left],
        current.position + 1 + map.map[lastRow * map.width + lastColumn]));
      return commitTableTransaction(transaction,
        "Word-/Excel-Zellen sicher eingefügt. Formeln wurden relativ angepasst; aktive Inhalte und externe Bezüge wurden nicht übernommen.");
    }
    const node = view.state.schema.nodeFromJSON(table); const transaction = view.state.tr.replaceSelectionWith(node);
    return commitTableTransaction(transaction, "Word-/Excel-Tabelle sicher eingefügt. Aktive Inhalte und externe Bezüge wurden nicht übernommen.");
  } catch {
    notice("Die kopierte Tabelle überschreitet die unterstützte Dokumentgröße oder Struktur. Der Entwurf blieb unverändert.", true); return true;
  }
}

function refreshTableFormulaResults(editor) {
  if (state.formulaRecalculating || editor !== state.editor) return false;
  const replacements = [];
  editor.state.doc.descendants((entry, position) => {
    if (entry.type.name !== "table" || !entry.toJSON().content.some((row) => row.content.some((cell) => cell.attrs?.formula))) return;
    let replacement;
    try { replacement = editor.schema.nodeFromJSON(recalculateOfficeTableFormulas(entry.toJSON())); }
    catch { return false; }
    let rowPosition = position + 1;
    for (let rowIndex = 0; rowIndex < entry.childCount; rowIndex += 1) {
      const row = entry.child(rowIndex), calculatedRow = replacement.child(rowIndex); let cellPosition = rowPosition + 1;
      for (let cellIndex = 0; cellIndex < row.childCount; cellIndex += 1) {
        const cell = row.child(cellIndex), calculatedCell = calculatedRow.child(cellIndex);
        if (cell.attrs.formula && !calculatedCell.eq(cell)) replacements.push({ position: cellPosition, entry: cell, replacement: calculatedCell });
        cellPosition += cell.nodeSize;
      }
      rowPosition += row.nodeSize;
    }
    return false;
  });
  if (!replacements.length) return false;
  let transaction = editor.state.tr;
  for (const item of replacements.reverse()) {
    transaction = transaction.setNodeMarkup(item.position, undefined, item.replacement.attrs)
      .replaceWith(item.position + 1, item.position + 1 + item.entry.content.size, item.replacement.content);
  }
  try { validateEditorDocument(transaction.doc); }
  catch { return false; }
  state.formulaRecalculating = true;
  try { editor.view.dispatch(transaction.setMeta("addToHistory", false)); }
  finally { state.formulaRecalculating = false; }
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
  pageControls.close();
  imageControls.close();
  chartControls.close();
  closeSectionDialog();
  closeReuse();
  closePrint();
  closeTableDialogs();
  closeParagraphDialog();
  closeCharacterDialog();
  closeLinkDialog();
  closeBookmarkDialog();
  closeCrossReferenceDialog();
  closeSemanticDialog();
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
      TableKit.configure({ table: false }), OfficeTable.configure({ resizable: false }), OfficeTableCellStyle, OfficeParagraphFormat, OfficeCharacterFormat, OfficeLink, OfficeBookmark, OfficeCrossReference, OfficeDocumentReference,
      officeDocumentCardExtension(() => state.documentReferenceResolutions, () => void documentCardControls.open()),
      officeChartExtension(() => void chartControls.open()),
      OfficeDocumentField, OfficeNoteReference, OfficeCitationReference, OfficeTableOfContents, OfficeBibliography, OfficeEquation, OfficeReferenceIndex, OfficeSemantics,
      SearchHighlights, NativeDocumentGuard, ReviewHighlight, OfficeNamedStyles, OfficePageBreak, OfficeSectionBreak,
      officeImageGroupExtension(),
      officeShapeGroupExtension(),
      officeShapeExtension(),
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
        if (insertClipboardTable(view, event)) return true;
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
    onUpdate: ({ editor: updatedEditor }) => { if (!refreshTableFormulaResults(updatedEditor)) contentChanged(session); },
    onSelectionUpdate: () => { if (sessionCurrent(session)) updateEditorState(); },
  });
  try {
    validateEditorDocument(editor.schema.nodeFromJSON(safeContent));
    editor.chain().setMeta("addToHistory", false)
      .setContent(safeContent, { emitUpdate: false, errorOnInvalidContent: true })
      .command(({ tr }) => {
        tr.setDocAttribute("styles", safeContent.attrs?.styles || []);
        tr.setDocAttribute("page", safeContent.attrs?.page ?? null); tr.setDocAttribute("running", safeContent.attrs?.running ?? null);
        tr.setDocAttribute("documentFields", safeContent.attrs?.documentFields || []);
        tr.setDocAttribute("citationSources", safeContent.attrs?.citationSources || []); return true;
      }).run();
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
  pageControls.close();
  imageControls.close();
  shapeControls.close();
  chartControls.close();
  closeSectionDialog();
  closeStyleDialog();
  state.formatSample = null;
  closeReuse();
  closePrint();
  clearReview();
  clearSuggestions();
  closeTableDialogs();
  closeParagraphDialog();
  closeCharacterDialog();
  closeDocumentReferenceDialog();
  state.documentReferenceResolutions = new Map();
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
  pageControls.update();
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
  state.documentReferenceResolutions = new Map();
  void refreshDocumentReferences(session);
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
  clearOfficeRunningPrint();
  clearOfficeSectionPrint();
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
  $("print-page-description").textContent = "";
  $("print-preview").removeAttribute("style");
  $("print-submit").disabled = true;
  $("print-dialog").close();
  if (returnFocus && print?.session === state.session && !$("document-print").disabled) $("document-print").focus();
}

function printFormat() {
  const paper = $("print-paper").value === "letter" ? "letter" : "a4";
  const orientation = $("print-orientation").value === "landscape" ? "landscape" : "portrait";
  return `paper-${paper} orientation-${orientation}`;
}

function printPage() {
  return officePageSettings({ paper: $("print-paper").value, orientation: $("print-orientation").value,
    margins: state.print?.margins || officePageSettings().margins });
}

function updatePrintControls() {
  const print = state.print;
  const current = printCurrent(print);
  const busy = Boolean(print?.loading || print?.printing);
  $("print-refresh").disabled = !current || busy;
  $("print-paper").disabled = !current || busy;
  $("print-orientation").disabled = !current || busy;
  $("print-submit").disabled = !current || busy || !print.content;
  $("print-document-settings").disabled = !current || busy || !print.content;
  $("print-preview").className = printFormat();
  officePagePreview($("print-preview"), printPage());
  $("print-page-description").textContent = print.content ? `${officePageDescription(printPage())} · ${officeRunningDescription(print.content.attrs?.running)}` : "";
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
    const referencePayload = await api(`/v1/office/documents/${encodeURIComponent(print.objectId)}/outbound-references?version_id=${encodeURIComponent(print.versionId)}`,
      { signal: print.controller.signal }, print.context);
    const documentReferences = officeDocumentReferenceResolutions(referencePayload, print.objectId, print.versionId);
    if (!current()) return;
    const images = await loadOfficePrintImages(content, print.context, print.controller.signal);
    if (!current()) { for (const url of images.values()) URL.revokeObjectURL(url); return; }
    print.images = images;
    const preview = renderOfficePrintDocument(content, result.version.title, document, images, documentReferences);
    if (!current()) return;
    print.content = content;
    const savedPage = officePageSettings(content.attrs?.page);
    print.margins = savedPage.margins;
    if (!print.settingsInitialized) {
      $("print-paper").value = savedPage.paper; $("print-orientation").value = savedPage.orientation;
      print.settingsInitialized = true;
    }
    $("print-preview").replaceChildren(preview);
    $("print-version").textContent = `${result.version.title} · ${dateLabel(result.version.created_at_utc)} · Version ${print.versionId}`;
    $("print-status").textContent = "Druckansicht bereit. Vor dem Drucken wird diese Fassung erneut geprüft.";
    if (finalAction) {
      // The print surface is made from this fresh response, never from the live
      // editor, the preview DOM, or an older cached authorization result.
      const root = $("office-print-root");
      state.preparedPrint = print;
      root.replaceChildren(renderOfficePrintDocument(content, result.version.title, document, images, documentReferences));
      await Promise.all([...root.querySelectorAll("img")].map((image) => image.decode()));
      if (!current()) return;
      root.className = printFormat();
      configureOfficePrintPage(printPage());
      configureOfficeRunningPrint(officeResolveRunningFields(content.attrs?.running, content.attrs?.documentFields || []), printPage());
      configureOfficeSectionPrint(content);
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
    $("print-status").textContent = error.message === "Office running print unsupported" ? "Ihr Browser unterstützt Kopf-/Fußzeilen im Druck nicht. Verwenden Sie einen aktuellen Chromium-Browser und prüfen Sie die Druckvorschau." : "Die Druckansicht ist gerade nicht verfügbar. Bitte erneut laden.";
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
$("print-document-settings").addEventListener("click", () => {
  if (!printCurrent(state.print) || state.print.loading || state.print.printing || !state.print.content) return;
  const page = officePageSettings(state.print.content.attrs?.page);
  $("print-paper").value = page.paper; $("print-orientation").value = page.orientation;
  updatePrintControls();
});
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
$("link-options").addEventListener("mousedown", (event) => { if (event.button === 0) event.preventDefault(); });
$("link-options").addEventListener("click", openLinkDialog);
$("link-form").addEventListener("submit", (event) => { event.preventDefault(); commitLink(); });
$("link-remove").addEventListener("click", () => commitLink(true));
$("link-open").addEventListener("click", openSelectedLink);
$("link-href").addEventListener("input", () => { $("link-status").classList.remove("error"); });
for (const id of ["link-close", "link-cancel"]) $(id).addEventListener("click", () => closeLinkDialog(true));
$("link-dialog").addEventListener("cancel", (event) => { event.preventDefault(); closeLinkDialog(true); });
$("link-dialog").addEventListener("close", () => { if (!$("link-dialog").open && state.linkAction) closeLinkDialog(); });
$("bookmark-options").addEventListener("mousedown", (event) => { if (event.button === 0) event.preventDefault(); });
$("bookmark-options").addEventListener("click", openBookmarkDialog);
$("bookmark-form").addEventListener("submit", (event) => { event.preventDefault(); commitBookmark(); });
$("bookmark-remove").addEventListener("click", () => commitBookmark(true));
$("bookmark-label").addEventListener("input", () => $("bookmark-status").classList.remove("error"));
for (const id of ["bookmark-close", "bookmark-cancel"]) $(id).addEventListener("click", () => closeBookmarkDialog(true));
$("bookmark-dialog").addEventListener("cancel", (event) => { event.preventDefault(); closeBookmarkDialog(true); });
$("bookmark-dialog").addEventListener("close", () => { if (!$("bookmark-dialog").open && state.bookmarkAction) closeBookmarkDialog(); });
$("cross-reference-options").addEventListener("mousedown", (event) => { if (event.button === 0) event.preventDefault(); });
$("cross-reference-options").addEventListener("click", openCrossReferenceDialog);
$("cross-reference-form").addEventListener("submit", (event) => { event.preventDefault(); commitCrossReference(); });
$("cross-reference-remove").addEventListener("click", () => commitCrossReference(true));
$("cross-reference-jump").addEventListener("click", jumpToCrossReference);
$("cross-reference-target").addEventListener("change", () => {
  const inventory = officeReferenceInventory(state.editor.getJSON()), targetId = $("cross-reference-target").value;
  $("cross-reference-jump").disabled = !inventory.some(({ id }) => id === targetId);
  $("cross-reference-status").textContent = officeCrossReferenceDescription({ targetId }, inventory);
  $("cross-reference-status").classList.remove("error");
});
for (const id of ["cross-reference-close", "cross-reference-cancel"]) $(id).addEventListener("click", () => closeCrossReferenceDialog(true));
$("cross-reference-dialog").addEventListener("cancel", (event) => { event.preventDefault(); closeCrossReferenceDialog(true); });
$("cross-reference-dialog").addEventListener("close", () => { if (!$("cross-reference-dialog").open && state.crossReferenceAction) closeCrossReferenceDialog(); });
$("document-reference-options").addEventListener("mousedown", (event) => { if (event.button === 0) event.preventDefault(); });
$("document-reference-options").addEventListener("click", () => void openDocumentReferenceDialog());
$("document-reference-form").addEventListener("submit", (event) => { event.preventDefault(); commitDocumentReference(); });
$("document-reference-remove").addEventListener("click", () => commitDocumentReference(true));
$("document-reference-open").addEventListener("click", () => void openSelectedDocumentReference());
$("document-reference-target").addEventListener("change", () => {
  const option = $("document-reference-target").selectedOptions[0];
  $("document-reference-apply").disabled = !option || option.dataset.unavailable === "true";
  $("document-reference-status").textContent = option?.dataset.unavailable === "true" ? "Dokumentziel nicht verfügbar" : "Die aktuell freigegebene Zielversion wird fest gespeichert.";
  $("document-reference-status").classList.remove("error");
});
for (const id of ["document-reference-close", "document-reference-cancel"]) $(id).addEventListener("click", () => closeDocumentReferenceDialog(true));
$("document-reference-dialog").addEventListener("cancel", (event) => { event.preventDefault(); closeDocumentReferenceDialog(true); });
$("document-reference-dialog").addEventListener("close", () => { if (!$("document-reference-dialog").open && state.documentReferenceAction) closeDocumentReferenceDialog(); });
$("document-backlinks").addEventListener("click", openBacklinksDialog);
$("backlinks-more").addEventListener("click", () => {
  const action = state.backlinksAction;
  if (backlinkActionCurrent(action) && action.cursor) void loadBacklinks(action, action.cursor);
});
for (const id of ["backlinks-close", "backlinks-done"]) $(id).addEventListener("click", closeBacklinksDialog);
$("backlinks-dialog").addEventListener("cancel", (event) => { event.preventDefault(); closeBacklinksDialog(); });
$("backlinks-dialog").addEventListener("close", () => { if (!$("backlinks-dialog").open && state.backlinksAction) closeBacklinksDialog(); });
$("semantic-options").addEventListener("mousedown", (event) => { if (event.button === 0) event.preventDefault(); });
$("semantic-options").addEventListener("click", openSemanticDialog);
$("semantic-kind").addEventListener("change", updateSemanticFields);
$("semantic-form").addEventListener("submit", (event) => { event.preventDefault(); commitSemanticElement(); });
$("semantic-remove").addEventListener("click", removeSemanticCatalogEntry);
for (const id of ["semantic-close", "semantic-cancel"]) $(id).addEventListener("click", () => closeSemanticDialog(true));
$("semantic-dialog").addEventListener("cancel", (event) => { event.preventDefault(); closeSemanticDialog(true); });
$("semantic-dialog").addEventListener("close", () => { if (!$("semantic-dialog").open && state.semanticAction) closeSemanticDialog(); });
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
    else if (command === "sectionBreak") openSectionDialog();
    else if (command === "editSectionBreak") openSectionDialog(true);
    else if (command === "removeSectionBreak") removeSectionBreak();
    else if (command === "horizontalRule") formatEditor((chain) => chain.setHorizontalRule());
    else if (command === "codeBlock") formatEditor((chain) => chain.toggleCodeBlock());
    else runTableCommand(command);
  }
  $("insert-menu").value = "";
});
$("section-form").addEventListener("input", previewSectionProfile);
$("section-form").addEventListener("submit", applySectionProfile);
for (const id of ["section-close", "section-cancel"]) $(id).addEventListener("click", () => closeSectionDialog(true));
$("section-dialog").addEventListener("cancel", (event) => { event.preventDefault(); closeSectionDialog(true); });
$("section-dialog").addEventListener("close", () => { if (!$("section-dialog").open && state.sectionAction) closeSectionDialog(); });
["table-row-action", "table-column-action"].forEach((id) => {
  $(id).addEventListener("change", () => {
    const command = $(id).value; $(id).value = "";
    if (tableReorderCommands.has(command)) runTableReorder(command);
    else if (tableDuplicateCommands.has(command)) runTableDuplicate(command);
    else runTableCommand(command);
  });
});
$("table-select").addEventListener("change", () => { const part = $("table-select").value; $("table-select").value = ""; selectTablePart(part); });
$("table-header-toggle").addEventListener("click", toggleTableHeader);
$("table-header-column-toggle").addEventListener("click", toggleTableHeaderColumn);
$("table-merge").addEventListener("click", () => runTableCellCommand(mergeCells,
  "Ausgewählte Zellen verbunden. Inhalte und Formatierung bleiben erhalten."));
$("table-split").addEventListener("click", () => runTableCellCommand(splitCell,
  "Verbundene Zelle wieder in einzelne Zellen aufgeteilt."));
$("table-caption").addEventListener("click", openTableCaption);
$("table-cell-style").addEventListener("click", openTableCellStyle);
$("table-layout").addEventListener("click", openTableLayout);
$("table-sort").addEventListener("click", openTableSort);
$("table-formula").addEventListener("click", openTableFormula);
$("table-delete").addEventListener("click", () => runTableCommand("deleteTable"));
["table-header-toggle", "table-header-column-toggle", "table-merge", "table-split", "table-caption", "table-cell-style", "table-layout", "table-sort", "table-formula", "table-delete"].forEach((id) => {
  $(id).addEventListener("mousedown", (event) => { if (event.button === 0) event.preventDefault(); });
});
$("table-caption-form").addEventListener("submit", (event) => { event.preventDefault(); commitTableCaption(); });
$("table-caption-remove").addEventListener("click", () => commitTableCaption(true));
$("table-caption-text").addEventListener("input", () => $("table-caption-status").classList.remove("error"));
$("table-cell-style-form").addEventListener("submit", commitTableCellStyle);
$("table-cell-style-reset").addEventListener("click", () => commitTableCellStyle(null, true));
$("table-layout-form").addEventListener("submit", commitTableLayout);
$("table-layout-reset").addEventListener("click", () => commitTableLayout(null, true));
$("table-sort-form").addEventListener("submit", commitTableSort);
$("table-formula-form").addEventListener("submit", commitTableFormula);
$("table-formula-remove").addEventListener("click", () => commitTableFormula(null, true));
$("table-formula-source").addEventListener("input", () => {
  $("table-formula-status").textContent = ""; $("table-formula-status").classList.remove("error");
});
[$("table-sort-column"), $("table-sort-type"), $("table-sort-direction")].forEach((field) => field.addEventListener("change", () => {
  $("table-sort-status").textContent = ""; $("table-sort-status").classList.remove("error");
}));
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
["table-insert-cancel", "table-insert-close", "table-remove-cancel", "table-caption-close", "table-caption-cancel", "table-cell-style-close", "table-cell-style-cancel", "table-layout-close", "table-layout-cancel", "table-sort-close", "table-sort-cancel", "table-formula-close", "table-formula-cancel"].forEach((id) => {
  $(id).addEventListener("click", () => closeTableDialogs(true));
});
["table-insert-dialog", "table-remove-dialog", "table-caption-dialog", "table-cell-style-dialog", "table-layout-dialog", "table-sort-dialog", "table-formula-dialog"].forEach((id) => {
  $(id).addEventListener("cancel", (event) => { event.preventDefault(); closeTableDialogs(true); });
  $(id).addEventListener("close", () => {
    const kind = id === "table-insert-dialog" ? "insert" : id === "table-remove-dialog" ? "remove" :
      id === "table-caption-dialog" ? "caption" : id === "table-cell-style-dialog" ? "cellStyle" :
        id === "table-sort-dialog" ? "sort" : id === "table-formula-dialog" ? "formula" : "layout";
    if (!$(id).open && state.tableAction?.kind === kind) closeTableDialogs();
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

const pageControls = installOfficePageControls({ state, allowed: paragraphAllowed, actionCurrent: characterActionCurrent,
  sessionCurrent, validate: validateEditorDocument, focus: focusEditor, updateEditor: updateEditorState, notice });
const imageControls = installOfficeImageControls({ state,
  allowed: () => paragraphAllowed() && (state.editor.state.selection.empty || ["image", "imageGroup"].includes(state.editor.state.selection.node?.type.name)),
  current: characterActionCurrent,
  validate: validateEditorDocument, focus: focusEditor, notice, accessDenied: officeAccessDenied, reference: mutationReference });
const shapeControls = installOfficeShapeControls({ state, allowed: () => paragraphAllowed(), current: characterActionCurrent,
  validate: validateEditorDocument, focus: focusEditor, updateEditor: updateEditorState, notice });
const chartControls = installOfficeChartControls({ state, $, sessionCurrent, validate: validateEditorDocument,
  update: updateEditorState, notice, focus: focusEditor });
const documentCardControls = installOfficeDocumentCardControls({ state, $, api, sessionCurrent,
  validate: validateEditorDocument, update: updateEditorState, notice, refreshReferences: refreshDocumentReferences,
  openDocument, isDirty });
restoreContext();
toggleInspector(!window.matchMedia("(max-width: 1000px)").matches);
window.matchMedia("(max-width: 1000px)").addEventListener("change", (event) => {
  if (event.matches && !hasReviewDraft() && !state.review?.saving && !hasSuggestionDraft() && !state.suggestions?.saving) {
    clearReview(); clearSuggestions(); toggleInspector(false);
  }
});
loadDocuments();
