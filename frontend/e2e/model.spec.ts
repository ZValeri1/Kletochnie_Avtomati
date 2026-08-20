import { expect, test } from "@playwright/test";

test("renders the reproducible ideal 2D lattice", async ({ page }) => {
  await page.goto("/");
  await expect(page.getByRole("heading", { name: "2D: вид сверху" })).toBeVisible();
  await expect(page.getByText("Энтропия S(N)")).toBeVisible();
  await expect(page).toHaveScreenshot("ui_2d_ideal.png", { animations: "disabled", fullPage: true });
});

test("renders the 3D lattice with interactive rotation canvas", async ({ page }) => {
  await page.goto("/");
  await page.locator("select").first().selectOption("3d");
  await page.getByRole("button", { name: "Создать модель" }).click();
  await expect(page.getByRole("heading", { name: "3D: перетаскивайте для вращения" })).toBeVisible();
  await expect(page.locator("canvas").first()).toBeVisible();
  await expect(page).toHaveScreenshot("ui_3d_lattice.png", { animations: "disabled", fullPage: true, maxDiffPixelRatio: 0.03 });
});
