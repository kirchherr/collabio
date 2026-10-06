import { Node } from "@tiptap/core";
import { NodeSelection } from "@tiptap/pm/state";
import { closeHistory } from "@tiptap/pm/history";
import { officeDocumentReferenceAttributes, officeDocumentReferenceDescription,
  officeDocumentReferenceKey } from "./office-document-references.mjs";

export const OFFICE_DOCUMENT_CARD_MODES = ["snapshot", "linked"];

export function officeDocumentCardAttributes(value) {
  const reference = officeDocumentReferenceAttributes(value);
  if (!OFFICE_DOCUMENT_CARD_MODES.includes(value?.mode) ||
      Object.keys(value).some((key) => !["targetObjectId", "targetVersionId", "mode"].includes(key))) {
    throw new Error("Invalid document object");
  }
  return { ...reference, mode: value.mode };
}

export function officeDocumentCardDescription(attrs, resolutions = new Map()) {
  attrs = officeDocumentCardAttributes(attrs);
  const target = officeDocumentReferenceDescription(attrs, resolutions);
  return `Dokumentobjekt · ${attrs.mode === "linked" ? "explizit aktualisierbar" : "feste Momentaufnahme"} · ${target}`;
}

export function officeDocumentCardExtension(resolutions, onEdit) {
  return Node.create({
    name: "documentCard", group: "block", atom: true, selectable: true, draggable: false,
    addAttributes() {
      return {
        targetObjectId: { default: null, rendered: false },
        targetVersionId: { default: null, rendered: false },
        mode: { default: "snapshot", rendered: false },
      };
    },
    parseHTML: () => [],
    renderHTML({ node }) {
      const attrs = officeDocumentCardAttributes(node.attrs);
      return ["article", { class: "office-document-card", contenteditable: "false",
        "data-office-document-card": attrs.targetObjectId,
        "data-office-document-version": attrs.targetVersionId,
        "data-office-document-mode": attrs.mode,
        "data-office-reference-status": "unavailable",
        "aria-label": officeDocumentCardDescription(attrs),
      }, "Dokumentobjekt nicht verfügbar"];
    },
    addNodeView() {
      return ({ node: initial, editor, getPos }) => {
        let current = initial;
        const dom = document.createElement("article");
        dom.className = "office-document-card"; dom.contentEditable = "false";
        const kind = document.createElement("span"); kind.className = "office-document-card-kind";
        const title = document.createElement("strong"); title.className = "office-document-card-title";
        const detail = document.createElement("span"); detail.className = "office-document-card-detail";
        const edit = document.createElement("button"); edit.className = "office-document-card-edit";
        edit.type = "button"; edit.textContent = "Dokumentobjekt bearbeiten";
        const paint = () => {
          const attrs = officeDocumentCardAttributes(current.attrs);
          const resolved = resolutions().get(officeDocumentReferenceKey(attrs));
          const available = resolved?.status === "resolved";
          dom.dataset.officeDocumentCard = attrs.targetObjectId;
          dom.dataset.officeDocumentVersion = attrs.targetVersionId;
          dom.dataset.officeDocumentMode = attrs.mode;
          dom.dataset.officeReferenceStatus = available ? "resolved" : "unavailable";
          kind.textContent = attrs.mode === "linked" ? "Verknüpftes Dokument" : "Dokument-Momentaufnahme";
          title.textContent = available ? resolved.title : "Dokumentobjekt nicht verfügbar";
          detail.textContent = available ? `${resolved.isCurrentVersion ? "Aktuelle" : "Gespeicherte"} Version` :
            "Zugriff oder Version nicht verfügbar";
          dom.setAttribute("aria-label", officeDocumentCardDescription(attrs, resolutions()));
        };
        edit.addEventListener("click", () => {
          const position = getPos();
          if (!Number.isInteger(position)) return;
          editor.view.dispatch(editor.state.tr.setSelection(NodeSelection.create(editor.state.doc, position)));
          onEdit();
        });
        dom.append(kind, title, detail, edit); paint();
        return { dom,
          update(updated) { if (updated.type !== current.type) return false; current = updated; paint(); return true; },
          ignoreMutation: () => true,
        };
      };
    },
  });
}

export function installOfficeDocumentCardControls({ state, $, api, sessionCurrent, validate, update,
  notice, refreshReferences, openDocument, isDirty }) {
  let action = null;
  const selected = () => {
    const selection = state.editor?.state.selection;
    return selection instanceof NodeSelection && selection.node.type.name === "documentCard" ? selection : null;
  };
  const allowed = () => Boolean(state.session && sessionCurrent(state.session) && state.editor?.isEditable &&
    state.session.objectId && !state.session.historical && !state.session.loading && !state.session.saving);
  const current = () => Boolean(action && state.session === action.session && state.editor === action.editor &&
    state.context === action.context && action.session.revision === action.revision && $("document-card-dialog").open &&
    (!action.editing || (() => {
      const node = action.editor.state.doc.nodeAt(action.position);
      if (node?.type.name !== "documentCard") return false;
      const attrs = officeDocumentCardAttributes(node.attrs);
      return officeDocumentReferenceKey(attrs) === officeDocumentReferenceKey(action.attrs) && attrs.mode === action.attrs.mode;
    })()));
  const close = (focus = false) => {
    const owner = action; action = null;
    $("document-card-dialog").close(); $("document-card-form").reset();
    $("document-card-target").replaceChildren(); $("document-card-status").textContent = "";
    if (focus && owner?.editor === state.editor) owner.editor.commands.focus();
  };
  const dispatch = (tr, message) => {
    validate(tr.doc); close(); state.editor.view.dispatch(closeHistory(tr).scrollIntoView());
    state.editor.view.dispatch(closeHistory(state.editor.state.tr)); state.editor.commands.focus(); update(); notice(message);
  };
  const options = () => [...$("document-card-target").options];
  const currentTargetOption = (objectId) => options().find((option) => option.dataset.objectId === objectId && option.dataset.current === "true");
  const updateButtons = () => {
    const option = $("document-card-target").selectedOptions[0], editing = Boolean(action?.editing), attrs = action?.attrs;
    $("document-card-apply").disabled = !option || option.dataset.unavailable === "true";
    $("document-card-open").disabled = !editing || action?.resolved?.status !== "resolved" || isDirty();
    $("document-card-refresh").disabled = !editing || attrs?.mode !== "linked" || $("document-card-mode").value !== "linked" ||
      !currentTargetOption(attrs.targetObjectId) || currentTargetOption(attrs.targetObjectId).dataset.versionId === attrs.targetVersionId;
    for (const id of ["document-card-duplicate", "document-card-remove"]) $(id).disabled = !editing;
    $("document-card-previous").disabled = !editing || action.rootIndex === 0;
    $("document-card-next").disabled = !editing || action.rootIndex >= action.editor.state.doc.childCount - 1;
  };
  const open = async () => {
    if (!allowed()) return;
    close();
    const editor = state.editor, selection = selected(), editing = Boolean(selection);
    const attrs = editing ? officeDocumentCardAttributes(selection.node.attrs) : null;
    action = { session: state.session, editor, context: state.context, revision: state.session.revision,
      editing, position: editing ? selection.from : null, attrs, rootIndex: null, resolved: null };
    if (editing) {
      let index = 0;
      editor.state.doc.forEach((_node, offset) => { if (offset === action.position) action.rootIndex = index; index += 1; });
    }
    $("document-card-title").textContent = editing ? "Dokumentobjekt bearbeiten" : "Dokumentobjekt einfügen";
    $("document-card-mode").value = attrs?.mode || "snapshot";
    $("document-card-status").textContent = "Freigegebene Dokumente werden geladen …";
    $("document-card-dialog").showModal();
    try {
      const [payload, resolutions] = await Promise.all([
        api("/v1/office/documents?query=&page_size=200", {}, action.context),
        editing ? refreshReferences(action.session) : Promise.resolve(state.documentReferenceResolutions),
      ]);
      if (!current() || payload?.tenant_id !== action.context.tenantId || !Array.isArray(payload.documents)) return;
      const select = $("document-card-target");
      const documents = payload.documents.filter((entry) => entry.object_id !== action.session.objectId &&
        typeof entry.title === "string" && /^office-doc-[a-f0-9]{32}$/.test(entry.object_id) &&
        /^office-version-[a-f0-9]{32}$/.test(entry.current_version_id));
      for (const entry of documents) {
        const option = new Option(entry.title, officeDocumentReferenceKey({ targetObjectId: entry.object_id,
          targetVersionId: entry.current_version_id }));
        option.dataset.objectId = entry.object_id; option.dataset.versionId = entry.current_version_id;
        option.dataset.current = "true"; option.dataset.title = entry.title; select.append(option);
      }
      action.resolved = attrs ? resolutions.get(officeDocumentReferenceKey(attrs)) : null;
      if (attrs && !options().some((option) => option.value === officeDocumentReferenceKey(attrs))) {
        const available = action.resolved?.status === "resolved";
        const option = new Option(available ? `${action.resolved.title} · gespeicherte Version` : "Dokumentobjekt nicht verfügbar",
          officeDocumentReferenceKey(attrs));
        option.dataset.objectId = attrs.targetObjectId; option.dataset.versionId = attrs.targetVersionId;
        option.dataset.current = "false"; if (available) option.dataset.title = action.resolved.title;
        else option.dataset.unavailable = "true"; select.prepend(option);
      }
      select.value = attrs ? officeDocumentReferenceKey(attrs) : select.options[0]?.value || "";
      $("document-card-status").textContent = select.value ? (editing ? officeDocumentCardDescription(attrs, resolutions) :
        "Die aktuell freigegebene Zielversion wird als inertes Objekt eingefügt.") : "Kein anderes freigegebenes Dokument verfügbar.";
      updateButtons(); select.focus();
    } catch {
      if (current()) $("document-card-status").textContent = "Dokumentziele sind gerade nicht verfügbar.";
    }
  };
  const apply = (forcedOption = null) => {
    if (!current()) { close(); return; }
    const option = forcedOption || $("document-card-target").selectedOptions[0];
    try {
      if (!option || option.dataset.unavailable === "true") throw new Error("unavailable");
      const attrs = officeDocumentCardAttributes({ targetObjectId: option.dataset.objectId,
        targetVersionId: option.dataset.versionId, mode: $("document-card-mode").value });
      const node = action.editor.schema.nodes.documentCard.create(attrs);
      let tr = action.editor.state.tr;
      if (action.editing) tr = tr.setNodeMarkup(action.position, undefined, attrs);
      else tr = tr.replaceSelectionWith(node, false);
      validate(tr.doc);
      if (option.dataset.title) state.documentReferenceResolutions.set(officeDocumentReferenceKey(attrs), {
        ...attrs, status: "resolved", title: option.dataset.title, isCurrentVersion: option.dataset.current === "true",
      });
      dispatch(tr, action.editing ? "Dokumentobjekt aktualisiert. Gespeichert wird erst mit der nächsten bestätigten Version." :
        "Inertes Dokumentobjekt eingefügt. Gespeichert wird erst mit der nächsten bestätigten Version.");
    } catch { $("document-card-status").textContent = "Das Dokumentobjekt konnte an dieser Stelle nicht übernommen werden."; }
  };
  const move = (direction) => {
    if (!current() || !action.editing) return;
    const index = action.rootIndex, target = index + (direction === "previous" ? -1 : 1);
    if (target < 0 || target >= action.editor.state.doc.childCount) return;
    const card = action.editor.state.doc.child(index), other = action.editor.state.doc.child(target);
    const start = direction === "previous" ? action.position - other.nodeSize : action.position;
    const end = direction === "previous" ? action.position + card.nodeSize : action.position + card.nodeSize + other.nodeSize;
    const content = direction === "previous" ? [card, other] : [other, card];
    const next = direction === "previous" ? start : action.position + other.nodeSize;
    const tr = action.editor.state.tr.replaceWith(start, end, content);
    tr.setSelection(NodeSelection.create(tr.doc, next));
    try { dispatch(tr, "Dokumentobjekt im Dokument verschoben."); } catch { $("document-card-status").textContent = "Das Dokumentobjekt konnte nicht verschoben werden."; }
  };
  $("document-card-options").addEventListener("click", () => void open());
  $("document-card-form").addEventListener("submit", (event) => { event.preventDefault(); apply(); });
  $("document-card-refresh").addEventListener("click", () => {
    if (!current() || !action.editing || action.attrs.mode !== "linked") return;
    const option = currentTargetOption(action.attrs.targetObjectId); if (option) apply(option);
  });
  $("document-card-open").addEventListener("click", async () => {
    if (!current() || !action.editing || isDirty()) return;
    const attrs = action.attrs; close(); await openDocument(attrs.targetObjectId, attrs.targetVersionId);
  });
  $("document-card-duplicate").addEventListener("click", () => {
    if (!current() || !action.editing) return;
    const card = action.editor.state.doc.nodeAt(action.position), at = action.position + card.nodeSize;
    const tr = action.editor.state.tr.insert(at, card.copy());
    tr.setSelection(NodeSelection.create(tr.doc, at));
    try { dispatch(tr, "Dokumentobjekt dupliziert. Beide Karten verweisen exakt auf dieselbe gespeicherte Version."); }
    catch { $("document-card-status").textContent = "Das Dokumentobjekt konnte nicht dupliziert werden."; }
  });
  $("document-card-remove").addEventListener("click", () => {
    if (!current() || !action.editing) return;
    const card = action.editor.state.doc.nodeAt(action.position);
    try { dispatch(action.editor.state.tr.delete(action.position, action.position + card.nodeSize), "Dokumentobjekt aus dem Entwurf entfernt."); }
    catch { $("document-card-status").textContent = "Das Dokumentobjekt konnte nicht entfernt werden."; }
  });
  $("document-card-previous").addEventListener("click", () => move("previous"));
  $("document-card-next").addEventListener("click", () => move("next"));
  $("document-card-target").addEventListener("change", updateButtons);
  $("document-card-mode").addEventListener("change", updateButtons);
  for (const id of ["document-card-close", "document-card-cancel"]) $(id).addEventListener("click", () => close(true));
  $("document-card-dialog").addEventListener("cancel", (event) => { event.preventDefault(); close(true); });
  const updateControl = () => {
    $("document-card-options").disabled = !allowed();
    $("document-card-options").textContent = selected() ? "Dokumentobjekt bearbeiten …" : "Dokumentobjekt einfügen …";
  };
  return { update: updateControl, close };
}
