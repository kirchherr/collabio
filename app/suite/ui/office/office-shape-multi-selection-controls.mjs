import { NodeSelection } from "@tiptap/pm/state";
import { closeHistory } from "@tiptap/pm/history";
import { OFFICE_SHAPE_LIMIT, officeShapeAttributes } from "./office-shapes.mjs";
import { OFFICE_SHAPE_GROUP_LIMIT, officeShapeGroupAttributes } from "./office-shape-groups.mjs";
import { OFFICE_SHAPE_MULTI_SELECTION_LIMIT, officeShapeMultiCanGroup, officeShapeMultiRange,
  officeShapeMultiAlignment, officeShapeMultiCanArrange, officeShapeMultiDistribution,
  officeShapeMultiSelection } from "./office-shape-multi-selection.mjs";

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
  let mode = false, anchorId = null, session = null, bound = null;
  const entries = () => state.editor ? rootEntries(state.editor.state.doc) : [];
  const selectedEntries = () => officeShapeMultiSelection(entries(), [...selectedIds]);
  const paint = () => {
    const editor = state.editor;
    if (editor) editor.view.dom.querySelectorAll("[data-office-multi-selected]").forEach((element) => {
      element.removeAttribute("data-office-multi-selected"); element.removeAttribute("aria-selected");
    });
    for (const entry of selectedEntries()) {
      const selector = entry.type === "shapeGroup" ? `.office-shape-group[data-shape-group="${entry.id}"]` :
        `.office-shape-node:has(>.office-shape[data-office-shape="${entry.id}"])`;
      const element = editor?.view.dom.querySelector(selector);
      if (element) { element.toggleAttribute("data-office-multi-selected", true); element.setAttribute("aria-selected", "true"); }
    }
    const count = selectedIds.size;
    $("shape-multi-toggle").setAttribute("aria-pressed", String(mode));
    $("shape-multi-status").textContent = count === 0 ? "Keine Objekte ausgewählt" :
      count === 1 ? "1 Objekt ausgewählt" : `${count} Objekte ausgewählt`;
    const actions = $("shape-multi-actions"); actions.hidden = count === 0;
    const current = selectedEntries(), writable = allowed(), enough = current.length >= 2, doc = state.editor?.state.doc;
    const duplicateShapes = current.reduce((total, entry) => total + (entry.type === "shape" ? 1 : entry.node.childCount), 0);
    const duplicateGroups = current.filter((entry) => entry.type === "shapeGroup").length;
    $("shape-multi-duplicate").disabled = !doc || !writable || !enough || shapeCount(doc) + duplicateShapes > OFFICE_SHAPE_LIMIT ||
      groupCount(doc) + duplicateGroups > OFFICE_SHAPE_GROUP_LIMIT;
    $("shape-multi-remove").disabled = !writable || !enough;
    $("shape-multi-group").disabled = !doc || !writable || !officeShapeMultiCanGroup(current) || groupCount(doc) >= OFFICE_SHAPE_GROUP_LIMIT;
    $("shape-multi-align").disabled = !writable || !officeShapeMultiCanArrange(current);
    $("shape-multi-distribute").disabled = !writable || !officeShapeMultiCanArrange(current, 3);
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
  const selectTarget = (event) => {
    const id = targetId(event.target), additive = event.ctrlKey || event.metaKey, ranged = event.shiftKey;
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
  const bind = () => {
    const next = state.editor?.view.dom ?? null;
    if (bound === next) return;
    bound?.removeEventListener("click", selectTarget, true); bound = next;
    bound?.addEventListener("click", selectTarget, true);
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
    if (!editor || !allowed() || changes.length !== current.length) return;
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
  document.addEventListener("keydown", (event) => {
    if (event.key === "Escape" && selectedIds.size && !document.querySelector("dialog[open]")) { event.preventDefault(); clear(); return; }
    if (!["Delete", "Backspace"].includes(event.key) || selectedIds.size < 2 || !allowed() || document.querySelector("dialog[open]")) return;
    if (!state.editor?.view.dom.contains(document.activeElement) && !document.activeElement?.closest?.(".shape-multi-tools")) return;
    event.preventDefault(); $("shape-multi-remove").click();
  });
  const update = () => {
    bind();
    if (session !== state.session) { session = state.session; mode = false; selectedIds.clear(); anchorId = null; }
    const available = new Set(entries().map((entry) => entry.id));
    for (const id of selectedIds) if (!available.has(id)) selectedIds.delete(id);
    $("shape-multi-toggle").disabled = !allowed(); paint();
  };
  return { update, clear };
}
