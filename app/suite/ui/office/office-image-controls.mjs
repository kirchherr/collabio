import { Node } from "@tiptap/core";
import { NodeSelection } from "@tiptap/pm/state";
import { closeHistory } from "@tiptap/pm/history";
import { officeImageKeys, officeImageAttributes, officeImageFigure, fetchOfficeImage } from "./office-images.mjs";

export function officeImageExtension(context) {
  return Node.create({
    name: "image", group: "block", atom: true, selectable: true, draggable: false,
    addAttributes: () => Object.fromEntries(officeImageKeys.map((key) => [key, { default: null, rendered: false }])),
    parseHTML: () => [],
    renderHTML: () => ["figure", { class: "office-image" }, "Bild"],
    addNodeView() {
      return ({ node }) => {
        const dom = document.createElement("div"); dom.className = "office-image-node";
        dom.setAttribute("contenteditable", "false"); dom.textContent = "Bild wird geladen …";
        const controller = new AbortController(); let url = null, current = node, destroyed = false;
        fetchOfficeImage(node.attrs, context, controller.signal).then((value) => {
          if (destroyed) { URL.revokeObjectURL(value); return; }
          url = value; dom.replaceChildren(officeImageFigure(current.attrs, url));
        }).catch(() => { if (!destroyed) { dom.textContent = "Bild nicht verfügbar. Zugriff prüfen und Dokument neu laden."; dom.setAttribute("role", "alert"); } });
        return { dom,
          update(next) {
            if (next.type !== current.type || next.attrs.assetId !== current.attrs.assetId || next.attrs.versionId !== current.attrs.versionId ||
                next.attrs.manifestHash !== current.attrs.manifestHash) return false;
            current = next; if (url) dom.replaceChildren(officeImageFigure(next.attrs, url)); return true;
          },
          selectNode() { dom.classList.add("ProseMirror-selectednode"); },
          deselectNode() { dom.classList.remove("ProseMirror-selectednode"); },
          ignoreMutation: () => true,
          destroy() { destroyed = true; controller.abort(); if (url) URL.revokeObjectURL(url); },
        };
      };
    },
  });
}

export function installOfficeImageControls({ state, allowed, current, validate, focus, notice }) {
  const $ = (id) => document.getElementById(id);
  let action = null;
  const valid = () => action && current(action);
  const close = (restore = false) => {
    const previous = action; action = null; previous?.controller?.abort();
    if (previous?.url) URL.revokeObjectURL(previous.url);
    $("image-dialog").close(); $("image-form").reset(); $("image-preview").replaceChildren(); $("image-status").textContent = "";
    if (restore && previous?.editor === state.editor) focus();
  };
  const update = () => {
    if (action && !valid()) close();
    $("image-options").disabled = !allowed();
    $("image-options").textContent = state.editor?.state.selection.node?.type.name === "image" ? "Bild bearbeiten …" : "Bild einfügen …";
    $("image-upload").disabled = !valid() || action?.busy || !state.session?.objectId || !$("image-file").files.length;
    $("image-apply").disabled = !valid() || action?.busy || !action?.attrs;
    for (const id of ["image-remove", "image-up", "image-down"]) $(id).disabled = !valid() || action?.busy || !action?.selected;
    $("image-alt").disabled = $("image-decorative").checked;
    $("image-alt").required = !$("image-decorative").checked;
  };
  const fill = (attrs, uploaded = false) => {
    for (const name of ["width", "height", "align", "alt", "caption"]) $(`image-${name}`).value = attrs[name];
    $("image-lock").checked = attrs.lockAspect;
    $("image-decorative").checked = uploaded ? false : attrs.decorative;
    update();
  };
  const preview = async (owner) => {
    const url = await fetchOfficeImage(owner.attrs, owner.context, owner.controller.signal);
    if (action !== owner || !valid()) { URL.revokeObjectURL(url); return; }
    if (owner.url) URL.revokeObjectURL(owner.url); owner.url = url;
    $("image-preview").replaceChildren(officeImageFigure(owner.attrs, url));
  };
  const open = () => {
    if (!allowed()) return;
    close();
    const editor = state.editor, selected = editor.state.selection.node?.type.name === "image";
    action = { session: state.session, editor, context: state.context, revision: state.session.revision,
      document: editor.state.doc, selection: editor.state.selection, storedMarks: editor.state.storedMarks,
      selected, attrs: selected ? officeImageAttributes(editor.state.selection.node.attrs) : null,
      controller: new AbortController(), busy: false, url: null };
    $("image-title").textContent = selected ? "Bild bearbeiten" : "Bild einfügen";
    $("image-upload-section").hidden = selected;
    $("image-edit-actions").hidden = !selected;
    $("image-status").textContent = !state.session.objectId ? "Speichern Sie das neue Dokument zuerst. Danach können Sie ein Bild hochladen." :
      "PNG oder JPEG, bis 8 MiB und 4 Millionen Pixel. Das Bild wird diesem Dokument zugeordnet; Einfügen ändert zunächst Ihren Entwurf.";
    if (selected) { fill(action.attrs); preview(action).catch(() => { if (valid()) $("image-status").textContent = "Bildvorschau nicht verfügbar."; }); }
    update(); $("image-dialog").showModal();
  };
  const upload = async () => {
    if (!valid() || action.busy || !state.session.objectId) return;
    const owner = action, file = $("image-file").files[0];
    if (!file || !["image/png", "image/jpeg"].includes(file.type) || file.size > 8388608 || !file.size) {
      $("image-status").textContent = "Wählen Sie eine PNG- oder JPEG-Datei bis 8 MiB."; return;
    }
    owner.busy = true; update(); $("image-status").textContent = "Bild wird hochgeladen und geprüft …";
    try {
      const context = owner.context;
      const response = await fetch(`/v1/office/documents/${encodeURIComponent(owner.session.objectId)}/images`, {
        method: "POST", cache: "no-store", signal: owner.controller.signal, body: file,
        headers: { "Content-Type": file.type, "X-Office-Upload-Confirmed": "true", "X-Tenant-Id": context.tenantId,
          "X-User-Id": context.userId, "X-Role-Ids": context.roleIds, "X-Readable-Object-Ids": context.readableObjectIds },
      });
      if (!response.ok) throw new Error("upload");
      const result = await response.json();
      if (action !== owner || !valid()) return;
      owner.attrs = officeImageAttributes(result.image);
      if (owner.attrs.documentId !== owner.session.objectId) throw new Error("owner");
      await preview(owner);
      if (action !== owner || !valid()) return;
      fill(owner.attrs, true); $("image-status").textContent = "Bild bereit. Beschreiben Sie es mit Alternativtext oder kennzeichnen Sie es ausdrücklich als dekorativ.";
    } catch {
      if (action === owner && valid()) $("image-status").textContent = "Bild nicht verfügbar: Datei, Größenlimit und Zugriff prüfen. Bei einer unterbrochenen Übertragung kann das Bild bereits hinterlegt sein; der Entwurf wurde nicht geändert.";
    } finally { if (action === owner) { owner.busy = false; update(); } }
  };
  const change = (operation) => {
    if (!valid() || action.busy || !action.attrs) return;
    const owner = action, editor = owner.editor, selection = owner.selection;
    try {
      const tr = editor.state.tr;
      if (operation === "apply") {
        if (!$("image-form").reportValidity()) return;
        const attrs = officeImageAttributes({ ...owner.attrs,
          width: Number($("image-width").value), height: Number($("image-height").value), align: $("image-align").value,
          decorative: $("image-decorative").checked, alt: $("image-decorative").checked ? "" : $("image-alt").value,
          caption: $("image-caption").value, lockAspect: $("image-lock").checked,
        });
        if (owner.selected) tr.setNodeMarkup(selection.from, undefined, attrs);
        else tr.replaceSelectionWith(editor.schema.nodes.image.create(attrs));
      } else if (operation === "remove") tr.deleteSelection();
      else {
        const index = selection.$from.index(), parent = selection.$from.parent;
        const other = parent.maybeChild(index + (operation === "up" ? -1 : 1));
        if (!other) return;
        const start = operation === "up" ? selection.from - other.nodeSize : selection.from;
        const end = operation === "up" ? selection.to : selection.to + other.nodeSize;
        tr.replaceWith(start, end, operation === "up" ? [selection.node, other] : [other, selection.node]);
        tr.setSelection(NodeSelection.create(tr.doc, operation === "up" ? start : start + other.nodeSize));
      }
      validate(tr.doc);
      if (tr.doc.eq(editor.state.doc)) { close(true); return; }
      close(); editor.view.dispatch(closeHistory(tr).scrollIntoView()); editor.view.dispatch(closeHistory(editor.state.tr));
      focus(); notice("Bildänderung im Entwurf. Mit Rückgängig wiederherstellbar; gespeichert wird erst mit der nächsten bestätigten Version.");
    } catch { $("image-status").textContent = "Diese Bildänderung ist ungültig oder überschreitet die Dokumentgrenzen."; }
  };
  $("image-options").addEventListener("mousedown", (event) => event.preventDefault());
  $("image-options").addEventListener("click", open);
  $("image-file").addEventListener("change", update);
  $("image-upload").addEventListener("click", upload);
  $("image-decorative").addEventListener("change", update);
  for (const name of ["width", "height"]) $(`image-${name}`).addEventListener("input", () => {
    if (!action?.attrs || !$("image-lock").checked) return;
    const ratio = action.attrs.pixelWidth / action.attrs.pixelHeight;
    $(`image-${name === "width" ? "height" : "width"}`).value = String(Math.max(1, Math.round(Number($(`image-${name}`).value) * (name === "width" ? 1 / ratio : ratio))));
  });
  $("image-form").addEventListener("submit", (event) => { event.preventDefault(); change("apply"); });
  for (const name of ["remove", "up", "down"]) $(`image-${name}`).addEventListener("click", () => change(name));
  for (const id of ["image-close", "image-cancel"]) $(id).addEventListener("click", () => close(true));
  $("image-dialog").addEventListener("cancel", (event) => { event.preventDefault(); close(true); });
  return { update, close };
}
