import { expect, test } from "@playwright/test";
import { compareOfficeDocuments, describeOfficeBlock } from "../office-comparison.mjs";
import { findDocumentMatches, replaceDocumentMatches } from "../office-search.mjs";
import { officeCharacterAttributes, officeCharacterDOMAttributes, officeCharacterDescription } from "../office-character.mjs";
import { characterDocument, characterText } from "./character-helper.mjs";

test("character attributes reject untrusted presentation and retain only browser null defaults", () => {
  for (const value of [{ fontFamily: "Arial" }, { fontSize: "12" }, { textColor: "#ff0000" }, { highlightColor: "url(SECRET)" }, { verticalPosition: "super" }, { letterSpacing: "0.1em" }, { fontSize: true }, { style: "url(SECRET)" }]) {
    expect(() => officeCharacterAttributes(value)).toThrow();
  }
  expect(officeCharacterAttributes({ fontFamily: null, fontSize: null, textColor: "blue" })).toEqual({ textColor: "blue" });
  expect(officeCharacterDOMAttributes({ fontFamily: "serif", fontSize: 18, textColor: "blue", highlightColor: "yellow", verticalPosition: "superscript", letterSpacing: "wide" })).toEqual({
    "data-office-font-family": "serif", "data-office-font-size": "18", "data-office-text-color": "blue", "data-office-highlight-color": "yellow", "data-office-vertical-position": "superscript", "data-office-letter-spacing": "wide",
  });
  expect(officeCharacterDescription({ fontFamily: "serif", fontSize: 18, textColor: "blue", highlightColor: "yellow", verticalPosition: "superscript", letterSpacing: "wide" })).toBe("Schriftart: Serif; Schriftgröße: 18 pt; Textfarbe: Blau; Hervorhebung: Gelb; Position: Hochgestellt; Zeichenabstand: Weit");
});

test("character comparison detects same-text size and color changes inside nested blocks", () => {
  const before = { type: "doc", content: [{ type: "blockquote", content: characterDocument().content }] };
  const after = structuredClone(before);
  after.content[0].content[0].content[0].marks[0].attrs = { fontFamily: "serif", fontSize: 24, textColor: "purple" };
  expect(compareOfficeDocuments(before, after).counts.changed).toBe(1);
  expect(describeOfficeBlock(after.content[0]).text).toContain("Schriftart: Serif; Schriftgröße: 24 pt; Textfarbe: Violett");
  expect(describeOfficeBlock(after.content[0]).text).toContain("Schriftgröße: 12 pt; Textfarbe: Rot");
});

test("replacement keeps adjacent mark attribute boundaries and inherits the first matched text style", () => {
  const before = characterDocument();
  const result = replaceDocumentMatches(before, findDocumentMatches(before, "café 😀 Beta"), "NEW");
  expect(result.document.content[0].content).toEqual([
    characterText("Alpha NEW"), characterText(" END", { fontSize: 12, textColor: "red" }),
  ]);
  expect(before).toEqual(characterDocument());
});

test("literal no-op replacement never flattens mixed character attributes", () => {
  const before = characterDocument();
  const result = replaceDocumentMatches(before, findDocumentMatches(before, "café 😀 Beta"), "café 😀 Beta");
  expect(result.noOp).toBe(true);
  expect(result.document).toEqual(before);
});
