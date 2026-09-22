import { expect, test } from "@playwright/test";

import { BASE_URL, BLOCKED_BASE_URL, monitorPage } from "./support.mjs";
import { createParagraphFixture, paragraph, paragraphWrites, richParagraphDocument } from "./paragraph-helper.mjs";
import {
  OFFICE_PATH, OFFICE_READER_ID, officeContent, officeEditor, officeVersions,
  openOffice, openOfficeDocument, saveOffice, setOfficeAcl,
} from "./office-support.mjs";

function keyboardDocument() {
  const document = richParagraphDocument();
  document.content.pop(); // Deliberately end in a table.
  document.content[0].attrs.textAlign = "center";
  document.content[0].content[0].marks = [{ type: "textStyle", attrs: { fontSize: 24, textColor: "blue" } }];
  return document;
}

async function fixture(page, document = keyboardDocument()) {
  const saved = await createParagraphFixture(page, "Synthetic whole-document keyboard", document);
  await openOffice(page);
  await openOfficeDocument(page, saved.document.object_id);
  return saved;
}

async function confirmReplacement(page) {
  await expect(page.locator("#table-remove-dialog")).toBeVisible();
  await expect(page.locator("#table-remove-cancel")).toBeFocused();
  await page.locator("#table-remove-confirm").click();
  await expect(page.locator("#table-remove-dialog")).toBeHidden();
  await expect(officeEditor(page)).toBeFocused();
}

async function paste(page, text) {
  await officeEditor(page).evaluate((editor, text) => {
    const clipboardData = new DataTransfer();
    clipboardData.setData("text/plain", text);
    clipboardData.setData("text/html", "<img src='https://keyboard.invalid/leak'>");
    editor.dispatchEvent(new ClipboardEvent("paste", { bubbles: true, cancelable: true, clipboardData }));
  }, text);
}

test("Office keyboard replacement confirms, cancels, undoes and saves rich documents without changing old versions", async ({ page }) => {
  const verify = monitorPage(page, { baseUrls: [BASE_URL] });
  const saved = await fixture(page);
  const writes = paragraphWrites(page, saved.document.object_id);
  const original = await officeEditor(page).innerHTML();
  const replacement = "Whole replacement Café 😀 <script>literal</script>";
  await officeEditor(page).press("Control+a");
  await page.keyboard.insertText(replacement);
  await expect(page.locator("#table-remove-dialog")).toBeVisible();
  expect(await officeEditor(page).innerHTML()).toBe(original);
  await expect(page.locator("#document-save")).toBeDisabled();
  await page.keyboard.press("Escape");
  await expect(officeEditor(page)).toBeFocused();
  expect(await officeEditor(page).innerHTML()).toBe(original);
  await page.keyboard.insertText(replacement);
  await confirmReplacement(page);
  await expect(officeEditor(page)).toHaveText(replacement);
  await expect(officeEditor(page).locator("table,script,img,h2,strong,em,span")).toHaveCount(0);
  await page.keyboard.type(" after");
  await officeEditor(page).press("Control+z");
  await expect(officeEditor(page)).toHaveText(replacement);
  await officeEditor(page).press("Control+z");
  expect(await officeEditor(page).innerHTML()).toBe(original);
  await expect(page.locator("#document-save")).toBeDisabled();
  await officeEditor(page).press("Control+Shift+z");
  await expect(officeEditor(page)).toHaveText(replacement);
  await expect(page.locator("#table-remove-dialog")).toBeHidden();
  expect(writes).toEqual([]);
  const next = await saveOffice(page, { objectId: saved.document.object_id });
  expect(next.version.previous_version_id).toBe(saved.version.version_id);
  expect(next.content).toEqual({ type: "doc", content: [paragraph(replacement)] });
  expect(writes).toHaveLength(1);
  expect(writes[0].human_confirmation).toBe(true);
  expect((await officeContent(page, saved.document.object_id, { versionId: saved.version.version_id })).content).toEqual(saved.content);
  verify();
});

for (const key of ["Backspace", "Delete", "Enter"]) {
  test(`Office whole-document ${key} leaves an editable paragraph and undoes a table-only document`, async ({ page }) => {
    const saved = await fixture(page, { type: "doc", content: [keyboardDocument().content.at(-1)] });
    const original = await officeEditor(page).innerHTML();
    await officeEditor(page).locator("td").last().click();
    await page.keyboard.press("Control+a");
    await page.keyboard.press(key);
    await expect(page.locator("#table-remove-dialog")).toBeVisible();
    await page.locator("#table-remove-cancel").click();
    expect(await officeEditor(page).innerHTML()).toBe(original);
    await page.keyboard.press(key);
    await confirmReplacement(page);
    await expect(officeEditor(page).locator(":scope > p")).toHaveCount(1);
    await expect(officeEditor(page)).toHaveText("");
    await page.keyboard.type("New paragraph");
    await officeEditor(page).press("Control+z");
    await expect(officeEditor(page)).toHaveText("");
    await officeEditor(page).press("Control+z");
    expect(await officeEditor(page).innerHTML()).toBe(original);
    await expect(page.locator("#document-save")).toBeDisabled();
    expect(await officeVersions(page, saved.document.object_id)).toHaveLength(1);
  });
}

test("Office whole-document paste keeps multiline literal text and replaces multiple tables in one undo step", async ({ page }) => {
  const document = keyboardDocument();
  document.content.unshift(structuredClone(document.content.at(-1)));
  await fixture(page, document);
  const original = await officeEditor(page).innerHTML();
  await officeEditor(page).press("Control+a");
  await paste(page, "First <img src=x>\r\n\r\nCafé 😀\n");
  await confirmReplacement(page);
  await expect(officeEditor(page).locator("p")).toHaveText(["First <img src=x>", "", "Café 😀", ""]);
  await expect(officeEditor(page).locator("table,img")).toHaveCount(0);
  await officeEditor(page).press("Control+z");
  expect(await officeEditor(page).innerHTML()).toBe(original);
});

test("Office whole-document input rejects character, canonical-byte and control limits before confirmation", async ({ page }) => {
  await fixture(page);
  const original = await officeEditor(page).innerHTML();
  for (const text of ["x".repeat(100001), "😀".repeat(40000), "Forbidden\u0001control"]) {
    await officeEditor(page).press("Control+a");
    await paste(page, text);
    await expect(page.locator("#document-notice")).toContainText("überschreitet");
    await expect(page.locator("#table-remove-dialog")).toBeHidden();
    expect(await officeEditor(page).innerHTML()).toBe(original);
    await expect(page.locator("#document-save")).toBeDisabled();
  }
  await page.keyboard.insertText("Valid after rejected input");
  await confirmReplacement(page);
  await expect(officeEditor(page)).toHaveText("Valid after rejected input");
});

test("Office whole-document cut copies plain text and confirms before removing tables", async ({ page }) => {
  await fixture(page);
  const original = await officeEditor(page).innerHTML();
  await officeEditor(page).press("Control+a");
  const clipboard = await officeEditor(page).evaluate((editor) => {
    const clipboardData = new DataTransfer();
    const allowed = editor.dispatchEvent(new ClipboardEvent("cut", { bubbles: true, cancelable: true, clipboardData }));
    return { allowed, text: clipboardData.getData("text/plain"), types: clipboardData.types };
  });
  expect(clipboard.allowed).toBe(false);
  expect(clipboard.types).toEqual(["text/plain"]);
  expect(clipboard.text).toContain("First cell");
  expect(await officeEditor(page).innerHTML()).toBe(original);
  await confirmReplacement(page);
  await expect(officeEditor(page)).toHaveText("");
  await officeEditor(page).press("Control+z");
  expect(await officeEditor(page).innerHTML()).toBe(original);
});

test("Office full selection works from a middle table with Meta A and real typed keys", async ({ page }) => {
  const document = keyboardDocument();
  document.content.push(paragraph("Final paragraph"));
  await fixture(page, document);
  await officeEditor(page).locator("td").first().click();
  await page.keyboard.press("Meta+a");
  await page.keyboard.press("R");
  await confirmReplacement(page);
  await page.keyboard.type("eplacement");
  await expect(officeEditor(page)).toHaveText("Replacement");
});

test("Office whole-document replacement stays disabled in reader and historical views", async ({ page, context }) => {
  const saved = await fixture(page);
  await setOfficeAcl(page, saved.document.object_id);
  const reader = await context.newPage();
  await openOffice(reader, { baseUrl: BLOCKED_BASE_URL, userId: OFFICE_READER_ID, roleIds: "office-reader" });
  await openOfficeDocument(reader, saved.document.object_id);
  const assertReadOnly = async (target) => {
    const original = await officeEditor(target).innerHTML();
    await expect(officeEditor(target)).toHaveAttribute("contenteditable", "false");
    await officeEditor(target).press("Control+a");
    await target.keyboard.press("Delete");
    await paste(target, "Denied replacement");
    await expect(target.locator("#table-remove-dialog")).toBeHidden();
    expect(await officeEditor(target).innerHTML()).toBe(original);
    await expect(target.locator("#document-save")).toBeDisabled();
  };
  await assertReadOnly(reader);
  await officeEditor(page).locator("h2").click();
  await page.keyboard.press("End");
  await page.keyboard.type(" current");
  await saveOffice(page, { objectId: saved.document.object_id });
  await page.locator("#history-tab").click();
  await page.locator(`[data-version-id="${saved.version.version_id}"]`).click();
  await assertReadOnly(page);
  expect(await officeVersions(page, saved.document.object_id)).toHaveLength(2);
});

test("Office context changes invalidate pending whole-document replacement", async ({ page }) => {
  const saved = await fixture(page);
  const writes = paragraphWrites(page, saved.document.object_id);
  await officeEditor(page).press("Control+a");
  await page.keyboard.insertText("Pending replacement");
  await expect(page.locator("#table-remove-dialog")).toBeVisible();
  const changed = page.waitForResponse((response) => new URL(response.url()).pathname === OFFICE_PATH && response.request().method() === "GET");
  await page.evaluate(() => {
    document.querySelector("#user-id").value = "work-assignee-e2e";
    document.querySelector("#role-ids").value = "office-reader";
    document.querySelector("#context-form").dispatchEvent(new Event("submit", { bubbles: true, cancelable: true }));
  });
  expect((await changed).status()).toBe(200);
  await expect(page.locator("#table-remove-dialog")).toBeHidden();
  await expect(page.locator("#office-editor")).toHaveText("");
  await page.locator("#table-remove-confirm").dispatchEvent("click");
  expect(writes).toEqual([]);
  expect((await officeContent(page, saved.document.object_id)).content).toEqual(saved.content);
});
