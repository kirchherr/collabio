import { expect, test } from "@playwright/test";

import { compareOfficeDocuments, describeOfficeBlock } from "../office-comparison.mjs";

const paragraph = (text, marks = []) => ({
  type: "paragraph", content: [{ type: "text", text, ...(marks.length ? { marks: marks.map((type) => ({ type })) } : {}) }],
});
const document = (...content) => ({ type: "doc", content });
const table = (first = "Name", second = "Wert") => ({
  type: "table", content: [{ type: "tableRow", content: [
    { type: "tableHeader", attrs: { colspan: 1, rowspan: 1, colwidth: null }, content: [paragraph(first)] },
    { type: "tableCell", attrs: { colspan: 1, rowspan: 1 }, content: [paragraph(second)] },
  ] }],
});

function preservesEveryBlock(result, before, after) {
  const left = result.rows.filter((row) => row.before !== null).map((row) => row.before);
  const right = result.rows.filter((row) => row.after !== null).map((row) => row.after);
  expect(left).toEqual(before.content);
  expect(right).toEqual(after.content);
  left.forEach((block, index) => expect(block).toBe(before.content[index]));
  right.forEach((block, index) => expect(block).toBe(after.content[index]));
  expect(Object.values(result.counts).reduce((sum, count) => sum + count, 0)).toBe(result.rows.length);
  for (const kind of ["equal", "added", "removed", "changed"]) {
    expect(result.counts[kind]).toBe(result.rows.filter((row) => row.kind === kind).length);
  }
}

function freeze(value) {
  if (value && typeof value === "object") {
    Object.values(value).forEach(freeze);
    Object.freeze(value);
  }
  return value;
}

test("native comparison keeps identical blocks and never mutates either input", () => {
  const before = freeze(document(paragraph("Absatz", ["bold", "italic"]), table()));
  const after = freeze(structuredClone(before));
  const result = compareOfficeDocuments(before, after);
  expect(result.counts).toEqual({ equal: 2, added: 0, removed: 0, changed: 0 });
  expect(result.simplified).toBe(false);
  preservesEveryBlock(result, before, after);
});

test("native comparison ignores object key and mark-set ordering", () => {
  const before = document(paragraph("Formatiert", ["bold", "italic"]), table());
  const after = { content: [
    { content: [{ marks: [{ type: "italic" }, { type: "bold" }], text: "Formatiert", type: "text" }], type: "paragraph" },
    { content: [{ content: [
      { content: [paragraph("Name")], attrs: { colwidth: null, rowspan: 1, colspan: 1 }, type: "tableHeader" },
      { content: [paragraph("Wert")], attrs: { rowspan: 1, colspan: 1 }, type: "tableCell" },
    ], type: "tableRow" }], type: "table" },
  ], type: "doc" };
  const result = compareOfficeDocuments(before, after);
  expect(result.counts).toEqual({ equal: 2, added: 0, removed: 0, changed: 0 });
  expect(describeOfficeBlock(before.content[0])).toEqual(describeOfficeBlock(after.content[0]));
  preservesEveryBlock(result, before, after);
});

test("native comparison aligns insertions at the beginning middle and end", () => {
  const before = document(paragraph("A"), paragraph("B"), paragraph("C"));
  const after = document(paragraph("Anfang"), paragraph("A"), paragraph("Mitte"), paragraph("B"), paragraph("C"), paragraph("Ende"));
  const result = compareOfficeDocuments(before, after);
  expect(result.rows.map((row) => row.kind)).toEqual(["added", "equal", "added", "equal", "equal", "added"]);
  expect(result.counts).toEqual({ equal: 3, added: 3, removed: 0, changed: 0 });
  preservesEveryBlock(result, before, after);
});

test("native comparison preserves removed blocks and pairs a replaced text block", () => {
  const before = document(paragraph("Entfernt"), paragraph("Anker"), paragraph("Alt"), paragraph("Schluss"));
  const after = document(paragraph("Anker"), paragraph("Neu"), paragraph("Schluss"));
  const result = compareOfficeDocuments(before, after);
  expect(result.rows.map((row) => row.kind)).toEqual(["removed", "equal", "changed", "equal"]);
  expect(describeOfficeBlock(result.rows[2].before).text).toBe("Alt");
  expect(describeOfficeBlock(result.rows[2].after).text).toBe("Neu");
  preservesEveryBlock(result, before, after);
});

test("native comparison exposes formatting-only changes and where marks moved", () => {
  const plain = paragraph("Gleicher Text");
  const bold = paragraph("Gleicher Text", ["bold"]);
  expect(compareOfficeDocuments(document(plain), document(bold)).counts.changed).toBe(1);
  expect(describeOfficeBlock(plain).text).toBe("Gleicher Text");
  expect(describeOfficeBlock(bold).text).toBe("⟦Fett⟧Gleicher Text⟦/Fett⟧");
  const before = { type: "paragraph", content: [...paragraph("A", ["bold"]).content, ...paragraph("B").content] };
  const after = { type: "paragraph", content: [...paragraph("A").content, ...paragraph("B", ["bold"]).content] };
  expect(compareOfficeDocuments(document(before), document(after)).counts.changed).toBe(1);
  expect(describeOfficeBlock(before).text).not.toBe(describeOfficeBlock(after).text);
  for (const [mark, label] of [["italic", "Kursiv"], ["underline", "Unterstrichen"], ["strike", "Durchgestrichen"], ["code", "Code"]]) {
    expect(describeOfficeBlock(paragraph("X", [mark])).text).toBe(`⟦${label}⟧X⟦/${label}⟧`);
  }
});

test("native comparison exposes heading levels and ordered list starts", () => {
  const heading = (level) => ({ type: "heading", attrs: { level }, content: paragraph("Titel").content });
  const list = (start) => ({ type: "orderedList", attrs: { start }, content: [{ type: "listItem", content: [paragraph("Punkt")] }] });
  const before = document(heading(1), list(3));
  const after = document(heading(2), list(8));
  const result = compareOfficeDocuments(before, after);
  expect(result.counts.changed).toBe(2);
  expect(describeOfficeBlock(before.content[0]).label).toBe("Überschrift Ebene 1");
  expect(describeOfficeBlock(after.content[0]).label).toBe("Überschrift Ebene 2");
  expect(describeOfficeBlock(before.content[1]).text).toBe("3. Punkt");
  expect(describeOfficeBlock(after.content[1]).text).toBe("8. Punkt");
  preservesEveryBlock(result, before, after);
});

test("native comparison retains table cells headers and literal hostile text", () => {
  const before = document(table());
  const after = document(table("Name", "<img src=x onerror=alert(1)>"));
  const result = compareOfficeDocuments(before, after);
  expect(result.counts).toEqual({ equal: 0, added: 0, removed: 0, changed: 1 });
  expect(describeOfficeBlock(after.content[0])).toEqual({
    label: "Tabelle · 1 Zeile × 2 Spalten",
    text: "Zeile 1: Kopfzelle 1: Name │ Zelle 2: <img src=x onerror=alert(1)>",
  });
  const headerChanged = structuredClone(before);
  headerChanged.content[0].content[0].content[0].type = "tableCell";
  expect(compareOfficeDocuments(before, headerChanged).counts.changed).toBe(1);
  expect(describeOfficeBlock(headerChanged.content[0]).text).toContain("Zeile 1: Zelle 1: Name");
  preservesEveryBlock(result, before, after);
});

test("native descriptions retain nested lists quotations code and hard line breaks", () => {
  const block = { type: "bulletList", content: [{ type: "listItem", content: [
    { type: "paragraph", content: [{ type: "text", text: "Zeile eins" }, { type: "hardBreak" }, { type: "text", text: "Zeile zwei" }] },
    { type: "orderedList", attrs: { start: 4 }, content: [{ type: "listItem", content: [paragraph("Unterpunkt")] }] },
    { type: "blockquote", content: [paragraph("Zitat")] },
    { type: "codeBlock", attrs: { language: null }, content: [{ type: "text", text: "if (x) {\n  y();\n}" }] },
    { type: "horizontalRule" },
  ] }] };
  const description = describeOfficeBlock(block);
  expect(description.label).toBe("Aufzählung");
  expect(description.text).toContain("• Zeile eins↵\n  Zeile zwei");
  expect(description.text).toContain("  4. Unterpunkt");
  expect(description.text).toContain("  │ Zitat");
  expect(description.text).toContain("Codeblock:\n  if (x) {\n    y();\n  }");
  expect(description.text).toContain("────────");
  expect(describeOfficeBlock({ type: "paragraph" }).text).toBe("(Leerer Absatz)");
});

test("native comparison retains full long text without truncation", () => {
  const text = "a".repeat(99999);
  const before = document(paragraph(`${text}x`));
  const after = document(paragraph(`${text}y`));
  const result = compareOfficeDocuments(before, after);
  expect(result.counts.changed).toBe(1);
  expect(result.simplified).toBe(false);
  expect(describeOfficeBlock(result.rows[0].before).text).toBe(`${text}x`);
  expect(describeOfficeBlock(result.rows[0].after).text).toBe(`${text}y`);
  preservesEveryBlock(result, before, after);
});

test("large native comparisons use exact unique anchors within the fixed matrix budget", () => {
  const before = document(...Array.from({ length: 2500 }, (_, index) => paragraph(`Abschnitt ${index}`)));
  const altered = new Set([100, 600, 1100, 1600, 2100]);
  const after = document(paragraph("Neuer Anfang"), ...before.content.map((block, index) =>
    altered.has(index) ? paragraph(`Änderung ${index}`) : structuredClone(block)), paragraph("Neues Ende"));
  const result = compareOfficeDocuments(before, after);
  expect(result.simplified).toBe(true);
  expect(result.counts).toEqual({ equal: 2495, added: 2, removed: 0, changed: 5 });
  preservesEveryBlock(result, before, after);
});

test("large repeated blocks keep complete ordered projections in the simplified fallback", () => {
  const before = document(...Array.from({ length: 4000 }, (_, index) => paragraph(`Wiederholt ${index % 3}`)));
  const after = document(paragraph("Neuer Anfang"), ...Array.from({ length: 3998 }, () => paragraph("Wiederholt 1")), paragraph("Neues Ende"));
  const result = compareOfficeDocuments(before, after);
  expect(result.simplified).toBe(true);
  expect(result.rows).toHaveLength(4000);
  expect(result.counts.changed).toBeGreaterThan(0);
  expect(compareOfficeDocuments(before, after)).toEqual(result);
  preservesEveryBlock(result, before, after);
});

test("small duplicate-heavy native comparisons preserve every block across edit patterns", () => {
  let seed = 253;
  const next = () => { seed = (seed * 1664525 + 1013904223) >>> 0; return seed; };
  for (let example = 0; example < 80; example += 1) {
    const before = document(...Array.from({ length: 1 + next() % 20 }, () => paragraph(String(next() % 5))));
    const after = document(...Array.from({ length: 1 + next() % 20 }, () => paragraph(String(next() % 5))));
    const result = compareOfficeDocuments(before, after);
    expect(result.simplified).toBe(false);
    preservesEveryBlock(result, before, after);
    for (const row of result.rows.filter((candidate) => candidate.kind === "equal")) {
      expect(row.before).toEqual(row.after);
    }
  }
});
