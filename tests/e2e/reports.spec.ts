import { expect, test } from "@playwright/test";

test("rename queue entries and export only the current session, including a pending blur save", async ({
  page,
  request,
}) => {
  await page.goto("/");
  await expect(page.getByTestId("export-session-report")).toBeDisabled();
  // A run elsewhere on the same server must not enter this browser session's report.
  const other = await request.post("/api/simulations", {
    data: { dimensions: [2, 2] },
  });
  const otherId = (await other.json()).simulation_id;
  try {
    await page.getByTestId("create-simulation").click();
    await page.getByTestId("create-simulation").click();
    const rows = page.getByTestId("simulation-row");
    await expect(rows).toHaveCount(2);
    const firstName = rows.nth(0).getByTestId("simulation-name");
    await firstName.dblclick();
    await rows
      .nth(0)
      .getByTestId("simulation-name-input")
      .fill("Контрольный образец");
    await rows.nth(0).getByTestId("simulation-name-input").press("Enter");
    await expect(firstName).toHaveText("Контрольный образец");
    await firstName.dblclick();
    await rows
      .nth(0)
      .getByTestId("simulation-name-input")
      .fill("Отменить это имя");
    await rows.nth(0).getByTestId("simulation-name-input").press("Escape");
    await expect(firstName).toHaveText("Контрольный образец");
    const secondName = rows.nth(1).getByTestId("simulation-name");
    await secondName.dblclick();
    await rows
      .nth(1)
      .getByTestId("simulation-name-input")
      .fill("Облучённый образец");
    // Save deliberately responds slowly: clicking Export triggers blur, and export must wait.
    let renameComplete = false;
    await page.route("**/api/simulations/*/name", async (route) => {
      const response = await route.fetch();
      await new Promise((resolve) => setTimeout(resolve, 200));
      renameComplete = true;
      await route.fulfill({ response });
    });
    let exportedIds: string[] = [];
    await page.route("**/api/simulations/report.zip", async (route) => {
      expect(renameComplete).toBe(true);
      exportedIds = route.request().postDataJSON().simulation_ids;
      await route.continue();
    });
    const downloaded = page.waitForEvent("download");
    await page.getByTestId("export-session-report").click();
    const result = await downloaded;
    expect(result.suggestedFilename()).toBe("session-report.zip");
    expect(await result.failure()).toBeNull();
    expect(exportedIds).toHaveLength(2);
    expect(exportedIds).not.toContain(otherId);
    await expect(secondName).toHaveText("Облучённый образец");
    const journal = await request.get(
      `/api/simulations/${exportedIds[1]}/journal.json`,
    );
    expect((await journal.json()).name).toBe("Облучённый образец");
  } finally {
    await request.delete(`/api/simulations/${otherId}?expected_revision=0`);
  }
});

test("download trial and series reports from the workspace", async ({
  page,
}) => {
  await page.goto("/");
  await page.getByTestId("create-simulation").click();
  await expect(page.getByTestId("selected-simulation")).toHaveAttribute(
    "data-revision",
    "0",
  );
  await page
    .getByTestId("workspace-tabs")
    .getByRole("tab", { name: "Проекты" })
    .click();
  const trialDownload = page.waitForEvent("download");
  await page.getByTestId("export-report").click();
  const trial = await trialDownload;
  expect(trial.suggestedFilename()).toMatch(/^simulations-.*-report\.zip$/);
  expect(await trial.failure()).toBeNull();
  await page
    .getByTestId("workspace-tabs")
    .getByRole("tab", { name: "Эксперименты" })
    .click();
  const panel = page.getByTestId("experiment-panel");
  await panel.getByLabel("Повторы").fill("1");
  await panel.getByLabel("Акты", { exact: true }).fill("0");
  await panel.getByRole("button", { name: "Запустить серию" }).click();
  await expect(page.getByTestId("export-experiment-report")).toBeEnabled();
  const seriesDownload = page.waitForEvent("download");
  await page.getByTestId("export-experiment-report").click();
  const series = await seriesDownload;
  expect(series.suggestedFilename()).toMatch(/^experiments-.*-report\.zip$/);
  expect(await series.failure()).toBeNull();
});
