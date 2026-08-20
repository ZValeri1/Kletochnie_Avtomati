import { expect, test } from "@playwright/test";

test("renders the reproducible ideal 2D lattice", async ({ page }) => {
  await page.goto("/");
  await expect(
    page.getByRole("heading", { name: "2D: вид сверху" }),
  ).toBeVisible();
  await expect(page.getByText("Энтропия S(N)")).toBeVisible();
  await expect(page).toHaveScreenshot("ui_2d_ideal.png", {
    animations: "disabled",
    fullPage: true,
  });
});

test("creates requested internal and surface defects from the form", async ({
  page,
}) => {
  await page.goto("/");
  await page.getByLabel("Внутренние дефекты").fill("2");
  await page.getByLabel("Поверхностные дефекты").fill("1");
  await page.getByRole("button", { name: "Создать модель" }).click();

  await expect(
    page.getByText("Вакансии").locator("..").getByText("3"),
  ).toBeVisible();
  await expect(page.locator(".metrics div").filter({ hasText: /^Дефекты6$/ })).toBeVisible();
});

test("moves a 2D atom by dragging it in edit mode", async ({ page }) => {
  await page.goto("/");
  await page.getByRole("spinbutton", { name: "X", exact: true }).fill("5");
  await page.getByRole("spinbutton", { name: "Y", exact: true }).fill("5");
  await page.getByRole("button", { name: "Создать модель" }).click();
  await page.getByRole("button", { name: "Редактирование" }).click();

  const box = await page.locator("canvas.scene-2d").boundingBox();
  if (!box) throw new Error("2D canvas is not available");
  const step = Math.min((box.width - 60) / 4, (box.height - 60) / 4);
  const x = box.x + (box.width - step * 4) / 2;
  const y = box.y + (box.height - step * 4) / 2;
  await page.mouse.move(x, y);
  await page.mouse.down();
  await page.mouse.move(x + step / 2, y + step / 2);
  await page.mouse.up();

  await expect(page.getByText(/manual_move/)).toBeVisible();
});

test("keeps simulation controls directly after model creation", async ({ page }) => {
  await page.goto("/");
  const create = await page.getByRole("button", { name: "Создать модель" }).boundingBox();
  const simulation = await page.getByRole("heading", { name: "Симуляция" }).boundingBox();
  const parameters = await page.getByRole("heading", { name: "Параметры системы" }).boundingBox();
  if (!create || !simulation || !parameters) throw new Error("Control panels are not visible");

  expect(simulation.y).toBeGreaterThan(create.y);
  expect(simulation.y).toBeLessThan(parameters.y);
});

test("renders the 3D lattice with interactive rotation canvas", async ({
  page,
}) => {
  await page.goto("/");
  await page.locator("select").first().selectOption("3d");
  await page.getByRole("button", { name: "Создать модель" }).click();
  await expect(
    page.getByRole("heading", { name: "3D: перетаскивайте для вращения" }),
  ).toBeVisible();
  await expect(page.locator("canvas").first()).toBeVisible();
  await expect(page).toHaveScreenshot("ui_3d_lattice.png", {
    animations: "disabled",
    fullPage: true,
    maxDiffPixelRatio: 0.03,
  });
});
