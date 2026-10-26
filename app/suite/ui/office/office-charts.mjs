import { officeTableAttributes, officeTableCellAttributes, officeTableCellText, officeTableGrid } from "./office-tables.mjs";

export const OFFICE_CHART_LIMIT = 20;
export const OFFICE_CHART_KINDS = ["bar", "stacked-bar", "line", "area", "pie", "doughnut"];
export const OFFICE_CHART_COLORS = ["teal", "blue", "orange", "purple"];
export const OFFICE_CHART_LEGEND_POSITIONS = ["bottom", "top", "left", "right"];
export const OFFICE_CHART_NUMBER_FORMATS = ["general", "integer", "decimal", "percent", "currency-eur"];
export const OFFICE_CHART_PALETTES = ["standard", "accessible", "warm", "monochrome"];
export const OFFICE_CHART_STYLES = ["clean", "soft", "focus"];
export const OFFICE_CHART_TITLE_ALIGNMENTS = ["left", "center", "right"];

const colorPalettes = {
  standard: { teal: "#0f766e", blue: "#2563eb", orange: "#ea580c", purple: "#7e22ce" },
  accessible: { teal: "#008576", blue: "#005ab5", orange: "#dc7b00", purple: "#7c3c8c" },
  warm: { teal: "#9a3412", blue: "#c2410c", orange: "#eab308", purple: "#be123c" },
  monochrome: { teal: "#17324d", blue: "#3d5f7d", orange: "#6d879e", purple: "#9cabb8" },
};
const kindLabels = { bar: "Säulendiagramm", "stacked-bar": "Gestapeltes Säulendiagramm", line: "Liniendiagramm",
  area: "Flächendiagramm", pie: "Kreisdiagramm", doughnut: "Ringdiagramm" };
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
  return series.flatMap((entry) => entry.values);
}

function officeChartPresentation(value) {
  if (!value || Object.keys(value).sort().join(",") !== "palette,style,titleAlignment" ||
      !OFFICE_CHART_PALETTES.includes(value.palette) || !OFFICE_CHART_STYLES.includes(value.style) ||
      !OFFICE_CHART_TITLE_ALIGNMENTS.includes(value.titleAlignment)) throw new Error("chart-presentation");
  return { palette: value.palette, style: value.style, titleAlignment: value.titleAlignment };
}

function officeChartAxes(value, series, kind) {
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
    const intervals = (value.maximum - value.minimum) / value.majorUnit, scaleValues = chartScaleValues(kind, series);
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
    ...(value?.axes == null ? [] : ["axes"]), ...(value?.presentation == null ? [] : ["presentation"])];
  const actualKeys = Object.keys(value || {}).filter((key) =>
    !["source", "dataLabels", "legendPosition", "axes", "presentation"].includes(key) || value[key] != null);
  if (!value || actualKeys.sort().join(",") !== keys.sort().join(",") ||
      !/^chart-[a-f0-9]{24}$/.test(value.id) || !OFFICE_CHART_KINDS.includes(value.kind) ||
      !literal(value.title, 1, 120) || !literal(value.altText, 1, 500) || typeof value.legend !== "boolean" ||
      (value.dataLabels != null && typeof value.dataLabels !== "boolean") ||
      (value.legendPosition != null && !OFFICE_CHART_LEGEND_POSITIONS.includes(value.legendPosition)) ||
      !Array.isArray(value.categories) || value.categories.length < 1 || value.categories.length > 12 ||
      value.categories.some((category) => !literal(category, 1, 60)) || new Set(value.categories).size !== value.categories.length ||
      !Array.isArray(value.series) || value.series.length < 1 || value.series.length > 4 ||
      (circularKind(value.kind) && value.series.length !== 1)) throw new Error("chart-attributes");
  const series = value.series.map((entry) => {
    if (!entry || Object.keys(entry).sort().join(",") !== "color,name,values" || !literal(entry.name, 1, 60) ||
        !OFFICE_CHART_COLORS.includes(entry.color) || !Array.isArray(entry.values) ||
        entry.values.length !== value.categories.length || entry.values.some((number) => typeof number !== "number" ||
          !Number.isFinite(number) || number < -1000000000 || number > 1000000000) ||
        (!["line", "area"].includes(value.kind) && entry.values.some((number) => number < 0))) {
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
  if (value.axes != null) {
    if (circularKind(value.kind)) throw new Error("chart-axes");
    result.axes = officeChartAxes(value.axes, series, value.kind);
  }
  if (value.source != null) result.source = officeChartSource(value.source);
  return result;
}

function niceStep(value) {
  const power = 10 ** Math.floor(Math.log10(Math.max(value, 1e-10))), normalized = value / power;
  return (normalized <= 1 ? 1 : normalized <= 2 ? 2 : normalized <= 5 ? 5 : 10) * power;
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
  const values = chartScaleValues(chart.kind, chart.series); let minimum = Math.min(0, ...values), maximum = Math.max(0, ...values);
  if (minimum === maximum) maximum = minimum + 1;
  const majorUnit = niceStep((maximum - minimum) / 5);
  minimum = Math.floor(minimum / majorUnit) * majorUnit; maximum = Math.ceil(maximum / majorUnit) * majorUnit;
  if (minimum === maximum) maximum = minimum + majorUnit;
  const ticks = [];
  for (let current = minimum, index = 0; index <= 12 && current <= maximum + majorUnit / 1000; index += 1, current += majorUnit) {
    ticks.push(Math.abs(current) < majorUnit / 1000000 ? 0 : current);
  }
  if (ticks.at(-1) !== maximum) ticks.push(maximum);
  return { ...axes, minimum, maximum, majorUnit, ticks };
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
  return `${kindLabels[chart.kind]} · ${chart.title} · ${chart.categories.length} Kategorien · ${chart.series.length} ${chart.series.length === 1 ? "Datenreihe" : "Datenreihen"}${axes}${chart.source ? ` · verknüpft mit ${chart.source.range}` : ""} · ${chart.altText}`;
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

function lineChart(chart, scale, dom) {
  const namespace = "http://www.w3.org/2000/svg", svg = dom.createElementNS(namespace, "svg");
  svg.classList.add("office-chart-lines"); svg.setAttribute("viewBox", "0 0 800 320"); svg.setAttribute("aria-hidden", "true");
  const span = scale.maximum - scale.minimum, denominator = Math.max(1, chart.categories.length - 1);
  for (const entry of chart.series) {
    const points = entry.values.map((number, index) => `${40 + index / denominator * 720},${280 - (number - scale.minimum) / span * 240}`).join(" ");
    if (chart.kind === "area") { const baseline = 280 - (0 - scale.minimum) / span * 240;
      const area = dom.createElementNS(namespace, "polygon"); area.setAttribute("points", `40,${baseline} ${points} 760,${baseline}`);
      area.setAttribute("fill", chartColor(chart, entry.color)); area.setAttribute("fill-opacity", "0.22"); svg.append(area); }
    const line = dom.createElementNS(namespace, "polyline"); line.setAttribute("points", points); line.setAttribute("fill", "none");
    line.setAttribute("stroke", chartColor(chart, entry.color)); line.setAttribute("stroke-width", "6"); line.setAttribute("stroke-linejoin", "round");
    svg.append(line);
    entry.values.forEach((number, index) => { const circle = dom.createElementNS(namespace, "circle");
      circle.setAttribute("cx", String(40 + index / denominator * 720)); circle.setAttribute("cy", String(280 - (number - scale.minimum) / span * 240));
      circle.setAttribute("r", "7"); circle.setAttribute("fill", chartColor(chart, entry.color)); svg.append(circle); });
  }
  return svg;
}

function axisFrame(scale, visual, dom) {
  const frame = dom.createElement("div"); frame.className = "office-chart-axis-frame";
  const valueTitle = dom.createElement("span"); valueTitle.className = "office-chart-value-axis-title";
  valueTitle.textContent = scale.valueTitle; valueTitle.hidden = !scale.valueTitle;
  const ticks = dom.createElement("div"); ticks.className = "office-chart-axis-ticks";
  [...scale.ticks].reverse().forEach((tick) => { const label = dom.createElement("span");
    label.textContent = formatChartNumber(tick, scale.numberFormat); ticks.append(label); });
  const stage = dom.createElement("div"); stage.className = "office-chart-plot-stage";
  if (scale.gridlines) { const grid = dom.createElement("div"); grid.className = "office-chart-gridlines";
    scale.ticks.forEach(() => grid.append(dom.createElement("i"))); stage.append(grid); }
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
    ["line", "area"].includes(chart.kind) ? lineChart(chart, scale, dom) : pieChart(chart, dom);
  visual.classList.add("office-chart-visual");
  const labels = dom.createElement("div"); labels.className = "office-chart-categories";
  if (!["bar", "stacked-bar"].includes(chart.kind)) for (const category of chart.categories) { const label = dom.createElement("span"); label.textContent = category; labels.append(label); }
  const legend = dom.createElement("div"); legend.className = "office-chart-legend"; legend.hidden = !chart.legend;
  const legendEntries = circularKind(chart.kind) ? chart.categories.map((name, index) => ({ name, color: OFFICE_CHART_COLORS[index % 4] })) : chart.series;
  for (const entry of legendEntries) { const item = dom.createElement("span"), swatch = dom.createElement("i");
    swatch.style.background = chartColor(chart, entry.color); item.append(swatch, entry.name); legend.append(item); }
  const plot = dom.createElement("div"); plot.className = "office-chart-plot";
  if (scale) plot.append(axisFrame(scale, visual, dom)); else plot.append(visual);
  plot.append(labels);
  if (scale?.categoryTitle) { const categoryTitle = dom.createElement("div"); categoryTitle.className = "office-chart-category-axis-title";
    categoryTitle.textContent = scale.categoryTitle; plot.append(categoryTitle); }
  const body = dom.createElement("div"); body.className = "office-chart-body"; body.append(plot, legend);
  const values = dom.createElement("div"); values.className = "office-chart-value-labels"; values.hidden = !chart.dataLabels;
  chart.categories.forEach((category, index) => chart.series.forEach((entry) => {
    const label = dom.createElement("span"); label.textContent = `${category} · ${entry.name}: ${formatChartNumber(entry.values[index], scale?.numberFormat)}`; values.append(label);
  }));
  figure.append(title, body, values, chartTable(chart, dom)); return figure;
}
