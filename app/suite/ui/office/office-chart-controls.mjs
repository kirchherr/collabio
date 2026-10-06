import { Node } from "@tiptap/core";
import { NodeSelection } from "@tiptap/pm/state";
import { closeHistory } from "@tiptap/pm/history";
import { OFFICE_CHART_COLORS, OFFICE_CHART_LIMIT, officeChartAttributes, officeChartElement } from "./office-charts.mjs";

export function officeChartExtension(onEdit) {
  return Node.create({
    name: "chart", group: "block", atom: true, selectable: true, draggable: false,
    addAttributes: () => Object.fromEntries(["id", "kind", "title", "altText", "legend", "categories", "series"]
      .map((key) => [key, { default: null, rendered: false }])),
    parseHTML: () => [], renderHTML: ({ node }) => ["figure", { class: "office-chart" }, node.attrs.title || "Diagramm"],
    addNodeView() {
      return ({ node: initial, editor, getPos }) => {
        let current = initial; const dom = document.createElement("div"); dom.className = "office-chart-node";
        const paint = () => {
          const chart = officeChartElement(current.attrs), edit = document.createElement("button");
          edit.type = "button"; edit.className = "office-chart-edit"; edit.textContent = "Diagramm bearbeiten";
          edit.addEventListener("click", () => { const position = getPos(); if (!Number.isInteger(position)) return;
            editor.view.dispatch(editor.state.tr.setSelection(NodeSelection.create(editor.state.doc, position))); onEdit(); });
          dom.replaceChildren(chart, edit);
        };
        paint();
        return { dom, update(next) { if (next.type !== current.type) return false; current = next; paint(); return true; },
          selectNode() { dom.classList.add("ProseMirror-selectednode"); },
          deselectNode() { dom.classList.remove("ProseMirror-selectednode"); }, ignoreMutation: () => true };
      };
    },
  });
}

function parseData(text, kind) {
  const rows = text.replaceAll("\r", "").split("\n").filter((row) => row.length);
  if (rows.length < 2 || rows.length > 13) throw new Error("chart-data");
  const cells = rows.map((row) => row.split("\t"));
  const width = cells[0].length;
  if (width < 2 || width > 5 || cells.some((row) => row.length !== width) || (kind === "pie" && width !== 2)) throw new Error("chart-data");
  const categories = cells.slice(1).map((row) => row[0]);
  const series = cells[0].slice(1).map((name, seriesIndex) => ({ name, color: OFFICE_CHART_COLORS[seriesIndex],
    values: cells.slice(1).map((row) => { if (!/^-?(?:0|[1-9][0-9]{0,9})$/.test(row[seriesIndex + 1])) throw new Error("chart-value");
      const number = Number(row[seriesIndex + 1]); if (!Number.isSafeInteger(number)) throw new Error("chart-value"); return number; }) }));
  return { categories, series };
}

function serializeData(chart) {
  return [["Kategorie", ...chart.series.map((entry) => entry.name)].join("\t"),
    ...chart.categories.map((category, index) => [category, ...chart.series.map((entry) => entry.values[index])].join("\t"))].join("\n");
}

export function installOfficeChartControls({ state, $, sessionCurrent, validate, update, notice, focus }) {
  let action = null;
  const selected = () => state.editor?.state.selection instanceof NodeSelection && state.editor.state.selection.node.type.name === "chart" ? state.editor.state.selection : null;
  const count = () => { let total = 0; state.editor?.state.doc.forEach((node) => { if (node.type.name === "chart") total += 1; }); return total; };
  const allowed = () => Boolean(state.session && sessionCurrent(state.session) && state.editor?.isEditable && !state.session.historical &&
    !state.session.loading && !state.session.saving);
  const current = () => Boolean(action && state.session === action.session && state.editor === action.editor &&
    state.context === action.context && action.session.revision === action.revision && $("chart-dialog").open &&
    (!action.editing || (() => { const node = action.editor.state.doc.nodeAt(action.position);
      return node?.type.name === "chart" && node.attrs.id === action.attrs.id; })()));
  const identifier = () => { const bytes = new Uint8Array(12); crypto.getRandomValues(bytes);
    return `chart-${Array.from(bytes, (byte) => byte.toString(16).padStart(2, "0")).join("")}`; };
  const read = (id = action?.attrs?.id || action?.id || (action.id = identifier())) => {
    const kind = $("chart-kind").value, data = parseData($("chart-data").value, kind);
    return officeChartAttributes({ id, kind, title: $("chart-name").value, altText: $("chart-alt").value,
      legend: $("chart-legend").checked, ...data });
  };
  const close = (restore = false) => { const owner = action; action = null; if ($("chart-dialog").open) $("chart-dialog").close();
    $("chart-form").reset(); $("chart-preview").replaceChildren(); $("chart-status").textContent = "";
    if (restore && owner?.editor === state.editor) focus(owner.editor); };
  const updateButtons = () => {
    const editing = Boolean(action?.editing); $("chart-duplicate").hidden = !editing; $("chart-remove").hidden = !editing;
    $("chart-previous").hidden = !editing; $("chart-next").hidden = !editing;
    $("chart-duplicate").disabled = !editing || count() >= OFFICE_CHART_LIMIT;
    $("chart-previous").disabled = !editing || action.rootIndex === 0;
    $("chart-next").disabled = !editing || action.rootIndex >= action.editor.state.doc.childCount - 1;
  };
  const preview = () => { try { const attrs = read(); $("chart-preview").replaceChildren(officeChartElement(attrs));
      $("chart-status").textContent = "Vorschau und zugängliche Datentabelle sind aktuell."; $("chart-apply").disabled = false; }
    catch { $("chart-preview").replaceChildren(); $("chart-status").textContent = "Titel, Alternativtext und Tabellendaten prüfen.";
      $("chart-apply").disabled = true; } };
  const open = () => {
    if (!allowed()) return; const selection = selected(), editing = Boolean(selection);
    if (!editing && count() >= OFFICE_CHART_LIMIT) return;
    const attrs = editing ? officeChartAttributes(selection.node.attrs) : null;
    action = { session: state.session, context: state.context, revision: state.session.revision, editor: state.editor,
      editing, position: editing ? selection.from : null, attrs, rootIndex: null };
    if (editing) { let index = 0; state.editor.state.doc.forEach((_node, offset) => { if (offset === action.position) action.rootIndex = index; index += 1; }); }
    $("chart-title").textContent = editing ? "Diagramm bearbeiten" : "Diagramm einfügen";
    $("chart-kind").value = attrs?.kind || "bar"; $("chart-name").value = attrs?.title || "Quartalsübersicht";
    $("chart-alt").value = attrs?.altText || "Vergleich der Werte nach Kategorie."; $("chart-legend").checked = attrs?.legend ?? true;
    $("chart-data").value = attrs ? serializeData(attrs) : "Kategorie\tPlan\tIst\nQ1\t120\t110\nQ2\t140\t152\nQ3\t160\t171\nQ4\t180\t176";
    updateButtons(); $("chart-dialog").showModal(); preview(); $("chart-kind").focus();
  };
  const dispatch = (transaction, message) => { validate(transaction.doc); close(); state.editor.view.dispatch(closeHistory(transaction).scrollIntoView());
    state.editor.view.dispatch(closeHistory(state.editor.state.tr)); focus(state.editor); update(); notice(message); };
  $("chart-options").addEventListener("click", open); $("chart-form").addEventListener("input", preview);
  $("chart-form").addEventListener("submit", (event) => { event.preventDefault(); if (!current()) { close(); return; }
    try { const attrs = read(), node = action.editor.schema.nodes.chart.create(attrs);
      const transaction = action.editing ? action.editor.state.tr.setNodeMarkup(action.position, undefined, attrs) : action.editor.state.tr.replaceSelectionWith(node, false);
      dispatch(transaction, action.editing ? "Diagramm aktualisiert." : "Inertes Diagramm in den Entwurf eingefügt."); }
    catch { $("chart-status").textContent = "Das Diagramm konnte nicht übernommen werden."; } });
  $("chart-duplicate").addEventListener("click", () => { if (!current() || !action.editing || count() >= OFFICE_CHART_LIMIT) return;
    try { const source = officeChartAttributes(action.editor.state.doc.nodeAt(action.position).attrs);
      const copy = action.editor.schema.nodes.chart.create({ ...source, id: identifier() }), at = action.position + action.editor.state.doc.nodeAt(action.position).nodeSize;
      const transaction = action.editor.state.tr.insert(at, copy); transaction.setSelection(NodeSelection.create(transaction.doc, at));
      dispatch(transaction, "Diagramm mit neuer ID dupliziert."); } catch { $("chart-status").textContent = "Das Diagramm konnte nicht dupliziert werden."; } });
  const move = (direction) => { if (!current() || !action.editing) return; const target = action.rootIndex + (direction === "previous" ? -1 : 1);
    if (target < 0 || target >= action.editor.state.doc.childCount) return; const chart = action.editor.state.doc.child(action.rootIndex), other = action.editor.state.doc.child(target);
    const start = direction === "previous" ? action.position - other.nodeSize : action.position;
    const end = direction === "previous" ? action.position + chart.nodeSize : action.position + chart.nodeSize + other.nodeSize;
    const content = direction === "previous" ? [chart, other] : [other, chart], next = direction === "previous" ? start : action.position + other.nodeSize;
    try { const transaction = action.editor.state.tr.replaceWith(start, end, content); transaction.setSelection(NodeSelection.create(transaction.doc, next));
      dispatch(transaction, "Diagramm im Dokument verschoben."); } catch { $("chart-status").textContent = "Das Diagramm konnte nicht verschoben werden."; } };
  $("chart-previous").addEventListener("click", () => move("previous")); $("chart-next").addEventListener("click", () => move("next"));
  $("chart-remove").addEventListener("click", () => { if (!current() || !action.editing) return; const node = action.editor.state.doc.nodeAt(action.position);
    try { dispatch(action.editor.state.tr.delete(action.position, action.position + node.nodeSize), "Diagramm aus dem Entwurf entfernt."); }
    catch { $("chart-status").textContent = "Das Diagramm konnte nicht entfernt werden."; } });
  for (const id of ["chart-close", "chart-cancel"]) $(id).addEventListener("click", () => close(true));
  $("chart-dialog").addEventListener("cancel", (event) => { event.preventDefault(); close(true); });
  const updateControl = () => { $("chart-options").disabled = !allowed() || (!selected() && count() >= OFFICE_CHART_LIMIT);
    $("chart-options").textContent = selected() ? "Diagramm bearbeiten …" : "Diagramm einfügen …"; };
  return { open, close, update: updateControl };
}
