import { expect } from "@playwright/test";

export const BASE_URL = process.env.WORK_E2E_BASE_URL || "http://work-e2e-api:8000";
export const BLOCKED_BASE_URL = process.env.WORK_E2E_BLOCKED_BASE_URL || "http://work-e2e-blocked-api:8000";
export const ARTIFACT_DIR = process.env.WORK_E2E_ARTIFACT_DIR || "/tmp/work-e2e-artifacts";
export const TENANT_ID = "tenant-work-e2e";
export const USER_ID = "work-user-e2e";
export const HTTP_LOCKED_CONSOLE_ERROR =
  "Failed to load resource: the server responded with a status of 423 (Locked)";
export const HTTP_UNAVAILABLE_CONSOLE_ERROR =
  "Failed to load resource: the server responded with a status of 503 (Service Unavailable)";

export const resources = {
  tasks: {
    label: "Aufgaben",
    path: "/v1/tasks/items",
    collection: "items",
    view: "tasks",
    errorSelector: "#task-list",
    group: "Aufgaben",
    token: "Synthetic E2E task",
    items: [
      {
        object_id: "task-synthetic-state",
        task_number: "TASK-E2E-STATE",
        title: "Synthetic E2E task",
        priority: "high",
        assigned_principal_id: USER_ID,
        due_at_utc: "2026-09-18T12:00:00Z",
        lifecycle_state: "assigned",
      },
    ],
  },
  taskActivities: {
    label: "Aktivitaeten",
    path: "/v1/tasks/activities",
    collection: "activities",
    view: "tasks",
    errorSelector: "#task-activity-list",
    group: "Aufgaben",
    token: "Synthetic E2E activity",
    items: [
      {
        object_id: "task-activity-synthetic-state",
        task_object_id: "task-synthetic-state",
        activity_number: "TASK-ACT-E2E-STATE",
        summary: "Synthetic E2E activity",
        activity_type: "created",
        occurred_at_utc: "2026-09-17T08:00:00Z",
      },
    ],
  },
  timeEntries: {
    label: "Zeit",
    path: "/v1/time-tracking/entries",
    collection: "entries",
    view: "time",
    errorSelector: "#time-entry-list",
    group: "Zeiterfassung",
    token: "project:synthetic-state",
    items: [
      {
        object_id: "time-entry-synthetic-state",
        entry_number: "TIME-E2E-STATE",
        worker_principal_id: USER_ID,
        work_date: "2026-09-17",
        started_at_utc: "2026-09-17T08:00:00Z",
        ended_at_utc: "2026-09-17T09:00:00Z",
        duration_minutes: 60,
        project_reference: "project:synthetic-state",
        cost_center_reference: "cost-center:synthetic-state",
        revision_no: 0,
      },
    ],
  },
  timeApprovals: {
    label: "Freigaben",
    path: "/v1/time-tracking/approvals",
    collection: "approvals",
    view: "time",
    errorSelector: null,
    group: "Zeiterfassung",
    token: "Nicht eingereicht",
    items: [
      {
        object_id: "time-approval-synthetic-state",
        entry_object_id: "time-entry-synthetic-state",
        approval_number: "TIME-APPROVAL-E2E-STATE",
        approval_state: "not_submitted",
        worker_principal_id: USER_ID,
      },
    ],
  },
  tickets: {
    label: "Tickets",
    path: "/v1/tickets",
    collection: "tickets",
    view: "tickets",
    errorSelector: "#ticket-list",
    group: "Tickets",
    token: "Synthetic E2E ticket",
    items: [
      {
        ticket_id: "ticket-synthetic-state",
        ticket_number: "TKT-E2E-STATE",
        subject_redacted: "Synthetic E2E ticket",
        priority: "normal",
        owner_principal_id: USER_ID,
        ticket_status: "open",
        sla_state: "on_track",
      },
    ],
  },
  knowledge: {
    label: "Wissen",
    path: "/v1/kb/articles",
    collection: "articles",
    view: "knowledge",
    errorSelector: "#knowledge-list",
    group: "Wissen",
    token: "Synthetic E2E knowledge",
    items: [
      {
        object_id: "kb-synthetic-state",
        article_key: "KB-E2E-STATE",
        title: "Synthetic E2E knowledge",
        current_version_label: "v1",
        status: "published",
        updated_at_utc: "2026-09-17T08:00:00Z",
      },
    ],
  },
  crm: {
    label: "Kontakte",
    path: "/v1/crm/accounts",
    collection: "accounts",
    view: "crm",
    errorSelector: "#crm-list",
    group: "CRM",
    token: "Synthetic E2E account",
    items: [
      {
        object_id: "crm-account-synthetic-state",
        display_name: "Synthetic E2E account",
        account_number: "CRM-E2E-STATE",
        account_kind: "customer",
        owner_principal_id: USER_ID,
        status: "active",
      },
    ],
  },
};

export async function installContext(page, overrides = {}) {
  const context = {
    tenantId: TENANT_ID,
    userId: USER_ID,
    roleIds: "tenant-admin",
    readableObjectIds: "",
    ...overrides,
  };
  await page.addInitScript((value) => {
    window.localStorage.setItem("collabio.workspace.context", JSON.stringify(value));
  }, context);
}

export function monitorPage(page, { baseUrls, expectedConsoleErrors = [] }) {
  const allowedHosts = new Set(baseUrls.map((value) => new URL(value).host));
  const consoleErrors = [];
  const pageErrors = [];
  const externalRequests = [];
  page.on("console", (message) => {
    if (message.type() === "error") {
      consoleErrors.push(message.text());
    }
  });
  page.on("pageerror", (error) => pageErrors.push(error.message));
  page.on("request", (request) => {
    const url = new URL(request.url());
    if (["http:", "https:"].includes(url.protocol) && !allowedHosts.has(url.host)) {
      externalRequests.push(request.url());
    }
  });
  return () => {
    const unexpectedConsoleErrors = [...consoleErrors];
    for (const expectedError of expectedConsoleErrors) {
      const index = unexpectedConsoleErrors.indexOf(expectedError);
      expect(index, `expected browser console error: ${expectedError}`).toBeGreaterThanOrEqual(0);
      unexpectedConsoleErrors.splice(index, 1);
    }
    expect(unexpectedConsoleErrors, "unexpected browser console errors").toEqual([]);
    expect(pageErrors, "uncaught page errors").toEqual([]);
    expect(externalRequests, "unexpected browser network requests").toEqual([]);
  };
}

export function responseBody(resource, items) {
  return {
    tenant_id: TENANT_ID,
    [resource.collection]: items,
    audit_event_id: "audit-event-work-e2e-state",
  };
}

export async function installResourceRoutes(page, states = {}) {
  const calls = Object.fromEntries(Object.keys(resources).map((key) => [key, 0]));
  for (const [key, resource] of Object.entries(resources)) {
    await page.route(`**${resource.path}`, async (route) => {
      if (route.request().method() !== "GET") {
        await route.continue();
        return;
      }
      calls[key] += 1;
      const state = states[key] || { kind: "empty" };
      if (state.kind === "blocked") {
        await route.fulfill({
          status: 423,
          contentType: "application/json",
          body: JSON.stringify({ detail: `synthetic_${key}_blocked` }),
        });
        return;
      }
      if (state.kind === "unavailable") {
        await route.fulfill({
          status: 503,
          contentType: "application/json",
          body: JSON.stringify({ detail: `synthetic_${key}_unavailable` }),
        });
        return;
      }
      const items = state.kind === "ready" ? resource.items : [];
      await route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify(responseBody(resource, items)),
      });
    });
  }
  return calls;
}

export async function waitForWorkspace(page, readyCount) {
  await expect(page.locator("#sync-line")).toContainText(`${readyCount}/7 Bereiche bereit`);
}

export async function openView(page, view) {
  await page.locator(`[data-view="${view}"]`).click();
  await expect(page.locator(`[data-view-panel="${view}"]`)).toHaveClass(/active/);
}

export function availabilityItem(page, label) {
  return page.locator(".availability-item").filter({ has: page.locator("strong", { hasText: label }) });
}

export async function switchContext(page, { userId, roleIds }) {
  await page.locator("#context-button").click();
  await page.locator("#user-id").fill(userId);
  await page.locator("#role-ids").fill(roleIds);
  await page.locator('#context-form button[type="submit"]').click();
  await expect(page.locator("#context-panel")).toBeHidden();
  await expect(page.locator("#refresh-button")).toBeEnabled();
}
