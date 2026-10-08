import { expect, test } from "@playwright/test";
import { randomUUID } from "node:crypto";

test("2D: create, step and display the new revision and metrics", async ({
  page,
}) => {
  await page.goto("/");
  await page.getByTestId("dimension-mode").selectOption("2d");
  await page.getByTestId("create-simulation").click();
  const selected = page.getByTestId("selected-simulation");
  await expect(selected).toHaveAttribute("data-revision", "0");

  await page.getByTestId("step-simulation").click();

  await expect(selected).toHaveAttribute("data-revision", "1");
  await page
    .getByTestId("workspace-tabs")
    .getByRole("tab", { name: "Графики" })
    .click();
  await expect(page.getByTestId("simulation-metrics")).toBeVisible();
  await expect(page.getByTestId("renderer-2d")).toBeVisible();
});

test("3D: accepted snapshot produces an interactive Three.js scene", async ({
  page,
}) => {
  await page.goto("/");
  await page.getByTestId("dimension-mode").selectOption("3d");
  await page.getByTestId("create-simulation").click();

  await expect(page.getByTestId("renderer-3d").locator("canvas")).toBeVisible();
  await expect(page.getByTestId("selected-simulation")).toHaveAttribute(
    "data-revision",
    "0",
  );
});

test("parallel simulations stay visually frozen until their final paused frame", async ({
  page,
}) => {
  await page.goto("/");
  await page.getByTestId("create-simulation").click();
  await page.getByTestId("create-simulation").click();
  const rows = page.getByTestId("simulation-row");
  await expect(rows).toHaveCount(2);

  await rows.nth(0).getByTestId("run-simulation").click();
  await rows.nth(1).getByTestId("run-simulation").click();
  await rows.nth(0).getByTestId("pause-simulation").click();
  await expect(rows.nth(0)).toHaveAttribute("data-status", "PAUSED");
  const pausedRevision = Number(
    await rows.nth(0).getAttribute("data-revision"),
  );
  const runningRevision = Number(
    await rows.nth(1).getAttribute("data-revision"),
  );

  await page.waitForTimeout(250);
  expect(Number(await rows.nth(1).getAttribute("data-revision"))).toBe(
    runningRevision,
  );
  expect(Number(await rows.nth(0).getAttribute("data-revision"))).toBe(
    pausedRevision,
  );
  await rows.nth(1).getByTestId("pause-simulation").click();
  await expect(rows.nth(1)).toHaveAttribute("data-status", "PAUSED");
  expect(
    Number(await rows.nth(1).getAttribute("data-revision")),
  ).toBeGreaterThan(runningRevision);
});

test("run mode is explicit, fast mode streams graphs, and visual mode can be restored", async ({
  page,
}) => {
  await page.goto("/");
  await page.getByTestId("create-simulation").click();

  await page.getByTestId("run-mode-fast").check();
  await page.getByTestId("run-selected-simulation").click();
  await expect(page.getByTestId("fast-mode-overlay")).toBeVisible();
  await expect(
    page.getByTestId("metrics-panel").locator("circle.physical-point").first(),
  ).toBeVisible();

  await page.getByTestId("pause-selected-simulation").click();
  await expect(page.getByTestId("fast-mode-overlay")).toBeHidden();
  await page.getByTestId("run-mode-visual").check();
  await page.getByTestId("run-selected-simulation").click();
  await expect(page.getByTestId("renderer-2d")).toBeVisible();
  await expect(page.getByTestId("fast-mode-overlay")).toBeHidden();
  await page.getByTestId("pause-selected-simulation").click();
});

test("project save/load restores a simulation and journal export is a browser download", async ({
  page,
}) => {
  const projectName = `e2e-${randomUUID()}`;
  await page.goto("/");
  await page.getByTestId("create-simulation").click();
  await page.getByTestId("step-simulation").click();
  await expect(page.getByTestId("selected-simulation")).toHaveAttribute(
    "data-revision",
    "1",
  );
  const revision = await page
    .getByTestId("selected-simulation")
    .getAttribute("data-revision");

  await page
    .getByTestId("workspace-tabs")
    .getByRole("tab", { name: "Проекты" })
    .click();
  await page.getByTestId("project-name").fill(projectName);
  await page.getByTestId("save-project").click();
  page.once("dialog", (dialog) => dialog.accept());
  await page.getByTestId("remove-simulation").click();
  await expect(page.getByTestId("selected-simulation")).toBeHidden();
  await page.getByTestId("load-project").click();
  await expect(page.getByTestId("selected-simulation")).toHaveAttribute(
    "data-revision",
    revision!,
  );

  const [download] = await Promise.all([
    page.waitForEvent("download"),
    page.getByTestId("export-journal").click(),
  ]);
  expect(download.suggestedFilename()).toContain("journal.json");
});

test("P7: explicit 2D configuration is controllable and observable through the panel", async ({
  page,
}) => {
  await page.goto("/");
  await page.getByTestId("dimension-x").fill("4");
  await page.getByTestId("dimension-y").fill("4");
  await page
    .getByTestId("initialization-mode")
    .selectOption("explicit_defective");
  await page.getByTestId("initial-vacancies").fill("1");
  await page.getByTestId("seed-init").fill("41");
  await page.getByTestId("seed-sim").fill("42");
  await page.getByTestId("create-simulation").click();

  const selected = page.getByTestId("selected-simulation");
  await expect(selected).toHaveAttribute("data-status", "PREPARATION");
  await page
    .getByTestId("workspace-tabs")
    .getByRole("tab", { name: "Графики" })
    .click();
  await expect(page.getByTestId("metric-n-v")).toContainText("1");

  await page.getByTestId("start-simulation").click();
  await expect(selected).toHaveAttribute("data-status", "PAUSED");
  await page.getByTestId("step-simulation").click();
  await expect(selected).toHaveAttribute("data-revision", "1");
  await page
    .getByTestId("workspace-tabs")
    .getByRole("tab", { name: "Журнал" })
    .click();
  await expect(page.getByTestId("journal-row")).toHaveCount(1);

  await page.getByTestId("undo-simulation").click();
  await expect(page.getByTestId("redo-simulation")).toBeEnabled();
  await page.getByTestId("redo-simulation").click();
  await page
    .getByTestId("workspace-tabs")
    .getByRole("tab", { name: "Графики" })
    .click();
  await expect(page.getByTestId("metrics-panel")).toBeVisible();
});

test("P7: mobile workspace keeps controls visible and exposes research tools as tabs", async ({
  page,
}) => {
  await page.setViewportSize({ width: 390, height: 844 });
  await page.goto("/");
  await page.getByTestId("create-simulation").click();

  await expect(page.getByTestId("selected-simulation")).toBeVisible();
  await expect(page.getByTestId("step-simulation")).toBeVisible();
  const tabs = page.getByTestId("workspace-tabs");
  await expect(tabs).toBeVisible();

  await tabs.getByRole("tab", { name: "Проекты" }).click();
  await expect(page.getByTestId("project-panel")).toBeVisible();
  await expect(page.getByTestId("export-panel")).toBeVisible();

  await tabs.getByRole("tab", { name: "Эксперименты" }).click();
  await expect(page.getByTestId("experiment-panel")).toBeVisible();
  expect(
    await page.evaluate(
      () => document.documentElement.scrollWidth <= window.innerWidth,
    ),
  ).toBe(true);
});

test("P7: cancelling an experiment loads the completed partial results", async ({
  page,
}) => {
  const aggregate = {
    count: 1,
    mean: 2,
    minimum: 2,
    maximum: 2,
    p50: 2,
    p95: 2,
    confidence_interval: [2, 2],
    ci_informative: false,
  };
  await page.route("**/api/experiments", async (route) => {
    await route.fulfill({
      contentType: "application/json",
      body: JSON.stringify({
        schema_version: 1,
        experiment_id: "experiment-cancel",
        status: "PENDING",
        completed_steps: 0,
        total_steps: 5,
        successful_runs: 0,
        failed_runs: 0,
      }),
    });
  });
  await page.route(
    "**/api/experiments/experiment-cancel/cancel",
    async (route) => {
      await route.fulfill({
        contentType: "application/json",
        body: JSON.stringify({
          schema_version: 1,
          experiment_id: "experiment-cancel",
          status: "CANCELLED",
          completed_steps: 1,
          total_steps: 5,
          successful_runs: 1,
          failed_runs: 0,
        }),
      });
    },
  );
  await page.route(
    "**/api/experiments/experiment-cancel/results",
    async (route) => {
      await route.fulfill({
        contentType: "application/json",
        body: JSON.stringify({
          schema_version: 1,
          experiment_id: "experiment-cancel",
          status: "CANCELLED",
          completed_steps: 1,
          total_steps: 5,
          successful_runs: [],
          failed_runs: [],
          aggregate: {
            schema_version: 1,
            bootstrap_seed: 99,
            final: { d: aggregate },
            by_act: { "1": { d: aggregate } },
          },
          master_seed: 42,
          bootstrap_seed: 99,
        }),
      });
    },
  );

  await page.goto("/");
  await page.getByTestId("create-simulation").click();
  await page
    .getByTestId("workspace-tabs")
    .getByRole("tab", { name: "Эксперименты" })
    .click();
  const experiment = page.getByTestId("experiment-panel");
  await experiment.getByRole("button", { name: "Запустить серию" }).click();
  await experiment
    .getByRole("button", { name: "Отменить", exact: true })
    .click();

  await expect(experiment).toContainText("Отменена");
  await expect(experiment).toContainText("Агрегаты по актам");
  await expect(experiment).toContainText("Акт 1");
});
