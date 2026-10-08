import { expect } from "@playwright/test";
import { officeEditor } from "./office-support.mjs";

export const characterMark = (fontSize = 18, textColor = "blue") => ({ type: "textStyle", attrs: { fontSize, textColor } });
export const characterText = (text, attrs = { fontSize: 18, textColor: "blue" }) => ({ type: "text", text, marks: [{ type: "textStyle", attrs }] });
export const characterDocument = () => ({ type: "doc", content: [{ type: "paragraph", content: [
  characterText("Alpha café 😀 "), characterText("Beta END", { fontSize: 12, textColor: "red" }),
] }] });

export async function selectCharacters(page, block, from, to = from) {
  await officeEditor(page).evaluate((editor, { block, from, to }) => {
    const element = editor.querySelectorAll("p,h1,h2,h3,pre")[block];
    const walker = document.createTreeWalker(element, NodeFilter.SHOW_TEXT);
    const texts = []; let current;
    while ((current = walker.nextNode())) texts.push(current);
    const point = (offset) => {
      for (const text of texts) { if (offset <= text.length) return [text, offset]; offset -= text.length; }
      throw new Error("Invalid text offset");
    };
    const range = document.createRange(); range.setStart(...point(from)); range.setEnd(...point(to));
    editor.focus(); const selection = window.getSelection(); selection.removeAllRanges(); selection.addRange(range);
    document.dispatchEvent(new Event("selectionchange"));
  }, { block, from, to });
}

export async function openCharacters(page) {
  await expect(page.locator("#character-format")).toBeEnabled();
  await page.locator("#character-format").click();
  await expect(page.locator("#character-dialog")).toBeVisible();
}

export async function applyCharacters(page, choices) {
  await openCharacters(page);
  for (const [key, value] of Object.entries(choices)) await page.locator(`#character-${key}`).selectOption(String(value));
  await page.locator("#character-apply").click();
  await expect(page.locator("#character-dialog")).toBeHidden();
  await expect(officeEditor(page)).toBeFocused();
}

export async function expectCharacterStyle(locator, size, color, family = null, highlight = null, position = null, spacing = null) {
  await expect(locator).toHaveAttribute("data-office-font-size", String(size));
  await expect(locator).toHaveAttribute("data-office-text-color", color);
  if (family) await expect(locator).toHaveAttribute("data-office-font-family", family);
  if (highlight) await expect(locator).toHaveAttribute("data-office-highlight-color", highlight);
  if (position) await expect(locator).toHaveAttribute("data-office-vertical-position", position);
  if (spacing) await expect(locator).toHaveAttribute("data-office-letter-spacing", spacing);
  expect(await locator.evaluate((element) => parseFloat(getComputedStyle(element).fontSize))).toBeCloseTo(size * 4 / 3, 1);
  const colors = { blue: "rgb(29, 78, 216)", red: "rgb(185, 28, 28)", purple: "rgb(126, 34, 206)", green: "rgb(22, 101, 52)" };
  if (colors[color]) await expect(locator).toHaveCSS("color", colors[color]);
  if (family) {
    const expected = { sans: "Arial", serif: "Georgia", mono: "Consolas" }[family];
    expect(await locator.evaluate((element) => getComputedStyle(element).fontFamily)).toContain(expected);
  }
  if (highlight) {
    const expected = { yellow: "rgb(254, 240, 138)", lime: "rgb(217, 249, 157)", cyan: "rgb(186, 230, 253)", pink: "rgb(251, 207, 232)", lavender: "rgb(221, 214, 254)", gray: "rgb(229, 231, 235)" }[highlight];
    await expect(locator).toHaveCSS("background-color", expected);
  }
  if (position) await expect(locator).toHaveCSS("vertical-align", position === "superscript" ? "super" : "sub");
  if (spacing) {
    const actual = await locator.evaluate((element) => parseFloat(getComputedStyle(element).letterSpacing));
    expect(actual).toBeCloseTo((spacing === "wide" ? .08 : -.02) * size * 4 / 3, 1);
  }
}
