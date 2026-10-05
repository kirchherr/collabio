import { Node } from "@tiptap/core";
import { NodeSelection } from "@tiptap/pm/state";
import { closeHistory } from "@tiptap/pm/history";
import { applyOfficeShapeDOM, officeShapeAttributes, officeShapeElement, officeShapePosition, officeShapeWrap, OFFICE_SHAPE_COLORS, OFFICE_SHAPE_LIMIT } from "./office-shapes.mjs";
import { OFFICE_SHAPE_GROUP_LIMIT, OFFICE_SHAPE_GROUP_MEMBER_LIMIT, officeShapeGroupAttributes } from "./office-shape-groups.mjs";
import { selectedOfficeShapeContext } from "./office-shape-group-extension.mjs";

export function officeShapeExtension() {
  return Node.create({
    name: "shape", group: "block", atom: true, selectable: true, draggable: false,
    addAttributes: () => Object.fromEntries(["id", "kind", "width", "height", "fill", "stroke", "strokeWidth", "text", "textAlign", "fontSize", "textColor", "textStyle", "rotation", "position", "wrap"]
      .map((key) => [key, { default: null, rendered: false }])),
    parseHTML: () => [], renderHTML: ({ node }) => ["div", { class: "office-shape" }, node.attrs.text || ""],
    addNodeView() {
      return ({ node, getPos, editor }) => {
        let current = node;
        const dom = document.createElement("div"); dom.className = "office-shape-node"; dom.setAttribute("contenteditable", "false");
        const commitPosition = (position) => {
          if (current.attrs.position == null || typeof getPos !== "function") return;
          const at = getPos(); if (!Number.isInteger(at)) return;
          const attrs = officeShapeAttributes({ ...current.attrs, position });
          const transaction = editor.state.tr.setNodeMarkup(at, undefined, attrs);
          editor.view.dispatch(closeHistory(transaction).scrollIntoView()); editor.view.dispatch(closeHistory(editor.state.tr));
        };
        const commitSize = (width, height) => {
          if (typeof getPos !== "function") return;
          const at = getPos(); if (!Number.isInteger(at)) return;
          const attrs = officeShapeAttributes({ ...current.attrs, width, height });
          const transaction = editor.state.tr.setNodeMarkup(at, undefined, attrs);
          editor.view.dispatch(closeHistory(transaction).scrollIntoView()); editor.view.dispatch(closeHistory(editor.state.tr));
        };
        const render = () => {
          const shape = officeShapeElement(current.attrs); dom.replaceChildren(shape);
          dom.toggleAttribute("data-shape-positioned", current.attrs.position != null);
          if (current.attrs.wrap != null) {
            const wrap = officeShapeWrap(current.attrs.wrap), sideways = [90, 270].includes(current.attrs.rotation);
            const width = sideways ? current.attrs.height : current.attrs.width, height = sideways ? current.attrs.width : current.attrs.height;
            dom.dataset.shapeWrap = wrap.side; dom.style.setProperty("--office-shape-wrap-gap", `${wrap.gap}px`);
            dom.style.setProperty("--office-shape-wrap-width", `${Math.min(width, 480 * width / height)}px`);
          } else {
            delete dom.dataset.shapeWrap; dom.style.removeProperty("--office-shape-wrap-gap"); dom.style.removeProperty("--office-shape-wrap-width");
          }
          dom.toggleAttribute("data-shape-sideways", [90, 270].includes(current.attrs.rotation));
          dom.style.setProperty("--office-shape-width", String(current.attrs.width));
          dom.style.setProperty("--office-shape-height", String(current.attrs.height));
          const resize = document.createElement("button"); resize.type = "button"; resize.className = "office-shape-resize";
          const describeSize = (width, height) => resize.setAttribute("aria-label", `Formgröße ${width} mal ${height} Pixel; ziehen oder mit Pfeiltasten ändern`);
          resize.textContent = "Größe ändern"; describeSize(current.attrs.width, current.attrs.height);
          resize.addEventListener("click", () => { const at = typeof getPos === "function" ? getPos() : null; if (Number.isInteger(at)) editor.commands.setNodeSelection(at); });
          let sizeDrag = null;
          resize.addEventListener("pointerdown", (event) => {
            if (event.button !== 0) return;
            sizeDrag = { id: event.pointerId, clientX: event.clientX, clientY: event.clientY,
              width: current.attrs.width, height: current.attrs.height, nextWidth: current.attrs.width, nextHeight: current.attrs.height };
            resize.setPointerCapture(event.pointerId); event.preventDefault();
          });
          resize.addEventListener("pointermove", (event) => {
            if (!sizeDrag || sizeDrag.id !== event.pointerId) return;
            sizeDrag.nextWidth = Math.max(80, Math.min(1200, Math.round(sizeDrag.width + event.clientX - sizeDrag.clientX)));
            sizeDrag.nextHeight = Math.max(40, Math.min(800, Math.round(sizeDrag.height + event.clientY - sizeDrag.clientY)));
            describeSize(sizeDrag.nextWidth, sizeDrag.nextHeight);
            applyOfficeShapeDOM(shape, { ...current.attrs, width: sizeDrag.nextWidth, height: sizeDrag.nextHeight });
          });
          const finishSize = (event, cancel = false) => {
            if (!sizeDrag || (event.pointerId != null && sizeDrag.id !== event.pointerId)) return;
            if (resize.hasPointerCapture(sizeDrag.id)) resize.releasePointerCapture(sizeDrag.id);
            const { width, height, nextWidth, nextHeight } = sizeDrag; sizeDrag = null;
            if (cancel) { render(); return; }
            if (nextWidth !== width || nextHeight !== height) commitSize(nextWidth, nextHeight);
          };
          resize.addEventListener("pointerup", (event) => finishSize(event)); resize.addEventListener("pointercancel", (event) => finishSize(event, true));
          resize.addEventListener("keydown", (event) => {
            const direction = { ArrowLeft: [-1, 0], ArrowRight: [1, 0], ArrowUp: [0, -1], ArrowDown: [0, 1] }[event.key];
            if (!direction || event.ctrlKey || event.metaKey || event.altKey) return;
            event.preventDefault(); const step = event.shiftKey ? 10 : 1;
            commitSize(Math.max(80, Math.min(1200, current.attrs.width + direction[0] * step)),
              Math.max(40, Math.min(800, current.attrs.height + direction[1] * step)));
          });
          dom.append(resize);
          const rotate = document.createElement("button"); rotate.type = "button"; rotate.className = "office-shape-rotate";
          rotate.textContent = "90° drehen";
          rotate.setAttribute("aria-label", `Form um 90 Grad nach rechts drehen; aktuell ${current.attrs.rotation || 0} Grad`);
          rotate.addEventListener("click", (event) => {
            event.preventDefault(); if (typeof getPos !== "function") return;
            const at = getPos(); if (!Number.isInteger(at)) return;
            const next = ((current.attrs.rotation || 0) + 90) % 360;
            const attrs = officeShapeAttributes({ ...current.attrs, rotation: next || null });
            const transaction = editor.state.tr.setNodeMarkup(at, undefined, attrs);
            editor.view.dispatch(closeHistory(transaction).scrollIntoView()); editor.view.dispatch(closeHistory(editor.state.tr));
          });
          dom.append(rotate);
          if (current.attrs.position == null) return;
          const position = officeShapePosition(current.attrs.position), anchor = document.createElement("button");
          anchor.type = "button"; anchor.className = "office-shape-anchor";
          anchor.textContent = position.layer === "front" ? "Formanker · vor Text" : "Formanker · hinter Text";
          anchor.setAttribute("aria-label", `${anchor.textContent}; X ${position.x}; Y ${position.y} Pixel; ziehen oder mit Pfeiltasten verschieben`);
          const paintAnchor = (value) => {
            anchor.style.setProperty("--office-shape-position-x", `${value.x / 10}%`);
            anchor.style.setProperty("--office-shape-position-shift", `${-value.x / 10}%`);
            anchor.style.setProperty("--office-shape-position-y", `${value.y}px`);
          };
          paintAnchor(position);
          for (const [name, value] of [["--office-shape-position-x", `${position.x / 10}%`],
            ["--office-shape-position-shift", `${-position.x / 10}%`], ["--office-shape-position-y", `${position.y}px`]]) {
            resize.style.setProperty(name, value); rotate.style.setProperty(name, value);
          }
          anchor.addEventListener("click", () => { const at = typeof getPos === "function" ? getPos() : null; if (Number.isInteger(at)) editor.commands.setNodeSelection(at); });
          let drag = null;
          anchor.addEventListener("pointerdown", (event) => {
            if (event.button !== 0) return;
            const bounds = editor.view.dom.getBoundingClientRect();
            drag = { id: event.pointerId, clientX: event.clientX, clientY: event.clientY, width: Math.max(1, bounds.width), start: position, next: position };
            anchor.setPointerCapture(event.pointerId); event.preventDefault();
          });
          anchor.addEventListener("pointermove", (event) => {
            if (!drag || drag.id !== event.pointerId) return;
            drag.next = { ...drag.start,
              x: Math.max(0, Math.min(1000, Math.round(drag.start.x + (event.clientX - drag.clientX) / drag.width * 1000))),
              y: Math.max(-1200, Math.min(1200, Math.round(drag.start.y + event.clientY - drag.clientY))) };
            paintAnchor(drag.next); applyOfficeShapeDOM(shape, { ...current.attrs, position: drag.next });
          });
          const finish = (event, cancel = false) => {
            if (!drag || (event.pointerId != null && drag.id !== event.pointerId)) return;
            if (anchor.hasPointerCapture(drag.id)) anchor.releasePointerCapture(drag.id);
            const next = drag.next, start = drag.start; drag = null;
            if (cancel) { render(); return; }
            if (next.x !== start.x || next.y !== start.y) commitPosition(next);
          };
          anchor.addEventListener("pointerup", (event) => finish(event)); anchor.addEventListener("pointercancel", (event) => finish(event, true));
          anchor.addEventListener("keydown", (event) => {
            const direction = { ArrowLeft: [-1, 0], ArrowRight: [1, 0], ArrowUp: [0, -1], ArrowDown: [0, 1] }[event.key];
            if (!direction || event.ctrlKey || event.metaKey || event.altKey) return;
            event.preventDefault(); const step = event.shiftKey ? 10 : 1;
            commitPosition({ ...position, x: Math.max(0, Math.min(1000, position.x + direction[0] * step)),
              y: Math.max(-1200, Math.min(1200, position.y + direction[1] * step)) });
          });
          dom.append(anchor);
        };
        dom.addEventListener("dblclick", () => {
          const position = typeof getPos === "function" ? getPos() : null;
          if (Number.isInteger(position)) { editor.commands.setNodeSelection(position); document.getElementById("shape-options")?.click(); }
        });
        render();
        return { dom,
          update(next) { if (next.type !== current.type) return false; current = next; render(); return true; },
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
  const selected = () => state.editor?.state.selection instanceof NodeSelection && ["shape", "shapeGroup"].includes(state.editor.state.selection.node.type.name);
  const count = () => { let total = 0; state.editor?.state.doc.descendants((node) => { if (node.type.name === "shape") total += 1; }); return total; };
  const groupCount = (doc) => { let total = 0; doc.forEach((node) => { if (node.type.name === "shapeGroup") total += 1; }); return total; };
  const groupCandidate = (owner, direction) => {
    const context = owner?.shapeContext;
    if (!context || owner.attrs.wrap != null || owner.attrs.position != null) return null;
    const other = context.root.maybeChild(context.rootIndex + (direction === "previous" ? -1 : 1));
    if (!other) return null;
    if (context.grouped) return other.type.name === "shape" && other.attrs.wrap == null && other.attrs.position == null &&
      context.group.childCount < OFFICE_SHAPE_GROUP_MEMBER_LIMIT ? other : null;
    if (other.type.name === "shape") return other.attrs.wrap == null && other.attrs.position == null &&
      groupCount(owner.document) < OFFICE_SHAPE_GROUP_LIMIT ? other : null;
    return other.type.name === "shapeGroup" && other.childCount < OFFICE_SHAPE_GROUP_MEMBER_LIMIT ? other : null;
  };
  const close = (restore = false) => { if ($("shape-dialog").open) $("shape-dialog").close(); if (restore && action && current(action)) focus(state.editor); action = null; };
  const fill = (attrs) => {
    $("shape-kind").value = attrs.kind; $("shape-width").value = String(attrs.width); $("shape-height").value = String(attrs.height);
    $("shape-fill").value = attrs.fill; $("shape-stroke").value = attrs.stroke; $("shape-stroke-width").value = String(attrs.strokeWidth);
    $("shape-text").value = attrs.text; $("shape-text-align").value = attrs.textAlign;
    $("shape-font-size").value = String(attrs.fontSize ?? 16); $("shape-text-color").value = attrs.textColor ?? "auto";
    $("shape-text-style").value = attrs.textStyle ?? "normal";
    $("shape-rotation").value = String(attrs.rotation || 0);
    $("shape-wrap").value = attrs.wrap?.side ?? "none"; $("shape-wrap-gap").value = String(attrs.wrap?.gap ?? 16);
    $("shape-position-layer").value = attrs.position?.layer ?? "flow";
    $("shape-position-x").value = String(attrs.position?.x ?? 0); $("shape-position-y").value = String(attrs.position?.y ?? 0);
    $("shape-group-layout").value = action?.shapeContext?.group?.attrs.layout ?? "row";
    $("shape-group-gap").value = String(action?.shapeContext?.group?.attrs.gap ?? 16);
    $("shape-group-connection").value = action?.shapeContext?.group?.attrs.connection?.kind ?? "none";
    $("shape-group-connection-color").value = action?.shapeContext?.group?.attrs.connection?.color ?? "slate";
    $("shape-group-connection-width").value = String(action?.shapeContext?.group?.attrs.connection?.width ?? 2);
  };
  const shapeId = () => { const bytes = new Uint8Array(12); crypto.getRandomValues(bytes); return `shape-${Array.from(bytes, (byte) => byte.toString(16).padStart(2, "0")).join("")}`; };
  const shapeGroupId = () => `shape-group-${shapeId().slice(6)}`;
  const readGroup = (id) => officeShapeGroupAttributes({ id, layout: $("shape-group-layout").value,
    gap: Number($("shape-group-gap").value), connection: $("shape-group-connection").value === "none" ? null : {
      kind: $("shape-group-connection").value, color: $("shape-group-connection-color").value,
      width: Number($("shape-group-connection-width").value),
    } });
  const read = () => officeShapeAttributes({ id: action?.attrs?.id || action?.id || (action.id = shapeId()),
    kind: $("shape-kind").value, width: Number($("shape-width").value), height: Number($("shape-height").value),
    fill: $("shape-fill").value, stroke: $("shape-stroke").value, strokeWidth: Number($("shape-stroke-width").value),
    text: $("shape-text").value, textAlign: $("shape-text-align").value,
    fontSize: Number($("shape-font-size").value) === 16 ? null : Number($("shape-font-size").value),
    textColor: $("shape-text-color").value === "auto" ? null : $("shape-text-color").value,
    textStyle: $("shape-text-style").value === "normal" ? null : $("shape-text-style").value,
    rotation: Number($("shape-rotation").value) || null,
    wrap: $("shape-wrap").value === "none" ? null : { side: $("shape-wrap").value, gap: Number($("shape-wrap-gap").value) },
    position: $("shape-position-layer").value === "flow" ? null : { layer: $("shape-position-layer").value,
      x: Number($("shape-position-x").value), y: Number($("shape-position-y").value) } });
  const preview = () => {
    try { const attrs = read(); applyOfficeShapeDOM($("shape-preview"), attrs); $("shape-status").textContent = "Die Vorschau entspricht der gespeicherten, inerten Form."; $("shape-apply").disabled = false; }
    catch { $("shape-status").textContent = "Bitte Maße, Farben, Rahmen und Text prüfen."; $("shape-apply").disabled = true; }
  };
  const open = () => {
    if (!allowed() || (!selected() && count() >= OFFICE_SHAPE_LIMIT)) return;
    const selection = state.editor.state.selection, groupSelected = selection.node?.type.name === "shapeGroup";
    const shapeSelection = groupSelected ? NodeSelection.create(state.editor.state.doc, selection.from + 1) : selection;
    const editing = shapeSelection.node?.type.name === "shape";
    action = { session: state.session, context: state.context, revision: state.session.revision, editor: state.editor,
      document: state.editor.state.doc, selection, storedMarks: state.editor.state.storedMarks,
      from: selection.from, shapeSelection, editing, attrs: editing ? officeShapeAttributes(shapeSelection.node.attrs) : null };
    action.shapeContext = editing ? selectedOfficeShapeContext(state.editor, shapeSelection) : null;
    $("shape-title").textContent = editing ? "Form bearbeiten" : "Form einfügen";
    $("shape-apply").textContent = editing ? "Änderungen übernehmen" : "In Entwurf einfügen";
    $("shape-duplicate").hidden = !editing;
    $("shape-remove").hidden = !editing;
    $("shape-group-section").hidden = !editing;
    fill(action.attrs || { kind: "rectangle", width: 320, height: 160, fill: "teal", stroke: "slate", strokeWidth: 2, text: "", textAlign: "center", fontSize: null, textColor: null, textStyle: null, rotation: null, position: null, wrap: null });
    updateLayoutControls(); preview(); $("shape-dialog").showModal(); $("shape-kind").focus();
  };
  const updateLayoutControls = () => { const grouped = Boolean(action?.shapeContext?.grouped), positioned = $("shape-position-layer").value !== "flow";
    $("shape-position-layer").disabled = grouped;
    $("shape-wrap").disabled = grouped || positioned; $("shape-wrap-gap").disabled = grouped || positioned || $("shape-wrap").value === "none";
    $("shape-position-x").disabled = grouped || !positioned; $("shape-position-y").disabled = grouped || !positioned;
    $("shape-group-previous").disabled = !groupCandidate(action, "previous");
    $("shape-group-next").disabled = !groupCandidate(action, "next");
    $("shape-group-ungroup").disabled = !grouped;
    $("shape-group-member-previous").disabled = !grouped || action.shapeContext.shapeIndex === 0;
    $("shape-group-member-next").disabled = !grouped || action.shapeContext.shapeIndex === action.shapeContext.group.childCount - 1;
    $("shape-group-remove").disabled = !grouped;
    $("shape-group-duplicate").disabled = !grouped || groupCount(action.document) >= OFFICE_SHAPE_GROUP_LIMIT ||
      count() + (action?.shapeContext?.group?.childCount ?? 0) > OFFICE_SHAPE_LIMIT;
    $("shape-duplicate").disabled = count() >= OFFICE_SHAPE_LIMIT || (grouped && action.shapeContext.group.childCount >= OFFICE_SHAPE_GROUP_MEMBER_LIMIT);
    const connected = $("shape-group-connection").value !== "none";
    $("shape-group-connection-color").disabled = !connected; $("shape-group-connection-width").disabled = !connected; };
  $("shape-options").addEventListener("click", open);
  $("shape-position-layer").addEventListener("input", () => { if ($("shape-position-layer").value !== "flow") $("shape-wrap").value = "none"; updateLayoutControls(); });
  $("shape-wrap").addEventListener("input", updateLayoutControls);
  $("shape-group-connection").addEventListener("input", updateLayoutControls);
  $("shape-form").addEventListener("input", preview);
  $("shape-form").addEventListener("submit", (event) => {
    event.preventDefault(); if (!action || !current(action)) { close(); return; }
    try {
      const attrs = read(), editor = state.editor;
      if (action.editing) {
        const shapeSelection = action.shapeSelection, context = action.shapeContext;
        const groupedAttrs = context?.grouped ? officeShapeAttributes({ ...attrs, position: null, wrap: null }) : attrs;
        const tr = editor.state.tr.setNodeMarkup(shapeSelection.from, undefined, groupedAttrs);
        if (context?.grouped) tr.setNodeMarkup(context.groupPos, undefined, readGroup(context.group.attrs.id));
        validate(tr.doc); editor.view.dispatch(closeHistory(tr).scrollIntoView()); editor.view.dispatch(closeHistory(editor.state.tr));
      } else {
        if (count() >= OFFICE_SHAPE_LIMIT) throw new Error("insert");
        editor.view.dispatch(closeHistory(editor.state.tr));
        if (!editor.chain().focus().insertContent({ type: "shape", attrs }).run()) throw new Error("insert");
        validate(editor.state.doc);
        editor.view.dispatch(closeHistory(editor.state.tr));
      }
      close(); focus(editor); updateEditor();
    } catch { notice("Die Form konnte nicht übernommen werden. Auswahl und Grenzwerte prüfen.", true); }
  });
  $("shape-duplicate").addEventListener("click", () => {
    if (!action || !current(action) || !action.editing || count() >= OFFICE_SHAPE_LIMIT) return;
    const editor = state.editor, context = action.shapeContext;
    if (!context || (context.grouped && context.group.childCount >= OFFICE_SHAPE_GROUP_MEMBER_LIMIT)) return;
    const position = context.shape.attrs.position == null ? null : {
      layer: context.shape.attrs.position.layer,
      x: context.shape.attrs.position.x <= 975 ? context.shape.attrs.position.x + 25 : context.shape.attrs.position.x - 25,
      y: context.shape.attrs.position.y <= 1176 ? context.shape.attrs.position.y + 24 : context.shape.attrs.position.y - 24,
    };
    const attrs = officeShapeAttributes({ ...context.shape.attrs, id: shapeId(), position });
    const duplicate = editor.schema.nodes.shape.create(attrs); let tr = editor.state.tr;
    if (context.grouped) {
      const members = [...context.group.content.content]; members.splice(context.shapeIndex + 1, 0, duplicate);
      tr = tr.replaceWith(context.groupPos, context.groupPos + context.group.nodeSize,
        editor.schema.nodes.shapeGroup.create(context.group.attrs, members));
      const offset = 1 + members.slice(0, context.shapeIndex + 1).reduce((total, node) => total + node.nodeSize, 0);
      tr.setSelection(NodeSelection.create(tr.doc, context.groupPos + offset));
    } else {
      const insertPos = context.shapePos + context.shape.nodeSize;
      tr.insert(insertPos, duplicate).setSelection(NodeSelection.create(tr.doc, insertPos));
    }
    try {
      validate(tr.doc); close(); editor.view.dispatch(closeHistory(tr).scrollIntoView()); editor.view.dispatch(closeHistory(editor.state.tr));
      focus(editor); updateEditor(); notice("Form dupliziert. Die Kopie besitzt eine neue ID und kann mit Rückgängig entfernt werden.");
    } catch { $("shape-status").textContent = "Die Form konnte wegen der Dokument- oder Gruppengrenze nicht dupliziert werden."; }
  });
  $("shape-remove").addEventListener("click", () => {
    if (!action || !current(action) || !selected()) return;
    const editor = state.editor, context = action.shapeContext, tr = editor.state.tr;
    if (context?.grouped) {
      const members = context.group.content.content;
      if (members.length === 2) {
        const remaining = members[context.shapeIndex === 0 ? 1 : 0];
        tr.replaceWith(context.groupPos, context.groupPos + context.group.nodeSize, remaining);
        tr.setSelection(NodeSelection.create(tr.doc, context.groupPos));
      } else {
        tr.delete(context.shapePos, context.shapePos + context.shape.nodeSize);
        tr.setSelection(NodeSelection.create(tr.doc, context.groupPos + 1));
      }
    } else tr.delete(action.shapeSelection.from, action.shapeSelection.to);
    try { validate(tr.doc); editor.view.dispatch(closeHistory(tr).scrollIntoView()); editor.view.dispatch(closeHistory(editor.state.tr)); close(); focus(editor); updateEditor(); }
    catch { notice("Die Form konnte nicht entfernt werden.", true); }
  });
  const group = (direction) => {
    if (!action || !current(action) || !groupCandidate(action, direction)) return;
    const editor = state.editor, context = action.shapeContext, delta = direction === "previous" ? -1 : 1;
    const other = context.root.child(context.rootIndex + delta), tr = editor.state.tr;
    try {
      if (context.grouped) {
        const otherPos = direction === "previous" ? context.groupPos - other.nodeSize : context.groupPos + context.group.nodeSize;
        const members = direction === "previous" ? [other, ...context.group.content.content] : [...context.group.content.content, other];
        const start = Math.min(context.groupPos, otherPos), end = Math.max(context.groupPos + context.group.nodeSize, otherPos + other.nodeSize);
        tr.replaceWith(start, end, editor.schema.nodes.shapeGroup.create(context.group.attrs, members));
        const selectedIndex = context.shapeIndex + (direction === "previous" ? 1 : 0);
        const offset = 1 + members.slice(0, selectedIndex).reduce((total, node) => total + node.nodeSize, 0);
        tr.setSelection(NodeSelection.create(tr.doc, start + offset));
      } else {
        const otherPos = direction === "previous" ? context.shapePos - other.nodeSize : context.shapePos + context.shape.nodeSize;
        const start = Math.min(context.shapePos, otherPos), end = Math.max(context.shapePos + context.shape.nodeSize, otherPos + other.nodeSize);
        let attrs, members, selectedIndex;
        if (other.type.name === "shapeGroup") {
          attrs = other.attrs; members = direction === "previous" ? [...other.content.content, context.shape] : [context.shape, ...other.content.content];
          selectedIndex = direction === "previous" ? members.length - 1 : 0;
        } else {
          attrs = readGroup(shapeGroupId());
          members = direction === "previous" ? [other, context.shape] : [context.shape, other]; selectedIndex = direction === "previous" ? 1 : 0;
        }
        tr.replaceWith(start, end, editor.schema.nodes.shapeGroup.create(officeShapeGroupAttributes(attrs), members));
        const offset = 1 + members.slice(0, selectedIndex).reduce((total, node) => total + node.nodeSize, 0);
        tr.setSelection(NodeSelection.create(tr.doc, start + offset));
      }
      validate(tr.doc); close(); editor.view.dispatch(closeHistory(tr).scrollIntoView()); editor.view.dispatch(closeHistory(editor.state.tr));
      focus(editor); updateEditor(); notice("Formgruppe im Entwurf geändert. Mit Rückgängig wiederherstellbar; gespeichert wird erst mit der nächsten bestätigten Version.");
    } catch { $("shape-status").textContent = "Diese Formgruppe ist ungültig oder überschreitet die Dokumentgrenzen."; }
  };
  $("shape-group-previous").addEventListener("click", () => group("previous"));
  $("shape-group-next").addEventListener("click", () => group("next"));
  const reorderMember = (direction) => {
    if (!action || !current(action) || !action.shapeContext?.grouped) return;
    const editor = state.editor, context = action.shapeContext;
    const targetIndex = context.shapeIndex + (direction === "previous" ? -1 : 1);
    if (targetIndex < 0 || targetIndex >= context.group.childCount) return;
    const members = [...context.group.content.content];
    [members[context.shapeIndex], members[targetIndex]] = [members[targetIndex], members[context.shapeIndex]];
    const tr = editor.state.tr.replaceWith(context.groupPos, context.groupPos + context.group.nodeSize,
      editor.schema.nodes.shapeGroup.create(context.group.attrs, members));
    const offset = 1 + members.slice(0, targetIndex).reduce((total, node) => total + node.nodeSize, 0);
    tr.setSelection(NodeSelection.create(tr.doc, context.groupPos + offset));
    try {
      validate(tr.doc); close(); editor.view.dispatch(closeHistory(tr).scrollIntoView()); editor.view.dispatch(closeHistory(editor.state.tr));
      focus(editor); updateEditor(); notice("Form in der Gruppe umgeordnet. Mit Rückgängig wiederherstellbar; gespeichert wird erst mit der nächsten bestätigten Version.");
    } catch { $("shape-status").textContent = "Die Form konnte in dieser Gruppe nicht umgeordnet werden."; }
  };
  $("shape-group-member-previous").addEventListener("click", () => reorderMember("previous"));
  $("shape-group-member-next").addEventListener("click", () => reorderMember("next"));
  $("shape-group-duplicate").addEventListener("click", () => {
    if (!action || !current(action) || !action.shapeContext?.grouped) return;
    const editor = state.editor, context = action.shapeContext;
    if (groupCount(editor.state.doc) >= OFFICE_SHAPE_GROUP_LIMIT || count() + context.group.childCount > OFFICE_SHAPE_LIMIT) return;
    const members = context.group.content.content.map((member) =>
      editor.schema.nodes.shape.create(officeShapeAttributes({ ...member.attrs, id: shapeId() })));
    const attrs = officeShapeGroupAttributes({ ...context.group.attrs, id: shapeGroupId() });
    const duplicate = editor.schema.nodes.shapeGroup.create(attrs, members);
    const insertPos = context.groupPos + context.group.nodeSize;
    const tr = editor.state.tr.insert(insertPos, duplicate);
    tr.setSelection(NodeSelection.create(tr.doc, insertPos));
    try {
      validate(tr.doc); close(); editor.view.dispatch(closeHistory(tr).scrollIntoView()); editor.view.dispatch(closeHistory(editor.state.tr));
      focus(editor); updateEditor(); notice("Formgruppe dupliziert. Gruppe und Mitglieder besitzen neue IDs; mit Rückgängig entfernbar.");
    } catch { $("shape-status").textContent = "Die Formgruppe konnte wegen der Dokumentgrenzen nicht dupliziert werden."; }
  });
  $("shape-group-remove").addEventListener("click", () => {
    if (!action || !current(action) || !action.shapeContext?.grouped) return;
    const editor = state.editor, context = action.shapeContext;
    const tr = editor.state.tr.delete(context.groupPos, context.groupPos + context.group.nodeSize);
    try {
      validate(tr.doc); close(); editor.view.dispatch(closeHistory(tr).scrollIntoView()); editor.view.dispatch(closeHistory(editor.state.tr));
      focus(editor); updateEditor(); notice("Formgruppe aus dem Entwurf entfernt. Mit Rückgängig vollständig wiederherstellbar; gespeichert wird erst mit der nächsten bestätigten Version.");
    } catch { $("shape-status").textContent = "Die Formgruppe konnte nicht entfernt werden."; }
  });
  $("shape-group-ungroup").addEventListener("click", () => {
    if (!action || !current(action) || !action.shapeContext?.grouped) return;
    const editor = state.editor, context = action.shapeContext, members = context.group.content.content;
    const offset = members.slice(0, context.shapeIndex).reduce((total, node) => total + node.nodeSize, 0);
    const tr = editor.state.tr.replaceWith(context.groupPos, context.groupPos + context.group.nodeSize, members);
    tr.setSelection(NodeSelection.create(tr.doc, context.groupPos + offset));
    try { validate(tr.doc); close(); editor.view.dispatch(closeHistory(tr).scrollIntoView()); editor.view.dispatch(closeHistory(editor.state.tr)); focus(editor); updateEditor(); }
    catch { $("shape-status").textContent = "Die Formgruppe konnte nicht aufgelöst werden."; }
  });
  for (const id of ["shape-close", "shape-cancel"]) $(id).addEventListener("click", () => close(true));
  $("shape-dialog").addEventListener("cancel", (event) => { event.preventDefault(); close(true); });
  const update = () => { $("shape-options").disabled = !allowed() || (!selected() && count() >= OFFICE_SHAPE_LIMIT); $("shape-options").textContent = selected() ? "Form bearbeiten …" : "Form einfügen …"; };
  return { update, close };
}
