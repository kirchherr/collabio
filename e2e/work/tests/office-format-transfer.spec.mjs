import { expect, test } from "@playwright/test";
import { BASE_URL, BLOCKED_BASE_URL, monitorPage } from "./support.mjs";
import { OFFICE_PATH, OFFICE_READER_ID, officeContent, officeEditor, officeVersions, openOffice, openOfficeDocument, saveOffice, setOfficeAcl } from "./office-support.mjs";
import { paragraph, paragraphWrites, selectParagraphBlocks, expectParagraphStyle } from "./paragraph-helper.mjs";
import { selectCharacters, applyCharacters } from "./character-helper.mjs";
import { SAMPLE_MARKS, SAMPLE_PARAGRAPH, captureSample, transfer, transferFixture } from "./format-transfer-helper.mjs";

test("Office transfers characters and paragraph presentation together with exact undo and immutable saved versions", async ({ page }) => {
  const verify = monitorPage(page, { baseUrls: [BASE_URL] });
  const first = await transferFixture(page);
  const writes = paragraphWrites(page, first.document.object_id);
  const original = await officeEditor(page).innerHTML();
  await captureSample(page);
  await expect(page.locator("#document-save")).toBeDisabled();
  await selectParagraphBlocks(page, 1); // Heading keeps its own level and text.
  await transfer(page, "both");
  const heading = officeEditor(page).locator("h2");
  await expect(heading).toHaveText("Paragraph heading Café 😀");
  await expect(heading.locator('strong u span[data-office-font-size="24"]')).toHaveCount(1);
  await expectParagraphStyle(heading, SAMPLE_PARAGRAPH);
  await officeEditor(page).press("Control+z");
  expect(await officeEditor(page).innerHTML()).toBe(original);
  await expect(page.locator("#document-save")).toBeDisabled();
  await officeEditor(page).press("Control+Shift+z");
  expect(writes).toEqual([]);
  const next = await saveOffice(page, { objectId: first.document.object_id });
  expect(next.version.previous_version_id).toBe(first.version.version_id);
  expect(next.content.content[1].attrs).toEqual({ level: 2, ...SAMPLE_PARAGRAPH });
  expect(next.content.content[1].content[0].marks).toEqual(SAMPLE_MARKS);
  expect(next.content.content[0]).toEqual(first.content.content[0]);
  expect((await officeContent(page, first.document.object_id, { versionId: first.version.version_id })).content).toEqual(first.content);
  expect(writes).toHaveLength(1);
  verify();
});

test("Office character-only transfer affects exact Unicode text and leaves paragraph layout and adjacent text intact", async ({ page }) => {
  const first = await transferFixture(page);
  await captureSample(page);
  await selectCharacters(page, 8, 18, 25); // Café and emoji within final paragraph.
  await transfer(page, "characters");
  const last = officeEditor(page).locator("p").last();
  await expect(last.locator('span[data-office-font-size="24"]')).toHaveText("Café 😀");
  await expect(last).not.toHaveAttribute("data-office-align");
  const next = await saveOffice(page, { objectId: first.document.object_id });
  expect(next.content.content.at(-1).content).toEqual([
    { type: "text", text: "Plain destination " }, { type: "text", text: "Café 😀", marks: SAMPLE_MARKS }, { type: "text", text: " END" },
  ]);
});

test("Office paragraph-only transfer preserves marks and applying a standard sample clears only chosen formatting", async ({ page }) => {
  const first = await transferFixture(page);
  await captureSample(page);
  await selectParagraphBlocks(page, 2); // Bold literal paragraph.
  await transfer(page, "paragraphs");
  await expectParagraphStyle(officeEditor(page).locator("p").nth(1), SAMPLE_PARAGRAPH);
  await expect(officeEditor(page).locator("p").nth(1).locator("strong")).toHaveCount(1);
  await expect(officeEditor(page).locator("p").nth(1).locator("span")).toHaveCount(0);
  await selectCharacters(page, 8, 2);
  await transfer(page, "copy"); // Standard text and paragraph are meaningful values.
  await selectParagraphBlocks(page, 0);
  await transfer(page, "both");
  await expect(officeEditor(page).locator("p").first()).not.toHaveAttribute("data-office-align");
  await expect(officeEditor(page).locator("p").first().locator("strong,u,span")).toHaveCount(0);
  const next = await saveOffice(page, { objectId: first.document.object_id });
  expect(next.content.content[0]).toEqual(paragraph("Format source"));
  expect(next.content.content[2].content).toEqual(first.content.content[2].content);
});

test("Office copied format stays clean on capture clear mixed selection and no-op", async ({ page }) => {
  await transferFixture(page);
  await captureSample(page);
  await transfer(page, "both");
  await expect(page.locator("#document-notice")).toContainText("Keine Änderung");
  await expect(page.locator("#document-save")).toBeDisabled();
  await selectParagraphBlocks(page, 0, 1);
  await transfer(page, "copy");
  await expect(page.locator("#document-notice")).toContainText("unterschiedliche Formate");
  await expect(page.locator('#format-transfer option[value="both"]')).toBeDisabled();
  await captureSample(page);
  await transfer(page, "clear");
  await expect(page.locator('#format-transfer option[value="both"]')).toBeDisabled();
  await expect(page.locator("#document-save")).toBeDisabled();
});

test("Office caret character transfer styles future typing and has separate undo from adjacent content", async ({ page }) => {
  await transferFixture(page);
  await captureSample(page);
  await selectCharacters(page, 8, 29);
  await transfer(page, "characters");
  await expect(page.locator("#document-save")).toBeDisabled();
  await page.keyboard.type(" typed");
  await expect(officeEditor(page).locator("p").last().locator("span")).toHaveText(" typed");
  await officeEditor(page).press("Control+z");
  await expect(page.locator("#document-save")).toBeDisabled();
});

test("Office format transfer targets only selected cells and excludes code", async ({ page }) => {
  const first = await transferFixture(page);
  await captureSample(page);
  const cells = officeEditor(page).locator("td");
  await cells.first().click();
  await page.locator("#table-select").selectOption("cell");
  await transfer(page, "both");
  await expect(cells.first().locator("span")).toHaveText("First cell");
  await expect(cells.last().locator("span")).toHaveCount(0);
  await expectParagraphStyle(cells.first().locator("p"), SAMPLE_PARAGRAPH);
  await officeEditor(page).locator("pre").click();
  await expect(page.locator('#format-transfer option[value="copy"]')).toBeDisabled();
  await expect(page.locator('#format-transfer option[value="both"]')).toBeDisabled();
  const next = await saveOffice(page, { objectId: first.document.object_id });
  expect(next.content.content[6]).toEqual(first.content.content[6]);
  expect(next.content.content[5].content[0].content[1]).toEqual(first.content.content[5].content[0].content[1]);
});

test("Office paragraph-only transfer preserves pending character choices at the caret", async ({ page }) => {
  await transferFixture(page);
  await captureSample(page);
  await selectCharacters(page, 8, 29);
  await applyCharacters(page, { size: 18, color: "green" });
  await transfer(page, "paragraphs");
  await page.keyboard.type(" pending");
  const last = officeEditor(page).locator("p").last();
  await expect(last.locator("span")).toHaveText(" pending");
  await expect(last.locator("span")).toHaveAttribute("data-office-font-size", "18");
  await expect(last.locator("span")).toHaveAttribute("data-office-text-color", "green");
  await expectParagraphStyle(last, SAMPLE_PARAGRAPH);
  await officeEditor(page).press("Control+z");
  await expect(last.locator("span")).toHaveCount(0);
  await expectParagraphStyle(last, SAMPLE_PARAGRAPH);
  await officeEditor(page).press("Control+z");
  await expect(page.locator("#document-save")).toBeDisabled();
});

test("Office format samples reset on document reload and context change and stay unavailable to readers", async ({ page, context }) => {
  const first = await transferFixture(page);
  await captureSample(page);
  await page.locator("#document-reload").click();
  await expect(page.locator("#format-sample")).toHaveText("Noch kein Format aufgenommen.");
  await expect(page.locator('#format-transfer option[value="both"]')).toBeDisabled();
  await setOfficeAcl(page, first.document.object_id);
  const reader = await context.newPage();
  await openOffice(reader, { baseUrl: BLOCKED_BASE_URL, userId: OFFICE_READER_ID, roleIds: "office-reader" });
  await openOfficeDocument(reader, first.document.object_id);
  await expect(reader.locator("#format-transfer")).toBeDisabled();
  await captureSample(page);
  const changed = page.waitForResponse((response) => new URL(response.url()).pathname === OFFICE_PATH && response.request().method() === "GET");
  await page.evaluate(() => {
    document.querySelector("#user-id").value = "work-assignee-e2e";
    document.querySelector("#role-ids").value = "office-reader";
    document.querySelector("#context-form").dispatchEvent(new Event("submit", { bubbles: true, cancelable: true }));
  });
  expect((await changed).status()).toBe(200);
  await expect(page.locator("#format-sample")).toHaveText("Noch kein Format aufgenommen.");
  expect(await officeVersions(page, first.document.object_id)).toHaveLength(1);
});

test("Office rejects format transfer beyond the canonical byte limit without changing the draft", async ({ page }) => {
  const document = { type: "doc", content: [
    { type: "paragraph", attrs: SAMPLE_PARAGRAPH, content: [{ type: "text", text: "Source", marks: SAMPLE_MARKS }] },
    paragraph("Padding"), ...Array.from({ length: 100 }, () => paragraph("Target")),
  ] };
  const asciiBytes = (value) => JSON.stringify(value).replace(/[^\x00-\x7f]/g, (character) => `\\u${character.charCodeAt(0).toString(16).padStart(4, "0")}`).length;
  document.content[1].content[0].text += "界".repeat(Math.floor((399700 - asciiBytes(document)) / 6));
  expect(asciiBytes(document)).toBeGreaterThan(399600);
  expect(asciiBytes(document)).toBeLessThan(400000);
  const first = await transferFixture(page, document);
  const original = await officeEditor(page).innerHTML();
  await captureSample(page);
  await selectParagraphBlocks(page, 2, 101);
  await transfer(page, "both");
  await expect(page.locator("#document-notice")).toContainText("überschreitet");
  expect(await officeEditor(page).innerHTML()).toBe(original);
  await expect(page.locator("#document-save")).toBeDisabled();
  expect(await officeVersions(page, first.document.object_id)).toHaveLength(1);
});
