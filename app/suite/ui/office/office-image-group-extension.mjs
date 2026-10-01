import { Node } from "@tiptap/core";
import { NodeSelection } from "@tiptap/pm/state";
import { OFFICE_IMAGE_GROUP_MEMBER_LIMIT, officeImageGroupAttributes } from "./office-image-groups.mjs";

export function officeImageGroupExtension() {
  return Node.create({
    name: "imageGroup", group: "block", content: `image{2,${OFFICE_IMAGE_GROUP_MEMBER_LIMIT}}`,
    isolating: true, selectable: true, draggable: false,
    addAttributes: () => ({ id: { default: null, rendered: false }, layout: { default: null, rendered: false },
      gap: { default: null, rendered: false } }),
    parseHTML: () => [],
    renderHTML: () => ["section", { class: "office-image-group" }, 0],
    addNodeView() {
      return ({ node, editor, getPos }) => {
        const dom = document.createElement("section"); dom.className = "office-image-group";
        const control = document.createElement("button"); control.type = "button"; control.className = "office-image-group-control";
        control.setAttribute("contenteditable", "false"); control.textContent = "Bildgruppe bearbeiten";
        const contentDOM = document.createElement("div"); contentDOM.className = "office-image-group-content";
        dom.append(control, contentDOM);
        const paint = (current) => {
          const attrs = officeImageGroupAttributes(current.attrs);
          dom.dataset.imageGroup = attrs.id; dom.dataset.imageGroupLayout = attrs.layout;
          dom.style.setProperty("--image-group-gap", `${attrs.gap}px`);
          dom.style.setProperty("--image-group-columns", attrs.layout === "row" ? String(current.childCount) : "1");
          control.setAttribute("aria-label", `Bildgruppe mit ${current.childCount} Bildern bearbeiten`);
        };
        paint(node);
        const selectGroup = () => {
          const position = typeof getPos === "function" ? getPos() : null;
          if (Number.isInteger(position)) {
            const selection = NodeSelection.create(editor.state.doc, position);
            editor.view.dispatch(editor.state.tr.setSelection(selection));
            editor.view.focus();
          }
        };
        control.addEventListener("mousedown", (event) => {
          event.preventDefault(); event.stopPropagation(); selectGroup();
        });
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

export function selectedOfficeImageContext(editor, selection = editor.state.selection) {
  if (selection.node?.type.name !== "image") return null;
  const parent = selection.$from.parent;
  if (parent.type.name !== "imageGroup") {
    return { grouped: false, image: selection.node, imagePos: selection.from, imageIndex: selection.$from.index(),
      root: parent, rootIndex: selection.$from.index(), group: null, groupPos: null };
  }
  const depth = selection.$from.depth;
  return { grouped: true, image: selection.node, imagePos: selection.from, imageIndex: selection.$from.index(),
    root: selection.$from.node(depth - 1), rootIndex: selection.$from.index(depth - 1),
    group: parent, groupPos: selection.$from.before(depth) };
}
