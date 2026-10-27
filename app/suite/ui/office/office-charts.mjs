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

function chartSeriesIndices(kind, series) {
  return Array.from({ length: series.length - (kind === "scatter" ? 1 : 0) }, (_value, index) =>
    index + (kind === "scatter" ? 1 : 0));
}

function chartScaleValues(kind, series, indices = null) {
  if (kind === "stacked-bar") return series[0].values.map((_value, index) =>
    series.reduce((sum, entry) => sum + entry.values[index], 0));
  const selected = indices || chartSeriesIndices(kind, series);
  return selected.flatMap((index) => series[index].values);
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

function officeChartDataTablePresentation(value) {
  if (!value || Object.keys(value).sort().join(",") !== "position,showLegendKeys" ||
      !["above", "below"].includes(value.position) || typeof value.showLegendKeys !== "boolean") {
    throw new Error("chart-data-table-presentation");
  }
  return { position: value.position, showLegendKeys: value.showLegendKeys };
}

function officeChartCategoryAxisPresentation(value, kind) {
  if (!value || Object.keys(value).sort().join(",") !== "direction,labelInterval,labelRotation" ||
      !["bar", "stacked-bar", "line", "area", "combo"].includes(kind) ||
      !["forward", "reverse"].includes(value.direction) ||
      !["horizontal", "diagonal", "vertical"].includes(value.labelRotation) ||
      !Number.isInteger(value.labelInterval) || value.labelInterval < 1 || value.labelInterval > 3) {
    throw new Error("chart-category-axis-presentation");
  }
  return { direction: value.direction, labelRotation: value.labelRotation, labelInterval: value.labelInterval };
}

function officeChartSeriesManagement(value, kind, series, seriesPresentation) {
  const supported = ["bar", "stacked-bar", "line", "area", "combo"].includes(kind), count = series.length;
  if (!value || Object.keys(value).sort().join(",") !== "hidden,order" || !supported || count < 2 ||
      !Array.isArray(value.order) || value.order.length !== count ||
      value.order.some((index) => !Number.isInteger(index) || index < 0 || index >= count) ||
      new Set(value.order).size !== count || !Array.isArray(value.hidden) || value.hidden.length >= count ||
      value.hidden.some((index) => !Number.isInteger(index) || index < 0 || index >= count) ||
      new Set(value.hidden).size !== value.hidden.length ||
      value.hidden.some((index, position) => index !== [...value.hidden].sort((left, right) => left - right)[position])) {
    throw new Error("chart-series-management");
  }
  const hidden = new Set(value.hidden), visible = value.order.filter((index) => !hidden.has(index));
  if (kind === "combo") {
    const renderers = new Set(visible.map((index) => seriesPresentation?.[index]?.renderAs));
    if (!renderers.has("bar") || !renderers.has("line")) throw new Error("chart-series-management");
  }
  return { order: [...value.order], hidden: [...value.hidden] };
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

function chartAnalysisSeries(kind, series, seriesPresentation, seriesIndex) {
  if (!Number.isInteger(seriesIndex) || seriesIndex < 0 || seriesIndex >= series.length ||
      !["line", "area", "scatter", "combo"].includes(kind) ||
      (kind === "scatter" && seriesIndex === 0) ||
      (kind === "combo" && seriesPresentation?.[seriesIndex]?.renderAs !== "line")) {
    throw new Error("chart-analysis");
  }
  return { x: kind === "scatter" ? series[0].values : series[seriesIndex].values.map((_value, index) => index),
    y: series[seriesIndex].values };
}

function linearRegression(xValues, yValues) {
  const count = xValues.length, xMean = xValues.reduce((sum, value) => sum + value, 0) / count;
  const yMean = yValues.reduce((sum, value) => sum + value, 0) / count;
  const denominator = xValues.reduce((sum, value) => sum + (value - xMean) ** 2, 0);
  const slope = denominator === 0 ? 0 : xValues.reduce((sum, value, index) =>
    sum + (value - xMean) * (yValues[index] - yMean), 0) / denominator;
  return { slope, intercept: yMean - slope * xMean };
}

function chartAnalysisValues(kind, series, seriesPresentation, analysis, seriesIndices = null) {
  if (!analysis) return [];
  const includes = (seriesIndex) => seriesIndices == null || seriesIndices.includes(seriesIndex);
  const values = [];
  if (analysis.trendline && includes(analysis.trendline.seriesIndex)) {
    const { x, y } = chartAnalysisSeries(kind, series, seriesPresentation, analysis.trendline.seriesIndex);
    const regression = linearRegression(x, y), minimum = Math.min(...x), maximum = Math.max(...x);
    values.push(regression.intercept + regression.slope * minimum, regression.intercept + regression.slope * maximum);
  }
  if (analysis.errorBars && includes(analysis.errorBars.seriesIndex)) {
    const { y } = chartAnalysisSeries(kind, series, seriesPresentation, analysis.errorBars.seriesIndex);
    y.forEach((value) => values.push(value - analysis.errorBars.amount, value + analysis.errorBars.amount));
  }
  if (values.some((value) => !Number.isFinite(value) || Math.abs(value) > 1000000000)) throw new Error("chart-analysis");
  return values;
}

function officeChartAnalysis(value, kind, series, seriesPresentation) {
  if (!value || Object.keys(value).sort().join(",") !== "errorBars,trendline" ||
      (value.trendline == null && value.errorBars == null)) throw new Error("chart-analysis");
  let trendline = null, errorBars = null;
  if (value.trendline != null) {
    const entry = value.trendline;
    if (!entry || Object.keys(entry).sort().join(",") !== "color,lineStyle,seriesIndex" ||
        !OFFICE_CHART_COLORS.includes(entry.color) || !["solid", "dashed"].includes(entry.lineStyle)) {
      throw new Error("chart-analysis");
    }
    chartAnalysisSeries(kind, series, seriesPresentation, entry.seriesIndex);
    trendline = { seriesIndex: entry.seriesIndex, color: entry.color, lineStyle: entry.lineStyle };
  }
  if (value.errorBars != null) {
    const entry = value.errorBars;
    if (!entry || Object.keys(entry).sort().join(",") !== "amount,color,seriesIndex" ||
        !OFFICE_CHART_COLORS.includes(entry.color) || typeof entry.amount !== "number" ||
        !Number.isFinite(entry.amount) || entry.amount <= 0 || entry.amount > 1000000000) {
      throw new Error("chart-analysis");
    }
    chartAnalysisSeries(kind, series, seriesPresentation, entry.seriesIndex);
    errorBars = { seriesIndex: entry.seriesIndex, amount: entry.amount, color: entry.color };
  }
  const result = { trendline, errorBars };
  chartAnalysisValues(kind, series, seriesPresentation, result);
  return result;
}

function manualScale(value, scaleType, scaleValues, stacked = false) {
  const numbers = [value.minimum, value.maximum, value.majorUnit];
  if (value.mode === "auto") return numbers.every((entry) => entry === null);
  if (numbers.some((entry) => typeof entry !== "number" || !Number.isFinite(entry) || Math.abs(entry) > 1000000000) ||
      value.minimum >= value.maximum || scaleValues.some((entry) => entry < value.minimum || entry > value.maximum)) return false;
  if (scaleType === "logarithmic") {
    if (value.minimum <= 0 || value.majorUnit <= 1 || scaleValues.some((entry) => entry <= 0)) return false;
    const intervals = Math.log(value.maximum / value.minimum) / Math.log(value.majorUnit);
    return Math.abs(intervals - Math.round(intervals)) <= 1e-9 && intervals <= 12;
  }
  const intervals = (value.maximum - value.minimum) / value.majorUnit;
  return value.majorUnit > 0 && value.majorUnit <= value.maximum - value.minimum &&
    Math.abs(intervals - Math.round(intervals)) <= 1e-9 && intervals <= 12 && (!stacked || value.minimum === 0);
}

function officeChartAxisOptions(value, kind, series, seriesPresentation, analysis, referenceLines = []) {
  if (!value || Object.keys(value).sort().join(",") !== "primaryScale,secondary" ||
      !["linear", "logarithmic"].includes(value.primaryScale) ||
      !["line", "area", "scatter", "combo"].includes(kind)) throw new Error("chart-axis-options");
  let secondary = null;
  if (value.secondary != null) {
    const entry = value.secondary;
    if (!entry || Object.keys(entry).sort().join(",") !==
      "majorUnit,maximum,minimum,mode,numberFormat,scale,seriesIndex,title" ||
      !Number.isInteger(entry.seriesIndex) || !chartSeriesIndices(kind, series).includes(entry.seriesIndex) ||
      chartSeriesIndices(kind, series).length < 2 || !literal(entry.title, 1, 60) ||
      !["linear", "logarithmic"].includes(entry.scale) || !["auto", "manual"].includes(entry.mode) ||
      !OFFICE_CHART_NUMBER_FORMATS.includes(entry.numberFormat)) throw new Error("chart-axis-options");
    const values = [...chartScaleValues(kind, series, [entry.seriesIndex]),
      ...chartAnalysisValues(kind, series, seriesPresentation, analysis, [entry.seriesIndex])];
    if (entry.scale === "logarithmic" && values.some((number) => number <= 0) || !manualScale(entry, entry.scale, values)) {
      throw new Error("chart-axis-options");
    }
    secondary = { seriesIndex: entry.seriesIndex, title: entry.title, scale: entry.scale, mode: entry.mode,
      minimum: entry.minimum, maximum: entry.maximum, majorUnit: entry.majorUnit, numberFormat: entry.numberFormat };
  }
  const primaryIndices = chartSeriesIndices(kind, series).filter((index) => index !== secondary?.seriesIndex);
  const primaryValues = [...chartScaleValues(kind, series, primaryIndices),
    ...referenceLines.map((entry) => entry.value),
    ...chartAnalysisValues(kind, series, seriesPresentation, analysis, primaryIndices)];
  if (value.primaryScale === "logarithmic" && primaryValues.some((number) => number <= 0)) {
    throw new Error("chart-axis-options");
  }
  return { primaryScale: value.primaryScale, secondary };
}

function officeChartAxes(value, series, kind, referenceLines = [], analysis = null, seriesPresentation = null,
  axisOptions = null) {
  const keys = Object.keys(value || {}).sort().join(",");
  if (!value || keys !== "categoryTitle,gridlines,majorUnit,maximum,minimum,mode,numberFormat,valueTitle" ||
      !["auto", "manual"].includes(value.mode) || typeof value.gridlines !== "boolean" ||
      !OFFICE_CHART_NUMBER_FORMATS.includes(value.numberFormat) ||
      !(value.categoryTitle === "" || literal(value.categoryTitle, 1, 60)) ||
      !(value.valueTitle === "" || literal(value.valueTitle, 1, 60))) throw new Error("chart-axes");
  const primaryIndices = chartSeriesIndices(kind, series).filter((index) => index !== axisOptions?.secondary?.seriesIndex);
  const scaleType = axisOptions?.primaryScale || "linear";
  const scaleValues = [...chartScaleValues(kind, series, primaryIndices), ...referenceLines.map((entry) => entry.value),
    ...chartAnalysisValues(kind, series, seriesPresentation, analysis, primaryIndices)];
  if (scaleType === "logarithmic" && scaleValues.some((number) => number <= 0) ||
      !manualScale(value, scaleType, scaleValues, kind === "stacked-bar")) throw new Error("chart-axes");
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
    ...(value?.dataTablePresentation == null ? [] : ["dataTablePresentation"]),
    ...(value?.categoryAxisPresentation == null ? [] : ["categoryAxisPresentation"]),
    ...(value?.seriesManagement == null ? [] : ["seriesManagement"]),
    ...(value?.referenceLines == null ? [] : ["referenceLines"]), ...(value?.analysis == null ? [] : ["analysis"]),
    ...(value?.axisOptions == null ? [] : ["axisOptions"])];
  const actualKeys = Object.keys(value || {}).filter((key) =>
    !["source", "dataLabels", "legendPosition", "axes", "presentation", "seriesPresentation", "dataLabelPresentation",
      "dataTablePresentation", "categoryAxisPresentation", "seriesManagement",
      "referenceLines", "analysis", "axisOptions"].includes(key) || value[key] != null);
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
  if (value.dataTablePresentation != null) {
    result.dataTablePresentation = officeChartDataTablePresentation(value.dataTablePresentation);
  }
  if (value.categoryAxisPresentation != null) {
    result.categoryAxisPresentation = officeChartCategoryAxisPresentation(value.categoryAxisPresentation, value.kind);
  }
  if (value.seriesPresentation != null) {
    result.seriesPresentation = officeChartSeriesPresentation(value.seriesPresentation, value.kind, series);
  }
  const seriesManagement = value.seriesManagement == null ? null : officeChartSeriesManagement(
    value.seriesManagement, value.kind, series, result.seriesPresentation);
  if (seriesManagement) result.seriesManagement = seriesManagement;
  const referenceLines = value.referenceLines == null ? [] : officeChartReferenceLines(value.referenceLines);
  if (referenceLines.length) {
    if (circularKind(value.kind)) throw new Error("chart-reference-lines");
    result.referenceLines = referenceLines;
  }
  const analysis = value.analysis == null ? null : officeChartAnalysis(value.analysis, value.kind, series,
    result.seriesPresentation);
  const hiddenSeries = new Set(seriesManagement?.hidden || []);
  if (analysis && [analysis.trendline?.seriesIndex, analysis.errorBars?.seriesIndex].some((index) =>
    index != null && hiddenSeries.has(index))) throw new Error("chart-series-management");
  if (analysis) result.analysis = analysis;
  const axisOptions = value.axisOptions == null ? null : officeChartAxisOptions(value.axisOptions, value.kind, series,
    result.seriesPresentation, analysis, referenceLines);
  if (axisOptions?.secondary && hiddenSeries.has(axisOptions.secondary.seriesIndex)) {
    throw new Error("chart-series-management");
  }
  if (axisOptions) result.axisOptions = axisOptions;
  if (value.axes != null) {
    if (circularKind(value.kind)) throw new Error("chart-axes");
    result.axes = officeChartAxes(value.axes, series, value.kind, referenceLines, analysis, result.seriesPresentation,
      axisOptions);
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

function automaticLogScale(values) {
  if (!values.length || values.some((value) => value <= 0)) throw new Error("chart-axis-options");
  const minimumPower = Math.floor(Math.log10(Math.min(...values)));
  const maximumPower = Math.ceil(Math.log10(Math.max(...values)));
  const maximum = maximumPower === minimumPower ? 10 ** (maximumPower + 1) : 10 ** maximumPower;
  const minimum = 10 ** minimumPower, span = Math.round(Math.log10(maximum / minimum));
  const exponentStep = Math.max(1, Math.ceil(span / 12)), majorUnit = 10 ** exponentStep, ticks = [];
  for (let value = minimum, index = 0; index <= 12 && value <= maximum; index += 1, value *= majorUnit) ticks.push(value);
  if (ticks.at(-1) !== maximum) ticks.push(maximum);
  return { minimum, maximum, majorUnit, ticks };
}

function scaleFromSettings(settings, scaleType, values) {
  if (settings.mode === "manual") {
    const ticks = [];
    if (scaleType === "logarithmic") {
      for (let value = settings.minimum, index = 0; index <= 12 && value < settings.maximum; index += 1,
        value *= settings.majorUnit) ticks.push(value);
    } else {
      for (let index = 0; index <= 12 && settings.minimum + settings.majorUnit * index < settings.maximum; index += 1) {
        ticks.push(settings.minimum + settings.majorUnit * index);
      }
    }
    ticks.push(settings.maximum); return { ...settings, scaleType, ticks };
  }
  const automatic = scaleType === "logarithmic" ? automaticLogScale(values) : automaticScale(values);
  return { ...settings, ...automatic, scaleType };
}

export function officeChartAxisScale(value) {
  const chart = chartSeriesView(officeChartAttributes(value));
  if (circularKind(chart.kind)) return null;
  const axes = chart.axes || { mode: "auto", categoryTitle: "", valueTitle: "", minimum: null, maximum: null,
    majorUnit: null, gridlines: true, numberFormat: "general" };
  const primaryIndices = chartSeriesIndices(chart.kind, chart.series).filter((index) =>
    index !== chart.axisOptions?.secondary?.seriesIndex);
  const values = [...chartScaleValues(chart.kind, chart.series, primaryIndices),
    ...(chart.referenceLines || []).map((entry) => entry.value),
    ...chartAnalysisValues(chart.kind, chart.series, chart.seriesPresentation, chart.analysis, primaryIndices)];
  return scaleFromSettings(axes, chart.axisOptions?.primaryScale || "linear", values);
}

export function officeChartSecondaryAxisScale(value) {
  const chart = chartSeriesView(officeChartAttributes(value)), secondary = chart.axisOptions?.secondary;
  if (!secondary) return null;
  const values = [...chartScaleValues(chart.kind, chart.series, [secondary.seriesIndex]),
    ...chartAnalysisValues(chart.kind, chart.series, chart.seriesPresentation, chart.analysis, [secondary.seriesIndex])];
  return scaleFromSettings({ ...secondary, categoryTitle: "", valueTitle: secondary.title, gridlines: false },
    secondary.scale, values);
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
  const axisOptions = chart.axisOptions ? ` · ${chart.axisOptions.primaryScale === "logarithmic" ? "logarithmische Hauptachse" :
    "lineare Hauptachse"}${chart.axisOptions.secondary ? ` · Sekundärachse ${chart.axisOptions.secondary.title}: ${chart.series[chart.axisOptions.secondary.seriesIndex].name}` : ""}` : "";
  const references = chart.referenceLines?.length ? ` · Referenzlinien ${chart.referenceLines.map((entry) =>
    `${entry.label}: ${entry.value}`).join(", ")}` : "";
  const analysis = chart.analysis ? `${chart.analysis.trendline ? ` · Trendlinie ${chart.series[chart.analysis.trendline.seriesIndex].name}` : ""}${chart.analysis.errorBars ?
    ` · Fehlerbalken ${chart.series[chart.analysis.errorBars.seriesIndex].name}: ±${chart.analysis.errorBars.amount}` : ""}` : "";
  const dataTable = chart.dataTablePresentation ? " · sichtbare Datentabelle" : "";
  const categoryAxis = chart.categoryAxisPresentation ? ` · Kategorien ${chart.categoryAxisPresentation.direction === "reverse" ?
    "umgekehrt" : "normal"}, Beschriftung ${chart.categoryAxisPresentation.labelRotation}, Intervall ${chart.categoryAxisPresentation.labelInterval}` : "";
  const managedSeries = chart.seriesManagement ? chart.seriesManagement.order.filter((index) =>
    !chart.seriesManagement.hidden.includes(index)) : [];
  const seriesManagement = chart.seriesManagement ? ` · ${managedSeries.length} von ${chart.series.length} Datenreihen sichtbar, Reihenfolge ${managedSeries.map((index) => chart.series[index].name).join(", ")}` : "";
  return `${kindLabels[chart.kind]} · ${chart.title} · ${chart.categories.length} Kategorien · ${chart.series.length} ${chart.series.length === 1 ? "Datenreihe" : "Datenreihen"}${axes}${axisOptions}${references}${analysis}${dataTable}${categoryAxis}${seriesManagement}${chart.source ? ` · verknüpft mit ${chart.source.range}` : ""} · ${chart.altText}`;
}

function chartSeriesView(chart) {
  if (!chart.seriesManagement) return chart;
  const { seriesManagement, ...base } = chart, hidden = new Set(seriesManagement.hidden);
  const indices = seriesManagement.order.filter((index) => !hidden.has(index));
  const remap = new Map(indices.map((index, position) => [index, position]));
  const analysis = chart.analysis ? {
    trendline: chart.analysis.trendline ? { ...chart.analysis.trendline,
      seriesIndex: remap.get(chart.analysis.trendline.seriesIndex) } : null,
    errorBars: chart.analysis.errorBars ? { ...chart.analysis.errorBars,
      seriesIndex: remap.get(chart.analysis.errorBars.seriesIndex) } : null,
  } : null;
  const axisOptions = chart.axisOptions ? { ...chart.axisOptions,
    secondary: chart.axisOptions.secondary ? { ...chart.axisOptions.secondary,
      seriesIndex: remap.get(chart.axisOptions.secondary.seriesIndex) } : null } : null;
  return { ...base, series: indices.map((index) => chart.series[index]),
    ...(chart.seriesPresentation ? { seriesPresentation: indices.map((index) => chart.seriesPresentation[index]) } : {}),
    ...(analysis ? { analysis } : {}), ...(axisOptions ? { axisOptions } : {}) };
}

function chartPresentationView(chart) {
  const seriesView = chartSeriesView(chart);
  if (seriesView.categoryAxisPresentation?.direction !== "reverse") return seriesView;
  return { ...seriesView, categories: [...seriesView.categories].reverse(),
    series: seriesView.series.map((entry) => ({ ...entry, values: [...entry.values].reverse() })) };
}

function chartCategoryLabel(chart, category, index) {
  return index % (chart.categoryAxisPresentation?.labelInterval || 1) === 0 ? category : "";
}

function chartTable(chart, dom) {
  const visible = Boolean(chart.dataTablePresentation), table = dom.createElement("table");
  table.className = `office-chart-data${visible ? " office-chart-data-visible" : " visually-hidden"}`;
  table.id = `${chart.id}-data`;
  const caption = dom.createElement("caption"); caption.textContent = `Datentabelle für ${chart.title}`;
  if (visible) caption.className = "visually-hidden";
  const head = dom.createElement("thead"), headRow = dom.createElement("tr"), categoryHead = dom.createElement("th");
  categoryHead.scope = "col"; categoryHead.textContent = "Kategorie"; headRow.append(categoryHead);
  for (const entry of chart.series) { const cell = dom.createElement("th"); cell.scope = "col";
    if (chart.dataTablePresentation?.showLegendKeys) { const key = dom.createElement("i");
      key.className = "office-chart-data-key"; key.style.background = chartColor(chart, entry.color);
      key.setAttribute("aria-hidden", "true"); cell.append(key); }
    cell.append(entry.name); headRow.append(cell); }
  head.append(headRow);
  const body = dom.createElement("tbody");
  chart.categories.forEach((category, index) => {
    const row = dom.createElement("tr"), label = dom.createElement("th"); label.scope = "row"; label.textContent = category; row.append(label);
    for (const entry of chart.series) { const cell = dom.createElement("td"); cell.textContent = String(entry.values[index]); row.append(cell); }
    body.append(row);
  });
  table.append(caption, head, body);
  if (visible) {
    const cells = [...table.querySelectorAll("th,td")], width = chart.series.length + 1;
    cells.forEach((cell, index) => { cell.tabIndex = index === 0 ? 0 : -1; });
    table.addEventListener("keydown", (event) => {
      const current = cells.indexOf(event.target); if (current < 0) return;
      const row = Math.floor(current / width), column = current % width, lastRow = chart.categories.length;
      let target = current;
      if (event.key === "ArrowLeft") target = row * width + Math.max(0, column - 1);
      else if (event.key === "ArrowRight") target = row * width + Math.min(width - 1, column + 1);
      else if (event.key === "ArrowUp") target = Math.max(0, row - 1) * width + column;
      else if (event.key === "ArrowDown") target = Math.min(lastRow, row + 1) * width + column;
      else if (event.key === "Home") target = event.ctrlKey ? 0 : row * width;
      else if (event.key === "End") target = event.ctrlKey ? cells.length - 1 : row * width + width - 1;
      else return;
      event.preventDefault(); cells[current].tabIndex = -1; cells[target].tabIndex = 0; cells[target].focus();
    });
  }
  if (!visible) return table;
  const scroll = dom.createElement("div"); scroll.className = "office-chart-data-scroll";
  scroll.dataset.position = chart.dataTablePresentation.position;
  const help = dom.createElement("p"); help.className = "office-chart-data-help";
  help.textContent = `Datentabelle für ${chart.title}. Mit Pfeiltasten navigieren oder horizontal wischen.`;
  scroll.append(help, table); return scroll;
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
    const label = dom.createElement("span"); label.className = "office-chart-category";
    label.textContent = chartCategoryLabel(chart, category, categoryIndex);
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

function scalePosition(value, scale) {
  if (scale.scaleType === "logarithmic") return Math.log(value / scale.minimum) / Math.log(scale.maximum / scale.minimum);
  return (value - scale.minimum) / (scale.maximum - scale.minimum);
}

function chartSeriesScale(chart, scale, secondaryScale, seriesIndex) {
  return chart.axisOptions?.secondary?.seriesIndex === seriesIndex ? secondaryScale : scale;
}

function addChartAnalysis(svg, chart, scale, secondaryScale, xPosition, dom, namespace) {
  if (!chart.analysis) return;
  if (chart.analysis.trendline) {
    const analysis = chart.analysis.trendline;
    const { x, y } = chartAnalysisSeries(chart.kind, chart.series, chart.seriesPresentation, analysis.seriesIndex);
    const regression = linearRegression(x, y), minimum = Math.min(...x), maximum = Math.max(...x);
    const targetScale = chartSeriesScale(chart, scale, secondaryScale, analysis.seriesIndex);
    const yPosition = (value) => 280 - scalePosition(value, targetScale) * 240;
    const line = dom.createElementNS(namespace, "polyline");
    line.classList.add("office-chart-trendline");
    line.setAttribute("points", `${xPosition(minimum)},${yPosition(regression.intercept + regression.slope * minimum)} ` +
      `${xPosition(maximum)},${yPosition(regression.intercept + regression.slope * maximum)}`);
    line.setAttribute("fill", "none"); line.setAttribute("stroke", chartColor(chart, analysis.color));
    line.setAttribute("stroke-width", "4");
    if (analysis.lineStyle === "dashed") line.setAttribute("stroke-dasharray", "14 10");
    svg.append(line);
  }
  if (chart.analysis.errorBars) {
    const analysis = chart.analysis.errorBars;
    const { x, y } = chartAnalysisSeries(chart.kind, chart.series, chart.seriesPresentation, analysis.seriesIndex);
    const targetScale = chartSeriesScale(chart, scale, secondaryScale, analysis.seriesIndex);
    const yPosition = (value) => 280 - scalePosition(value, targetScale) * 240;
    y.forEach((value, index) => {
      const center = xPosition(x[index]), top = yPosition(value + analysis.amount), bottom = yPosition(value - analysis.amount);
      const bar = dom.createElementNS(namespace, "path"); bar.classList.add("office-chart-error-bar");
      bar.setAttribute("d", `M ${center} ${top} V ${bottom} M ${center - 7} ${top} H ${center + 7} ` +
        `M ${center - 7} ${bottom} H ${center + 7}`);
      bar.setAttribute("fill", "none"); bar.setAttribute("stroke", chartColor(chart, analysis.color));
      bar.setAttribute("stroke-width", "3"); svg.append(bar);
    });
  }
}

function lineChart(chart, scale, secondaryScale, dom) {
  const namespace = "http://www.w3.org/2000/svg", svg = dom.createElementNS(namespace, "svg");
  svg.classList.add("office-chart-lines"); svg.setAttribute("viewBox", "0 0 800 320"); svg.setAttribute("aria-hidden", "true");
  const denominator = Math.max(1, chart.categories.length - 1);
  chart.series.forEach((entry, seriesIndex) => {
    const style = chart.seriesPresentation?.[seriesIndex] || { renderAs: "line", marker: "circle", lineStyle: "solid" };
    const targetScale = chartSeriesScale(chart, scale, secondaryScale, seriesIndex);
    const points = entry.values.map((number, index) =>
      `${40 + index / denominator * 720},${280 - scalePosition(number, targetScale) * 240}`).join(" ");
    if (chart.kind === "area") { const baselineValue = targetScale.scaleType === "logarithmic" ? targetScale.minimum : 0;
      const baseline = 280 - scalePosition(baselineValue, targetScale) * 240;
      const area = dom.createElementNS(namespace, "polygon"); area.setAttribute("points", `40,${baseline} ${points} 760,${baseline}`);
      area.setAttribute("fill", chartColor(chart, entry.color)); area.setAttribute("fill-opacity", "0.22"); svg.append(area); }
    const color = chartColor(chart, entry.color); addChartLine(svg, points, style, color, dom, namespace);
    entry.values.forEach((number, index) => addChartMarker(svg, 40 + index / denominator * 720,
      280 - scalePosition(number, targetScale) * 240, style, color, dom, namespace));
  });
  addChartAnalysis(svg, chart, scale, secondaryScale, (value) => 40 + value / denominator * 720, dom, namespace);
  return svg;
}

function comboChart(chart, scale, secondaryScale, dom) {
  const namespace = "http://www.w3.org/2000/svg", svg = dom.createElementNS(namespace, "svg");
  svg.classList.add("office-chart-lines", "office-chart-combo"); svg.setAttribute("viewBox", "0 0 800 320");
  svg.setAttribute("aria-hidden", "true");
  const denominator = Math.max(1, chart.categories.length - 1);
  const barCount = chart.seriesPresentation.filter((entry) => entry.renderAs === "bar").length;
  chart.series.forEach((entry, seriesIndex) => {
    const style = chart.seriesPresentation[seriesIndex], color = chartColor(chart, entry.color);
    const targetScale = chartSeriesScale(chart, scale, secondaryScale, seriesIndex);
    if (style.renderAs === "bar") {
      const barIndex = chart.seriesPresentation.slice(0, seriesIndex).filter((item) => item.renderAs === "bar").length;
      entry.values.forEach((number, index) => {
        const center = 40 + index / denominator * 720, width = Math.min(54 / barCount, 28);
        const baseline = 280 - scalePosition(Math.max(0, targetScale.minimum), targetScale) * 240;
        const y = 280 - scalePosition(number, targetScale) * 240;
        const bar = dom.createElementNS(namespace, "rect");
        bar.setAttribute("x", String(center - barCount * width / 2 + barIndex * width));
        bar.setAttribute("y", String(Math.min(y, baseline))); bar.setAttribute("width", String(Math.max(4, width - 3)));
        bar.setAttribute("height", String(Math.max(2, Math.abs(baseline - y)))); bar.setAttribute("fill", color); svg.append(bar);
      });
    } else {
      const points = entry.values.map((number, index) =>
        `${40 + index / denominator * 720},${280 - scalePosition(number, targetScale) * 240}`).join(" ");
      addChartLine(svg, points, style, color, dom, namespace);
      entry.values.forEach((number, index) => addChartMarker(svg, 40 + index / denominator * 720,
        280 - scalePosition(number, targetScale) * 240, style, color, dom, namespace));
    }
  });
  addChartAnalysis(svg, chart, scale, secondaryScale, (value) => 40 + value / denominator * 720, dom, namespace);
  return svg;
}

function scatterChart(chart, scale, secondaryScale, dom) {
  const namespace = "http://www.w3.org/2000/svg", svg = dom.createElementNS(namespace, "svg");
  svg.classList.add("office-chart-lines", "office-chart-scatter"); svg.setAttribute("viewBox", "0 0 800 320");
  svg.setAttribute("aria-hidden", "true");
  const xValues = chart.series[0].values, xScale = automaticScale(xValues);
  const xSpan = xScale.maximum - xScale.minimum;
  chart.series.slice(1).forEach((entry, seriesIndex) => {
    const actualIndex = seriesIndex + 1, style = chart.seriesPresentation[seriesIndex], color = chartColor(chart, entry.color);
    const targetScale = chartSeriesScale(chart, scale, secondaryScale, actualIndex);
    const coordinates = entry.values.map((number, index) => ({
      x: 40 + (xValues[index] - xScale.minimum) / xSpan * 720,
      y: 280 - scalePosition(number, targetScale) * 240,
    }));
    addChartLine(svg, coordinates.map((point) => `${point.x},${point.y}`).join(" "), style, color, dom, namespace);
    coordinates.forEach((point) => addChartMarker(svg, point.x, point.y, style, color, dom, namespace));
  });
  addChartAnalysis(svg, chart, scale, secondaryScale,
    (value) => 40 + (value - xScale.minimum) / xSpan * 720, dom, namespace);
  return svg;
}

function axisFrame(chart, scale, secondaryScale, visual, dom) {
  const frame = dom.createElement("div"); frame.className = "office-chart-axis-frame";
  frame.dataset.secondaryAxis = String(Boolean(secondaryScale));
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
      line.style.setProperty("--reference-position", String(scalePosition(entry.value, scale) * 100));
      line.style.setProperty("--reference-color", chartColor(chart, entry.color));
      line.dataset.lineStyle = entry.lineStyle; label.textContent = `${entry.label}: ${formatChartNumber(entry.value, scale.numberFormat)}`;
      line.append(label); lines.append(line); }); stage.append(lines); }
  stage.append(visual); frame.append(valueTitle, ticks, stage);
  if (secondaryScale) {
    const secondaryTicks = dom.createElement("div"); secondaryTicks.className = "office-chart-secondary-axis-ticks";
    [...secondaryScale.ticks].reverse().forEach((tick) => { const label = dom.createElement("span");
      label.textContent = formatChartNumber(tick, secondaryScale.numberFormat); secondaryTicks.append(label); });
    const secondaryTitle = dom.createElement("span"); secondaryTitle.className = "office-chart-secondary-axis-title";
    secondaryTitle.textContent = secondaryScale.valueTitle; frame.append(secondaryTicks, secondaryTitle);
  }
  return frame;
}

function pieChart(chart, dom) {
  const pie = dom.createElement("div"); pie.className = `office-chart-pie${chart.kind === "doughnut" ? " office-chart-doughnut" : ""}`;
  const values = chart.series[0].values, total = values.reduce((sum, value) => sum + value, 0); let offset = 0;
  const parts = values.map((value, index) => { const start = offset; offset += value / total * 360;
    return `${chartColor(chart, OFFICE_CHART_COLORS[index % OFFICE_CHART_COLORS.length])} ${start}deg ${offset}deg`; });
  pie.style.background = `conic-gradient(${parts.join(",")})`; return pie;
}

export function officeChartElement(value, dom = document) {
  const savedChart = officeChartAttributes(value), chart = chartPresentationView(savedChart), figure = dom.createElement("figure");
  figure.className = "office-chart"; figure.dataset.officeChart = chart.id; figure.dataset.chartKind = chart.kind;
  figure.dataset.legendPosition = chart.legendPosition || "bottom";
  figure.dataset.chartStyle = chart.presentation?.style || "clean";
  figure.dataset.titleAlignment = chart.presentation?.titleAlignment || "center";
  figure.dataset.categoryLabelRotation = chart.categoryAxisPresentation?.labelRotation || "horizontal";
  figure.dataset.visibleSeries = String(chart.series.length);
  figure.setAttribute("role", "group"); figure.setAttribute("aria-label", officeChartDescription(savedChart));
  figure.setAttribute("aria-describedby", `${chart.id}-data`);
  const title = dom.createElement("figcaption"); title.className = "office-chart-title"; title.textContent = chart.title;
  const scale = officeChartAxisScale(chart), secondaryScale = officeChartSecondaryAxisScale(chart);
  const visual = ["bar", "stacked-bar"].includes(chart.kind) ? barChart(chart, scale, dom) :
    ["line", "area"].includes(chart.kind) ? lineChart(chart, scale, secondaryScale, dom) :
    chart.kind === "combo" ? comboChart(chart, scale, secondaryScale, dom) :
    chart.kind === "scatter" ? scatterChart(chart, scale, secondaryScale, dom) : pieChart(chart, dom);
  visual.classList.add("office-chart-visual");
  visual.setAttribute("aria-hidden", "true");
  const labels = dom.createElement("div"); labels.className = "office-chart-categories";
  const labelValues = chart.kind === "scatter" ? automaticScale(chart.series[0].values).ticks.map((tick) =>
    formatChartNumber(tick, scale.numberFormat)) : chart.categories;
  if (!["bar", "stacked-bar"].includes(chart.kind)) labelValues.forEach((category, index) => {
    const label = dom.createElement("span"); label.textContent = chartCategoryLabel(chart, category, index); labels.append(label);
  });
  const legend = dom.createElement("div"); legend.className = "office-chart-legend"; legend.hidden = !chart.legend;
  const legendEntries = circularKind(chart.kind) ? chart.categories.map((name, index) =>
    ({ name, color: OFFICE_CHART_COLORS[index % 4] })) : chart.kind === "scatter" ? chart.series.slice(1) : chart.series;
  for (const entry of legendEntries) { const item = dom.createElement("span"), swatch = dom.createElement("i");
    swatch.style.background = chartColor(chart, entry.color); item.append(swatch, entry.name); legend.append(item); }
  const plot = dom.createElement("div"); plot.className = "office-chart-plot";
  if (scale) plot.append(axisFrame(chart, scale, secondaryScale, visual, dom)); else plot.append(visual);
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
      const entryIndex = chart.kind === "scatter" ? chart.series.indexOf(entry) : chart.series.indexOf(entry);
      const numberFormat = chart.axisOptions?.secondary?.seriesIndex === entryIndex ? secondaryScale.numberFormat : scale?.numberFormat;
      const number = formatChartNumber(entry.values[index], numberFormat);
      const content = labelPresentation.content === "value" ? number :
        labelPresentation.content === "category-value" ? `${category}: ${number}` :
          labelPresentation.content === "series-value" ? `${entry.name}: ${number}` :
            `${category}${xValue} · ${entry.name}: ${number}`;
      label.textContent = content;
      values.append(label); });
  });
  const dataTable = chartTable(chartSeriesView(savedChart), dom), tableAbove = chart.dataTablePresentation?.position === "above";
  figure.append(title);
  if (tableAbove) figure.append(dataTable);
  if (labelPresentation.position === "top") figure.append(values);
  figure.append(body);
  if (labelPresentation.position !== "top") figure.append(values);
  if (!tableAbove) figure.append(dataTable);
  return figure;
}
