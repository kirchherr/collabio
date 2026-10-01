import { Node } from "@tiptap/core";
import { NodeSelection } from "@tiptap/pm/state";
import { closeHistory } from "@tiptap/pm/history";
import { officeImageKeys, officeImageAttributes, officeImageFigure, fetchOfficeImage, applyOfficeImageLayout } from "./office-images.mjs";
import { installImageCropControls } from "./office-image-crop-controls.mjs";
import { officeFigureInventory } from "./office-figures.mjs";

function renderOfficeFigureNumbers(editor) {
  const labels = new Map(officeFigureInventory(editor.getJSON()).map(({ id, label }) => [id, label]));
  for (const figure of editor.view.dom.querySelectorAll("figure[data-office-figure]")) {
    const label = labels.get(figure.dataset.officeFigure), caption = figure.querySelector("figcaption");
    if (label && caption) caption.textContent = label;
  }
}

export function officeImageExtension(context, accessDenied) {
  return Node.create({
    name: "image", group: "block", atom: true, selectable: true, draggable: false,
    addAttributes: () => ({
      ...Object.fromEntries(officeImageKeys.filter((key) => key !== "figureId").map((key) => [key, { default: null, rendered: false }])),
      figureId: { default: null, rendered: false },
    }),
    parseHTML: () => [],
    renderHTML: () => ["figure", { class: "office-image" }, "Bild"],
    addNodeView() {
      return ({ node, editor, getPos }) => {
        const dom = document.createElement("div"); dom.className = "office-image-node";
        dom.setAttribute("contenteditable", "false"); dom.textContent = "Bild wird geladen …";
        applyOfficeImageLayout(dom, node.attrs);
        const controller = new AbortController(); let url = null, current = node, destroyed = false;
        const commitPosition = (position) => {
          if (destroyed || current.attrs.position == null || typeof getPos !== "function") return;
          const at = getPos();
          if (!Number.isInteger(at)) return;
          const attrs = officeImageAttributes({ ...current.attrs, position });
          const transaction = editor.state.tr.setNodeMarkup(at, undefined, attrs);
          editor.view.dispatch(closeHistory(transaction).scrollIntoView());
          editor.view.dispatch(closeHistory(editor.state.tr));
        };
        const positionAnchor = (anchor, figure) => {
          let drag = null;
          const paint = (position) => {
            const attrs = { ...current.attrs, position };
            applyOfficeImageLayout(dom, attrs); applyOfficeImageLayout(figure, attrs);
            anchor.setAttribute("aria-label", `${position.layer === "front" ? "Bildanker vor Text" : "Bildanker hinter Text"}; X ${position.x}; Y ${position.y} Pixel; ziehen oder mit Pfeiltasten verschieben`);
          };
          const finish = (event, cancel = false) => {
            if (!drag || (event.pointerId != null && drag.id !== event.pointerId)) return;
            if (anchor.hasPointerCapture(drag.id)) anchor.releasePointerCapture(drag.id);
            const next = drag.next, start = drag.start; drag = null;
            if (cancel) { paint(start); return; }
            if (next.x !== start.x || next.y !== start.y) commitPosition(next);
          };
          anchor.addEventListener("pointerdown", (event) => {
            if (event.button !== 0 || current.attrs.position == null) return;
            const bounds = editor.view.dom.getBoundingClientRect();
            drag = { id: event.pointerId, clientX: event.clientX, clientY: event.clientY,
              width: Math.max(1, bounds.width), start: { ...current.attrs.position }, next: { ...current.attrs.position } };
            anchor.setPointerCapture(event.pointerId); event.preventDefault();
          });
          anchor.addEventListener("pointermove", (event) => {
            if (!drag || drag.id !== event.pointerId) return;
            drag.next = { ...drag.start,
              x: Math.max(0, Math.min(1000, Math.round(drag.start.x + (event.clientX - drag.clientX) / drag.width * 1000))),
              y: Math.max(-1200, Math.min(1200, Math.round(drag.start.y + event.clientY - drag.clientY))) };
            paint(drag.next);
          });
          anchor.addEventListener("pointerup", (event) => finish(event));
          anchor.addEventListener("pointercancel", (event) => finish(event, true));
          anchor.addEventListener("keydown", (event) => {
            const direction = { ArrowLeft: [-1, 0], ArrowRight: [1, 0], ArrowUp: [0, -1], ArrowDown: [0, 1] }[event.key];
            if (!direction || event.ctrlKey || event.metaKey || event.altKey || current.attrs.position == null) return;
            event.preventDefault(); const step = event.shiftKey ? 10 : 1;
            commitPosition({ ...current.attrs.position,
              x: Math.max(0, Math.min(1000, current.attrs.position.x + direction[0] * step)),
              y: Math.max(-1200, Math.min(1200, current.attrs.position.y + direction[1] * step)) });
          });
          paint(current.attrs.position);
        };
        const render = () => {
          if (!url || destroyed) return;
          const target = current.attrs.figureId == null ? null : officeFigureInventory(editor.getJSON()).find(({ id }) => id === current.attrs.figureId);
          const figure = officeImageFigure(current.attrs, url, document, target?.number ?? null);
          if (current.attrs.position != null) {
            const anchor = document.createElement("button"); anchor.type = "button"; anchor.className = "office-image-anchor";
            anchor.textContent = current.attrs.position.layer === "front" ? "Bildanker · vor Text" : "Bildanker · hinter Text";
            anchor.addEventListener("click", () => {
              const position = typeof getPos === "function" ? getPos() : null;
              if (Number.isInteger(position)) editor.commands.setNodeSelection(position);
            });
            positionAnchor(anchor, figure);
            dom.replaceChildren(figure, anchor);
          } else dom.replaceChildren(figure);
        };
        fetchOfficeImage(node.attrs, context, controller.signal).then((value) => {
          if (destroyed) { URL.revokeObjectURL(value); return; }
          url = value; render(); renderOfficeFigureNumbers(editor);
        }).catch((error) => {
          if (destroyed) return;
          if ([401, 403, 404, 423].includes(error.status)) { accessDenied(); return; }
          dom.textContent = "Bild nicht verfügbar. Zugriff prüfen und Dokument neu laden."; dom.setAttribute("role", "alert");
        });
        return { dom,
          update(next) {
            if (next.type !== current.type || next.attrs.assetId !== current.attrs.assetId || next.attrs.versionId !== current.attrs.versionId ||
                next.attrs.manifestHash !== current.attrs.manifestHash) return false;
            current = next; applyOfficeImageLayout(dom, next.attrs);
            // ProseMirror updates node views before Editor.state is observable here.
            // Render on the next frame so order-derived numbering reads the committed document.
            requestAnimationFrame(() => { render(); renderOfficeFigureNumbers(editor); });
            return true;
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

export function installOfficeImageControls({ state, allowed, current, validate, focus, notice, accessDenied, reference }) {
  const $ = (id) => document.getElementById(id);
  let action = null;
  const valid = () => action && current(action);
  const cropControls = installImageCropControls(() => action, valid);
  const close = (restore = false) => {
    const previous = action; action = null; previous?.controller?.abort();
    if (previous?.url) URL.revokeObjectURL(previous.url);
    cropControls.close();
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
    $("image-caption").required = Boolean(action?.numbered);
    const positioned = $("image-position-layer").value !== "flow";
    $("image-wrap").disabled = positioned;
    $("image-wrap-gap").disabled = positioned || $("image-wrap").value === "none";
    for (const name of ["x", "y"]) $(`image-position-${name}`).disabled = !positioned;
  };
  const fill = (attrs, uploaded = false) => {
    for (const name of ["width", "height", "align", "alt", "caption"]) $(`image-${name}`).value = attrs[name];
    $("image-lock").checked = attrs.lockAspect;
    $("image-decorative").checked = uploaded ? false : attrs.decorative;
    action.numbered = attrs.figureId != null;
    $("image-numbered").checked = action.numbered;
    $("image-wrap").value = attrs.wrap?.side ?? "none";
    $("image-wrap-gap").value = attrs.wrap?.gap ?? 16;
    $("image-position-layer").value = attrs.position?.layer ?? "flow";
    $("image-position-x").value = attrs.position?.x ?? 0;
    $("image-position-y").value = attrs.position?.y ?? 0;
    cropControls.fill(action);
    update();
  };
  const preview = async (owner) => {
    const url = await fetchOfficeImage(owner.attrs, owner.context, owner.controller.signal);
    if (action !== owner || !valid()) { URL.revokeObjectURL(url); return; }
    if (owner.url) URL.revokeObjectURL(owner.url); owner.url = url;
    cropControls.source(owner);
  };
  const open = () => {
    if (!allowed()) return;
    close();
    const editor = state.editor, selected = editor.state.selection.node?.type.name === "image";
    action = { session: state.session, editor, context: state.context, revision: state.session.revision,
      document: editor.state.doc, selection: editor.state.selection, storedMarks: editor.state.storedMarks,
      selected, attrs: selected ? officeImageAttributes(editor.state.selection.node.attrs) : null,
      controller: new AbortController(), busy: false, url: null };
    const figures = officeFigureInventory(editor.getJSON());
    action.figureNumber = selected ? figures.find(({ id }) => id === action.attrs.figureId)?.number ?? figures.length + 1 : figures.length + 1;
    $("image-title").textContent = selected ? "Bild bearbeiten" : "Bild einfügen";
    $("image-upload-section").hidden = selected;
    $("image-edit-actions").hidden = !selected;
    $("image-status").textContent = !state.session.objectId ? "Speichern Sie das neue Dokument zuerst. Danach können Sie ein Bild hochladen." :
      "PNG oder JPEG, bis 8 MiB und 4 Millionen Pixel. Das Bild wird diesem Dokument zugeordnet; Einfügen ändert zunächst Ihren Entwurf.";
    if (selected) { const owner = action; fill(owner.attrs); preview(owner).catch((error) => {
      if (action !== owner || !valid()) return;
      if ([401, 403, 404, 423].includes(error.status)) { accessDenied(); return; }
      $("image-status").textContent = "Bildvorschau nicht verfügbar.";
    }); }
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
      if (!response.ok) {
        if (action === owner && valid() && [401, 403, 404, 423].includes(response.status)) { accessDenied(); return; }
        throw new Error("upload");
      }
      const result = await response.json();
      if (action !== owner || !valid()) return;
      owner.attrs = officeImageAttributes(result.image);
      delete owner.crop;
      if (owner.attrs.documentId !== owner.session.objectId) throw new Error("owner");
      await preview(owner);
      if (action !== owner || !valid()) return;
      fill(owner.attrs, true); $("image-status").textContent = "Bild bereit. Beschreiben Sie es mit Alternativtext oder kennzeichnen Sie es ausdrücklich als dekorativ.";
    } catch (error) {
      if (action === owner && valid() && [401, 403, 404, 423].includes(error.status)) { accessDenied(); return; }
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
        // Read the submitted control directly. The dialog can refresh its
        // preview between the checkbox change and submit; the form remains
        // the authoritative source for the user's current choice.
        const numbered = $("image-numbered").checked;
        const attrs = officeImageAttributes({ ...owner.attrs,
          width: Number($("image-width").value), height: Number($("image-height").value), align: $("image-align").value,
          decorative: $("image-decorative").checked, alt: $("image-decorative").checked ? "" : $("image-alt").value,
          caption: $("image-caption").value, lockAspect: $("image-lock").checked, crop: cropControls.value(),
          wrap: $("image-wrap").value === "none" ? null : { side: $("image-wrap").value, gap: $("image-wrap-gap").valueAsNumber },
          position: $("image-position-layer").value === "flow" ? null : { layer: $("image-position-layer").value,
            x: $("image-position-x").valueAsNumber, y: $("image-position-y").valueAsNumber },
          figureId: numbered ? owner.attrs.figureId || `figure-${reference().replaceAll("-", "").slice(0, 24)}` : null,
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
  $("image-numbered").addEventListener("change", () => {
    if (!valid()) return;
    action.numbered = $("image-numbered").checked; update(); cropControls.preview(action);
  });
  $("image-caption").addEventListener("input", () => { update(); if (valid()) cropControls.preview(action); });
  for (const id of ["image-wrap", "image-wrap-gap", "image-align"]) $(id).addEventListener("input", () => {
    if (!valid()) return;
    update(); cropControls.preview(action);
  });
  $("image-position-layer").addEventListener("input", () => {
    if (!valid()) return;
    if ($("image-position-layer").value !== "flow") $("image-wrap").value = "none";
    update(); cropControls.preview(action);
  });
  for (const name of ["x", "y"]) $(`image-position-${name}`).addEventListener("input", () => {
    if (!valid()) return;
    update(); cropControls.preview(action);
  });
  for (const name of ["width", "height"]) $(`image-${name}`).addEventListener("input", () => {
    if (!action?.attrs) return;
    if ($("image-lock").checked) {
      const ratio = action.crop.width / action.crop.height;
      $(`image-${name === "width" ? "height" : "width"}`).value = String(Math.max(1, Math.round(Number($(`image-${name}`).value) * (name === "width" ? 1 / ratio : ratio))));
    }
    cropControls.preview(action);
  });
  $("image-form").addEventListener("submit", (event) => { event.preventDefault(); change("apply"); });
  for (const name of ["remove", "up", "down"]) $(`image-${name}`).addEventListener("click", () => change(name));
  for (const id of ["image-close", "image-cancel"]) $(id).addEventListener("click", () => close(true));
  $("image-dialog").addEventListener("cancel", (event) => { event.preventDefault(); close(true); });
  return { update, close };
}
