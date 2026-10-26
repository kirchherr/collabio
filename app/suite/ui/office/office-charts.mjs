import { officeTableAttributes, officeTableCellAttributes, officeTableCellText, officeTableGrid } from "./office-tables.mjs";

export const OFFICE_CHART_LIMIT = 20;
export const OFFICE_CHART_KINDS = ["bar", "stacked-bar", "line", "area", "pie", "doughnut", "scatter", "combo"];
export const OFFICE_CHART_COLORS = ["teal", "blue", "orange", "purple"];
export const OFFICE_CHART_LEGEND_POSITIONS = ["bottom", "top", "left", "right"];
export const OFFICE_CHART_NUMBER_FORMATS = ["general", "integer", "decimal", "percent", "currency-eur"];
export const OFFICE_CHART_PALETTES = ["standard", "accessible", "warm", "monochrome"];
export const OFFICE_CHART_STYLES = ["clean", "soft", "focus"];
export const OFFICE_CHART_TITLE_ALIGNMENTS = ["left", "center", "right"];
export const OFFICE_CHART_SERIES_RENDERERS = ["bar", "line", "points"];
export const OFFICE_CHART_MARKERS = ["none", "circle", "square", "diamond"];
export const OFFICE_CHART_LINE_STYLES = ["none", "solid", "dashed"];
export const OFFICE_CHART_DATA_LABEL_CONTENTS = ["value", "category-value", "series-value", "full"];
export const OFFICE_CHART_DATA_LABEL_POSITIONS = ["below", "top"];

const colorPalettes = {
  standard: { teal: "#0f766e", blue: "#2563eb", orange: "#ea580c", purple: "#7e22ce" },
  accessible: { teal: "#008576", blue: "#005ab5", orange: "#dc7b00", purple: "#7c3c8c" },
  warm: { teal: "#9a3412", blue: "#c2410c", orange: "#eab308", purple: "#be123c" },
  monochrome: { teal: "#17324d", blue: "#3d5f7d", orange: "#6d879e", purple: "#9cabb8" },
};
const kindLabels = { bar: "Säulendiagramm", "stacked-bar": "Gestapeltes Säulendiagramm", line: "Liniendiagramm",
  area: "Flächendiagramm", pie: "Kreisdiagramm", doughnut: "Ringdiagramm", scatter: "Streudiagramm",
  combo: "Kombinationsdiagramm" };
const chartRange = /^([A-T])([1-9][0-9]{0,2}):([A-T])([1-9][0-9]{0,2})$/u;
const chartNumber = /^-?(?:0|[1-9][0-9]*)(?:[.,][0-9]{1,10})?$/u;

function literal(value, minimum, maximum) {
  return typeof value === "string" && value.length >= minimum && value.length <= maximum && value === value.trim() &&
    ![...value].some((character) => character.codePointAt(0) < 32 ||
      (character.codePointAt(0) >= 127 && character.codePointAt(0) <= 159) ||
      (character.codePointAt(0) >= 0xd800 && character.codePointAt(0) <= 0xdfff) || ["\u2028", "\u2029"].includes(character));
}

const circularKind = (kind) => ["pie", "doughnut"].includes(kind);

function chartScaleValues(kind, series) {
  if (kind === "stacked-bar") return series[0].values.map((_value, index) =>
    series.reduce((sum, entry) => sum + entry.values[index], 0));
  if (kind === "scatter") return series.slice(1).flatMap((entry) => entry.values);
  return series.flatMap((entry) => entry.values);
}

function officeChartPresentation(value) {
  if (!value || Object.keys(value).sort().join(",") !== "palette,style,titleAlignment" ||
      !OFFICE_CHART_PALETTES.includes(value.palette) || !OFFICE_CHART_STYLES.includes(value.style) ||
      !OFFICE_CHART_TITLE_ALIGNMENTS.includes(value.titleAlignment)) throw new Error("chart-presentation");
  return { palette: value.palette, style: value.style, titleAlignment: value.titleAlignment };
}

function officeChartDataLabelPresentation(value) {
  if (!value || Object.keys(value).sort().join(",") !== "content,position" ||
      !OFFICE_CHART_DATA_LABEL_CONTENTS.includes(value.content) ||
      !OFFICE_CHART_DATA_LABEL_POSITIONS.includes(value.position)) throw new Error("chart-data-label-presentation");
  return { content: value.content, position: value.position };
}

function officeChartReferenceLines(value) {
  if (!Array.isArray(value) || value.length < 1 || value.length > 4) throw new Error("chart-reference-lines");
  const labels = new Set();
  return value.map((entry) => {
    if (!entry || Object.keys(entry).sort().join(",") !== "color,label,lineStyle,value" ||
        !literal(entry.label, 1, 60) || labels.has(entry.label) || typeof entry.value !== "number" ||
        !Number.isFinite(entry.value) || Math.abs(entry.value) > 1000000000 || !OFFICE_CHART_COLORS.includes(entry.color) ||
        !["solid", "dashed"].includes(entry.lineStyle)) throw new Error("chart-reference-lines");
    labels.add(entry.label); return { label: entry.label, value: entry.value, color: entry.color, lineStyle: entry.lineStyle };
  });
}

function officeChartSeriesPresentation(value, kind, series) {
  const count = kind === "scatter" ? series.length - 1 : series.length;
  if (!Array.isArray(value) || value.length !== count) throw new Error("chart-series-presentation");
  const result = value.map((entry) => {
    if (!entry || Object.keys(entry).sort().join(",") !== "lineStyle,marker,renderAs" ||
        !OFFICE_CHART_SERIES_RENDERERS.includes(entry.renderAs) || !OFFICE_CHART_MARKERS.includes(entry.marker) ||
        !OFFICE_CHART_LINE_STYLES.includes(entry.lineStyle)) throw new Error("chart-series-presentation");
    if ((entry.renderAs === "bar" && (entry.marker !== "none" || entry.lineStyle !== "none")) ||
        (entry.renderAs === "line" && entry.lineStyle === "none") ||
        (entry.renderAs === "points" && entry.marker === "none")) throw new Error("chart-series-presentation");
    return { renderAs: entry.renderAs, marker: entry.marker, lineStyle: entry.lineStyle };
  });
  if ((kind === "line" || kind === "area") && result.some((entry) => entry.renderAs !== "line") ||
      kind === "scatter" && result.some((entry) => entry.renderAs !== "points") ||
      kind === "combo" && (!result.some((entry) => entry.renderAs === "bar") ||
        !result.some((entry) => entry.renderAs === "line") || result.some((entry) => entry.renderAs === "points")) ||
      !["line", "area", "scatter", "combo"].includes(kind)) throw new Error("chart-series-presentation");
  if (kind === "combo" && result.some((entry, index) => entry.renderAs === "bar" &&
      series[index].values.some((number) => number < 0))) throw new Error("chart-series-presentation");
  return result;
}

function officeChartAxes(value, series, kind, referenceLines = []) {
  const keys = Object.keys(value || {}).sort().join(",");
  if (!value || keys !== "categoryTitle,gridlines,majorUnit,maximum,minimum,mode,numberFormat,valueTitle" ||
      !["auto", "manual"].includes(value.mode) || typeof value.gridlines !== "boolean" ||
      !OFFICE_CHART_NUMBER_FORMATS.includes(value.numberFormat) ||
      !(value.categoryTitle === "" || literal(value.categoryTitle, 1, 60)) ||
      !(value.valueTitle === "" || literal(value.valueTitle, 1, 60))) throw new Error("chart-axes");
  const numbers = [value.minimum, value.maximum, value.majorUnit];
  if (value.mode === "auto") {
    if (numbers.some((entry) => entry !== null)) throw new Error("chart-axes");
  } else {
    const intervals = (value.maximum - value.minimum) / value.majorUnit;
    const scaleValues = [...chartScaleValues(kind, series), ...referenceLines.map((entry) => entry.value)];
    if (numbers.some((entry) => typeof entry !== "number" || !Number.isFinite(entry) || Math.abs(entry) > 1000000000) ||
        value.minimum >= value.maximum || value.majorUnit <= 0 || value.majorUnit > value.maximum - value.minimum ||
        Math.abs(intervals - Math.round(intervals)) > 1e-9 || intervals > 12 || (kind === "stacked-bar" && value.minimum !== 0) ||
        scaleValues.some((entry) => entry < value.minimum || entry > value.maximum)) {
      throw new Error("chart-axes");
    }
  }
  return { mode: value.mode, categoryTitle: value.categoryTitle, valueTitle: value.valueTitle,
    minimum: value.minimum, maximum: value.maximum, majorUnit: value.majorUnit,
    gridlines: value.gridlines, numberFormat: value.numberFormat };
}

export function officeChartAttributes(value) {
  const baseKeys = ["altText", "categories", "id", "kind", "legend", "series", "title"];
  const keys = [...baseKeys, ...(value?.source == null ? [] : ["source"]),
    ...(value?.dataLabels == null ? [] : ["dataLabels"]), ...(value?.legendPosition == null ? [] : ["legendPosition"]),
    ...(value?.axes == null ? [] : ["axes"]), ...(value?.presentation == null ? [] : ["presentation"]),
    ...(value?.seriesPresentation == null ? [] : ["seriesPresentation"]),
    ...(value?.dataLabelPresentation == null ? [] : ["dataLabelPresentation"]),
    ...(value?.referenceLines == null ? [] : ["referenceLines"])];
  const actualKeys = Object.keys(value || {}).filter((key) =>
    !["source", "dataLabels", "legendPosition", "axes", "presentation", "seriesPresentation", "dataLabelPresentation",
      "referenceLines"].includes(key) || value[key] != null);
  if (!value || actualKeys.sort().join(",") !== keys.sort().join(",") ||
      !/^chart-[a-f0-9]{24}$/.test(value.id) || !OFFICE_CHART_KINDS.includes(value.kind) ||
      !literal(value.title, 1, 120) || !literal(value.altText, 1, 500) || typeof value.legend !== "boolean" ||
      (value.dataLabels != null && typeof value.dataLabels !== "boolean") ||
      (value.dataLabelPresentation != null && value.dataLabels !== true) ||
      (value.legendPosition != null && !OFFICE_CHART_LEGEND_POSITIONS.includes(value.legendPosition)) ||
      !Array.isArray(value.categories) || value.categories.length < 1 || value.categories.length > 12 ||
      value.categories.some((category) => !literal(category, 1, 60)) || new Set(value.categories).size !== value.categories.length ||
      !Array.isArray(value.series) || value.series.length < 1 || value.series.length > 4 ||
      (circularKind(value.kind) && value.series.length !== 1) ||
      (["scatter", "combo"].includes(value.kind) && value.series.length < 2) ||
      (["scatter", "combo"].includes(value.kind) && value.seriesPresentation == null)) throw new Error("chart-attributes");
  const series = value.series.map((entry) => {
    if (!entry || Object.keys(entry).sort().join(",") !== "color,name,values" || !literal(entry.name, 1, 60) ||
        !OFFICE_CHART_COLORS.includes(entry.color) || !Array.isArray(entry.values) ||
        entry.values.length !== value.categories.length || entry.values.some((number) => typeof number !== "number" ||
          !Number.isFinite(number) || number < -1000000000 || number > 1000000000) ||
        (!["line", "area", "scatter", "combo"].includes(value.kind) && entry.values.some((number) => number < 0))) {
      throw new Error("chart-series");
    }
    return { name: entry.name, color: entry.color, values: [...entry.values] };
  });
  if (new Set(series.map((entry) => entry.name)).size !== series.length ||
      new Set(series.map((entry) => entry.color)).size !== series.length ||
      (circularKind(value.kind) && !series[0].values.some((number) => number > 0))) throw new Error("chart-series");
  const result = { id: value.id, kind: value.kind, title: value.title, altText: value.altText, legend: value.legend,
    categories: [...value.categories], series };
  if (value.dataLabels != null) result.dataLabels = value.dataLabels;
  if (value.legendPosition != null) result.legendPosition = value.legendPosition;
  if (value.presentation != null) result.presentation = officeChartPresentation(value.presentation);
  if (value.dataLabelPresentation != null) {
    result.dataLabelPresentation = officeChartDataLabelPresentation(value.dataLabelPresentation);
  }
  if (value.seriesPresentation != null) {
    result.seriesPresentation = officeChartSeriesPresentation(value.seriesPresentation, value.kind, series);
  }
  const referenceLines = value.referenceLines == null ? [] : officeChartReferenceLines(value.referenceLines);
  if (referenceLines.length) {
    if (circularKind(value.kind)) throw new Error("chart-reference-lines");
    result.referenceLines = referenceLines;
  }
  if (value.axes != null) {
    if (circularKind(value.kind)) throw new Error("chart-axes");
    result.axes = officeChartAxes(value.axes, series, value.kind, referenceLines);
  }
  if (value.source != null) result.source = officeChartSource(value.source);
  return result;
}

function niceStep(value) {
  const power = 10 ** Math.floor(Math.log10(Math.max(value, 1e-10))), normalized = value / power;
  return (normalized <= 1 ? 1 : normalized <= 2 ? 2 : normalized <= 5 ? 5 : 10) * power;
}

function automaticScale(values) {
  let minimum = Math.min(0, ...values), maximum = Math.max(0, ...values);
  if (minimum === maximum) maximum = minimum + 1;
  const majorUnit = niceStep((maximum - minimum) / 5);
  minimum = Math.floor(minimum / majorUnit) * majorUnit; maximum = Math.ceil(maximum / majorUnit) * majorUnit;
  if (minimum === maximum) maximum = minimum + majorUnit;
  const ticks = [];
  for (let current = minimum, index = 0; index <= 12 && current <= maximum + majorUnit / 1000; index += 1, current += majorUnit) {
    ticks.push(Math.abs(current) < majorUnit / 1000000 ? 0 : current);
  }
  if (ticks.at(-1) !== maximum) ticks.push(maximum);
  return { minimum, maximum, majorUnit, ticks };
}

export function officeChartAxisScale(value) {
  const chart = officeChartAttributes(value);
  if (circularKind(chart.kind)) return null;
  const axes = chart.axes || { mode: "auto", categoryTitle: "", valueTitle: "", minimum: null, maximum: null,
    majorUnit: null, gridlines: true, numberFormat: "general" };
  if (axes.mode === "manual") {
    const ticks = [];
    for (let index = 0; index <= 12 && axes.minimum + axes.majorUnit * index < axes.maximum; index += 1) {
      ticks.push(axes.minimum + axes.majorUnit * index);
    }
    ticks.push(axes.maximum);
    return { ...axes, ticks };
  }
  return { ...axes, ...automaticScale([...chartScaleValues(chart.kind, chart.series),
    ...(chart.referenceLines || []).map((entry) => entry.value)]) };
}

function formatChartNumber(value, format = "general") {
  if (format === "integer") return String(Math.round(value));
  if (format === "decimal") return value.toFixed(2).replace(".", ",");
  if (format === "percent") return `${(value * 100).toFixed(0)} %`;
  if (format === "currency-eur") return `${value.toFixed(2).replace(".", ",")} €`;
  return String(Number(value.toFixed(10)));
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
      (circularKind(kind) && (orientation === "columns" ? right - left !== 2 : bottom - top !== 2))) throw new Error("chart-source-range");
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
  const axes = chart.axes ? ` · Achsen ${chart.axes.categoryTitle || "Kategorien"} / ${chart.axes.valueTitle || "Werte"}` : "";
  const references = chart.referenceLines?.length ? ` · Referenzlinien ${chart.referenceLines.map((entry) =>
    `${entry.label}: ${entry.value}`).join(", ")}` : "";
  return `${kindLabels[chart.kind]} · ${chart.title} · ${chart.categories.length} Kategorien · ${chart.series.length} ${chart.series.length === 1 ? "Datenreihe" : "Datenreihen"}${axes}${references}${chart.source ? ` · verknüpft mit ${chart.source.range}` : ""} · ${chart.altText}`;
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

function barChart(chart, scale, dom) {
  const visual = dom.createElement("div"); visual.className = "office-chart-bars";
  const span = scale.maximum - scale.minimum;
  chart.categories.forEach((category, categoryIndex) => {
    const group = dom.createElement("div"); group.className = "office-chart-bar-group";
    const bars = dom.createElement("div"); bars.className = "office-chart-bar-values";
    if (chart.kind === "stacked-bar") {
      const stack = dom.createElement("div"); stack.className = "office-chart-bar-stack";
      for (const entry of chart.series) {
        const bar = dom.createElement("span"); bar.className = "office-chart-bar office-chart-bar-segment";
        bar.style.setProperty("--chart-value", String(entry.values[categoryIndex] / span * 100));
        bar.style.setProperty("--chart-color", chartColor(chart, entry.color));
        bar.title = `${category} · ${entry.name}: ${entry.values[categoryIndex]}`; stack.append(bar);
      }
      bars.append(stack);
    } else {
      for (const entry of chart.series) {
        const bar = dom.createElement("span"); bar.className = "office-chart-bar";
        bar.style.setProperty("--chart-value", String(Math.max(3, (entry.values[categoryIndex] - scale.minimum) / span * 100)));
        bar.style.setProperty("--chart-color", chartColor(chart, entry.color)); bar.dataset.negative = String(entry.values[categoryIndex] < 0);
        bar.title = `${category} · ${entry.name}: ${entry.values[categoryIndex]}`; bars.append(bar);
      }
    }
    const label = dom.createElement("span"); label.className = "office-chart-category"; label.textContent = category;
    group.append(bars, label); visual.append(group);
  });
  return visual;
}

function chartColor(chart, color) {
  return colorPalettes[chart.presentation?.palette || "standard"][color];
}

function addChartMarker(svg, x, y, style, color, dom, namespace) {
  if (style.marker === "none") return;
  let marker;
  if (style.marker === "circle") {
    marker = dom.createElementNS(namespace, "circle"); marker.setAttribute("cx", String(x));
    marker.setAttribute("cy", String(y)); marker.setAttribute("r", "7");
  } else if (style.marker === "square") {
    marker = dom.createElementNS(namespace, "rect"); marker.setAttribute("x", String(x - 7));
    marker.setAttribute("y", String(y - 7)); marker.setAttribute("width", "14"); marker.setAttribute("height", "14");
  } else {
    marker = dom.createElementNS(namespace, "polygon");
    marker.setAttribute("points", `${x},${y - 9} ${x + 9},${y} ${x},${y + 9} ${x - 9},${y}`);
  }
  marker.classList.add("office-chart-marker"); marker.setAttribute("fill", color); svg.append(marker);
}

function addChartLine(svg, points, style, color, dom, namespace) {
  if (style.lineStyle === "none") return;
  const line = dom.createElementNS(namespace, "polyline"); line.setAttribute("points", points); line.setAttribute("fill", "none");
  line.setAttribute("stroke", color); line.setAttribute("stroke-width", "6"); line.setAttribute("stroke-linejoin", "round");
  if (style.lineStyle === "dashed") line.setAttribute("stroke-dasharray", "18 12");
  svg.append(line);
}

function lineChart(chart, scale, dom) {
  const namespace = "http://www.w3.org/2000/svg", svg = dom.createElementNS(namespace, "svg");
  svg.classList.add("office-chart-lines"); svg.setAttribute("viewBox", "0 0 800 320"); svg.setAttribute("aria-hidden", "true");
  const span = scale.maximum - scale.minimum, denominator = Math.max(1, chart.categories.length - 1);
  chart.series.forEach((entry, seriesIndex) => {
    const style = chart.seriesPresentation?.[seriesIndex] || { renderAs: "line", marker: "circle", lineStyle: "solid" };
    const points = entry.values.map((number, index) => `${40 + index / denominator * 720},${280 - (number - scale.minimum) / span * 240}`).join(" ");
    if (chart.kind === "area") { const baseline = 280 - (0 - scale.minimum) / span * 240;
      const area = dom.createElementNS(namespace, "polygon"); area.setAttribute("points", `40,${baseline} ${points} 760,${baseline}`);
      area.setAttribute("fill", chartColor(chart, entry.color)); area.setAttribute("fill-opacity", "0.22"); svg.append(area); }
    const color = chartColor(chart, entry.color); addChartLine(svg, points, style, color, dom, namespace);
    entry.values.forEach((number, index) => addChartMarker(svg, 40 + index / denominator * 720,
      280 - (number - scale.minimum) / span * 240, style, color, dom, namespace));
  });
  return svg;
}

function comboChart(chart, scale, dom) {
  const namespace = "http://www.w3.org/2000/svg", svg = dom.createElementNS(namespace, "svg");
  svg.classList.add("office-chart-lines", "office-chart-combo"); svg.setAttribute("viewBox", "0 0 800 320");
  svg.setAttribute("aria-hidden", "true");
  const span = scale.maximum - scale.minimum, denominator = Math.max(1, chart.categories.length - 1);
  const barCount = chart.seriesPresentation.filter((entry) => entry.renderAs === "bar").length;
  chart.series.forEach((entry, seriesIndex) => {
    const style = chart.seriesPresentation[seriesIndex], color = chartColor(chart, entry.color);
    if (style.renderAs === "bar") {
      const barIndex = chart.seriesPresentation.slice(0, seriesIndex).filter((item) => item.renderAs === "bar").length;
      entry.values.forEach((number, index) => {
        const center = 40 + index / denominator * 720, width = Math.min(54 / barCount, 28);
        const baseline = 280 - (0 - scale.minimum) / span * 240, y = 280 - (number - scale.minimum) / span * 240;
        const bar = dom.createElementNS(namespace, "rect");
        bar.setAttribute("x", String(center - barCount * width / 2 + barIndex * width));
        bar.setAttribute("y", String(Math.min(y, baseline))); bar.setAttribute("width", String(Math.max(4, width - 3)));
        bar.setAttribute("height", String(Math.max(2, Math.abs(baseline - y)))); bar.setAttribute("fill", color); svg.append(bar);
      });
    } else {
      const points = entry.values.map((number, index) =>
        `${40 + index / denominator * 720},${280 - (number - scale.minimum) / span * 240}`).join(" ");
      addChartLine(svg, points, style, color, dom, namespace);
      entry.values.forEach((number, index) => addChartMarker(svg, 40 + index / denominator * 720,
        280 - (number - scale.minimum) / span * 240, style, color, dom, namespace));
    }
  });
  return svg;
}

function scatterChart(chart, scale, dom) {
  const namespace = "http://www.w3.org/2000/svg", svg = dom.createElementNS(namespace, "svg");
  svg.classList.add("office-chart-lines", "office-chart-scatter"); svg.setAttribute("viewBox", "0 0 800 320");
  svg.setAttribute("aria-hidden", "true");
  const xValues = chart.series[0].values, xScale = automaticScale(xValues);
  const xSpan = xScale.maximum - xScale.minimum, ySpan = scale.maximum - scale.minimum;
  chart.series.slice(1).forEach((entry, seriesIndex) => {
    const style = chart.seriesPresentation[seriesIndex], color = chartColor(chart, entry.color);
    const coordinates = entry.values.map((number, index) => ({
      x: 40 + (xValues[index] - xScale.minimum) / xSpan * 720,
      y: 280 - (number - scale.minimum) / ySpan * 240,
    }));
    addChartLine(svg, coordinates.map((point) => `${point.x},${point.y}`).join(" "), style, color, dom, namespace);
    coordinates.forEach((point) => addChartMarker(svg, point.x, point.y, style, color, dom, namespace));
  });
  return svg;
}

function axisFrame(chart, scale, visual, dom) {
  const frame = dom.createElement("div"); frame.className = "office-chart-axis-frame";
  const valueTitle = dom.createElement("span"); valueTitle.className = "office-chart-value-axis-title";
  valueTitle.textContent = scale.valueTitle; valueTitle.hidden = !scale.valueTitle;
  const ticks = dom.createElement("div"); ticks.className = "office-chart-axis-ticks";
  [...scale.ticks].reverse().forEach((tick) => { const label = dom.createElement("span");
    label.textContent = formatChartNumber(tick, scale.numberFormat); ticks.append(label); });
  const stage = dom.createElement("div"); stage.className = "office-chart-plot-stage";
  if (scale.gridlines) { const grid = dom.createElement("div"); grid.className = "office-chart-gridlines";
    scale.ticks.forEach(() => grid.append(dom.createElement("i"))); stage.append(grid); }
  if (chart.referenceLines?.length) { const lines = dom.createElement("div"); lines.className = "office-chart-reference-lines";
    chart.referenceLines.forEach((entry) => { const line = dom.createElement("span"), label = dom.createElement("b");
      line.style.setProperty("--reference-position", String((entry.value - scale.minimum) /
        (scale.maximum - scale.minimum) * 100)); line.style.setProperty("--reference-color", chartColor(chart, entry.color));
      line.dataset.lineStyle = entry.lineStyle; label.textContent = `${entry.label}: ${formatChartNumber(entry.value, scale.numberFormat)}`;
      line.append(label); lines.append(line); }); stage.append(lines); }
  stage.append(visual); frame.append(valueTitle, ticks, stage); return frame;
}

function pieChart(chart, dom) {
  const pie = dom.createElement("div"); pie.className = `office-chart-pie${chart.kind === "doughnut" ? " office-chart-doughnut" : ""}`;
  const values = chart.series[0].values, total = values.reduce((sum, value) => sum + value, 0); let offset = 0;
  const parts = values.map((value, index) => { const start = offset; offset += value / total * 360;
    return `${chartColor(chart, OFFICE_CHART_COLORS[index % OFFICE_CHART_COLORS.length])} ${start}deg ${offset}deg`; });
  pie.style.background = `conic-gradient(${parts.join(",")})`; return pie;
}

export function officeChartElement(value, dom = document) {
  const chart = officeChartAttributes(value), figure = dom.createElement("figure");
  figure.className = "office-chart"; figure.dataset.officeChart = chart.id; figure.dataset.chartKind = chart.kind;
  figure.dataset.legendPosition = chart.legendPosition || "bottom";
  figure.dataset.chartStyle = chart.presentation?.style || "clean";
  figure.dataset.titleAlignment = chart.presentation?.titleAlignment || "center";
  figure.setAttribute("role", "img"); figure.setAttribute("aria-label", officeChartDescription(chart));
  figure.setAttribute("aria-describedby", `${chart.id}-data`);
  const title = dom.createElement("figcaption"); title.className = "office-chart-title"; title.textContent = chart.title;
  const scale = officeChartAxisScale(chart);
  const visual = ["bar", "stacked-bar"].includes(chart.kind) ? barChart(chart, scale, dom) :
    ["line", "area"].includes(chart.kind) ? lineChart(chart, scale, dom) :
    chart.kind === "combo" ? comboChart(chart, scale, dom) :
    chart.kind === "scatter" ? scatterChart(chart, scale, dom) : pieChart(chart, dom);
  visual.classList.add("office-chart-visual");
  const labels = dom.createElement("div"); labels.className = "office-chart-categories";
  const labelValues = chart.kind === "scatter" ? automaticScale(chart.series[0].values).ticks.map((tick) =>
    formatChartNumber(tick, scale.numberFormat)) : chart.categories;
  if (!["bar", "stacked-bar"].includes(chart.kind)) for (const category of labelValues) {
    const label = dom.createElement("span"); label.textContent = category; labels.append(label);
  }
  const legend = dom.createElement("div"); legend.className = "office-chart-legend"; legend.hidden = !chart.legend;
  const legendEntries = circularKind(chart.kind) ? chart.categories.map((name, index) =>
    ({ name, color: OFFICE_CHART_COLORS[index % 4] })) : chart.kind === "scatter" ? chart.series.slice(1) : chart.series;
  for (const entry of legendEntries) { const item = dom.createElement("span"), swatch = dom.createElement("i");
    swatch.style.background = chartColor(chart, entry.color); item.append(swatch, entry.name); legend.append(item); }
  const plot = dom.createElement("div"); plot.className = "office-chart-plot";
  if (scale) plot.append(axisFrame(chart, scale, visual, dom)); else plot.append(visual);
  plot.append(labels);
  if (scale?.categoryTitle) { const categoryTitle = dom.createElement("div"); categoryTitle.className = "office-chart-category-axis-title";
    categoryTitle.textContent = scale.categoryTitle; plot.append(categoryTitle); }
  const body = dom.createElement("div"); body.className = "office-chart-body"; body.append(plot, legend);
  const labelPresentation = chart.dataLabelPresentation || { content: "full", position: "below" };
  const values = dom.createElement("div"); values.className = "office-chart-value-labels"; values.hidden = !chart.dataLabels;
  values.dataset.position = labelPresentation.position;
  chart.categories.forEach((category, index) => {
    const entries = chart.kind === "scatter" ? chart.series.slice(1) : chart.series;
    entries.forEach((entry) => { const label = dom.createElement("span");
      const xValue = chart.kind === "scatter" ? ` · ${chart.series[0].name}: ${formatChartNumber(chart.series[0].values[index], scale?.numberFormat)}` : "";
      const number = formatChartNumber(entry.values[index], scale?.numberFormat);
      const content = labelPresentation.content === "value" ? number :
        labelPresentation.content === "category-value" ? `${category}: ${number}` :
          labelPresentation.content === "series-value" ? `${entry.name}: ${number}` :
            `${category}${xValue} · ${entry.name}: ${number}`;
      label.textContent = content;
      values.append(label); });
  });
  if (labelPresentation.position === "top") figure.append(title, values, body, chartTable(chart, dom));
  else figure.append(title, body, values, chartTable(chart, dom));
  return figure;
}
