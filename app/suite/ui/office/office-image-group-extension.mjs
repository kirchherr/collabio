import { Node } from "@tiptap/core";
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
        control.addEventListener("click", () => {
          const position = typeof getPos === "function" ? getPos() : null;
          if (Number.isInteger(position)) editor.commands.setNodeSelection(position + 1);
        });
        return { dom, contentDOM,
          update(next) { if (next.type !== node.type) return false; paint(next); node = next; return true; },
          selectNode() { dom.classList.add("ProseMirror-selectednode"); },
          deselectNode() { dom.classList.remove("ProseMirror-selectednode"); },
          ignoreMutation(mutation) { return mutation.target === control || control.contains(mutation.target); },
        };
      };
    },
  });
}

export function selectedOfficeImageContext(editor, selection = editor.state.selection) {
  if (selection.node?.type.name !== "image") return null;
  const root = editor.state.doc;
  let result = null;
  root.forEach((node, position, rootIndex) => {
    if (result) return;
    if (node.type.name === "image" && position === selection.from) {
      result = { grouped: false, image: node, imagePos: position, imageIndex: rootIndex,
        root, rootIndex, group: null, groupPos: null };
      return;
    }
    if (node.type.name !== "imageGroup") return;
    node.forEach((image, offset, imageIndex) => {
      const imagePos = position + 1 + offset;
      if (!result && imagePos === selection.from) {
        result = { grouped: true, image, imagePos, imageIndex, root, rootIndex,
          group: node, groupPos: position };
      }
    });
  });
  return result;
}
