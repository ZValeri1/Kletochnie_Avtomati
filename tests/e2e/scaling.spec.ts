import { expect, test } from "@playwright/test";

test("million-atom lattice runs headless, pauses and exports its complete journal", async ({ page, request }) => {
  test.setTimeout(60_000);
  const errors: string[] = [];
  page.on("pageerror", (error) => errors.push(error.message));
  await page.goto("/");
  await page.getByTestId("dimension-x").fill("1000");
  await page.getByTestId("dimension-y").fill("1000");
  const creation = page.waitForResponse((response) => response.url().endsWith("/api/simulations") && response.request().method() === "POST");
  await page.getByTestId("create-simulation").click();
  const id = (await (await creation).json()).simulation_id;
  try {
    await expect(page.getByTestId("sampled-render-notice")).toBeVisible();
    await expect(page.getByTestId("metric-n-correct")).toContainText("1000000");
    await page.getByTestId("run-mode-fast").check();
    await page.getByTestId("run-selected-simulation").click();
    await expect(page.getByTestId("fast-mode-overlay")).toBeVisible();
    await expect.poll(async () => {
      const response = await request.get(`/api/simulations/${id}/events?offset=0&limit=1`);
      return response.ok() ? (await response.json()).total : 0;
    }, { timeout: 20_000 }).toBeGreaterThan(2000);
    await page.getByTestId("pause-selected-simulation").click();
    await expect(page.getByTestId("fast-mode-overlay")).toBeHidden();
    const response = await request.get(`/api/simulations/${id}/journal.json`);
    expect(response.ok()).toBe(true);
    const journal = await response.json();
    expect(journal.events.length).toBeGreaterThan(2000);
    expect(journal.metrics.length).toBe(journal.events.length + 1);
    expect(journal.final_snapshot.render_sampled).toBe(true);
    expect(journal.final_snapshot.atoms.length).toBeLessThan(10000);
    expect(journal.configuration.dimensions).toEqual([1000, 1000]);
    const download = page.waitForEvent("download");
    await page.getByTestId("export-session-report").click();
    expect(await (await download).failure()).toBeNull();
    expect(errors).toEqual([]);
  } finally {
    await request.delete(`/api/simulations/${id}`);
  }
});
