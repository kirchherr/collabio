import { NodeSelection } from "@tiptap/pm/state";
import { closeHistory } from "@tiptap/pm/history";
import { OFFICE_SHAPE_LIMIT, applyOfficeShapeDOM, applyOfficeShapeLayoutDOM,
  officeShapeAttributes } from "./office-shapes.mjs";
import { OFFICE_SHAPE_GROUP_LIMIT, officeShapeGroupAttributes,
  officeShapeGroupLayout } from "./office-shape-groups.mjs";
import { OFFICE_SHAPE_MULTI_SELECTION_LIMIT, officeShapeMultiCanGroup, officeShapeMultiRange,
  officeShapeMultiAlignment, officeShapeMultiAppearance, officeShapeMultiAppearanceSample,
  officeShapeMultiCanArrange, officeShapeMultiCanCopyAppearance, officeShapeMultiCanOrder, officeShapeMultiCanStyle,
  officeShapeMultiCanRegroup, officeShapeMultiCanUngroup,
  officeShapeMultiDistribution,
  officeShapeMultiLayer, officeShapeMultiMoveTo, officeShapeMultiNudge, officeShapeMultiOrder,
  officeShapeMultiObjectState, officeShapeMultiUnlocked,
  officeShapeMultiResize, officeShapeMultiRotate,
  officeShapeMultiPasteAppearance, officeShapeMultiRootRotation, officeShapeMultiRootSize,
  officeShapeMultiRegroup, officeShapeMultiSelection, officeShapeMultiSelectionPlan,
  officeShapeMultiTransform, officeShapeMultiTranslate,
  officeShapeMultiUngroup,
  OFFICE_SHAPE_MULTI_SCALE_BASE } from "./office-shape-multi-selection.mjs";

function freshId(prefix) {
  const bytes = new Uint8Array(12); crypto.getRandomValues(bytes);
  return `${prefix}-${Array.from(bytes, (byte) => byte.toString(16).padStart(2, "0")).join("")}`;
}

function offsetPosition(position) {
  return position == null ? null : { layer: position.layer,
    x: position.x <= 975 ? position.x + 25 : position.x - 25,
    y: position.y <= 1176 ? position.y + 24 : position.y - 24 };
}

function rootEntries(doc) {
  const entries = [];
  doc.forEach((node, pos, rootIndex) => {
    if (!["shape", "shapeGroup"].includes(node.type.name)) return;
    entries.push({ id: node.attrs.id, type: node.type.name, node, pos, rootIndex });
  });
  return entries;
}

function shapeCount(doc) {
  let total = 0; doc.descendants((node) => { if (node.type.name === "shape") total += 1; }); return total;
}

function groupCount(doc) {
  let total = 0; doc.forEach((node) => { if (node.type.name === "shapeGroup") total += 1; }); return total;
}

export function installOfficeShapeMultiSelection({ state, allowed, validate, focus, updateEditor, notice }) {
  const $ = (id) => document.getElementById(id), selectedIds = new Set();
  let mode = false, anchorId = null, session = null, bound = null, drag = null, resizeDrag = null, rotateDrag = null,
    suppressedClick = null, selectionSnapshot = null, orderSnapshot = null, transformSnapshot = null,
    appearanceSnapshot = null, appearanceClipboard = null,
    regroupMemory = null;
  const entries = () => state.editor ? rootEntries(state.editor.state.doc) : [];
  const selectedEntries = () => officeShapeMultiSelection(entries(), [...selectedIds]);
  const paint = () => {
    const editor = state.editor;
    if (editor) editor.view.dom.querySelectorAll("[data-office-multi-selected]").forEach((element) => {
      element.removeAttribute("data-office-multi-selected"); element.removeAttribute("aria-selected");
    });
    if (editor) editor.view.dom.querySelectorAll("[data-office-multi-anchor-label]").forEach((element) => {
      element.setAttribute("aria-label", element.dataset.officeMultiAnchorLabel);
      delete element.dataset.officeMultiAnchorLabel;
    });
    if (editor) editor.view.dom.querySelectorAll("[data-office-multi-resize-label]").forEach((element) => {
      element.setAttribute("aria-label", element.dataset.officeMultiResizeLabel);
      delete element.dataset.officeMultiResizeLabel;
    });
    if (editor) editor.view.dom.querySelectorAll("[data-office-multi-rotate-label]").forEach((element) => {
      element.setAttribute("aria-label", element.dataset.officeMultiRotateLabel);
      delete element.dataset.officeMultiRotateLabel;
    });
    for (const entry of selectedEntries()) {
      const selector = entry.type === "shapeGroup" ? `.office-shape-group[data-shape-group="${entry.id}"]` :
        `.office-shape-node:has(>.office-shape[data-office-shape="${entry.id}"])`;
      const element = editor?.view.dom.querySelector(selector);
      if (element) {
        element.toggleAttribute("data-office-multi-selected", true); element.setAttribute("aria-selected", "true");
        const handle = element.querySelector(":scope > .office-shape-anchor, :scope > .office-shape-group-anchor");
        if (handle && selectedIds.size >= 2) {
          handle.dataset.officeMultiAnchorLabel = handle.getAttribute("aria-label") || "Objektanker";
          handle.setAttribute("aria-label", `${selectedIds.size} ausgewählte Objekte gemeinsam ziehen; Maus oder Touch`);
        }
        const resize = element.querySelector(":scope > .office-shape-resize, :scope > .office-shape-group-resize");
        if (resize && selectedIds.size >= 2 && entry.node.attrs.position != null) {
          resize.dataset.officeMultiResizeLabel = resize.getAttribute("aria-label") || "Objektgröße ändern";
          resize.setAttribute("aria-label", `${selectedIds.size} ausgewählte Objekte gemeinsam skalieren; Maus, Touch oder Pfeiltasten; Umschalt beim Ziehen behält das Seitenverhältnis bei`);
        }
        const rotate = element.querySelector(":scope > .office-shape-rotate, :scope > .office-shape-group-rotate");
        if (rotate && selectedIds.size >= 2 && entry.node.attrs.position != null) {
          rotate.dataset.officeMultiRotateLabel = rotate.getAttribute("aria-label") || "Objekt drehen";
          rotate.setAttribute("aria-label", `${selectedIds.size} ausgewählte Objekte gemeinsam drehen; Maus, Touch oder Pfeiltasten; Umschalt rastet auf 15 Grad`);
        }
      }
    }
    const count = selectedIds.size;
    $("shape-multi-toggle").setAttribute("aria-pressed", String(mode));
    $("shape-multi-status").textContent = count === 0 ? "Keine Objekte ausgewählt" :
      count === 1 ? "1 Objekt ausgewählt" : `${count} Objekte ausgewählt`;
    const actions = $("shape-multi-actions"); actions.hidden = count === 0;
    const current = selectedEntries(), writable = allowed(), enough = current.length >= 2, doc = state.editor?.state.doc;
    const editable = current.length > 0 && officeShapeMultiUnlocked(current);
    $("shape-multi-navigator").disabled = !doc || !writable || entries().length === 0;
    const rememberedGroups = regroupMemory?.session === state.session;
    $("shape-multi-regroup").hidden = !rememberedGroups;
    $("shape-multi-regroup").disabled = !doc || !writable || !rememberedGroups ||
      !officeShapeMultiCanRegroup(entries(), regroupMemory);
    const duplicateShapes = current.reduce((total, entry) => total + (entry.type === "shape" ? 1 : entry.node.childCount), 0);
    const duplicateGroups = current.filter((entry) => entry.type === "shapeGroup").length;
    $("shape-multi-duplicate").disabled = !doc || !writable || !editable || !enough || shapeCount(doc) + duplicateShapes > OFFICE_SHAPE_LIMIT ||
      groupCount(doc) + duplicateGroups > OFFICE_SHAPE_GROUP_LIMIT;
    $("shape-multi-remove").disabled = !writable || !editable || !enough;
    $("shape-multi-ungroup").disabled = !writable || !officeShapeMultiCanUngroup(current);
    for (const button of document.querySelectorAll("[data-shape-multi-order]")) {
      button.disabled = !doc || !writable || !editable ||
        !officeShapeMultiCanOrder(doc.childCount, current, button.dataset.shapeMultiOrder);
    }
    $("shape-multi-move-to").disabled = !doc || !writable || !editable || !enough || current.length >= doc.childCount;
    $("shape-multi-group").disabled = !doc || !writable || !officeShapeMultiCanGroup(current) || groupCount(doc) >= OFFICE_SHAPE_GROUP_LIMIT;
    $("shape-multi-align").disabled = !writable || !officeShapeMultiCanArrange(current);
    $("shape-multi-distribute").disabled = !writable || !officeShapeMultiCanArrange(current, 3);
    $("shape-multi-layer").disabled = !writable || !officeShapeMultiCanArrange(current);
    $("shape-multi-transform").disabled = !writable || !officeShapeMultiCanArrange(current);
    $("shape-multi-appearance").disabled = !writable || !officeShapeMultiCanStyle(current);
    const copiedHere = appearanceClipboard?.session === state.session;
    $("shape-multi-copy-appearance").disabled = !writable || !officeShapeMultiCanCopyAppearance(current);
    $("shape-multi-paste-appearance").disabled = !writable || !copiedHere || !officeShapeMultiCanStyle(current);
    $("shape-multi-style-status").textContent = copiedHere ? "Darstellung gemerkt" : "Keine Darstellung gemerkt";
    const hiddenCount = current.filter((entry) => entry.node.attrs.hidden === true).length;
    const lockedCount = current.filter((entry) => entry.node.attrs.locked === true).length;
    $("shape-multi-show").disabled = !doc || !writable || hiddenCount === 0;
    $("shape-multi-hide").disabled = !doc || !writable || current.length === 0 || hiddenCount === current.length;
    $("shape-multi-lock").disabled = !doc || !writable || current.length === 0 || lockedCount === current.length;
    $("shape-multi-unlock").disabled = !doc || !writable || lockedCount === 0;
    const positions = current.map((entry) => entry.node?.attrs.position).filter(Boolean);
    const movable = writable && officeShapeMultiCanArrange(current);
    $("shape-multi-nudge-left").disabled = !movable || positions.some((position) => position.x <= 0);
    $("shape-multi-nudge-right").disabled = !movable || positions.some((position) => position.x >= 1000);
    $("shape-multi-nudge-up").disabled = !movable || positions.some((position) => position.y <= -1200);
    $("shape-multi-nudge-down").disabled = !movable || positions.some((position) => position.y >= 1200);
    $("shape-multi-clear").disabled = count === 0;
  };
  const setSelection = (ids, nextAnchor = null) => {
    selectedIds.clear();
    for (const id of ids.slice(0, OFFICE_SHAPE_MULTI_SELECTION_LIMIT)) selectedIds.add(id);
    anchorId = nextAnchor ?? ids.at(-1) ?? null; paint();
  };
  const clear = () => setSelection([]);
  const targetId = (target) => {
    const group = target.closest?.(".office-shape-group[data-shape-group]");
    if (group && state.editor?.view.dom.contains(group)) return group.dataset.shapeGroup;
    const node = target.closest?.(".office-shape-node"), shape = node?.querySelector(":scope > .office-shape[data-office-shape]");
    return node?.parentElement === state.editor?.view.dom ? shape?.dataset.officeShape ?? null : null;
  };
  const rootElement = (entry) => entry.type === "shapeGroup" ?
    state.editor?.view.dom.querySelector(`.office-shape-group[data-shape-group="${entry.id}"]`) :
    state.editor?.view.dom.querySelector(`.office-shape-node:has(>.office-shape[data-office-shape="${entry.id}"])`);
  const positionedUngroupPlacements = (current) => {
    if (!current.length || current[0].node.attrs.position == null) return null;
    const placements = []; let expansionBefore = 0;
    for (const entry of current) {
      const root = rootElement(entry), memberRoots = root?.querySelectorAll(
        ":scope > .office-shape-group-content > .office-shape-node");
      if (!root || memberRoots?.length !== entry.node.childCount) throw new Error("shape-multi-ungroup-layout");
      const rootRect = root.getBoundingClientRect();
      if (!Number.isFinite(rootRect.width) || rootRect.width <= 0) throw new Error("shape-multi-ungroup-layout");
      for (const [index, memberRoot] of Array.from(memberRoots).entries()) {
        const member = entry.node.child(index), shape = memberRoot.querySelector(":scope > .office-shape");
        if (!shape || shape.dataset.officeShape !== member.attrs.id) throw new Error("shape-multi-ungroup-layout");
        const box = shape.getBoundingClientRect(), style = shape.ownerDocument.defaultView.getComputedStyle(shape);
        const width = Number.parseFloat(style.width), height = Number.parseFloat(style.height);
        if (![box.left, box.top, box.width, box.height, width, height].every(Number.isFinite) || width <= 0 ||
            height <= 0 || width > rootRect.width + 1) throw new Error("shape-multi-ungroup-layout");
        const futureWidth = Math.min(rootRect.width, member.attrs.width);
        const futureHeight = member.attrs.height * futureWidth / member.attrs.width;
        const available = rootRect.width - futureWidth;
        const rawX = available <= 0.5 ? 0 :
          (box.left + box.width / 2 - rootRect.left - futureWidth / 2) / available * 1000;
        const rawY = box.top + box.height / 2 - rootRect.top - futureHeight / 2 - expansionBefore - index;
        const x = Math.max(0, Math.min(1000, Math.round(rawX)));
        const y = Math.max(-1200, Math.min(1200, Math.round(rawY)));
        const targetCenterX = box.left + box.width / 2;
        const positionedCenterX = rootRect.left + futureWidth / 2 + available * x / 1000;
        if (Math.abs(targetCenterX - positionedCenterX) > 4 || Math.abs(rawY - y) > 0.5) {
          throw new Error("shape-multi-ungroup-layout");
        }
        placements.push({ id: member.attrs.id, position: { layer: entry.node.attrs.position.layer,
          x, y } });
      }
      expansionBefore += entry.node.childCount - 1;
    }
    return placements;
  };
  const previewPosition = (entry, position, dragging = true) => {
    const root = rootElement(entry); if (!root) return;
    root.toggleAttribute("data-office-multi-dragging", dragging);
    if (entry.type === "shapeGroup") {
      root.style.setProperty("--shape-group-position-x", `${position.x / 10}%`);
      root.style.setProperty("--shape-group-position-shift", `${-position.x / 10}%`);
      root.style.setProperty("--shape-group-position-y", `${position.y}px`);
      return;
    }
    const targets = root.querySelectorAll(":scope > .office-shape, :scope > .office-shape-anchor, :scope > .office-shape-resize, :scope > .office-shape-rotate");
    for (const element of targets) {
      element.style.setProperty("--office-shape-position-x", `${position.x / 10}%`);
      element.style.setProperty("--office-shape-position-shift", `${-position.x / 10}%`);
      element.style.setProperty("--office-shape-position-y", `${position.y}px`);
    }
  };
  const restorePreview = (entriesToRestore) => {
    for (const entry of entriesToRestore) previewPosition(entry, entry.node.attrs.position, false);
  };
  const originalShapeChange = (entry) => entry.type === "shape" ?
    { id: entry.id, type: entry.type, attrs: officeShapeAttributes(entry.node.attrs) } :
    { id: entry.id, type: entry.type, attrs: officeShapeGroupAttributes(entry.node.attrs),
      members: entry.node.content.content.map((member) => officeShapeAttributes(member.attrs)) };
  const previewShapeChange = (entry, change, marker, active = true) => {
    const root = rootElement(entry); if (!root) return;
    root.toggleAttribute(marker, active);
    if (entry.type === "shape") {
      const shape = root.querySelector(":scope > .office-shape");
      if (shape) applyOfficeShapeDOM(shape, change.attrs);
      applyOfficeShapeLayoutDOM(root, change.attrs); return;
    }
    const memberRoots = root.querySelectorAll(":scope > .office-shape-group-content > .office-shape-node");
    for (const [index, memberRoot] of Array.from(memberRoots).entries()) {
      const attrs = change.members[index], shape = memberRoot.querySelector(":scope > .office-shape");
      if (!attrs || !shape) continue;
      applyOfficeShapeDOM(shape, attrs); applyOfficeShapeLayoutDOM(memberRoot, attrs);
    }
    const layout = officeShapeGroupLayout(change.attrs, change.members);
    root.style.setProperty("--shape-group-gap", `${layout.gap}px`);
    root.style.setProperty("--shape-group-bound-width", String(layout.width));
    const position = change.attrs.position;
    if (position) {
      root.dataset.shapeGroupPosition = position.layer;
      root.style.setProperty("--shape-group-position-x", `${position.x / 10}%`);
      root.style.setProperty("--shape-group-position-shift", `${-position.x / 10}%`);
      root.style.setProperty("--shape-group-position-y", `${position.y}px`);
    } else {
      delete root.dataset.shapeGroupPosition;
      root.style.removeProperty("--shape-group-position-x");
      root.style.removeProperty("--shape-group-position-shift");
      root.style.removeProperty("--shape-group-position-y");
    }
  };
  const previewResize = (entry, change, resizing = true) =>
    previewShapeChange(entry, change, "data-office-multi-resizing", resizing);
  const previewRotate = (entry, change, rotating = true) =>
    previewShapeChange(entry, change, "data-office-multi-rotating", rotating);
  const restoreResizePreview = (entriesToRestore) => {
    for (const entry of entriesToRestore) previewResize(entry, originalShapeChange(entry), false);
  };
  const restoreRotatePreview = (entriesToRestore) => {
    for (const entry of entriesToRestore) previewRotate(entry, originalShapeChange(entry), false);
  };
  const sameDragSource = (active) => {
    const current = selectedEntries();
    return active.session === state.session && active.doc === state.editor?.state.doc && allowed() &&
      current.length === active.entries.length && current.every((entry, index) => entry.id === active.entries[index].id &&
        entry.node.attrs.position.x === active.entries[index].node.attrs.position.x &&
        entry.node.attrs.position.y === active.entries[index].node.attrs.position.y &&
        entry.node.attrs.position.layer === active.entries[index].node.attrs.position.layer);
  };
  const finishDrag = (event, cancel = false) => {
    if (!drag || (event?.pointerId != null && drag.pointerId !== event.pointerId)) return;
    const active = drag; drag = null;
    try { if (bound?.hasPointerCapture?.(active.pointerId)) bound.releasePointerCapture(active.pointerId); } catch { /* capture may be synthetic */ }
    event?.preventDefault?.(); event?.stopImmediatePropagation?.();
    suppressedClick = { id: active.sourceId, until: performance.now() + 500 };
    const changed = active.changes.some((change, index) => change.position.x !== active.entries[index].node.attrs.position.x ||
      change.position.y !== active.entries[index].node.attrs.position.y);
    if (cancel || !changed || !sameDragSource(active)) {
      restorePreview(active.entries); paint();
      if (!cancel && changed) notice("Die gemeinsame Bewegung wurde wegen eines geänderten Dokumentzustands verworfen.", true);
      return;
    }
    for (const entry of active.entries) rootElement(entry)?.removeAttribute("data-office-multi-dragging");
    const dx = active.changes[0].position.x - active.entries[0].node.attrs.position.x;
    const dy = active.changes[0].position.y - active.entries[0].node.attrs.position.y;
    commitArrangement(active.changes,
      `${active.entries.length} positionierte Objekte atomar um X ${dx} und Y ${dy} gezogen. Rückgängig ist möglich.`);
  };
  const cancelDrag = (event) => finishDrag(event, true);
  const startDrag = (event) => {
    const handle = event.target.closest?.(".office-shape-anchor, .office-shape-group-anchor");
    const sourceId = targetId(event.target), current = selectedEntries();
    if (!handle || !sourceId || !selectedIds.has(sourceId) || event.button !== 0 || event.isPrimary === false ||
        event.ctrlKey || event.metaKey || event.altKey || drag || !allowed() || document.querySelector("dialog[open]") ||
        !officeShapeMultiCanArrange(current)) return;
    const bounds = state.editor.view.dom.getBoundingClientRect();
    drag = { pointerId: event.pointerId, sourceId, clientX: event.clientX, clientY: event.clientY,
      width: Math.max(1, bounds.width), entries: current, changes: current.map((entry) => ({ id: entry.id,
        position: entry.node.attrs.position })), session: state.session, doc: state.editor.state.doc };
    for (const entry of current) rootElement(entry)?.toggleAttribute("data-office-multi-dragging", true);
    try { bound?.setPointerCapture?.(event.pointerId); } catch { /* synthetic pointer events cannot capture */ }
    event.preventDefault(); event.stopImmediatePropagation();
  };
  const moveDrag = (event) => {
    if (!drag || drag.pointerId !== event.pointerId) return;
    event.preventDefault(); event.stopImmediatePropagation();
    try {
      const deltaX = Math.round((event.clientX - drag.clientX) / drag.width * 1000);
      const deltaY = Math.round(event.clientY - drag.clientY);
      drag.changes = officeShapeMultiTranslate(drag.entries, deltaX, deltaY);
      const byId = new Map(drag.changes.map((change) => [change.id, change.position]));
      for (const entry of drag.entries) previewPosition(entry, byId.get(entry.id));
      const actualX = drag.changes[0].position.x - drag.entries[0].node.attrs.position.x;
      const actualY = drag.changes[0].position.y - drag.entries[0].node.attrs.position.y;
      $("shape-multi-status").textContent = `${drag.entries.length} Objekte · X ${actualX >= 0 ? "+" : ""}${actualX} · Y ${actualY >= 0 ? "+" : ""}${actualY}`;
    } catch { finishDrag(event, true); }
  };
  const finishResize = (event, cancel = false) => {
    if (!resizeDrag || (event?.pointerId != null && resizeDrag.pointerId !== event.pointerId)) return;
    const active = resizeDrag; resizeDrag = null;
    try { if (bound?.hasPointerCapture?.(active.pointerId)) bound.releasePointerCapture(active.pointerId); } catch { /* capture may be synthetic */ }
    event?.preventDefault?.(); event?.stopImmediatePropagation?.();
    suppressedClick = { id: active.sourceId, until: performance.now() + 500 };
    const changed = active.result.changes.some((change, index) => {
      const original = active.entries[index];
      if (change.type === "shape") return change.attrs.width !== original.node.attrs.width || change.attrs.height !== original.node.attrs.height;
      return change.members.some((member, memberIndex) => member.width !== original.node.child(memberIndex).attrs.width ||
        member.height !== original.node.child(memberIndex).attrs.height);
    });
    restoreResizePreview(active.entries); paint();
    if (cancel || !changed || !sameDragSource(active)) {
      if (!cancel && changed) notice("Die gemeinsame Größenänderung wurde wegen eines geänderten Dokumentzustands verworfen.", true);
      return;
    }
    commitShapeChanges(active.result.changes,
      `${active.entries.length} positionierte Objekte atomar auf ${Math.round(active.result.scaleX / 10)} % Breite und ${Math.round(active.result.scaleY / 10)} % Höhe skaliert. Rückgängig ist möglich.`,
      "Die ausgewählten Objekte besitzen bereits diese Größe.",
      "Die ausgewählten Objekte konnten nicht gemeinsam skaliert werden.");
  };
  const cancelResize = (event) => finishResize(event, true);
  const startResize = (event) => {
    const handle = event.target.closest?.(".office-shape-resize, .office-shape-group-resize");
    const sourceId = targetId(event.target), current = selectedEntries();
    if (!handle || !sourceId || !selectedIds.has(sourceId) || event.button !== 0 || event.isPrimary === false ||
        event.ctrlKey || event.metaKey || event.altKey || drag || resizeDrag || !allowed() ||
        document.querySelector("dialog[open]") || !officeShapeMultiCanArrange(current)) return;
    const source = current.find((entry) => entry.id === sourceId), sourceSize = officeShapeMultiRootSize(source);
    resizeDrag = { pointerId: event.pointerId, sourceId, clientX: event.clientX, clientY: event.clientY,
      sourceSize, entries: current, result: officeShapeMultiResize(current, OFFICE_SHAPE_MULTI_SCALE_BASE,
        OFFICE_SHAPE_MULTI_SCALE_BASE), session: state.session, doc: state.editor.state.doc };
    for (const entry of current) rootElement(entry)?.toggleAttribute("data-office-multi-resizing", true);
    try { bound?.setPointerCapture?.(event.pointerId); } catch { /* synthetic pointer events cannot capture */ }
    event.preventDefault(); event.stopImmediatePropagation();
  };
  const moveResize = (event) => {
    if (!resizeDrag || resizeDrag.pointerId !== event.pointerId) return;
    event.preventDefault(); event.stopImmediatePropagation();
    try {
      const width = Math.max(1, resizeDrag.sourceSize.width + event.clientX - resizeDrag.clientX);
      const height = Math.max(1, resizeDrag.sourceSize.height + event.clientY - resizeDrag.clientY);
      const scaleX = Math.max(1, Math.round(width / resizeDrag.sourceSize.width * OFFICE_SHAPE_MULTI_SCALE_BASE));
      const scaleY = Math.max(1, Math.round(height / resizeDrag.sourceSize.height * OFFICE_SHAPE_MULTI_SCALE_BASE));
      resizeDrag.result = officeShapeMultiResize(resizeDrag.entries, scaleX, scaleY, event.shiftKey);
      const byId = new Map(resizeDrag.result.changes.map((change) => [change.id, change]));
      for (const entry of resizeDrag.entries) previewResize(entry, byId.get(entry.id));
      $("shape-multi-status").textContent = `${resizeDrag.entries.length} Objekte · Breite ${Math.round(resizeDrag.result.scaleX / 10)} % · Höhe ${Math.round(resizeDrag.result.scaleY / 10)} %`;
    } catch { finishResize(event, true); }
  };
  const pointerAngle = (event, center) =>
    Math.atan2(event.clientY - center.y, event.clientX - center.x) * 180 / Math.PI;
  const shortestAngle = (value) => ((value + 540) % 360) - 180;
  const finishRotate = (event, cancel = false) => {
    if (!rotateDrag || (event?.pointerId != null && rotateDrag.pointerId !== event.pointerId)) return;
    const active = rotateDrag; rotateDrag = null;
    try { if (bound?.hasPointerCapture?.(active.pointerId)) bound.releasePointerCapture(active.pointerId); } catch { /* capture may be synthetic */ }
    event?.preventDefault?.(); event?.stopImmediatePropagation?.();
    if (active.moved) suppressedClick = { id: active.sourceId, until: performance.now() + 500 };
    const changed = active.result.changes.some((change, index) => {
      const original = active.entries[index];
      if (change.type === "shape") return change.attrs.rotation !== original.node.attrs.rotation;
      return change.members.some((member, memberIndex) => member.rotation !== original.node.child(memberIndex).attrs.rotation);
    });
    restoreRotatePreview(active.entries); paint();
    if (cancel || !changed || !sameDragSource(active)) {
      if (!cancel && changed) notice("Die gemeinsame Drehung wurde wegen eines geänderten Dokumentzustands verworfen.", true);
      return;
    }
    commitShapeChanges(active.result.changes,
      `${active.entries.length} positionierte Objekte atomar um ${active.result.delta} Grad gedreht. Rückgängig ist möglich.`,
      "Die ausgewählten Objekte besitzen bereits diese Drehung.",
      "Die ausgewählten Objekte konnten nicht gemeinsam gedreht werden.");
  };
  const cancelRotate = (event) => finishRotate(event, true);
  const startRotate = (event) => {
    const handle = event.target.closest?.(".office-shape-rotate, .office-shape-group-rotate");
    const sourceId = targetId(event.target), current = selectedEntries();
    if (!handle || !sourceId || !selectedIds.has(sourceId) || event.button !== 0 || event.isPrimary === false ||
        event.ctrlKey || event.metaKey || event.altKey || drag || resizeDrag || rotateDrag || !allowed() ||
        document.querySelector("dialog[open]") || !officeShapeMultiCanArrange(current)) return;
    const source = current.find((entry) => entry.id === sourceId), root = rootElement(source);
    const target = source.type === "shape" ? root?.querySelector(":scope > .office-shape") :
      root?.querySelector(":scope > .office-shape-group-content");
    const bounds = target?.getBoundingClientRect();
    if (!bounds || !Number.isFinite(bounds.left) || !Number.isFinite(bounds.top)) return;
    const center = { x: bounds.left + bounds.width / 2, y: bounds.top + bounds.height / 2 };
    rotateDrag = { pointerId: event.pointerId, sourceId, center, startPointer: pointerAngle(event, center),
      entries: current, result: officeShapeMultiRotate(current, 0), moved: false,
      session: state.session, doc: state.editor.state.doc };
    for (const entry of current) rootElement(entry)?.toggleAttribute("data-office-multi-rotating", true);
    try { bound?.setPointerCapture?.(event.pointerId); } catch { /* synthetic pointer events cannot capture */ }
    event.preventDefault(); event.stopImmediatePropagation();
  };
  const moveRotate = (event) => {
    if (!rotateDrag || rotateDrag.pointerId !== event.pointerId) return;
    event.preventDefault(); event.stopImmediatePropagation();
    try {
      const raw = shortestAngle(pointerAngle(event, rotateDrag.center) - rotateDrag.startPointer);
      rotateDrag.moved ||= Math.abs(raw) >= 1;
      const delta = event.shiftKey ? Math.round(raw / 15) * 15 : Math.round(raw);
      rotateDrag.result = officeShapeMultiRotate(rotateDrag.entries, delta);
      const byId = new Map(rotateDrag.result.changes.map((change) => [change.id, change]));
      for (const entry of rotateDrag.entries) previewRotate(entry, byId.get(entry.id));
      $("shape-multi-status").textContent = `${rotateDrag.entries.length} Objekte · Drehung ${delta >= 0 ? "+" : ""}${delta}°`;
    } catch { finishRotate(event, true); }
  };
  const rotateClick = (event) => {
    const handle = event.target.closest?.(".office-shape-rotate, .office-shape-group-rotate");
    const sourceId = targetId(event.target), current = selectedEntries();
    if (!handle || !sourceId || !selectedIds.has(sourceId) || !allowed() ||
        document.querySelector("dialog[open]") || !officeShapeMultiCanArrange(current)) return;
    event.preventDefault(); event.stopImmediatePropagation();
    if (suppressedClick?.id === sourceId && performance.now() <= suppressedClick.until) {
      suppressedClick = null; return;
    }
    suppressedClick = null;
    try {
      const result = officeShapeMultiRotate(current, 90);
      commitShapeChanges(result.changes,
        `${current.length} positionierte Objekte atomar um 90 Grad gedreht. Rückgängig ist möglich.`,
        "Die ausgewählten Objekte besitzen bereits diese Drehung.",
        "Die ausgewählten Objekte konnten nicht gemeinsam gedreht werden.");
    } catch { notice("Für die gemeinsame Drehung müssen mindestens zwei frei positionierte Objekte ausgewählt sein.", true); }
  };
  const selectTarget = (event) => {
    const id = targetId(event.target), additive = event.ctrlKey || event.metaKey, ranged = event.shiftKey;
    if (id && suppressedClick?.id === id && performance.now() <= suppressedClick.until) {
      suppressedClick = null; event.preventDefault(); event.stopImmediatePropagation(); return;
    }
    suppressedClick = null;
    if (!id) { if (!additive && !ranged && !mode && selectedIds.size) clear(); return; }
    if (!mode && !additive && !ranged) { if (selectedIds.size) clear(); return; }
    event.preventDefault(); event.stopImmediatePropagation();
    if (ranged) setSelection(officeShapeMultiRange(entries(), anchorId, id), id);
    else {
      const next = new Set(selectedIds);
      if (next.has(id)) next.delete(id); else if (next.size < OFFICE_SHAPE_MULTI_SELECTION_LIMIT) next.add(id);
      else { notice(`Es können höchstens ${OFFICE_SHAPE_MULTI_SELECTION_LIMIT} Objekte gleichzeitig ausgewählt werden.`, true); return; }
      setSelection([...next], id);
    }
    focus(state.editor);
  };
  const selectDirectTarget = (event) => {
    if (event.type === "pointerdown" && event.pointerType === "mouse") return;
    const id = targetId(event.target), additive = event.ctrlKey || event.metaKey, ranged = event.shiftKey;
    if (event.button !== 0 || event.isPrimary === false || !id || (!mode && !additive && !ranged) ||
        document.querySelector("dialog[open]")) return;
    selectTarget(event);
  };
  const bind = () => {
    const next = state.editor?.view.dom ?? null;
    if (bound === next) return;
    if (drag) finishDrag(null, true);
    if (resizeDrag) finishResize(null, true);
    if (rotateDrag) finishRotate(null, true);
    bound?.removeEventListener("click", rotateClick, true);
    bound?.removeEventListener("click", selectTarget, true);
    bound?.removeEventListener("pointerdown", startRotate, true);
    bound?.removeEventListener("pointerdown", startResize, true);
    bound?.removeEventListener("pointerdown", startDrag, true);
    bound?.removeEventListener("pointerdown", selectDirectTarget, true);
    bound?.removeEventListener("mousedown", selectDirectTarget, true);
    bound?.removeEventListener("pointermove", moveRotate, true);
    bound?.removeEventListener("pointermove", moveResize, true);
    bound?.removeEventListener("pointermove", moveDrag, true);
    bound?.removeEventListener("pointerup", finishRotate, true);
    bound?.removeEventListener("pointerup", finishResize, true);
    bound?.removeEventListener("pointerup", finishDrag, true);
    bound?.removeEventListener("pointercancel", cancelRotate, true);
    bound?.removeEventListener("pointercancel", cancelResize, true);
    bound?.removeEventListener("pointercancel", cancelDrag, true);
    bound?.removeEventListener("keydown", rotateKey, true);
    bound?.removeEventListener("keydown", resizeKey, true);
    bound = next;
    bound?.addEventListener("click", rotateClick, true);
    bound?.addEventListener("click", selectTarget, true);
    bound?.addEventListener("pointerdown", startRotate, true);
    bound?.addEventListener("pointerdown", startResize, true);
    bound?.addEventListener("pointerdown", startDrag, true);
    bound?.addEventListener("pointerdown", selectDirectTarget, true);
    bound?.addEventListener("mousedown", selectDirectTarget, true);
    bound?.addEventListener("pointermove", moveRotate, true);
    bound?.addEventListener("pointermove", moveResize, true);
    bound?.addEventListener("pointermove", moveDrag, true);
    bound?.addEventListener("pointerup", finishRotate, true);
    bound?.addEventListener("pointerup", finishResize, true);
    bound?.addEventListener("pointerup", finishDrag, true);
    bound?.addEventListener("pointercancel", cancelRotate, true);
    bound?.addEventListener("pointercancel", cancelResize, true);
    bound?.addEventListener("pointercancel", cancelDrag, true);
    bound?.addEventListener("keydown", rotateKey, true);
    bound?.addEventListener("keydown", resizeKey, true);
  };
  const clone = (editor, entry) => {
    if (entry.type === "shape") return editor.schema.nodes.shape.create(officeShapeAttributes({ ...entry.node.attrs,
      id: freshId("shape"), position: offsetPosition(entry.node.attrs.position) }));
    const members = entry.node.content.content.map((member) => editor.schema.nodes.shape.create(officeShapeAttributes({
      ...member.attrs, id: freshId("shape") })));
    return editor.schema.nodes.shapeGroup.create(officeShapeGroupAttributes({ ...entry.node.attrs,
      id: freshId("shape-group"), position: offsetPosition(entry.node.attrs.position) }), members);
  };
  $("shape-multi-toggle").addEventListener("click", () => { mode = !mode; paint(); focus(state.editor); });
  $("shape-multi-clear").addEventListener("click", () => { clear(); focus(state.editor); });
  const navigatorDialog = $("shape-multi-navigator-dialog");
  const navigatorForm = $("shape-multi-navigator-form");
  const navigatorLabel = (entry) => {
    const attrs = entry.node.attrs, positioned = attrs.position;
    const anchor = positioned ? `${positioned.layer === "front" ? "vor" : "hinter"} Text · X ${positioned.x} · Y ${positioned.y}` :
      attrs.wrap ? `Textumfluss ${attrs.wrap.side === "left" ? "links" : "rechts"}` : "im Textfluss";
    const stateLabel = `${attrs.hidden === true ? " · ausgeblendet" : ""}${attrs.locked === true ? " · gesperrt" : ""}`;
    if (entry.type === "shapeGroup") {
      const texts = entry.node.content.content.map((member) => String(member.attrs.text ?? "").trim()).filter(Boolean);
      return { title: attrs.name || `Formgruppe mit ${entry.node.childCount} Formen`,
        details: `Position ${entry.rootIndex + 1} · ${anchor}${attrs.altText ? ` · ${attrs.altText}` : ""}${texts.length ? ` · ${texts.join(" · ")}` : ""}${stateLabel}` };
    }
    const text = String(attrs.text ?? "").trim();
    return { title: attrs.name || text || `Form ${attrs.kind}`,
      details: `Position ${entry.rootIndex + 1} · ${attrs.kind} · ${anchor}${attrs.altText ? ` · ${attrs.altText}` : ""}${attrs.name && text ? ` · ${text}` : ""}${stateLabel}` };
  };
  const navigatorMatches = () => {
    if (!selectionSnapshot) return [];
    const query = $("shape-multi-navigator-search").value.trim().toLocaleLowerCase("de");
    const type = $("shape-multi-navigator-type").value;
    return selectionSnapshot.entries.filter((entry) => {
      if (type !== "all" && entry.type !== type) return false;
      const label = navigatorLabel(entry);
      return !query || `${label.title} ${label.details}`.toLocaleLowerCase("de").includes(query);
    });
  };
  const navigatorStatus = (message = "") => {
    if (!selectionSnapshot) return;
    const count = selectionSnapshot.checked.size, matches = navigatorMatches().length;
    $("shape-multi-navigator-status").textContent = message ||
      `${count} von höchstens ${OFFICE_SHAPE_MULTI_SELECTION_LIMIT} Objekten ausgewählt · ${matches} Treffer.`;
    $("shape-multi-navigator-clear").disabled = count === 0;
  };
  const renderNavigator = () => {
    const list = $("shape-multi-navigator-list"); list.replaceChildren();
    for (const entry of navigatorMatches()) {
      const label = document.createElement("label"), input = document.createElement("input"), body = document.createElement("span");
      const title = document.createElement("strong"), details = document.createElement("small"), description = navigatorLabel(entry);
      label.className = "shape-multi-navigator-item"; input.type = "checkbox"; input.value = entry.id;
      input.checked = selectionSnapshot.checked.has(entry.id); title.textContent = description.title; details.textContent = description.details;
      body.append(title, details); label.append(input, body); list.append(label);
      input.addEventListener("change", () => {
        if (input.checked && selectionSnapshot.checked.size >= OFFICE_SHAPE_MULTI_SELECTION_LIMIT) {
          input.checked = false;
          navigatorStatus(`Es können höchstens ${OFFICE_SHAPE_MULTI_SELECTION_LIMIT} Objekte gleichzeitig ausgewählt werden.`);
          return;
        }
        if (input.checked) selectionSnapshot.checked.add(entry.id); else selectionSnapshot.checked.delete(entry.id);
        navigatorStatus();
      });
    }
    if (!list.childElementCount) {
      const empty = document.createElement("p"); empty.className = "paragraph-help"; empty.textContent = "Keine passenden Objekte.";
      list.append(empty);
    }
    navigatorStatus();
  };
  const closeNavigator = () => {
    selectionSnapshot = null; if (navigatorDialog.open) navigatorDialog.close(); paint();
  };
  const updateNavigatorMatches = (operation) => {
    if (!selectionSnapshot) return;
    const next = new Set(selectionSnapshot.checked), matches = navigatorMatches();
    if (operation === "all") for (const entry of matches) next.add(entry.id);
    else if (operation === "invert") for (const entry of matches) {
      if (next.has(entry.id)) next.delete(entry.id); else next.add(entry.id);
    }
    if (next.size > OFFICE_SHAPE_MULTI_SELECTION_LIMIT) {
      navigatorStatus(`Diese Aktion würde die Grenze von ${OFFICE_SHAPE_MULTI_SELECTION_LIMIT} Objekten überschreiten.`); return;
    }
    selectionSnapshot.checked = next; renderNavigator();
  };
  $("shape-multi-navigator").addEventListener("click", () => {
    const editor = state.editor, current = entries();
    if (!editor || !allowed() || !current.length || document.querySelector("dialog[open]")) return;
    selectionSnapshot = { session: state.session, doc: editor.state.doc, entries: current,
      checked: new Set(selectedEntries().map((entry) => entry.id)) };
    $("shape-multi-navigator-search").value = ""; $("shape-multi-navigator-type").value = "all";
    renderNavigator(); navigatorDialog.showModal(); $("shape-multi-navigator-search").focus();
  });
  $("shape-multi-navigator-search").addEventListener("input", renderNavigator);
  $("shape-multi-navigator-type").addEventListener("change", renderNavigator);
  $("shape-multi-navigator-all").addEventListener("click", () => updateNavigatorMatches("all"));
  $("shape-multi-navigator-invert").addEventListener("click", () => updateNavigatorMatches("invert"));
  $("shape-multi-navigator-clear").addEventListener("click", () => {
    if (!selectionSnapshot) return; selectionSnapshot.checked.clear(); renderNavigator();
  });
  $("shape-multi-navigator-close").addEventListener("click", closeNavigator);
  $("shape-multi-navigator-cancel").addEventListener("click", closeNavigator);
  navigatorDialog.addEventListener("cancel", (event) => { event.preventDefault(); closeNavigator(); });
  navigatorForm.addEventListener("submit", (event) => {
    event.preventDefault();
    const snapshot = selectionSnapshot, editor = state.editor;
    const fresh = snapshot && editor && snapshot.session === state.session && snapshot.doc === editor.state.doc && allowed();
    try {
      if (!fresh) throw new Error("shape-multi-navigator-stale");
      const plan = officeShapeMultiSelectionPlan(entries(), [...snapshot.checked]);
      selectionSnapshot = null; navigatorDialog.close(); if (plan.ids.length) mode = true;
      setSelection(plan.ids); focus(editor);
      notice(plan.ids.length ? `${plan.ids.length} Objekte wurden über die Dokumentliste ausgewählt. Der Inhalt blieb unverändert.` :
        "Die Objektauswahl wurde aufgehoben. Der Inhalt blieb unverändert.");
    } catch {
      closeNavigator(); notice("Die Objektauswahl wurde wegen eines geänderten Dokumentzustands verworfen.", true);
    }
  });
  const commitObjectState = (options, message) => {
    const editor = state.editor, ids = [...selectedIds];
    if (!editor || !allowed() || !ids.length) return;
    try {
      const planned = officeShapeMultiSelectionPlan(entries(), ids).entries;
      const result = officeShapeMultiObjectState(planned, options);
      let tr = editor.state.tr;
      for (const change of result.changes) {
        const entry = planned.find((candidate) => candidate.id === change.id);
        if (!entry || entry.type !== change.type) throw new Error("shape-multi-object-state");
        tr = tr.setNodeMarkup(entry.pos, undefined, change.attrs);
      }
      if (!tr.docChanged || tr.doc.eq(editor.state.doc)) { notice("Der Objektzustand ist bereits gesetzt."); return; }
      validate(tr.doc); editor.view.dispatch(closeHistory(tr).scrollIntoView()); editor.view.dispatch(closeHistory(editor.state.tr));
      focus(editor); updateEditor(); paint(); notice(message);
    } catch { notice("Sichtbarkeit oder Bearbeitungsschutz konnten wegen eines geänderten Dokumentzustands nicht gesetzt werden.", true); }
  };
  $("shape-multi-show").addEventListener("click", () => commitObjectState({ hidden: false, locked: null },
    "Die ausgewählten Objekte wurden eingeblendet. Rückgängig ist möglich."));
  $("shape-multi-hide").addEventListener("click", () => commitObjectState({ hidden: true, locked: null },
    "Die ausgewählten Objekte wurden ausgeblendet und bleiben über die Objektliste erreichbar. Rückgängig ist möglich."));
  $("shape-multi-lock").addEventListener("click", () => commitObjectState({ hidden: null, locked: true },
    "Die ausgewählten Objekte sind gegen versehentliche Bearbeitung gesperrt. Rückgängig ist möglich."));
  $("shape-multi-unlock").addEventListener("click", () => commitObjectState({ hidden: null, locked: false },
    "Der Bearbeitungsschutz der ausgewählten Objekte wurde aufgehoben. Rückgängig ist möglich."));
  const commitOrder = (plan, current, message) => {
    const editor = state.editor;
    if (!editor || !allowed() || !officeShapeMultiUnlocked(current) || !plan.changed) return false;
    const nodes = plan.order.map((index) => editor.state.doc.child(index));
    let tr = editor.state.tr.replaceWith(0, editor.state.doc.content.size, nodes);
    const wanted = new Set(current.map((entry) => entry.id)); let firstPos = null;
    tr.doc.forEach((node, pos) => { if (firstPos == null && wanted.has(node.attrs?.id)) firstPos = pos; });
    if (firstPos == null) throw new Error("shape-multi-order-selection");
    tr = tr.setSelection(NodeSelection.create(tr.doc, firstPos)); validate(tr.doc);
    editor.view.dispatch(closeHistory(tr).scrollIntoView()); editor.view.dispatch(closeHistory(editor.state.tr));
    focus(editor); updateEditor(); paint(); notice(message); return true;
  };
  for (const button of document.querySelectorAll("[data-shape-multi-order]")) {
    button.addEventListener("click", () => {
      const editor = state.editor, current = selectedEntries(), action = button.dataset.shapeMultiOrder;
      if (!editor || !allowed()) return;
      try {
        const plan = officeShapeMultiOrder(editor.state.doc.childCount, current, action);
        if (!plan.changed) { paint(); return; }
        const labels = { previous: "einen Schritt nach vorn", next: "einen Schritt nach hinten",
          first: "an den Anfang", last: "an das Ende" };
        commitOrder(plan, current,
          `${current.length} Objekte wurden atomar ${labels[action]} verschoben. Rückgängig ist möglich.`);
      } catch { notice("Die ausgewählten Objekte konnten nicht gemeinsam in der Dokumentreihenfolge verschoben werden.", true); }
    });
  }
  const orderDialog = $("shape-multi-order-dialog"), orderForm = $("shape-multi-order-form");
  const closeOrder = () => {
    orderSnapshot = null; if (orderDialog.open) orderDialog.close(); paint();
  };
  const refreshOrder = () => {
    const target = Number($("shape-multi-order-target").value);
    if (!orderSnapshot || !orderForm.checkValidity()) {
      $("shape-multi-order-apply").disabled = true;
      $("shape-multi-order-status").textContent =
        `Bitte eine ganze Startposition von 1 bis ${orderSnapshot?.maximum ?? 1} eingeben.`;
      return null;
    }
    try {
      const plan = officeShapeMultiMoveTo(orderSnapshot.rootCount, orderSnapshot.entries, target);
      $("shape-multi-order-apply").disabled = !plan.changed;
      $("shape-multi-order-status").textContent = plan.changed ?
        `Die Auswahl beginnt danach an Position ${target} von ${orderSnapshot.maximum}.` :
        "Die Auswahl befindet sich bereits geschlossen an dieser Position.";
      return plan;
    } catch {
      $("shape-multi-order-apply").disabled = true;
      $("shape-multi-order-status").textContent =
        `Bitte eine ganze Startposition von 1 bis ${orderSnapshot?.maximum ?? 1} eingeben.`;
      return null;
    }
  };
  $("shape-multi-move-to").addEventListener("click", () => {
    const editor = state.editor, current = selectedEntries();
    if (!editor || !allowed() || current.length < 2 || current.length >= editor.state.doc.childCount ||
        document.querySelector("dialog[open]")) return;
    const maximum = editor.state.doc.childCount - current.length + 1;
    orderSnapshot = { session: state.session, doc: editor.state.doc, entries: current,
      ids: current.map((entry) => entry.id), rootCount: editor.state.doc.childCount, maximum };
    $("shape-multi-order-selection").textContent =
      `${current.length} ausgewählte Objekte werden als stabiler Block zwischen ${editor.state.doc.childCount} Dokumentelementen verschoben.`;
    const target = $("shape-multi-order-target"); target.min = "1"; target.max = String(maximum);
    target.value = String(current[0].rootIndex + 1);
    orderDialog.showModal(); refreshOrder(); target.focus(); target.select();
  });
  $("shape-multi-order-target").addEventListener("input", refreshOrder);
  $("shape-multi-order-close").addEventListener("click", closeOrder);
  $("shape-multi-order-cancel").addEventListener("click", closeOrder);
  orderDialog.addEventListener("cancel", (event) => { event.preventDefault(); closeOrder(); });
  orderForm.addEventListener("submit", (event) => {
    event.preventDefault();
    const current = selectedEntries(), snapshot = orderSnapshot;
    const fresh = snapshot && snapshot.session === state.session && snapshot.doc === state.editor?.state.doc &&
      allowed() && current.length === snapshot.ids.length &&
      current.every((entry, index) => entry.id === snapshot.ids[index]);
    const plan = fresh ? refreshOrder() : null;
    if (!plan?.changed) {
      closeOrder();
      if (!fresh) notice("Die exakte Positionierung wurde wegen eines geänderten Dokumentzustands verworfen.", true);
      return;
    }
    const count = current.length, target = plan.target; orderSnapshot = null; orderDialog.close();
    try {
      commitOrder(plan, current,
        `${count} Objekte wurden atomar als stabiler Block an Position ${target} verschoben. Rückgängig ist möglich.`);
    } catch { notice("Die ausgewählten Objekte konnten nicht an die exakte Dokumentposition verschoben werden.", true); }
  });
  $("shape-multi-duplicate").addEventListener("click", () => {
    const editor = state.editor, current = selectedEntries(); if (!editor || current.length < 2 || !allowed()) return;
    const copies = current.map((entry) => ({ source: entry, node: clone(editor, entry) })); let tr = editor.state.tr;
    for (const copy of [...copies].reverse()) tr.insert(copy.source.pos + copy.source.node.nodeSize, copy.node);
    const first = copies[0], firstPos = tr.mapping.map(first.source.pos + first.source.node.nodeSize, -1);
    tr.setSelection(NodeSelection.create(tr.doc, firstPos));
    try {
      validate(tr.doc); editor.view.dispatch(closeHistory(tr).scrollIntoView()); editor.view.dispatch(closeHistory(editor.state.tr));
      setSelection(copies.map((copy) => copy.node.attrs.id)); focus(editor); updateEditor();
      notice(`${copies.length} Objekte atomar dupliziert. Die Kopien besitzen neue IDs und können gemeinsam rückgängig gemacht werden.`);
    } catch { notice("Die Mehrfachauswahl konnte wegen der Dokumentgrenzen nicht dupliziert werden.", true); }
  });
  $("shape-multi-remove").addEventListener("click", () => {
    const editor = state.editor, current = selectedEntries(); if (!editor || current.length < 2 || !allowed()) return;
    let tr = editor.state.tr;
    for (const entry of [...current].reverse()) tr.delete(entry.pos, entry.pos + entry.node.nodeSize);
    try {
      validate(tr.doc); editor.view.dispatch(closeHistory(tr).scrollIntoView()); editor.view.dispatch(closeHistory(editor.state.tr));
      clear(); focus(editor); updateEditor(); notice(`${current.length} Objekte atomar aus dem Entwurf entfernt. Rückgängig ist möglich.`);
    } catch { notice("Die Mehrfachauswahl konnte nicht entfernt werden.", true); }
  });
  $("shape-multi-ungroup").addEventListener("click", () => {
    const editor = state.editor, current = selectedEntries();
    if (!editor || !allowed()) return;
    try {
      const plan = officeShapeMultiUngroup(current, positionedUngroupPlacements(current));
      const positions = new Map(plan.groups.flatMap((group) => group.memberPositions ?? [])
        .map((placement) => [placement.id, placement.position]));
      let tr = editor.state.tr;
      for (const entry of [...current].reverse()) {
        const members = entry.node.content.content.map((member) => {
          const position = positions.get(member.attrs.id);
          return position ? editor.schema.nodes.shape.create(officeShapeAttributes({ ...member.attrs, position })) : member;
        });
        tr = tr.replaceWith(entry.pos, entry.pos + entry.node.nodeSize, members);
      }
      tr.setSelection(NodeSelection.create(tr.doc, current[0].pos)); validate(tr.doc);
      regroupMemory = { session: state.session, groups: plan.groups };
      editor.view.dispatch(closeHistory(tr).scrollIntoView()); editor.view.dispatch(closeHistory(editor.state.tr));
      clear(); focus(editor); updateEditor();
      const placement = positions.size ? " frei positionierte" : "";
      notice(`${plan.groups.length} Formgruppen wurden atomar in ${plan.memberIds.length}${placement} eigenständige Formen aufgelöst. Rückgängig ist möglich.`);
    } catch {
      regroupMemory = null; paint();
      notice("Nur mindestens zwei vollständige Formgruppen derselben Ankerart können gemeinsam aufgelöst werden; ihre sichtbare Anordnung muss in den Positionsgrenzen liegen.", true);
    }
  });
  $("shape-multi-regroup").addEventListener("click", () => {
    const editor = state.editor;
    if (!editor || !allowed() || regroupMemory?.session !== state.session) return;
    try {
      const current = entries(), byId = new Map(current.map((entry) => [entry.id, entry]));
      const plan = officeShapeMultiRegroup(current, regroupMemory); let tr = editor.state.tr;
      for (const group of [...plan.groups].reverse()) {
        const members = group.memberIds.map((id) => byId.get(id));
        const memberNodes = members.map((entry) => group.attrs.position == null ? entry.node :
          editor.schema.nodes.shape.create(officeShapeAttributes({ ...entry.node.attrs, position: null })));
        const node = editor.schema.nodes.shapeGroup.create(group.attrs, memberNodes);
        tr = tr.replaceWith(members[0].pos, members.at(-1).pos + members.at(-1).node.nodeSize, node);
      }
      const first = plan.groups[0], firstEntry = byId.get(first.memberIds[0]);
      tr.setSelection(NodeSelection.create(tr.doc, firstEntry.pos)); validate(tr.doc);
      editor.view.dispatch(closeHistory(tr).scrollIntoView()); editor.view.dispatch(closeHistory(editor.state.tr));
      clear(); focus(editor); updateEditor();
      notice(`${plan.groups.length} zuletzt aufgelöste Formgruppen wurden atomar wiederhergestellt. Rückgängig ist möglich.`);
    } catch {
      regroupMemory = null; paint();
      notice("Die zuletzt aufgelösten Gruppen können in diesem Dokumentzustand nicht wiederhergestellt werden.", true);
    }
  });
  $("shape-multi-group").addEventListener("click", () => {
    const editor = state.editor, current = selectedEntries(); if (!editor || !allowed() || !officeShapeMultiCanGroup(current)) return;
    const attrs = officeShapeGroupAttributes({ id: freshId("shape-group"), layout: "row", gap: 16 });
    const group = editor.schema.nodes.shapeGroup.create(attrs, current.map((entry) => entry.node));
    const start = current[0].pos, end = current.at(-1).pos + current.at(-1).node.nodeSize;
    const tr = editor.state.tr.replaceWith(start, end, group); tr.setSelection(NodeSelection.create(tr.doc, start));
    try {
      validate(tr.doc); editor.view.dispatch(closeHistory(tr).scrollIntoView()); editor.view.dispatch(closeHistory(editor.state.tr));
      clear(); focus(editor); updateEditor(); notice(`${current.length} ausgewählte Formen atomar gruppiert. Rückgängig ist möglich.`);
    } catch { notice("Die ausgewählten Formen konnten nicht gruppiert werden.", true); }
  });
  const commitArrangement = (changes, message) => {
    const editor = state.editor, current = selectedEntries();
    if (!editor || !allowed() || !officeShapeMultiUnlocked(current) || changes.length !== current.length) return;
    const byId = new Map(changes.map((change) => [change.id, change.position]));
    let tr = editor.state.tr;
    for (const entry of current) {
      const position = byId.get(entry.id);
      const attrs = entry.type === "shape" ? officeShapeAttributes({ ...entry.node.attrs, position }) :
        officeShapeGroupAttributes({ ...entry.node.attrs, position });
      tr = tr.setNodeMarkup(entry.pos, undefined, attrs);
    }
    if (!tr.docChanged || tr.doc.eq(editor.state.doc)) {
      notice("Die ausgewählten Objekte sind bereits so angeordnet."); return;
    }
    try {
      validate(tr.doc); editor.view.dispatch(closeHistory(tr).scrollIntoView()); editor.view.dispatch(closeHistory(editor.state.tr));
      focus(editor); updateEditor(); notice(message);
    } catch { notice("Die ausgewählten Objekte konnten nicht gemeinsam angeordnet werden.", true); }
  };
  const commitShapeChanges = (changes, message, unchangedMessage, failureMessage) => {
    const editor = state.editor, current = selectedEntries();
    if (!editor || !allowed() || !officeShapeMultiUnlocked(current) || changes.length !== current.length) return;
    const byId = new Map(changes.map((change) => [change.id, change]));
    let tr = editor.state.tr;
    try {
      for (const entry of [...current].reverse()) {
        const change = byId.get(entry.id);
        if (!change || change.type !== entry.type) throw new Error("shape-multi-resize-change");
        if (entry.type === "shape") tr = tr.setNodeMarkup(entry.pos, undefined, officeShapeAttributes(change.attrs));
        else {
          if (change.members.length !== entry.node.childCount) throw new Error("shape-multi-resize-members");
          const members = entry.node.content.content.map((member, index) =>
            member.type.create(officeShapeAttributes(change.members[index])));
          const group = entry.node.type.create(officeShapeGroupAttributes(change.attrs), members);
          tr = tr.replaceWith(entry.pos, entry.pos + entry.node.nodeSize, group);
        }
      }
      if (!tr.docChanged || tr.doc.eq(editor.state.doc)) {
        notice(unchangedMessage); return;
      }
      validate(tr.doc); editor.view.dispatch(closeHistory(tr).scrollIntoView()); editor.view.dispatch(closeHistory(editor.state.tr));
      focus(editor); updateEditor(); notice(message);
    } catch { notice(failureMessage, true); }
  };
  $("shape-multi-copy-appearance").addEventListener("click", () => {
    const current = selectedEntries();
    if (!allowed() || !officeShapeMultiCanCopyAppearance(current)) return;
    try {
      appearanceClipboard = { session: state.session, sourceId: current[0].id,
        options: officeShapeMultiAppearanceSample(current[0]) };
      paint(); focus(state.editor);
      notice("Die sieben Darstellungswerte sind für dieses Dokument gemerkt. Wählen Sie mindestens zwei Zielobjekte.");
    } catch { appearanceClipboard = null; paint(); notice("Diese Gruppe besitzt keine einheitliche kopierbare Darstellung.", true); }
  });
  $("shape-multi-paste-appearance").addEventListener("click", () => {
    const current = selectedEntries();
    if (!allowed() || appearanceClipboard?.session !== state.session || !officeShapeMultiCanStyle(current)) return;
    try {
      const result = officeShapeMultiPasteAppearance(current, appearanceClipboard.options);
      commitShapeChanges(result.changes,
        `${current.length} Objekte haben die gemerkte Darstellung atomar erhalten. Rückgängig ist möglich.`,
        "Die Zielobjekte besitzen bereits die gemerkte Darstellung.",
        "Die gemerkte Darstellung konnte nicht auf die Zielobjekte übertragen werden.");
    } catch { appearanceClipboard = null; paint(); notice("Die gemerkte Darstellung ist nicht mehr gültig.", true); }
  });
  $("shape-multi-align").addEventListener("change", (event) => {
    const value = event.target.value; event.target.value = ""; if (!value) return;
    const [axis, alignment] = value.split(":");
    try {
      commitArrangement(officeShapeMultiAlignment(selectedEntries(), axis, alignment),
        `${selectedIds.size} positionierte Objekte atomar ausgerichtet. Rückgängig ist möglich.`);
    } catch { notice("Für die gemeinsame Ausrichtung müssen mindestens zwei frei positionierte Objekte ausgewählt sein.", true); }
  });
  $("shape-multi-distribute").addEventListener("change", (event) => {
    const axis = event.target.value; event.target.value = ""; if (!axis) return;
    try {
      commitArrangement(officeShapeMultiDistribution(selectedEntries(), axis),
        `${selectedIds.size} positionierte Objekte atomar gleichmäßig verteilt. Rückgängig ist möglich.`);
    } catch { notice("Für die gleichmäßige Verteilung müssen mindestens drei frei positionierte Objekte ausgewählt sein.", true); }
  });
  $("shape-multi-layer").addEventListener("change", (event) => {
    const layer = event.target.value; event.target.value = ""; if (!layer) return;
    try {
      commitArrangement(officeShapeMultiLayer(selectedEntries(), layer),
        `${selectedIds.size} positionierte Objekte atomar ${layer === "front" ? "vor" : "hinter"} den Text gelegt. Rückgängig ist möglich.`);
    } catch { notice("Für die gemeinsame Ebene müssen mindestens zwei frei positionierte Objekte ausgewählt sein.", true); }
  });
  const nudge = (axis, amount) => {
    try {
      commitArrangement(officeShapeMultiNudge(selectedEntries(), axis, amount),
        `${selectedIds.size} positionierte Objekte atomar um ${Math.abs(amount)} Schritt${Math.abs(amount) === 1 ? "" : "e"} verschoben. Rückgängig ist möglich.`);
    } catch { notice("Für das gemeinsame Verschieben müssen mindestens zwei frei positionierte Objekte ausgewählt sein.", true); }
  };
  for (const button of document.querySelectorAll("[data-shape-multi-nudge]")) {
    button.addEventListener("click", () => nudge(button.dataset.axis, Number(button.dataset.amount)));
  }
  const transformDialog = $("shape-multi-transform-dialog"), transformForm = $("shape-multi-transform-form");
  const transformOptions = () => ({
    deltaX: Number($("shape-multi-transform-x").value),
    deltaY: Number($("shape-multi-transform-y").value),
    scaleX: Number($("shape-multi-transform-width").value) * 10,
    scaleY: Number($("shape-multi-transform-height").value) * 10,
    lockAspect: $("shape-multi-transform-lock").checked,
    rotation: Number($("shape-multi-transform-rotation").value),
    layer: $("shape-multi-transform-layer").value || null,
  });
  const restoreTransformPreview = () => {
    if (!transformSnapshot) return;
    for (const entry of transformSnapshot.entries) {
      previewShapeChange(entry, originalShapeChange(entry), "data-office-multi-transforming", false);
    }
  };
  const refreshTransformPreview = () => {
    if (!transformSnapshot || !transformForm.checkValidity()) {
      restoreTransformPreview(); $("shape-multi-transform-apply").disabled = true;
      $("shape-multi-transform-status").textContent = "Bitte alle Werte innerhalb der angegebenen Grenzen eingeben.";
      return null;
    }
    try {
      const result = officeShapeMultiTransform(transformSnapshot.entries, transformOptions());
      const byId = new Map(result.changes.map((change) => [change.id, change]));
      for (const entry of transformSnapshot.entries) {
        previewShapeChange(entry, byId.get(entry.id), "data-office-multi-transforming", true);
      }
      $("shape-multi-transform-apply").disabled = false;
      $("shape-multi-transform-status").textContent =
        `${transformSnapshot.entries.length} Objekte · X ${result.deltaX >= 0 ? "+" : ""}${result.deltaX} · Y ${result.deltaY >= 0 ? "+" : ""}${result.deltaY} · Breite ${Math.round(result.scaleX / 10)} % · Höhe ${Math.round(result.scaleY / 10)} % · Drehung ${result.rotation >= 0 ? "+" : ""}${result.rotation}°`;
      return result;
    } catch {
      restoreTransformPreview(); $("shape-multi-transform-apply").disabled = true;
      $("shape-multi-transform-status").textContent = "Diese Kombination überschreitet die gemeinsamen Objektgrenzen.";
      return null;
    }
  };
  const closeTransform = () => {
    restoreTransformPreview(); transformSnapshot = null;
    if (transformDialog.open) transformDialog.close(); paint();
  };
  $("shape-multi-transform").addEventListener("click", () => {
    const current = selectedEntries();
    if (!allowed() || !officeShapeMultiCanArrange(current) || document.querySelector("dialog[open]")) return;
    transformForm.reset();
    transformSnapshot = { session: state.session, doc: state.editor.state.doc, entries: current,
      ids: current.map((entry) => entry.id) };
    $("shape-multi-transform-selection").textContent =
      `${current.length} positionierte Objekte werden gemeinsam und in einem Rückgängig-Schritt transformiert.`;
    transformDialog.showModal(); refreshTransformPreview(); $("shape-multi-transform-x").focus();
  });
  for (const input of transformForm.querySelectorAll("input, select")) {
    input.addEventListener("input", refreshTransformPreview); input.addEventListener("change", refreshTransformPreview);
  }
  $("shape-multi-transform-close").addEventListener("click", closeTransform);
  $("shape-multi-transform-cancel").addEventListener("click", closeTransform);
  transformDialog.addEventListener("cancel", (event) => { event.preventDefault(); closeTransform(); });
  transformForm.addEventListener("submit", (event) => {
    event.preventDefault();
    const current = selectedEntries(), snapshot = transformSnapshot;
    const fresh = snapshot && snapshot.session === state.session && snapshot.doc === state.editor?.state.doc && allowed() &&
      current.length === snapshot.ids.length && current.every((entry, index) => entry.id === snapshot.ids[index]);
    const result = fresh ? refreshTransformPreview() : null;
    if (!result) {
      closeTransform(); notice("Die exakte Transformation wurde wegen eines ungültigen oder geänderten Dokumentzustands verworfen.", true);
      return;
    }
    restoreTransformPreview(); transformSnapshot = null; transformDialog.close(); paint();
    commitShapeChanges(result.changes,
      `${current.length} positionierte Objekte atomar exakt transformiert. Rückgängig ist möglich.`,
      "Die ausgewählten Objekte besitzen bereits diese Transformation.",
      "Die ausgewählten Objekte konnten nicht exakt transformiert werden.");
  });
  const appearanceDialog = $("shape-multi-appearance-dialog"), appearanceForm = $("shape-multi-appearance-form");
  const appearanceInteger = (id) => $(id).value === "" ? null : Number($(id).value);
  const appearanceChoice = (id) => $(id).value || null;
  const appearanceOptions = () => ({
    fill: appearanceChoice("shape-multi-appearance-fill"),
    stroke: appearanceChoice("shape-multi-appearance-stroke"),
    strokeWidth: appearanceInteger("shape-multi-appearance-stroke-width"),
    fontSize: appearanceInteger("shape-multi-appearance-font-size"),
    textColor: appearanceChoice("shape-multi-appearance-text-color"),
    textStyle: appearanceChoice("shape-multi-appearance-text-style"),
    textAlign: appearanceChoice("shape-multi-appearance-text-align"),
  });
  const appearanceMembers = (current) => current.flatMap((entry) => entry.type === "shape" ?
    [officeShapeAttributes(entry.node.attrs)] :
    entry.node.content.content.map((member) => officeShapeAttributes(member.attrs)));
  const commonAppearanceValue = (members, key, fallback = null) => {
    const values = members.map((member) => member[key] ?? fallback);
    return values.every((value) => value === values[0]) ? String(values[0]) : "";
  };
  const restoreAppearancePreview = () => {
    if (!appearanceSnapshot) return;
    for (const entry of appearanceSnapshot.entries) {
      previewShapeChange(entry, originalShapeChange(entry), "data-office-multi-appearance", false);
    }
  };
  const refreshAppearancePreview = () => {
    const options = appearanceOptions();
    if (!appearanceSnapshot || !appearanceForm.checkValidity() || Object.values(options).every((value) => value === null)) {
      restoreAppearancePreview(); $("shape-multi-appearance-apply").disabled = true;
      $("shape-multi-appearance-status").textContent = "Mindestens einen gültigen Darstellungswert auswählen.";
      return null;
    }
    try {
      const result = officeShapeMultiAppearance(appearanceSnapshot.entries, options);
      const byId = new Map(result.changes.map((change) => [change.id, change]));
      for (const entry of appearanceSnapshot.entries) {
        previewShapeChange(entry, byId.get(entry.id), "data-office-multi-appearance", true);
      }
      const changed = Object.values(options).filter((value) => value !== null).length;
      $("shape-multi-appearance-apply").disabled = false;
      $("shape-multi-appearance-status").textContent =
        `${appearanceSnapshot.entries.length} Objekte · ${appearanceSnapshot.memberCount} Formen · ${changed} gemeinsame Werte`;
      return result;
    } catch {
      restoreAppearancePreview(); $("shape-multi-appearance-apply").disabled = true;
      $("shape-multi-appearance-status").textContent = "Diese Darstellung enthält einen unzulässigen Wert.";
      return null;
    }
  };
  const closeAppearance = () => {
    restoreAppearancePreview(); appearanceSnapshot = null;
    if (appearanceDialog.open) appearanceDialog.close(); paint();
  };
  $("shape-multi-appearance").addEventListener("click", () => {
    const current = selectedEntries();
    if (!allowed() || !officeShapeMultiCanStyle(current) || document.querySelector("dialog[open]")) return;
    appearanceForm.reset();
    const members = appearanceMembers(current);
    $("shape-multi-appearance-fill").value = commonAppearanceValue(members, "fill");
    $("shape-multi-appearance-stroke").value = commonAppearanceValue(members, "stroke");
    $("shape-multi-appearance-stroke-width").value = commonAppearanceValue(members, "strokeWidth");
    $("shape-multi-appearance-font-size").value = commonAppearanceValue(members, "fontSize", 16);
    $("shape-multi-appearance-text-color").value = commonAppearanceValue(members, "textColor", "auto");
    $("shape-multi-appearance-text-style").value = commonAppearanceValue(members, "textStyle", "normal");
    $("shape-multi-appearance-text-align").value = commonAppearanceValue(members, "textAlign");
    appearanceSnapshot = { session: state.session, doc: state.editor.state.doc, entries: current,
      ids: current.map((entry) => entry.id), memberCount: members.length };
    $("shape-multi-appearance-selection").textContent =
      `${current.length} Objekte mit ${members.length} Formen werden gemeinsam und in einem Rückgängig-Schritt formatiert.`;
    appearanceDialog.showModal(); refreshAppearancePreview(); $("shape-multi-appearance-fill").focus();
  });
  for (const input of appearanceForm.querySelectorAll("input, select")) {
    input.addEventListener("input", refreshAppearancePreview);
    input.addEventListener("change", refreshAppearancePreview);
  }
  $("shape-multi-appearance-close").addEventListener("click", closeAppearance);
  $("shape-multi-appearance-cancel").addEventListener("click", closeAppearance);
  appearanceDialog.addEventListener("cancel", (event) => { event.preventDefault(); closeAppearance(); });
  appearanceForm.addEventListener("submit", (event) => {
    event.preventDefault();
    const current = selectedEntries(), snapshot = appearanceSnapshot;
    const fresh = snapshot && snapshot.session === state.session && snapshot.doc === state.editor?.state.doc && allowed() &&
      current.length === snapshot.ids.length && current.every((entry, index) => entry.id === snapshot.ids[index]);
    const result = fresh ? refreshAppearancePreview() : null;
    if (!result) {
      closeAppearance(); notice("Die gemeinsame Darstellung wurde wegen eines ungültigen oder geänderten Dokumentzustands verworfen.", true);
      return;
    }
    restoreAppearancePreview(); appearanceSnapshot = null; appearanceDialog.close(); paint();
    commitShapeChanges(result.changes,
      `${current.length} Objekte atomar gemeinsam formatiert. Rückgängig ist möglich.`,
      "Die ausgewählten Objekte besitzen bereits diese Darstellung.",
      "Die ausgewählten Objekte konnten nicht gemeinsam formatiert werden.");
  });
  const resizeKey = (event) => {
    const handle = event.target.closest?.(".office-shape-resize, .office-shape-group-resize");
    const direction = { ArrowLeft: ["horizontal", -1], ArrowRight: ["horizontal", 1],
      ArrowUp: ["vertical", -1], ArrowDown: ["vertical", 1] }[event.key];
    const sourceId = targetId(event.target), current = selectedEntries();
    if (!handle || !direction || !sourceId || !selectedIds.has(sourceId) || event.ctrlKey || event.metaKey || event.altKey ||
        !allowed() || document.querySelector("dialog[open]") || !officeShapeMultiCanArrange(current)) return;
    event.preventDefault(); event.stopImmediatePropagation();
    try {
      const source = current.find((entry) => entry.id === sourceId), size = officeShapeMultiRootSize(source);
      const step = (event.shiftKey ? 10 : 1) * direction[1];
      const scaleX = direction[0] === "horizontal" ? Math.max(1, Math.round((size.width + step) / size.width * OFFICE_SHAPE_MULTI_SCALE_BASE)) : OFFICE_SHAPE_MULTI_SCALE_BASE;
      const scaleY = direction[0] === "vertical" ? Math.max(1, Math.round((size.height + step) / size.height * OFFICE_SHAPE_MULTI_SCALE_BASE)) : OFFICE_SHAPE_MULTI_SCALE_BASE;
      const result = officeShapeMultiResize(current, scaleX, scaleY);
      commitShapeChanges(result.changes,
        `${current.length} positionierte Objekte atomar per Tastatur skaliert. Rückgängig ist möglich.`,
        "Die ausgewählten Objekte besitzen bereits diese Größe.",
        "Die ausgewählten Objekte konnten nicht gemeinsam skaliert werden.");
    } catch { notice("Für die gemeinsame Größenänderung müssen mindestens zwei frei positionierte Objekte ausgewählt sein.", true); }
  };
  const rotateKey = (event) => {
    const handle = event.target.closest?.(".office-shape-rotate, .office-shape-group-rotate");
    const direction = { ArrowLeft: -1, ArrowDown: -1, ArrowRight: 1, ArrowUp: 1 }[event.key];
    const sourceId = targetId(event.target), current = selectedEntries();
    if (!handle || (direction == null && event.key !== "Home") || !sourceId || !selectedIds.has(sourceId) ||
        event.ctrlKey || event.metaKey || event.altKey || !allowed() || document.querySelector("dialog[open]") ||
        !officeShapeMultiCanArrange(current)) return;
    event.preventDefault(); event.stopImmediatePropagation();
    try {
      const source = current.find((entry) => entry.id === sourceId);
      const delta = event.key === "Home" ? -officeShapeMultiRootRotation(source) :
        direction * (event.shiftKey ? 15 : 1);
      const result = officeShapeMultiRotate(current, delta);
      commitShapeChanges(result.changes,
        `${current.length} positionierte Objekte atomar per Tastatur gedreht. Rückgängig ist möglich.`,
        "Die ausgewählten Objekte besitzen bereits diese Drehung.",
        "Die ausgewählten Objekte konnten nicht gemeinsam gedreht werden.");
    } catch { notice("Für die gemeinsame Drehung müssen mindestens zwei frei positionierte Objekte ausgewählt sein.", true); }
  };
  document.addEventListener("keydown", (event) => {
    if (event.key === "Escape" && rotateDrag) { event.preventDefault(); finishRotate(null, true); return; }
    if (event.key === "Escape" && resizeDrag) { event.preventDefault(); finishResize(null, true); return; }
    if (event.key === "Escape" && drag) { event.preventDefault(); finishDrag(null, true); return; }
    if (event.key === "Escape" && selectedIds.size && !document.querySelector("dialog[open]")) { event.preventDefault(); clear(); return; }
    const arrow = { ArrowLeft: ["horizontal", -1], ArrowRight: ["horizontal", 1],
      ArrowUp: ["vertical", -1], ArrowDown: ["vertical", 1] }[event.key];
    const active = document.activeElement, inScope = state.editor?.view.dom.contains(active) || active?.closest?.(".shape-multi-tools");
    if (arrow && selectedIds.size >= 2 && allowed() && !event.ctrlKey && !event.metaKey && !event.altKey &&
        !document.querySelector("dialog[open]") && inScope && !["INPUT", "SELECT", "TEXTAREA"].includes(active?.tagName)) {
      event.preventDefault(); nudge(arrow[0], arrow[1] * (event.shiftKey ? 10 : 1)); return;
    }
    if (!["Delete", "Backspace"].includes(event.key) || selectedIds.size < 2 || !allowed() || document.querySelector("dialog[open]")) return;
    if (!state.editor?.view.dom.contains(document.activeElement) && !document.activeElement?.closest?.(".shape-multi-tools")) return;
    event.preventDefault(); $("shape-multi-remove").click();
  });
  const update = () => {
    bind();
    if (drag && (drag.session !== state.session || !allowed())) finishDrag(null, true);
    if (resizeDrag && (resizeDrag.session !== state.session || !allowed())) finishResize(null, true);
    if (rotateDrag && (rotateDrag.session !== state.session || !allowed())) finishRotate(null, true);
    if (selectionSnapshot && (selectionSnapshot.session !== state.session ||
        selectionSnapshot.doc !== state.editor?.state.doc || !allowed())) closeNavigator();
    if (orderSnapshot && (orderSnapshot.session !== state.session ||
        orderSnapshot.doc !== state.editor?.state.doc || !allowed())) closeOrder();
    if (transformSnapshot && (transformSnapshot.session !== state.session ||
        transformSnapshot.doc !== state.editor?.state.doc || !allowed())) closeTransform();
    if (appearanceSnapshot && (appearanceSnapshot.session !== state.session ||
        appearanceSnapshot.doc !== state.editor?.state.doc || !allowed())) closeAppearance();
    if (appearanceClipboard && (appearanceClipboard.session !== state.session || !allowed())) appearanceClipboard = null;
    if (regroupMemory && (regroupMemory.session !== state.session || state.session?.canWrite !== true ||
        state.session?.historical === true)) regroupMemory = null;
    if (session !== state.session) {
      session = state.session; mode = false; selectedIds.clear(); anchorId = null; appearanceClipboard = null;
      regroupMemory = null;
    }
    const available = new Set(entries().map((entry) => entry.id));
    for (const id of selectedIds) if (!available.has(id)) selectedIds.delete(id);
    $("shape-multi-toggle").disabled = !allowed(); paint();
  };
  return { update, clear };
}
