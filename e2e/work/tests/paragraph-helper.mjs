import { expect } from "@playwright/test";

import { BASE_URL } from "./support.mjs";
import { OFFICE_HEADERS, OFFICE_PATH, officeEditor } from "./office-support.mjs";

export const PARAGRAPH_FORMAT = { textAlign: "center", lineSpacing: "1.5", spacingBefore: 6, spacingAfter: 12 };
export const PARAGRAPH_ALTERNATE = { textAlign: "right", lineSpacing: "2", spacingBefore: 18, spacingAfter: 24 };
export const FORMAT_IDS = {
  textAlign: "paragraph-align", lineSpacing: "paragraph-line-spacing",
  spacingBefore: "paragraph-spacing-before", spacingAfter: "paragraph-spacing-after",
};

export const paragraph = (text, attrs = {}, marks = []) => ({
  type: "paragraph", ...(Object.keys(attrs).length ? { attrs } : {}),
  content: [{ type: "text", text, ...(marks.length ? { marks: marks.map((type) => ({ type })) } : {}) }],
});

export function richParagraphDocument() {
  const cell = (text) => ({ type: "tableCell", attrs: { colspan: 1, rowspan: 1 }, content: [paragraph(text, {}, ["italic"])] });
  return { type: "doc", content: [
    { type: "heading", attrs: { level: 2 }, content: [{ type: "text", text: "Paragraph heading Café 😀" }] },
    paragraph('Literal <img src="https://paragraph.invalid/leak"> wording', {}, ["bold"]),
    { type: "bulletList", content: [{ type: "listItem", content: [paragraph("List paragraph")] }] },
    { type: "blockquote", content: [paragraph("Quoted paragraph")] },
    { type: "table", content: [{ type: "tableRow", content: [cell("First cell"), cell("Second cell")] }] },
    { type: "codeBlock", content: [{ type: "text", text: "Code has no paragraph formatting" }] },
  ] };
}

export function formatBlocks(document, attrs) {
  const result = structuredClone(document);
  const visit = (node) => {
    if (["paragraph", "heading"].includes(node.type)) node.attrs = { ...(node.attrs || {}), ...attrs };
    for (const child of node.content || []) visit(child);
  };
  visit(result);
  return result;
}

export function withoutParagraphFormat(document) {
  const result = structuredClone(document);
  const visit = (node) => {
    if (["paragraph", "heading"].includes(node.type) && node.attrs) {
      for (const key of Object.keys(FORMAT_IDS)) delete node.attrs[key];
      if (!Object.keys(node.attrs).length) delete node.attrs;
    }
    for (const child of node.content || []) visit(child);
  };
  visit(result);
  return result;
}

export async function createParagraphFixture(page, title, document = richParagraphDocument()) {
  const response = await page.request.post(`${BASE_URL}${OFFICE_PATH}`, {
    headers: OFFICE_HEADERS,
    data: { title, document, mutation_reference: `paragraph-fixture-${crypto.randomUUID()}`, human_confirmation: true },
  });
  expect(response.status()).toBe(200);
  expect(response.headers()["cache-control"]).toContain("no-store");
  return response.json();
}

export const paragraphBlocks = (page) => officeEditor(page).locator("p,h1,h2,h3");

export async function selectParagraphBlocks(page, first, last = first, { caret = false } = {}) {
  await officeEditor(page).evaluate((editor, { first, last, caret }) => {
    const blocks = editor.querySelectorAll("p,h1,h2,h3");
    const range = document.createRange();
    range.setStart(blocks[first], 0);
    range.setEnd(blocks[last], blocks[last].childNodes.length);
    if (caret) range.collapse(false);
    editor.focus();
    const selection = window.getSelection(); selection.removeAllRanges(); selection.addRange(range);
    document.dispatchEvent(new Event("selectionchange"));
  }, { first, last, caret });
  await expect(page.locator("#paragraph-format")).toBeEnabled();
}

export async function openParagraphDialog(page, count = null) {
  await page.locator("#paragraph-format").click();
  await expect(page.locator("#paragraph-dialog")).toBeVisible();
  if (count !== null) await expect(page.locator("#paragraph-selection")).toContainText(`${count} ${count === 1 ? "Absatz" : "Absätze"}`);
}

export async function chooseParagraphFormat(page, attrs) {
  for (const [key, value] of Object.entries(attrs)) await page.locator(`#${FORMAT_IDS[key]}`).selectOption(String(value));
}

export async function applyParagraphFormat(page, attrs, { count = null } = {}) {
  await openParagraphDialog(page, count);
  await chooseParagraphFormat(page, attrs);
  await page.locator("#paragraph-apply").click();
  await expect(page.locator("#paragraph-dialog")).toBeHidden();
  await expect(officeEditor(page)).toBeFocused();
}

export async function expectParagraphStyle(block, attrs) {
  const style = await block.evaluate((element) => {
    const computed = getComputedStyle(element);
    return { align: computed.textAlign, line: parseFloat(computed.lineHeight) / parseFloat(computed.fontSize), before: parseFloat(computed.marginTop), after: parseFloat(computed.marginBottom) };
  });
  if (attrs.textAlign !== undefined) expect(style.align).toBe(attrs.textAlign);
  if (attrs.lineSpacing !== undefined) expect(style.line).toBeCloseTo(Number(attrs.lineSpacing), 2);
  if (attrs.spacingBefore !== undefined) expect(style.before).toBeCloseTo(attrs.spacingBefore * 4 / 3, 1);
  if (attrs.spacingAfter !== undefined) expect(style.after).toBeCloseTo(attrs.spacingAfter * 4 / 3, 1);
}

export function paragraphWrites(page, objectId = null) {
  const writes = [];
  page.on("request", (request) => {
    const path = new URL(request.url()).pathname;
    if (request.method() === "POST" && (path === OFFICE_PATH || path === `${OFFICE_PATH}/${objectId}/versions`)) writes.push(request.postDataJSON());
  });
  return writes;
}
