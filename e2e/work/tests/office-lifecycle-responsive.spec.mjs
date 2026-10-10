import { expect, test } from "@playwright/test";

import { BASE_URL, monitorPage } from "./support.mjs";
import { createOfficeDocument, officeEditor, openOffice } from "./office-support.mjs";

test("Office lifecycle explains draft, collaboration, saved version and closed record transitions", async ({ page }, testInfo) => {
  test.setTimeout(60000);
  const verify = monitorPage(page, { baseUrls: [BASE_URL] });
  await openOffice(page);
  const saved = await createOfficeDocument(page, `Synthetic lifecycle ${testInfo.project.name}`, "Saved lifecycle text");
  await expect(page.locator("#edit-lease-banner")).toContainText("Bearbeitung für diese Sitzung reserviert");
  await officeEditor(page).fill("Unsaved lifecycle draft");

  const lifecycle = page.waitForResponse((response) => {
    const url = new URL(response.url());
    return url.pathname === `/v1/office/documents/${saved.document.object_id}/lifecycle` && response.request().method() === "GET";
  });
  const preflight = page.waitForResponse((response) => {
    const url = new URL(response.url());
    return url.pathname === `/v1/office/documents/${saved.document.object_id}/collaboration/preflight` && response.request().method() === "POST";
  });
  const gatewayPreflight = page.waitForResponse((response) => {
    const url = new URL(response.url());
    return url.pathname === `/v1/office/documents/${saved.document.object_id}/collaboration/gateway-preflight` && response.request().method() === "POST";
  });
  const parserPlan = page.waitForResponse((response) => {
    const url = new URL(response.url());
    return url.pathname === "/v1/office/documents/parser-worker-plan" && response.request().method() === "GET";
  });
  await page.locator("#document-lifecycle").click();
  expect((await lifecycle).status()).toBe(200);
  const preflightResponse = await preflight;
  expect(preflightResponse.status()).toBe(200);
  const preflightBody = await preflightResponse.json();
  expect(preflightBody.contract_state).toBe("prepared_runtime_closed");
  expect(preflightBody.transport_state).toBe("websocket_not_admitted");
  expect(preflightBody.runtime_admitted).toBe(false);
  expect(preflightBody.target_concurrent_editors).toBe(50);
  expect(preflightBody.raw_session_or_client_id_persisted).toBe(false);
  const gatewayResponse = await gatewayPreflight;
  expect(gatewayResponse.status()).toBe(200);
  const gatewayBody = await gatewayResponse.json();
  expect(gatewayBody.gateway_contract_state).toBe("prepared_upgrade_closed");
  expect(gatewayBody.upgrade_state).toBe("http_upgrade_not_admitted");
  expect(gatewayBody.required_subprotocol).toBe("collabio-office-crdt.v1");
  expect(gatewayBody.server_accepts_connections).toBe(false);
  expect(gatewayBody.credential_issued).toBe(false);
  expect(gatewayBody).not.toHaveProperty("ticket");
  expect(gatewayBody).not.toHaveProperty("socket_url");
  const parserPlanResponse = await parserPlan;
  expect(parserPlanResponse.status()).toBe(200);
  const parserPlanBody = await parserPlanResponse.json();
  expect(parserPlanBody.plan_state).toBe("planned_dispatch_closed");
  expect(parserPlanBody.worker_profile_id).toBe("rich-document-parser-worker:1");
  expect(parserPlanBody.dispatch_allowed).toBe(false);
  expect(parserPlanBody.production_admitted).toBe(false);
  expect(parserPlanBody.content_accepted_by_plan_endpoint).toBe(false);
  await expect(page.locator("#lifecycle-dialog")).toBeVisible();
  await expect(page.locator("#lifecycle-draft")).toContainText("ungespeicherte Änderungen vorhanden");
  await expect(page.locator("#lifecycle-collaborative")).toContainText("für diese Sitzung reserviert");
  await expect(page.locator("#lifecycle-live-collaboration")).toContainText("Runtime und WebSocket bleiben geschlossen");
  await expect(page.locator("#lifecycle-live-collaboration")).toContainText("Restore-, Fuzzing- und Lastnachweise sind noch offen");
  await expect(page.locator("#lifecycle-websocket-gateway")).toContainText("Same-Origin, Subprotocol, Binärframes");
  await expect(page.locator("#lifecycle-websocket-gateway")).toContainText("HTTP-Upgrade, Zugangsticket und Verbindungen bleiben geschlossen");
  await expect(page.locator("#lifecycle-parser-worker")).toContainText("No-Network-, Read-only- und Non-root-Profil geplant");
  await expect(page.locator("#lifecycle-parser-worker")).toContainText("Dispatch und Produktion bleiben geschlossen");
  await expect(page.locator("#lifecycle-saved")).toContainText(saved.version.version_id);
  await expect(page.locator("#lifecycle-business")).toContainText("Übergang geschlossen");
  await expect(page.locator("#lifecycle-worm")).toContainText("kein WORM Evidence Record");
  await expect(page.locator("#lifecycle-status")).toContainText("AI darf keinen Business Record auslösen");
  await expect(officeEditor(page)).toContainText("Unsaved lifecycle draft");
  await page.locator("#lifecycle-done").click();
  await expect(page.locator("#lifecycle-dialog")).toBeHidden();
  verify();
});
