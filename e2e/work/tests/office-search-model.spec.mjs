import { expect, test } from "@playwright/test";

import { findDocumentMatches, OfficeSearchLimitError, replaceDocumentMatches } from "../office-search.mjs";

const text = (value, ...marks) => ({ type: "text", text: value, ...(marks.length ? { marks: marks.map((type) => ({ type })) } : {}) });
const paragraph = (...content) => ({ type: "paragraph", content });
const document = (...content) => ({ type: "doc", content });
const plain = (value) => document(paragraph(text(value)));
const table = (...values) => ({
  type: "table", content: [{ type: "tableRow", content: values.map((value, index) => ({
    type: index ? "tableCell" : "tableHeader", attrs: { colspan: 1, rowspan: 1 }, content: [paragraph(text(value))],
  })) }],
});

function freeze(value) {
  if (value && typeof value === "object") {
    Object.values(value).forEach(freeze);
    Object.freeze(value);
  }
  return value;
}

const replace = (before, query, replacement, options = {}) =>
  replaceDocumentMatches(before, findDocumentMatches(before, query, options), replacement);

test("native search treats regex punctuation and replacement substitution syntax literally", () => {
  const before = freeze(plain("[a.*] [a.*] aaaa $ \\"));
  const matches = findDocumentMatches(before, "[a.*]");
  expect(matches).toEqual([{ from: 1, to: 6 }, { from: 7, to: 12 }]);
  const result = replaceDocumentMatches(before, matches, "<b>$&\\$1</b>");
  expect(result.document).toEqual(plain("<b>$&\\$1</b> <b>$&\\$1</b> aaaa $ \\"));
  expect(result.changedCount).toBe(2);
  expect(result.noOp).toBe(false);
  expect(findDocumentMatches(before, "\\")).toHaveLength(1);
  expect(findDocumentMatches(before, "$" )).toHaveLength(1);
});

test("Unicode simple case folding retains original UTF-16 offsets around dotted I and emoji", () => {
  const before = plain("İ A😀i I ı");
  expect(findDocumentMatches(before, "i")).toEqual([{ from: 6, to: 7 }, { from: 8, to: 9 }]);
  expect(findDocumentMatches(before, "i", { caseSensitive: true })).toEqual([{ from: 6, to: 7 }]);
  expect(findDocumentMatches(before, "İ")).toEqual([{ from: 1, to: 2 }]);
  expect(findDocumentMatches(before, "😀")).toEqual([{ from: 4, to: 6 }]);
  expect(replace(before, "i", "X").document).toEqual(plain("İ A😀X X ı"));
  expect(replace(before, "😀", "💡").document).toEqual(plain("İ A💡i I ı"));
});

test("Unicode folding handles German sharp S without length-changing expansions", () => {
  const before = plain("Straße STRAẞE STRASSE");
  expect(findDocumentMatches(before, "straße", { wholeWord: true })).toHaveLength(2);
  expect(findDocumentMatches(before, "Straße", { caseSensitive: true })).toHaveLength(1);
  expect(findDocumentMatches(before, "ss")).toHaveLength(1);
  expect(replace(before, "straße", "Weg").document).toEqual(plain("Weg Weg STRASSE"));
  expect(findDocumentMatches(plain("𐐀 𐐨"), "𐐨")).toEqual([{ from: 1, to: 3 }, { from: 4, to: 6 }]);
});

test("whole-word boundaries include Unicode letters numbers marks connectors and join controls", () => {
  const before = plain("Café CAFÉ Caféteria café猫 Café_ Café2 Café\u0301 Café\u200d Café\u200c");
  expect(findDocumentMatches(before, "Café")).toHaveLength(9);
  expect(findDocumentMatches(before, "Café", { wholeWord: true })).toHaveLength(2);
  expect(findDocumentMatches(before, "Café", { wholeWord: true, caseSensitive: true })).toHaveLength(1);
  expect(findDocumentMatches(plain("𐐀Café Café𐐀"), "Café", { wholeWord: true })).toEqual([]);
});

test("combining sequences keep literal identity and cannot be mistaken for whole-word prefixes", () => {
  const before = plain("e\u0301 é e");
  expect(findDocumentMatches(before, "e", { wholeWord: true })).toEqual([{ from: 6, to: 7 }]);
  expect(findDocumentMatches(before, "e\u0301", { wholeWord: true })).toEqual([{ from: 1, to: 3 }]);
  expect(findDocumentMatches(before, "é")).toEqual([{ from: 4, to: 5 }]);
  expect(replace(before, "e\u0301", "X").document).toEqual(plain("X é e"));
});

test("matches cross adjacent formatting nodes and replacement inherits the first character's marks", () => {
  const before = freeze(document(paragraph(text("Ca", "bold"), text("fé CAFÉ", "italic", "underline"))));
  const matches = findDocumentMatches(before, "Café");
  expect(matches).toEqual([{ from: 1, to: 5 }, { from: 6, to: 10 }]);
  const result = replaceDocumentMatches(before, matches, "Wort", { currentIndex: 0 });
  expect(result.document).toEqual(document(paragraph(text("Wort", "bold"), text(" CAFÉ", "italic", "underline"))));
  expect(result.changedCount).toBe(1);
  expect(before.content[0].content[0].text).toBe("Ca");
});

test("matches never cross paragraphs hard breaks or table cells", () => {
  const before = freeze(document(
    paragraph(text("ab")), paragraph(text("cd")),
    paragraph(text("ab"), { type: "hardBreak" }, text("cd")),
    table("ab", "cd"),
  ));
  expect(findDocumentMatches(before, "bc")).toEqual([]);
  expect(findDocumentMatches(before, "abcd")).toEqual([]);
  expect(findDocumentMatches(before, "ab")).toHaveLength(3);
  const result = replace(before, "ab", "X");
  expect(result.changedCount).toBe(3);
  expect(result.document.content[2]).toEqual(paragraph(text("X"), { type: "hardBreak" }, text("cd")));
  expect(result.document.content[3]).toEqual(table("X", "cd"));
});

test("nested lists tables and leaf nodes contribute exact ProseMirror positions", () => {
  const before = document(
    paragraph(text("A")), { type: "horizontalRule" },
    { type: "bulletList", content: [{ type: "listItem", content: [paragraph(text("B"))] }] },
    table("C", "D"), { type: "codeBlock", content: [text("E")] },
  );
  expect(findDocumentMatches(before, "B")).toEqual([{ from: 7, to: 8 }]);
  expect(findDocumentMatches(before, "C")).toEqual([{ from: 15, to: 16 }]);
  expect(findDocumentMatches(before, "D")).toEqual([{ from: 20, to: 21 }]);
  expect(findDocumentMatches(before, "E")).toEqual([{ from: 26, to: 27 }]);
  const result = replace(before, "D", "Delta");
  expect(result.document.content[3]).toEqual(table("C", "Delta"));
  expect(result.document.content[2]).toBe(before.content[2]);
  expect(findDocumentMatches(result.document, "E", { caseSensitive: true })).toEqual([{ from: 30, to: 31 }]);
});

test("replacement preserves headings list attributes quotes code text and unsupported-looking literal content", () => {
  const before = freeze(document(
    { type: "heading", attrs: { level: 2 }, content: [text("target", "strike")] },
    { type: "orderedList", attrs: { start: 7 }, content: [{ type: "listItem", content: [paragraph(text("target"))] }] },
    { type: "blockquote", content: [paragraph(text("untouched", "code"))] },
    { type: "codeBlock", attrs: { language: null }, content: [text("target\nnext\tline")] },
  ));
  const result = replace(before, "target", "<img src=x>");
  expect(result.changedCount).toBe(3);
  expect(result.document.content[0]).toEqual({ type: "heading", attrs: { level: 2 }, content: [text("<img src=x>", "strike")] });
  expect(result.document.content[1].attrs).toEqual({ start: 7 });
  expect(result.document.content[2]).toBe(before.content[2]);
  expect(result.document.content[3]).toEqual({ type: "codeBlock", attrs: { language: null }, content: [text("<img src=x>\nnext\tline")] });
  expect(findDocumentMatches(before, "target\nnext")).toHaveLength(1);
});

test("deleting a complete match retains required empty paragraphs and table structure", () => {
  const before = document(paragraph(text("a")), table("a", "a"));
  const result = replace(before, "a", "");
  expect(result.changedCount).toBe(3);
  expect(result.document.content[0]).toEqual(paragraph());
  for (const cell of result.document.content[1].content[0].content) expect(cell.content).toEqual([paragraph()]);
  expect(findDocumentMatches(result.document, "a")).toEqual([]);
});

test("literal no-op retains mixed formatting and the original document reference", () => {
  const before = freeze(document(paragraph(text("ab", "bold"), text("cd", "italic"))));
  const result = replace(before, "abcd", "abcd");
  expect(result).toEqual({ document: before, changedCount: 0, noOp: true });
  expect(result.document).toBe(before);
  expect(result.document.content[0].content).toHaveLength(2);
});

test("changedCount excludes already identical case-insensitive matches", () => {
  const result = replace(plain("a A a"), "a", "a");
  expect(result.document).toEqual(plain("a a a"));
  expect(result.changedCount).toBe(1);
  expect(result.noOp).toBe(false);
});

test("replacing only the selected occurrence leaves other matches and later blocks untouched", () => {
  const before = freeze(document(paragraph(text("one one one")), paragraph(text("one", "underline"))));
  const matches = findDocumentMatches(before, "one");
  const result = replaceDocumentMatches(before, matches, "TWO", { currentIndex: 1 });
  expect(result.document.content[0]).toEqual(paragraph(text("one TWO one")));
  expect(result.document.content[1]).toBe(before.content[1]);
  expect(result.changedCount).toBe(1);
  expect(() => replaceDocumentMatches(before, matches, "x", { currentIndex: 4 })).toThrow(RangeError);
});

test("non-overlapping matches do not recursively replace newly inserted query text", () => {
  const before = plain("aaaaa");
  expect(findDocumentMatches(before, "aa")).toEqual([{ from: 1, to: 3 }, { from: 3, to: 5 }]);
  expect(replace(before, "aa", "aaa").document).toEqual(plain("aaaaaaa"));
  expect(replace(before, "aa", "X").document).toEqual(plain("XXa"));
});

test("more than one thousand occurrences are counted and replaced without a hidden clip", () => {
  const before = plain("word ".repeat(1500));
  const matches = findDocumentMatches(before, "word", { wholeWord: true });
  expect(matches).toHaveLength(1500);
  expect(matches[1499]).toEqual({ from: 7496, to: 7500 });
  const result = replaceDocumentMatches(before, matches, "x");
  expect(result.changedCount).toBe(1500);
  expect(result.document).toEqual(plain("x ".repeat(1500)));
});

test("the full one-hundred-thousand-character limit replaces linearly and remains one text node", () => {
  const before = freeze(plain("a".repeat(100000)));
  const matches = findDocumentMatches(before, "a");
  expect(matches).toHaveLength(100000);
  expect(matches[99999]).toEqual({ from: 100000, to: 100001 });
  const result = replaceDocumentMatches(before, matches, "b");
  expect(result.changedCount).toBe(100000);
  expect(result.document).toEqual(plain("b".repeat(100000)));
  expect(result.document.content[0].content).toHaveLength(1);
  expect(replace(result.document, "b", "b").document).toBe(result.document);
});

test("aggregate expansion is rejected before constructing the expanded output", () => {
  const before = freeze(plain("a".repeat(100000)));
  const matches = findDocumentMatches(before, "a");
  expect(() => replaceDocumentMatches(before, matches, "x".repeat(100000))).toThrow(OfficeSearchLimitError);
  expect(() => replaceDocumentMatches(before, matches, "xx")).toThrow(OfficeSearchLimitError);
  expect(before.content[0].content[0].text).toHaveLength(100000);
});

test("bounds count Unicode code points and Python ASCII-escaped canonical bytes", () => {
  const before = freeze(plain("😀".repeat(20000) + "a".repeat(70000)));
  expect(before.content[0].content[0].text.length).toBe(110000);
  const result = replaceDocumentMatches(before, findDocumentMatches(before, "a"), "b", { currentIndex: 0 });
  expect(result.changedCount).toBe(1);
  expect(result.document.content[0].content[0].text).toBe("😀".repeat(20000) + "b" + "a".repeat(69999));
  const byteLimited = freeze(plain("é".repeat(66000)));
  expect(() => replace(byteLimited, "é", "😀")).toThrow(OfficeSearchLimitError);
  expect(replace(byteLimited, "é", "ä").changedCount).toBe(66000);
});

test("byte preflight handles escaped quotes backslashes tabs and deletions between hard breaks", () => {
  const before = document(paragraph(text("x"), { type: "hardBreak" }, text("x"), { type: "hardBreak" }, text("x")));
  expect(replace(before, "x", "\"\\\n\t").document).toEqual(document(paragraph(
    text("\"\\\n\t"), { type: "hardBreak" }, text("\"\\\n\t"), { type: "hardBreak" }, text("\"\\\n\t"),
  )));
  expect(replace(before, "x", "").document).toEqual(document(paragraph({ type: "hardBreak" }, { type: "hardBreak" })));
});

test("invalid controls surrogates and overlong query or replacement are rejected without mutation", () => {
  const before = freeze(plain("word"));
  for (const invalid of ["\u0000", "\r", "\u001f", "\ud800", "\udc00", "x".repeat(100001)]) {
    expect(() => replace(before, "word", invalid)).toThrow(OfficeSearchLimitError);
    expect(() => findDocumentMatches(before, invalid)).toThrow(OfficeSearchLimitError);
  }
  expect(before).toEqual(plain("word"));
});

test("node and depth limits are checked before searching or replacing", () => {
  const atNodeLimit = document(...Array.from({ length: 9999 }, () => paragraph()));
  expect(findDocumentMatches(atNodeLimit, "x")).toEqual([]);
  const tooMany = document(...Array.from({ length: 10000 }, () => paragraph()));
  expect(() => findDocumentMatches(tooMany, "x")).toThrow(OfficeSearchLimitError);
  let nested = paragraph(text("x"));
  for (let index = 0; index < 30; index += 1) nested = { type: "blockquote", content: [nested] };
  expect(findDocumentMatches(document(nested), "x")).toHaveLength(1);
  expect(() => findDocumentMatches(document({ type: "blockquote", content: [nested] }), "x")).toThrow(OfficeSearchLimitError);
});

test("invalid overlapping split-surrogate and cross-block positions cannot edit a document", () => {
  const before = freeze(document(paragraph(text("😀ab")), paragraph(text("cd"))));
  for (const matches of [
    [{ from: 1, to: 2 }], [{ from: 2, to: 3 }], [{ from: 4, to: 8 }],
    [{ from: 3, to: 5 }, { from: 4, to: 5 }], [{ from: 0, to: 1 }], [{ from: 3, to: 3 }],
  ]) expect(() => replaceDocumentMatches(before, matches, "x")).toThrow(RangeError);
  expect(before).toEqual(document(paragraph(text("😀ab")), paragraph(text("cd"))));
});

test("empty queries and empty match sets create no replacement or dirty state", () => {
  const before = freeze(plain("original"));
  expect(findDocumentMatches(before, "")).toEqual([]);
  expect(replaceDocumentMatches(before, [], "replacement")).toEqual({ document: before, changedCount: 0, noOp: true });
  expect(replaceDocumentMatches(before, [], "replacement").document).toBe(before);
});
