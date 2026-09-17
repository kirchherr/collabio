import path from "node:path";

import { test, expect } from "@playwright/test";

import {
  ARTIFACT_DIR,
  BASE_URL,
  HTTP_NOT_FOUND_CONSOLE_ERROR,
  USER_ID,
  installContext,
  monitorPage,
  openView,
  switchContext,
  waitForWorkspace,
} from "./support.mjs";

test("reassignment and correction-resubmission complete through the real API", async ({ page }) => {
  const run = `${Date.now()}`;
  const taskTitle = `E2E Aufgabe ${run}`;
  const projectReference = `project:e2e-${run}`;
  await installContext(page);
  const assertClean = monitorPage(page, {
    baseUrls: [BASE_URL],
    expectedConsoleErrors: [HTTP_NOT_FOUND_CONSOLE_ERROR],
  });

  await page.goto(`${BASE_URL}/work`);
  await waitForWorkspace(page, 6);

  await openView(page, "tasks");
  await page.locator('[data-view-panel="tasks"] [data-open-dialog="task-dialog"]').click();
  await page.locator('#task-form input[name="title"]').fill(taskTitle);
  await page.locator('#task-form input[name="assigned_principal_id"]').fill(USER_ID);
  await page.locator('#task-form button[type="submit"]').click();

  const taskRow = page.locator("#task-list .task-row").filter({ hasText: taskTitle });
  await expect(taskRow).toBeVisible();
  await taskRow.locator("[data-task-amendment]").click();
  await page.locator('#task-amendment-form input[name="target_assigned_principal_id"]').fill("work-assignee-e2e");
  await page.locator('#task-amendment-form input[name="target_due_at_utc"]').fill("2026-09-18T12:30");
  page.once("dialog", (dialog) => dialog.accept());
  await page.locator('#task-amendment-form button[type="submit"]').click();
  await expect(taskRow).toContainText("work-assignee-e2e");
  await expect(page.locator("#task-activity-list")).toContainText("Zuweisung oder Termin aktualisiert");

  await openView(page, "time");
  await page.locator('[data-view-panel="time"] [data-open-dialog="time-dialog"]').click();
  await page.locator('#time-form input[name="started_at_utc"]').fill("2026-09-17T08:00");
  await page.locator('#time-form input[name="ended_at_utc"]').fill("2026-09-17T09:00");
  await page.locator('#time-form input[name="project_reference"]').fill(projectReference);
  await page.locator('#time-form input[name="worker_principal_id"]').fill(USER_ID);
  await page.locator('#time-form button[type="submit"]').click();

  const timeRow = page.locator("#time-entry-list .time-row").filter({ hasText: projectReference });
  await expect(timeRow).toBeVisible();
  await timeRow.locator("[data-time-approval]").click();
  await expect(page.locator('#time-approval-form select[name="decision"]')).toHaveValue("submitted|submit");
  await page.locator('#time-approval-form button[type="submit"]').click();
  await expect(timeRow).toContainText("Eingereicht");

  await switchContext(page, { userId: "work-approver-e2e", roleIds: "time-approver" });
  await expect(timeRow).toBeVisible();
  await timeRow.locator("[data-time-approval]").click();
  await page
    .locator('#time-approval-form select[name="decision"]')
    .selectOption("correction_requested|request_correction");
  page.once("dialog", (dialog) => dialog.accept());
  await page.locator('#time-approval-form button[type="submit"]').click();
  await expect(timeRow).toContainText("Korrektur");

  await switchContext(page, { userId: USER_ID, roleIds: "time-worker" });
  await expect(timeRow).toBeVisible();
  await timeRow.locator("[data-time-correction]").click();
  await page.locator('#time-correction-form input[name="ended_at_utc"]').fill("2026-09-17T09:30");
  await page.locator('#time-correction-form button[type="submit"]').click();
  await expect(timeRow).toContainText("1 h 30 min");

  await timeRow.locator("[data-time-approval]").click();
  await expect(page.locator('#time-approval-form select[name="decision"]')).toHaveValue("submitted|submit");
  await page.locator('#time-approval-form button[type="submit"]').click();
  await expect(timeRow).toContainText("Eingereicht");

  const persisted = await page.evaluate(async ({ title, project }) => {
    const context = JSON.parse(window.localStorage.getItem("collabio.workspace.context") || "{}");
    const headers = {
      "X-Tenant-Id": context.tenantId,
      "X-User-Id": context.userId,
      "X-Role-Ids": context.roleIds,
      "X-Readable-Object-Ids": context.readableObjectIds,
    };
    const [tasksResponse, entriesResponse, approvalsResponse] = await Promise.all([
      fetch("/v1/tasks/items", { headers }),
      fetch("/v1/time-tracking/entries", { headers }),
      fetch("/v1/time-tracking/approvals", { headers }),
    ]);
    const [tasks, entries, approvals] = await Promise.all([
      tasksResponse.json(),
      entriesResponse.json(),
      approvalsResponse.json(),
    ]);
    const task = tasks.items.find((item) => item.title === title);
    const entry = entries.entries.find((item) => item.project_reference === project);
    const approval = approvals.approvals.find((item) => item.entry_object_id === entry?.object_id);
    return { task, entry, approval };
  }, { title: taskTitle, project: projectReference });

  expect(persisted.task.assigned_principal_id).toBe("work-assignee-e2e");
  expect(persisted.entry.revision_no).toBe(1);
  expect(persisted.entry.duration_minutes).toBe(90);
  expect(persisted.approval.approval_state).toBe("submitted");
  await page.screenshot({ path: path.join(ARTIFACT_DIR, "work-workflows-complete.png"), fullPage: true });
  assertClean();
});
