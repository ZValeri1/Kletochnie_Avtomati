import type { RenderFrame } from "./snapshotMapper";

export function physicalPosition2D(frame: RenderFrame, x: number, y: number, interstitial: boolean): boolean {
  const inside = (px: number, py: number): boolean => {
    const polygon = frame.metal_contour;
    if (!polygon?.length) {
      return px >= frame.metal_origin[0] && py >= frame.metal_origin[1] &&
        px <= frame.metal_origin[0] + frame.metal_dimensions[0] - 1 &&
        py <= frame.metal_origin[1] + frame.metal_dimensions[1] - 1;
    }
    let result = false;
    for (let i = 0, j = polygon.length - 1; i < polygon.length; j = i++) {
      const [ax, ay] = polygon[j];
      const [bx, by] = polygon[i];
      if ((ax === bx && px === ax && py >= Math.min(ay, by) && py <= Math.max(ay, by)) ||
          (ay === by && py === ay && px >= Math.min(ax, bx) && px <= Math.max(ax, bx))) return true;
      if ((ay > py) !== (by > py) && px < ((bx - ax) * (py - ay)) / (by - ay) + ax) result = !result;
    }
    return result;
  };
  return inside(x, y) || (interstitial && [-0.5, 0.5].some(dx => [-0.5, 0.5].some(dy => inside(x + dx, y + dy))));
}
