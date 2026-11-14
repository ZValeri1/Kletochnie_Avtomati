/** Keep endpoints and each bucket's extremes; full data remains in the store/export. */
export function samplePlot<T>(points: T[], value: (point: T) => number, limit = 1000): T[] {
  if (points.length <= limit) return points;
  const result = [points[0]];
  const buckets = Math.max(1, Math.floor((limit - 2) / 2));
  for (let bucket = 0; bucket < buckets; bucket++) {
    const start = 1 + Math.floor((bucket * (points.length - 2)) / buckets);
    const end = 1 + Math.floor(((bucket + 1) * (points.length - 2)) / buckets);
    let min = start;
    let max = start;
    for (let i = start + 1; i < end; i++) {
      if (value(points[i]) < value(points[min])) min = i;
      if (value(points[i]) > value(points[max])) max = i;
    }
    result.push(points[Math.min(min, max)]);
    if (min !== max) result.push(points[Math.max(min, max)]);
  }
  result.push(points[points.length - 1]);
  return result;
}
