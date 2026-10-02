import { Node } from "@tiptap/core";
import { NodeSelection } from "@tiptap/pm/state";
import { OFFICE_SHAPE_GROUP_MEMBER_LIMIT, officeShapeGroupAttributes } from "./office-shape-groups.mjs";

export function officeShapeGroupExtension() {
  return Node.create({
    name: "shapeGroup", group: "block", content: `shape{2,${OFFICE_SHAPE_GROUP_MEMBER_LIMIT}}`,
    isolating: true, selectable: true, draggable: false,
    addAttributes: () => ({ id: { default: null, rendered: false }, layout: { default: null, rendered: false },
      gap: { default: null, rendered: false } }),
    parseHTML: () => [], renderHTML: () => ["section", { class: "office-shape-group" }, 0],
    addNodeView() {
      return ({ node, editor, getPos }) => {
        const dom = document.createElement("section"); dom.className = "office-shape-group";
        const control = document.createElement("button"); control.type = "button"; control.className = "office-shape-group-control";
        control.setAttribute("contenteditable", "false"); control.textContent = "Formgruppe bearbeiten";
        const contentDOM = document.createElement("div"); contentDOM.className = "office-shape-group-content";
        dom.append(control, contentDOM);
        const paint = (current) => {
          const attrs = officeShapeGroupAttributes(current.attrs);
          dom.dataset.shapeGroup = attrs.id; dom.dataset.shapeGroupLayout = attrs.layout;
          dom.style.setProperty("--shape-group-gap", `${attrs.gap}px`);
          dom.style.setProperty("--shape-group-columns", attrs.layout === "row" ? String(current.childCount) : "1");
          control.setAttribute("aria-label", `Formgruppe mit ${current.childCount} Formen bearbeiten`);
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
        return { dom, contentDOM,
          update(next) { if (next.type !== node.type) return false; paint(next); node = next; return true; },
          selectNode() { dom.classList.add("ProseMirror-selectednode"); },
          deselectNode() { dom.classList.remove("ProseMirror-selectednode"); },
          stopEvent(event) { return event.target === control || control.contains(event.target); },
          ignoreMutation(mutation) { return mutation.target === control || control.contains(mutation.target); },
        };
      };
    },
  });
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
