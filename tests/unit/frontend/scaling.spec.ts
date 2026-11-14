import { expect, test } from "@playwright/test";
import { samplePlot } from "../../../src/metrics/samplePlot";

test("long plots preserve endpoints and extrema without huge SVGs", () => {
  const points = Array.from({ length: 200_000 }, (_, i) => ({ i, value: Math.sin(i) }));
  points[73_245].value = 100;
  points[154_666].value = -100;
  const sampled = samplePlot(points, (point) => point.value);
  expect(sampled.length).toBeLessThanOrEqual(1000);
  expect(sampled[0]).toBe(points[0]);
  expect(sampled.at(-1)).toBe(points.at(-1));
  expect(sampled).toContain(points[73_245]);
  expect(sampled).toContain(points[154_666]);
  expect(sampled.every((point, i) => i === 0 || point.i > sampled[i - 1].i)).toBe(true);
});
