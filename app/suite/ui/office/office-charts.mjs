import { officeTableAttributes, officeTableCellAttributes, officeTableCellText, officeTableGrid } from "./office-tables.mjs";

export const OFFICE_CHART_LIMIT = 20;
export const OFFICE_CHART_KINDS = ["bar", "line", "pie"];
export const OFFICE_CHART_COLORS = ["teal", "blue", "orange", "purple"];

const colorValues = { teal: "#0f766e", blue: "#2563eb", orange: "#ea580c", purple: "#7e22ce" };
const kindLabels = { bar: "Säulendiagramm", line: "Liniendiagramm", pie: "Kreisdiagramm" };
const chartRange = /^([A-T])([1-9][0-9]{0,2}):([A-T])([1-9][0-9]{0,2})$/u;
const chartNumber = /^-?(?:0|[1-9][0-9]*)(?:[.,][0-9]{1,10})?$/u;

function literal(value, minimum, maximum) {
  return typeof value === "string" && value.length >= minimum && value.length <= maximum && value === value.trim() &&
    ![...value].some((character) => character.codePointAt(0) < 32 ||
      (character.codePointAt(0) >= 127 && character.codePointAt(0) <= 159) ||
      (character.codePointAt(0) >= 0xd800 && character.codePointAt(0) <= 0xdfff) || ["\u2028", "\u2029"].includes(character));
}

export function officeChartAttributes(value) {
  const baseKeys = ["altText", "categories", "id", "kind", "legend", "series", "title"];
  const keys = [...baseKeys, ...(value?.source == null ? [] : ["source"]),
    ...(value?.dataLabels == null ? [] : ["dataLabels"])];
  const actualKeys = Object.keys(value || {}).filter((key) => !["source", "dataLabels"].includes(key) || value[key] != null);
  if (!value || actualKeys.sort().join(",") !== keys.sort().join(",") ||
      !/^chart-[a-f0-9]{24}$/.test(value.id) || !OFFICE_CHART_KINDS.includes(value.kind) ||
      !literal(value.title, 1, 120) || !literal(value.altText, 1, 500) || typeof value.legend !== "boolean" ||
      (value.dataLabels != null && typeof value.dataLabels !== "boolean") ||
      !Array.isArray(value.categories) || value.categories.length < 1 || value.categories.length > 12 ||
      value.categories.some((category) => !literal(category, 1, 60)) || new Set(value.categories).size !== value.categories.length ||
      !Array.isArray(value.series) || value.series.length < 1 || value.series.length > 4 ||
      (value.kind === "pie" && value.series.length !== 1)) throw new Error("chart-attributes");
  const series = value.series.map((entry) => {
    if (!entry || Object.keys(entry).sort().join(",") !== "color,name,values" || !literal(entry.name, 1, 60) ||
        !OFFICE_CHART_COLORS.includes(entry.color) || !Array.isArray(entry.values) ||
        entry.values.length !== value.categories.length || entry.values.some((number) => typeof number !== "number" ||
          !Number.isFinite(number) || number < -1000000000 || number > 1000000000) ||
        (value.kind !== "line" && entry.values.some((number) => number < 0))) {
      throw new Error("chart-series");
    }
    return { name: entry.name, color: entry.color, values: [...entry.values] };
  });
  if (new Set(series.map((entry) => entry.name)).size !== series.length ||
      new Set(series.map((entry) => entry.color)).size !== series.length ||
      (value.kind === "pie" && !series[0].values.some((number) => number > 0))) throw new Error("chart-series");
  const result = { id: value.id, kind: value.kind, title: value.title, altText: value.altText, legend: value.legend,
    categories: [...value.categories], series };
  if (value.dataLabels != null) result.dataLabels = value.dataLabels;
  if (value.source != null) result.source = officeChartSource(value.source);
  return result;
}

export function officeChartSource(value) {
  const keys = Object.keys(value || {}).sort().join(",");
  if (!value || !["range,tableId", "orientation,range,tableId"].includes(keys) ||
      !/^table-[a-f0-9]{24}$/u.test(value.tableId) || typeof value.range !== "string") {
    throw new Error("chart-source");
  }
  const match = chartRange.exec(value.range);
  if (!match) throw new Error("chart-source");
  const left = match[1].charCodeAt(0) - 65, top = Number(match[2]) - 1;
  const right = match[3].charCodeAt(0) - 64, bottom = Number(match[4]);
  const orientation = value.orientation || "columns";
  if (!["columns", "rows"].includes(orientation) || right - left < 2 || bottom - top < 2 ||
      (orientation === "columns" ? right - left > 5 || bottom - top > 13 : right - left > 13 || bottom - top > 5)) {
    throw new Error("chart-source");
  }
  return { tableId: value.tableId, range: value.range, ...(value.orientation == null ? {} : { orientation }) };
}

function sourceTable(document, tableId) {
  let found = null;
  const walk = (node) => {
    if (found || !node || typeof node !== "object") return;
    if (node.type === "table" && officeTableAttributes(node.attrs).tableId === tableId) { found = node; return; }
    for (const child of node.content || []) walk(child);
  };
  walk(document);
  if (!found) throw new Error("chart-source");
  return found;
}

function sourceCellText(cell, numeric = false) {
  const attrs = officeTableCellAttributes(cell.attrs);
  const text = attrs.formula != null ? attrs.formulaResult : officeTableCellText(cell);
  if (numeric) {
    if (!chartNumber.test(text) || text.startsWith("#")) throw new Error("chart-source-value");
    const value = Number(text.replace(",", "."));
    if (!Number.isFinite(value) || value < -1000000000 || value > 1000000000) throw new Error("chart-source-value");
    return value;
  }
  if (!literal(text, 1, 60)) throw new Error("chart-source-label");
  return text;
}

export function officeChartDataFromDocument(document, source, kind) {
  const binding = officeChartSource(source), table = sourceTable(document, binding.tableId), grid = officeTableGrid(table);
  if (table.content.some((row) => row.content.some((cell) => {
    const attrs = officeTableCellAttributes(cell.attrs); return attrs.colspan !== 1 || attrs.rowspan !== 1;
  }))) throw new Error("chart-source-grid");
  const match = chartRange.exec(binding.range), left = match[1].charCodeAt(0) - 65, top = Number(match[2]) - 1;
  const right = match[3].charCodeAt(0) - 64, bottom = Number(match[4]);
  const orientation = binding.orientation || "columns";
  if (right > grid.columns || bottom > grid.rows ||
      (kind === "pie" && (orientation === "columns" ? right - left !== 2 : bottom - top !== 2))) throw new Error("chart-source-range");
  const rows = table.content.slice(top, bottom).map((row) => row.content.slice(left, right));
  const categories = orientation === "columns" ? rows.slice(1).map((row) => sourceCellText(row[0])) :
    rows[0].slice(1).map((cell) => sourceCellText(cell));
  const series = orientation === "columns" ? rows[0].slice(1).map((cell, index) => ({ name: sourceCellText(cell),
    color: OFFICE_CHART_COLORS[index], values: rows.slice(1).map((row) => sourceCellText(row[index + 1], true)) })) :
    rows.slice(1).map((row, index) => ({ name: sourceCellText(row[0]), color: OFFICE_CHART_COLORS[index],
      values: row.slice(1).map((cell) => sourceCellText(cell, true)) }));
  if (new Set(categories).size !== categories.length || new Set(series.map((entry) => entry.name)).size !== series.length) {
    throw new Error("chart-source-label");
  }
  return { categories, series };
}

export function officeChartBindingMatches(document, value) {
  const chart = officeChartAttributes(value);
  if (!chart.source) return true;
  const derived = officeChartDataFromDocument(document, chart.source, chart.kind);
  return JSON.stringify({ categories: chart.categories, series: chart.series }) === JSON.stringify(derived);
}

export function validateOfficeChartBindings(document) {
  const walk = (node) => {
    if (node?.type === "chart" && !officeChartBindingMatches(document, node.attrs)) throw new Error("chart-source-stale");
    for (const child of node?.content || []) walk(child);
  };
  walk(document); return document;
}

export function officeChartDescription(value) {
  const chart = officeChartAttributes(value);
  return `${kindLabels[chart.kind]} · ${chart.title} · ${chart.categories.length} Kategorien · ${chart.series.length} ${chart.series.length === 1 ? "Datenreihe" : "Datenreihen"}${chart.source ? ` · verknüpft mit ${chart.source.range}` : ""} · ${chart.altText}`;
}

function chartTable(chart, dom) {
  const table = dom.createElement("table"); table.className = "office-chart-data visually-hidden";
  table.id = `${chart.id}-data`;
  const caption = dom.createElement("caption"); caption.textContent = `Datentabelle für ${chart.title}`;
  const head = dom.createElement("thead"), headRow = dom.createElement("tr"), categoryHead = dom.createElement("th");
  categoryHead.scope = "col"; categoryHead.textContent = "Kategorie"; headRow.append(categoryHead);
  for (const entry of chart.series) { const cell = dom.createElement("th"); cell.scope = "col"; cell.textContent = entry.name; headRow.append(cell); }
  head.append(headRow);
  const body = dom.createElement("tbody");
  chart.categories.forEach((category, index) => {
    const row = dom.createElement("tr"), label = dom.createElement("th"); label.scope = "row"; label.textContent = category; row.append(label);
    for (const entry of chart.series) { const cell = dom.createElement("td"); cell.textContent = String(entry.values[index]); row.append(cell); }
    body.append(row);
  });
  table.append(caption, head, body); return table;
}

function barChart(chart, dom) {
  const visual = dom.createElement("div"); visual.className = "office-chart-bars";
  const maximum = Math.max(1, ...chart.series.flatMap((entry) => entry.values.map((number) => Math.abs(number))));
  chart.categories.forEach((category, categoryIndex) => {
    const group = dom.createElement("div"); group.className = "office-chart-bar-group";
    const bars = dom.createElement("div"); bars.className = "office-chart-bar-values";
    for (const entry of chart.series) {
      const bar = dom.createElement("span"); bar.className = "office-chart-bar";
      bar.style.setProperty("--chart-value", String(Math.max(3, Math.abs(entry.values[categoryIndex]) / maximum * 100)));
      bar.style.setProperty("--chart-color", colorValues[entry.color]); bar.dataset.negative = String(entry.values[categoryIndex] < 0);
      bar.title = `${category} · ${entry.name}: ${entry.values[categoryIndex]}`; bars.append(bar);
    }
    const label = dom.createElement("span"); label.className = "office-chart-category"; label.textContent = category;
    group.append(bars, label); visual.append(group);
  });
  return visual;
}

function lineChart(chart, dom) {
  const namespace = "http://www.w3.org/2000/svg", svg = dom.createElementNS(namespace, "svg");
  svg.classList.add("office-chart-lines"); svg.setAttribute("viewBox", "0 0 800 320"); svg.setAttribute("aria-hidden", "true");
  const all = chart.series.flatMap((entry) => entry.values), minimum = Math.min(...all), maximum = Math.max(...all);
  const span = Math.max(1, maximum - minimum), denominator = Math.max(1, chart.categories.length - 1);
  for (const entry of chart.series) {
    const points = entry.values.map((number, index) => `${40 + index / denominator * 720},${280 - (number - minimum) / span * 240}`).join(" ");
    const line = dom.createElementNS(namespace, "polyline"); line.setAttribute("points", points); line.setAttribute("fill", "none");
    line.setAttribute("stroke", colorValues[entry.color]); line.setAttribute("stroke-width", "6"); line.setAttribute("stroke-linejoin", "round");
    svg.append(line);
    entry.values.forEach((number, index) => { const circle = dom.createElementNS(namespace, "circle");
      circle.setAttribute("cx", String(40 + index / denominator * 720)); circle.setAttribute("cy", String(280 - (number - minimum) / span * 240));
      circle.setAttribute("r", "7"); circle.setAttribute("fill", colorValues[entry.color]); svg.append(circle); });
  }
  return svg;
}

function pieChart(chart, dom) {
  const pie = dom.createElement("div"); pie.className = "office-chart-pie";
  const values = chart.series[0].values, total = values.reduce((sum, value) => sum + value, 0); let offset = 0;
  const parts = values.map((value, index) => { const start = offset; offset += value / total * 360;
    return `${colorValues[OFFICE_CHART_COLORS[index % OFFICE_CHART_COLORS.length]]} ${start}deg ${offset}deg`; });
  pie.style.background = `conic-gradient(${parts.join(",")})`; return pie;
}

export function officeChartElement(value, dom = document) {
  const chart = officeChartAttributes(value), figure = dom.createElement("figure");
  figure.className = "office-chart"; figure.dataset.officeChart = chart.id; figure.dataset.chartKind = chart.kind;
  figure.setAttribute("role", "img"); figure.setAttribute("aria-label", officeChartDescription(chart));
  figure.setAttribute("aria-describedby", `${chart.id}-data`);
  const title = dom.createElement("figcaption"); title.className = "office-chart-title"; title.textContent = chart.title;
  const visual = chart.kind === "bar" ? barChart(chart, dom) : chart.kind === "line" ? lineChart(chart, dom) : pieChart(chart, dom);
  visual.classList.add("office-chart-visual");
  const labels = dom.createElement("div"); labels.className = "office-chart-categories";
  if (chart.kind !== "bar") for (const category of chart.categories) { const label = dom.createElement("span"); label.textContent = category; labels.append(label); }
  const legend = dom.createElement("div"); legend.className = "office-chart-legend"; legend.hidden = !chart.legend;
  const legendEntries = chart.kind === "pie" ? chart.categories.map((name, index) => ({ name, color: OFFICE_CHART_COLORS[index % 4] })) : chart.series;
  for (const entry of legendEntries) { const item = dom.createElement("span"), swatch = dom.createElement("i");
    swatch.style.background = colorValues[entry.color]; item.append(swatch, entry.name); legend.append(item); }
  const values = dom.createElement("div"); values.className = "office-chart-value-labels"; values.hidden = !chart.dataLabels;
  chart.categories.forEach((category, index) => chart.series.forEach((entry) => {
    const label = dom.createElement("span"); label.textContent = `${category} · ${entry.name}: ${entry.values[index]}`; values.append(label);
  }));
  figure.append(title, visual, labels, legend, values, chartTable(chart, dom)); return figure;
}
