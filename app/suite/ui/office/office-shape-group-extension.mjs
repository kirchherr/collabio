import { Node } from "@tiptap/core";
import { closeHistory } from "@tiptap/pm/history";
import { NodeSelection } from "@tiptap/pm/state";
import { OFFICE_SHAPE_GROUP_MEMBER_LIMIT, officeShapeGroupAttributes, officeShapeGroupBounds } from "./office-shape-groups.mjs";

export function officeShapeGroupExtension() {
  return Node.create({
    name: "shapeGroup", group: "block", content: `shape{2,${OFFICE_SHAPE_GROUP_MEMBER_LIMIT}}`,
    isolating: true, selectable: true, draggable: false,
    addAttributes: () => ({ id: { default: null, rendered: false }, layout: { default: null, rendered: false },
      gap: { default: null, rendered: false }, connection: { default: null, rendered: false },
      position: { default: null, rendered: false } }),
    parseHTML: () => [], renderHTML: () => ["section", { class: "office-shape-group" }, 0],
    addNodeView() {
      return ({ node, editor, getPos }) => {
        const dom = document.createElement("section"); dom.className = "office-shape-group";
        const control = document.createElement("button"); control.type = "button"; control.className = "office-shape-group-control";
        control.setAttribute("contenteditable", "false"); control.textContent = "Formgruppe bearbeiten";
        const anchor = document.createElement("button"); anchor.type = "button"; anchor.className = "office-shape-group-anchor";
        anchor.setAttribute("contenteditable", "false");
        const contentDOM = document.createElement("div"); contentDOM.className = "office-shape-group-content";
        dom.append(control, anchor, contentDOM);
        const setPosition = (value) => {
          dom.toggleAttribute("data-shape-group-positioned", value != null);
          if (value == null) {
            delete dom.dataset.shapeGroupPosition;
            for (const name of ["--shape-group-position-x", "--shape-group-position-shift", "--shape-group-position-y"]) dom.style.removeProperty(name);
            anchor.hidden = true; return;
          }
          dom.dataset.shapeGroupPosition = value.layer;
          dom.style.setProperty("--shape-group-position-x", `${value.x / 10}%`);
          dom.style.setProperty("--shape-group-position-shift", `${-value.x / 10}%`);
          dom.style.setProperty("--shape-group-position-y", `${value.y}px`);
          anchor.hidden = false;
          anchor.textContent = value.layer === "front" ? "Gruppenanker · vor Text" : "Gruppenanker · hinter Text";
          anchor.setAttribute("aria-label", `${anchor.textContent}; X ${value.x}; Y ${value.y} Pixel; ziehen oder mit Pfeiltasten verschieben`);
        };
        const commitPosition = (position) => {
          if (node.attrs.position == null || typeof getPos !== "function") return;
          const at = getPos(); if (!Number.isInteger(at)) return;
          const attrs = officeShapeGroupAttributes({ ...node.attrs, position });
          const transaction = editor.state.tr.setNodeMarkup(at, undefined, attrs);
          editor.view.dispatch(closeHistory(transaction).scrollIntoView()); editor.view.dispatch(closeHistory(editor.state.tr));
        };
        const paint = (current) => {
          const attrs = officeShapeGroupAttributes(current.attrs);
          const bounds = officeShapeGroupBounds(attrs, current.content.content.map((member) => member.attrs));
          dom.dataset.shapeGroup = attrs.id; dom.dataset.shapeGroupLayout = attrs.layout;
          dom.style.setProperty("--shape-group-gap", `${attrs.gap}px`);
          dom.style.setProperty("--shape-group-columns", attrs.layout === "row" ? String(current.childCount) : "1");
          dom.style.setProperty("--shape-group-bound-width", String(bounds.width));
          setPosition(attrs.position ?? null);
          if (attrs.connection) {
            dom.dataset.shapeGroupConnection = attrs.connection.kind;
            dom.dataset.shapeGroupConnectionColor = attrs.connection.color;
            dom.style.setProperty("--shape-group-connection-width", `${attrs.connection.width}px`);
          } else {
            delete dom.dataset.shapeGroupConnection; delete dom.dataset.shapeGroupConnectionColor;
            dom.style.removeProperty("--shape-group-connection-width");
          }
          const connection = attrs.connection ? `; Verbindung ${attrs.connection.kind}, ${attrs.connection.color}, ${attrs.connection.width} Pixel` : "";
          const position = attrs.position ? `; ${attrs.position.layer === "front" ? "vor" : "hinter"} Text; X ${attrs.position.x}; Y ${attrs.position.y} Pixel` : "";
          control.setAttribute("aria-label", `Formgruppe mit ${current.childCount} Formen bearbeiten${connection}${position}`);
        };
        paint(node);
        const selectGroup = () => {
          const position = typeof getPos === "function" ? getPos() : null;
          if (Number.isInteger(position)) {
            editor.view.dispatch(editor.state.tr.setSelection(NodeSelection.create(editor.state.doc, position)));
            editor.view.focus();
          }
        };
        control.addEventListener("mousedown", (event) => { event.preventDefault(); event.stopPropagation(); selectGroup(); });
        control.addEventListener("click", (event) => { event.preventDefault(); event.stopPropagation(); });
        anchor.addEventListener("click", (event) => { event.preventDefault(); event.stopPropagation(); selectGroup(); });
        let drag = null;
        const dragTarget = anchor.ownerDocument.defaultView;
        const move = (event) => {
          if (!drag || drag.id !== event.pointerId) return;
          drag.next = { ...drag.start,
            x: Math.max(0, Math.min(1000, Math.round(drag.start.x + (event.clientX - drag.clientX) / drag.width * 1000))),
            y: Math.max(-1200, Math.min(1200, Math.round(drag.start.y + event.clientY - drag.clientY))) };
          setPosition(drag.next);
        };
        const removeDragListeners = () => {
          dragTarget?.removeEventListener("pointermove", move);
          dragTarget?.removeEventListener("pointerup", finish);
          dragTarget?.removeEventListener("pointercancel", cancel);
        };
        const finish = (event, cancel = false) => {
          if (!drag || (event.pointerId != null && drag.id !== event.pointerId)) return;
          removeDragListeners();
          if (anchor.hasPointerCapture(drag.id)) anchor.releasePointerCapture(drag.id);
          const { next, start } = drag; drag = null;
          if (cancel) { paint(node); return; }
          if (next.x !== start.x || next.y !== start.y) commitPosition(next);
        };
        const cancel = (event) => finish(event, true);
        anchor.addEventListener("pointerdown", (event) => {
          if (event.button !== 0 || node.attrs.position == null) return;
          const bounds = editor.view.dom.getBoundingClientRect();
          drag = { id: event.pointerId, clientX: event.clientX, clientY: event.clientY, width: Math.max(1, bounds.width),
            start: node.attrs.position, next: node.attrs.position };
          dragTarget?.addEventListener("pointermove", move);
          dragTarget?.addEventListener("pointerup", finish);
          dragTarget?.addEventListener("pointercancel", cancel);
          anchor.setPointerCapture(event.pointerId); event.preventDefault(); event.stopPropagation();
        });
        anchor.addEventListener("keydown", (event) => {
          if (event.key === "Home" && node.attrs.position != null) {
            event.preventDefault(); commitPosition({ ...node.attrs.position, x: 0, y: 0 }); return;
          }
          const direction = { ArrowLeft: [-1, 0], ArrowRight: [1, 0], ArrowUp: [0, -1], ArrowDown: [0, 1] }[event.key];
          if (!direction || event.ctrlKey || event.metaKey || event.altKey || node.attrs.position == null) return;
          event.preventDefault(); const step = event.shiftKey ? 10 : 1, position = node.attrs.position;
          commitPosition({ ...position, x: Math.max(0, Math.min(1000, position.x + direction[0] * step)),
            y: Math.max(-1200, Math.min(1200, position.y + direction[1] * step)) });
        });
        return { dom, contentDOM,
          update(next) { if (next.type !== node.type) return false; paint(next); node = next; return true; },
          selectNode() { dom.classList.add("ProseMirror-selectednode"); },
          deselectNode() { dom.classList.remove("ProseMirror-selectednode"); },
          stopEvent(event) { return event.target === control || control.contains(event.target) || event.target === anchor || anchor.contains(event.target); },
          ignoreMutation(mutation) { return eventTarget(control, mutation.target) || eventTarget(anchor, mutation.target); },
          destroy() { removeDragListeners(); drag = null; },
        };
      };
    },
  });
}

function eventTarget(control, target) {
  return target === control || control.contains(target);
}

export function selectedOfficeShapeContext(editor, selection = editor.state.selection) {
  if (selection.node?.type.name !== "shape") return null;
  const parent = selection.$from.parent;
  if (parent.type.name !== "shapeGroup") {
    return { grouped: false, shape: selection.node, shapePos: selection.from, shapeIndex: selection.$from.index(),
      root: parent, rootIndex: selection.$from.index(), group: null, groupPos: null };
  }
  const depth = selection.$from.depth;
  return { grouped: true, shape: selection.node, shapePos: selection.from, shapeIndex: selection.$from.index(),
    root: selection.$from.node(depth - 1), rootIndex: selection.$from.index(depth - 1),
    group: parent, groupPos: selection.$from.before(depth) };
}
