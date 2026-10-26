import { Node } from "@tiptap/core";
import { NodeSelection } from "@tiptap/pm/state";
import { closeHistory } from "@tiptap/pm/history";
import { OFFICE_CHART_COLORS, OFFICE_CHART_LIMIT, officeChartAttributes, officeChartDataFromDocument, officeChartElement } from "./office-charts.mjs";
import { officeTableGrid, officeTableInventory } from "./office-tables.mjs";

export function officeChartExtension(onEdit) {
  return Node.create({
    name: "chart", group: "block", atom: true, selectable: true, draggable: false,
    addAttributes: () => Object.fromEntries(["id", "kind", "title", "altText", "legend", "legendPosition", "dataLabels",
      "dataLabelPresentation", "referenceLines", "axes", "presentation", "seriesPresentation", "categories", "series", "source"]
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
  if (width < 2 || width > 5 || cells.some((row) => row.length !== width) ||
      (["pie", "doughnut"].includes(kind) && width !== 2) || (["scatter", "combo"].includes(kind) && width < 3)) {
    throw new Error("chart-data");
  }
  const categories = cells.slice(1).map((row) => row[0]);
  const series = cells[0].slice(1).map((name, seriesIndex) => ({ name, color: OFFICE_CHART_COLORS[seriesIndex],
    values: cells.slice(1).map((row) => { if (!/^-?(?:0|[1-9][0-9]{0,9})(?:[.,][0-9]{1,10})?$/.test(row[seriesIndex + 1])) throw new Error("chart-value");
      const number = Number(row[seriesIndex + 1].replace(",", "."));
      if (!Number.isFinite(number) || number < -1000000000 || number > 1000000000) throw new Error("chart-value"); return number; }) }));
  return { categories, series };
}

function serializeData(chart) {
  return [["Kategorie", ...chart.series.map((entry) => entry.name)].join("\t"),
    ...chart.categories.map((category, index) => [category, ...chart.series.map((entry) => entry.values[index])].join("\t"))].join("\n");
}

export function installOfficeChartControls({ state, $, sessionCurrent, validate, update, notice, focus }) {
  let action = null;
  const circular = (kind) => ["pie", "doughnut"].includes(kind);
  const styled = (kind) => ["line", "area", "scatter", "combo"].includes(kind);
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
  const tableNode = (tableId) => {
    let found = null;
    const walk = (node) => { if (found) return; if (node.type === "table" && node.attrs?.tableId === tableId) { found = node; return; }
      for (const child of node.content || []) walk(child); };
    walk(action.editor.getJSON()); return found;
  };
  const defaultRange = (tableId, kind, orientation = "columns") => {
    const table = tableNode(tableId); if (!table) return "A1:C5"; const grid = officeTableGrid(table);
    const columns = Math.min(grid.columns, orientation === "rows" ? 5 : circular(kind) ? 2 : 3),
      rows = Math.min(grid.rows, orientation === "rows" ? circular(kind) ? 2 : 3 : 5);
    return columns >= 2 && rows >= 2 ? `A1:${String.fromCharCode(64 + columns)}${rows}` : "A1:B2";
  };
  const source = () => ({ tableId: $("chart-source-table").value, range: $("chart-source-range").value.trim().toUpperCase(),
    orientation: $("chart-source-orientation").value });
  const defaultSeriesStyle = (kind, index) => kind === "combo" && index === 0 ?
    { renderAs: "bar", marker: "none", lineStyle: "none" } : kind === "scatter" ?
      { renderAs: "points", marker: "circle", lineStyle: "none" } :
      { renderAs: "line", marker: "circle", lineStyle: "solid" };
  const seriesStyleRows = () => [...$("chart-series-presentation").querySelectorAll(".chart-series-presentation-row")];
  const readSeriesStyleRows = () => seriesStyleRows().map((row) => ({
    renderAs: row.querySelector('[data-field="renderAs"]').value,
    marker: row.querySelector('[data-field="marker"]').value,
    lineStyle: row.querySelector('[data-field="lineStyle"]').value,
  }));
  const normalizeSeriesStyle = (kind, index, value) => {
    if (kind === "line" || kind === "area") return { renderAs: "line", marker: value?.marker || "circle",
      lineStyle: ["solid", "dashed"].includes(value?.lineStyle) ? value.lineStyle : "solid" };
    if (kind === "scatter") return { renderAs: "points", marker: ["circle", "square", "diamond"].includes(value?.marker) ?
      value.marker : "circle", lineStyle: ["none", "solid", "dashed"].includes(value?.lineStyle) ? value.lineStyle : "none" };
    const renderAs = ["bar", "line"].includes(value?.renderAs) ? value.renderAs : index === 0 ? "bar" : "line";
    return renderAs === "bar" ? { renderAs, marker: "none", lineStyle: "none" } :
      { renderAs, marker: value?.marker || "circle", lineStyle: ["solid", "dashed"].includes(value?.lineStyle) ? value.lineStyle : "solid" };
  };
  const seriesSelect = (field, values, selected, disabled = false) => {
    const select = document.createElement("select"); select.dataset.field = field; select.disabled = disabled;
    select.replaceChildren(...values.map(([value, label]) => { const option = document.createElement("option");
      option.value = value; option.textContent = label; option.selected = value === selected; return option; })); return select;
  };
  const renderReferenceLines = (entries = []) => {
    const rows = entries.map((entry, index) => {
      const row = document.createElement("div"); row.className = "chart-reference-row";
      const label = document.createElement("label"), labelInput = document.createElement("input");
      labelInput.dataset.field = "label"; labelInput.maxLength = 60; labelInput.value = entry.label || `Ziel ${index + 1}`;
      label.append("Bezeichnung", labelInput);
      const value = document.createElement("label"), valueInput = document.createElement("input");
      valueInput.dataset.field = "value"; valueInput.type = "number"; valueInput.step = "any";
      valueInput.min = "-1000000000"; valueInput.max = "1000000000"; valueInput.value = String(entry.value ?? 0);
      value.append("Wert", valueInput);
      const color = document.createElement("label"); color.append("Farbe", seriesSelect("color",
        [["teal", "Türkis"], ["blue", "Blau"], ["orange", "Orange"], ["purple", "Violett"]], entry.color || "orange"));
      const line = document.createElement("label"); line.append("Linie", seriesSelect("lineStyle",
        [["solid", "Durchgezogen"], ["dashed", "Gestrichelt"]], entry.lineStyle || "dashed"));
      const remove = document.createElement("button"); remove.type = "button"; remove.className = "button secondary";
      remove.dataset.action = "remove-reference"; remove.textContent = "Entfernen"; row.append(label, value, color, line, remove);
      return row;
    });
    $("chart-reference-lines").replaceChildren(...rows); $("chart-reference-add").disabled = rows.length >= 4;
  };
  const referenceLines = () => [...$("chart-reference-lines").querySelectorAll(".chart-reference-row")].map((row) => ({
    label: row.querySelector('[data-field="label"]').value,
    value: Number(row.querySelector('[data-field="value"]').value),
    color: row.querySelector('[data-field="color"]').value,
    lineStyle: row.querySelector('[data-field="lineStyle"]').value,
  }));
  const seriesPresentation = (kind, series) => {
    const fieldset = $("chart-series-presentation-fields"), container = $("chart-series-presentation");
    fieldset.hidden = !styled(kind); if (!styled(kind)) { container.replaceChildren(); return null; }
    const visibleSeries = kind === "scatter" ? series.slice(1) : series;
    const currentRows = seriesStyleRows(), same = container.dataset.kind === kind && currentRows.length === visibleSeries.length &&
      currentRows.every((row, index) => row.dataset.seriesName === visibleSeries[index].name);
    const previous = action?.seriesPresentationSeed || (currentRows.length ? readSeriesStyleRows() : []);
    if (!same || action?.seriesPresentationSeed) {
      const rows = visibleSeries.map((entry, index) => {
        const style = normalizeSeriesStyle(kind, index, previous[index] || defaultSeriesStyle(kind, index));
        const row = document.createElement("div"); row.className = "chart-series-presentation-row"; row.dataset.seriesName = entry.name;
        const name = document.createElement("strong"); name.textContent = entry.name;
        const renderer = document.createElement("label"); renderer.append("Typ", seriesSelect("renderAs",
          [["bar", "Säule"], ["line", "Linie"], ["points", "Punkte"]], style.renderAs, kind !== "combo"));
        const marker = document.createElement("label"); marker.append("Marker", seriesSelect("marker",
          [["none", "Ohne"], ["circle", "Kreis"], ["square", "Quadrat"], ["diamond", "Raute"]], style.marker));
        const line = document.createElement("label"); line.append("Linie", seriesSelect("lineStyle",
          [["none", "Ohne"], ["solid", "Durchgezogen"], ["dashed", "Gestrichelt"]], style.lineStyle));
        row.append(name, renderer, marker, line); return row;
      });
      container.replaceChildren(...rows); container.dataset.kind = kind; if (action) action.seriesPresentationSeed = null;
    }
    const result = readSeriesStyleRows().map((entry, index) => normalizeSeriesStyle(kind, index, entry));
    seriesStyleRows().forEach((row, index) => { const style = result[index];
      row.querySelector('[data-field="renderAs"]').value = style.renderAs;
      row.querySelector('[data-field="marker"]').value = style.marker;
      row.querySelector('[data-field="lineStyle"]').value = style.lineStyle; });
    return result;
  };
  const read = (id = action?.attrs?.id || action?.id || (action.id = identifier())) => {
    const kind = $("chart-kind").value, linked = $("chart-linked").checked, binding = linked ? source() : null;
    const data = linked ? officeChartDataFromDocument(action.editor.getJSON(), binding, kind) : parseData($("chart-data").value, kind);
    const mode = $("chart-axis-mode").value;
    const axes = circular(kind) ? null : { mode, categoryTitle: $("chart-category-axis-title").value,
      valueTitle: $("chart-value-axis-title").value,
      minimum: mode === "manual" ? Number($("chart-axis-minimum").value) : null,
      maximum: mode === "manual" ? Number($("chart-axis-maximum").value) : null,
      majorUnit: mode === "manual" ? Number($("chart-axis-major-unit").value) : null,
      gridlines: $("chart-gridlines").checked, numberFormat: $("chart-number-format").value };
    const presentation = { palette: $("chart-palette").value, style: $("chart-style").value,
      titleAlignment: $("chart-title-alignment").value };
    const seriesStyles = seriesPresentation(kind, data.series);
    const references = circular(kind) ? [] : referenceLines();
    const labelPresentation = $("chart-data-labels").checked ? { content: $("chart-data-label-content").value,
      position: $("chart-data-label-position").value } : null;
    return officeChartAttributes({ id, kind, title: $("chart-name").value, altText: $("chart-alt").value,
      legend: $("chart-legend").checked, legendPosition: $("chart-legend-position").value,
      dataLabels: $("chart-data-labels").checked, presentation, ...data, ...(seriesStyles ? { seriesPresentation: seriesStyles } : {}),
      ...(labelPresentation ? { dataLabelPresentation: labelPresentation } : {}),
      ...(references.length ? { referenceLines: references } : {}), ...(axes ? { axes } : {}), ...(binding ? { source: binding } : {}) });
  };
  const close = (restore = false) => { const owner = action; action = null; if ($("chart-dialog").open) $("chart-dialog").close();
    $("chart-form").reset(); $("chart-preview").replaceChildren(); $("chart-reference-lines").replaceChildren();
    $("chart-status").textContent = "";
    if (restore && owner?.editor === state.editor) focus(owner.editor); };
  const updateButtons = () => {
    const editing = Boolean(action?.editing); $("chart-duplicate").hidden = !editing; $("chart-remove").hidden = !editing;
    $("chart-previous").hidden = !editing; $("chart-next").hidden = !editing;
    $("chart-duplicate").disabled = !editing || count() >= OFFICE_CHART_LIMIT;
    $("chart-previous").disabled = !editing || action.rootIndex === 0;
    $("chart-next").disabled = !editing || action.rootIndex >= action.editor.state.doc.childCount - 1;
  };
  const sourceState = () => { const linked = $("chart-linked").checked;
    $("chart-source-fields").hidden = !linked; $("chart-source-table").disabled = !linked; $("chart-source-range").disabled = !linked;
    $("chart-source-orientation").disabled = !linked;
    $("chart-data").readOnly = linked; };
  const presentationState = () => { const axes = !circular($("chart-kind").value), manual = $("chart-axis-mode").value === "manual";
    $("chart-axis-fields").disabled = !axes; $("chart-manual-axis-fields").hidden = !axes || !manual;
    $("chart-reference-fields").hidden = !axes; $("chart-reference-fields").disabled = !axes;
    $("chart-data-label-fields").hidden = !$("chart-data-labels").checked;
    $("chart-data-label-content").disabled = !$("chart-data-labels").checked;
    $("chart-data-label-position").disabled = !$("chart-data-labels").checked;
    $("chart-legend-position").disabled = !$("chart-legend").checked; };
  const preview = () => { sourceState(); presentationState(); try { const attrs = read(); if (attrs.source) $("chart-data").value = serializeData(attrs);
      $("chart-preview").replaceChildren(officeChartElement(attrs));
      $("chart-status").textContent = "Vorschau und zugängliche Datentabelle sind aktuell."; $("chart-apply").disabled = false; }
    catch { $("chart-preview").replaceChildren(); $("chart-status").textContent = $("chart-linked").checked ?
      "Nummerierte Quelltabelle und Bereich prüfen. Erste Zeile und Spalte müssen eindeutige Beschriftungen enthalten." :
      "Titel, Alternativtext und Tabellendaten prüfen.";
      $("chart-apply").disabled = true; } };
  const open = () => {
    if (!allowed()) return; const selection = selected(), editing = Boolean(selection);
    if (!editing && count() >= OFFICE_CHART_LIMIT) return;
    const attrs = editing ? officeChartAttributes(selection.node.attrs) : null;
    action = { session: state.session, context: state.context, revision: state.session.revision, editor: state.editor,
      editing, position: editing ? selection.from : null, attrs, rootIndex: null,
      seriesPresentationSeed: attrs?.seriesPresentation || null };
    if (editing) { let index = 0; state.editor.state.doc.forEach((_node, offset) => { if (offset === action.position) action.rootIndex = index; index += 1; }); }
    const tables = officeTableInventory(state.editor.getJSON()); $("chart-source-table").replaceChildren(...tables.map((entry) => {
      const option = document.createElement("option"); option.value = entry.id; option.textContent = entry.label; return option; }));
    $("chart-title").textContent = editing ? "Diagramm bearbeiten" : "Diagramm einfügen";
    $("chart-kind").value = attrs?.kind || "bar"; $("chart-name").value = attrs?.title || "Quartalsübersicht";
    $("chart-alt").value = attrs?.altText || "Vergleich der Werte nach Kategorie."; $("chart-legend").checked = attrs?.legend ?? true;
    $("chart-legend-position").value = attrs?.legendPosition || "bottom";
    $("chart-data-labels").checked = attrs?.dataLabels ?? false;
    $("chart-data-label-content").value = attrs?.dataLabelPresentation?.content || "full";
    $("chart-data-label-position").value = attrs?.dataLabelPresentation?.position || "below";
    $("chart-palette").value = attrs?.presentation?.palette || "standard";
    $("chart-style").value = attrs?.presentation?.style || "clean";
    $("chart-title-alignment").value = attrs?.presentation?.titleAlignment || "center";
    $("chart-category-axis-title").value = attrs?.axes?.categoryTitle || "";
    $("chart-value-axis-title").value = attrs?.axes?.valueTitle || "";
    $("chart-number-format").value = attrs?.axes?.numberFormat || "general";
    $("chart-axis-mode").value = attrs?.axes?.mode || "auto";
    $("chart-axis-minimum").value = attrs?.axes?.minimum ?? "0";
    $("chart-axis-maximum").value = attrs?.axes?.maximum ?? "200";
    $("chart-axis-major-unit").value = attrs?.axes?.majorUnit ?? "50";
    $("chart-gridlines").checked = attrs?.axes?.gridlines ?? true;
    renderReferenceLines(attrs?.referenceLines || []);
    $("chart-linked").checked = Boolean(attrs?.source); $("chart-linked").disabled = !tables.length && !attrs?.source;
    if (attrs?.source) { $("chart-source-table").value = attrs.source.tableId; $("chart-source-range").value = attrs.source.range;
      $("chart-source-orientation").value = attrs.source.orientation || "columns"; }
    else if (tables.length) { $("chart-source-table").value = tables[0].id;
      $("chart-source-orientation").value = "columns";
      $("chart-source-range").value = defaultRange(tables[0].id, $("chart-kind").value, "columns"); }
    $("chart-data").value = attrs ? serializeData(attrs) : "Kategorie\tPlan\tIst\nQ1\t120\t110\nQ2\t140\t152\nQ3\t160\t171\nQ4\t180\t176";
    updateButtons(); $("chart-dialog").showModal(); preview(); $("chart-kind").focus();
  };
  const dispatch = (transaction, message) => { validate(transaction.doc); close(); state.editor.view.dispatch(closeHistory(transaction).scrollIntoView());
    state.editor.view.dispatch(closeHistory(state.editor.state.tr)); focus(state.editor); update(); notice(message); };
  $("chart-options").addEventListener("click", open); $("chart-form").addEventListener("input", preview);
  $("chart-reference-add").addEventListener("click", () => { const entries = referenceLines();
    if (entries.length < 4) { entries.push({ label: `Ziel ${entries.length + 1}`, value: 0, color: "orange", lineStyle: "dashed" });
      renderReferenceLines(entries); preview(); } });
  $("chart-reference-lines").addEventListener("click", (event) => { const button = event.target.closest('[data-action="remove-reference"]');
    if (!button) return; const rows = [...$("chart-reference-lines").children], index = rows.indexOf(button.closest(".chart-reference-row"));
    const entries = referenceLines(); entries.splice(index, 1); renderReferenceLines(entries); preview(); });
  $("chart-linked").addEventListener("change", () => { if ($("chart-linked").checked && $("chart-source-table").value) {
    $("chart-source-range").value = defaultRange($("chart-source-table").value, $("chart-kind").value,
      $("chart-source-orientation").value); } preview(); });
  $("chart-source-table").addEventListener("change", () => { $("chart-source-range").value =
    defaultRange($("chart-source-table").value, $("chart-kind").value, $("chart-source-orientation").value); preview(); });
  $("chart-source-orientation").addEventListener("change", () => { $("chart-source-range").value =
    defaultRange($("chart-source-table").value, $("chart-kind").value, $("chart-source-orientation").value); preview(); });
  $("chart-kind").addEventListener("change", () => { if ($("chart-linked").checked && $("chart-source-table").value) {
    $("chart-source-range").value = defaultRange($("chart-source-table").value, $("chart-kind").value,
      $("chart-source-orientation").value); } preview(); });
  $("chart-form").addEventListener("submit", (event) => { event.preventDefault(); if (!current()) { close(); return; }
    try { const attrs = read(), node = action.editor.schema.nodes.chart.create(attrs);
      const transaction = action.editing ? action.editor.state.tr.setNodeMarkup(action.position, undefined, attrs) : action.editor.state.tr.replaceSelectionWith(node, false);
      dispatch(transaction, action.editing ? "Diagramm aktualisiert." : attrs.source ?
        "Mit Tabelle verknüpftes Diagramm in den Entwurf eingefügt." : "Diagramm in den Entwurf eingefügt."); }
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
