import { Node } from "@tiptap/core";
import { NodeSelection } from "@tiptap/pm/state";
import { closeHistory } from "@tiptap/pm/history";
import { officeImageKeys, officeImageAttributes, officeImageFigure, fetchOfficeImage, applyOfficeImageLayout } from "./office-images.mjs";
import { OFFICE_IMAGE_GROUP_LIMIT, OFFICE_IMAGE_GROUP_MEMBER_LIMIT, officeImageGroupAttributes,
} from "./office-image-groups.mjs";
import { selectedOfficeImageContext } from "./office-image-group-extension.mjs";
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
  const groupCount = (doc) => { let count = 0; doc.forEach((node) => { if (node.type.name === "imageGroup") count += 1; }); return count; };
  const imageCount = (doc) => { let count = 0; doc.descendants((node) => { if (node.type.name === "image") count += 1; }); return count; };
  const groupCandidate = (owner, direction) => {
    const context = owner?.imageContext;
    if (!context || owner.attrs.wrap != null || owner.attrs.position != null) return null;
    const delta = direction === "previous" ? -1 : 1;
    const other = context.root.maybeChild(context.rootIndex + delta);
    if (!other) return null;
    if (context.grouped) return other.type.name === "image" && other.attrs.wrap == null && other.attrs.position == null &&
      context.group.childCount < OFFICE_IMAGE_GROUP_MEMBER_LIMIT ? other : null;
    if (other.type.name === "image") return other.attrs.wrap == null && other.attrs.position == null &&
      groupCount(owner.document) < OFFICE_IMAGE_GROUP_LIMIT ? other : null;
    return other.type.name === "imageGroup" && other.childCount < OFFICE_IMAGE_GROUP_MEMBER_LIMIT ? other : null;
  };
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
    $("image-options").textContent = ["image", "imageGroup"].includes(state.editor?.state.selection.node?.type.name) ? "Bild bearbeiten …" : "Bild einfügen …";
    $("image-upload").disabled = !valid() || action?.busy || !state.session?.objectId || !$("image-file").files.length;
    $("image-apply").disabled = !valid() || action?.busy || !action?.attrs;
    for (const id of ["image-remove", "image-up", "image-down"]) $(id).disabled = !valid() || action?.busy || !action?.selected;
    $("image-alt").disabled = $("image-decorative").checked;
    $("image-alt").required = !$("image-decorative").checked;
    $("image-caption").required = Boolean(action?.numbered);
    const grouped = Boolean(action?.imageContext?.grouped), positioned = $("image-position-layer").value !== "flow";
    $("image-duplicate").disabled = !valid() || action?.busy || !action?.selected || grouped || imageCount(action?.document) >= 40;
    $("image-position-layer").disabled = grouped;
    $("image-wrap").disabled = grouped || positioned;
    $("image-wrap-gap").disabled = grouped || positioned || $("image-wrap").value === "none";
    for (const name of ["x", "y"]) $(`image-position-${name}`).disabled = grouped || !positioned;
    $("image-group-previous").disabled = !valid() || action?.busy || !groupCandidate(action, "previous");
    $("image-group-next").disabled = !valid() || action?.busy || !groupCandidate(action, "next");
    $("image-group-duplicate").disabled = !valid() || action?.busy || !grouped ||
      groupCount(action?.document) >= OFFICE_IMAGE_GROUP_LIMIT || imageCount(action?.document) + (action?.imageContext?.group?.childCount ?? 0) > 40;
    $("image-group-ungroup").disabled = !valid() || action?.busy || !grouped;
    $("image-group-remove").disabled = !valid() || action?.busy || !grouped;
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
    $("image-rotation").value = String(attrs.transform?.rotation ?? 0);
    $("image-flip-x").checked = attrs.transform?.flipX ?? false;
    $("image-flip-y").checked = attrs.transform?.flipY ?? false;
    const group = action.imageContext?.group;
    $("image-group-layout").value = group?.attrs.layout ?? "row";
    $("image-group-gap").value = group?.attrs.gap ?? 16;
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
    const editor = state.editor, selection = editor.state.selection;
    const groupSelected = selection.node?.type.name === "imageGroup";
    const imageSelection = groupSelected ? NodeSelection.create(editor.state.doc, selection.from + 1) : selection;
    const selected = imageSelection.node?.type.name === "image";
    action = { session: state.session, editor, context: state.context, revision: state.session.revision,
      document: editor.state.doc, selection, imageSelection, storedMarks: editor.state.storedMarks,
      selected, attrs: selected ? officeImageAttributes(imageSelection.node.attrs) : null,
      controller: new AbortController(), busy: false, url: null };
    action.imageContext = selected ? selectedOfficeImageContext(editor, action.imageSelection) : null;
    const figures = officeFigureInventory(editor.getJSON());
    action.figureNumber = selected ? figures.find(({ id }) => id === action.attrs.figureId)?.number ?? figures.length + 1 : figures.length + 1;
    $("image-title").textContent = selected ? "Bild bearbeiten" : "Bild einfügen";
    $("image-upload-section").hidden = selected;
    $("image-edit-actions").hidden = !selected;
    $("image-group-section").hidden = !selected;
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
    const owner = action, editor = owner.editor, selection = owner.imageSelection, context = owner.imageContext;
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
          wrap: context?.grouped || $("image-wrap").value === "none" ? null : { side: $("image-wrap").value, gap: $("image-wrap-gap").valueAsNumber },
          position: context?.grouped || $("image-position-layer").value === "flow" ? null : { layer: $("image-position-layer").value,
            x: $("image-position-x").valueAsNumber, y: $("image-position-y").valueAsNumber },
          transform: Number($("image-rotation").value) || $("image-flip-x").checked || $("image-flip-y").checked ?
            { rotation: Number($("image-rotation").value), flipX: $("image-flip-x").checked, flipY: $("image-flip-y").checked } : null,
          figureId: numbered ? owner.attrs.figureId || `figure-${reference().replaceAll("-", "").slice(0, 24)}` : null,
        });
        if (owner.selected) {
          tr.setNodeMarkup(selection.from, undefined, attrs);
          if (context.grouped) tr.setNodeMarkup(context.groupPos, undefined, officeImageGroupAttributes({
            id: context.group.attrs.id, layout: $("image-group-layout").value, gap: $("image-group-gap").valueAsNumber,
          }));
        }
        else tr.replaceSelectionWith(editor.schema.nodes.image.create(attrs));
      } else if (operation === "remove" && context?.grouped) {
        const members = context.group.content.content;
        if (members.length === 2) {
          const remaining = members[context.imageIndex === 0 ? 1 : 0];
          tr.replaceWith(context.groupPos, context.groupPos + context.group.nodeSize, remaining);
          tr.setSelection(NodeSelection.create(tr.doc, context.groupPos));
        } else {
          tr.delete(context.imagePos, context.imagePos + context.image.nodeSize);
          tr.setSelection(NodeSelection.create(tr.doc, context.groupPos + 1));
        }
      } else if (operation === "remove") tr.deleteSelection();
      else if (operation === "ungroup" && context?.grouped) {
        const members = context.group.content.content;
        const selectedOffset = members.slice(0, context.imageIndex).reduce((total, node) => total + node.nodeSize, 0);
        tr.replaceWith(context.groupPos, context.groupPos + context.group.nodeSize, members);
        tr.setSelection(NodeSelection.create(tr.doc, context.groupPos + selectedOffset));
      }
      else {
        const entity = context?.grouped ? context.group : selection.node;
        const entityPos = context?.grouped ? context.groupPos : selection.from;
        const index = context?.grouped ? context.rootIndex : selection.$from.index(), parent = context?.root ?? selection.$from.parent;
        const other = parent.maybeChild(index + (operation === "up" ? -1 : 1));
        if (!other) return;
        const start = operation === "up" ? entityPos - other.nodeSize : entityPos;
        const end = operation === "up" ? entityPos + entity.nodeSize : entityPos + entity.nodeSize + other.nodeSize;
        tr.replaceWith(start, end, operation === "up" ? [entity, other] : [other, entity]);
        const entityStart = operation === "up" ? start : start + other.nodeSize;
        const memberOffset = context?.grouped ? 1 + context.group.content.content.slice(0, context.imageIndex)
          .reduce((total, node) => total + node.nodeSize, 0) : 0;
        tr.setSelection(NodeSelection.create(tr.doc, entityStart + memberOffset));
      }
      validate(tr.doc);
      if (tr.doc.eq(editor.state.doc)) { close(true); return; }
      close(); editor.view.dispatch(closeHistory(tr).scrollIntoView()); editor.view.dispatch(closeHistory(editor.state.tr));
      focus(); notice("Bildänderung im Entwurf. Mit Rückgängig wiederherstellbar; gespeichert wird erst mit der nächsten bestätigten Version.");
    } catch { $("image-status").textContent = "Diese Bildänderung ist ungültig oder überschreitet die Dokumentgrenzen."; }
  };
  const group = (direction) => {
    if (!valid() || action.busy || !action.attrs || !groupCandidate(action, direction)) return;
    const owner = action, editor = owner.editor, context = owner.imageContext, delta = direction === "previous" ? -1 : 1;
    const other = context.root.child(context.rootIndex + delta);
    try {
      const tr = editor.state.tr;
      if (context.grouped) {
        const otherPos = direction === "previous" ? context.groupPos - other.nodeSize : context.groupPos + context.group.nodeSize;
        const members = direction === "previous" ? [other, ...context.group.content.content] : [...context.group.content.content, other];
        const start = Math.min(context.groupPos, otherPos), end = Math.max(context.groupPos + context.group.nodeSize, otherPos + other.nodeSize);
        tr.replaceWith(start, end, editor.schema.nodes.imageGroup.create(context.group.attrs, members));
        const selectedIndex = context.imageIndex + (direction === "previous" ? 1 : 0);
        const offset = 1 + members.slice(0, selectedIndex).reduce((total, node) => total + node.nodeSize, 0);
        tr.setSelection(NodeSelection.create(tr.doc, start + offset));
      } else {
        const otherPos = direction === "previous" ? context.imagePos - other.nodeSize : context.imagePos + context.image.nodeSize;
        const start = Math.min(context.imagePos, otherPos), end = Math.max(context.imagePos + context.image.nodeSize, otherPos + other.nodeSize);
        let attrs, members, selectedIndex;
        if (other.type.name === "imageGroup") {
          attrs = other.attrs;
          members = direction === "previous" ? [...other.content.content, context.image] : [context.image, ...other.content.content];
          selectedIndex = direction === "previous" ? members.length - 1 : 0;
        } else {
          attrs = { id: `image-group-${reference().replaceAll("-", "").slice(0, 24)}`, layout: $("image-group-layout").value,
            gap: $("image-group-gap").valueAsNumber };
          members = direction === "previous" ? [other, context.image] : [context.image, other];
          selectedIndex = direction === "previous" ? 1 : 0;
        }
        const groupNode = editor.schema.nodes.imageGroup.create(officeImageGroupAttributes(attrs), members);
        tr.replaceWith(start, end, groupNode);
        const offset = 1 + members.slice(0, selectedIndex).reduce((total, node) => total + node.nodeSize, 0);
        tr.setSelection(NodeSelection.create(tr.doc, start + offset));
      }
      validate(tr.doc); close(); editor.view.dispatch(closeHistory(tr).scrollIntoView()); editor.view.dispatch(closeHistory(editor.state.tr));
      focus(); notice("Bildgruppe im Entwurf geändert. Mit Rückgängig wiederherstellbar; gespeichert wird erst mit der nächsten bestätigten Version.");
    } catch { $("image-status").textContent = "Diese Bildgruppe ist ungültig oder überschreitet die Dokumentgrenzen."; }
  };
  const duplicateGroup = async () => {
    if (!valid() || action.busy || !action.imageContext?.grouped || !state.session.objectId) return;
    const owner = action, source = owner.imageContext.group;
    if (groupCount(owner.document) >= OFFICE_IMAGE_GROUP_LIMIT || imageCount(owner.document) + source.childCount > 40) {
      $("image-status").textContent = "Die Dokumentgrenze für Bildgruppen oder Bilder ist erreicht."; return;
    }
    owner.busy = true; update(); $("image-status").textContent = "Bildgruppe wird mit unabhängigen Bilddateien dupliziert …";
    try {
      const response = await fetch(`/v1/office/documents/${encodeURIComponent(owner.session.objectId)}/image-groups/duplicate`, {
        method: "POST", cache: "no-store", signal: owner.controller.signal,
        headers: { "Content-Type": "application/json", "X-Tenant-Id": owner.context.tenantId,
          "X-User-Id": owner.context.userId, "X-Role-Ids": owner.context.roleIds,
          "X-Readable-Object-Ids": owner.context.readableObjectIds },
        body: JSON.stringify({ images: source.content.content.map((node) => officeImageAttributes(node.attrs)) }),
      });
      if (!response.ok) {
        if ([401, 403, 404, 423].includes(response.status)) { accessDenied(); return; }
        throw new Error("duplicate-group");
      }
      const payload = await response.json();
      if (!valid() || action !== owner || !Array.isArray(payload.images) || payload.images.length !== source.childCount) return;
      const editor = owner.editor, groupId = source.attrs.id;
      let currentGroup = null, groupPos = null;
      editor.state.doc.forEach((node, offset) => {
        if (currentGroup == null && node.type.name === "imageGroup" && node.attrs.id === groupId) { currentGroup = node; groupPos = offset; }
      });
      if (!currentGroup || !Number.isInteger(groupPos) || currentGroup.childCount !== payload.images.length) throw new Error("stale-group");
      const members = payload.images.map((attrs) => {
        const checked = officeImageAttributes(attrs);
        return editor.schema.nodes.image.create({ ...checked,
          figureId: checked.figureId == null ? null : `figure-${reference().replaceAll("-", "").slice(0, 24)}` });
      });
      const copied = editor.schema.nodes.imageGroup.create(officeImageGroupAttributes({ ...currentGroup.attrs,
        id: `image-group-${reference().replaceAll("-", "").slice(0, 24)}` }), members);
      const insertAt = groupPos + currentGroup.nodeSize, tr = editor.state.tr.insert(insertAt, copied);
      tr.setSelection(NodeSelection.create(tr.doc, insertAt + 1)); validate(tr.doc);
      close(); editor.view.dispatch(closeHistory(tr).scrollIntoView()); editor.view.dispatch(closeHistory(editor.state.tr));
      focus(); notice("Bildgruppe mit unabhängigen Bilddateien dupliziert. Mit Rückgängig entfernbar; gespeichert wird erst mit der nächsten bestätigten Version.");
    } catch (error) {
      if (action === owner && valid() && [401, 403, 404, 423].includes(error.status)) { accessDenied(); return; }
      if (action === owner && valid()) $("image-status").textContent = "Die Bildgruppe konnte nicht vollständig dupliziert werden. Der Entwurf wurde nicht geändert.";
    } finally { if (action === owner) { owner.busy = false; update(); } }
  };
  const duplicateImage = async () => {
    if (!valid() || action.busy || !action.selected || action.imageContext?.grouped || !state.session.objectId) return;
    const owner = action, source = owner.attrs, sourcePos = owner.imageSelection.from;
    if (imageCount(owner.document) >= 40) {
      $("image-status").textContent = "Die Dokumentgrenze für Bilder ist erreicht."; return;
    }
    owner.busy = true; update(); $("image-status").textContent = "Bild wird mit einer unabhängigen Bilddatei dupliziert …";
    try {
      const response = await fetch(`/v1/office/documents/${encodeURIComponent(owner.session.objectId)}/images/duplicate`, {
        method: "POST", cache: "no-store", signal: owner.controller.signal,
        headers: { "Content-Type": "application/json", "X-Tenant-Id": owner.context.tenantId,
          "X-User-Id": owner.context.userId, "X-Role-Ids": owner.context.roleIds,
          "X-Readable-Object-Ids": owner.context.readableObjectIds },
        body: JSON.stringify({ image: source }),
      });
      if (!response.ok) {
        if ([401, 403, 404, 423].includes(response.status)) { accessDenied(); return; }
        throw new Error("duplicate-image");
      }
      const payload = await response.json();
      if (!valid() || action !== owner || payload.image == null) return;
      const editor = owner.editor, current = editor.state.doc.nodeAt(sourcePos);
      if (current?.type.name !== "image" || current.attrs.assetId !== source.assetId ||
          current.attrs.versionId !== source.versionId) throw new Error("stale-image");
      const checked = officeImageAttributes(payload.image);
      if (checked.documentId !== source.documentId || checked.assetId === source.assetId ||
          checked.versionId === source.versionId || checked.contentHash !== source.contentHash ||
          checked.pixelWidth !== source.pixelWidth || checked.pixelHeight !== source.pixelHeight) throw new Error("invalid-copy");
      const position = checked.position == null ? null : { ...checked.position,
        x: checked.position.x <= 960 ? checked.position.x + 40 : checked.position.x - 40,
        y: checked.position.y <= 1176 ? checked.position.y + 24 : checked.position.y - 24 };
      const attrs = officeImageAttributes({ ...checked, position,
        figureId: checked.figureId == null ? null : `figure-${reference().replaceAll("-", "").slice(0, 24)}` });
      const copied = editor.schema.nodes.image.create(attrs), insertAt = sourcePos + current.nodeSize;
      const tr = editor.state.tr.insert(insertAt, copied);
      tr.setSelection(NodeSelection.create(tr.doc, insertAt)); validate(tr.doc);
      close(); editor.view.dispatch(closeHistory(tr).scrollIntoView()); editor.view.dispatch(closeHistory(editor.state.tr));
      focus(); notice("Bild mit unabhängiger Bilddatei dupliziert. Mit Rückgängig entfernbar; gespeichert wird erst mit der nächsten bestätigten Version.");
    } catch (error) {
      if (action === owner && valid() && [401, 403, 404, 423].includes(error.status)) { accessDenied(); return; }
      if (action === owner && valid()) $("image-status").textContent = "Das Bild konnte nicht vollständig dupliziert werden. Der Entwurf wurde nicht geändert.";
    } finally { if (action === owner) { owner.busy = false; update(); } }
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
  for (const id of ["image-rotation", "image-flip-x", "image-flip-y"]) $(id).addEventListener("input", () => {
    if (valid()) cropControls.preview(action);
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
  for (const direction of ["previous", "next"]) $(`image-group-${direction}`).addEventListener("click", () => group(direction));
  $("image-group-duplicate").addEventListener("click", duplicateGroup);
  $("image-duplicate").addEventListener("click", duplicateImage);
  $("image-group-ungroup").addEventListener("click", () => change("ungroup"));
  $("image-group-remove").addEventListener("click", () => {
    if (!valid() || action.busy || !action.imageContext?.grouped) {
      $("image-status").textContent = "Bitte die Bildgruppe erneut auswählen."; return;
    }
    if (!allowed() || !state.editor) { $("image-status").textContent = "Die Bildgruppe ist derzeit schreibgeschützt."; return; }
    const editor = state.editor, groupId = action.imageContext.group.attrs.id;
    let group = null, groupPos = null;
    editor.state.doc.forEach((node, offset) => {
      if (group == null && node.type.name === "imageGroup" && node.attrs.id === groupId) { group = node; groupPos = offset; }
    });
    if (!group || !Number.isInteger(groupPos)) { $("image-status").textContent = "Die Bildgruppe wurde im aktuellen Entwurf nicht gefunden."; return; }
    const tr = editor.state.tr.delete(groupPos, groupPos + group.nodeSize);
    try {
      validate(tr.doc); close(); editor.view.dispatch(closeHistory(tr).scrollIntoView()); editor.view.dispatch(closeHistory(editor.state.tr));
      focus(); notice("Bildgruppe aus dem Entwurf entfernt. Mit Rückgängig vollständig wiederherstellbar; gespeichert wird erst mit der nächsten bestätigten Version.");
    } catch { $("image-status").textContent = "Die Bildgruppe konnte nicht entfernt werden."; }
  });
  for (const id of ["image-close", "image-cancel"]) $(id).addEventListener("click", () => close(true));
  $("image-dialog").addEventListener("cancel", (event) => { event.preventDefault(); close(true); });
  return { update, close };
}
