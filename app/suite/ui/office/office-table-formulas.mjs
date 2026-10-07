import { officeTableCellAttributes, officeTableCellText, officeTableFormulaSource, officeTableReorderInfo } from "./office-tables.mjs";

const formulaErrors = new Set(["#BEZUG!", "#DIV/0!", "#ZYKLUS!", "#WERT!", "#LIMIT!"]);
const numericText = /^[+-]?(?:0|[1-9][0-9]*)(?:[.,][0-9]+)?$/u;
const formulaReferencePattern = /(\$?)([A-T])(\$?)([1-9][0-9]{0,2})/gu;

function formulaError(code) { const error = new Error(code); error.formulaCode = code; return error; }

function formatFormulaNumber(value) {
  if (!Number.isFinite(value) || Math.abs(value) > 1e15) throw formulaError("#LIMIT!");
  const stable = Math.abs(value) < 5e-11 ? 0 : Math.round(value * 1e10) / 1e10;
  return stable.toFixed(10).replace(/\.0+$/u, "").replace(/(\.[0-9]*?)0+$/u, "$1");
}

function tokenize(source) {
  const tokens = []; let index = 1;
  while (index < source.length) {
    const rest = source.slice(index); const space = /^\s+/u.exec(rest);
    if (space) { index += space[0].length; continue; }
    const number = /^(?:0|[1-9][0-9]*)(?:\.[0-9]+)?/u.exec(rest);
    if (number) { tokens.push({ type: "number", value: Number(number[0]) }); index += number[0].length; continue; }
    if (rest.startsWith("#BEZUG!")) { tokens.push({ type: "error", value: "#BEZUG!" }); index += 7; continue; }
    const ref = /^\$?[A-T]\$?(?:[1-9][0-9]{0,2})/u.exec(rest);
    if (ref) { tokens.push({ type: "ref", value: ref[0] }); index += ref[0].length; continue; }
    const name = /^(?:SUM|AVERAGE|MIN|MAX|COUNT)/u.exec(rest);
    if (name) { tokens.push({ type: "name", value: name[0] }); index += name[0].length; continue; }
    if ("+-*/(),:".includes(rest[0])) { tokens.push({ type: rest[0], value: rest[0] }); index += 1; continue; }
    throw formulaError("#WERT!");
  }
  tokens.push({ type: "end" }); return tokens;
}

function referenceCoordinates(reference, rows, columns) {
  const match = /^\$?([A-T])\$?([1-9][0-9]{0,2})$/u.exec(reference);
  const row = match ? Number(match[2]) - 1 : -1; const column = match ? match[1].charCodeAt(0) - 65 : -1;
  if (row < 0 || row >= rows || column < 0 || column >= columns) throw formulaError("#BEZUG!");
  return { row, column };
}

function parseFormula(source, context) {
  const tokens = tokenize(officeTableFormulaSource(source)); let position = 0;
  const peek = () => tokens[position]; const take = (type) => {
    if (peek().type !== type) throw formulaError("#WERT!"); return tokens[position++];
  };
  const primary = () => {
    if (peek().type === "error") throw formulaError(take("error").value);
    if (peek().type === "number") return take("number").value;
    if (peek().type === "ref") return context.value(take("ref").value);
    if (peek().type === "(") { take("("); const value = expression(); take(")"); return value; }
    if (peek().type === "name") {
      const name = take("name").value; take("("); const values = [];
      if (peek().type !== ")") {
        while (true) {
          if (peek().type === "ref" && tokens[position + 1]?.type === ":") {
            const from = take("ref").value; take(":"); const to = take("ref").value;
            values.push(...context.range(from, to));
          } else values.push(expression());
          if (peek().type !== ",") break; take(",");
        }
      }
      take(")");
      if (!values.length || values.length > 4000) throw formulaError("#LIMIT!");
      if (name === "SUM") return values.reduce((total, value) => total + value, 0);
      if (name === "AVERAGE") return values.reduce((total, value) => total + value, 0) / values.length;
      if (name === "MIN") return Math.min(...values);
      if (name === "MAX") return Math.max(...values);
      if (name === "COUNT") return values.length;
    }
    throw formulaError("#WERT!");
  };
  const unary = () => peek().type === "+" ? (take("+"), unary()) : peek().type === "-" ? (take("-"), -unary()) : primary();
  const term = () => { let value = unary(); while (["*", "/"].includes(peek().type)) {
    const operator = take(peek().type).type; const right = unary();
    if (operator === "/" && right === 0) throw formulaError("#DIV/0!"); value = operator === "*" ? value * right : value / right;
  } return value; };
  const expression = () => { let value = term(); while (["+", "-"].includes(peek().type)) {
    const operator = take(peek().type).type; const right = term(); value = operator === "+" ? value + right : value - right;
  } return value; };
  const value = expression(); if (peek().type !== "end") throw formulaError("#WERT!"); return value;
}

export function recalculateOfficeTableFormulas(value) {
  const info = officeTableReorderInfo(value); const result = structuredClone(value);
  const cells = result.content.map((row) => row.content); const states = new Map(); const memo = new Map();
  let formulaCount = 0;
  const key = (row, column) => `${row}:${column}`;
  const numericValue = (row, column) => {
    const id = key(row, column); const cell = cells[row][column]; const attrs = cell.attrs || {};
    if (attrs.formula != null) return evaluate(row, column);
    const text = officeTableCellText(cell);
    if (!text) return 0;
    if (!numericText.test(text)) throw formulaError("#WERT!");
    const number = Number(text.replace(",", ".")); if (!Number.isFinite(number)) throw formulaError("#WERT!"); return number;
  };
  const evaluate = (row, column) => {
    const id = key(row, column); if (memo.has(id)) return memo.get(id);
    if (states.get(id) === "visiting") throw formulaError("#ZYKLUS!"); states.set(id, "visiting");
    const source = cells[row][column].attrs?.formula;
    if (source == null) return numericValue(row, column);
    const context = {
      value(reference) { const point = referenceCoordinates(reference, info.rows, info.columns); return numericValue(point.row, point.column); },
      range(from, to) {
        const first = referenceCoordinates(from, info.rows, info.columns), last = referenceCoordinates(to, info.rows, info.columns);
        const values = [];
        for (let rowIndex = Math.min(first.row, last.row); rowIndex <= Math.max(first.row, last.row); rowIndex += 1) {
          for (let columnIndex = Math.min(first.column, last.column); columnIndex <= Math.max(first.column, last.column); columnIndex += 1) {
            values.push(numericValue(rowIndex, columnIndex));
          }
        }
        return values;
      },
    };
    const evaluated = parseFormula(source, context); states.set(id, "done"); memo.set(id, evaluated); return evaluated;
  };
  for (let row = 0; row < info.rows; row += 1) for (let column = 0; column < info.columns; column += 1) {
    const cell = cells[row][column]; if (cell.attrs?.formula == null) continue;
    formulaCount += 1; if (formulaCount > 1000 || cell.type !== "tableCell") throw new TypeError("Invalid Office table formula");
    let formulaResult;
    try { formulaResult = formatFormulaNumber(evaluate(row, column)); }
    catch (error) { formulaResult = formulaErrors.has(error.formulaCode) ? error.formulaCode : "#WERT!"; }
    cell.attrs = officeTableCellAttributes({ ...cell.attrs, formula: cell.attrs.formula, formulaResult });
    cell.content = [{ type: "paragraph", ...(formulaResult ? { content: [{ type: "text", text: formulaResult }] } : {}) }];
  }
  return result;
}

export function setOfficeTableFormula(value, options) {
  const info = officeTableReorderInfo(value);
  if (!options || Object.keys(options).sort().join(",") !== "column,formula,row" ||
      !Number.isInteger(options.row) || !Number.isInteger(options.column) || options.row < 0 || options.row >= info.rows ||
      options.column < 0 || options.column >= info.columns || value.content[options.row].content[options.column].type !== "tableCell") {
    throw new TypeError("Invalid Office table formula target");
  }
  const result = structuredClone(value); const cell = result.content[options.row].content[options.column];
  cell.attrs = { ...officeTableCellAttributes(cell.attrs), formula: officeTableFormulaSource(options.formula), formulaResult: "#WERT!" };
  return recalculateOfficeTableFormulas(result);
}

export function clearOfficeTableFormula(value, options) {
  const info = officeTableReorderInfo(value);
  if (!options || Object.keys(options).sort().join(",") !== "column,row" || !Number.isInteger(options.row) ||
      !Number.isInteger(options.column) || options.row < 0 || options.row >= info.rows || options.column < 0 || options.column >= info.columns) {
    throw new TypeError("Invalid Office table formula target");
  }
  const result = structuredClone(value); const cell = result.content[options.row].content[options.column];
  const attrs = { ...(cell.attrs || {}) }; delete attrs.formula; delete attrs.formulaResult;
  cell.attrs = officeTableCellAttributes(attrs); return recalculateOfficeTableFormulas(result);
}

export function officeTableFromTSV(text) {
  if (typeof text !== "string" || !text.includes("\t") || text.length > 100000) return null;
  const rows = []; let row = [], field = "", quoted = false;
  const source = text.replaceAll("\r\n", "\n").replaceAll("\r", "\n");
  for (let index = 0; index <= source.length; index += 1) {
    const character = index === source.length ? "\n" : source[index];
    if (quoted) {
      if (character === '"' && source[index + 1] === '"') { field += '"'; index += 1; }
      else if (character === '"') quoted = false;
      else field += character;
    } else if (character === '"' && !field) quoted = true;
    else if (character === "\t") { row.push(field); field = ""; }
    else if (character === "\n") { row.push(field); rows.push(row); row = []; field = ""; }
    else field += character;
  }
  if (quoted) throw new TypeError("Invalid Office clipboard quoting");
  if (rows.at(-1)?.every((entry) => !entry)) rows.pop();
  const width = rows[0]?.length || 0;
  if (!rows.length || rows.length > 200 || width < 1 || width > 20 || rows.some((entry) => entry.length !== width)) {
    throw new TypeError("Invalid Office clipboard table");
  }
  const table = { type: "table", content: rows.map((entries) => ({ type: "tableRow", content: entries.map((entry) => {
    const formula = entry.trim().startsWith("=") ? officeTableFormulaSource(entry) : null;
    return { type: "tableCell", ...(formula ? { attrs: { formula, formulaResult: "#WERT!" } } : {}),
      content: [{ type: "paragraph", ...(!formula && entry ? { content: [{ type: "text", text: entry }] } : {}) }] };
  }) })) };
  return recalculateOfficeTableFormulas(table);
}

function shiftedFormula(source, rowOffset, columnOffset) {
  const normalized = officeTableFormulaSource(source);
  return normalized.replace(formulaReferencePattern, (_match, columnAnchor, letter, rowAnchor, rowText) => {
    const column = letter.charCodeAt(0) - 65 + (columnAnchor ? 0 : columnOffset);
    const row = Number(rowText) - 1 + (rowAnchor ? 0 : rowOffset);
    if (column < 0 || column >= 20 || row < 0 || row >= 200) throw new TypeError("Shifted Office table formula is out of bounds");
    return `${columnAnchor}${String.fromCharCode(65 + column)}${rowAnchor}${row + 1}`;
  });
}

function simpleTable(value) {
  const info = officeTableReorderInfo(value);
  if (value.content.some((row) => row.content.some((cell) => {
    const attrs = officeTableCellAttributes(cell.attrs);
    return attrs.colspan !== 1 || attrs.rowspan !== 1;
  }))) throw new TypeError("Office table paste requires a simple grid");
  return info;
}

function emptyCell(type) {
  return { type, attrs: { colspan: 1, rowspan: 1 }, content: [{ type: "paragraph" }] };
}

function pastedCell(target, source, rowOffset, columnOffset) {
  const sourceAttrs = officeTableCellAttributes(source.attrs); const attrs = { ...sourceAttrs, colspan: 1, rowspan: 1 };
  if (sourceAttrs.formula) {
    attrs.formula = shiftedFormula(sourceAttrs.formula, rowOffset, columnOffset);
    attrs.formulaResult = "#WERT!";
  }
  return { type: target.type, attrs: officeTableCellAttributes(attrs), content: structuredClone(source.content) };
}

export function pasteOfficeTableCells(target, source, options) {
  const targetInfo = simpleTable(target); const sourceInfo = simpleTable(source);
  if (!options || Object.keys(options).sort().join(",") !== "bottom,left,right,top" ||
      ![options.top, options.left, options.bottom, options.right].every(Number.isInteger) ||
      options.top < 0 || options.left < 0 || options.bottom <= options.top || options.right <= options.left ||
      options.bottom > targetInfo.rows || options.right > targetInfo.columns) {
    throw new TypeError("Invalid Office table paste target");
  }
  const selectedRows = options.bottom - options.top, selectedColumns = options.right - options.left;
  const singleTarget = selectedRows === 1 && selectedColumns === 1;
  if (!singleTarget && !((sourceInfo.rows === selectedRows && sourceInfo.columns === selectedColumns) ||
      (sourceInfo.rows === 1 && sourceInfo.columns === 1))) {
    throw new TypeError("Office table paste dimensions do not match the selection");
  }
  const pasteRows = singleTarget ? sourceInfo.rows : selectedRows;
  const pasteColumns = singleTarget ? sourceInfo.columns : selectedColumns;
  const requiredRows = Math.max(targetInfo.rows, options.top + pasteRows);
  const requiredColumns = Math.max(targetInfo.columns, options.left + pasteColumns);
  if (requiredRows > 200 || requiredColumns > 20) throw new TypeError("Office table paste exceeds grid limits");
  const result = structuredClone(target);
  const headerRow = result.content[0].content.every((cell) => cell.type === "tableHeader");
  const headerColumn = result.content.every((row) => row.content[0].type === "tableHeader");
  for (const row of result.content) while (row.content.length < requiredColumns) {
    row.content.push(emptyCell(headerRow && result.content.indexOf(row) === 0 ? "tableHeader" : "tableCell"));
  }
  while (result.content.length < requiredRows) {
    const rowIndex = result.content.length;
    result.content.push({ type: "tableRow", content: Array.from({ length: requiredColumns }, (_entry, column) =>
      emptyCell(headerColumn && column === 0 && rowIndex > 0 ? "tableHeader" : "tableCell")) });
  }
  for (let row = 0; row < pasteRows; row += 1) for (let column = 0; column < pasteColumns; column += 1) {
    const sourceRow = sourceInfo.rows === 1 ? 0 : row;
    const sourceColumn = sourceInfo.columns === 1 ? 0 : column;
    const targetRow = options.top + row, targetColumn = options.left + column;
    result.content[targetRow].content[targetColumn] = pastedCell(result.content[targetRow].content[targetColumn],
      source.content[sourceRow].content[sourceColumn], targetRow - sourceRow, targetColumn - sourceColumn);
  }
  return recalculateOfficeTableFormulas(result);
}

function formulaStructureEntry(entry, maximum) {
  if (!entry || Object.keys(entry).sort().join(",") !== "duplicate,source" ||
      !Number.isInteger(entry.source) || entry.source < 0 || entry.source >= maximum || typeof entry.duplicate !== "boolean") {
    throw new TypeError("Invalid Office table formula structure map");
  }
  return entry;
}

function formulaReference(row, column, rowAnchor = "", columnAnchor = "") {
  if (row == null || column == null || row < 0 || row >= 200 || column < 0 || column >= 20) return "#BEZUG!";
  return `${columnAnchor}${String.fromCharCode(65 + column)}${rowAnchor}${row + 1}`;
}

export function remapOfficeTableFormulas(original, transformed, options) {
  const before = simpleTable(original); const after = simpleTable(transformed);
  if (!options || Object.keys(options).sort().join(",") !== "columns,rows" ||
      !Array.isArray(options.rows) || options.rows.length !== after.rows ||
      !Array.isArray(options.columns) || options.columns.length !== after.columns) {
    throw new TypeError("Invalid Office table formula structure map");
  }
  const rows = options.rows.map((entry) => formulaStructureEntry(entry, before.rows));
  const columns = options.columns.map((entry) => formulaStructureEntry(entry, before.columns));
  const canonicalRows = new Map(); const canonicalColumns = new Map();
  rows.forEach((entry, index) => { if (!entry.duplicate && !canonicalRows.has(entry.source)) canonicalRows.set(entry.source, index); });
  columns.forEach((entry, index) => { if (!entry.duplicate && !canonicalColumns.has(entry.source)) canonicalColumns.set(entry.source, index); });
  const result = structuredClone(transformed);
  for (let row = 0; row < after.rows; row += 1) for (let column = 0; column < after.columns; column += 1) {
    const cell = result.content[row].content[column]; if (cell.attrs?.formula == null) continue;
    const rowEntry = rows[row], columnEntry = columns[column];
    const formula = officeTableFormulaSource(cell.attrs.formula).replace(formulaReferencePattern,
      (_match, columnAnchor, letter, rowAnchor, rowText) => {
        const sourceRow = Number(rowText) - 1, sourceColumn = letter.charCodeAt(0) - 65;
        const canonicalRow = canonicalRows.get(sourceRow), canonicalColumn = canonicalColumns.get(sourceColumn);
        const sourceFormulaRow = canonicalRows.get(rowEntry.source), sourceFormulaColumn = canonicalColumns.get(columnEntry.source);
        const targetRow = rowEntry.duplicate && !rowAnchor && canonicalRow != null && sourceFormulaRow != null ?
          canonicalRow + row - sourceFormulaRow : canonicalRow;
        const targetColumn = columnEntry.duplicate && !columnAnchor && canonicalColumn != null && sourceFormulaColumn != null ?
          canonicalColumn + column - sourceFormulaColumn : canonicalColumn;
        return formulaReference(targetRow, targetColumn, rowAnchor, columnAnchor);
      });
    cell.attrs = officeTableCellAttributes({ ...cell.attrs, formula, formulaResult: "#WERT!" });
  }
  return recalculateOfficeTableFormulas(result);
}
