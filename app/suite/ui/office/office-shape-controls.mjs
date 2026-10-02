import { Node } from "@tiptap/core";
import { NodeSelection } from "@tiptap/pm/state";
import { applyOfficeShapeDOM, officeShapeAttributes, officeShapeElement, OFFICE_SHAPE_COLORS, OFFICE_SHAPE_LIMIT } from "./office-shapes.mjs";

export function officeShapeExtension() {
  return Node.create({
    name: "shape", group: "block", atom: true, selectable: true, draggable: false,
    addAttributes: () => Object.fromEntries(["id", "kind", "width", "height", "fill", "stroke", "strokeWidth", "text", "textAlign"]
      .map((key) => [key, { default: null, rendered: false }])),
    parseHTML: () => [], renderHTML: ({ node }) => ["div", { class: "office-shape" }, node.attrs.text || ""],
    addNodeView() {
      return ({ node, getPos, editor }) => {
        let current = node;
        const dom = officeShapeElement(node.attrs);
        dom.addEventListener("dblclick", () => {
          const position = typeof getPos === "function" ? getPos() : null;
          if (Number.isInteger(position)) { editor.commands.setNodeSelection(position); document.getElementById("shape-options")?.click(); }
        });
        return { dom,
          update(next) { if (next.type !== current.type) return false; current = next; applyOfficeShapeDOM(dom, next.attrs); return true; },
          selectNode() { dom.classList.add("ProseMirror-selectednode"); },
          deselectNode() { dom.classList.remove("ProseMirror-selectednode"); }, ignoreMutation: () => true,
        };
      };
    },
  });
}

export function installOfficeShapeControls({ state, allowed, current, validate, focus, updateEditor, notice }) {
  const $ = (id) => document.getElementById(id);
  let action = null;
  const selected = () => state.editor?.state.selection instanceof NodeSelection && state.editor.state.selection.node.type.name === "shape";
  const count = () => { let total = 0; state.editor?.state.doc.descendants((node) => { if (node.type.name === "shape") total += 1; }); return total; };
  const close = (restore = false) => { if ($("shape-dialog").open) $("shape-dialog").close(); if (restore && action && current(action)) focus(state.editor); action = null; };
  const fill = (attrs) => {
    $("shape-kind").value = attrs.kind; $("shape-width").value = String(attrs.width); $("shape-height").value = String(attrs.height);
    $("shape-fill").value = attrs.fill; $("shape-stroke").value = attrs.stroke; $("shape-stroke-width").value = String(attrs.strokeWidth);
    $("shape-text").value = attrs.text; $("shape-text-align").value = attrs.textAlign;
  };
  const read = () => officeShapeAttributes({ id: action?.attrs.id || `shape-${crypto.randomUUID().replaceAll("-", "").slice(0, 24)}`,
    kind: $("shape-kind").value, width: Number($("shape-width").value), height: Number($("shape-height").value),
    fill: $("shape-fill").value, stroke: $("shape-stroke").value, strokeWidth: Number($("shape-stroke-width").value),
    text: $("shape-text").value, textAlign: $("shape-text-align").value });
  const preview = () => {
    try { const attrs = read(); applyOfficeShapeDOM($("shape-preview"), attrs); $("shape-status").textContent = "Die Vorschau entspricht der gespeicherten, inerten Form."; $("shape-apply").disabled = false; }
    catch { $("shape-status").textContent = "Bitte Maße, Farben, Rahmen und Text prüfen."; $("shape-apply").disabled = true; }
  };
  const open = () => {
    if (!allowed() || (!selected() && count() >= OFFICE_SHAPE_LIMIT)) return;
    const selection = state.editor.state.selection, editing = selected();
    action = { session: state.session, context: state.context, revision: state.session.revision, editor: state.editor,
      document: state.editor.state.doc, selection, storedMarks: state.editor.state.storedMarks,
      from: selection.from, editing, attrs: editing ? officeShapeAttributes(selection.node.attrs) : null };
    $("shape-title").textContent = editing ? "Form bearbeiten" : "Form einfügen";
    $("shape-apply").textContent = editing ? "Änderungen übernehmen" : "In Entwurf einfügen";
    $("shape-remove").hidden = !editing;
    fill(action.attrs || { kind: "rectangle", width: 320, height: 160, fill: "teal", stroke: "slate", strokeWidth: 2, text: "", textAlign: "center" });
    preview(); $("shape-dialog").showModal(); $("shape-kind").focus();
  };
  $("shape-options").addEventListener("click", open);
  $("shape-form").addEventListener("input", preview);
  $("shape-form").addEventListener("submit", (event) => {
    event.preventDefault(); if (!action || !current(action)) { close(); return; }
    try {
      const attrs = read(), editor = state.editor;
      if (action.editing) {
        if (!(editor.state.selection instanceof NodeSelection) || editor.state.selection.node.type.name !== "shape") throw new Error("selection");
        const tr = editor.state.tr.setNodeMarkup(editor.state.selection.from, undefined, attrs);
        validate(tr.doc); editor.view.dispatch(tr.scrollIntoView());
      } else {
        if (count() >= OFFICE_SHAPE_LIMIT || !editor.chain().focus().insertContent({ type: "shape", attrs }).run()) throw new Error("insert");
        validate(editor.state.doc);
      }
      close(); focus(editor); updateEditor();
    } catch { notice("Die Form konnte nicht übernommen werden. Auswahl und Grenzwerte prüfen.", true); }
  });
  $("shape-remove").addEventListener("click", () => {
    if (!action || !current(action) || !selected()) return;
    const editor = state.editor, tr = editor.state.tr.deleteSelection();
    try { validate(tr.doc); editor.view.dispatch(tr.scrollIntoView()); close(); focus(editor); updateEditor(); }
    catch { notice("Die Form konnte nicht entfernt werden.", true); }
  });
  for (const id of ["shape-close", "shape-cancel"]) $(id).addEventListener("click", () => close(true));
  $("shape-dialog").addEventListener("cancel", (event) => { event.preventDefault(); close(true); });
  const update = () => { $("shape-options").disabled = !allowed() || (!selected() && count() >= OFFICE_SHAPE_LIMIT); $("shape-options").textContent = selected() ? "Form bearbeiten …" : "Form einfügen …"; };
  return { update, close };
}
