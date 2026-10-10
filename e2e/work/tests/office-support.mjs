import { expect } from "@playwright/test";

import { BASE_URL, TENANT_ID, installContext } from "./support.mjs";

export const OFFICE_PATH = "/v1/office/documents";
export const OFFICE_EDITOR_ID = "work-office-editor-e2e";
export const OFFICE_READER_ID = "work-reader-e2e";
export const OFFICE_HEADERS = {
  "X-Tenant-Id": TENANT_ID, "X-User-Id": OFFICE_EDITOR_ID, "X-Role-Ids": "office-editor",
};
export const OFFICE_READER_HEADERS = {
  "X-Tenant-Id": TENANT_ID, "X-User-Id": OFFICE_READER_ID, "X-Role-Ids": "office-reader",
};
export const officeContentPath = (id) => `${OFFICE_PATH}/${encodeURIComponent(id)}/content`;
export const officeDictationPath = (id) => `${OFFICE_PATH}/${encodeURIComponent(id)}/voice/dictations`;
export const officeReadAloudPath = (id) => `${OFFICE_PATH}/${encodeURIComponent(id)}/voice/read-aloud-preparations`;
export const officeEditor = (page) => page.locator("#office-editor .tiptap");
export const textDocument = (text) => ({ type: "doc", content: [{ type: "paragraph", content: [{ type: "text", text }] }] });

export async function installSyntheticSpeechRecognition(page) {
  await page.addInitScript(() => {
    const state = { current: null };
    class SyntheticSpeechRecognition {
      constructor() { state.current = this; this.lang = "de-DE"; this.continuous = false; this.interimResults = true; }
      start() { this.started = true; }
      stop() { this.started = false; queueMicrotask(() => this.onend?.()); }
      abort() { this.started = false; }
    }
    window.SpeechRecognition = SyntheticSpeechRecognition;
    window.__officeSyntheticDictation = {
      emit(transcript, isFinal = true) {
        const result = { 0: { transcript }, length: 1, isFinal };
        state.current?.onresult?.({ results: [result] });
      },
    };
  });
}

export async function installSyntheticSpeechSynthesis(page, { localService = true } = {}) {
  await page.addInitScript(({ local }) => {
    const listeners = new Map(), state = { current: null, spoken: [], cancellations: 0 };
    class SyntheticSpeechSynthesisUtterance {
      constructor(text) { this.text = text; this.lang = ""; this.rate = 1; this.voice = null; }
    }
    const voice = { name: "Synthetic local voice", lang: "de-DE", localService: local, default: true, voiceURI: "synthetic" };
    const synthesis = {
      getVoices: () => [voice],
      speak(utterance) { state.current = utterance; state.spoken.push({ text: utterance.text, lang: utterance.lang, rate: utterance.rate, localService: utterance.voice?.localService === true }); },
      cancel() { state.cancellations += 1; state.current = null; },
      addEventListener(type, listener) { const entries = listeners.get(type) || []; entries.push(listener); listeners.set(type, entries); },
    };
    Object.defineProperty(window, "SpeechSynthesisUtterance", { configurable: true, value: SyntheticSpeechSynthesisUtterance });
    Object.defineProperty(window, "speechSynthesis", { configurable: true, value: synthesis });
    window.__officeSyntheticSpeechSynthesis = {
      state,
      finish() { const current = state.current; state.current = null; current?.onend?.(); },
      fail() { const current = state.current; state.current = null; current?.onerror?.({ error: "synthetic" }); },
    };
  }, { local: localService });
}

export async function captureOfficeResponse(page, matches, { method = "GET", extraHeaders = {} } = {}) {
  let complete;
  const received = new Promise((resolve) => { complete = resolve; });
  await page.route(matches, async (route) => {
    if (route.request().method() !== method) return route.fallback();
    // Capture the real upstream bytes without depending on Chromium retaining a
    // streamed no-store error body. Never generate a response or retry a write.
    const response = await route.fetch({ headers: { ...route.request().headers(), ...extraHeaders }, maxRetries: 0, maxRedirects: 0 });
    const body = await response.body();
    const result = { status: response.status(), headers: response.headers(), json: JSON.parse(body.toString("utf8")) };
    await route.fulfill({ response, body });
    complete(result);
  }, { times: 1 });
  return { received };
}

export async function openOffice(page, { baseUrl = BASE_URL, userId = OFFICE_EDITOR_ID, roleIds = "office-editor", readableObjectIds = "" } = {}) {
  await installContext(page, { userId, roleIds, readableObjectIds });
  const pending = page.waitForResponse((response) => new URL(response.url()).pathname === OFFICE_PATH && response.request().method() === "GET");
  await page.goto(`${baseUrl}/office`);
  const response = await pending;
  expect(response.status()).toBe(200);
  expect(response.headers()["cache-control"]).toContain("no-store");
  await expect(page.locator("#documents-refresh")).toBeEnabled();
  return response.json();
}

export async function newOfficeDraft(page, title, { text, template = "blank", classification = "internal" } = {}) {
  const control = await page.locator("#welcome-new").isVisible() ? "#welcome-new" : "#document-new";
  await page.locator(control).click();
  await page.locator('#new-document-form input[name="title"]').fill(title);
  await page.locator('#new-document-form select[name="information_classification"]').selectOption(classification);
  await page.locator(`#new-document-form input[value="${template}"]`).check();
  await page.locator('#new-document-form button[type="submit"]').click();
  await expect(officeEditor(page)).toHaveAttribute("contenteditable", "true");
  if (text !== undefined) await officeEditor(page).fill(text);
}

export async function saveOffice(page, { status = 200, objectId = null, extraHeaders = {} } = {}) {
  await page.locator("#document-save").click();
  await expect(page.locator("#save-dialog")).toBeVisible();
  await expect(page.locator("#save-submit")).toBeDisabled();
  await page.locator("#save-confirm").check();
  const path = objectId ? `${OFFICE_PATH}/${objectId}/versions` : OFFICE_PATH;
  const captured = status >= 400 ? await captureOfficeResponse(page, (url) => url.pathname === path, { method: "POST", extraHeaders }) : null;
  const pending = page.waitForResponse((response) => new URL(response.url()).pathname === path && response.request().method() === "POST");
  await page.locator("#save-submit").click();
  const response = await pending;
  expect(response.status()).toBe(status);
  expect(response.headers()["cache-control"]).toContain("no-store");
  const upstream = captured ? await captured.received : null;
  const result = upstream ? upstream.json : await response.json();
  if (upstream) {
    expect(upstream.status).toBe(status);
    expect(upstream.headers["cache-control"]).toContain("no-store");
    expect(result.detail).toEqual(expect.any(String));
    if (status === 409) expect(result.detail).toBe("The document has a newer or conflicting saved version");
    if (status === 503) expect(result.detail).toBe("Office storage unavailable");
  }
  await expect(page.locator("#save-dialog")).toBeHidden();
  if (status === 200) {
    expect(result.tenant_id).toBe(TENANT_ID);
    expect(result.document.object_id).toMatch(/^office-doc-[a-f0-9]{32}$/);
    expect(result.version.version_id).toMatch(/^office-version-[a-f0-9]{32}$/);
    expect(result.version.content_hash).toMatch(/^sha256:[a-f0-9]{64}$/);
    expect(result.version.source_write_receipt_hash).toMatch(/^sha256:[a-f0-9]{64}$/);
    expect(result.rag_indexing_allowed).toBe(false);
    expect(result.search_indexing_allowed).toBe(false);
    expect(result.audit_event_id).toBeTruthy();
    await expect(page.locator("#document-status")).toContainText("Gespeichert");
    await expect(page.locator("#document-version")).toContainText(result.version.version_id);
    await expect(page.locator("#document-save")).toBeDisabled();
  }
  return result;
}

export async function createOfficeDocument(page, title, text) {
  await newOfficeDraft(page, title, { text });
  return saveOffice(page);
}

export async function showDocumentList(page) {
  if (await page.locator("#documents-toggle").isVisible() && await page.locator("#documents-toggle").getAttribute("aria-expanded") !== "true") {
    await page.locator("#documents-toggle").click();
  }
}

export async function openOfficeDocument(page, objectId) {
  await showDocumentList(page);
  const pending = page.waitForResponse((response) => new URL(response.url()).pathname === officeContentPath(objectId));
  await page.locator(`[data-document-id="${objectId}"]`).click();
  const response = await pending;
  expect(response.status()).toBe(200);
  await expect(officeEditor(page)).toBeVisible();
  return response.json();
}

export async function dictateIntoOffice(page, objectId, transcript) {
  const button = page.locator("#dictation-push");
  await button.scrollIntoViewIfNeeded();
  await expect(button).toBeEnabled();
  await officeEditor(page).click();
  await page.keyboard.press("ControlOrMeta+End");
  await expect(button).toBeEnabled();
  const box = await button.boundingBox();
  expect(box).toBeTruthy();
  const pending = page.waitForResponse((response) =>
    new URL(response.url()).pathname === officeDictationPath(objectId) && response.request().method() === "POST");
  await page.mouse.move(box.x + box.width / 2, box.y + box.height / 2);
  await page.mouse.down();
  await expect(button).toHaveAttribute("aria-pressed", "true");
  await page.evaluate((value) => window.__officeSyntheticDictation.emit(value), transcript);
  await page.mouse.up();
  const response = await pending;
  expect(response.status()).toBe(200);
  expect(response.headers()["cache-control"]).toContain("no-store");
  const result = await response.json();
  expect(result.object_id).toBe(objectId);
  expect(result.activation_contract).toBe("explicit_push_to_talk");
  expect(result.recognition_adapter).toBe("browser_web_speech");
  expect(result.classification).toBe("voice_transcript");
  expect(result.transcript_hash).toMatch(/^sha256:[a-f0-9]{64}$/);
  expect(result.raw_audio_uploaded).toBe(false);
  expect(result.raw_audio_stored).toBe(false);
  expect(result.transcript_persisted).toBe(false);
  expect(result.document_changed).toBe(false);
  expect(result.requires_explicit_version_save).toBe(true);
  expect(result.ai_used).toBe(false);
  await expect(button).toHaveAttribute("aria-pressed", "false");
  await expect(page.locator("#dictation-status")).toContainText("Version noch nicht gespeichert");
  await expect(officeEditor(page)).toContainText(transcript);
  return result;
}

export async function readOfficeSelectionAloud(page, objectId) {
  const button = page.locator("#read-aloud");
  await officeEditor(page).selectText();
  await button.scrollIntoViewIfNeeded();
  await expect(button).toBeEnabled();
  const pending = page.waitForResponse((response) =>
    new URL(response.url()).pathname === officeReadAloudPath(objectId) && response.request().method() === "POST");
  await button.click();
  const response = await pending;
  expect(response.status()).toBe(200);
  expect(response.headers()["cache-control"]).toContain("no-store");
  const result = await response.json();
  expect(result.object_id).toBe(objectId);
  expect(result.activation_contract).toBe("explicit_read_aloud");
  expect(result.synthesis_adapter).toBe("client_local_tts");
  expect(result.source_text_hash).toMatch(/^sha256:[a-f0-9]{64}$/);
  expect(result.source_text_persisted).toBe(false);
  expect(result.audio_generated_by_server).toBe(false);
  expect(result.audio_uploaded).toBe(false);
  expect(result.audio_stored).toBe(false);
  expect(result.document_changed).toBe(false);
  expect(result.ai_used).toBe(false);
  await expect(button).toHaveAttribute("aria-pressed", "true");
  await expect(page.locator("#read-aloud-status")).toContainText("Audio bleibt flüchtig");
  return result;
}

export async function officeContent(page, objectId, { baseUrl = BASE_URL, headers = OFFICE_HEADERS, versionId = null } = {}) {
  const response = await page.request.get(`${baseUrl}${officeContentPath(objectId)}${versionId ? `?version_id=${versionId}` : ""}`, { headers });
  expect(response.status()).toBe(200);
  expect(response.headers()["cache-control"]).toContain("no-store");
  return response.json();
}

export async function officeVersions(page, objectId) {
  const response = await page.request.get(`${BASE_URL}${OFFICE_PATH}/${objectId}/versions`, { headers: OFFICE_HEADERS });
  expect(response.status()).toBe(200);
  return (await response.json()).versions;
}

export async function setOfficeAcl(page, objectId, { status = "active", creator = false } = {}) {
  const response = await page.request.post(`${BASE_URL}/v1/admin/authz/object-acl-entries`, {
    headers: { ...OFFICE_HEADERS, "X-Role-Ids": "security-admin" },
    data: {
      object_id: objectId, object_type: "office.document", acl_subject_type: "user",
      acl_subject_id: creator ? OFFICE_EDITOR_ID : OFFICE_READER_ID,
      permission: creator ? "admin" : "read", acl_version: 1, status,
      approval_reference: "test-fixture:work-e2e-office-acl", reason: "Synthetic isolated Office browser proof only",
    },
  });
  expect(response.status()).toBe(200);
}

export async function officeFeatures(page) {
  const response = await page.request.get(`${BASE_URL}/v1/platform/modules`, { headers: { ...OFFICE_HEADERS, "X-Role-Ids": "tenant-admin" } });
  expect(response.status()).toBe(200);
  return (await response.json()).modules.find((module) => module.module_id === "office_documents").enabled_features;
}

export async function setOfficeFeatures(page, features) {
  const response = await page.request.post(`${BASE_URL}/v1/admin/tenant-modules/office_documents/enable`, {
    headers: { ...OFFICE_HEADERS, "X-Role-Ids": "tenant-admin" },
    data: { enabled_features: features, approval_reference: "test-fixture:work-e2e-office-feature", reason: "Synthetic Office feature denial proof only" },
  });
  expect(response.status()).toBe(200);
  expect((await response.json()).enabled_features).toEqual(features);
}

export async function holdOfficeRead(page, objectId, { versionId = null } = {}) {
  let release;
  let started;
  let delivered;
  let settled;
  let interrupted = false;
  const gate = new Promise((resolve) => { release = resolve; });
  const ready = new Promise((resolve) => { started = resolve; });
  const delivery = new Promise((resolve) => { delivered = resolve; });
  const network = new Promise((resolve) => { settled = resolve; });
  const matches = (url) => url.pathname === officeContentPath(objectId) && url.searchParams.get("version_id") === versionId;
  const failed = (request) => {
    if (matches(new URL(request.url()))) { interrupted = true; settled(); }
  };
  const responded = (response) => {
    if (matches(new URL(response.url()))) response.finished().then(settled);
  };
  page.on("requestfailed", failed);
  page.on("response", responded);
  await page.route(matches, async (route) => {
    const response = await route.fetch();
    expect(response.status()).toBe(200);
    started();
    await gate;
    try { await route.fulfill({ response }); }
    catch (error) { if (!interrupted) throw error; }
    finally { delivered(); }
  }, { times: 1 });
  return { ready, release, async complete() {
    release();
    await Promise.all([delivery, network]);
    page.off("requestfailed", failed);
    page.off("response", responded);
    await page.evaluate(() => new Promise((resolve) => requestAnimationFrame(() => requestAnimationFrame(resolve))));
  } };
}

export async function createOfficeVersionPair(page, title, firstText = "Earlier saved wording", secondText = "Current saved wording") {
  const first = await createOfficeDocument(page, `${title} earlier`, firstText);
  await page.locator("#document-title").fill(`${title} current`);
  await officeEditor(page).fill(secondText);
  const second = await saveOffice(page, { objectId: first.document.object_id });
  return { first, second, objectId: first.document.object_id };
}

export async function openOfficeComparison(page) {
  if (!await page.locator("#history-tab").isVisible()) await page.locator("#inspector-toggle").click();
  await page.locator("#history-tab").click();
  await page.locator("#history-compare").click();
  await expect(page.locator("#compare-dialog")).toBeVisible();
  await expect(page.locator("#compare-left")).toBeEnabled();
  await expect(page.locator("#compare-right")).toBeEnabled();
  await expect(page.locator("#compare-load")).toBeEnabled();
}

export async function loadOfficeComparison(page, objectId, leftVersionId, rightVersionId) {
  await page.locator("#compare-left").selectOption(leftVersionId);
  await page.locator("#compare-right").selectOption(rightVersionId);
  const selected = [...new Set([leftVersionId, rightVersionId])];
  const pending = selected.map((versionId) => page.waitForResponse((response) => {
    const url = new URL(response.url());
    return url.pathname === officeContentPath(objectId) && url.searchParams.get("version_id") === versionId && response.request().method() === "GET";
  }));
  await page.locator("#compare-load").click();
  const responses = await Promise.all(pending);
  for (const response of responses) {
    expect(response.status()).toBe(200);
    expect(response.headers()["cache-control"]).toContain("no-store");
    const content = await response.json();
    expect(content.document.object_id).toBe(objectId);
    expect(selected).toContain(content.version.version_id);
  }
  await expect(page.locator("#compare-load")).toBeEnabled();
  await expect(page.locator("#compare-summary")).not.toHaveText("");
}

export async function observeStaleOfficeContent(page, text) {
  await page.evaluate((staleText) => {
    window.staleOfficeContent = false;
    new MutationObserver(() => {
      window.staleOfficeContent ||= document.querySelector("#office-editor").textContent.includes(staleText);
    }).observe(document.querySelector("#office-editor"), { subtree: true, childList: true, characterData: true });
  }, text);
}
