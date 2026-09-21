import { expect } from "@playwright/test";

import { BASE_URL, ARTIFACT_DIR } from "./support.mjs";
import { OFFICE_HEADERS, OFFICE_PATH, captureOfficeResponse, officeContentPath } from "./office-support.mjs";

export const exactPrintRead = (objectId, versionId) => (url) => url.pathname === officeContentPath(objectId) && url.searchParams.get("version_id") === versionId;
export const PRINT_WHITESPACE = "WHITESPACE_PROOF: two  spaces\ttab\nliteral newline";

export function pdfPageCount(pdf, width, height) {
  expect(pdf.subarray(0, 5).toString()).toBe("%PDF-");
  const structure = pdf.toString("latin1");
  const boxes = [...structure.matchAll(/\/MediaBox\s*\[\s*0\s+0\s+([\d.]+)\s+([\d.]+)\s*\]/g)];
  expect(boxes.length).toBeGreaterThan(0);
  for (const box of boxes) {
    expect(Number(box[1])).toBeCloseTo(width, 0);
    expect(Number(box[2])).toBeCloseTo(height, 0);
  }
  return [...structure.matchAll(/\/Type\s*\/Page\b/g)].length;
}

export function expectPdfStructure(pdf, tags) {
  // Chromium emits these structure dictionaries outside content streams. A
  // tagged request or MarkInfo flag alone does not prove accessible content.
  const structure = pdf.toString("latin1");
  expect(structure).toMatch(/\/StructTreeRoot\b/);
  expect(structure).toMatch(/\/Type\s*\/StructElem\b/);
  for (const tag of tags) expect(structure, `PDF semantic structure ${tag}`).toMatch(new RegExp(`/S\\s*/${tag}\\b`));
}

export function collectOfficePrintRequests(page) {
  const requests = [];
  page.on("request", (request) => {
    if (new URL(request.url()).pathname.startsWith(OFFICE_PATH)) requests.push({ method: request.method(), url: request.url() });
  });
  return requests;
}

export async function installPrintProbe(page, { pdfName = null } = {}) {
  const calls = [];
  await page.exposeFunction("officeE2EPrint", async (snapshot) => {
    const call = { snapshot, pdf: null };
    calls.push(call);
    if (pdfName) {
      // The product awaits native print, so the real authorized print root stays
      // installed while Chromium renders this same page. No alternate renderer.
      await page.emulateMedia({ media: "print" });
      call.layout = await page.evaluate(() => {
        const root = document.querySelector("#office-print-root");
        return {
          rootVisible: getComputedStyle(root).display !== "none",
          shellVisible: getComputedStyle(document.querySelector("#office-shell")).display !== "none",
          dialogVisible: getComputedStyle(document.querySelector("#print-dialog")).display !== "none",
          guidanceVisible: getComputedStyle(document.querySelector("#office-print-guidance")).display !== "none",
          overflow: [...root.querySelectorAll("table,pre")].map((element) => element.scrollWidth > element.clientWidth + 1),
        };
      });
      try {
        call.pdf = await page.pdf({ path: `${ARTIFACT_DIR}/${pdfName}`, preferCSSPageSize: true, printBackground: true, tagged: true });
      } finally { await page.emulateMedia({ media: "screen" }); }
    }
  });
  await page.evaluate(() => {
    window.print = () => {
      const root = document.querySelector("#office-print-root");
      return window.officeE2EPrint({
        text: root.textContent,
        html: root.innerHTML,
        ready: document.body.classList.contains("office-print-ready"),
        className: root.className,
        headings: [...root.querySelectorAll("h1,h2,h3")].map((element) => element.textContent),
        marks: [...root.querySelectorAll("strong,em,u,s,code")].map((element) => ({ tag: element.tagName, text: element.textContent })),
        orderedStarts: [...root.querySelectorAll("ol")].map((element) => element.start),
        tables: [...root.querySelectorAll("table")].map((table) => ({ rows: table.rows.length, columns: table.rows[0]?.cells.length || 0, headers: table.querySelectorAll("th").length })),
        whitespace: [...root.querySelectorAll("p")].filter((element) => element.textContent.startsWith("WHITESPACE_PROOF:")).map((element) => ({ text: element.textContent, whiteSpace: getComputedStyle(element).whiteSpace })),
        unsafeElements: root.querySelectorAll("script,img,iframe,object,embed,input,textarea,button,a[href]").length,
      });
    };
  });
  return calls;
}

export async function openPrintPreview(page, objectId, versionId, { keyboard = null, status = 200, extraHeaders = {} } = {}) {
  const captured = await captureOfficeResponse(page, exactPrintRead(objectId, versionId), { extraHeaders });
  if (keyboard) await page.keyboard.press(keyboard);
  else await page.locator("#document-print").click();
  const response = await captured.received;
  expect(response.status).toBe(status);
  expect(response.headers["cache-control"]).toContain("no-store");
  if (status === 200) {
    expect(response.json.document.object_id).toBe(objectId);
    expect(response.json.version.version_id).toBe(versionId);
    await expect(page.locator("#print-dialog")).toBeVisible();
    await expect(page.locator("#print-submit")).toBeEnabled();
    await expect(page.locator("#print-version")).toContainText(versionId);
  } else {
    await expect(page.locator("#print-submit")).toBeDisabled();
    await expect(page.locator("#print-preview")).toHaveText("");
  }
  return response.json;
}

export async function submitOfficePrint(page, objectId, versionId, { status = 200, extraHeaders = {} } = {}) {
  const captured = await captureOfficeResponse(page, exactPrintRead(objectId, versionId), { extraHeaders });
  await page.locator("#print-submit").click();
  const response = await captured.received;
  expect(response.status).toBe(status);
  expect(response.headers["cache-control"]).toContain("no-store");
  if (status === 200) expect(response.json.version.version_id).toBe(versionId);
  if (status === 503) expect(response.json.detail).toBe("Office storage unavailable");
  if (status === 404) expect(response.json.detail).toBe("Document not found");
  return response.json;
}

export async function refreshPrintPreview(page, objectId, versionId) {
  const captured = await captureOfficeResponse(page, exactPrintRead(objectId, versionId));
  await page.locator("#print-refresh").click();
  const response = await captured.received;
  expect(response.status).toBe(200);
  expect(response.headers["cache-control"]).toContain("no-store");
  expect(response.json.version.version_id).toBe(versionId);
  await expect(page.locator("#print-submit")).toBeEnabled();
  return response.json;
}

export async function expectPrintCleared(page) {
  await expect(page.locator("#office-print-root")).toHaveText("");
  await expect(page.locator("body")).not.toHaveClass(/office-print-ready/);
}

export async function openPrintHistory(page, objectId, versionId) {
  if (!await page.locator("#history-tab").isVisible()) await page.locator("#inspector-toggle").click();
  await page.locator("#history-tab").click();
  const pending = page.waitForResponse((response) => exactPrintRead(objectId, versionId)(new URL(response.url())));
  await page.locator(`[data-version-id="${versionId}"]`).click();
  expect((await pending).status()).toBe(200);
}

export async function createPrintFixture(page) {
  const paragraph = (text) => ({ type: "paragraph", content: [{ type: "text", text }] });
  const cell = (type, text) => ({ type, content: [paragraph(text)] });
  const content = [
    { type: "heading", attrs: { level: 1 }, content: [{ type: "text", text: "Printable section" }] },
    { type: "paragraph", content: [
      ...[["Bold", "bold"], [" Italic", "italic"], [" Underline", "underline"], [" Strike", "strike"], [" Code", "code"]].map(([text, type]) => ({ type: "text", text, marks: [{ type }] })),
      { type: "text", text: ' <img src="https://print.invalid/leak" onerror="window.printExecuted=true"> literal 😀' },
      { type: "hardBreak" }, { type: "text", text: "Line after hard break" },
    ] },
    { type: "blockquote", content: [paragraph("Quoted saved source")] },
    { type: "bulletList", content: [{ type: "listItem", content: [paragraph("Bullet source")] }] },
    { type: "orderedList", attrs: { start: 7 }, content: [{ type: "listItem", content: [paragraph("Numbered source")] }] },
    { type: "codeBlock", content: [{ type: "text", text: `LONG_CODE_${"identifier_".repeat(100)}` }] },
    paragraph(PRINT_WHITESPACE),
    { type: "table", content: [
      { type: "tableRow", content: Array.from({ length: 20 }, (_, index) => cell("tableHeader", `C${index + 1}`)) },
      { type: "tableRow", content: Array.from({ length: 20 }, (_, index) => cell("tableCell", `Value${index + 1}`)) },
      { type: "tableRow", content: Array.from({ length: 20 }, (_, index) => cell("tableCell", `End${index + 1}`)) },
    ] },
    { type: "horizontalRule" },
    ...Array.from({ length: 80 }, (_, index) => paragraph(`Printed paragraph ${String(index + 1).padStart(2, "0")}. ${"This is saved synthetic text for real browser pagination. ".repeat(3)}`)),
    paragraph("LAST_PRINT_PROOF_SENTINEL"),
  ];
  const response = await page.request.post(`${BASE_URL}${OFFICE_PATH}`, {
    headers: OFFICE_HEADERS,
    data: { title: "Synthetic print <b>literal title</b>", document: { type: "doc", content }, mutation_reference: `synthetic-print-${crypto.randomUUID()}`, human_confirmation: true },
  });
  expect(response.status()).toBe(200);
  expect(response.headers()["cache-control"]).toContain("no-store");
  return response.json();
}

export async function observeLatePrint(page, text) {
  await page.evaluate((protectedText) => {
    window.staleOfficePrint = false;
    for (const id of ["print-preview", "office-print-root"]) {
      new MutationObserver(() => {
        window.staleOfficePrint ||= document.querySelector(`#${id}`).textContent.includes(protectedText);
      }).observe(document.querySelector(`#${id}`), { subtree: true, childList: true, characterData: true });
    }
  }, text);
}
