import { expect, test } from "@playwright/test";

test("compute badge reports GPU and refreshes after CPU fallback", async ({ page }) => {
  let failed = false;
  await page.route("**/api/compute", async (route) => {
    await route.fulfill({ json: failed
      ? { backend: "cpu", device_name: "NVIDIA test", reason: "CUDA device lost" }
      : { backend: "cuda", device_name: "NVIDIA test", reason: null } });
  });
  await page.goto("/");
  const badge = page.getByTestId("compute-status");
  await expect(badge).toHaveText("GPU · NVIDIA test");
  failed = true;
  await expect(badge).toHaveText("CPU · резервный расчёт", { timeout: 10000 });
  await expect(badge).toHaveAttribute("title", "CUDA device lost");
});
